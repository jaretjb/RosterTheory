from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import datetime, timezone

from roster_theory.core.isotonic import MonotoneCurve
from roster_theory.core.models import FantasyTeam, LeagueRules, Player, Projection
from roster_theory.core.provenance import AnalysisManifest, DataStamp
from roster_theory.trade.boards import BoardPlayerValue, ValueBoard
from roster_theory.trade.market import (
    TradeMarketBoard,
    TradeMarketEvidence,
    TradeMarketPrice,
    ecr_proxy,
)
from roster_theory.trade.schedule import EvaluationWeek
from roster_theory.trade.snapshot import SnapshotCompleteness, TradeSnapshot
from roster_theory.trade.targets import (
    TargetDiscoveryConfig,
    TargetPerformanceContext,
    discover_trade_targets,
    summarize_projection_warnings,
)


PLAYER_ROWS = (
    ("o_buy", "Discount Tight End", "TE", 10.0),
    ("o_con", "Consolidation Receiver", "WR", 20.0),
    ("o_need", "Need Fit Runner", "RB", 13.0),
    ("u_rb", "User Runner", "RB", 12.0),
    ("u_wr_depth", "User Receiver Depth", "WR", 8.0),
    ("u_flex", "User Flex", "RB", 7.0),
    ("u_te", "User Tight End", "TE", 4.0),
    ("u_sell", "Market Premium Receiver", "WR", 8.0),
    ("o_fill", "Partner Filler", "RB", 6.0),
    ("fa_rb", "Waiver Runner", "RB", 3.0),
)

SELECTED_RANKS = {
    "o_buy": 1,
    "o_con": 2,
    "o_need": 3,
    "u_rb": 4,
    "u_wr_depth": 5,
    "u_flex": 6,
    "u_te": 7,
    "u_sell": 8,
    "o_fill": 9,
    "fa_rb": 10,
}

MARKET_RANKS = {
    "u_sell": 1,
    "o_con": 2,
    "o_need": 3,
    "u_rb": 4,
    "u_wr_depth": 5,
    "u_flex": 6,
    "u_te": 7,
    "o_buy": 8,
    "o_fill": 9,
    "fa_rb": 10,
}


