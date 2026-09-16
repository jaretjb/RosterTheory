from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from roster_theory.core.models import RankObservation
from roster_theory.providers.fantasypros import NewsRecord
from roster_theory.providers.cache import DailyRequestBudget
from roster_theory.trade.backtest import (
    DraftProxyForecast,
    HorizonForecast,
    run_draft_proxy_backtest,
    run_rolling_origin_backtest,
    write_draft_proxy_backtest,
)
from roster_theory.trade.horizons import (
    EARLY_SEASON_DRAFT_ANCHOR,
    ROS,
    STOP_REVIEW,
    LongTermPlayer,
    SnapshotDatum,
    WeeklyPlayerSignal,
    capture_prospective_snapshot,
    choose_season_stage,
    compose_horizon_views,
    filter_ros_ballots,
    load_draft_anchor,
)
from roster_theory.trade.backtest_service import (
    historical_backtest_plan,
    load_historical_byes,
)
from roster_theory.trade.board_service import (
    POSITION_MINIMUMS,
    _input_calls,
    _ros_market_is_complete,
)


def ballot(
    player_id: str,
    position: str,
    expert_id: str,
    *,
    response_updated_at: str = "2026-09-05T12:00:00+00:00",
) -> RankObservation:
    return RankObservation(
        player_id=player_id,
        horizon="ROS",
        board_source="expert_ballot",
        expert_id=expert_id,
        position=position,
        position_rank=1.0,
        overall_rank=None,
        updated_at=response_updated_at,
    )


class BallotFreshnessTests(unittest.TestCase):
    def test_new_response_does_not_refresh_old_august_te_ballot(self) -> None:
        rows = (ballot("te1", "TE", "22"), ballot("rb1", "RB", "22"))
        result = filter_ros_ballots(
            rows,
            {
                ("22", "TE"): "2026-08-08 23:09:56",
                ("22", "RB"): "2026-09-02 17:01:32",
            },
            now=datetime(2026, 9, 5, 12, tzinfo=timezone.utc),
        )
        self.assertEqual([row.player_id for row in result.eligible], ["rb1"])
        self.assertEqual(result.excluded_expert_positions, (("22", "TE"),))
        self.assertEqual(result.exclusions[0].reason, "stale_position_ballot")

    def test_material_news_invalidates_only_affected_player_row(self) -> None:
        result = filter_ros_ballots(
            (ballot("p1", "RB", "a"), ballot("p2", "RB", "a")),
            {("a", "RB"): "2026-09-01T12:00:00+00:00"},
            (
                NewsRecord(
                    player_id="p1",
                    published_at="2026-09-02T12:00:00+00:00",
                    title="Placed on injured reserve",
                    category="injury",
                ),
            ),
            now=datetime(2026, 9, 5, 12, tzinfo=timezone.utc),
        )
        self.assertEqual([row.player_id for row in result.eligible], ["p2"])
        self.assertEqual(result.exclusions[0].player_id, "p1")
        self.assertEqual(result.exclusions[0].reason, "material_news_after_ballot")


class SeasonStageTests(unittest.TestCase):
    def test_draft_anchor_is_mandatory_during_week_one(self) -> None:
        decision = choose_season_stage(
            1,
            selected_ros_fresh=True,
            selected_ros_complete=True,
            market_ros_fresh=True,
            market_ros_complete=True,
        )
        self.assertEqual(decision.mode, EARLY_SEASON_DRAFT_ANCHOR)
        self.assertTrue(decision.usable)

    def test_week_two_switches_both_boards_or_retains_both_for_review(self) -> None:
        passing = choose_season_stage(
            2,
            selected_ros_fresh=True,
            selected_ros_complete=True,
            market_ros_fresh=True,
            market_ros_complete=True,
        )
        failing = choose_season_stage(2, selected_ros_fresh=True)
        self.assertEqual(passing.mode, ROS)
        self.assertIn("ROS", passing.selected_source)
        self.assertIn("ROS", passing.market_source)
        self.assertEqual(failing.mode, EARLY_SEASON_DRAFT_ANCHOR)
        self.assertTrue(failing.review_required)

    def test_failed_gate_after_week_two_stops_without_extension_approval(self) -> None:
        decision = choose_season_stage(3)
        self.assertEqual(decision.mode, STOP_REVIEW)
        self.assertFalse(decision.usable)
        self.assertTrue(decision.review_required)


class DualViewTests(unittest.TestCase):
    def test_bye_changes_current_use_but_not_long_term_value(self) -> None:
        long_term = (
            LongTermPlayer("p1", "RB", 1, 100.0, "final Draft selected", "2026-08-30T00:00:00+00:00"),
        )
        current = (
            WeeklyPlayerSignal(
                "p1",
                "RB",
                5,
                None,
                18.0,
                -2.0,
                "FantasyPros weekly",
                "2026-10-06T12:00:00+00:00",
                bye=True,
            ),
        )
        view = compose_horizon_views(long_term, current)[0]
        self.assertEqual((view.long_term_rank, view.long_term_value), (1, 100.0))
        self.assertEqual(view.current_adjusted_points, 0.0)
        self.assertEqual(view.current_availability, "BYE")
        self.assertIn("not long-term", view.warnings[0])


