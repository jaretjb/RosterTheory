import ast
import json
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from roster_theory.cli import build_parser, command_waiver_evaluate
from roster_theory.core.errors import CoverageIncomplete, RosterIllegal
from roster_theory.core.models import FantasyTeam, LeagueRules, Player, Projection
from roster_theory.core.provenance import DataStamp, stable_hash
from roster_theory.inseason.evaluation import (
    InSeasonWeek,
    WeeklyProjectionMatrix as NeutralProjectionMatrix,
)
from roster_theory.providers.sleeper import SleeperBundle
from roster_theory.providers.fantasypros import normalize_rankings
from roster_theory.trade.evaluation import WeeklyProjectionMatrix as TradeProjectionMatrix
from roster_theory.waiver.evaluation import (
    ContingencyScenarioInput,
    PlayerValueInput,
    evaluate_waiver,
    fresh_rank_dominates,
    load_waiver_evaluation,
    load_waiver_evaluation_inputs,
    save_waiver_evaluation,
    save_waiver_evaluation_inputs,
)
from roster_theory.waiver.emergence import (
    FantasyResultComponents,
    GameUsageObservation,
    UsageMeasure,
    build_emergence_evidence,
)
from roster_theory.waiver.service import (
    WaiverRefreshResult,
    evaluate_entered_waiver,
    format_waiver_evaluation,
    waiver_evaluation_report,
    waiver_refresh_plan,
)
from roster_theory.waiver.snapshot import PlayerAcquisition, build_waiver_snapshot
from roster_theory.waiver.ww_evidence import (
    WaiverWireConfig,
    build_waiver_wire_evidence,
)
from scripts.waiver_live_inputs import load_contingency_inputs


POLICY_PATH = (
    Path(__file__).parent
    / "fixtures"
    / "waiver"
    / "league_alpha.decision-policy.json"
)
CAPTURED = datetime(2026, 9, 9, 12, tzinfo=timezone.utc)
NOW = datetime(2026, 9, 9, 12, 1, tzinfo=timezone.utc)
POINTS = {
    "qb": 20.0,
    "rb": 10.0,
    "wr": 9.0,
    "bench": 5.0,
    "ir": 8.0,
    "other": 7.0,
    "add": 22.0,
    "fa_rb": 8.0,
    "fa_wr": 7.0,
}


def waiver_wire_evidence():
    def ranking(expert_id=None):
        return normalize_rankings(
            {
                "year": "2026",
                "week": "1",
                "scoring": "HALF",
                "ranking_type_name": "Waiver Wire",
                "last_updated": CAPTURED.isoformat(),
                "expert_names": {"17": "Trusted"},
                "players": [
                    {
                        "player_id": "10",
                        "player_name": "Target Quarterback",
                        "player_position_id": "QB",
                        "rank_ecr": 2 if expert_id is None else 1,
                        "pos_rank": "QB1",
                        "rank_min": 1,
                        "rank_max": 4,
                        "rank_std": 1.1,
                    }
                ],
            },
            requested_horizon="WAIVER",
            board_source="market" if expert_id is None else "selected",
            expert_id=expert_id,
            captured_at=CAPTURED,
        )

    return build_waiver_wire_evidence(
        config=WaiverWireConfig(
            league_key="league_alpha",
            scoring="HALF",
            position="ALL",
            maximum_age_hours=24,
            trusted_expert_ids=("17",),
            config_hash="fixture-config",
        ),
        players=(
            Player("add", "Target Quarterback", ("QB",), fantasypros_id="10"),
        ),
        market=ranking(),
        selected={"17": ranking("17")},
        now=NOW,
    )


