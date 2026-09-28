"""Synthetic Trade/Waiver evaluation across the half-PPR roster family."""

import unittest

from roster_theory.core.errors import CoverageIncomplete
from roster_theory.inseason.evaluation import InSeasonWeek
from roster_theory.trade.evaluation import (
    PlayerAsset, TradePackage, diagnose_roster, evaluate_trade,
)
from roster_theory.waiver.evaluation import evaluate_waiver
from scripts.ma001_baseline import offline
from tests.ma001_fixtures import AS_OF, reference_fixture
from tests.test_ma005a_roster_matrix import FLEXES, cases


def waiver_inputs(fixture, projections=None):
    return dict(
        add_player_id="fa_RB", weeks=(InSeasonWeek(1, False),),
        projections=fixture.projections if projections is None else projections,
        values=fixture.values(),
        drop_legality={pid: True for pid in fixture.bundle.teams[0].player_ids},
        news_fresh={player.player_id: True for player in fixture.bundle.players},
        now=AS_OF,
    )


class HalfPprInSeasonMatrixTests(unittest.TestCase):
    def test_trade_and_waiver_evaluation_use_each_synthetic_shape(self):
        with offline():
            for teams, flexes, bench in cases():
                with self.subTest(teams=teams, flexes=flexes, bench=bench):
                    shape = (teams, flexes, bench)
                    fixture = reference_fixture(roster_shape=shape)
                    expected_points = 140.0 if flexes == FLEXES[2] else 126.0
                    diagnosis = diagnose_roster(fixture.trade,
                                                projections=fixture.projections)
                    self.assertEqual(dict(diagnosis.weekly_optimal_points),
                                     {week: expected_points for week in (1, 2, 3)})
                    package = TradePackage("1", "2", (PlayerAsset("r1_1"),),
                                           (PlayerAsset("r2_1"),))
                    trade = evaluate_trade(
                        fixture.trade, package, projections=fixture.projections,
                        selected_board=fixture.selected, market_board=fixture.market,
                    )
                    self.assertEqual(trade.league_key, fixture.bundle.league.league_id)
                    self.assertEqual(trade.package, package)
                    self.assertEqual(trade.projection_coverage.missing_player_week_count, 0)
                    self.assertEqual(
                        {row.roster_id: row.weighted_delta for row in trade.team_impacts},
                        {"1": 3.0, "2": -3.0},
                    )
                    self.assertTrue(trade.evidence_hash)
                    full = evaluate_waiver(fixture.waiver(), **waiver_inputs(fixture))
                    self.assertEqual(full.league_key, fixture.bundle.league.league_id)
                    self.assertEqual(full.add_player_id, "fa_RB")
                    self.assertIn(full.selected_drop_player_id,
                                  fixture.bundle.teams[0].player_ids)
                    self.assertTrue(full.projection_inputs_complete)
                    self.assertTrue(full.value_inputs_complete)
                    self.assertIsNone(full.decision)
                    self.assertFalse(full.recommendation_generated)
                    self.assertFalse(full.sleeper_write_performed)
                    open_fixture = reference_fixture(roster_shape=shape, open_slot=True)
                    open_result = evaluate_waiver(open_fixture.waiver(),
                                                  **waiver_inputs(open_fixture))
                    self.assertIsNone(open_result.selected_drop_player_id)
                    self.assertFalse(open_result.recommendation_generated)
                    self.assertFalse(open_result.sleeper_write_performed)

    def test_missing_add_projection_blocks_only_the_affected_waiver_case(self):
        with offline():
            for teams, flexes, bench in cases():
                with self.subTest(teams=teams, flexes=flexes, bench=bench):
                    fixture = reference_fixture(roster_shape=(teams, flexes, bench))
                    partial = tuple(row for row in fixture.projections
                                    if row.player_id != "fa_RB")
                    with self.assertRaisesRegex(CoverageIncomplete, "fa_RB"):
                        evaluate_waiver(fixture.waiver(),
                                        **waiver_inputs(fixture, projections=partial))
                    self.assertEqual(
                        dict(diagnose_roster(fixture.trade,
                                            projections=fixture.projections).weekly_optimal_points)[1],
                        140.0 if flexes == FLEXES[2] else 126.0,
                    )


if __name__ == "__main__":
    unittest.main()
