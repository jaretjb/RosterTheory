import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

from roster_theory.core.errors import CoverageIncomplete
from roster_theory.core.models import Player
from roster_theory.core.specialists import fixed_specialist_swap
from roster_theory.inseason.evaluation import InSeasonContext, build_weekly_projection_matrix
from roster_theory.waiver.evaluation import WaiverEvaluationOptions
from roster_theory.waiver.plans import validate_claim_branch
from roster_theory.waiver.policy import load_waiver_policy
from roster_theory.waiver.search import waiver_readiness, weekly_skill_streamers
from roster_theory.waiver.service import format_waiver_search, _special_team_lines
from roster_theory.waiver.ww_evidence import _provider_update_fresh
from tests.test_waiver_evaluation import weeks
from tests.test_waiver_joint_plans import fixed_specialist_gap_fixture
from tests.test_waiver_search import POLICY_PATH, complete_search_snapshot, search
from tests.test_waiver_ww_evidence import config, dataset
from roster_theory.waiver.ww_evidence import build_waiver_wire_evidence


class WeeklyWaiverReportTests(unittest.TestCase):
    def test_daily_update_does_not_invent_a_midnight_publication_time(self):
        now = datetime(2026, 10, 7, 4, 40, tzinfo=timezone.utc)
        capture = now - timedelta(hours=1)
        for raw in ('10/06', '10/06/2026', '2026-10-06'):
            with self.subTest(raw=raw):
                self.assertTrue(_provider_update_fresh(raw, capture, timedelta(days=1), now=now))
        for raw in ('10/04', '10/08', 'bad', '2026-10-06T00:00:00+00:00'):
            with self.subTest(raw=raw):
                self.assertFalse(_provider_update_fresh(raw, capture, timedelta(days=1), now=now))
        self.assertFalse(_provider_update_fresh('10/07', capture, timedelta(hours=1), now=now))

    def test_daily_update_handles_year_rollover_without_accepting_future_dates(self):
        now = datetime(2027, 1, 1, 4, tzinfo=timezone.utc)
        self.assertTrue(_provider_update_fresh('12/31', now, timedelta(days=1), now=now))
        self.assertFalse(_provider_update_fresh('01/02', now, timedelta(days=1), now=now))

    def test_date_only_freshness_reaches_market_and_selected_ballot_evidence(self):
        now = datetime(2026, 10, 7, 4, 40, tzinfo=timezone.utc)
        evidence = build_waiver_wire_evidence(config=config(experts=('17', '29', '31')),
            players=(Player('s1', 'Runner', ('RB',), fantasypros_id='10'),),
            market=dataset(captured_at=now, updated_at='10/06'),
            selected={eid: dataset(expert_id=eid, captured_at=now, updated_at='10/06')
                      for eid in ('17', '29', '31')},
            now=now)
        self.assertTrue(evidence.market_complete)
        self.assertTrue(evidence.selected_experts_complete)
        self.assertTrue(evidence.complete)
        self.assertTrue(all(stamp.fresh for stamp in evidence.stamps))
        stale = build_waiver_wire_evidence(config=config(),
            players=(Player('s1', 'Runner', ('RB',), fantasypros_id='10'),),
            market=dataset(captured_at=now-timedelta(days=2), updated_at='10/06'),
            selected={}, now=now)
        self.assertFalse(stale.market_complete)

    def weekly_watch(self):
        evaluation = search().exact_evaluations[0]
        candidate = evaluation.candidates[0]
        week = replace(candidate.lineup.weeks[0], week=evaluation.current_week,
                       lineup_entrants=(evaluation.add_player_id,), lineup_exits=('wr',))
        candidate = replace(candidate, added_start_weeks=(evaluation.current_week,),
                            current_week_delta=1.8, current_week_add_points=10.75,
                            current_week_projection_complete=True,
                            lineup=replace(candidate.lineup, weeks=(week,)))
        return replace(evaluation, add_position='RB', decision_label='WATCH',
            candidates=(candidate,), decision=replace(evaluation.decision, label='WATCH',
                gates=(*evaluation.decision.gates,
                       replace(evaluation.decision.gates[0], name='same_position_ros_improvement',
                               passed=False))))

    def test_weekly_starter_is_visible_despite_ros_watch_label(self):
        evaluation = self.weekly_watch()
        rows = weekly_skill_streamers((evaluation,))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].current_week_lineup_gain, 1.8)
        self.assertEqual(rows[0].ros_decision_label, 'WATCH')
        self.assertIn('rest-of-season rank', rows[0].ros_tradeoff)
        self.assertEqual(evaluation.decision_label, 'WATCH')

    def test_streamer_mentions_protected_drop_rather_than_implying_safe_claim(self):
        evaluation = self.weekly_watch()
        gate = replace(evaluation.decision.gates[0],
                       name='drop_retention_protection', passed=False)
        evaluation = replace(evaluation, decision=replace(evaluation.decision,
                             gates=(*evaluation.decision.gates, gate)))
        self.assertIn('proposed drop is protected',
                      weekly_skill_streamers((evaluation,))[0].ros_tradeoff)

    def test_streamer_requires_actual_start_gain_and_available_weekly_evidence(self):
        evaluation = self.weekly_watch()
        candidate = evaluation.candidates[0]
        for changed in (replace(candidate, added_start_weeks=()),
                        replace(candidate, current_week_delta=0),
                        replace(candidate, current_week_projection_complete=False,
                                projection_inputs_complete=False)):
            self.assertEqual(weekly_skill_streamers((replace(evaluation, candidates=(changed,)),)), ())
        self.assertEqual(weekly_skill_streamers((replace(evaluation, material_news_fresh=False),)), ())
        snapshot = complete_search_snapshot()
        snapshot = replace(snapshot, players=tuple(
            replace(p, injury_status='Out') if p.player_id==evaluation.add_player_id else p
            for p in snapshot.players))
        self.assertEqual(weekly_skill_streamers((evaluation,), snapshot=snapshot), ())

    def test_streamer_requires_available_acquisition_state_and_no_owner(self):
        evaluation = self.weekly_watch()
        snapshot = complete_search_snapshot()
        self.assertEqual(len(weekly_skill_streamers((evaluation,), snapshot=snapshot)), 1)
        owned = replace(snapshot, owner_by_player=(*snapshot.owner_by_player,
                         (evaluation.add_player_id, 'other-roster')))
        self.assertEqual(weekly_skill_streamers((evaluation,), snapshot=owned), ())
        locked = replace(snapshot, acquisitions=tuple(
            replace(row, state='LOCKED') if row.player_id==evaluation.add_player_id else row
            for row in snapshot.acquisitions))
        self.assertEqual(weekly_skill_streamers((evaluation,), snapshot=locked), ())

    def test_normal_directory_and_specialist_gaps_do_not_make_safe_move_incomplete(self):
        result = search()
        from roster_theory.waiver.search import WaiverSearchOmission
        result = replace(result, omissions=(*result.omissions,
            WaiverSearchOmission('unranked', 'UNROSTERED', 'NO_AUTHORITATIVE_VALUE'),
            WaiverSearchOmission('k', 'LOCKED', 'ROSTER_PROJECTION_INCOMPLETE')))
        self.assertTrue(waiver_readiness(result)['inputs_complete'])
        best = result.exact_evaluations[0]
        conditional = replace(best, projection_inputs_complete=False,
            decision=replace(best.decision, decision_path='CONDITIONAL_ROSTER_EVIDENCE'))
        result = replace(result, best_add_player_id=conditional.add_player_id,
                         exact_evaluations=(conditional,))
        self.assertFalse(waiver_readiness(result)['inputs_complete'])

    def test_rank_fallback_readiness_never_requires_missing_specialist_forecasts(self):
        evaluation = self.weekly_watch()
        gate = replace(evaluation.decision.gates[0], name='complete_special_team_evidence', passed=True)
        evaluation = replace(evaluation, add_position='DST', projection_inputs_complete=False,
            decision=replace(evaluation.decision, gates=(gate,), specialist_evidence={
                'basis':'RANK_PERFORMANCE', 'performance_complete':True}))
        result = replace(search(), best_add_player_id=evaluation.add_player_id,
                         exact_evaluations=(evaluation,))
        self.assertTrue(waiver_readiness(result)['inputs_complete'])
        evaluation = replace(evaluation, decision=replace(evaluation.decision,
            gates=(replace(gate, passed=False),)))
        self.assertFalse(waiver_readiness(replace(result, exact_evaluations=(evaluation,)))['inputs_complete'])

    def test_specialist_section_excludes_cross_position_drops(self):
        evaluation = self.weekly_watch()
        evaluation = replace(evaluation, add_position='K', candidates=(
            replace(evaluation.candidates[0], same_position=False, drop_position='RB'),))
        self.assertEqual(_special_team_lines((evaluation,), {}, 'K'), [])

    def test_human_report_shows_streamer_and_removes_numbered_conflicts_and_jargon(self):
        result = search()
        watch = self.weekly_watch()
        result = replace(result, exact_evaluations=(*result.exact_evaluations, watch),
                         weekly_streamers=weekly_skill_streamers((watch,)))
        report = format_waiver_search(SimpleNamespace(search=result,
            refresh=SimpleNamespace(snapshot=complete_search_snapshot())))
        self.assertIn('WEEKLY SKILL STREAMERS', report)
        self.assertIn('10.75 pts', report)
        self.assertIn('backups for one roster spot', report)
        self.assertNotIn('alternatives #', report)
        self.assertNotIn('CONDITIONAL CLAIM BRANCH CHECKS', report)
        self.assertNotIn('real-world calibration', report)
        self.assertNotIn('OTHER PLAYERS TO WATCH', report)
        self.assertNotIn('not available in this league', report)

    def test_specialist_is_independent_only_for_one_pure_holder_and_one_fixed_slot(self):
        snapshot, _, _ = fixed_specialist_gap_fixture()
        roster = snapshot.teams[0].player_ids
        args = (snapshot.players, snapshot.league.roster_positions, roster, 'fa_dst', 'dst')
        self.assertEqual(fixed_specialist_swap(*args), 'DST')
        self.assertIsNone(fixed_specialist_swap(snapshot.players,
            (*snapshot.league.roster_positions, 'DEF'), roster, 'fa_dst', 'dst'))
        self.assertIsNone(fixed_specialist_swap(snapshot.players,
            snapshot.league.roster_positions, (*roster, 'fa_dst'), 'fa_dst', 'dst'))
        players = tuple(replace(p, positions=('DST', 'RB')) if p.player_id=='fa_dst' else p
                        for p in snapshot.players)
        self.assertIsNone(fixed_specialist_swap(players, snapshot.league.roster_positions,
                                                roster, 'fa_dst', 'dst'))
        self.assertIsNone(fixed_specialist_swap(snapshot.players,
            snapshot.league.roster_positions, (*roster, 'unknown-identity'), 'fa_dst', 'dst'))

    def test_skill_and_rank_only_specialist_claims_validate_in_either_order(self):
        snapshot, projections, _ = fixed_specialist_gap_fixture()
        template = search().exact_evaluations[0]
        specialist = replace(template, add_player_id='fa_dst', add_position='DST',
            selected_drop_player_id='dst', decision_label='ACQUIRE',
            candidates=(replace(template.candidates[0], drop_player_id='dst',
                                drop_position='DST', same_position=True),),
            decision=replace(template.decision, label='ACQUIRE', specialist_evidence={
                'basis': 'RANK_PERFORMANCE', 'performance_complete': True}))
        skill = replace(template, add_player_id='add', selected_drop_player_id='bench',
                        decision_label='ACQUIRE')
        context = InSeasonContext(players=snapshot.players,
            roster_positions=snapshot.league.roster_positions, weeks=weeks(),
            unowned_player_ids=(), evaluation_positions=('QB','RB','WR','TE','K','DST'),
            current_week=snapshot.manifest.current_week, allow_estimated_projections=True)
        # The roster's fixed specialists have no usable projections, just as
        # in the reported case. Each order must avoid scoring that missing DST.
        matrix = build_weekly_projection_matrix(context, projections)
        roster = set(snapshot.teams[0].player_ids) - {'k','dst'}
        for order in ((skill, specialist), (specialist, skill)):
            with self.subTest(order=[row.add_player_id for row in order]):
                checks = validate_claim_branch(snapshot, order,
                    evaluate_pair=lambda _s, add, _d: specialist if add=='fa_dst' else skill,
                    context=context, matrix=matrix, roster_player_ids=roster,
                    options=WaiverEvaluationOptions(), policy=load_waiver_policy(POLICY_PATH))
                self.assertEqual([row.accepted for row in checks], [True, True])
                self.assertIsNone(checks[0 if order[0]==specialist else 1].cumulative_lineup_delta)

    def test_non_singleton_specialist_keeps_ordinary_missing_projection_failure(self):
        snapshot, _, _ = fixed_specialist_gap_fixture()
        snapshot = replace(snapshot, league=replace(snapshot.league,
            roster_positions=(*snapshot.league.roster_positions, 'DEF')))
        template = search().exact_evaluations[0]
        specialist = replace(template, add_player_id='fa_dst', add_position='DST',
            selected_drop_player_id='dst', decision_label='ACQUIRE',
            candidates=(replace(template.candidates[0], drop_player_id='dst',
                                drop_position='DST', same_position=True),),
            decision=replace(template.decision, specialist_evidence={
                'basis': 'RANK_PERFORMANCE', 'performance_complete': True}))
        with patch('roster_theory.waiver.plans.team_impact', side_effect=CoverageIncomplete('missing DST')):
            checks = validate_claim_branch(snapshot, (specialist,), evaluate_pair=lambda *_: specialist,
                context=None, matrix=None, roster_player_ids=set(snapshot.teams[0].player_ids),
                options=WaiverEvaluationOptions(), policy=load_waiver_policy(POLICY_PATH))
        self.assertFalse(checks[0].accepted)
