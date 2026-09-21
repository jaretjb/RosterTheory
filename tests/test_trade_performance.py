from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from roster_theory.core.errors import CoverageIncomplete
from roster_theory.trade.performance import (
    CompletedPerformanceOutcome,
    PerformancePolicy,
    PregameExpectation,
    build_performance_evidence,
)
from roster_theory.trade.targets import discover_trade_targets
from tests.test_trade_targets import config as target_config
from tests.test_trade_targets import fixture


UTC = timezone.utc
GAME = {
    1: datetime(2026, 9, 13, 17, tzinfo=UTC),
    2: datetime(2026, 9, 20, 17, tzinfo=UTC),
    3: datetime(2026, 9, 27, 17, tzinfo=UTC),
}


def policy(*, minimum_games: int = 1, maximum_age_days: float = 14.0) -> PerformancePolicy:
    return PerformancePolicy(
        policy_id="fixture-performance-v1",
        window_weeks=3,
        prior_games=2.0,
        minimum_games=minimum_games,
        signal_threshold=0.1,
        maximum_age_days=maximum_age_days,
        point_scales=(("QB", 4.0), ("RB", 2.0), ("WR", 2.0), ("TE", 2.0)),
        rank_scales=(("QB", 10.0), ("RB", 10.0), ("WR", 10.0), ("TE", 10.0)),
    )


def pregame(
    player_id: str,
    week: int,
    *,
    points: float | None = 10.0,
    rank: float | None = 10.0,
    captured_at: datetime | None = None,
) -> PregameExpectation:
    return PregameExpectation(
        league_key="fixture",
        season=2026,
        player_id=player_id,
        week=week,
        position="TE",
        captured_at=captured_at or GAME[week] - timedelta(hours=2),
        projected_points=points,
        projected_position_rank=rank,
        scoring_fingerprint="league-half-ppr-v1",
        source="pregame fixture",
    )


def outcome(
    player_id: str,
    week: int,
    *,
    points: float | None = 14.0,
    rank: float | None = 6.0,
    availability: str = "PLAYED",
    captured_at: datetime | None = None,
) -> CompletedPerformanceOutcome:
    return CompletedPerformanceOutcome(
        league_key="fixture",
        season=2026,
        player_id=player_id,
        week=week,
        position="TE",
        game_started_at=GAME[week],
        game_completed_at=GAME[week] + timedelta(hours=3),
        captured_at=captured_at or GAME[week] + timedelta(hours=4),
        actual_points=points,
        actual_position_rank=rank,
        availability=availability,
        scoring_fingerprint="league-half-ppr-v1",
        source="completed fixture",
    )


