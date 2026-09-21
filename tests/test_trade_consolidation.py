from __future__ import annotations

import unittest
from dataclasses import replace

from roster_theory.core.models import Projection
from roster_theory.inseason.evaluation import build_weekly_projection_matrix
from roster_theory.trade.consolidation import analyze_consolidation
from roster_theory.trade.evaluation import (
    PlayerAsset,
    TradePackage,
    evaluate_trade,
)
from roster_theory.trade.target_optimizer import _context, optimize_target_packages
from roster_theory.trade.targets import discover_trade_targets
from tests.test_trade_target_optimizer import optimizer_config, permissive_options
from tests.test_trade_targets import config as target_config
from tests.test_trade_targets import fixture


POINTS = {
    "u_rb": 16.0,
    "o_buy": 2.0,
    "o_need": 3.0,
    "fa_rb": 14.0,
}


def consolidation_fixture(*, weak_add: bool = False):
    snapshot, projections, selected, market_ecr, market = fixture()
    projections = tuple(
        replace(row, league_points=POINTS.get(row.player_id, row.league_points))
        for row in projections
    )
    if weak_add:
        weak_player = replace(
            next(row for row in snapshot.players if row.player_id == "fa_rb"),
            player_id="fa_weak",
            name="Weak waiver add",
        )
        snapshot = replace(
            snapshot,
            players=(*snapshot.players, weak_player),
            free_agent_ids=(*snapshot.free_agent_ids, "fa_weak"),
        )
        projections += tuple(
            Projection(
                player_id="fa_weak",
                horizon="WEEKLY",
                week=week,
                raw_stats=(),
                league_points=1.0,
                source="fixture",
            )
            for week in (1, 2, 3)
        )
        selected = replace(
            selected,
            players=(
                *selected.players,
                replace(
                    next(row for row in selected.players if row.player_id == "fa_rb"),
                    player_id="fa_weak",
                    reconciled_vorp=1.0,
                    positional_vorp=1.0,
                ),
            ),
        )
        market_ecr = replace(
            market_ecr,
            players=(
                *market_ecr.players,
                replace(
                    next(row for row in market_ecr.players if row.player_id == "fa_rb"),
                    player_id="fa_weak",
                    reconciled_vorp=1.0,
                    positional_vorp=1.0,
                ),
            ),
        )
    return snapshot, projections, selected, market_ecr, market


def exact_consolidation(*, add_override: str | None = None, drop_override: str | None = None):
    snapshot, projections, selected, market_ecr, _ = consolidation_fixture(weak_add=True)
    projections = tuple(
        replace(row, league_points=20.0) if row.player_id == "u_rb" else row
        for row in projections
    )
    options = replace(
        permissive_options(),
        add_override=add_override,
        drop_override=drop_override,
    )
    package = TradePackage(
        roster_a_id="1",
        roster_b_id="2",
        from_a=(PlayerAsset("u_rb"), PlayerAsset("u_wr_depth")),
        from_b=(PlayerAsset("o_con"),),
    )
    context = _context(snapshot)
    matrix = build_weekly_projection_matrix(context, projections)
    evaluation = evaluate_trade(
        snapshot,
        package,
        projections=projections,
        selected_board=selected,
        market_board=market_ecr,
        options=options,
        projection_matrix=matrix,
    )
    evidence = analyze_consolidation(
        snapshot,
        evaluation,
        context=context,
        matrix=matrix,
        options=options,
        minimum_starter_upgrade=1.0,
        minimum_partner_lineup_use=0.0,
        minimum_partner_depth_use=0.0,
    )
    return evaluation, evidence


