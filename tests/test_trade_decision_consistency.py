import unittest
from dataclasses import replace
from unittest.mock import patch

from roster_theory.trade.evaluation import (
    EvaluationOptions,
    build_entered_package,
    evaluate_trade,
    _decision_assessment,
)
from roster_theory.trade.evaluation_service import format_trade_evaluation
from roster_theory.trade.target_optimizer import optimize_target_packages
from tests import test_trade_target_optimizer as target_fixtures
from tests.test_trade_evaluation import snapshot_fixture, projection_fixture, board_fixture


class TradeDecisionConsistencyTests(unittest.TestCase):
    def test_secondary_move_prefers_gate_passing_pair_over_more_lineup_points(self):
        snapshot = snapshot_fixture()
        board = board_fixture(snapshot, "selected_final")
        board = replace(
            board,
            players=tuple(
                replace(row, reconciled_vorp=100 if row.player_id == "a_low" else 0)
                if row.player_id in {"a_low", "a_bench"}
                else row
                for row in board.players
            ),
        )
        result = self.evaluate(
            send=("a_rb",),
            receive=("b_wr", "b_bench"),
            snapshot=snapshot,
            board=board,
            partner_market_floor=-100,
            max_depth_loss=100,
            projections=tuple(
                replace(row, league_points=20) if row.player_id == "b_wr" else row
                for row in projection_fixture()
            ),
        )
        move = result.secondary_moves[0]
        self.assertEqual(move.chosen_player_ids, ("a_bench",))
        alternative = next(row for row in move.candidates if row.player_ids == ("a_low",))
        self.assertGreater(
            alternative.weighted_lineup_points, move.candidates[0].weighted_lineup_points
        )
        self.assertIn("USER_SELECTED_VALUE", alternative.gate_failures)
        self.assertFalse(move.candidates[0].gate_failures)

    def test_proxy_market_shortlist_remains_explicitly_provisional(self):
        snapshot, projections, selected, market_ecr, market, targets = (
            target_fixtures.TargetPackageOptimizerTests()._inputs(proxy=True)
        )
        result = optimize_target_packages(
            snapshot,
            projections=projections,
            selected_board=selected,
            market_ecr_board=market_ecr,
            trade_market=market,
            target_result=targets,
            config=target_fixtures.optimizer_config(),
            options=target_fixtures.permissive_options(),
        )
        accepted = [row for row in result.evaluated_decisions if row.accepted]
        self.assertTrue(accepted)
        self.assertTrue(all(row.recommendation_status == "PROVISIONAL_MARKET" for row in accepted))
        self.assertTrue(all(row.package_verdict == "ACCEPTABLE" for row in accepted))

    def evaluate(
        self,
        *,
        send=("a_bench",),
        receive=("b_bench",),
        snapshot=None,
        projections=None,
        board=None,
        **options,
    ):
        snapshot = snapshot or snapshot_fixture()
        board = board or board_fixture(snapshot, "selected_final")
        return evaluate_trade(
            snapshot,
            build_entered_package(snapshot, send=send, receive=receive),
            projections=projections or projection_fixture(),
            selected_board=board,
            market_board=board,
            options=EvaluationOptions(**options),
        )

    def test_identical_package_axes_and_verdict_match_for_all_searched_sizes(self):
        snapshot, projections, selected, market_ecr, market, targets = (
            target_fixtures.TargetPackageOptimizerTests()._inputs()
        )
        options = target_fixtures.permissive_options()
        result = optimize_target_packages(
            snapshot,
            projections=projections,
            selected_board=selected,
            market_ecr_board=market_ecr,
            trade_market=market,
            target_result=targets,
            config=target_fixtures.optimizer_config(),
            options=options,
        )
        self.assertEqual(
            {row.package_size for row in result.evaluated_decisions},
            {"1-for-1", "1-for-2", "2-for-1", "2-for-2"},
        )
        for row in result.evaluated_decisions:
            entered = evaluate_trade(
                snapshot,
                build_entered_package(
                    snapshot, send=row.sent_player_ids, receive=row.received_player_ids
                ),
                projections=projections,
                selected_board=selected,
                market_board=market_ecr,
                options=options,
            )
            self.assertEqual(row.package_verdict, entered.decision_label)
            self.assertEqual(row.decision_axes, entered.decision)
            self.assertEqual(row.intrinsic_outcome, entered.decision.intrinsic_outcome)
            if row.accepted:
                self.assertEqual(row.package_verdict, "ACCEPTABLE")

    def test_each_common_gate_changes_only_its_axis(self):
        base = self.evaluate(send=("a_low",), receive=("b_wr",), partner_market_floor=-100)
        options = EvaluationOptions(partner_market_floor=-100)
        self.assertEqual(base.decision_label, "ACCEPTABLE")
        cases = (
            (
                "user_expected_lineup_delta",
                (replace(base.team_impacts[0], weighted_delta=-1), base.team_impacts[1]),
                base.risk_impacts,
                base.ownership_impacts,
                (),
                options,
            ),
            (
                "user_depth_delta",
                (replace(base.team_impacts[0], depth_delta=-100), base.team_impacts[1]),
                base.risk_impacts,
                base.ownership_impacts,
                (),
                options,
            ),
            (
                "user_offense_downside_increase",
                base.team_impacts,
                (
                    replace(base.risk_impacts[0], offense_downside_loss_delta=100),
                    base.risk_impacts[1],
                ),
                base.ownership_impacts,
                (),
                options,
            ),
            (
                "user_selected_value_delta",
                base.team_impacts,
                base.risk_impacts,
                base.ownership_impacts,
                (),
                replace(options, user_selected_floor=1000),
            ),
            (
                "partner_market_delta",
                base.team_impacts,
                base.risk_impacts,
                base.ownership_impacts,
                (),
                replace(options, partner_market_floor=1000),
            ),
            (
                "complete_evidence",
                base.team_impacts,
                base.risk_impacts,
                base.ownership_impacts,
                ("MANUAL-LEGALITY",),
                options,
            ),
        )
        for name, impacts, risks, ownership, modes, policy in cases:
            with self.subTest(gate=name):
                result = _decision_assessment(impacts, risks, ownership, modes, policy)
                self.assertEqual([gate.name for gate in result.gates if not gate.passed], [name])
                self.assertNotEqual(result.label, "ACCEPTABLE")
                if name == "partner_market_delta":
                    self.assertEqual(result.intrinsic_outcome, base.decision.intrinsic_outcome)
                    self.assertEqual(result.partner_status, "FAIL")

    def test_secondary_lineup_tie_preserves_higher_ownership_value(self):
        snapshot = snapshot_fixture()
        projections = tuple(
            replace(row, league_points=0) if row.player_id in {"a_bench", "a_low"} else row
            for row in projection_fixture()
        )
        board = board_fixture(snapshot, "selected_final")
        board = replace(
            board,
            players=tuple(
                replace(row, reconciled_vorp=50) if row.player_id == "a_bench" else row
                for row in board.players
            ),
        )
        result = self.evaluate(
            send=("a_rb",),
            receive=("b_wr", "b_bench"),
            snapshot=snapshot,
            projections=projections,
            board=board,
            user_selected_floor=-100,
            partner_market_floor=-100,
            max_depth_loss=100,
        )
        self.assertEqual(result.secondary_moves[0].chosen_player_ids, ("a_low",))
        self.assertEqual(
            next(row for row in snapshot.players if row.player_id == "a_low").positions, ("WR",)
        )
        self.assertIn(
            ("a_bench",), {row.player_ids for row in result.secondary_moves[0].candidates}
        )

    def test_explicit_unsafe_drop_is_shown_not_approved(self):
        result = self.evaluate(
            send=("a_rb",),
            receive=("b_wr", "b_bench"),
            drop_overrides=("b_bench",),
            user_selected_floor=-100,
            partner_market_floor=-100,
        )
        self.assertEqual(result.secondary_moves[0].chosen_player_ids, ("b_bench",))
        self.assertIn(
            "RECEIVED_ASSET_DROPPED", result.secondary_moves[0].candidates[0].gate_failures
        )
        self.assertEqual(result.decision_label, "DECLINE")

    def test_bound_and_missing_market_are_visible(self):
        with patch("roster_theory.trade.evaluation.MAX_SECONDARY_COMBINATIONS", 1):
            result = self.evaluate(send=("a_rb",), receive=("b_wr", "b_bench"))
        self.assertIn("BOUNDED-SECONDARY-SEARCH", result.modes)
        self.assertEqual(result.decision.market_status, "ECR_OWNERSHIP_ONLY_NOT_CHART_PRICED")
        text = format_trade_evaluation(result)
        self.assertIn("unexamined combinations may be better", text)
        self.assertIn("not a confirmed market-priced offer", text)

    def test_target_search_cannot_bypass_entered_partner_gate(self):
        snapshot, projections, selected, market_ecr, market, targets = (
            target_fixtures.TargetPackageOptimizerTests()._inputs()
        )
        result = optimize_target_packages(
            snapshot,
            projections=projections,
            selected_board=selected,
            market_ecr_board=market_ecr,
            trade_market=market,
            target_result=targets,
            config=target_fixtures.optimizer_config(),
            options=replace(target_fixtures.permissive_options(), partner_market_floor=100000),
        )
        self.assertTrue(result.evaluated_decisions)
        self.assertFalse(any(row.accepted for row in result.evaluated_decisions))

    def test_valuable_injured_bench_is_not_the_automatic_drop(self):
        snapshot = snapshot_fixture()
        snapshot = replace(
            snapshot,
            players=tuple(
                replace(row, injury_status="IR") if row.player_id == "a_bench" else row
                for row in snapshot.players
            ),
        )
        package = build_entered_package(
            snapshot, send=("Alpha Runner",), receive=("Bravo Receiver", "Bravo Bench")
        )
        board = board_fixture(snapshot, "selected_final")
        board = replace(
            board,
            players=tuple(
                replace(row, reconciled_vorp=100.0) if row.player_id == "a_bench" else row
                for row in board.players
            ),
        )
        projections = tuple(
            replace(row, league_points=0.0) if row.player_id == "a_bench" else row
            for row in projection_fixture()
        )
        result = evaluate_trade(
            snapshot,
            package,
            projections=projections,
            selected_board=board,
            market_board=board,
            options=EvaluationOptions(
                user_selected_floor=-1000,
                partner_market_floor=-1000,
                max_depth_loss=1000,
                max_downside_increase=1000,
            ),
        )
        self.assertNotIn("a_bench", result.secondary_moves[0].chosen_player_ids)