def emergence_evidence():
    share = UsageMeasure(30, 50, 0.6)
    count = UsageMeasure(10, 40)
    observation = GameUsageObservation(
        player_id="add",
        player_name="Target Quarterback",
        team="ADD",
        position="QB",
        season=2026,
        week=1,
        game_id="fixture-1",
        source="controlled fixture",
        captured_at=CAPTURED,
        source_updated_at=CAPTURED,
        identity_status="MATCHED",
        coverage_status="COMPLETE",
        game_status="PLAYED",
        overtime=False,
        offensive_snap_share=share,
        route_participation=share,
        target_share=UsageMeasure(6, 30, 0.2),
        targets=count,
        carries=UsageMeasure(0, 20),
        total_opportunities=count,
        goal_line_work=UsageMeasure(0, 4),
        red_zone_work=UsageMeasure(1, 10),
        two_minute_usage=UsageMeasure(2, 8),
        designed_touches=UsageMeasure(8, 30),
        fantasy_result=FantasyResultComponents(18, 14, 0, 0, 4),
        teammate_injury_context="NONE",
        role_durability="DURABLE",
        role_news="Controlled fixture",
    )
    return build_emergence_evidence(
        league_key="league_alpha",
        observations=(observation,),
        captured_at=NOW,
    )


def player(player_id, name, position, team):
    return Player(
        player_id=player_id,
        sleeper_id=player_id,
        fantasypros_id=None,
        name=name,
        positions=(position,),
        nfl_team=team,
        active=True,
        identity_confidence="fixture",
    )


def waiver_snapshot(
    *,
    open_slot=False,
    add_state="FREE_AGENT",
    add_name="Target Quarterback",
    add_active=True,
    add_injury_status=None,
):
    roster_positions = ("QB", "RB", "WR", "BN", *(('BN',) if open_slot else ()))
    league = LeagueRules(
        league_id="league-1",
        season=2026,
        team_count=2,
        roster_positions=roster_positions,
        scoring=(("rec", 0.5),),
        playoff_start_week=3,
        championship_week=3,
        reserve_slots=1,
        platform_settings=(("reserve_slots", 1), ("waiver_budget", 100)),
    )
    teams = (
        FantasyTeam(
            roster_id="1",
            owner_id="u1",
            display_name="One",
            player_ids=("qb", "rb", "wr", "bench", "ir"),
            starter_ids=("qb", "rb", "wr"),
            reserve_ids=("ir",),
            waiver_position=2,
            waiver_budget_used=11,
        ),
        FantasyTeam(
            roster_id="2",
            owner_id="u2",
            display_name="Two",
            player_ids=("other",),
            starter_ids=("other",),
        ),
    )
    players = (
        player("qb", "Roster Quarterback", "QB", "AAA"),
        player("rb", "Roster Runner", "RB", "BBB"),
        player("wr", "Roster Receiver", "WR", "CCC"),
        player("bench", "Bench Receiver", "WR", "DDD"),
        replace(player("ir", "Reserve Runner", "RB", "EEE"), injury_status="IR"),
        player("other", "Other Runner", "RB", "FFF"),
        replace(
            player("add", add_name, "QB", "GGG"),
            active=add_active,
            injury_status=add_injury_status,
        ),
        player("fa_rb", "Free Runner", "RB", "HHH"),
        player("fa_wr", "Free Receiver", "WR", "III"),
    )
    stamp = DataStamp("fixture", "/fixture", CAPTURED, season=2026, week=1, fresh=True)
    bundle = SleeperBundle(
        captured_at=CAPTURED,
        state=(("season", "2026"), ("week", 1)),
        league=league,
        teams=teams,
        players=players,
        matchups=(),
        transactions=(),
        winner_bracket_rounds=None,
        loser_bracket_rows=0,
        stamps=(stamp,),
        player_directory_cache_status="fixture",
    )
    return build_waiver_snapshot(
        league_key="league_alpha",
        user_id="u1",
        sleeper=bundle,
        expected_user_roster_id="1",
        availability_by_player={
            "add": add_state,
            "fa_rb": "FREE_AGENT",
            "fa_wr": "FREE_AGENT",
        },
        now=NOW,
    )


