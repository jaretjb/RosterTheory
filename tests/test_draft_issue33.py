"""Synthetic legal-capacity and season-evidence cases for issue #33."""

from collections import defaultdict
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from roster_theory.cli import _load_draft_schedule, command_simulate
from roster_theory.core.errors import ScheduleIncomplete
from roster_theory.core.roster import draft_roster_fits
from roster_theory.draft.simulation import (
    DraftSeasonSchedule, Player, _can_draft, _policy_allows_draft,
    compare_strategies, deterministic_roster_strength, rank_user_candidates,
    snake_slot,
)
from roster_theory.draft.watcher import reconcile_draft_state, recommend_for_state
from roster_theory.presentation.draft_watcher import _format_recommendation_rows
from roster_theory.schedule_inputs import NFL_TEAMS
from tests.ma001_fixtures import draft_fixture, rules


SCHEDULE = DraftSeasonSchedule(2026, {team: 8 for team in NFL_TEAMS}, 17)


def player(number: int, position: str) -> Player:
    return Player(str(number), f"Synthetic {number}", position, 200.0, number, 20.0, number)


class DraftLegalCapacityTests(unittest.TestCase):
    def test_third_qb_is_slot_eligible_but_disfavored_by_draft_policy(self) -> None:
        slots = ("QB", "RB", "WR", "TE", "BN", "BN", "BN")
        roster = [player(1, "QB"), player(2, "QB")]
        third = player(3, "QB")
        self.assertTrue(_can_draft(third, roster, slots))
        self.assertFalse(_policy_allows_draft(third, roster, slots))
        self.assertFalse(_can_draft(third, roster, ("QB", "RB", "WR")))
        self.assertFalse(_can_draft(roster[0], roster, slots))
        ranked = rank_user_candidates(
            [third], roster, "vbd", 3, 2, 2, 1, slots, len(slots), {"QB": 100.0}
        )
        self.assertEqual(ranked[0]["player_name"], third.name)
        self.assertTrue(ranked[0]["draft_preference_override"])
        human = "\n".join(_format_recommendation_rows(ranked))
        self.assertIn("outside Draft acquisition preference", human)
        self.assertIn("Check Sleeper position limits", human)

    def test_independent_capacity_examples_cover_flex_bench_and_final_rosters(self) -> None:
        slots = ("QB", "RB", "WR", "TE", "FLEX", "BN", "BN", "K", "DST")
        final = ("QB", "RB", "WR", "TE", "RB", "QB", "WR", "K", "DST")
        self.assertTrue(draft_roster_fits(final, slots))
        self.assertFalse(draft_roster_fits((*final, "RB"), slots))
        self.assertFalse(draft_roster_fits(("QB", "QB", "QB"), ("QB", "RB", "BN")))
        self.assertFalse(draft_roster_fits(("TE", "TE"), ("TE", "WRRB_FLEX")))
        self.assertTrue(draft_roster_fits(("RB", "WR"), ("RB", "WRRB_FLEX")))

    def test_every_reference_snake_slot_finishes_with_a_slot_legal_roster(self) -> None:
        for profile, teams in (("reference_a", 10), ("reference_b", 12)):
            _, board = draft_fixture(profile)
            positions = tuple(rules(profile)["roster_positions"])
            self.assertEqual(len(positions), 15)
            for user_slot in range(1, teams + 1):
                with self.subTest(profile=profile, slot=user_slot):
                    result = compare_strategies(
                        board, teams, user_slot, positions, 15, trials=1,
                        seed=33, strategies=("scenario_safe",),
                        include_special_teams=True, include_trace=True,
                        availability_rates=(0.1,), availability_samples=2,
                        bench_weights=(0.2,), rank_weights=(0.0,),
                        season=2026, schedule=SCHEDULE,
                    )[0]
                    picks = result["trace"]["picks"]
                    self.assertEqual(len(picks), teams * 15)
                    rosters = defaultdict(list)
                    for row in picks:
                        self.assertEqual(row["draft_slot"], snake_slot(row["pick_no"], teams))
                        rosters[row["draft_slot"]].append(row["position"])
                    self.assertEqual(len({row["player_key"] for row in picks}), len(picks))
                    for roster in rosters.values():
                        self.assertEqual(len(roster), 15)
                        self.assertTrue(draft_roster_fits(roster, positions))
                    self.assertEqual(result["trace"]["starter_slots_filled"],
                                     result["trace"]["starter_slot_count"])

    def test_edit_and_undo_recompute_capacity_from_current_picks(self) -> None:
        draft = {"status": "drafting", "type": "snake", "metadata": {"scoring_type": "half_ppr"},
                 "settings": {"teams": 2, "rounds": 3, "slots_qb": 1, "slots_bn": 2}}

        def pick(number: int, slot: int, position: str, player_id: str | None = None) -> dict:
            return {"pick_no": number, "draft_slot": slot, "player_id": player_id or str(number),
                    "metadata": {"position": position}}

        first = [pick(1, 1, "QB"), pick(2, 2, "RB"), pick(3, 2, "WR"),
                 pick(4, 1, "QB"), pick(5, 1, "QB")]
        initial = reconcile_draft_state(draft, first, 1)
        self.assertTrue(draft_roster_fits(
            [row["metadata"]["position"] for row in initial.rosters[1]], ("QB", "BN", "BN")
        ))
        edited = reconcile_draft_state(draft, [*first[:-1], pick(5, 1, "RB", "replacement")], 1, initial)
        self.assertEqual(edited.transition, "edit")
        self.assertTrue(draft_roster_fits(
            [row["metadata"]["position"] for row in edited.rosters[1]], ("QB", "BN", "BN")
        ))
        undone = reconcile_draft_state(draft, first[:-1], 1, edited)
        self.assertEqual(undone.transition, "undo")
        self.assertTrue(draft_roster_fits(
            [row["metadata"]["position"] for row in undone.rosters[1]], ("QB", "BN", "BN")
        ))

    def test_invalid_live_roster_is_reported_without_a_pick_recommendation(self) -> None:
        draft = {"status": "drafting", "type": "snake", "metadata": {"scoring_type": "half_ppr"},
                 "settings": {"teams": 2, "rounds": 5, "slots_qb": 1,
                              "slots_rb": 1, "slots_wr": 1, "slots_te": 1,
                              "slots_wrrb_flex": 1}}
        board = [{"player_key": f"sleeper_id:{i}", "sleeper_id": str(i),
                  "player_name": f"Synthetic {i}", "position": "RB",
                  "projected_points": 200 - i, "adp": i, "vbd": 50 - i,
                  "rank_score": i} for i in range(1, 5)]
        picks = [{"pick_no": i, "draft_slot": 1, "player_id": str(i),
                  "metadata": {"position": "RB"}} for i in range(1, 4)]
        state = reconcile_draft_state(draft, picks, 1)
        result = recommend_for_state(state, draft, board)
        self.assertEqual(result["roster_legality"], "invalid")
        self.assertEqual(result["recommendations"], {})
        self.assertIn("cannot fit", result["reason"])


