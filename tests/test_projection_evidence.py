from __future__ import annotations

import unittest
from dataclasses import replace

from roster_theory.core.errors import CoverageIncomplete
from roster_theory.core.models import Player, Projection
from roster_theory.inseason.evaluation import (
    InSeasonContext,
    InSeasonWeek,
    build_weekly_projection_matrix,
)
from roster_theory.trade.boards import build_projection_curves
from roster_theory.trade.board_service import _canonical_projections
from roster_theory.providers.fantasypros import FantasyProsIdentity, ProjectionDataset
from roster_theory.trade.evaluation import (
    EvaluationOptions,
    build_entered_package,
    build_weekly_projection_matrix as trade_matrix,
    evaluate_trade,
)
from tests.test_trade_evaluation import board_fixture, projection_fixture, snapshot_fixture


def projection(week: int, status: str = "complete", points: float = 10.0) -> Projection:
    return Projection("p", "WEEKLY", week, (), points, "fixture", status)


def context(**kwargs) -> InSeasonContext:
    return InSeasonContext(
        players=(Player("p", "Player", ("RB",), nfl_team="AAA", active=True),),
        roster_positions=("RB",),
        weeks=(InSeasonWeek(4, False), InSeasonWeek(5, False)),
        unowned_player_ids=(),
        **kwargs,
    )


