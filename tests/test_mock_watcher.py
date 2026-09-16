import unittest
from unittest.mock import patch
from urllib.parse import urlsplit

from roster_theory.draft_analysis import HistoricalPositionCurves
from roster_theory.draft_preferences import DraftPreference, DraftPreferenceBook
from roster_theory.mock_watcher import (
    MockDraftWatcher,
    _compact_decision_signal,
    _construction_flags,
    _explain_leader,
    _format_preference_overlay,
    _preserve_planned_turn,
    format_mock_report,
    live_position_pace,
    parse_draft_id,
    policy_pair_for_scoring,
    reconcile_draft_state,
    recommend_for_state,
    room_survival_probabilities,
    resolve_draft_slot,
    roster_positions_from_draft,
    scoring_family,
)
from roster_theory.sleeper import SleeperClient
from roster_theory.simulation import Player


class MockWatcherTests(unittest.TestCase):
    @staticmethod
    def draft(*, status: str = "drafting") -> dict:
        return {
            "draft_id": "123456789012345678",
            "status": status,
            "draft_order": {"user-1": 1, "user-2": 2},
            "metadata": {"scoring_type": "std"},
            "settings": {
                "teams": 2,
                "rounds": 5,
                "pick_timer": 60,
                "slots_qb": 1,
                "slots_rb": 1,
                "slots_wr": 1,
                "slots_te": 1,
                "slots_wrrb_flex": 1,
            },
        }

    @staticmethod
    def pick(number: int, slot: int, player_id: str, position: str = "RB") -> dict:
        return {
            "pick_no": number,
            "draft_slot": slot,
            "player_id": player_id,
            "roster_id": slot,
            "metadata": {
                "first_name": f"Player{player_id}",
                "last_name": "Test",
                "position": position,
                "team": "CAR",
            },
        }

    @staticmethod
    def board() -> list[dict]:
        positions = ("RB", "WR", "QB", "TE")
        teams = ("CAR", "CIN", "BUF", "HOU")
        return [
            {
                "player_key": f"sleeper_id:{index}",
                "sleeper_id": str(index),
                "player_name": f"Player{index} Test",
                "position": positions[(index - 1) % 4],
                "team": teams[(index - 1) % 4],
                "projected_points": 300 - index,
                "adp": index,
                "vbd": 100 - index,
                "rank_score": index,
            }
            for index in range(1, 41)
        ]

    def test_parses_id_or_draftboard_url(self) -> None:
        draft_id = "123456789012345678"
        self.assertEqual(parse_draft_id(draft_id), draft_id)
        self.assertEqual(
            parse_draft_id(f"https://sleeper.com/draft/nfl/{draft_id}"), draft_id
        )
        with self.assertRaises(ValueError):
            parse_draft_id("not-a-draft")

    def test_detects_scoring_slot_and_roster_settings(self) -> None:
        draft = self.draft()
        self.assertEqual(scoring_family(draft), "standard")
        self.assertEqual(policy_pair_for_scoring("standard")[0], "standard_reconciled")
        self.assertEqual(
            policy_pair_for_scoring("half_ppr"),
            ("half_ppr_reconciled", "half_ppr_expert_ordered_curve"),
        )
        self.assertEqual(
            policy_pair_for_scoring(
                "half_ppr",
                teams=10,
                roster_positions=(
                    "QB",
                    "RB",
                    "RB",
                    "WR",
                    "WR",
                    "TE",
                    "WRRB_FLEX",
                ),
            ),
            (
                "half_ppr_reconciled_tol05",
                "half_ppr_expert_ordered_curve",
            ),
        )
        self.assertEqual(
            policy_pair_for_scoring("half_ppr", teams=12),
            ("half_ppr_reconciled", "half_ppr_expert_ordered_curve"),
        )
        self.assertEqual(
            policy_pair_for_scoring(
                "half_ppr",
                teams=12,
                roster_positions=(
                    "QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "FLEX"
                ),
            ),
            (
                "half_ppr_reconciled_horizon_guard",
                "half_ppr_expert_ordered_curve",
            ),
        )
        self.assertEqual(
            policy_pair_for_scoring(
                "half_ppr", teams=10, roster_positions=("QB", "QB", "TE")
            ),
            ("half_ppr_reconciled", "half_ppr_expert_ordered_curve"),
        )
        self.assertEqual(
            policy_pair_for_scoring(
                "half_ppr",
                teams=10,
                roster_positions=(
                    "QB",
                    "RB",
                    "RB",
                    "WR",
                    "WR",
                    "TE",
                    "WRRB_FLEX",
                    "WRRB_FLEX",
                ),
            ),
            ("half_ppr_reconciled", "half_ppr_expert_ordered_curve"),
        )
        self.assertEqual(resolve_draft_slot(draft, user_id="user-1"), 1)
        self.assertEqual(resolve_draft_slot(draft, claimed_slot=2), 2)
        self.assertEqual(
            roster_positions_from_draft(draft),
            ["QB", "RB", "WR", "TE", "WRRB_FLEX"],
        )

    def test_reconciles_duplicates_appends_edits_and_undos(self) -> None:
        draft = self.draft()
        first_picks = [self.pick(1, 1, "1"), self.pick(2, 2, "2")]
        first = reconcile_draft_state(draft, first_picks, 1)
        self.assertEqual(first.transition, "initial")
        self.assertFalse(first.is_user_turn)
        duplicate = reconcile_draft_state(draft, first_picks, 1, first)
        self.assertEqual(duplicate.transition, "duplicate")
        appended_picks = [*first_picks, self.pick(3, 2, "3")]
        appended = reconcile_draft_state(draft, appended_picks, 1, duplicate)
        self.assertEqual(appended.transition, "append")
        self.assertTrue(appended.is_user_turn)
        self.assertEqual(appended.current_pick, 4)
        self.assertEqual(appended.next_user_pick, 5)
        edited_picks = [*first_picks, self.pick(3, 1, "4")]
        edited = reconcile_draft_state(draft, edited_picks, 1, appended)
        self.assertEqual(edited.transition, "edit")
        self.assertEqual(edited.edited_pick_numbers, [3])
        undone = reconcile_draft_state(draft, first_picks, 1, edited)
        self.assertEqual(undone.transition, "undo")
        self.assertEqual(undone.removed_pick_numbers, [3])
        self.assertEqual(len(undone.rosters[1]), 1)

    def test_edit_rebuilds_player_availability_from_authoritative_picks(self) -> None:
        draft = self.draft()
        before_picks = [
            self.pick(1, 1, "1"),
            self.pick(2, 2, "2"),
            self.pick(3, 2, "3"),
        ]
        before = reconcile_draft_state(draft, before_picks, 1)
        before_report = recommend_for_state(before, draft, self.board(), limit=40)
        before_names = {
            row["player_name"]
            for rows in before_report["recommendations"].values()
            for row in rows
        }
        self.assertNotIn("Player3 Test", before_names)
        after_picks = [*before_picks[:2], self.pick(3, 2, "4")]
        after = reconcile_draft_state(draft, after_picks, 1, before)
        after_report = recommend_for_state(after, draft, self.board(), limit=40)
        after_names = {
            row["player_name"]
            for rows in after_report["recommendations"].values()
            for row in rows
        }
        self.assertIn("Player3 Test", after_names)
        self.assertNotIn("Player4 Test", after_names)

    def test_unmatched_user_pick_is_reported_not_silently_dropped(self) -> None:
        draft = self.draft()
        picks = [
            self.pick(1, 1, "999", "RB"),
            self.pick(2, 2, "2"),
            self.pick(3, 2, "3"),
        ]
        state = reconcile_draft_state(draft, picks, 1)
        report = recommend_for_state(state, draft, self.board())
        self.assertEqual(report["unmatched_user_picks"][0]["player_id"], "999")
        self.assertEqual(
            report["rank_reconciliation"]["rank_weights"], [0.0, 0.5, 1.0]
        )

    def test_watcher_preserves_raw_projection_but_values_player_on_expert_positional_curve(self) -> None:
        board = self.board()
        by_key = {row["player_key"]: row for row in board}
        by_key["sleeper_id:1"]["projected_points"] = 100
        by_key["sleeper_id:5"]["projected_points"] = 400
        state = reconcile_draft_state(self.draft(), [], 1)

        report = recommend_for_state(state, self.draft(), board, limit=40)
        rows = {
            row["player_key"]: row
            for policy_rows in report["recommendations"].values()
            for row in policy_rows
        }
        expert_first = rows["sleeper_id:1"]
        expert_later = rows["sleeper_id:5"]

        self.assertEqual(expert_first["raw_projected_points"], 100)
        self.assertEqual(expert_later["raw_projected_points"], 400)
        self.assertGreater(
            expert_first["position_curve_projected_points"],
            expert_later["position_curve_projected_points"],
        )
        self.assertEqual(
            report["rank_reconciliation"]["projection_value_method"],
            "expert_ordered_positional_projection_curve",
        )
        self.assertTrue(report["rank_reconciliation"]["raw_projections_preserved"])
        first_policy = report["policies"][0]
        first_row = report["recommendations"][first_policy][0]
        self.assertEqual(
            set(first_row["rank_adjusted_vorp"]), {"0.00", "0.50", "1.00"}
        )

    def test_watcher_labels_raw_and_adjusted_acquisition_adp(self) -> None:
        draft = self.draft()
        state = reconcile_draft_state(draft, [], 1)
        history = HistoricalPositionCurves(
            position_picks={
                "QB": (40, 44, 48, 52, 56, 60, 64, 68, 72, 76),
                "RB": (20, 24, 28, 32, 36, 40, 44, 48, 52, 56),
                "WR": (22, 26, 30, 34, 38, 42, 46, 50, 54, 58),
                "TE": (45, 50, 55, 60, 65, 70, 75, 80, 85, 90),
            },
            draft_end_pick=100,
            source="Sleeper fixture draft",
        )
        report = recommend_for_state(
            state,
            draft,
            self.board(),
            acquisition_history=history,
            history_weight=0.5,
        )

        self.assertEqual(report["acquisition_adp"]["history_weight"], 0.5)
        self.assertEqual(
            report["acquisition_adp"]["history_source"],
            "Sleeper fixture draft",
        )
        first_policy = report["policies"][0]
        first_row = report["recommendations"][first_policy][0]
        self.assertIn("adp", first_row)
        self.assertIn("acquisition_adp", first_row)
        self.assertIn("market_survival", first_row)
        self.assertIn("league_survival", first_row)
        self.assertNotEqual(first_row["adp"], first_row["acquisition_adp"])
        self.assertNotEqual(
            first_row["market_survival"], first_row["league_survival"]
        )

    def test_sleeper_cpu_mode_changes_only_acquisition_timing(self) -> None:
        draft = self.draft()
        state = reconcile_draft_state(draft, [], 1)
        snapshot = {
            "captured_at": 12345,
            "scoring": "standard",
            "adp_field": "adp_std",
            "source": {"endpoint": "https://example.test/projections"},
            "players": [
                {"player_id": str(index), "sleeper_adp": 41 - index}
                for index in range(1, 41)
            ],
        }

        report = recommend_for_state(
            state,
            draft,
            self.board(),
            limit=40,
            acquisition_mode="sleeper_cpu",
            sleeper_adp_snapshot=snapshot,
        )
        market_report = recommend_for_state(
            state,
            draft,
            self.board(),
            limit=40,
        )

        self.assertEqual(report["acquisition_adp"]["mode"], "sleeper_cpu")
        self.assertTrue(report["acquisition_adp"]["cpu_mock_only"])
        self.assertTrue(report["acquisition_adp"]["raw_adp_preserved"])
        self.assertEqual(report["acquisition_adp"]["coverage"], 1.0)
        visible = {
            row["player_key"]: row
            for rows in report["recommendations"].values()
            for row in rows
        }
        player = visible["sleeper_id:1"]
        market_visible = {
            row["player_key"]: row
            for rows in market_report["recommendations"].values()
            for row in rows
        }
        self.assertEqual(player["market_adp"], 1.0)
        self.assertEqual(player["cpu_expected_pick"], 40.0)
        self.assertEqual(player["acquisition_adp"], 40.0)
        self.assertEqual(player["raw_projected_points"], 299.0)
        for field in (
            "overall_expert_rank",
            "position_expert_rank",
            "raw_projected_points",
            "position_curve_projected_points",
        ):
            self.assertEqual(player[field], market_visible["sleeper_id:1"][field])
        self.assertEqual(
            report["replacement_baselines"], market_report["replacement_baselines"]
        )

        output = format_mock_report(
            {
                "draft_id": draft["draft_id"],
                "status": state.status,
                "scoring": state.scoring,
                "draft_slot": state.draft_slot,
                "current_pick": state.current_pick,
                "next_user_pick": state.next_user_pick,
                "is_user_turn": True,
                "transition": state.transition,
                "rosters": state.rosters,
                "recommendation": report,
            }
        )
        self.assertIn("SLEEPER CPU MOCK", output)
        self.assertIn("CPU Pick", output)
        self.assertIn("CPU Surv%", output)
        self.assertNotIn("Lg Pick", output)
        self.assertNotIn("Lg Surv%", output)

    def test_sleeper_cpu_mode_rejects_wrong_scoring_snapshot(self) -> None:
        state = reconcile_draft_state(self.draft(), [], 1)
        with self.assertRaisesRegex(ValueError, "snapshot scoring does not match"):
            recommend_for_state(
                state,
                self.draft(),
                self.board(),
                acquisition_mode="sleeper_cpu",
                sleeper_adp_snapshot={
                    "scoring": "half_ppr",
                    "adp_field": "adp_half_ppr",
                    "players": [{"player_id": "1", "sleeper_adp": 1}],
                },
            )

    def test_ten_team_half_ppr_watcher_uses_promoted_uncapped_primary(self) -> None:
        draft = self.draft()
        draft["settings"].update(
            {
                "teams": 10,
                "slots_rb": 2,
                "slots_wr": 2,
                "slots_wrrb_flex": 1,
            }
        )
        draft["metadata"]["scoring_type"] = "half_ppr"
        state = reconcile_draft_state(draft, [], 1)

        report = recommend_for_state(state, draft, self.board())

        self.assertEqual(
            report["policies"][0], "half_ppr_reconciled_tol05"
        )
        self.assertEqual(
            report["recommendations"][report["policies"][0]][0][
                "construction_policy"
            ],
            {},
        )

        poll_report = {
            "draft_id": draft["draft_id"],
            "status": state.status,
            "scoring": state.scoring,
            "draft_slot": state.draft_slot,
            "current_pick": state.current_pick,
            "next_user_pick": state.next_user_pick,
            "is_user_turn": True,
            "transition": state.transition,
            "rosters": state.rosters,
            "recommendation": report,
        }
        report["model_split"] = True
        report["room_timing_split"] = True
        output = format_mock_report(poll_report)
        self.assertIn("Market ADP", output)
        self.assertIn("Lg Pick", output)
        self.assertIn("Market Surv%", output)
        self.assertIn("Lg Surv%", output)
        self.assertNotIn("Lg%", output)
        self.assertIn("! MODEL SPLIT", output)
        self.assertIn("! ROOM TIMING SPLIT", output)

    def test_model_split_flags_only_a_changed_top_recommendation(self) -> None:
        draft = self.draft()
        state = reconcile_draft_state(draft, [], 1)
        history = HistoricalPositionCurves(
            position_picks={position: (20, 30, 40) for position in ("QB", "RB", "WR", "TE")},
            draft_end_pick=100,
            source="fixture",
        )
        call_count = 0

        def fake_rank(available, *_args, **_kwargs):
            nonlocal call_count
            call_count += 1
            # Each policy ranks room-aware league, generic league, then market.
            desired_key = "sleeper_id:2" if call_count == 3 else "sleeper_id:1"
            player = next(player for player in available if player.key == desired_key)
            return [
                {
                    "_player": player,
                    "player_name": player.name,
                    "position": player.position,
                    "final_score": 1.0,
                    "vona": 0.0,
                    "roster_need": "starter",
                    "next_pick": 4,
                    "next_pick_survival": 0.5,
                }
            ]

        with patch("roster_theory.mock_watcher.rank_user_candidates", side_effect=fake_rank):
            report = recommend_for_state(
                state,
                draft,
                self.board(),
                acquisition_history=history,
                history_weight=0.5,
            )

        self.assertTrue(report["model_split"])
        self.assertEqual(report["model_split_policies"], [report["policies"][0]])
        self.assertEqual(report["market_leaders"][report["policies"][0]], "Player2 Test")
        self.assertEqual(report["league_leaders"][report["policies"][0]], "Player1 Test")

    def test_exact_intervening_seats_lower_survival_for_qb_needy_teams(self) -> None:
        qb = Player.from_mapping(
            {
                "player_key": "qb",
                "player_name": "Available QB",
                "position": "QB",
                "projected_points": 250,
                "adp": 24,
                "vbd": 20,
                "rank_score": 8,
            }
        )
        roster_positions = ["QB", "RB", "WR", "TE", "FLEX"]
        empty_rosters = {slot: [] for slot in range(1, 5)}
        filled_rosters = {
            slot: [
                Player.from_mapping(
                    {
                        "player_key": f"qb-{slot}",
                        "player_name": f"Roster QB {slot}",
                        "position": "QB",
                        "projected_points": 240,
                        "adp": 20,
                        "vbd": 10,
                        "rank_score": 10,
                    }
                )
            ]
            for slot in range(1, 5)
        }

        needy, metadata = room_survival_probabilities(
            [qb], empty_rosters, roster_positions, [], 20, 28, 4
        )
        filled, _ = room_survival_probabilities(
            [qb], filled_rosters, roster_positions, [], 20, 28, 4
        )

        self.assertLess(needy[qb.key], filled[qb.key])
        self.assertEqual(metadata["intervening_picks"], list(range(21, 28)))
        consecutive, _ = room_survival_probabilities(
            [qb], empty_rosters, roster_positions, [], 4, 5, 4
        )
        self.assertEqual(consecutive[qb.key], 1.0)

    def test_live_position_pace_is_shrunk_but_responds_to_a_run(self) -> None:
        players = [Player.from_mapping(row) for row in self.board()]
        qb_run = [self.pick(number, 1, str(number), "QB") for number in range(1, 9)]

        pace = live_position_pace(qb_run, players, completed_pick=8)

        self.assertGreater(pace["QB"]["multiplier"], 1.0)
        self.assertLessEqual(pace["QB"]["multiplier"], 1.25)
        self.assertLess(pace["RB"]["multiplier"], 1.0)

    def test_watcher_reports_room_model_without_changing_first_round_expert_order(self) -> None:
        draft = self.draft()
        board = self.board()
        for row in board:
            row["overall_rank_score"] = row["rank_score"]
        state = reconcile_draft_state(draft, [], 1)

        report = recommend_for_state(state, draft, board)

        primary = report["recommendations"][report["policies"][0]]
        self.assertEqual(primary[0]["player_name"], "Player1 Test")
        self.assertEqual(
            report["room_survival"]["method"],
            "exact_intervening_seats_with_shrunk_live_position_pace",
        )
        self.assertIn("baseline_league_survival", primary[0])

    def test_rejects_a_board_for_the_wrong_scoring_format(self) -> None:
        draft = self.draft()
        state = reconcile_draft_state(draft, [], 1)
        board = self.board()
        for row in board:
            row["scoring"] = "HALF"
        with self.assertRaisesRegex(ValueError, "board scoring"):
            recommend_for_state(state, draft, board)

    def test_approved_scoring_override_is_explicit_and_auditable(self) -> None:
        draft = self.draft()
        state = reconcile_draft_state(
            draft, [], 1, scoring_override="half_ppr"
        )
        self.assertEqual(state.scoring, "half_ppr")
        self.assertTrue(any("Sleeper room reports standard" in warning for warning in state.warnings))

    def test_watcher_uses_get_only_endpoints_and_detects_missed_turn(self) -> None:
        draft = self.draft()
        responses = {
            "draft": draft,
            "picks": [
                self.pick(1, 1, "1"),
                self.pick(2, 2, "2"),
                self.pick(3, 2, "3"),
            ],
        }
        urls: list[str] = []

        def transport(url: str):
            urls.append(url)
            return (
                responses["picks"]
                if urlsplit(url).path.endswith("/picks")
                else responses["draft"]
            )

        watcher = MockDraftWatcher(
            SleeperClient(transport=transport),
            draft["draft_id"],
            self.board(),
            claimed_slot=1,
        )
        first = watcher.poll_once(now=100.0)
        self.assertTrue(first["is_user_turn"])
        self.assertTrue(first["read_only"])
        self.assertIsNotNone(first["recommendation"])
        duplicate = watcher.poll_once(now=100.5)
        self.assertEqual(duplicate["transition"], "duplicate")
        self.assertTrue(duplicate["recommendation_cached"])
        responses["picks"] = [*responses["picks"], self.pick(4, 2, "4")]
        second = watcher.poll_once(now=101.0)
        self.assertTrue(second["missed_turn"])
        self.assertTrue(all("/draft/" in url for url in urls))
        self.assertTrue(
            all(
                urlsplit(url).path.endswith(draft["draft_id"])
                or urlsplit(url).path.endswith("/picks")
                for url in urls
            )
        )
        pick_urls = [url for url in urls if urlsplit(url).path.endswith("/picks")]
        self.assertTrue(all("roster_theory_fresh=" in url for url in pick_urls))

    def test_watcher_warns_and_counts_an_unexpected_cached_picks_response(self) -> None:
        draft = self.draft()

        class CachedPicksClient:
            last_get_metadata: dict = {}

            def draft(self, draft_id: str) -> dict:
                return draft

            def draft_picks(self, draft_id: str) -> list[dict]:
                self.last_get_metadata = {
                    "fresh": True,
                    "cache_busted": True,
                    "cache_status": "HIT",
                    "cache_age_seconds": 7.0,
                    "elapsed_ms": 20.0,
                }
                return []

        watcher = MockDraftWatcher(
            CachedPicksClient(),
            draft["draft_id"],
            self.board(),
            claimed_slot=1,
        )

        report = watcher.poll_once(now=100.0)

        self.assertTrue(
            any("cache bypass returned HIT at age 7s" in row for row in report["warnings"])
        )
        self.assertEqual(report["draft_picks_fetch"]["status_counts"], {"HIT": 1})
        self.assertEqual(report["draft_picks_fetch"]["max_cache_age_seconds"], 7.0)

    def test_watcher_persistently_labels_sleeper_cpu_mode(self) -> None:
        draft = self.draft()

        def transport(url: str):
            return [] if urlsplit(url).path.endswith("/picks") else draft

        watcher = MockDraftWatcher(
            SleeperClient(transport=transport),
            draft["draft_id"],
            self.board(),
            claimed_slot=1,
            acquisition_mode="sleeper_cpu",
            sleeper_adp_snapshot={
                "captured_at": 12345,
                "scoring": "standard",
                "adp_field": "adp_std",
                "players": [
                    {"player_id": str(index), "sleeper_adp": index}
                    for index in range(1, 41)
                ],
            },
        )

        report = watcher.poll_once(now=100.0)

        self.assertTrue(any("CPU MOCK MODE" in row for row in report["warnings"]))
        self.assertEqual(
            report["recommendation"]["acquisition_adp"]["mode"],
            "sleeper_cpu",
        )

    def test_offline_full_mock_reconciles_every_pick_without_a_missed_turn(self) -> None:
        draft = self.draft()
        responses = {"draft": draft, "picks": []}

        def transport(url: str):
            return (
                responses["picks"]
                if urlsplit(url).path.endswith("/picks")
                else responses["draft"]
            )

        watcher = MockDraftWatcher(
            SleeperClient(transport=transport),
            draft["draft_id"],
            self.board(),
            claimed_slot=1,
        )
        initial = watcher.poll_once(now=100.0)
        self.assertTrue(initial["is_user_turn"])
        expected_slots = [1, 2, 2, 1, 1, 2, 2, 1, 1, 2]
        for number, slot in enumerate(expected_slots, start=1):
            responses["picks"] = [
                *responses["picks"],
                self.pick(number, slot, str(number)),
            ]
            if number == len(expected_slots):
                responses["draft"]["status"] = "complete"
            report = watcher.poll_once(now=100.0 + number)
            self.assertFalse(report["missed_turn"])
            self.assertEqual(
                sum(len(roster) for roster in report["rosters"].values()),
                number,
            )
        self.assertEqual(report["status"], "complete")
        self.assertIsNone(report["current_pick"])

    def test_formats_compact_on_the_clock_terminal_report(self) -> None:
        draft = self.draft()
        responses = {"draft": draft, "picks": []}

        def transport(url: str):
            return (
                responses["picks"]
                if urlsplit(url).path.endswith("/picks")
                else responses["draft"]
            )

        watcher = MockDraftWatcher(
            SleeperClient(transport=transport),
            draft["draft_id"],
            self.board(),
            claimed_slot=1,
            recommendation_limit=2,
        )
        output = format_mock_report(watcher.poll_once(now=100.0))

        self.assertIn("ROSTER THEORY - READ ONLY", output)
        self.assertIn("YOU ARE ON THE CLOCK", output)
        self.assertIn("YOUR ROSTER (0)", output)
        self.assertIn("PRIMARY - standard reconciled", output)
        self.assertIn(
            "EXPERT-ORDERED VALUE-CURVE CHECK - standard expert ordered curve",
            output,
        )
        self.assertIn("Player", output)
        self.assertNotIn("Roster use", output)
        lines = output.splitlines()
        header_index = next(
            index for index, line in enumerate(lines) if "Market ADP" in line
        )
        self.assertEqual(len(lines[header_index]), len(lines[header_index + 1]))
        self.assertNotIn('\"draft_id\"', output)

    def test_specialist_order_prefers_kicker_unless_top_three_dst_is_available(
        self,
    ) -> None:
        draft = self.draft()
        draft["settings"].update(
            {
                "rounds": 7,
                "slots_k": 1,
                "slots_def": 1,
            }
        )
        picks = [
            self.pick(number, 1 if number in {1, 4, 5, 8, 9} else 2, str(number))
            for number in range(1, 11)
        ]
        board = [
            *self.board(),
            {
                "player_key": "sleeper_id:41",
                "sleeper_id": "41",
                "player_name": "Top Kicker",
                "position": "K",
                "team": "CAR",
                "adp": 120,
                "rank_score": 2.0,
            },
            {
                "player_key": "sleeper_id:42",
                "sleeper_id": "42",
                "player_name": "Los Angeles Chargers",
                "position": "DST",
                "team": "LAC",
                "adp": 119,
                "rank_score": 1.0,
            },
        ]
        state = reconcile_draft_state(draft, picks, 1)
        kicker_first = recommend_for_state(state, draft, board)
        self.assertEqual(kicker_first["policies"], ["specialist_rank"])
        self.assertEqual(
            kicker_first["recommendations"]["specialist_rank"][0]["position"],
            "K",
        )

        board.extend(
            [
                {
                    "player_key": "sleeper_id:43",
                    "sleeper_id": "43",
                    "player_name": "Seattle Seahawks",
                    "position": "DST",
                    "team": "SEA",
                    "adp": 121,
                    "rank_score": 1.5,
                },
                {
                    "player_key": "sleeper_id:44",
                    "sleeper_id": "44",
                    "player_name": "Houston Texans",
                    "position": "DST",
                    "team": "HOU",
                    "adp": 122,
                    "rank_score": 5.0,
                },
            ]
        )
        dst_first = recommend_for_state(state, draft, board)
        self.assertEqual(
            dst_first["recommendations"]["specialist_rank"][0]["position"],
            "DST",
        )
        self.assertEqual(
            dst_first["recommendations"]["specialist_rank"][0]["player_name"],
            "Houston Texans",
        )
        self.assertEqual(
            dst_first["recommendations"]["specialist_rank"][0]["user_dst_rank"],
            1,
        )
        self.assertIn(
            "Houston Texans is user DST1",
            dst_first["explanations"]["specialist_rank"],
        )

    def test_target_overlay_is_compact_and_does_not_change_recommendations(self) -> None:
        draft = self.draft()
        state = reconcile_draft_state(draft, [], 1)
        book = DraftPreferenceBook(
            league_key="league_alpha",
            source_path="preferences.csv",
            sha256="a" * 64,
            entries=(
                DraftPreference(
                    player_key="sleeper_id:2",
                    player_name="Player2 Test",
                    position="WR",
                    stance="target",
                    category="user_target",
                    take_at_or_after=None,
                    condition="",
                    linked_player="",
                    source="user",
                    league_scope=("league_alpha",),
                ),
                DraftPreference(
                    player_key="sleeper_id:1",
                    player_name="Player1 Test",
                    position="RB",
                    stance="caution",
                    category="fade_at_cost",
                    take_at_or_after=None,
                    condition="",
                    linked_player="",
                    source="user",
                    league_scope=("league_alpha",),
                ),
            ),
        )
        baseline = recommend_for_state(state, draft, self.board(), limit=2)
        with_preferences = recommend_for_state(
            state,
            draft,
            self.board(),
            limit=2,
            draft_preferences=book,
            preference_scoring_settings={"pass_td": 4},
        )

        self.assertEqual(
            with_preferences["recommendations"], baseline["recommendations"]
        )
        self.assertFalse(
            with_preferences["preference_overlay"]["recommendations_changed"]
        )
        self.assertTrue(
            with_preferences["preference_overlay"]["display_targets"][0][
                "roster_need"
            ]
        )

        self.assertIsNotNone(
            with_preferences["preference_overlay"]["display_targets"][0][
                "candidate_rank"
            ]
        )
        self.assertIsNotNone(
            with_preferences["preference_overlay"]["display_targets"][0][
                "primary_score_gap"
            ]
        )
        poll_report = {
            "draft_id": draft["draft_id"],
            "status": state.status,
            "scoring": state.scoring,
            "draft_slot": state.draft_slot,
            "current_pick": state.current_pick,
            "next_user_pick": state.next_user_pick,
            "is_user_turn": True,
            "transition": state.transition,
            "rosters": state.rosters,
            "recommendation": with_preferences,
        }
        primary_policy = with_preferences["policies"][0]
        with_preferences["recommendations"][primary_policy][0][
            "position_expert_rank"
        ] = 14.0
        output = format_mock_report(poll_report, color=True)
        self.assertIn("UPSIDE TARGETS", output)
        self.assertIn("Call", output)
        self.assertIn("Market Surv%", output)
        self.assertIn("Lg Surv%", output)
        self.assertIn(
            "\033[31m  ! PRICE CAUTION: Player1 Test - at/above cost\033[0m",
            output,
        )
        self.assertIn("\033[31m  ! STRATEGY: RB13-30\033[0m", output)
        self.assertIn("\033[31m", output)
        self.assertIn("\033[32m", output)

    def test_rollout_shadow_failure_does_not_change_recommendations(self) -> None:
        draft = self.draft()
        state = reconcile_draft_state(
            draft,
            [
                self.pick(1, 1, "1", "RB"),
                self.pick(2, 2, "2", "WR"),
                self.pick(3, 2, "3", "QB"),
            ],
            1,
        )

        baseline = recommend_for_state(state, draft, self.board(), limit=2)
        with_shadow = recommend_for_state(
            state,
            draft,
            self.board(),
            limit=2,
            rollout_shadow=True,
            rollout_scenarios=0,
        )

        self.assertEqual(
            with_shadow["recommendations"], baseline["recommendations"]
        )
        self.assertEqual(with_shadow["rollout_shadow"]["status"], "unavailable")
        self.assertIn("latency_ms", with_shadow["rollout_shadow"])

    def test_disagreement_and_operational_warnings_are_red(self) -> None:
        report = {
            "draft_id": "test",
            "status": "drafting",
            "scoring": "half_ppr",
            "draft_slot": 4,
            "current_pick": 17,
            "next_user_pick": 17,
            "is_user_turn": True,
            "transition": "advanced",
            "rosters": {slot: [] for slot in range(1, 11)},
            "warnings": ["STALE DRAFT STATE"],
            "recommendation": {
                "policies": ["primary"],
                "model_split": True,
                "room_timing_split": True,
                "recommendations": {
                    "primary": [
                        {
                            "player_key": "walker",
                            "player_name": "Kenneth Walker III",
                            "position": "RB",
                            "final_score": 215.956,
                            "overall_expert_rank": 17.571,
                            "position_expert_rank": 8.692,
                            "overall_rank_stddev": 7.65,
                            "overall_rank_min": 9,
                            "overall_rank_max": 38,
                            "overall_rank_experts": 10,
                            "overall_rank_weight_coverage": 0.999997,
                        },
                        {
                            "player_key": "henry",
                            "player_name": "Derrick Henry",
                            "position": "RB",
                            "final_score": 210.511,
                            "overall_expert_rank": 18.749,
                            "position_expert_rank": 9.795,
                            "overall_rank_stddev": 4.5,
                            "overall_rank_min": 12,
                            "overall_rank_max": 24,
                            "overall_rank_experts": 10,
                            "overall_rank_weight_coverage": 0.999997,
                        },
                    ]
                },
            },
        }

        output = format_mock_report(report, color=True)

        self.assertIn("\033[31mWARNINGS\033[0m", output)
        self.assertIn("\033[31m  ! STALE DRAFT STATE\033[0m", output)
        self.assertIn("\033[31m  ! MODEL SPLIT\033[0m", output)
        self.assertIn("\033[31m  ! ROOM TIMING SPLIT\033[0m", output)
        self.assertIn(
            "\033[31m  ! HIGH EXPERT DISAGREEMENT: Kenneth Walker III | "
            "Ovr SD 7.7 | ranks 9-38 | 10 experts\033[0m",
            output,
        )
        self.assertNotIn("HIGH EXPERT DISAGREEMENT: Derrick Henry", output)

    def test_only_now_upside_calls_are_green_in_the_overlay(self) -> None:
        output = "\n".join(
            _format_preference_overlay(
                {
                    "display_targets": [
                        {
                            "player_name": "Take Him Now",
                            "position": "WR",
                            "call": "NOW",
                            "market_survival": 0.2,
                            "league_survival": 0.3,
                            "note": "upside",
                        },
                        {
                            "player_name": "Wait On Him",
                            "position": "RB",
                            "call": "WAIT",
                            "market_survival": 0.8,
                            "league_survival": 0.7,
                            "note": "later",
                        },
                    ]
                },
                color=True,
            )
        )

        self.assertIn("\033[32mTake Him Now", output)
        self.assertNotIn("\033[32mWait On Him", output)

    def test_watcher_marks_targets_now_on_the_last_skill_pick(self) -> None:
        draft = self.draft()
        draft["settings"].update(
            {
                "rounds": 7,
                "slots_k": 1,
                "slots_def": 1,
            }
        )
        picks = [
            self.pick(number, slot, str(number))
            for number, slot in (
                (1, 1),
                (2, 2),
                (3, 2),
                (4, 1),
                (5, 1),
                (6, 2),
                (7, 2),
                (8, 1),
            )
        ]
        state = reconcile_draft_state(draft, picks, 1)
        self.assertEqual(state.current_pick, 9)
        book = DraftPreferenceBook(
            league_key="league_alpha",
            source_path="preferences.csv",
            sha256="a" * 64,
            entries=(
                DraftPreference(
                    player_key="sleeper_id:10",
                    player_name="Player10 Test",
                    position="WR",
                    stance="target",
                    category="user_target",
                    take_at_or_after=None,
                    condition="",
                    linked_player="",
                    source="user",
                    league_scope=("league_alpha",),
                ),
            ),
        )

        result = recommend_for_state(
            state,
            draft,
            self.board(),
            draft_preferences=book,
        )

        target = result["preference_overlay"]["display_targets"][0]
        self.assertEqual(target["call"], "NOW")
        self.assertEqual(target["note"], "last skill pick")

    def test_explanation_labels_expert_order_override_of_raw_score(self) -> None:
        explanation = _explain_leader(
            [
                {
                    "player_name": "Trevor Lawrence",
                    "roster_need": "open_qb_starter",
                    "final_score": 44.59,
                    "vona": -3.64,
                    "next_pick_survival": 0.538,
                },
                {
                    "player_name": "Brock Purdy",
                    "final_score": 44.606,
                },
            ]
        )
        self.assertIn("expert-order constraint", explanation)
        self.assertIn("raw model score is 0.016 lower", explanation)

    def test_compact_signal_prefers_one_sean_now_near_tie(self) -> None:
        signal = _compact_decision_signal(
            {
                "primary": [
                    {"player_name": "Primary", "final_score": 50.0},
                    {"player_name": "Sean Target", "final_score": 49.5},
                ]
            },
            ("primary",),
            {
                "targets": [
                    {
                        "player_name": "Sean Target",
                        "call": "NOW",
                        "source": "sean_koerner_2026",
                        "candidate_rank": 2,
                        "primary_score_gap": 0.5,
                    },
                    {
                        "player_name": "User Target",
                        "call": "NOW",
                        "source": "user",
                        "candidate_rank": 3,
                        "primary_score_gap": 0.2,
                    },
                ]
            },
        )

        self.assertEqual(signal["kind"], "consider_sean_now")
        self.assertEqual(signal["player_name"], "Sean Target")

    def test_explanation_labels_turn_horizon_qb_guard(self) -> None:
        explanation = _explain_leader(
            [
                {
                    "player_name": "MarShawn Lloyd",
                    "roster_need": "bench_depth",
                    "final_score": 46.687,
                    "vona": -2.41,
                    "next_pick_survival": 1.0,
                    "turn_aware_qb_deferred": True,
                    "turn_aware_qb_name": "Brock Purdy",
                    "turn_aware_qb_survival": 0.766685,
                },
                {"player_name": "Brock Purdy", "final_score": 47.41},
            ]
        )

        self.assertIn("wait on Brock Purdy with 76.7% survival", explanation)
        self.assertIn("turn-horizon QB guard moves this above Brock Purdy", explanation)

    def test_adjacent_turn_plan_is_preserved_only_inside_near_tie(self) -> None:
        leader = Player("leader", "New Leader", "WR", 180, 50, 40, 5)
        planned = Player("planned", "Planned Player", "RB", 175, 51, 35, 6)
        rows = [
            {"_player": leader, "final_score": 50.0},
            {"_player": planned, "final_score": 49.2},
        ]
        plan = {"second_pick": 73, "second_player_key": "planned"}

        preserved, conflict = _preserve_planned_turn(rows, plan, 73)

        self.assertIsNone(conflict)
        self.assertEqual(preserved[0]["_player"].key, "planned")
        self.assertTrue(preserved[0]["planned_turn_preserved"])

        rows[1]["final_score"] = 48.5
        unchanged, conflict = _preserve_planned_turn(rows, plan, 73)
        self.assertEqual(unchanged[0]["_player"].key, "leader")
        self.assertEqual(conflict["score_gap"], 1.5)

    def test_report_renders_only_the_compact_decision_signal(self) -> None:
        report = {
            "draft_id": "123456789012345678",
            "status": "drafting",
            "scoring": "half_ppr",
            "draft_slot": 1,
            "current_pick": 96,
            "next_user_pick": 97,
            "is_user_turn": True,
            "transition": "pick_added",
            "rosters": {slot: [] for slot in range(1, 13)},
            "recommendation": {
                "policies": ["primary"],
                "recommendations": {
                    "primary": [
                        {
                            "player_name": "MarShawn Lloyd",
                            "position": "RB",
                            "final_score": 46.687,
                            "roster_need": "bench_depth",
                            "vona": -2.41,
                            "next_pick_survival": 1.0,
                        }
                    ]
                },
                "explanations": {},
                "construction_context": {"one_qb": True},
                "decision_signal": {
                    "kind": "wait_on_qb",
                    "player_name": "MarShawn Lloyd",
                    "qb_name": "Brock Purdy",
                    "qb_survival": 0.766685,
                    "turn_package_gap": 0.38,
                    "continuation_pick": 120,
                },
            },
        }

        output = format_mock_report(report)

        self.assertIn(
            "DECISION: MarShawn Lloyd; wait on Brock Purdy (76.7% to 10.12, "
            "turn-package gap 0.38)",
            output,
        )
        self.assertNotIn("source-VBD", output)

    def test_explanation_labels_elite_te_sequence_option(self) -> None:
        explanation = _explain_leader(
            [
                {
                    "player_name": "Trey McBride",
                    "roster_need": "open_te_starter",
                    "final_score": 151.581,
                    "vona": 23.677,
                    "next_pick_survival": 0.009,
                    "sequence_option_promoted": True,
                },
                {
                    "player_name": "Javonte Williams",
                    "final_score": 161.343,
                },
            ]
        )

        self.assertIn("elite-TE option moves this above Javonte Williams", explanation)
        self.assertIn("current-path score is 9.762 lower", explanation)

    def test_construction_flags_label_elite_te_sequence_option(self) -> None:
        self.assertEqual(
            _construction_flags(
                {
                    "position": "TE",
                    "position_expert_rank": 2.0,
                    "sequence_option_promoted": True,
                },
                current_pick=24,
                teams=10,
            ),
            ("ELITE TE OPTION",),
        )

    def test_report_shows_sequence_option_without_preference_overlay(self) -> None:
        report = {
            "draft_id": "123456789012345678",
            "status": "drafting",
            "scoring": "half_ppr",
            "draft_slot": 4,
            "current_pick": 24,
            "next_user_pick": 24,
            "is_user_turn": True,
            "transition": "pick_added",
            "rosters": {slot: [] for slot in range(1, 11)},
            "recommendation": {
                "policies": ["half_ppr_reconciled_tol05"],
                "recommendations": {
                    "half_ppr_reconciled_tol05": [
                        {
                            "player_name": "Trey McBride",
                            "position": "TE",
                            "position_expert_rank": 2.0,
                            "sequence_option_promoted": True,
                        }
                    ]
                },
                "explanations": {},
                "construction_context": {"one_qb": True},
            },
        }

        self.assertIn("! STRATEGY: ELITE TE OPTION", format_mock_report(report))

    def test_explanation_exposes_roster_adjusted_reserve_value(self) -> None:
        explanation = _explain_leader(
            [
                {
                    "player_name": "Jordan Mason",
                    "roster_need": "bench_depth",
                    "final_score": 12.4,
                    "vona": 0.7,
                    "next_pick_survival": 0.286,
                    "deterministic_bench_marginal": 41.3,
                }
            ]
        )
        self.assertIn("roster-adjusted reserve marginal 41.3", explanation)

    def test_formats_waiting_roster_without_recent_pick_section(self) -> None:
        draft = self.draft()
        picks = [self.pick(1, 1, "1")]
        state = reconcile_draft_state(draft, picks, 1)
        report = {
            "draft_id": draft["draft_id"],
            "status": state.status,
            "scoring": state.scoring,
            "draft_slot": state.draft_slot,
            "current_pick": state.current_pick,
            "next_user_pick": state.next_user_pick,
            "is_user_turn": state.is_user_turn,
            "transition": state.transition,
            "newly_drafted": state.newly_drafted,
            "rosters": state.rosters,
            "recommendation": None,
            "poll_latency_ms": 10.0,
            "recommendation_latency_ms": 0.0,
            "state_age_seconds": 0.0,
            "warnings": ["test warning"],
        }
        output = format_mock_report(report)

        self.assertIn("WAITING", output)
        self.assertNotIn("RECENT PICKS", output)
        self.assertIn("RB  Player1 Test", output)
        self.assertIn("! test warning", output)


if __name__ == "__main__":
    unittest.main()