class ConsolidationTests(unittest.TestCase):
    def test_premium_adjusts_construction_and_fairness_without_changing_intrinsic_win(self) -> None:
        snapshot, projections, selected, market_ecr, market = consolidation_fixture()
        chart_values = {"u_rb": 20.0, "u_wr_depth": 13.0, "o_con": 30.0}
        market = replace(
            market,
            board=replace(
                market.board,
                prices=tuple(
                    replace(row, value=chart_values.get(row.player_id, row.value))
                    for row in market.board.prices
                ),
            ),
        )
        targets = discover_trade_targets(
            snapshot,
            projections=projections,
            selected_board=selected,
            market_ecr_board=market_ecr,
            trade_market=market,
            config=target_config(),
        )
        config = replace(
            optimizer_config(fair_ratio=0.0, fair_floor=0.01),
            construction_market_band_ratio=0.0,
            construction_market_band_floor=0.01,
        )
        result = optimize_target_packages(
            snapshot,
            projections=projections,
            selected_board=selected,
            market_ecr_board=market_ecr,
            trade_market=market,
            target_result=targets,
            config=config,
            options=permissive_options(),
        )
        row = next(
            row for row in result.evaluated_decisions
            if row.lane == "CONSOLIDATE"
            and row.sent_player_ids == ("u_rb", "u_wr_depth")
            and row.received_player_ids == ("o_con",)
        )
        self.assertTrue(row.accepted)
        self.assertEqual(row.intrinsic_outcome, "WIN")
        self.assertEqual(row.market_fairness.raw_user_price_delta, -3.0)
        self.assertEqual(row.market_fairness.consolidation_premium_value, 3.0)
        self.assertEqual(row.market_fairness.premium_adjusted_received_value, 33.0)
        self.assertEqual(row.market_fairness.user_price_delta, 0.0)
        self.assertEqual(row.market_fairness.status, "FAIR")

    def test_mutually_useful_package_prints_premium_add_drop_and_both_asset_uses(self) -> None:
        snapshot, projections, selected, market_ecr, market = consolidation_fixture()
        targets = discover_trade_targets(
            snapshot,
            projections=projections,
            selected_board=selected,
            market_ecr_board=market_ecr,
            trade_market=market,
            config=target_config(),
        )
        result = optimize_target_packages(
            snapshot,
            projections=projections,
            selected_board=selected,
            market_ecr_board=market_ecr,
            trade_market=market,
            target_result=targets,
            config=optimizer_config(),
            options=permissive_options(),
        )
        row = next(
            row for row in result.evaluated_decisions
            if row.lane == "CONSOLIDATE"
            and row.sent_player_ids == ("u_rb", "u_wr_depth")
            and row.received_player_ids == ("o_con",)
        )
        self.assertTrue(row.accepted)
        self.assertEqual(row.package_size, "2-for-1")
        self.assertTrue(
            all(
                decision.package_size == "2-for-1"
                for decision in result.evaluated_decisions
                if decision.lane == "CONSOLIDATE"
            )
        )
        self.assertEqual(row.market_fairness.consolidation_premium_policy_id, "fixture-premium-v1")
        self.assertEqual(row.market_fairness.consolidation_premium_value, 9.0)
        self.assertEqual(row.market_fairness.raw_user_price_delta, -40.0)
        self.assertEqual(row.market_fairness.user_price_delta, -31.0)
        self.assertIsNotNone(row.consolidation)
        self.assertTrue(row.consolidation.passes)
        self.assertEqual(row.consolidation.user_add_player_id, "fa_rb")
        self.assertEqual(row.consolidation.partner_drop_player_id, "o_need")
        self.assertEqual(
            {asset.player_id: asset.use for asset in row.consolidation.partner_asset_uses},
            {"u_rb": "STARTER", "u_wr_depth": "STARTER"},
        )
        self.assertTrue(all(asset.marginal_lineup_points > 0.0 for asset in row.consolidation.partner_asset_uses))
        self.assertIsNotNone(row.consolidation.user_add_marginal_lineup_points)
        self.assertIsNotNone(row.consolidation.partner_drop_lineup_effect)
        self.assertTrue(any(
            opportunity.lane == "CONSOLIDATE"
            and opportunity.sent_player_ids == row.sent_player_ids
            and opportunity.consolidation is not None
            for opportunity in result.opportunities
        ))

    def test_correct_drop_and_add_reverse_the_exact_consolidation_outcome(self) -> None:
        _, good = exact_consolidation()
        _, bad_drop = exact_consolidation(drop_override="u_wr_depth")
        _, bad_add = exact_consolidation(add_override="fa_weak")
        self.assertTrue(good.passes)
        self.assertEqual(good.user_add_player_id, "fa_rb")
        self.assertEqual(good.partner_drop_player_id, "o_need")
        self.assertFalse(bad_drop.passes)
        self.assertEqual(bad_drop.partner_drop_player_id, "u_wr_depth")
        self.assertEqual(bad_drop.partner_asset_uses[1].use, "DROPPED")
        self.assertFalse(bad_add.passes)
        self.assertEqual(bad_add.user_add_player_id, "fa_weak")
        self.assertFalse(bad_add.starter_upgrade_passed)

    def test_additive_value_mirage_rejects_an_unusable_second_asset(self) -> None:
        snapshot, projections, selected, market_ecr, market = consolidation_fixture()
        projections = tuple(
            replace(row, league_points=1.0) if row.player_id == "u_te" else row
            for row in projections
        )
        targets = discover_trade_targets(
            snapshot,
            projections=projections,
            selected_board=selected,
            market_ecr_board=market_ecr,
            trade_market=market,
            config=target_config(),
        )
        result = optimize_target_packages(
            snapshot,
            projections=projections,
            selected_board=selected,
            market_ecr_board=market_ecr,
            trade_market=market,
            target_result=targets,
            config=optimizer_config(),
            options=permissive_options(),
        )
        row = next(
            row for row in result.evaluated_decisions
            if row.lane == "CONSOLIDATE"
            and row.sent_player_ids == ("u_rb", "u_te")
            and row.received_player_ids == ("o_con",)
        )
        self.assertTrue(row.market_fairness.within_band)
        self.assertFalse(row.accepted)
        self.assertEqual(row.reason, "CONSOLIDATION_PARTNER_ASSET_USE")
        self.assertEqual(row.consolidation.partner_asset_uses[1].use, "UNUSED")


if __name__ == "__main__":
    unittest.main()
