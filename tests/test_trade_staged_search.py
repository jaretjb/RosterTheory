from __future__ import annotations

import unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch

from roster_theory.trade import finder
from roster_theory.trade.evaluation import build_entered_package, evaluate_trade
from roster_theory.trade.execution import FinderExecutionPolicy, SearchExecution
from roster_theory.trade.offer import attach_offer_assessment
from roster_theory.trade.screening import diverse_prefix
from roster_theory.trade.target_optimizer import _Candidate
from tests.test_trade_finder import inputs
from tests.test_trade_target_optimizer import optimizer_config, permissive_options


def staged(case, **kwargs):
    snapshot, projections, selected, ecr, market, targets = case
    return finder.find_trade_packages(snapshot, projections=projections,
        selected_board=selected, market_ecr_board=ecr, trade_market=market,
        target_result=targets, config=kwargs.pop('config', optimizer_config()),
        options=kwargs.pop('options', permissive_options()), scope=finder.resolve_scope(snapshot, None),
        execution_policy=kwargs.pop('policy', FinderExecutionPolicy(repairs_per_counter=0)), **kwargs)


class StagedSearchTests(unittest.TestCase):
    def test_default_is_thirty_seconds_and_execution_limits_validate(self):
        self.assertEqual((FinderExecutionPolicy().league_seconds,
                          FinderExecutionPolicy().opponent_seconds), (30, 30))
        for changes in ({'shortlist_size': 0}, {'screening_pool_size': 0},
                        {'secondary_shortlist_size': -1}, {'shortlist_size': 1000},
                        {'shortlist_size': True}):
            with self.assertRaises(ValueError):
                FinderExecutionPolicy(**changes)

    def test_global_order_gives_consolidation_a_turn_before_low_gain_swaps(self):
        def row(shape, gain, rid='2', suffix=''):
            return _Candidate('BASELINE', 'x', 0, (), rid, ('a' + suffix,), ('x' + suffix,),
                shape, 'CURRENT_MARKET', 0, 0, True, gain, 1, 0, True)
        rows = [row('1-for-1', 1, str(n), str(n)) for n in range(2, 14)]
        rows.extend((row('2-for-1', 20), row('3-for-1', 15)))
        selected = diverse_prefix(rows, 5)
        self.assertEqual([r.package_size for r in selected[:2]], ['2-for-1', '3-for-1'])
        self.assertEqual(selected, diverse_prefix(reversed(rows), 5))

    def test_chart_rejections_never_enter_expensive_evaluation(self):
        case = list(inputs())
        chart = case[4]
        board = replace(chart.board, prices=tuple(replace(p, value=10.0 ** n)
            for n, p in enumerate(chart.board.prices, 1)))
        case[4] = replace(chart, board=board)
        config = replace(optimizer_config(fair_ratio=0, fair_floor=0),
            construction_market_band_floor=1e20, consolidation_premium_ratio=0)
        with patch.object(finder, 'evaluate_trade', side_effect=AssertionError('unfair drill-down')):
            result = staged(tuple(case), config=config)
        self.assertEqual(len(result.evaluated_decisions), 0)
        self.assertGreater(sum(c.screened_out for c in result.shape_coverage), 0)
        self.assertTrue(all(c.eligible == c.screened_out for c in result.shape_coverage))

    def test_staged_shortlist_has_honest_accounting_and_final_checks(self):
        case = inputs()
        result = staged(case, policy=FinderExecutionPolicy(screening_pool_size=64,
            shortlist_size=12, repairs_per_counter=0))
        self.assertLessEqual(sum(c.shortlisted for c in result.shape_coverage), 12)
        self.assertLessEqual(sum(c.screen_checked for c in result.shape_coverage), 64)
        self.assertGreater(len(result.evaluated_decisions), 0)
        self.assertIn('screening', result.timing['stage_seconds'])
        for c in result.shape_coverage:
            self.assertEqual(c.eligible, c.evaluated + c.screened_out + c.unevaluated)
        for i in result.ideas:
            self.assertTrue(i.decision.market_fairness.within_band)
            self.assertTrue(i.decision.user_downside_passed)
            self.assertTrue(i.decision.user_depth_passed)
            self.assertNotIn('partner_lineup_floor', i.failed_checks)

    def test_deadline_does_not_publish_unfinished_staged_evaluation(self):
        case = inputs()
        clock = SimpleNamespace(value=0.0)
        execution = SearchExecution(3, 'staged-fixture', clock=lambda: clock.value)
        original = finder.evaluate_trade
        def timed(*args, **kwargs):
            result = original(*args, **kwargs)
            clock.value += 1
            return result
        with patch.object(finder, 'evaluate_trade', side_effect=timed):
            result = staged(case, execution=execution)
        self.assertEqual(result.termination, 'TIME_BUDGET')
        self.assertEqual(len(result.evaluated_decisions), 2)
        self.assertEqual(sum(c.attempted for c in result.shape_coverage), 3)

    def test_entered_trade_cannot_hide_chart_overpay_behind_intrinsic_approval(self):
        snapshot, projections, selected, ecr, market, _ = inputs()
        options = permissive_options()
        evaluation = evaluate_trade(snapshot, build_entered_package(snapshot,
            send=('u_sell',), receive=('o_con',)), projections=projections,
            selected_board=selected, market_board=ecr, options=options)
        prices = tuple(replace(p, value=55 if p.player_id == 'u_sell' else
            28 if p.player_id == 'o_con' else p.value) for p in market.board.prices)
        market = replace(market, board=replace(market.board, prices=prices))
        refresh = SimpleNamespace(refresh=SimpleNamespace(snapshot=snapshot),
            weekly_projections=projections, selected_final=selected, market=ecr)
        policy = SimpleNamespace(optimizer=optimizer_config(fair_ratio=0.12, fair_floor=2))
        with patch('roster_theory.trade.target_workflow._policy', return_value=policy), patch(
            'roster_theory.trade.offer.resolve_trade_market_evidence', return_value=market):
            checked = attach_offer_assessment(evaluation, refresh, options)
        self.assertEqual(checked.decision_label, evaluation.decision_label)
        self.assertEqual(checked.offer_assessment['market_fairness']['status'], 'USER_OVERPAY')
        self.assertEqual(checked.offer_assessment['status'], 'NOT_RECOMMENDED')
        self.assertIn('chart_fairness', checked.offer_assessment['failed_checks'])
        self.assertEqual(checked.offer_assessment['pricing']['provider'], market.board.provider)
        self.assertNotEqual(checked.evidence_hash, evaluation.evidence_hash)

    def test_missing_chart_preserves_intrinsic_evaluation_without_approval(self):
        from roster_theory.trade.market import ecr_proxy
        snapshot, projections, selected, ecr, _, _ = inputs()
        options = permissive_options()
        evaluation = evaluate_trade(snapshot, build_entered_package(snapshot,
            send=('u_sell',), receive=('o_con',)), projections=projections,
            selected_board=selected, market_board=ecr, options=options)
        refresh = SimpleNamespace(refresh=SimpleNamespace(snapshot=snapshot),
            weekly_projections=projections, selected_final=selected, market=ecr)
        with patch('roster_theory.trade.target_workflow._policy', return_value=SimpleNamespace()), patch(
            'roster_theory.trade.offer.resolve_trade_market_evidence', return_value=ecr_proxy('missing')):
            checked = attach_offer_assessment(evaluation, refresh, options)
        self.assertEqual(checked.decision, evaluation.decision)
        self.assertEqual(checked.offer_assessment['status'], 'UNAVAILABLE')
        self.assertIn('current_chart_unavailable', checked.offer_assessment['failed_checks'])

    def test_entered_and_finder_use_identical_final_offer_checks(self):
        case = inputs()
        result = staged(case)
        self.assertTrue(result.ideas)
        idea = result.ideas[0]
        snapshot, projections, selected, ecr, market, _ = case
        refresh = SimpleNamespace(refresh=SimpleNamespace(snapshot=snapshot),
            weekly_projections=projections, selected_final=selected, market=ecr)
        with patch('roster_theory.trade.target_workflow._policy', return_value=SimpleNamespace(
            optimizer=optimizer_config())), patch(
            'roster_theory.trade.offer.resolve_trade_market_evidence', return_value=market):
            entered = attach_offer_assessment(idea.evaluation, refresh,
                replace(permissive_options(), secondary_shortlist_size=4))
        self.assertEqual(entered.offer_assessment['status'], idea.status)
        self.assertEqual(entered.offer_assessment['failed_checks'], idea.failed_checks)
        self.assertEqual(entered.offer_assessment['strict_verdict'], idea.decision.package_verdict)


if __name__ == '__main__':
    unittest.main()