class ProjectionEvidenceTests(unittest.TestCase):
    def test_trade_current_status_never_erases_supplied_future_points(self):
        snapshot = snapshot_fixture()
        for status in ("OUT", "IR", "PUP", "SUSP"):
            with self.subTest(status=status):
                injured = replace(snapshot, players=tuple(
                    replace(p, injury_status=status) if p.player_id == "a_rb" else p
                    for p in snapshot.players
                ))
                matrix = trade_matrix(injured, projection_fixture())
                self.assertEqual(matrix.cell("a_rb", 1).points, 0.0)
                self.assertEqual(matrix.cell("a_rb", 2).points, 10.0)
                self.assertEqual(matrix.cell("a_rb", 3).points, 10.0)
                self.assertIn("future availability is unverified",
                              " ".join(matrix.cell("a_rb", 2).warnings))

    def test_unknown_active_flag_is_not_confirmed_inactive(self):
        ctx = context()
        ctx = replace(ctx, players=(replace(ctx.players[0], active=None),))
        matrix = build_weekly_projection_matrix(ctx, (projection(4), projection(5)))
        self.assertEqual(matrix.cell("p", 4).points, 10.0)

    def test_inactive_directory_flag_only_applies_to_current_week(self):
        ctx = context()
        ctx = replace(ctx, players=(replace(ctx.players[0], active=False),))
        matrix = build_weekly_projection_matrix(ctx, (projection(4), projection(5)))
        self.assertEqual(matrix.cell("p", 4).points, 0.0)
        self.assertEqual(matrix.cell("p", 5).points, 10.0)
        self.assertIn("future availability is unverified",
                      " ".join(matrix.cell("p", 5).warnings))

    def test_future_only_horizon_does_not_reinterpret_first_week_as_current(self):
        ctx = context(current_week=3)
        ctx = replace(ctx, players=(replace(ctx.players[0], injury_status="OUT"),))
        matrix = build_weekly_projection_matrix(ctx, (projection(4), projection(5)))
        self.assertEqual(matrix.cell("p", 4).points, 10.0)

    def test_legacy_status_switch_cannot_restore_season_long_absence(self):
        with self.assertRaisesRegex(ValueError, "future weeks"):
            context(current_status_week_only=False)

    def test_verified_future_absence_and_counterfactual_absence_are_distinct(self):
        rows = (projection(4), projection(5, "verified_inactive_zero", 0))
        matrix = build_weekly_projection_matrix(context(), rows)
        self.assertTrue(matrix.complete)
        self.assertEqual(matrix.cell("p", 5).availability, "INACTIVE")
        rows = (projection(4), projection(5, "scenario_inactive_zero", 0))
        matrix = build_weekly_projection_matrix(context(), rows)
        self.assertFalse(matrix.complete)
        self.assertIsNone(matrix.cell("p", 5).points)
        scenario = build_weekly_projection_matrix(context(allow_scenario_projections=True), rows)
        self.assertTrue(scenario.complete)
        self.assertEqual(scenario.cell("p", 5).points, 0)

    def test_incomplete_and_nonfinite_rows_are_missing_not_active_zero(self):
        for row in (projection(4, "source_omission_zero", 0),
                    projection(4, "partial", 0), projection(4, "unavailable", 0),
                    projection(4, points=float("nan")),
                    projection(4, points=float("inf")),
                    projection(4, points=float("-inf"))):
            with self.subTest(status=row.coverage_status, points=row.league_points):
                matrix = build_weekly_projection_matrix(context(), (row, projection(5)))
                self.assertIsNone(matrix.cell("p", 4).points)
                self.assertEqual(matrix.cell("p", 4).availability, "MISSING")
                self.assertFalse(matrix.complete)
                self.assertTrue(matrix.cell("p", 4).warnings)

    def test_old_future_inactive_zero_is_not_authoritative(self):
        rows = (projection(4, "known_inactive_zero", 0),
                projection(5, "known_inactive_zero", 0))
        matrix = build_weekly_projection_matrix(context(), rows)
        self.assertEqual(matrix.cell("p", 4).points, 0)
        self.assertEqual(matrix.cell("p", 4).availability, "INACTIVE")
        self.assertIsNone(matrix.cell("p", 5).points)

    def test_bye_and_actual_zero_or_negative_projections_remain_valid(self):
        ctx = replace(context(), weeks=(InSeasonWeek(4, False, ("AAA",)),
                                        InSeasonWeek(5, False)))
        matrix = build_weekly_projection_matrix(ctx, (projection(5, points=-2),))
        self.assertEqual(matrix.cell("p", 4).availability, "BYE")
        self.assertEqual(matrix.cell("p", 4).points, 0)
        self.assertEqual(matrix.cell("p", 5).points, -2)
        self.assertTrue(matrix.complete)
        matrix = build_weekly_projection_matrix(context(),
                                                (projection(4, points=0), projection(5)))
        self.assertTrue(matrix.complete)

    def test_missing_current_inactive_is_known_but_missing_future_is_not(self):
        ctx = context()
        ctx = replace(ctx, players=(replace(ctx.players[0], injury_status="OUT"),))
        matrix = build_weekly_projection_matrix(ctx, ())
        self.assertEqual(matrix.cell("p", 4).availability, "INACTIVE")
        self.assertEqual(matrix.cell("p", 4).points, 0)
        self.assertIsNone(matrix.cell("p", 5).points)
        self.assertFalse(matrix.complete)

    def test_zero_provenance_cannot_carry_positive_points(self):
        for status in ("verified_bye_zero", "known_inactive_zero"):
            matrix = build_weekly_projection_matrix(context(),
                                                    (projection(4, status), projection(5)))
            self.assertIsNone(matrix.cell("p", 4).points)

    def test_outside_rows_do_not_poison_context_subset(self):
        matrix = build_weekly_projection_matrix(context(), (
            projection(4), projection(5),
            replace(projection(4, "source_omission_zero", 0), player_id="outside"),
        ))
        self.assertTrue(matrix.complete)

    def test_curve_omits_incomplete_players_without_fabricating_rank_slots(self):
        rows = (projection(4, "source_omission_zero", 0), projection(5),
                replace(projection(4), player_id="good"),
                replace(projection(5), player_id="good"))
        curves = build_projection_curves(rows, {"p": "RB", "good": "RB"},
                                         required_counts={"RB": 1}, expected_weeks=(4, 5))
        self.assertEqual(curves[0].raw_player_points, (("good", 20.0),))
        self.assertEqual(curves[0].excluded_players[0][0], "p")
        self.assertIn("source_omission_zero", curves[0].excluded_players[0][1])
        with self.assertRaises(CoverageIncomplete):
            build_projection_curves(rows, {"p": "RB", "good": "RB"},
                                    required_counts={"RB": 2}, expected_weeks=(4, 5))

    def test_curve_rejects_duplicate_week_instead_of_double_counting(self):
        with self.assertRaises(CoverageIncomplete):
            build_projection_curves((projection(4), projection(4), projection(5)),
                                    {"p": "RB"}, required_counts={"RB": 1},
                                    expected_weeks=(4, 5))

    def test_curve_rejects_future_inactive_and_nonfinite_evidence(self):
        for row in (projection(4, "known_inactive_zero", 0),
                    projection(4, points=float("nan")),
                    projection(4, points=float("inf"))):
            with self.subTest(row=row), self.assertRaises(CoverageIncomplete):
                build_projection_curves((row, projection(5)), {"p": "RB"},
                                        required_counts={"RB": 1}, expected_weeks=(4, 5),
                                        current_week=3)

    def test_curve_does_not_overflow_finite_weekly_inputs(self):
        with self.assertRaisesRegex(CoverageIncomplete, "Nonfinite projection horizon total"):
            build_projection_curves((projection(4, points=1e308), projection(5, points=1e308)),
                                    {"p": "RB"}, required_counts={"RB": 1},
                                    expected_weeks=(4, 5))

    def test_provider_normalization_preserves_supplied_future_after_current_omission(self):
        ctx = context()
        player = replace(ctx.players[0], injury_status="OUT")
        stamp = snapshot_fixture().stamps[0]
        datasets = tuple(ProjectionDataset(
            horizon="WEEKLY", scoring="HALF", week=week, contributor_ids=(),
            identities=(FantasyProsIdentity("p", "Player", "RB", "AAA", ()),),
            projections=(projection(week),) if week == 5 else (), stamp=stamp,
        ) for week in (4, 5))
        rows, positions, _ = _canonical_projections(
            datasets, {"p": "p"}, {"p": "RB"}, {}, {"p": player}, current_week=4
        )
        by_week = {row.week: row for row in rows}
        self.assertEqual(by_week[4].coverage_status, "known_inactive_zero")
        self.assertEqual(by_week[5], projection(5))
        curves = build_projection_curves(rows, positions, required_counts={"RB": 1},
                                         expected_weeks=(4, 5), current_week=4)
        self.assertEqual(curves[0].raw_player_points, (("p", 10.0),))
        with self.assertRaisesRegex(CoverageIncomplete, "Duplicate canonical"):
            _canonical_projections((*datasets, datasets[1]), {"p": "p"}, {"p": "RB"},
                                   {}, {"p": player}, current_week=4)

    def test_provider_nonrequired_omission_is_retained_and_disclosed(self):
        player = context().players[0]
        stamp = snapshot_fixture().stamps[0]
        datasets = tuple(ProjectionDataset(
            horizon="WEEKLY", scoring="HALF", week=week, contributor_ids=(),
            identities=(FantasyProsIdentity("p", "Player", "RB", "AAA", ()),),
            projections=(projection(week),) if week == 5 else (), stamp=stamp,
        ) for week in (4, 5))
        rows, positions, warnings = _canonical_projections(
            datasets, {"p": "p"}, {}, {}, {"p": player}, current_week=4
        )
        self.assertEqual(positions, {"p": "RB"})
        self.assertEqual(len(rows), 2)
        self.assertTrue(warnings["p"])
        self.assertEqual(next(row for row in rows if row.week == 4).coverage_status,
                         "source_omission_zero")

    def test_trade_omission_marks_relevant_evaluation_partial_not_acceptable(self):
        snapshot = snapshot_fixture()
        rows = tuple(replace(p, coverage_status="source_omission_zero", league_points=0)
                     if p.player_id == "a_bench" and p.week == 2 else p
                     for p in projection_fixture())
        args = dict(projections=rows, selected_board=board_fixture(snapshot, "selected_final"),
                    market_board=board_fixture(snapshot, "market"))
        package = build_entered_package(snapshot, send=("a_wr",), receive=("b_rb",))
        partial = evaluate_trade(snapshot, package, **args)
        self.assertIn("DECISION-CONDITIONAL", partial.modes)
        self.assertNotEqual(partial.decision_label, "ACCEPTABLE")
        issue = next(p for p in partial.projection_coverage.issues if p.player_id == "a_bench")
        self.assertEqual(issue.missing_weeks, (2,))

    def test_trade_outside_omission_is_disclosed_without_blocking_package(self):
        snapshot = snapshot_fixture()
        rows = tuple(replace(p, coverage_status="source_omission_zero", league_points=0)
                     if p.player_id == "twin_1" else p for p in projection_fixture())
        result = evaluate_trade(snapshot, build_entered_package(
            snapshot, send=("a_wr",), receive=("b_rb",)), projections=rows,
            selected_board=board_fixture(snapshot, "selected_final"),
            market_board=board_fixture(snapshot, "market"))
        self.assertNotIn("SCHEDULE-PARTIAL", result.modes)
        self.assertEqual(result.projection_coverage.outside_player_week_count, 3)


if __name__ == "__main__":
    unittest.main()