def weeks():
    return (
        InSeasonWeek(1, False),
        InSeasonWeek(2, False, ("GGG",)),
        InSeasonWeek(3, True),
    )


def projections():
    return tuple(
        Projection(
            player_id=player_id,
            horizon="WEEKLY",
            week=week,
            raw_stats=(),
            league_points=points,
            source="fixture",
        )
        for player_id, points in POINTS.items()
        for week in (1, 2, 3)
    )


def values():
    return tuple(
        PlayerValueInput(
            player_id=player_id,
            selected_value=points * 2,
            market_value=points * 1.5,
            raw_projection=points * 3,
        )
        for player_id, points in POINTS.items()
    )


def legality():
    return {"qb": False, "rb": True, "wr": True, "bench": True}


class NeutralExtractionTests(unittest.TestCase):
    def test_trade_reexports_the_neutral_projection_matrix(self):
        self.assertIs(TradeProjectionMatrix, NeutralProjectionMatrix)

    def test_neutral_inseason_package_does_not_import_feature_policy(self):
        source_root = Path(__file__).parents[1] / "src" / "roster_theory" / "inseason"
        prohibited = ("roster_theory.trade", "roster_theory.waiver", "roster_theory.draft")
        violations = []
        for path in source_root.glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module:
                    if node.module.startswith(prohibited):
                        violations.append(f"{path.name}:{node.module}")
                elif isinstance(node, ast.Import):
                    violations.extend(
                        f"{path.name}:{alias.name}"
                        for alias in node.names
                        if alias.name.startswith(prohibited)
                    )
        self.assertEqual(violations, [])


