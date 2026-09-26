from __future__ import annotations

import unittest
from dataclasses import replace
from unittest.mock import patch

from roster_theory.core.errors import CoverageIncomplete
from roster_theory.trade.evaluation import EvaluationOptions
from roster_theory.trade.market import ecr_proxy
from roster_theory.trade.target_optimizer import (
    ExactEvaluationBudget,
    TargetOptimizerConfig,
    _fairness,
    optimize_target_packages,
    uniform_exact_budgets,
)
from roster_theory.trade.targets import discover_trade_targets
from tests.test_trade_targets import config as target_config
from tests.test_trade_targets import fixture


def optimizer_config(
    *,
    exact_budgets: tuple[ExactEvaluationBudget, ...] | None = None,
    fair_ratio: float = 10.0,
    fair_floor: float = 100.0,
) -> TargetOptimizerConfig:
    return TargetOptimizerConfig(
        policy_id="optimizer-fixture-v1",
        outgoing_pool_limit=5,
        incoming_pool_limit=5,
        construction_market_band_ratio=10.0,
        construction_market_band_floor=100.0,
        fair_market_band_ratio=fair_ratio,
        fair_market_band_floor=fair_floor,
        consolidation_premium_policy_id="fixture-premium-v1",
        consolidation_premium_ratio=0.1,
        minimum_consolidation_starter_upgrade=0.1,
        minimum_partner_asset_lineup_use=0.0,
        minimum_partner_asset_depth_use=0.0,
        minimum_user_lineup_gain=0.1,
        partner_lineup_floor=-100.0,
        partner_selected_floor=-100.0,
        maximum_partner_depth_loss=100.0,
        max_results_per_lane=20,
        exact_budgets=exact_budgets or uniform_exact_budgets(100),
    )


def permissive_options(*, selected_floor: float = -100.0) -> EvaluationOptions:
    return EvaluationOptions(
        user_selected_floor=selected_floor,
        partner_market_floor=-100.0,
        max_depth_loss=100.0,
        max_downside_increase=100.0,
    )


