import ast
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from roster_theory.waiver.evaluation import ContingencyScenarioInput, evaluate_waiver
from roster_theory.waiver.evaluation import PlayerValueInput
from roster_theory.core.models import Projection
from roster_theory.core.errors import RosterIllegal
from roster_theory.inseason.evaluation import InSeasonWeek
from roster_theory.waiver.policy import (
    apply_waiver_policy,
    default_waiver_policy_path,
    load_waiver_policy,
)
from tests.test_waiver_evaluation import (
    NOW,
    POINTS,
    legality,
    projections,
    values,
    waiver_snapshot,
    weeks,
    player,
)
from roster_theory.waiver.snapshot import PlayerAcquisition


WAIVER_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "waiver"
POLICY_PATH = WAIVER_FIXTURE_DIR / "league_alpha.decision-policy.json"
LEAGUE_BETA_POLICY_PATH = WAIVER_FIXTURE_DIR / "league_beta.decision-policy.json"


def target_values(*, bad_drop_case=False):
    result = []
    for row in values():
        if row.player_id == "add":
            result.append(
                replace(
                    row,
                    selected_value=12.0 if bad_drop_case else row.selected_value,
                    market_value=10.0 if bad_drop_case else row.market_value,
                    raw_projection=20.0 if bad_drop_case else row.raw_projection,
                )
            )
        else:
            result.append(row)
    return tuple(result)


