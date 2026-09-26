"""Missing roster evidence must be protected and scoped to the actual move."""
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import tempfile

from roster_theory.core.decision_coverage import lineup_dependency_positions, maximum_delta_bound
from roster_theory.core.errors import CoverageIncomplete, RosterIllegal
from roster_theory.core.models import Player, Projection
from roster_theory.trade.evaluation import EvaluationOptions, build_entered_package, evaluate_trade
from roster_theory.trade.evaluation import load_trade_evaluation, save_trade_evaluation
from roster_theory.trade.evaluation_service import format_trade_evaluation
from roster_theory.trade.boards import valuation_gaps
from roster_theory.trade.search import SearchConfig, search_league
from roster_theory.trade.target_optimizer import optimize_target_packages
from roster_theory.trade.targets import discover_trade_targets
from roster_theory.waiver.evaluation import evaluate_waiver
from roster_theory.waiver.policy import apply_waiver_policy, load_waiver_policy
from roster_theory.waiver.service import format_waiver_evaluation
from tests.test_trade_evaluation import snapshot_fixture, projection_fixture, board_fixture
from tests.test_trade_targets import fixture, config
from tests.test_trade_target_optimizer import optimizer_config, permissive_options
from tests.test_waiver_evaluation import waiver_snapshot, weeks, projections, values, legality, NOW, POLICY_PATH


class DependencyMechanicsTests(unittest.TestCase):
    def test_slot_connections_include_flex_and_multiple_position_bridges(self):
        players = (Player("rb", "Runner", ("RB",)), Player("qb", "Quarterback", ("QB",)))
        slots = ("QB", "RB", "WR", "TE", "FLEX", "BN")
        self.assertEqual(lineup_dependency_positions(slots, players, ("rb",)), {"RB", "WR", "TE"})
        self.assertIn("QB", lineup_dependency_positions((*slots, "SUPER_FLEX"), players, ("rb",)))
        bridged = (*players, Player("bridge", "Bridge", ("QB", "WR")))
        self.assertIn("QB", lineup_dependency_positions(slots, bridged, ("rb",)))

    def test_maximum_risk_bound_survives_unknown_team_and_maximum_switches(self):
        before, after = {"A": 2, "B": 20}, {"A": 9, "B": 16}
        bound = maximum_delta_bound(before, after)
        self.assertEqual(bound, 7)
        for unknown_a in (0, 3, 20, 1000):
            for unknown_b in (0, 3, 20, 1000):
                for other_team in (0, 1000):
                    old = max(before["A"] + unknown_a, before["B"] + unknown_b, other_team)
                    new = max(after["A"] + unknown_a, after["B"] + unknown_b, other_team)
                    self.assertLessEqual(new - old, bound)