class WaiverEvaluationTests(unittest.TestCase):
    def evaluate(self, snapshot=None, **kwargs):
        return evaluate_waiver(
            snapshot or waiver_snapshot(),
            add="Target Quarterback",
            weeks=weeks(),
            projections=projections(),
            values=values(),
            drop_legality=legality(),
            news_fresh={"add": True},
            now=NOW,
            **kwargs,
        )

    def test_fresh_rank_dominance_is_narrow_and_never_overrides_current_ros_values(self):
        add = PlayerValueInput(
            "add",
            -3.0,
            -3.0,
            31.0,
            current_week_position_rank=32,
            rest_of_season_position_rank=37,
            long_term_value_horizon="EARLY_SEASON_DRAFT_ANCHOR",
        )
        drop = PlayerValueInput(
            "rb",
            0.0,
            0.0,
            30.0,
            current_week_position_rank=42,
            rest_of_season_position_rank=41,
            long_term_value_horizon="EARLY_SEASON_DRAFT_ANCHOR",
        )
        self.assertTrue(fresh_rank_dominates(add, drop, same_position=True))
        self.assertFalse(fresh_rank_dominates(add, drop, same_position=False))
        self.assertFalse(
            fresh_rank_dominates(
                replace(add, long_term_value_horizon="ROS"),
                replace(drop, long_term_value_horizon="ROS"),
                same_position=True,
            )
        )
        self.assertFalse(
            fresh_rank_dominates(
                replace(add, rest_of_season_position_rank=45),
                drop,
                same_position=True,
            )
        )

    def test_full_roster_enumerates_every_legal_skill_drop(self):
        result = self.evaluate()
        self.assertEqual(len(result.candidates), 3)
        self.assertEqual(
            {row.drop_player_id for row in result.candidates},
            {"rb", "wr", "bench"},
        )

    def test_true_waiver_market_and_selected_ranks_are_separate_evidence(self):
        evidence = waiver_wire_evidence()
        result = self.evaluate(waiver_wire_evidence=evidence)
        selected = result.candidates[0].ownership
        self.assertEqual(result.schema_version, 13)
        self.assertEqual(selected.waiver_wire_market_add_rank, 2.0)
        self.assertEqual(selected.waiver_wire_market_add_position_rank, 1.0)
        self.assertEqual(selected.waiver_wire_selected_add_ranks[0].expert_id, "17")
        self.assertEqual(selected.waiver_wire_selected_add_ranks[0].overall_rank, 1.0)
        self.assertEqual(result.waiver_wire_evidence, evidence)
        self.assertEqual(result.selected_drop_player_id, "bench")
        self.assertEqual(set(result.next_best_drop_player_ids), {"rb", "wr"})
        self.assertIn(("qb", "ROSTER_LOCKED"), {(row.player_id, row.reason) for row in result.exclusions})
        self.assertIn(("ir", "RESERVE"), {(row.player_id, row.reason) for row in result.exclusions})

    def test_emergence_evidence_is_preserved_but_does_not_change_selection(self):
        role_evidence = emergence_evidence()
        result = self.evaluate(emergence_evidence=role_evidence)
        self.assertEqual(result.emergence_evidence, role_evidence)
        self.assertEqual(result.selected_drop_player_id, "bench")
        self.assertFalse(result.sleeper_write_performed)

    def test_open_slot_produces_one_no_drop_evaluation(self):
        result = self.evaluate(snapshot=waiver_snapshot(open_slot=True))
        self.assertEqual(len(result.candidates), 1)
        self.assertIsNone(result.selected_drop_player_id)
        self.assertGreater(result.candidates[0].ownership.selected_delta, 0)

    def test_named_drop_produces_exactly_one_candidate(self):
        result = self.evaluate(drop="Roster Receiver")
        self.assertEqual(len(result.candidates), 1)
        self.assertEqual(result.selected_drop_player_id, "wr")

    def test_only_locked_acquisition_state_stops(self):
        with self.assertRaisesRegex(RosterIllegal, "LOCKED"):
            self.evaluate(snapshot=waiver_snapshot(add_state="LOCKED"))

    def test_unclassified_or_pending_unowned_player_can_be_evaluated(self):
        for state in ("UNKNOWN", "PENDING"):
            with self.subTest(state=state):
                result = self.evaluate(snapshot=waiver_snapshot(add_state=state))
                expected = "UNROSTERED" if state == "UNKNOWN" else "PENDING"
                self.assertEqual(result.acquisition_state, expected)

    def test_unknown_drop_legality_blocks_complete_automatic_search(self):
        incomplete = legality()
        incomplete.pop("wr")
        with self.assertRaisesRegex(RosterIllegal, "every skill player"):
            evaluate_waiver(
                waiver_snapshot(),
                add="Target Quarterback",
                weeks=weeks(),
                projections=projections(),
                values=values(),
                drop_legality=incomplete,
                now=NOW,
            )

    def test_locked_or_reserve_named_drop_stops(self):
        for name, message in (
            ("Roster Quarterback", "locked"),
            ("Reserve Runner", "active droppable"),
        ):
            with self.subTest(name=name):
                with self.assertRaisesRegex(RosterIllegal, message):
                    self.evaluate(drop=name)

    def test_missing_value_or_projection_stops(self):
        with self.assertRaisesRegex(CoverageIncomplete, "Value inputs"):
            evaluate_waiver(
                waiver_snapshot(),
                add="Target Quarterback",
                drop="Bench Receiver",
                weeks=weeks(),
                projections=projections(),
                values=tuple(row for row in values() if row.player_id != "bench"),
                drop_legality=legality(),
                now=NOW,
            )
        with self.assertRaisesRegex(CoverageIncomplete, "player-weeks"):
            evaluate_waiver(
                waiver_snapshot(),
                add="Target Quarterback",
                drop="Bench Receiver",
                weeks=weeks(),
                projections=tuple(
                    row for row in projections() if not (row.player_id == "add" and row.week == 2)
                ),
                values=values(),
                drop_legality=legality(),
                now=NOW,
            )

    def test_views_risk_weeks_and_no_label_are_preserved_deterministically(self):
        first = self.evaluate()
        second = self.evaluate()
        selected = first.candidates[0]
        self.assertEqual(first.evidence_hash, second.evidence_hash)
        self.assertNotEqual(selected.ownership.selected_delta, selected.ownership.market_delta)
        self.assertEqual(selected.current_week_delta, 2.0)
        self.assertEqual(selected.added_start_weeks, (1, 3))
        self.assertEqual(selected.added_bye_weeks, (2,))
        self.assertEqual(selected.lineup.playoff_delta, 2.0)
        self.assertIsNotNone(selected.risk.after)
        self.assertIsNone(first.decision_label)
        self.assertFalse(first.recommendation_generated)
        self.assertFalse(first.sleeper_write_performed)
        self.assertTrue(first.candidate_hash)
        self.assertTrue(first.value_input_hash)

    def test_bye_add_is_valued_over_next_available_waiver_player(self):
        snapshot = waiver_snapshot()
        alternate = player("fa_qb", "Next Quarterback", "QB", "JJJ")
        locked = player("locked_qb", "Locked Quarterback", "QB", "KKK")
        snapshot = replace(
            snapshot,
            players=(*snapshot.players, alternate, locked),
            acquisitions=(
                *snapshot.acquisitions,
                PlayerAcquisition(
                    "fa_qb", "FREE_AGENT", None, (), ("controlled_fixture",)
                ),
                PlayerAcquisition(
                    "locked_qb", "LOCKED", None, (), ("controlled_fixture",)
                ),
            ),
        )
        week_rows = (
            InSeasonWeek(1, False, ("AAA",)),
            *weeks()[1:],
        )
        projection_rows = (
            *projections(),
            *(
                Projection("fa_qb", "WEEKLY", week, (), 17.0, "fixture")
                for week in (1, 2, 3)
            ),
            *(
                Projection("locked_qb", "WEEKLY", week, (), 25.0, "fixture")
                for week in (1, 2, 3)
            ),
        )
        value_rows = (
            *values(),
            PlayerValueInput("fa_qb", 34.0, 25.5, 51.0),
            PlayerValueInput("locked_qb", 50.0, 37.5, 75.0),
        )
        result = evaluate_waiver(
            snapshot,
            add="Target Quarterback",
            drop="Bench Receiver",
            weeks=week_rows,
            projections=projection_rows,
            values=value_rows,
            drop_legality=legality(),
            news_fresh={"add": True},
            now=NOW,
        )
        selected = result.candidates[0]
        current = selected.lineup.weeks[0]
        self.assertEqual(current.before_replacements, ("fa_qb",))
        self.assertEqual(current.after_replacements, ())
        self.assertEqual(current.before_points, 36.0)
        self.assertEqual(current.after_points, 41.0)
        self.assertEqual(selected.current_week_delta, 5.0)

    def test_saved_evidence_replays_and_rejects_tampering(self):
        result = self.evaluate()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "evaluation.json"
            save_waiver_evaluation(result, path)
            replay = load_waiver_evaluation(path)
            self.assertTrue(replay["offline_replay"])
            raw = json.loads(path.read_text(encoding="utf-8"))
            raw["add_player_id"] = "tampered"
            path.write_text(json.dumps(raw), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "hash verification"):
                load_waiver_evaluation(path)