class TargetPackageOptimizerTests(unittest.TestCase):
    def test_cross_lane_exact_packages_are_evaluated_once(self) -> None:
        snapshot, projections, selected, market_ecr, market, targets = self._inputs()
        from roster_theory.trade import target_optimizer

        original = target_optimizer.evaluate_trade
        calls: list[tuple[str, tuple[str, ...], tuple[str, ...]]] = []

        def counted(*args, **kwargs):
            package = args[1]
            calls.append((
                package.roster_b_id,
                tuple(asset.player_id for asset in package.from_a),
                tuple(asset.player_id for asset in package.from_b),
            ))
            return original(*args, **kwargs)

        metrics: dict[str, object] = {}
        with patch.object(target_optimizer, "evaluate_trade", side_effect=counted):
            result = optimize_target_packages(
                snapshot,
                projections=projections,
                selected_board=selected,
                market_ecr_board=market_ecr,
                trade_market=market,
                target_result=targets,
                config=optimizer_config(),
                options=permissive_options(),
                metrics=metrics,
            )
        decision_keys = [
            (row.opponent_roster_id, row.sent_player_ids, row.received_player_ids)
            for row in result.evaluated_decisions
        ]
        self.assertGreater(len(decision_keys), len(set(decision_keys)))
        self.assertEqual(len(calls), len(set(calls)))
        self.assertEqual(len(set(calls)), len(set(decision_keys)))
        self.assertEqual(metrics["cache"]["exact_hits"], len(decision_keys) - len(calls))
        self.assertEqual(metrics["coverage"]["evaluated"], len(decision_keys))
        self.assertEqual(set(metrics["stage_ms"]), {"setup", "construction", "exact", "finalize"})
        replay = optimize_target_packages(
            snapshot,
            projections=projections,
            selected_board=selected,
            market_ecr_board=market_ecr,
            trade_market=market,
            target_result=targets,
            config=optimizer_config(),
            options=permissive_options(),
        )
        self.assertEqual(replay.evidence_hash, result.evidence_hash)
        self.assertEqual(replay.coverage, result.coverage)

    def test_market_rejections_skip_lineup_work_but_keep_coverage(self) -> None:
        snapshot, projections, selected, market_ecr, market, targets = self._inputs()
        strict = replace(
            optimizer_config(),
            construction_market_band_ratio=0.0,
            construction_market_band_floor=0.0,
            fair_market_band_ratio=0.0,
            fair_market_band_floor=0.0,
        )
        metrics: dict[str, object] = {}
        result = optimize_target_packages(
            snapshot,
            projections=projections,
            selected_board=selected,
            market_ecr_board=market_ecr,
            trade_market=market,
            target_result=targets,
            config=strict,
            options=permissive_options(),
            metrics=metrics,
        )
        self.assertEqual(metrics["coverage"]["enumerated"], 180)
        self.assertEqual(metrics["coverage"]["prefiltered"], 169)
        self.assertEqual(metrics["coverage"]["evaluated"], 11)
        self.assertLess(metrics["cache"]["lineup_entries"], metrics["coverage"]["prefiltered"])
        self.assertEqual(sum(row.enumerated for row in result.coverage), 180)

    def test_provisional_premium_sensitivity_changes_only_market_verdict(self) -> None:
        fairness = _fairness(
            ("sent",), ("received",), {"sent": 105.0, "received": 100.0},
            "DIRECT", 0.0, 0.0, (), consolidation=True,
            premium_policy_id="fixture-provisional", premium_ratio=0.05,
        )
        self.assertEqual(fairness.status, "FAIR")
        self.assertEqual(
            [(row.ratio, row.status) for row in fairness.premium_sensitivity],
            [(0.0, "USER_OVERPAY"), (0.05, "FAIR"), (0.1, "USER_UNDERPAY")],
        )
        proxy = _fairness(
            ("sent",), ("received",), {"sent": 105.0, "received": 100.0},
            "ECR-PROXY", 0.0, 0.0, (), consolidation=True,
            premium_policy_id="fixture-provisional", premium_ratio=0.05,
        )
        self.assertEqual(proxy.premium_sensitivity, ())

    def _inputs(self, *, proxy: bool = False):
        snapshot, projections, selected, market_ecr, direct = fixture()
        market = ecr_proxy("fixture direct chart unavailable") if proxy else direct
        targets = discover_trade_targets(
            snapshot,
            projections=projections,
            selected_board=selected,
            market_ecr_board=market_ecr,
            trade_market=market,
            config=target_config(),
        )
        return snapshot, projections, selected, market_ecr, market, targets

    def test_lane_size_budgets_preserve_best_controlled_two_for_one(self) -> None:
        snapshot, projections, selected, market_ecr, market, targets = self._inputs()
        bounded = optimize_target_packages(
            snapshot,
            projections=projections,
            selected_board=selected,
            market_ecr_board=market_ecr,
            trade_market=market,
            target_result=targets,
            config=optimizer_config(exact_budgets=uniform_exact_budgets(1)),
            options=permissive_options(),
        )
        exhaustive = optimize_target_packages(
            snapshot,
            projections=projections,
            selected_board=selected,
            market_ecr_board=market_ecr,
            trade_market=market,
            target_result=targets,
            config=optimizer_config(),
            options=permissive_options(),
        )
        coverage = {(row.lane, row.package_size): row for row in bounded.coverage}

        for lane, package_size in coverage:
            exhaustive_passing = tuple(
                row
                for row in exhaustive.evaluated_decisions
                if row.lane == lane and row.package_size == package_size and row.accepted
            )
            bounded_passing = tuple(
                row
                for row in bounded.evaluated_decisions
                if row.lane == lane and row.package_size == package_size and row.accepted
            )
            if exhaustive_passing:
                self.assertTrue(bounded_passing, (lane, package_size))
                self.assertEqual(
                    bounded_passing[0].user_weighted_lineup_delta,
                    max(row.user_weighted_lineup_delta for row in exhaustive_passing),
                    (lane, package_size),
                )
        self.assertEqual(coverage[("BUY_LOW", "1-for-1")].evaluated, 1)
        self.assertEqual(coverage[("CONSOLIDATE", "2-for-1")].evaluated, 1)
        self.assertGreater(coverage[("CONSOLIDATE", "2-for-1")].runtime_pruned, 0)
        self.assertEqual(len(bounded.coverage), 16)
        consolidation_seeds = tuple(
            row for row in bounded.outgoing_seeds if row.lane == "CONSOLIDATE"
        )
        self.assertEqual(consolidation_seeds[0].player_id, "u_flex")
        self.assertTrue(consolidation_seeds[0].usable_surplus)
        self.assertEqual(consolidation_seeds[0].exact_marginal_lineup_cost, 0.0)

    def test_exact_decisions_distinguish_fair_losses_from_unfair_wins(self) -> None:
        snapshot, projections, selected, market_ecr, market, targets = self._inputs()
        result = optimize_target_packages(
            snapshot,
            projections=projections,
            selected_board=selected,
            market_ecr_board=market_ecr,
            trade_market=market,
            target_result=targets,
            config=optimizer_config(fair_ratio=0.0, fair_floor=0.0),
            options=permissive_options(selected_floor=10.0),
        )
        unfair_wins = tuple(
            row
            for row in result.evaluated_decisions
            if row.intrinsic_outcome == "WIN" and not row.market_fairness.within_band
        )
        fair_losses = tuple(
            row
            for row in result.evaluated_decisions
            if row.intrinsic_outcome == "LOSS" and row.market_fairness.within_band
        )

        self.assertTrue(unfair_wins)
        self.assertTrue(fair_losses)
        self.assertTrue(all(row.reason == "MARKET_FAIRNESS_GATE" for row in unfair_wins))
        self.assertTrue(all(row.reason == "INTRINSIC_LOSS" for row in fair_losses))
        self.assertTrue(all(not row.accepted for row in (*unfair_wins, *fair_losses)))
        self.assertTrue(
            all(
                row.intrinsic_outcome == "WIN" and row.market_fairness.within_band
                for row in result.opportunities
            )
        )

    def test_ecr_proxy_constrains_search_without_claiming_chart_fairness(self) -> None:
        snapshot, projections, selected, market_ecr, market, targets = self._inputs(proxy=True)
        result = optimize_target_packages(
            snapshot,
            projections=projections,
            selected_board=selected,
            market_ecr_board=market_ecr,
            trade_market=market,
            target_result=targets,
            config=optimizer_config(exact_budgets=uniform_exact_budgets(1)),
            options=permissive_options(),
        )

        self.assertEqual(result.pricing_mode, "ECR-PROXY")
        self.assertTrue(result.evaluated_decisions)
        self.assertTrue(
            all(row.market_fairness.status == "ECR-PROXY" for row in result.evaluated_decisions)
        )
        self.assertTrue(
            all(
                row.market_fairness.consolidation_premium_value is None
                for row in result.evaluated_decisions
            )
        )
        self.assertTrue(
            any("cannot make chart-fairness claims" in warning for warning in result.warnings)
        )

    def test_partial_current_chart_excludes_unpriced_assets_only(self) -> None:
        snapshot, projections, selected, market_ecr, market, _ = self._inputs()
        assert market.board is not None
        board = replace(
            market.board,
            prices=tuple(row for row in market.board.prices if row.player_id != "o_buy"),
            normalized_count=len(market.board.prices) - 1,
        )
        market = replace(market, board=board)
        targets = discover_trade_targets(
            snapshot, projections=projections, selected_board=selected,
            market_ecr_board=market_ecr, trade_market=market,
            config=target_config(),
        )
        result = optimize_target_packages(
            snapshot, projections=projections, selected_board=selected,
            market_ecr_board=market_ecr, trade_market=market,
            target_result=targets, config=optimizer_config(),
            options=permissive_options(),
        )
        self.assertEqual(result.pricing_mode, "STATS_GUY_FANTASY_API")
        self.assertTrue(result.evaluated_decisions)
        self.assertTrue(all(
            "o_buy" not in (*row.sent_player_ids, *row.received_player_ids)
            for row in result.evaluated_decisions
        ))

    def test_missing_current_target_uses_one_prior_chart_for_whole_package(self) -> None:
        snapshot, projections, selected, market_ecr, market, _ = self._inputs()
        assert market.board is not None
        prior = replace(
            market.board,
            mode="PRIOR_WEEK_MARKET",
            prices=tuple(replace(row, value=row.value * 2) for row in market.board.prices),
            stamp=replace(market.board.stamp, fresh=False),
        )
        current = replace(
            market.board,
            prices=tuple(row for row in market.board.prices if row.player_id != "o_buy"),
            normalized_count=len(market.board.prices) - 1,
        )
        market = replace(market, board=current, prior_board=prior)
        targets = discover_trade_targets(
            snapshot, projections=projections, selected_board=selected,
            market_ecr_board=market_ecr, trade_market=market,
            config=target_config(),
        )
        self.assertEqual(targets.pricing_mode, "MIXED_CURRENT_PRIOR")
        self.assertTrue(any(
            row.player_id == "o_buy" and row.trade_price.mode == "PRIOR_WEEK_MARKET"
            for row in targets.targets
        ))
        result = optimize_target_packages(
            snapshot, projections=projections, selected_board=selected,
            market_ecr_board=market_ecr, trade_market=market,
            target_result=targets, config=optimizer_config(),
            options=permissive_options(),
        )
        prior_decisions = [
            row for row in result.evaluated_decisions
            if "o_buy" in (*row.sent_player_ids, *row.received_player_ids)
        ]
        self.assertTrue(prior_decisions)
        prior_values = {row.player_id: row.value for row in prior.prices}
        self.assertTrue(all(
            row.market_fairness.sent_value
            == sum(prior_values[player_id] for player_id in row.sent_player_ids)
            and row.market_fairness.received_value
            == sum(prior_values[player_id] for player_id in row.received_player_ids)
            for row in prior_decisions
        ))
        self.assertTrue(all(
            row.market_fairness.status == "PRIOR_WEEK_MARKET"
            and not row.accepted
            and not row.market_fairness.premium_sensitivity
            for row in prior_decisions
        ))
        self.assertTrue(all(
            row.market_fairness.status == "PRIOR_WEEK_MARKET"
            for row in prior_decisions
        ))

    def test_prior_market_prices_are_indicative_and_never_accept(self) -> None:
        snapshot, projections, selected, market_ecr, market, _ = self._inputs()
        assert market.board is not None
        market = replace(
            market,
            mode="PRIOR_WEEK_MARKET",
            board=replace(
                market.board,
                mode="PRIOR_WEEK_MARKET",
                stamp=replace(market.board.stamp, fresh=False),
            ),
            chart_fairness_available=False,
            consolidation_premium_available=False,
        )
        targets = discover_trade_targets(
            snapshot, projections=projections, selected_board=selected,
            market_ecr_board=market_ecr, trade_market=market,
            config=target_config(),
        )
        result = optimize_target_packages(
            snapshot, projections=projections, selected_board=selected,
            market_ecr_board=market_ecr, trade_market=market,
            target_result=targets, config=optimizer_config(),
            options=permissive_options(),
        )
        self.assertTrue(result.evaluated_decisions)
        self.assertTrue(all(
            row.market_fairness.status == "PRIOR_WEEK_MARKET"
            and not row.market_fairness.premium_sensitivity
            and not row.accepted
            for row in result.evaluated_decisions
        ))

    def test_unfunded_lanes_leave_targets_as_deterministic_watch_items(self) -> None:
        snapshot, projections, selected, market_ecr, market, targets = self._inputs()
        config = optimizer_config(exact_budgets=uniform_exact_budgets(0))
        first = optimize_target_packages(
            snapshot,
            projections=projections,
            selected_board=selected,
            market_ecr_board=market_ecr,
            trade_market=market,
            target_result=targets,
            config=config,
            options=permissive_options(),
        )
        second = optimize_target_packages(
            snapshot,
            projections=projections,
            selected_board=selected,
            market_ecr_board=market_ecr,
            trade_market=market,
            target_result=targets,
            config=config,
            options=permissive_options(),
        )

        self.assertEqual(first.evidence_hash, second.evidence_hash)
        self.assertFalse(first.opportunities)
        self.assertTrue(first.target_statuses)
        self.assertTrue(
            all(
                row.status == "WATCH"
                and not row.partner_credible_offer_found
                and not row.obtainable
                for row in first.target_statuses
            )
        )
        self.assertTrue(all(row.attempted == 0 for row in first.coverage))

    def test_optimizer_rejects_value_evidence_that_differs_from_target_discovery(self) -> None:
        snapshot, projections, selected, market_ecr, market, targets = self._inputs()
        changed_selected = replace(
            selected,
            players=tuple(
                replace(row, reconciled_vorp=row.reconciled_vorp + 1.0)
                if row.player_id == "o_buy"
                else row
                for row in selected.players
            ),
        )

        with self.assertRaises(CoverageIncomplete):
            optimize_target_packages(
                snapshot,
                projections=projections,
                selected_board=changed_selected,
                market_ecr_board=market_ecr,
                trade_market=market,
                target_result=targets,
                config=optimizer_config(exact_budgets=uniform_exact_budgets(0)),
                options=permissive_options(),
            )


class TargetOptimizerConfigTests(unittest.TestCase):
    def test_requires_complete_nonnegative_lane_size_budgets(self) -> None:
        with self.assertRaises(ValueError):
            replace(optimizer_config(), exact_budgets=uniform_exact_budgets(1)[:-1])
        with self.assertRaises(ValueError):
            replace(optimizer_config(), fair_market_band_ratio=11.0)
        with self.assertRaises(ValueError):
            replace(optimizer_config(), outgoing_pool_limit=0)
        with self.assertRaises(ValueError):
            ExactEvaluationBudget("BUY_LOW", "2-for-1", -1)
        with self.assertRaises(ValueError):
            replace(optimizer_config(), consolidation_premium_policy_id="")
        with self.assertRaises(ValueError):
            replace(optimizer_config(), consolidation_premium_ratio=-0.01)
        with self.assertRaises(ValueError):
            replace(optimizer_config(), minimum_consolidation_starter_upgrade=0.0)


if __name__ == "__main__":
    unittest.main()