class TradeDecisionCoverageTests(unittest.TestCase):
    def setUp(self):
        self.snapshot = snapshot_fixture()
        self.projections = projection_fixture()
        self.selected = board_fixture(self.snapshot, "selected")
        self.market = board_fixture(self.snapshot, "market")
        self.options = EvaluationOptions(max_downside_increase=100, max_depth_loss=100,
                                         user_selected_floor=-100, partner_market_floor=-100)

    def evaluate(self, snapshot=None, projections=None, send=("a_wr",), receive=("b_rb",)):
        snapshot = snapshot or self.snapshot
        return evaluate_trade(snapshot, build_entered_package(snapshot, send=send, receive=receive),
                              projections=self.projections if projections is None else projections,
                              selected_board=self.selected, market_board=self.market, options=self.options)

    def with_unknown_qb(self):
        return replace(self.snapshot,
            league=replace(self.snapshot.league, roster_positions=("QB", *self.snapshot.league.roster_positions)),
            players=(*self.snapshot.players, Player("unknown", "Unknown Quarterback", ("QB",), nfl_team="AAA")),
            teams=tuple(replace(team, player_ids=(*team.player_ids, "unknown")) if team.roster_id == "1" else team
                        for team in self.snapshot.teams),
            owner_by_player=(*self.snapshot.owner_by_player, ("unknown", "1")))

    def test_independent_move_matches_every_completed_unknown_projection(self):
        snapshot = self.with_unknown_qb()
        partial = self.evaluate(snapshot)
        self.assertNotIn("DECISION-CONDITIONAL", partial.modes)
        self.assertEqual(partial.decision.confidence, "SCOPED_PROVISIONAL_MARKET")
        self.assertIn("whole-roster risk/exposure unavailable", format_trade_evaluation(partial))
        for points in (0, 1, 25, 1000):
            completed = (*self.projections, *(Projection("unknown", "WEEKLY", week, (), points, "fixture")
                                             for week in (1, 2, 3)))
            full = self.evaluate(snapshot, completed)
            self.assertEqual(partial.decision.label, full.decision.label)
            for incomplete_team, full_team in zip(partial.team_impacts, full.team_impacts):
                self.assertEqual(incomplete_team.weighted_delta, full_team.weighted_delta)
                self.assertEqual(incomplete_team.depth_delta, full_team.depth_delta)

    def test_replacement_or_superflex_makes_unknown_qb_relevant(self):
        snapshot = self.with_unknown_qb()
        superflex = replace(snapshot, league=replace(snapshot.league,
                            roster_positions=(*snapshot.league.roster_positions, "SUPER_FLEX")))
        self.assertEqual(self.evaluate(superflex).decision.label, "CONDITIONAL")
        replacement = replace(snapshot, players=(*snapshot.players,
                              Player("free_qb", "Available Quarterback", ("QB",))),
                              free_agent_ids=(*snapshot.free_agent_ids, "free_qb"))
        self.assertEqual(self.evaluate(replacement).decision.label, "CONDITIONAL")

    def test_future_missing_week_and_secondary_moves_preserve_unknown_capacity(self):
        partial = tuple(row for row in self.projections if not (row.player_id == "a_bench" and row.week == 3))
        snapshot = replace(self.snapshot, players=tuple(replace(row, injury_status="OUT")
                           if row.player_id == "a_bench" else row for row in self.snapshot.players))
        result = self.evaluate(snapshot, projections=partial, receive=("b_rb", "b_wr"))
        self.assertEqual(result.decision.label, "CONDITIONAL")
        move = next(row for row in result.secondary_moves if row.roster_id == "1")
        self.assertEqual(move.kind, "DROP")
        self.assertEqual(len(move.chosen_player_ids), 1)
        self.assertNotIn("a_bench", move.chosen_player_ids)
        self.assertTrue(all("a_bench" not in row.player_ids for row in move.candidates))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "conditional.json"
            save_trade_evaluation(result, path)
            restored = load_trade_evaluation(path)
            self.assertEqual(restored['decision']['label'], "CONDITIONAL")
            self.assertEqual(restored['evidence_hash'], result.evidence_hash)

    def test_actual_trade_asset_still_requires_projection_evidence(self):
        with self.assertRaisesRegex(CoverageIncomplete, "package assets"):
            self.evaluate(projections=tuple(row for row in self.projections if row.player_id != "a_wr"))

    def test_unresolved_identity_still_occupies_a_slot(self):
        snapshot = replace(self.snapshot,
            players=tuple(row for row in self.snapshot.players if row.player_id != "a_bench"),
            player_exclusions=(("a_bench", "PLAYER_IDENTITY_UNAVAILABLE"),))
        result = self.evaluate(snapshot, receive=("b_rb", "b_wr"))
        self.assertEqual(result.decision.label, "CONDITIONAL")
        move = next(row for row in result.secondary_moves if row.roster_id == "1")
        self.assertEqual(move.kind, "DROP")
        self.assertNotIn("a_bench", move.chosen_player_ids)

    def test_search_evaluates_other_assets_with_protected_roster_gap(self):
        partial = tuple(row for row in self.projections if row.player_id != "a_bench")
        result = search_league(self.snapshot, projections=partial, selected_board=self.selected,
                              market_board=self.market, gaps=valuation_gaps(self.selected, self.market), options=self.options,
                              config=SearchConfig(max_exact_per_opponent=50, market_band_floor=100))
        self.assertTrue(result.roster_exclusions)
        self.assertTrue(result.coverage)
        self.assertGreater(sum(row.evaluated for row in result.coverage), 0)
        self.assertTrue(result.opportunities)
        for row in result.opportunities:
            self.assertNotIn("a_bench", (*row.sent_player_ids, *row.received_player_ids))
            self.assertEqual(row.label, "CONDITIONAL")
            self.assertEqual(row.objective_tags, ("CONDITIONAL",))

    def test_target_optimizer_survives_connected_gap_and_consolidation(self):
        snapshot, rows, selected, market, trade_market = fixture()
        rows = tuple(row for row in rows if row.player_id != "u_flex")
        targets = discover_trade_targets(snapshot, projections=rows, selected_board=selected,
            market_ecr_board=market, trade_market=trade_market, config=config())
        result = optimize_target_packages(snapshot, projections=rows, selected_board=selected,
            market_ecr_board=market, trade_market=trade_market, target_result=targets,
            config=optimizer_config(), options=permissive_options())
        self.assertGreater(len(result.evaluated_decisions), 0)
        conditional = [row for row in result.evaluated_decisions if row.reason == "CONDITIONAL_ROSTER_EVIDENCE"]
        self.assertTrue(conditional)
        self.assertTrue(all(not row.accepted and row.recommendation_status == "CONDITIONAL" for row in conditional))
        self.assertTrue(all("u_flex" not in (*row.sent_player_ids, *row.received_player_ids)
                            for row in result.evaluated_decisions))