class WaiverEvaluationInputAndCliTests(unittest.TestCase):
    def test_live_contingency_loader_builds_named_league_scored_ceiling(self):
        snapshot = SimpleNamespace(
            players=(
                player("corum", "Blake Corum", "RB", "LAR"),
                player("kyren", "Kyren Williams", "RB", "LAR"),
            ),
            weeks=weeks(),
        )
        projection_rows = tuple(
            Projection(
                player_id,
                "WEEKLY",
                week,
                (),
                points,
                "league-scored fixture",
            )
            for player_id, points in (("corum", 7.0), ("kyren", 14.0))
            for week in (1, 2, 3)
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "contingency.json"
            path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "product": "WAIVER ASSISTANT",
                        "league_key": "league_beta",
                        "relationships": [
                            {
                                "beneficiary": "Blake Corum",
                                "unavailable_teammate": "Kyren Williams",
                                "relationship": "DIRECT_SUCCESSOR",
                                "evidence_source": "official depth chart fixture",
                                "evidence_captured_at": NOW.isoformat(),
                                "relationship_status": "CURRENT_AUTHORITATIVE",
                                "scenario_model": "TEAMMATE_PROJECTION_CEILING",
                                "strongest_uncertainty": "Workload transfer is uncertain",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            loaded = load_contingency_inputs(
                path,
                league_key="league_beta",
                snapshot=snapshot,
                projections=projection_rows,
            )
            self.assertEqual(len(loaded), 1)
            self.assertEqual(loaded[0].beneficiary_player_id, "corum")
            self.assertEqual(
                [row.league_points for row in loaded[0].projections],
                [14.0, 14.0, 14.0],
            )
            with self.assertRaisesRegex(ValueError, "different league"):
                load_contingency_inputs(
                    path,
                    league_key="league_alpha",
                    snapshot=snapshot,
                    projections=projection_rows,
                )

    def _input_payload(self):
        payload = {
            "schema_version": 1,
            "product": "WAIVER ASSISTANT",
            "league_key": "league_alpha",
            "captured_at": CAPTURED.isoformat(),
            "availability_source": "controlled fixture",
            "availability_by_player": {"add": "FREE_AGENT"},
            "drop_legality": legality(),
            "weeks": [
                {"week": row.week, "playoff": row.playoff, "bye_teams": list(row.bye_teams)}
                for row in weeks()
            ],
            "projections": [
                {
                    "player_id": row.player_id,
                    "horizon": row.horizon,
                    "week": row.week,
                    "raw_stats": [],
                    "league_points": row.league_points,
                    "source": row.source,
                }
                for row in projections()
            ],
            "values": [
                {
                    "player_id": row.player_id,
                    "selected_value": row.selected_value,
                    "market_value": row.market_value,
                    "raw_projection": row.raw_projection,
                    "waiver_wire_rank": 2 if row.player_id == "add" else None,
                }
                for row in values()
            ],
            "news_fresh": {"add": True},
        }
        payload["input_hash"] = stable_hash(payload)
        return payload

    def test_input_loader_verifies_scope_and_hash(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "inputs.json"
            payload = self._input_payload()
            path.write_text(json.dumps(payload), encoding="utf-8")
            loaded = load_waiver_evaluation_inputs(path)
            self.assertEqual(loaded.input_hash, payload["input_hash"])
            self.assertIn(
                "Legacy ambiguous waiver_wire_rank was ignored",
                next(row for row in loaded.values if row.player_id == "add").warnings[0],
            )
            del payload["input_hash"]
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "require an input hash"):
                load_waiver_evaluation_inputs(path)
            payload["input_hash"] = stable_hash(payload)
            payload["values"][0]["selected_value"] = -1
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "hash verification"):
                load_waiver_evaluation_inputs(path)

    def test_input_saver_round_trips_canonical_bundle(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "inputs.json"
            scenario = ContingencyScenarioInput(
                beneficiary_player_id="fa_rb",
                unavailable_teammate_player_id="other",
                relationship="DIRECT_BACKFIELD_ROLE_EXPANSION",
                evidence_source="controlled fixture",
                evidence_captured_at=CAPTURED,
                relationship_status="CURRENT_AUTHORITATIVE",
                projections=tuple(
                    Projection("fa_rb", "WEEKLY", week, (), 15.0, "scenario fixture")
                    for week in (1, 2, 3)
                ),
                strongest_uncertainty="Role expansion is conditional",
            )
            save_waiver_evaluation_inputs(
                path,
                league_key="league_alpha",
                captured_at=CAPTURED,
                availability_source="current roster delta",
                availability_by_player={},
                drop_legality=legality(),
                weeks=weeks(),
                projections=projections(),
                values=values(),
                news_fresh={"add": True},
                contingencies=(scenario,),
                waiver_wire_evidence=waiver_wire_evidence(),
                emergence_evidence=emergence_evidence(),
            )
            loaded = load_waiver_evaluation_inputs(path)
            self.assertEqual(loaded.schema_version, 6)
            self.assertEqual(loaded.league_key, "league_alpha")
            self.assertEqual(loaded.availability_source, "current roster delta")
            self.assertEqual(len(loaded.projections), len(projections()))
            self.assertEqual(loaded.contingencies, (scenario,))
            self.assertEqual(loaded.waiver_wire_evidence, waiver_wire_evidence())
            self.assertEqual(loaded.emergence_evidence, emergence_evidence())

    def test_waiver_evaluate_parser_is_namespaced_and_read_only(self):
        for league_key in ("league_alpha", "league_beta"):
            with self.subTest(league_key=league_key):
                args = build_parser().parse_args(
                    [
                        "waiver",
                        "evaluate",
                        league_key,
                        "--add",
                        "Target Quarterback",
                        "--inputs",
                        "inputs.json",
                    ]
                )
                self.assertIs(args.func, command_waiver_evaluate)
                self.assertIsNone(args.drop)
                self.assertIsNone(args.policy)

    def test_service_builds_and_saves_a_controlled_entered_evaluation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_path = root / "inputs.json"
            output_path = root / "evaluation.json"
            input_path.write_text(json.dumps(self._input_payload()), encoding="utf-8")
            refresh = WaiverRefreshResult(
                snapshot=waiver_snapshot(),
                call_plan=waiver_refresh_plan("league-1", 1, player_cache_hit=True),
                output_path=root / "snapshot.json",
            )
            with patch(
                "roster_theory.waiver.service.refresh_waiver_snapshot",
                return_value=refresh,
            ):
                result = evaluate_entered_waiver(
                    "league_alpha",
                    add="Target Quarterback",
                    inputs_path=input_path,
                    output_path=output_path,
                    policy_path=POLICY_PATH,
                    now=NOW,
                )
            self.assertTrue(output_path.is_file())
            self.assertEqual(result.evaluation.decision_label, "ADD NOW")
            self.assertEqual(
                result.evaluation.policy_version,
                "test-league-alpha-emerging-upside-v1",
            )
            self.assertFalse(result.evaluation.sleeper_write_performed)
            self.assertEqual(result.evaluation.input_bundle_hash, self._input_payload()["input_hash"])
            self.assertEqual(result.evaluation.availability_source, "controlled fixture")
            machine_report = waiver_evaluation_report(result)
            json.dumps(machine_report, allow_nan=False)
            self.assertIsInstance(machine_report["evaluated_at"], str)
            report = format_waiver_evaluation(result)
            self.assertIn("Decision: ADD NOW", report)
            self.assertIn(
                "FantasyPros Waiver Wire market overall rank (acquisition only): unavailable",
                report,
            )
            self.assertIn("priority 2", report)
            self.assertIn("no bid or claim probability generated", report)

    @patch("roster_theory.cli.evaluate_entered_waiver", side_effect=ValueError("bad"))
    def test_cli_exits_nonzero_on_required_failure(self, _mocked):
        args = build_parser().parse_args(
            [
                "waiver",
                "evaluate",
                "league_alpha",
                "--add",
                "Target Quarterback",
                "--inputs",
                "inputs.json",
            ]
        )
        with self.assertRaisesRegex(SystemExit, "2"):
            command_waiver_evaluate(args)


if __name__ == "__main__":
    unittest.main()