class ProspectiveSnapshotTests(unittest.TestCase):
    def test_snapshot_is_deterministic_and_rejects_future_information(self) -> None:
        cutoff = datetime(2026, 9, 8, 16, tzinfo=timezone.utc)
        rows = (
            SnapshotDatum("weekly_rank", "p2", "WR", 2, "FantasyPros", "2026-09-08T15:00:00+00:00"),
            SnapshotDatum("ros_rank", "p1", "RB", 1, "FantasyPros", "2026-09-08T14:00:00+00:00"),
        )
        with tempfile.TemporaryDirectory() as directory:
            first = Path(directory) / "one.json"
            second = Path(directory) / "two.json"
            capture_prospective_snapshot(first, season=2026, week=2, cutoff=cutoff, mode="LONG_TERM", data=rows)
            capture_prospective_snapshot(second, season=2026, week=2, cutoff=cutoff, mode="LONG_TERM", data=tuple(reversed(rows)))
            self.assertEqual(
                json.loads(first.read_text(encoding="utf-8"))["snapshot_hash"],
                json.loads(second.read_text(encoding="utf-8"))["snapshot_hash"],
            )
            with self.assertRaisesRegex(ValueError, "after its cutoff"):
                capture_prospective_snapshot(
                    first,
                    season=2026,
                    week=2,
                    cutoff=cutoff,
                    mode="LONG_TERM",
                    data=(SnapshotDatum("news", "p1", "RB", None, "News", "2026-09-08T17:00:00+00:00"),),
                )

    def test_final_draft_anchor_loads_selected_and_market_without_adp(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "board.csv"
            path.write_text(
                "scope,scoring,position,weighted_position_rank,ecr,weighted_overall_rank,overall_ecr,sleeper_id,adp\n"
                "skills_half_ppr,HALF,RB,1,2,3,4,p1,99\n",
                encoding="utf-8",
            )
            selected, market = load_draft_anchor(path, updated_at="2026-08-30T00:00:00+00:00")
        self.assertEqual(selected[0].position_rank, 1)
        self.assertEqual(market[0].position_rank, 2)
        self.assertEqual(selected[0].horizon, EARLY_SEASON_DRAFT_ANCHOR)
        self.assertNotIn("adp", selected[0].board_source)


def forecast(
    season: int,
    week: int,
    player: int,
    *,
    draft_rank: float,
    weekly_rank: float,
    adjusted_rank: float,
    points: float,
) -> DraftProxyForecast:
    return DraftProxyForecast(
        season=season,
        week=week,
        player_id=f"p{player}",
        position="RB",
        draft_rank=draft_rank,
        weekly_rank=weekly_rank,
        adjusted_weekly_rank=adjusted_rank,
        actual_points=points,
        actual_lineup_value=max(0.0, points - 10.0),
        forecast_cutoff=f"{season}-09-{week + 1:02d}T12:00:00+00:00",
        draft_published_at=f"{season}-08-30T12:00:00+00:00",
        weekly_published_at=f"{season}-09-{week + 1:02d}T11:00:00+00:00",
        outcome_available_at=f"{season}-12-30T12:00:00+00:00",
    )


class DraftProxyBacktestTests(unittest.TestCase):
    def test_historical_preflight_is_budgeted_and_cache_aware(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            plan, _, _ = historical_backtest_plan(
                (2024, 2025),
                (1, 2, 3),
                cache_dir=Path(directory),
                budget=DailyRequestBudget(limit=100),
            )
        # Per season and position: one Draft, one points, and three weekly calls.
        self.assertEqual(plan.fantasypros_calls, 40)
        self.assertEqual(plan.fantasypros_remaining_after_plan, 60)

    def test_week_two_value_plan_adds_joint_ros_freshness_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            plan, _, _ = _input_calls(
                2026,
                2,
                (2, 3),
                Path(directory),
                datetime(2026, 9, 20, tzinfo=timezone.utc),
                DailyRequestBudget(limit=100),
            )
        self.assertEqual(plan.fantasypros_calls, 12)
        self.assertIn("ros_experts", {call.name for call in plan.calls})
        material_news = next(call for call in plan.calls if call.name == "material_news")
        self.assertEqual(dict(material_news.parameters), {"limit": 100})

    def test_ros_market_gate_rejects_empty_or_draft_fallback_boards(self) -> None:
        self.assertEqual(POSITION_MINIMUMS["RB"], 60)
        datasets = tuple(
            SimpleNamespace(
                complete_horizon=True,
                horizon="ROS",
                observations=tuple(
                    SimpleNamespace(position=position, position_rank=index)
                    for index in range(1, minimum + 1)
                ),
            )
            for position, minimum in POSITION_MINIMUMS.items()
        )
        self.assertTrue(_ros_market_is_complete(datasets))
        self.assertFalse(
            _ros_market_is_complete(
                (SimpleNamespace(**{**datasets[0].__dict__, "observations": ()}), *datasets[1:])
            )
        )
        self.assertFalse(
            _ros_market_is_complete(
                (SimpleNamespace(**{**datasets[0].__dict__, "horizon": "DRAFT"}), *datasets[1:])
            )
        )

    def test_synthetic_historical_bye_template_covers_every_team(self) -> None:
        byes = load_historical_byes("examples/nfl_byes_template.json")
        self.assertEqual(set(byes), {2099})
        self.assertTrue(all(len(teams) == 32 for teams in byes.values()))
        self.assertEqual(byes[2099]["T01"], 5)
        self.assertEqual(byes[2099]["T32"], 12)

    def test_rolling_origin_reports_controls_early_weeks_modes_and_uncertainty(self) -> None:
        rows = []
        for season in (2024, 2025):
            for week in (1, 2, 3, 4):
                for player in (1, 2, 3, 4):
                    rows.append(
                        forecast(
                            season,
                            week,
                            player,
                            draft_rank=float(player),
                            weekly_rank=float(5 - player if week >= 3 else player),
                            adjusted_rank=float(player),
                            points=float(50 - player * 5),
                        )
                    )
        result = run_draft_proxy_backtest(rows, weights=(0.0, 0.5, 1.0))
        self.assertEqual(result.label, "DRAFT_PROXY")
        self.assertEqual(result.weights, (0.0, 0.5, 1.0))
        self.assertEqual({row.week for row in result.metrics}.intersection({1, 2, 3}), {1, 2, 3})
        self.assertEqual({row.signal_mode for row in result.metrics}, {"RAW", "MATCHUP_BYE_AWARE"})
        self.assertTrue(all(row.sample_size == 4 for row in result.metrics))
        self.assertTrue(all(row.point_standard_error >= 0 for row in result.metrics))
        self.assertTrue(any(row.draft_weight == 0.0 for row in result.metrics))
        self.assertTrue(any(row.draft_weight == 1.0 for row in result.metrics))
        self.assertIn("do not validate", result.warnings[1])
        with tempfile.TemporaryDirectory() as directory:
            path = write_draft_proxy_backtest(Path(directory) / "study.json", result)
            saved = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(saved["evidence_hash"], result.evidence_hash)

    def test_future_rank_is_rejected_as_leakage(self) -> None:
        rows = [
            forecast(2024, 1, player, draft_rank=player, weekly_rank=player, adjusted_rank=player, points=20 - player)
            for player in (1, 2)
        ] + [
            forecast(2025, 1, player, draft_rank=player, weekly_rank=player, adjusted_rank=player, points=20 - player)
            for player in (1, 2)
        ]
        bad = rows[0]
        rows[0] = DraftProxyForecast(
            **{
                **{field: getattr(bad, field) for field in bad.__dataclass_fields__},
                "weekly_published_at": "2024-10-01T00:00:00+00:00",
            }
        )
        with self.assertRaisesRegex(ValueError, "after forecast cutoff"):
            run_draft_proxy_backtest(rows)

    def test_general_harness_compares_all_unblended_controls_and_blends(self) -> None:
        rows = []
        for season in (2024, 2025):
            for player in (1, 2, 3):
                rows.append(
                    HorizonForecast(
                        season=season,
                        week=4,
                        player_id=f"p{player}",
                        position="RB",
                        long_term_rank=float(player),
                        weekly_rank=float(4 - player),
                        projection_rank=float(player),
                        actual_points=float(40 - player * 5),
                        actual_lineup_value=float(max(0, 25 - player * 5)),
                        forecast_cutoff=f"{season}-10-01T12:00:00+00:00",
                        long_term_published_at=f"{season}-09-30T12:00:00+00:00",
                        weekly_published_at=f"{season}-10-01T11:00:00+00:00",
                        projection_published_at=f"{season}-10-01T10:00:00+00:00",
                        outcome_available_at=f"{season}-12-31T12:00:00+00:00",
                    )
                )
        result = run_rolling_origin_backtest(rows, blend_weights=(0.5,))
        self.assertEqual(
            {row.candidate for row in result.metrics},
            {
                "LONG_TERM_ONLY",
                "WEEKLY_ONLY",
                "PROJECTION_ONLY",
                "BLEND_LONG_TERM_0.50",
            },
        )
        self.assertEqual(result.selected_candidates[0][0], 2025)
        self.assertIn("disabled", result.warnings[0])


if __name__ == "__main__":
    unittest.main()