class WaiverDecisionPolicyTests(unittest.TestCase):
    def evaluate_contingent_rb(
        self,
        *,
        drop_selected=12.0,
        drop_market=9.0,
        relationship_status="CURRENT_AUTHORITATIVE",
        duplicate_drop_relationship=False,
        add_scenario_points=None,
        league_key="league_alpha",
        policy_path=POLICY_PATH,
        beneficiary_name="Bench Receiver",
        teammate_name="Other Runner",
        automatic_drop=False,
    ):
        snapshot = waiver_snapshot()
        adjusted_players = tuple(
            replace(
                row,
                name=beneficiary_name,
                positions=("RB",),
                nfl_team="DDD",
            )
            if row.player_id == "bench"
            else replace(row, name=teammate_name, nfl_team="DDD")
            if row.player_id == "other"
            else row
            for row in snapshot.players
        )
        add_lead = player("add_lead", "Add Backfield Lead", "RB", "HHH")
        snapshot = replace(
            snapshot,
            league_key=league_key,
            players=(*adjusted_players, add_lead),
            owner_by_player=tuple(sorted((*snapshot.owner_by_player, ("add_lead", "2")))),
            teams=tuple(
                replace(team, player_ids=(*team.player_ids, "add_lead"))
                if team.roster_id == "2"
                else team
                for team in snapshot.teams
            ),
            acquisitions=(
                *snapshot.acquisitions,
                PlayerAcquisition(
                    "add_lead", "LOCKED", "2", (), ("controlled_fixture",)
                ),
            ),
        )
        projection_rows = (
            *projections(),
            *(
                Projection("add_lead", "WEEKLY", week, (), 12.0, "fixture")
                for week in (1, 2, 3)
            ),
        )
        value_rows = tuple(
            replace(row, selected_value=drop_selected, market_value=drop_market)
            if row.player_id == "bench"
            else replace(row, selected_value=30.0, market_value=25.0)
            if row.player_id == "fa_rb"
            else row
            for row in values()
        )
        drop_scenario = ContingencyScenarioInput(
            beneficiary_player_id="bench",
            unavailable_teammate_player_id="other",
            relationship="DIRECT_BACKFIELD_ROLE_EXPANSION",
            evidence_source="controlled depth-chart fixture",
            evidence_captured_at=NOW,
            relationship_status=relationship_status,
            projections=tuple(
                Projection("bench", "WEEKLY", week, (), 15.0, "scenario fixture")
                for week in (1, 2, 3)
            ),
            strongest_uncertainty="Committee share remains uncertain",
        )
        scenarios = [drop_scenario]
        if duplicate_drop_relationship:
            scenarios.append(replace(drop_scenario, relationship="AMBIGUOUS_COMMITTEE"))
        if add_scenario_points is not None:
            scenarios.append(
                ContingencyScenarioInput(
                    beneficiary_player_id="fa_rb",
                    unavailable_teammate_player_id="add_lead",
                    relationship="DIRECT_BACKFIELD_ROLE_EXPANSION",
                    evidence_source="controlled depth-chart fixture",
                    evidence_captured_at=NOW,
                    relationship_status="CURRENT_AUTHORITATIVE",
                    projections=tuple(
                        Projection(
                            "fa_rb", "WEEKLY", week, (), add_scenario_points, "scenario fixture"
                        )
                        for week in (1, 2, 3)
                    ),
                    strongest_uncertainty="Expanded workload is a ceiling, not an expectation",
                )
            )
        evaluated = evaluate_waiver(
            snapshot,
            add="Free Runner",
            drop=None if automatic_drop else beneficiary_name,
            weeks=weeks(),
            projections=projection_rows,
            values=value_rows,
            drop_legality=legality(),
            news_fresh={"fa_rb": True},
            contingencies=tuple(scenarios),
            now=NOW,
        )
        return apply_waiver_policy(evaluated, load_waiver_policy(policy_path))

    def evaluate_qb_hold(
        self,
        *,
        add_points,
        starter_points,
        streamer_points,
        drop="Bench Receiver",
        week_rows=None,
        multi_qb=False,
        value_rows=None,
        weekly_add_points=None,
        weekly_starter_points=None,
        league_key="league_alpha",
        policy_path=POLICY_PATH,
        add_name="Candidate Quarterback",
        drop_name_override=None,
    ):
        snapshot = waiver_snapshot(add_name=add_name)
        if drop_name_override is not None:
            snapshot = replace(
                snapshot,
                players=tuple(
                    replace(row, name=drop_name_override)
                    if row.player_id == "rb"
                    else row
                    for row in snapshot.players
                ),
            )
            if drop == "Roster Runner":
                drop = drop_name_override
        if snapshot.league_key != league_key:
            snapshot = replace(snapshot, league_key=league_key)
        streamers = tuple(
            player(f"streamer_{index}", f"Streamer {index}", "QB", f"S{index}")
            for index, _ in enumerate(streamer_points, start=1)
        )
        snapshot = replace(
            snapshot,
            league=(
                replace(
                    snapshot.league,
                    roster_positions=("QB", "RB", "WR", "SUPER_FLEX", "BN"),
                )
                if multi_qb
                else snapshot.league
            ),
            players=(*snapshot.players, *streamers),
            acquisitions=(
                *snapshot.acquisitions,
                *(
                    PlayerAcquisition(
                        row.player_id,
                        "FREE_AGENT",
                        None,
                        (),
                        ("controlled_fixture",),
                    )
                    for row in streamers
                ),
            ),
        )
        week_rows = week_rows or weeks()
        point_overrides = {"qb": starter_points, "add": add_points}
        point_overrides.update(
            {
                f"streamer_{index}": points
                for index, points in enumerate(streamer_points, start=1)
            }
        )
        projection_rows = tuple(
            Projection(
                player_id,
                "WEEKLY",
                week.week,
                (),
                (
                    weekly_add_points[week_index]
                    if player_id == "add" and weekly_add_points is not None
                    else weekly_starter_points[week_index]
                    if player_id == "qb" and weekly_starter_points is not None
                    else points
                ),
                "fixture",
            )
            for player_id, points in {
                **POINTS,
                **point_overrides,
            }.items()
            for week_index, week in enumerate(week_rows)
        )
        if value_rows is None:
            value_rows = tuple(
                PlayerValueInput(
                    player_id,
                    points * 2,
                    points * 1.5,
                    points * len(week_rows),
                )
                for player_id, points in {
                    **POINTS,
                    **point_overrides,
                }.items()
            )
        unclassified = evaluate_waiver(
            snapshot,
            add=add_name,
            drop=drop,
            weeks=week_rows,
            projections=projection_rows,
            values=value_rows,
            drop_legality=legality(),
            news_fresh={"add": True},
            now=NOW,
        )
        return apply_waiver_policy(unclassified, load_waiver_policy(policy_path))

    def test_waiver_package_does_not_import_draft_or_trade_policy(self):
        source_root = Path(__file__).parents[1] / "src" / "roster_theory" / "waiver"
        prohibited = ("roster_theory.draft", "roster_theory.trade")
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

    def evaluate(
        self,
        *,
        state="FREE_AGENT",
        drop="Bench Receiver",
        projection_rows=None,
        value_rows=None,
        news_fresh=True,
        add_active=True,
        add_injury_status=None,
        league_key="league_alpha",
        policy_path=POLICY_PATH,
    ):
        snapshot = waiver_snapshot(
                add_state=state,
                add_name="Candidate Quarterback",
                add_active=add_active,
                add_injury_status=add_injury_status,
            )
        if snapshot.league_key != league_key:
            snapshot = replace(snapshot, league_key=league_key)
        unclassified = evaluate_waiver(
            snapshot,
            add="Candidate Quarterback",
            drop=drop,
            weeks=weeks(),
            projections=projection_rows or projections(),
            values=value_rows or target_values(),
            drop_legality=legality(),
            news_fresh={"add": news_fresh},
            now=NOW,
        )
        return apply_waiver_policy(unclassified, load_waiver_policy(policy_path))

    def test_policy_is_versioned_waiver_scoped_and_hash_stable(self):
        first = load_waiver_policy(POLICY_PATH)
        second = load_waiver_policy(POLICY_PATH)
        self.assertEqual(first.product, "WAIVER ASSISTANT")
        self.assertEqual(first.league_key, "league_alpha")
        self.assertEqual(first.version, "test-league-alpha-emerging-upside-v1")
        self.assertEqual(first.policy_hash, second.policy_hash)

    def test_affirmative_skill_move_exposes_combined_evidence_contract(self):
        result = self.evaluate()
        self.assertIn(result.decision_label, {"ADD NOW", "CLAIM", "ACQUIRE"})
        evidence = result.candidates[0].skill_player
        self.assertTrue(evidence.applicable)
        self.assertEqual(evidence.schema_version, 1)
        self.assertEqual(
            evidence.ownership_normalization_basis_add,
            "LEAGUE_POSITIONAL_VORP",
        )
        self.assertEqual(
            evidence.selected_ownership_delta,
            result.candidates[0].ownership.selected_delta,
        )
        self.assertEqual(
            evidence.holding_cost,
            result.candidates[0].holding.bench_slot_opportunity_cost,
        )
        self.assertEqual(
            evidence.streaming_baseline,
            result.candidates[0].holding.streaming_replacement_value,
        )
        self.assertEqual(
            evidence.credited_starter_weeks,
            result.candidates[0].added_start_weeks,
        )
        self.assertEqual(len(evidence.contingency_scenarios), 2)

    def test_standalone_plus_contingency_rb_is_protected_from_marginal_drop(self):
        result = self.evaluate_contingent_rb()
        evidence = result.candidates[0].contingency
        self.assertTrue(evidence.drop_protected)
        self.assertFalse(evidence.incremental_gate_passed)
        self.assertEqual(evidence.drop.evidence_status, "CURRENT_AUTHORITATIVE")
        self.assertEqual(evidence.drop.role_expansion_weighted_points, 30.0)
        self.assertEqual(evidence.drop.lineup_ceiling_gain, 15.0)
        self.assertEqual(evidence.incremental_option_value, -15.0)
        self.assertEqual(result.decision_label, "PASS")
        gate = next(
            row
            for row in result.decision.gates
            if row.name == "protected_upside_incremental_value"
        )
        self.assertFalse(gate.passed)

    def test_low_standalone_pure_handcuff_is_not_protected(self):
        result = self.evaluate_contingent_rb(drop_selected=4.0, drop_market=3.0)
        evidence = result.candidates[0].contingency
        self.assertFalse(evidence.drop_protected)
        self.assertTrue(evidence.incremental_gate_passed)
        self.assertIn(result.decision_label, {"ADD NOW", "CLAIM", "ACQUIRE"})

    def test_ambiguous_committee_fails_closed_and_remains_visible(self):
        result = self.evaluate_contingent_rb(duplicate_drop_relationship=True)
        evidence = result.candidates[0].contingency
        self.assertEqual(evidence.drop.evidence_status, "AMBIGUOUS")
        self.assertFalse(evidence.drop.current_authoritative)
        self.assertFalse(evidence.drop_protected)
        self.assertTrue(any("AMBIGUOUS" in warning for warning in result.warnings))

    def test_stale_role_relationship_fails_closed_and_preserves_uncertainty(self):
        result = self.evaluate_contingent_rb(relationship_status="STALE")
        evidence = result.candidates[0].contingency.drop
        self.assertEqual(evidence.evidence_status, "STALE")
        self.assertFalse(evidence.current_authoritative)
        self.assertFalse(result.candidates[0].contingency.drop_protected)
        self.assertEqual(evidence.strongest_uncertainty, "Committee share remains uncertain")

    def test_acquisition_upside_can_clear_protected_option_gate(self):
        result = self.evaluate_contingent_rb(add_scenario_points=22.0)
        evidence = result.candidates[0].contingency
        self.assertTrue(evidence.add_protected)
        self.assertTrue(evidence.drop_protected)
        self.assertTrue(evidence.incremental_gate_passed)
        self.assertEqual(evidence.incremental_option_value, 21.0)
        self.assertEqual(result.decision.decision_path, "CONTINGENT_UPSIDE")
        self.assertIn(result.decision_label, {"ADD NOW", "CLAIM", "ACQUIRE"})

    def test_league_beta_love_for_white_audit_is_not_affirmative_with_streaming(self):
        result = self.evaluate_qb_hold(
            add_points=18.0,
            starter_points=20.0,
            streamer_points=(17.0,),
            drop="Roster Runner",
            week_rows=(
                InSeasonWeek(1, False),
                InSeasonWeek(2, False, ("AAA",)),
                InSeasonWeek(3, True),
            ),
            league_key="league_beta",
            policy_path=LEAGUE_BETA_POLICY_PATH,
            add_name="Jordan Love",
            drop_name_override="Rachaad White",
        )
        holding = result.candidates[0].holding
        self.assertIn(result.decision_label, {"WATCH", "PASS"})
        self.assertEqual(holding.required_bye_weeks, (2,))
        self.assertEqual(holding.streaming_replacement_value, 17.0)
        self.assertEqual(holding.bench_slot_opportunity_cost, 2.0)
        self.assertEqual(holding.net_hold_value, -1.0)
        self.assertEqual(result.candidates[0].skill_player.credited_starter_weeks, (2,))

    def test_league_beta_corum_kyren_audit_protects_corum_from_routine_drop(self):
        result = self.evaluate_contingent_rb(
            drop_selected=15.0,
            drop_market=12.0,
            league_key="league_beta",
            policy_path=LEAGUE_BETA_POLICY_PATH,
            beneficiary_name="Blake Corum",
            teammate_name="Kyren Williams",
            automatic_drop=True,
        )
        corum = next(
            row for row in result.candidates if row.drop_player_id == "bench"
        )
        self.assertTrue(corum.contingency.drop_protected)
        self.assertFalse(corum.contingency.incremental_gate_passed)
        self.assertNotEqual(result.selected_drop_player_id, "bench")

    def test_default_policy_resolution_is_explicit_and_league_specific(self):
        league_alpha = load_waiver_policy(
            default_waiver_policy_path(
                "league_alpha", config_dir=WAIVER_FIXTURE_DIR
            )
        )
        league_beta = load_waiver_policy(
            default_waiver_policy_path(
                "league_beta", config_dir=WAIVER_FIXTURE_DIR
            )
        )
        self.assertEqual(league_alpha.league_key, "league_alpha")
        self.assertEqual(league_beta.league_key, "league_beta")
        self.assertEqual(
            league_beta.version, "test-league-beta-emerging-upside-v1"
        )
        self.assertNotEqual(league_alpha.policy_hash, league_beta.policy_hash)
        self.assertEqual(league_beta.maximum_current_week_loss, 0.0)
        self.assertEqual(league_beta.maximum_depth_loss, 0.0)
        self.assertEqual(
            default_waiver_policy_path("new_league"),
            Path("config/waiver/new_league.decision-policy.json"),
        )
        with self.assertRaisesRegex(ValueError, "Invalid Waiver league key"):
            default_waiver_policy_path("../unsafe")

    def test_league_beta_controlled_fixtures_cover_promotion_cases(self):
        common = {
            "league_key": "league_beta",
            "policy_path": LEAGUE_BETA_POLICY_PATH,
        }
        immediate = self.evaluate(**common)
        insurance_rows = tuple(
            replace(row, league_points=18.0) if row.player_id == "add" else row
            for row in projections()
        )
        insurance = self.evaluate(
            state="WAIVERS",
            projection_rows=insurance_rows,
            **common,
        )
        negative_drop = self.evaluate(
            drop="Roster Receiver",
            value_rows=target_values(bad_drop_case=True),
            **common,
        )
        self.assertEqual(immediate.decision_label, "ADD NOW")
        self.assertEqual(immediate.decision.decision_path, "IMMEDIATE")
        self.assertEqual(insurance.decision_label, "CLAIM")
        self.assertEqual(insurance.decision.decision_path, "QB_INJURY_INSURANCE")
        self.assertEqual(negative_drop.decision_label, "PASS")
        self.assertTrue(all(row.policy_hash for row in (immediate, insurance, negative_drop)))
        with self.assertRaisesRegex(ValueError, "different league"):
            apply_waiver_policy(
                replace(immediate, league_key="league_alpha"),
                load_waiver_policy(LEAGUE_BETA_POLICY_PATH),
            )

    def test_policy_rejects_incomplete_or_cross_track_configuration(self):
        payload = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "policy.json"
            payload["product"] = "TRADE ASSISTANT"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Waiver-scoped"):
                load_waiver_policy(path)
            payload["product"] = "WAIVER ASSISTANT"
            del payload["thresholds"]["market_value_floor"]
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "misses threshold"):
                load_waiver_policy(path)

    def test_immediate_upgrade_hand_audit_is_add_now(self):
        result = self.evaluate()
        selected = result.candidates[0]
        self.assertEqual(result.decision_label, "ADD NOW")
        self.assertEqual(result.decision.decision_path, "IMMEDIATE")
        self.assertEqual(selected.lineup.weighted_delta, 4.0)
        self.assertEqual(selected.current_week_delta, 2.0)
        self.assertEqual(
            [
                (row.week, row.before_points, row.after_points, row.delta)
                for row in selected.lineup.weeks
            ],
            [(1, 39.0, 41.0, 2.0), (2, 39.0, 39.0, 0.0), (3, 39.0, 41.0, 2.0)],
        )
        self.assertEqual(
            (
                selected.ownership.selected_delta,
                selected.ownership.market_delta,
                selected.ownership.raw_projection_delta,
            ),
            (34.0, 25.5, 51.0),
        )
        self.assertIsNone(selected.ownership.waiver_wire_market_add_rank)
        self.assertFalse(result.sleeper_write_performed)

    def test_waiver_state_maps_the_same_passed_gates_to_claim(self):
        result = self.evaluate(state="WAIVERS")
        self.assertEqual(result.decision_label, "CLAIM")
        self.assertTrue(all(gate.passed for gate in result.decision.gates))

    def test_unrostered_and_pending_states_use_neutral_acquire_label(self):
        for state in ("UNROSTERED", "PENDING"):
            with self.subTest(state=state):
                result = self.evaluate(state=state)
                self.assertEqual(result.decision_label, "ACQUIRE")
                self.assertTrue(all(gate.passed for gate in result.decision.gates))

    def test_insurance_case_can_pass_without_a_projected_start(self):
        insurance_projections = tuple(
            replace(row, league_points=18.0) if row.player_id == "add" else row
            for row in projections()
        )
        result = self.evaluate(state="WAIVERS", projection_rows=insurance_projections)
        selected = result.candidates[0]
        self.assertEqual(result.decision_label, "CLAIM")
        self.assertEqual(result.decision.decision_path, "QB_INJURY_INSURANCE")
        self.assertEqual(selected.lineup.weighted_delta, 0.0)
        self.assertEqual(selected.current_week_delta, 0.0)
        self.assertEqual(selected.added_start_weeks, ())
        self.assertEqual(
            [row.delta for row in selected.lineup.weeks],
            [0.0, 0.0, 0.0],
        )

    def test_one_bye_qb_stash_loses_to_streaming_when_it_costs_a_useful_rb(self):
        week_rows = (
            InSeasonWeek(1, False),
            InSeasonWeek(2, False, ("AAA",)),
            InSeasonWeek(3, True),
        )
        value_rows = list(values())
        value_rows = [
            replace(row, selected_value=30.0, market_value=25.0)
            if row.player_id == "rb"
            else replace(row, raw_projection=100.0)
            if row.player_id == "add"
            else row
            for row in value_rows
        ]
        value_rows.append(PlayerValueInput("streamer_1", 34.0, 25.5, 51.0))
        result = self.evaluate_qb_hold(
            add_points=18.0,
            starter_points=20.0,
            streamer_points=(17.0,),
            drop="Roster Runner",
            week_rows=week_rows,
            value_rows=tuple(value_rows),
        )
        holding = result.candidates[0].holding
        self.assertEqual(result.decision_label, "PASS")
        self.assertTrue(holding.applicable)
        self.assertEqual(holding.streaming_candidate_ids, ("streamer_1",))
        self.assertEqual(holding.required_bye_weeks, (2,))
        self.assertEqual(holding.streaming_replacement_value, 17.0)
        self.assertEqual(holding.required_bye_coverage_value, 1.0)
        self.assertEqual(holding.holding_period, 2)
        self.assertEqual(holding.unused_weeks, (1,))
        self.assertEqual(holding.bench_replacement_candidate_ids, ("fa_rb",))
        self.assertEqual(holding.bench_slot_opportunity_cost, 7.0)
        self.assertEqual(holding.net_hold_value, -6.0)
        raw_gate = next(
            gate for gate in result.decision.gates if gate.name == "raw_projection_delta"
        )
        self.assertTrue(raw_gate.passed)

    def test_materially_superior_qb_can_pass_as_injury_insurance(self):
        result = self.evaluate_qb_hold(
            add_points=25.0,
            starter_points=26.0,
            streamer_points=(17.0,),
            week_rows=(
                InSeasonWeek(1, False),
                InSeasonWeek(2, False),
                InSeasonWeek(3, True),
            ),
        )
        holding = result.candidates[0].holding
        self.assertEqual(result.decision_label, "ADD NOW")
        self.assertEqual(result.decision.decision_path, "QB_INJURY_INSURANCE")
        self.assertEqual(holding.required_bye_weeks, ())
        self.assertEqual(holding.injury_insurance_value, 8.0)
        self.assertEqual(holding.net_hold_value, 0.0)
        self.assertEqual(holding.unused_weeks, (1, 2, 3))

    def test_scarce_streaming_pool_preserves_candidates_and_uses_worst_available(self):
        result = self.evaluate_qb_hold(
            add_points=18.0,
            starter_points=20.0,
            streamer_points=(19.0, 15.0),
            week_rows=(
                InSeasonWeek(1, False),
                InSeasonWeek(2, False, ("AAA",)),
                InSeasonWeek(3, True),
            ),
        )
        baseline = result.candidates[0].holding.weekly_streaming_baselines[1]
        self.assertEqual(baseline.candidate_ids, ("streamer_1", "streamer_2"))
        self.assertEqual(baseline.stress_rank, 3)
        self.assertEqual(baseline.selected_player_id, "streamer_2")
        self.assertEqual(baseline.selected_points, 15.0)

    def test_close_qb_start_sit_edges_are_reported_but_not_credited(self):
        result = self.evaluate_qb_hold(
            add_points=19.0,
            starter_points=20.0,
            streamer_points=(17.0,),
            weekly_add_points=(19.0, 20.5, 19.0),
            weekly_starter_points=(20.0, 20.0, 20.0),
            week_rows=(
                InSeasonWeek(1, False),
                InSeasonWeek(2, False),
                InSeasonWeek(3, True),
            ),
        )
        holding = result.candidates[0].holding
        self.assertEqual(holding.starter_decision_margin, 1.5)
        self.assertEqual(holding.close_call_weeks, (2,))
        self.assertEqual(holding.discretionary_start_weeks, ())
        self.assertEqual(holding.discretionary_start_value, 0.0)

    def test_incomplete_streamer_is_visible_and_blocks_affirmative_hold(self):
        value_rows = (
            *values(),
            PlayerValueInput(
                "streamer_1",
                34.0,
                25.5,
                51.0,
                coverage_status="partial",
            ),
        )
        result = self.evaluate_qb_hold(
            add_points=18.0,
            starter_points=20.0,
            streamer_points=(17.0,),
            week_rows=(
                InSeasonWeek(1, False),
                InSeasonWeek(2, False),
                InSeasonWeek(3, True),
            ),
            value_rows=value_rows,
        )
        holding = result.candidates[0].holding
        self.assertNotIn(result.decision_label, {"ADD NOW", "CLAIM", "ACQUIRE"})
        self.assertEqual(holding.streaming_candidate_ids, ())
        self.assertEqual(holding.streaming_omission_ids, ("streamer_1",))
        self.assertTrue(
            any("streamer_1" in warning for warning in result.warnings)
        )

    def test_multi_qb_format_does_not_apply_one_qb_holding_policy(self):
        result = self.evaluate_qb_hold(
            add_points=18.0,
            starter_points=20.0,
            streamer_points=(17.0,),
            multi_qb=True,
        )
        holding = result.candidates[0].holding
        self.assertFalse(holding.applicable)
        self.assertFalse(holding.one_qb_format)
        self.assertEqual(holding.reason, "MULTI_QB_FORMAT")

    def test_required_bad_drop_reverses_the_same_target_inputs_to_pass(self):
        value_rows = target_values(bad_drop_case=True)
        good_drop = self.evaluate(value_rows=value_rows)
        bad_drop = self.evaluate(drop="Roster Receiver", value_rows=value_rows)
        selected = bad_drop.candidates[0]
        self.assertEqual(good_drop.decision_label, "ADD NOW")
        self.assertEqual(bad_drop.decision_label, "PASS")
        self.assertEqual(selected.lineup.weighted_delta, -8.0)
        self.assertEqual(selected.current_week_delta, -2.0)
        self.assertEqual(
            [
                (row.week, row.before_points, row.after_points, row.delta)
                for row in selected.lineup.weeks
            ],
            [(1, 39.0, 37.0, -2.0), (2, 39.0, 35.0, -4.0), (3, 39.0, 37.0, -2.0)],
        )
        self.assertEqual(
            (
                selected.ownership.selected_delta,
                selected.ownership.market_delta,
                selected.ownership.raw_projection_delta,
            ),
            (-6.0, -3.5, -7.0),
        )
        self.assertIn(
            "Selected ownership delta below +0.0",
            bad_drop.decision.reversal_conditions,
        )

    def test_automatic_selection_prefers_an_affirmative_move_over_a_higher_lineup_pass(self):
        projection_rows = tuple(
            replace(row, league_points=30.0) if row.player_id == "add" else row
            for row in projections()
        )
        value_rows = tuple(
            replace(
                row,
                selected_value=(20.0 if row.player_id == "add" else 100.0),
                market_value=(20.0 if row.player_id == "add" else 100.0),
                raw_projection=(30.0 if row.player_id == "add" else 100.0),
            )
            if row.player_id in {"add", "bench"}
            else replace(
                row,
                selected_value=1.0,
                market_value=1.0,
                raw_projection=1.0,
            )
            if row.player_id == "wr"
            else row
            for row in target_values()
        )
        result = self.evaluate(
            drop=None,
            projection_rows=projection_rows,
            value_rows=value_rows,
        )
        self.assertEqual(result.decision_label, "ADD NOW")
        self.assertEqual(result.selected_drop_player_id, "wr")
        self.assertGreater(
            next(row for row in result.candidates if row.drop_player_id == "bench").lineup.weighted_delta,
            result.candidates[0].lineup.weighted_delta,
        )

    def test_missing_news_partial_inputs_and_inactive_status_are_never_affirmative(self):
        partial_values = tuple(
            replace(row, coverage_status="partial") if row.player_id == "add" else row
            for row in target_values()
        )
        partial_projections = tuple(
            replace(row, coverage_status="partial")
            if row.player_id == "add" and row.week == 1
            else row
            for row in projections()
        )
        cases = (
            self.evaluate(news_fresh=False),
            self.evaluate(value_rows=partial_values),
            self.evaluate(projection_rows=partial_projections),
            self.evaluate(add_injury_status="OUT"),
        )
        for result in cases:
            with self.subTest(warnings=result.warnings):
                self.assertEqual(result.decision_label, "WATCH")
                self.assertNotIn(result.decision_label, {"ADD NOW", "CLAIM"})

    def test_evidence_hash_changes_with_policy_and_replay_fields_are_populated(self):
        result = self.evaluate()
        self.assertTrue(result.policy_hash)
        self.assertEqual(result.policy_hash, result.decision.policy_hash)
        self.assertTrue(result.evidence_hash)
        self.assertTrue(result.recommendation_generated)
        self.assertIn("controlled-fixture calibrated", result.strongest_uncertainty)

    def special_team_evaluation(
        self,
        position,
        *,
        current_delta,
        future_delta=0.0,
        current_rank=5,
        ros_rank=None,
        drop_name=None,
    ):
        snapshot = waiver_snapshot()
        roster_position = "DEF" if position == "DST" else position
        incumbent_id = position.lower()
        add_id = f"add_{position.lower()}"
        incumbent = player(incumbent_id, f"Roster {position}", position, "ST1")
        target = player(add_id, f"Candidate {position}", position, "ST2")
        user_team = replace(
            snapshot.teams[0],
            player_ids=(*snapshot.teams[0].player_ids, incumbent_id),
            starter_ids=(*snapshot.teams[0].starter_ids, incumbent_id),
        )
        capacity = replace(
            snapshot.roster_capacity[0],
            active_limit=snapshot.roster_capacity[0].active_limit + 1,
            active_count=snapshot.roster_capacity[0].active_count + 1,
        )
        snapshot = replace(
            snapshot,
            league=replace(
                snapshot.league,
                roster_positions=(*snapshot.league.roster_positions, roster_position),
            ),
            teams=(user_team, *snapshot.teams[1:]),
            players=(*snapshot.players, incumbent, target),
            owner_by_player=(*snapshot.owner_by_player, (incumbent_id, "1")),
            roster_capacity=(capacity, *snapshot.roster_capacity[1:]),
            acquisitions=(
                *snapshot.acquisitions,
                PlayerAcquisition(incumbent_id, "LOCKED", "1", (), ("fixture",)),
                PlayerAcquisition(add_id, "FREE_AGENT", None, (), ("fixture",)),
            ),
        )
        projection_rows = (
            *projections(),
            *(
                Projection(incumbent_id, "WEEKLY", week, (), 8.0, "fixture")
                for week in (1, 2, 3)
            ),
            Projection(add_id, "WEEKLY", 1, (), 8.0 + current_delta, "fixture"),
            Projection(add_id, "WEEKLY", 2, (), 8.0 + future_delta, "fixture"),
            Projection(add_id, "WEEKLY", 3, (), 8.0 + future_delta, "fixture"),
        )
        value_rows = (
            *values(),
            PlayerValueInput(
                incumbent_id,
                0.0,
                0.0,
                24.0,
                current_week_position_rank=10,
                rest_of_season_position_rank=10,
            ),
            PlayerValueInput(
                add_id,
                0.0,
                0.0,
                24.0 + current_delta + 2 * future_delta,
                current_week_position_rank=current_rank,
                rest_of_season_position_rank=ros_rank,
            ),
        )
        evaluated = evaluate_waiver(
            snapshot,
            add_player_id=add_id,
            drop=drop_name or f"Roster {position}",
            weeks=weeks(),
            projections=projection_rows,
            values=value_rows,
            drop_legality={**legality(), incumbent_id: True},
            news_fresh={add_id: True},
            now=NOW,
        )
        return apply_waiver_policy(evaluated, load_waiver_policy(POLICY_PATH))

    def test_kicker_and_ordinary_dst_use_current_week_streaming_path(self):
        for position in ("K", "DST"):
            with self.subTest(position=position):
                result = self.special_team_evaluation(
                    position, current_delta=2.0, future_delta=-1.0, ros_rank=8
                )
                self.assertEqual(result.decision_label, "ADD NOW")
                self.assertEqual(result.decision.decision_path, f"{position}_STREAM")
                self.assertFalse(result.decision.elite_dst_exception)

    def test_elite_dst_can_survive_a_bad_week_but_non_elite_cannot(self):
        elite = self.special_team_evaluation(
            "DST", current_delta=-1.0, future_delta=1.0, ros_rank=2
        )
        ordinary = self.special_team_evaluation(
            "DST", current_delta=-1.0, future_delta=1.0, ros_rank=4
        )
        self.assertEqual(elite.decision_label, "ADD NOW")
        self.assertEqual(elite.decision.decision_path, "ELITE_DST")
        self.assertTrue(elite.decision.elite_dst_exception)
        self.assertEqual(ordinary.decision_label, "PASS")

    def test_special_team_missing_weekly_rank_is_never_affirmative(self):
        result = self.special_team_evaluation(
            "K", current_delta=2.0, current_rank=None
        )
        self.assertEqual(result.decision_label, "WATCH")
        self.assertFalse(result.decision.gates[0].passed)

    def test_special_team_drop_must_match_the_added_position(self):
        with self.assertRaisesRegex(RosterIllegal, "active droppable K replacement"):
            self.special_team_evaluation(
                "K", current_delta=2.0, drop_name="Roster Receiver"
            )


if __name__ == "__main__":
    unittest.main()