class WaiverDecisionCoverageTests(unittest.TestCase):
    def evaluate(self, snapshot=None, rows=None, drop="bench"):
        result = evaluate_waiver(snapshot or waiver_snapshot(), add_player_id="fa_wr", drop_player_id=drop,
            weeks=weeks(), projections=projections() if rows is None else rows, values=values(),
            drop_legality=legality(), news_fresh={"fa_wr": True}, now=NOW)
        return apply_waiver_policy(result, load_waiver_policy(POLICY_PATH))

    def test_future_missing_wr_is_conditional_and_cannot_be_dropped(self):
        rows = tuple(row for row in projections() if not (row.player_id == "wr" and row.week == 3))
        result = self.evaluate(rows=rows)
        self.assertEqual(result.decision_label, "WATCH")
        self.assertEqual(result.decision.decision_path, "CONDITIONAL_ROSTER_EVIDENCE")
        self.assertFalse(result.projection_inputs_complete)
        report = format_waiver_evaluation(SimpleNamespace(evaluation=result,
            refresh=SimpleNamespace(snapshot=waiver_snapshot()), output_path=Path("fixture.json")))
        self.assertIn("Conditional comparison", report)
        with self.assertRaises(RosterIllegal):
            self.evaluate(rows=rows, drop="wr")

    def test_unknown_identity_retains_capacity_and_conditional_status(self):
        snapshot = waiver_snapshot()
        snapshot = replace(snapshot, players=tuple(row for row in snapshot.players if row.player_id != "wr"))
        result = self.evaluate(snapshot)
        self.assertEqual(result.selected_drop_player_id, "bench")
        self.assertEqual(result.decision.decision_path, "CONDITIONAL_ROSTER_EVIDENCE")
        self.assertIn("IDENTITY_UNAVAILABLE", {row.reason for row in result.exclusions})

    def test_independent_qb_requires_no_replacement_or_holding_dependency(self):
        # Remove the unowned QB from this decision universe so replacement
        # floors cannot connect its empty slot to the WR depth comparison.
        snapshot = waiver_snapshot()
        snapshot = replace(snapshot, acquisitions=tuple(row for row in snapshot.acquisitions if row.player_id != "add"))
        rows = tuple(row for row in projections() if row.player_id not in {"qb", "add"})
        partial = self.evaluate(snapshot, rows)
        self.assertNotEqual(partial.decision.decision_path, "CONDITIONAL_ROSTER_EVIDENCE")
        for points in (0, 1, 25, 1000):
            full = self.evaluate(snapshot, (*rows, *(Projection("qb", "WEEKLY", week, (), points, "fixture")
                                                    for week in (1, 2, 3))))
            self.assertEqual(partial.decision_label, full.decision_label)
            self.assertEqual(partial.candidates[0].lineup.weighted_delta, full.candidates[0].lineup.weighted_delta)
            self.assertEqual(partial.candidates[0].lineup.depth_delta, full.candidates[0].lineup.depth_delta)

    def test_missing_add_evidence_still_blocks(self):
        with self.assertRaises(CoverageIncomplete):
            self.evaluate(rows=tuple(row for row in projections() if row.player_id != "fa_wr"))