def fixture() -> tuple[
    TradeSnapshot,
    tuple[Projection, ...],
    ValueBoard,
    ValueBoard,
    TradeMarketEvidence,
]:
    now = datetime.now(timezone.utc)
    players = tuple(
        Player(
            player_id=player_id,
            name=name,
            positions=(position,),
            sleeper_id=player_id,
            nfl_team="SEA",
            active=True,
            identity_confidence="exact",
        )
        for player_id, name, position, _ in PLAYER_ROWS
    )
    teams = (
        FantasyTeam(
            "1",
            "user",
            "User Team",
            ("u_rb", "u_wr_depth", "u_flex", "u_te", "u_sell"),
        ),
        FantasyTeam(
            "2",
            "partner",
            "Partner Team",
            ("o_buy", "o_con", "o_need", "o_fill"),
        ),
    )
    weeks = tuple(
        EvaluationWeek(
            week=week,
            playoff=week == 3,
            fantasy_matchup_rows=2,
            fantasy_matchups_complete=True,
            bye_teams=(),
            nfl_schedule_complete=True,
        )
        for week in (1, 2, 3)
    )
    stamp = DataStamp(
        source="fixture",
        endpoint="fixture://targets",
        captured_at=now,
        season=2026,
        week=2,
        horizon_start=1,
        horizon_end=3,
        fresh=True,
    )
    manifest = AnalysisManifest.build(
        league_id="league",
        user_id="user",
        current_week=1,
        horizon_start=1,
        horizon_end=3,
        configuration={"fixture": "targets"},
        normalized_inputs=(players, teams, weeks),
        data_stamps=(stamp,),
    )
    snapshot = TradeSnapshot(
        schema_version=1,
        product="TRADE ASSISTANT",
        league_key="fixture",
        captured_at=now,
        ranking_horizon="ROS",
        current=True,
        league=LeagueRules(
            league_id="league",
            season=2026,
            team_count=2,
            roster_positions=("RB", "WR", "TE", "FLEX", "BN"),
            scoring=(("rec", 0.5),),
            playoff_start_week=3,
            championship_week=3,
        ),
        user_roster_id="1",
        teams=teams,
        players=players,
        weeks=weeks,
        owner_by_player=tuple(
            sorted(
                (
                    *((player_id, "1") for player_id in teams[0].player_ids),
                    *((player_id, "2") for player_id in teams[1].player_ids),
                )
            )
        ),
        free_agent_ids=("fa_rb",),
        tradeable_player_ids=tuple(player_id for team in teams for player_id in team.player_ids),
        transaction_ids=(),
        stamps=(stamp,),
        capabilities=(("valuation_inputs_loaded", True),),
        completeness=SnapshotCompleteness(True, True, True, True, True, True),
        warnings=(),
        manifest=manifest,
    )
    projections = tuple(
        Projection(
            player_id=player_id,
            horizon="WEEKLY",
            week=week,
            raw_stats=(),
            league_points=points,
            source="fixture",
        )
        for player_id, _, _, points in PLAYER_ROWS
        for week in (1, 2, 3)
    )

    def board(board_id: str, ranks: dict[str, int]) -> ValueBoard:
        rows = tuple(
            BoardPlayerValue(
                player_id=player_id,
                position=position,
                position_rank=rank,
                overall_rank=rank,
                raw_projection=points * 3,
                raw_projection_rank=rank,
                aligned_points=points * 3,
                replacement_points=0.0,
                positional_vorp=(2.0 if player_id == "o_fill" else points),
                reconciled_vorp=(2.0 if player_id == "o_fill" else points),
                tier=1 if rank <= 3 else 2 if rank <= 7 else 3,
            )
            for player_id, _, position, points in PLAYER_ROWS
            for rank in (ranks[player_id],)
        )
        return ValueBoard(
            board_id=board_id,
            horizon="ROS",
            players=rows,
            curves=(),
            replacement_baselines=(("RB", 3.0), ("WR", 0.0), ("TE", 0.0)),
            overall_curve=MonotoneCurve(((1.0, 1.0),), len(rows), 1),
            complete=True,
            stamps=(stamp,),
        )

    selected = board("selected_final", SELECTED_RANKS)
    market_ecr = board("market", MARKET_RANKS)
    positions = {player_id: position for player_id, _, position, _ in PLAYER_ROWS}
    prices = tuple(
        TradeMarketPrice(
            player_id=player_id,
            position=positions[player_id],
            overall_rank=rank,
            position_rank=rank,
            value=float(110 - (rank * 10)),
            provider_change_7d=(5.0 if player_id == "u_sell" else -3.0),
            provider_change_30d=1.0,
            previous_board_change=2.0,
        )
        for player_id, rank in sorted(MARKET_RANKS.items(), key=lambda row: row[1])
    )
    trade_board = TradeMarketBoard(
        schema_version=1,
        mode="STATS_GUY_FANTASY_API",
        provider="Stats Guy Fantasy",
        format="non_sf_redraft",
        as_of=now,
        captured_at=now,
        season=2026,
        week=2,
        scoring_variant="reception blend",
        te_premium_variant="TEP blend",
        league_format_compatible=True,
        league_scoring_exact=False,
        prices=prices,
        source_total=len(prices),
        normalized_count=len(prices),
        complete=True,
        source_url="https://example.test/trade-values",
        attribution="Fixture trade values",
        authorization_basis="fixture",
        warnings=("Provider scoring is blended",),
        stamp=stamp,
        evidence_hash="fixture",
    )
    evidence = TradeMarketEvidence(
        mode=trade_board.mode,
        board=trade_board,
        chart_price_available=True,
        chart_change_available=True,
        chart_fairness_available=True,
        consolidation_premium_available=True,
        warnings=trade_board.warnings,
    )
    return snapshot, projections, selected, market_ecr, evidence


def config() -> TargetDiscoveryConfig:
    return TargetDiscoveryConfig(
        policy_id="golden-fixture-v1",
        material_percentile_gap=0.20,
        minimum_lineup_gain=1.0,
        consolidation_lineup_gain=20.0,
        maximum_disposable_lineup_cost=3.0,
        max_targets_per_lane=5,
    )