class DraftSeasonEvidenceTests(unittest.TestCase):
    def test_validated_synthetic_schedule_is_bound_to_its_declared_season(self) -> None:
        artifact = Path("tests/fixtures/provider/nfl_schedule.synthetic.json")
        with patch("roster_theory.cli.default_schedule_path", return_value=artifact):
            schedule = _load_draft_schedule(2099, "synthetic")
            self.assertEqual(schedule.season, 2099)
            self.assertEqual(schedule.bye_weeks["ARI"], 2)
            self.assertEqual(schedule.active_games, 1)
            with self.assertRaisesRegex(ScheduleIncomplete, "does not match"):
                _load_draft_schedule(2026, "synthetic")

    def test_missing_wrong_season_and_missing_team_schedules_fail_closed(self) -> None:
        roster = [Player("q", "Synthetic QB", "QB", 300.0, 1.0, 50.0, 1.0, team="CAR")]
        for season, schedule in ((None, None), (2026, None),
                                 (2026, DraftSeasonSchedule(2025, {"CAR": 5}, 17)),
                                 (2026, DraftSeasonSchedule(2026, {}, 17))):
            with self.subTest(season=season, schedule=schedule):
                with self.assertRaises(ScheduleIncomplete):
                    deterministic_roster_strength(
                        roster, ("QB",), {"QB": 100.0}, season=season, schedule=schedule
                    )
        with self.assertRaises(ScheduleIncomplete):
            compare_strategies([], 10, 1, ("QB",), 1, season=2026)

    def test_simulation_cli_rejects_missing_and_wrong_season_artifacts_before_board(self) -> None:
        args = SimpleNamespace(league="synthetic", snapshot=None, board="unused")
        snapshot = {"current": {"league": {"season": "2026", "total_rosters": 10}, "drafts": []}}
        wrong_season = Path("tests/fixtures/provider/nfl_schedule.synthetic.json")
        with TemporaryDirectory() as temporary:
            missing = Path(temporary) / "missing.json"
            with patch("roster_theory.cli.find_league_config", return_value={"user_draft_slot": 1}), \
                 patch("roster_theory.cli._load_snapshot", return_value=snapshot), \
                 patch("roster_theory.cli._load_board") as board:
                for path, message in ((missing, "missing"), (wrong_season, "does not match")):
                    with self.subTest(path=path), patch("roster_theory.cli.default_schedule_path", return_value=path):
                        with self.assertRaisesRegex(ScheduleIncomplete, message):
                            command_simulate(args)
                board.assert_not_called()
