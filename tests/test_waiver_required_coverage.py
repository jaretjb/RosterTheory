import unittest
from dataclasses import replace
from datetime import timedelta

from roster_theory.waiver.evaluation import evaluate_waiver
from roster_theory.waiver.policy import apply_waiver_policy
from roster_theory.waiver.weekly import WeeklyPlanPolicy, build_weekly_plan
from tests import test_waiver_policy as specialists
from tests.test_waiver_weekly_plans import fixture, NOW


def coverage_fixture():
    s, weeks, projections, values, policy, legality, news, _ = fixture(ir=False, extra_qb=False)
    s = replace(s, players=tuple(replace(p, injury_status=None) if p.player_id == 'injured'
                                 else p for p in s.players))
    weeks = (replace(weeks[0], bye_teams=('QTEAM',)), *weeks[1:])
    values = tuple(replace(v, market_value=30, selected_rest_of_season_position_rank=30)
                   if v.player_id == 'weak' else v for v in values)
    return s, weeks, projections, values, policy, legality, news


class RequiredCoverageTests(unittest.TestCase):
    def evaluate(self, data, add='marginal', drop='weak'):
        s,w,p,v,policy,l,n = data
        return apply_waiver_policy(evaluate_waiver(s, add_player_id=add, drop_player_id=drop,
            weeks=w, projections=p, values=v, drop_legality=l, news_fresh=n, now=NOW),policy)

    def test_qb_bye_repair_uses_owned_gain_despite_ros_tradeoff(self):
        e = self.evaluate(coverage_fixture())
        self.assertEqual(e.decision.decision_path, 'REQUIRED_STARTER_COVERAGE')
        self.assertIn(e.decision_label, {'ADD NOW','CLAIM','ACQUIRE'})
        self.assertAlmostEqual(e.candidates[0].coverage_repair.owned_points_gain,20.12)
        self.assertLess(e.candidates[0].ownership.market_delta,0)

    def test_repair_cannot_drop_a_starter_or_elite_bye_hold(self):
        data = coverage_fixture()
        for drop in ('r','q','te'):
            with self.subTest(drop=drop):
                e = self.evaluate(data, drop=drop)
                self.assertNotEqual(e.decision.decision_path, 'REQUIRED_STARTER_COVERAGE')

    def test_missing_news_and_optional_depth_do_not_receive_exception(self):
        data = list(coverage_fixture())
        data[6] = {}
        self.assertNotEqual(self.evaluate(tuple(data)).decision.decision_path,
                            'REQUIRED_STARTER_COVERAGE')
        data = list(coverage_fixture())
        data[1] = tuple(replace(w, bye_teams=()) for w in data[1])
        self.assertIsNone(self.evaluate(tuple(data)).candidates[0].coverage_repair)

    def test_kicker_bye_does_not_require_an_invented_incumbent_rank(self):
        helper = specialists.WaiverDecisionPolicyTests()
        for missing in (False,True):
            with self.subTest(missing_forecasts=missing):
                e = helper.special_team_evaluation('K', current_delta=2.0, incumbent_bye=True,
                    missing_forecasts=missing, ros_rank=15)
                self.assertEqual(e.decision.decision_path,'REQUIRED_STARTER_COVERAGE')
                self.assertIsNone(e.candidates[0].ownership.current_week_drop_rank)
                self.assertIsNone(e.candidates[0].coverage_repair.owned_points_gain)

    def test_conditional_failed_target_is_removed_from_exact_pool(self):
        s,w,p,v,policy,l,n = coverage_fixture()
        # Include another usable QB so the failed preferred claim has a repair.
        def exact(branch, add, drop):
            result = self.evaluate((branch,w,p,v,policy,l,n),add,drop)
            failed = {a.player_id for a in branch.acquisitions
                      if a.state == 'LOCKED' and a.owner_roster_id is None}
            for candidate in result.candidates:
                self.assertFalse(failed.intersection(candidate.holding.streaming_candidate_ids))
                for row in candidate.lineup.weeks:
                    self.assertFalse(failed.intersection(row.before_replacements))
            return result
        evaluations = tuple(self.evaluate((s,w,p,v,policy,l,n),pid)
                            for pid in ('marginal','backup'))
        result = build_weekly_plan(s,weeks=w,projections=p,values=v,evaluations=evaluations,
            policy=policy,planning_policy=WeeklyPlanPolicy(s.league_key),drop_legality=l,
            news_fresh=n,input_hash='synthetic-coverage',exact_pair=exact)
        self.assertTrue(any(x.player_id=='marginal' for x in result.selected.steps))
        branch = result.failed_claim_branches[0]
        self.assertEqual(branch['failed_player_id'],'marginal')
        self.assertTrue(any(x.player_id=='backup' for x in branch['replacement_plan'].steps))
        self.assertFalse(any(x.player_id=='marginal' for x in branch['replacement_plan'].steps))

    def test_stale_kicker_production_does_not_receive_coverage_approval(self):
        helper = specialists.WaiverDecisionPolicyTests()
        e = helper.special_team_evaluation('K', current_delta=2, incumbent_bye=True,
                                         missing_forecasts=True, ros_rank=15)
        c = e.candidates[0]
        c = replace(c, ownership=replace(c.ownership, performance_add_as_of=NOW-timedelta(days=4)))
        from roster_theory.waiver.policy import load_waiver_policy
        p = load_waiver_policy(specialists.POLICY_PATH)
        result = apply_waiver_policy(replace(e,candidates=(c,)),p)
        self.assertNotEqual(result.decision.decision_path,'REQUIRED_STARTER_COVERAGE')