class PerformanceEvidenceTests(unittest.TestCase):
    def test_position_scales_and_disagreeing_metrics_do_not_fake_signal(self) -> None:
        gate = replace(policy(), signal_threshold=0.5)
        te = build_performance_evidence(
            "fixture", 2026, 1, GAME[1] + timedelta(hours=5),
            expectations=(pregame("te", 1, rank=None),),
            outcomes=(outcome("te", 1, rank=None),), policy=gate,
        )
        qb = build_performance_evidence(
            "fixture", 2026, 1, GAME[1] + timedelta(hours=5),
            expectations=(replace(pregame("qb", 1, rank=None), position="QB"),),
            outcomes=(replace(outcome("qb", 1, rank=None), position="QB"),),
            policy=gate,
        )
        self.assertEqual(te.contexts[0].signal, "OUTPERFORMING")
        self.assertEqual(qb.contexts[0].signal, "NEUTRAL")
        conflict = build_performance_evidence(
            "fixture", 2026, 1, GAME[1] + timedelta(hours=5),
            expectations=(pregame("conflict", 1),),
            outcomes=(outcome("conflict", 1, rank=18.0),),
            policy=policy(),
        )
        self.assertEqual(conflict.contexts[0].signal, "NEUTRAL")
        self.assertIn("disagree", conflict.contexts[0].warnings[0])

    def test_point_and_rank_use_their_own_latest_pregame_captures(self) -> None:
        point = pregame("o_buy", 1, points=10.0, rank=None)
        rank = pregame(
            "o_buy", 1, points=None, rank=12.0,
            captured_at=GAME[1] - timedelta(hours=1),
        )
        result = build_performance_evidence(
            "fixture", 2026, 1, GAME[1] + timedelta(hours=5),
            expectations=(point, rank), outcomes=(outcome("o_buy", 1),),
            policy=policy(),
        )
        row = result.residuals[0]
        self.assertEqual(row.point_residual, 4.0)
        self.assertEqual(row.rank_residual, 6.0)
        self.assertEqual(row.point_expectation_captured_at, point.captured_at)
        self.assertEqual(row.rank_expectation_captured_at, rank.captured_at)
        self.assertTrue(row.included)
        with_postgame = build_performance_evidence(
            "fixture", 2026, 1, GAME[1] + timedelta(hours=5),
            expectations=(point, rank, pregame(
                "o_buy", 1, points=99.0, rank=1.0,
                captured_at=GAME[1] + timedelta(minutes=1),
            )),
            outcomes=(outcome("o_buy", 1),), policy=policy(),
        )
        self.assertEqual(with_postgame.residuals[0].point_residual, 4.0)
        self.assertEqual(with_postgame.residuals[0].rank_residual, 6.0)
        with self.assertRaises(CoverageIncomplete):
            build_performance_evidence(
                "fixture", 2026, 1, GAME[1] + timedelta(hours=5),
                expectations=(point, replace(point, projected_points=99.0)),
                outcomes=(outcome("o_buy", 1),), policy=policy(),
            )
        with self.assertRaisesRegex(CoverageIncomplete, "Ambiguous simultaneous"):
            build_performance_evidence(
                "fixture", 2026, 1, GAME[1] + timedelta(hours=5),
                expectations=(
                    point,
                    replace(point, source="other pregame source", projected_points=99.0),
                ),
                outcomes=(outcome("o_buy", 1),), policy=policy(),
            )

    def test_rolling_origin_excludes_future_and_shrinks_point_and_rank_surprise(self) -> None:
        captures = (
            pregame("o_buy", 1),
            pregame("o_buy", 2, points=12.0, rank=8.0),
        )
        outcomes = (
            outcome("o_buy", 1),
            outcome("o_buy", 2, points=4.0, rank=16.0),
        )
        first = build_performance_evidence(
            "fixture", 2026, 1, GAME[1] + timedelta(hours=5),
            expectations=captures, outcomes=outcomes, policy=policy(),
        )
        self.assertEqual(first.contexts[0].signal, "OUTPERFORMING")
        self.assertEqual(first.contexts[0].sample_size, 1)
        self.assertEqual(first.contexts[0].shrunk_point_residual, 1.333333)
        self.assertEqual(first.contexts[0].shrunk_rank_residual, 1.333333)
        self.assertEqual(first.residuals[1].exclusion_reason, "FUTURE_WEEK")
        self.assertIsNone(first.residuals[1].actual_points)
        self.assertIsNone(first.residuals[1].actual_position_rank)
        before_capture = build_performance_evidence(
            "fixture", 2026, 2, GAME[2] + timedelta(hours=3, minutes=30),
            expectations=captures, outcomes=outcomes, policy=policy(),
        )
        self.assertEqual(
            before_capture.residuals[1].exclusion_reason, "FUTURE_OUTCOME_CAPTURE"
        )
        self.assertIsNone(before_capture.residuals[1].actual_points)
        second = build_performance_evidence(
            "fixture", 2026, 2, GAME[2] + timedelta(hours=5),
            expectations=captures, outcomes=outcomes, policy=policy(),
        )
        self.assertEqual(second.contexts[0].signal, "UNDERPERFORMING")
        self.assertEqual(second.contexts[0].shrunk_point_residual, -1.0)
        self.assertEqual(second.contexts[0].shrunk_rank_residual, -1.0)
        self.assertEqual(second.contexts[0].sample_size, 2)
        self.assertEqual(second.residuals[1].point_residual, -8.0)
        self.assertEqual(second.residuals[1].rank_residual, -8.0)
        self.assertEqual(second.evidence_hash, build_performance_evidence(
            "fixture", 2026, 2, GAME[2] + timedelta(hours=5),
            expectations=captures, outcomes=outcomes, policy=policy(),
        ).evidence_hash)

    def test_exclusions_keep_postgame_bye_inactive_partial_and_incompatible_rows(self) -> None:
        captures = tuple(pregame(f"p{week}", week) for week in (1, 2, 3))
        captures += (
            pregame("post", 1, captured_at=GAME[1] + timedelta(minutes=1)),
            pregame("wrong", 1),
            pregame("rank", 1, points=None, rank=15.0),
        )
        outcomes = (
            outcome("p1", 1, availability="BYE"),
            outcome("p2", 2, availability="INACTIVE"),
            outcome("p3", 3, availability="PARTIAL"),
            outcome("post", 1),
            replace(outcome("wrong", 1), scoring_fingerprint="other-scoring"),
            outcome("rank", 1, points=None, rank=9.0),
        )
        result = build_performance_evidence(
            "fixture", 2026, 3, GAME[3] + timedelta(hours=5),
            expectations=captures, outcomes=outcomes, policy=policy(),
        )
        reasons = {row.player_id: row.exclusion_reason for row in result.residuals}
        self.assertEqual(reasons["p1"], "BYE")
        self.assertEqual(reasons["p2"], "INACTIVE")
        self.assertEqual(reasons["p3"], "PARTIAL")
        self.assertEqual(reasons["post"], "POSTGAME_OR_FUTURE_CAPTURE")
        self.assertEqual(reasons["wrong"], "SCORING_MISMATCH")
        rank = next(row for row in result.residuals if row.player_id == "rank")
        self.assertTrue(rank.included)
        self.assertIsNone(rank.point_residual)
        self.assertEqual(rank.rank_residual, 6.0)
        self.assertTrue(result.warnings)

    def test_small_or_stale_samples_cannot_support_target_or_cross_league(self) -> None:
        capture = pregame("o_buy", 1)
        played = outcome("o_buy", 1, points=3.0, rank=18.0)
        as_of = GAME[1] + timedelta(hours=5)
        small = build_performance_evidence(
            "fixture", 2026, 1, as_of,
            expectations=(capture,), outcomes=(played,), policy=policy(minimum_games=2),
        )
        self.assertFalse(small.contexts[0].compatible)
        self.assertIn("too small", small.contexts[0].warnings[0])
        stale = build_performance_evidence(
            "fixture", 2026, 1, as_of + timedelta(days=3),
            expectations=(capture,), outcomes=(played,), policy=policy(maximum_age_days=1),
        )
        self.assertFalse(stale.contexts[0].fresh)
        self.assertFalse(stale.contexts[0].compatible)
        with self.assertRaises(CoverageIncomplete):
            build_performance_evidence(
                "other-league", 2026, 1, as_of,
                expectations=(capture,), outcomes=(played,), policy=policy(),
            )

    def test_target_context_keeps_expert_board_order_and_cannot_make_target_alone(self) -> None:
        snapshot, projections, selected, market_ecr, market = fixture()
        capture = pregame("o_buy", 1, points=12.0)
        played = outcome("o_buy", 1, points=3.0, rank=18.0)
        evidence = build_performance_evidence(
            "fixture", 2026, 1, snapshot.captured_at,
            expectations=(capture,), outcomes=(played,), policy=policy(),
        )
        before = tuple(row.player_id for row in selected.players)
        result = discover_trade_targets(
            snapshot,
            projections=projections,
            selected_board=selected,
            market_ecr_board=market_ecr,
            trade_market=market,
            config=target_config(),
            performance_context=evidence.contexts,
        )
        self.assertEqual(before, tuple(row.player_id for row in selected.players))
        buy = next(row for row in result.targets if row.kind == "BUY_LOW")
        self.assertEqual(buy.performance_support, "SUPPORTS")
        self.assertEqual(buy.performance.sample_size, 1)
        stale = replace(evidence.contexts[0], fresh=False)
        stale_result = discover_trade_targets(
            snapshot,
            projections=projections,
            selected_board=selected,
            market_ecr_board=market_ecr,
            trade_market=market,
            config=target_config(),
            performance_context=(stale,),
        )
        stale_buy = next(row for row in stale_result.targets if row.kind == "BUY_LOW")
        self.assertEqual(stale_buy.performance_support, "EXCLUDED_STALE")
        self.assertEqual(
            tuple((row.kind, row.player_id) for row in result.targets),
            tuple((row.kind, row.player_id) for row in stale_result.targets),
        )


if __name__ == "__main__":
    unittest.main()