class TargetDiscoveryTests(unittest.TestCase):
    def test_missing_projection_warnings_are_aggregated_not_silenced(self) -> None:
        warnings = summarize_projection_warnings((
            "p1 Week 2: missing projection",
            "p1 Week 3: missing projection",
            "p2 Week 2: missing projection",
            "Provider is stale",
        ))
        self.assertEqual(len(warnings), 2)
        self.assertIn("3 player-week projections", warnings[1])
        self.assertIn("2 players", warnings[1])
        self.assertEqual(warnings[0], "Provider is stale")

    def test_golden_fixture_identifies_each_target_lane_and_owner(self) -> None:
        snapshot, projections, selected, market_ecr, trade_market = fixture()
        now = snapshot.captured_at
        performance = (
            TargetPerformanceContext(
                player_id="o_buy",
                signal="UNDERPERFORMING",
                sample_size=2,
                as_of=now,
                compatible=True,
                shrunk_point_residual=-2.0,
                fresh=True,
                source="fixture",
            ),
            TargetPerformanceContext(
                player_id="u_sell",
                signal="OUTPERFORMING",
                sample_size=2,
                as_of=now,
                compatible=True,
                shrunk_point_residual=2.0,
                fresh=True,
                source="fixture",
            ),
        )
        result = discover_trade_targets(
            snapshot,
            projections=projections,
            selected_board=selected,
            market_ecr_board=market_ecr,
            trade_market=trade_market,
            config=config(),
            performance_context=performance,
        )
        by_lane = {target.kind: target for target in result.targets}

        self.assertEqual(by_lane["BUY_LOW"].player_id, "o_buy")
        self.assertEqual(by_lane["SELL_HIGH"].player_id, "u_sell")
        self.assertEqual(by_lane["CONSOLIDATE"].player_id, "o_con")
        self.assertEqual(by_lane["NEED_FIT"].player_id, "o_need")
        self.assertEqual(by_lane["BUY_LOW"].roster.owner_roster_id, "2")
        self.assertEqual(by_lane["SELL_HIGH"].roster.owner_roster_id, "1")
        self.assertEqual(by_lane["BUY_LOW"].performance_support, "SUPPORTS")
        self.assertEqual(by_lane["SELL_HIGH"].performance_support, "SUPPORTS")

    def test_cards_keep_intrinsic_market_team_and_freshness_evidence_separate(self) -> None:
        snapshot, projections, selected, market_ecr, trade_market = fixture()
        result = discover_trade_targets(
            snapshot,
            projections=projections,
            selected_board=selected,
            market_ecr_board=market_ecr,
            trade_market=trade_market,
            config=config(),
        )
        buy = next(target for target in result.targets if target.kind == "BUY_LOW")

        self.assertGreater(buy.intrinsic.percentile, buy.trade_price.percentile)
        self.assertNotEqual(buy.intrinsic.board_id, buy.market_ecr.board_id)
        self.assertEqual(buy.trade_price.percentile_source, "TRADE_MARKET")
        self.assertIsNotNone(buy.trade_price.raw_value)
        self.assertEqual(buy.roster.lineup_value_basis, "WEIGHTED_HORIZON_POINTS")
        self.assertGreater(buy.roster.user_standalone_lineup_gain or 0.0, 0.0)
        self.assertEqual(buy.intrinsic.stamps[0].captured_at, snapshot.captured_at)
        self.assertEqual(buy.trade_price.as_of, snapshot.captured_at)
        self.assertEqual(buy.roster.ownership_captured_at, snapshot.captured_at)
        self.assertTrue(buy.roster.ownership_current)
        self.assertTrue(buy.ranking_factors)
        self.assertFalse(any(factor.name == "score" for factor in buy.ranking_factors))

    def test_targets_remain_watch_without_performance_or_passing_package(self) -> None:
        snapshot, projections, selected, market_ecr, trade_market = fixture()
        first = discover_trade_targets(
            snapshot,
            projections=projections,
            selected_board=selected,
            market_ecr_board=market_ecr,
            trade_market=trade_market,
            config=config(),
        )
        second = discover_trade_targets(
            snapshot,
            projections=projections,
            selected_board=selected,
            market_ecr_board=market_ecr,
            trade_market=trade_market,
            config=config(),
        )

        self.assertEqual(first.evidence_hash, second.evidence_hash)
        self.assertEqual(len(first.targets), 4)
        for target in first.targets:
            self.assertEqual(target.status, "WATCH")
            self.assertFalse(target.partner_credible_offer_found)
            self.assertFalse(target.obtainable)
            self.assertFalse(target.roster.owner_preference_claimed)
            self.assertIsNone(target.performance)
            self.assertEqual(target.performance_support, "UNAVAILABLE")

    def test_ecr_proxy_keeps_targets_but_disables_chart_specific_evidence(self) -> None:
        snapshot, projections, selected, market_ecr, _ = fixture()
        result = discover_trade_targets(
            snapshot,
            projections=projections,
            selected_board=selected,
            market_ecr_board=market_ecr,
            trade_market=ecr_proxy("fixture chart unavailable"),
            config=config(),
        )
        buy = next(target for target in result.targets if target.kind == "BUY_LOW")

        self.assertEqual(result.pricing_mode, "ECR-PROXY")
        self.assertEqual(buy.trade_price.mode, "ECR-PROXY")
        self.assertEqual(buy.trade_price.percentile_source, "MARKET_ECR")
        self.assertIsNone(buy.trade_price.raw_value)
        self.assertIsNone(buy.trade_price.provider_change_7d)
        self.assertEqual(buy.market_gap.market_ecr_corroboration, "ECR_PROXY_ONLY")
        self.assertTrue(any("fairness" in warning for warning in buy.warnings))

    def test_partial_direct_chart_excludes_only_unpriced_targets(
        self,
    ) -> None:
        snapshot, projections, selected, market_ecr, evidence = fixture()
        assert evidence.board is not None
        partial_board = replace(
            evidence.board,
            prices=tuple(row for row in evidence.board.prices if row.player_id != "o_buy"),
            normalized_count=len(evidence.board.prices) - 1,
        )
        partial = replace(evidence, board=partial_board)
        result = discover_trade_targets(
            snapshot,
            projections=projections,
            selected_board=selected,
            market_ecr_board=market_ecr,
            trade_market=partial,
            config=config(),
        )

        self.assertEqual(result.pricing_mode, "STATS_GUY_FANTASY_API")
        self.assertTrue(any(
            row.player_id == "o_buy" and row.reason == "MISSING_TRADE_MARKET_PRICE"
            for row in result.exclusions
        ))
        self.assertTrue(any("lack a price" in warning for warning in result.warnings))
        self.assertTrue(all(target.player_id != "o_buy" for target in result.targets))
        self.assertTrue(all(
            target.trade_price.mode == "STATS_GUY_FANTASY_API"
            for target in result.targets
        ))

    def test_lane_order_and_limit_use_the_exposed_lexicographic_factors(self) -> None:
        snapshot, projections, selected, market_ecr, evidence = fixture()
        assert evidence.board is not None
        repriced = replace(
            evidence.board,
            prices=tuple(
                replace(row, overall_rank=10, value=10.0)
                if row.player_id == "o_con"
                else replace(row, overall_rank=2, value=90.0)
                if row.player_id == "fa_rb"
                else row
                for row in evidence.board.prices
            ),
        )
        result = discover_trade_targets(
            snapshot,
            projections=projections,
            selected_board=selected,
            market_ecr_board=market_ecr,
            trade_market=replace(evidence, board=repriced),
            config=replace(config(), max_targets_per_lane=1),
        )
        buy = next(target for target in result.targets if target.kind == "BUY_LOW")

        self.assertEqual(buy.player_id, "o_con")
        self.assertEqual(buy.rank_in_lane, 1)
        self.assertEqual(
            buy.ranking_factors[0].name,
            "intrinsic_discount_percentile",
        )
        self.assertTrue(
            any(
                row.player_id == "o_buy" and row.kind == "BUY_LOW" and row.reason == "LANE_LIMIT"
                for row in result.exclusions
            )
        )


class TargetDiscoveryConfigTests(unittest.TestCase):
    def test_requires_explicit_valid_threshold_policy(self) -> None:
        with self.assertRaises(ValueError):
            replace(config(), policy_id="")
        with self.assertRaises(ValueError):
            replace(config(), material_percentile_gap=1.1)
        with self.assertRaises(ValueError):
            replace(config(), max_targets_per_lane=0)


if __name__ == "__main__":
    unittest.main()
