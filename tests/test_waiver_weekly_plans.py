import json
import tempfile
import unittest
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

from roster_theory.core.models import FantasyTeam, LeagueRules, Player, Projection
from roster_theory.inseason.evaluation import InSeasonWeek
from roster_theory.providers.sleeper import SleeperBundle
from roster_theory.waiver.evaluation import PlayerValueInput, evaluate_waiver
from roster_theory.waiver.policy import load_waiver_policy, apply_waiver_policy
from roster_theory.waiver.snapshot import build_waiver_snapshot
from roster_theory.cli import build_parser
from roster_theory.waiver.search import search_waiver_candidates
from roster_theory.waiver.weekly import (
    WeeklyPlanPolicy, build_weekly_plan, load_availability, load_plan_policy, format_weekly_plan,
)
from tests.test_waiver_evaluation import CAPTURED, NOW


def fixture(*, ir=True, extra_qb=True):
    roles = {'q':'QB','backup':'QB','r':'RB','w':'WR','te':'TE','weak':'RB',
             'injured':'WR','bye':'RB','a':'RB','b':'RB','receiver':'WR','marginal':'QB'}
    points = {'q':20,'backup':14,'r':12,'w':11,'te':8,'weak':5,'injured':10,
              'bye':15,'a':9,'b':8.2,'receiver':9.7,'marginal':20.12}
    ownership = {'q':25,'backup':5,'r':30,'w':30,'te':12,'weak':-15,'injured':25,
                 'bye':40,'a':15,'b':-14,'receiver':0,'marginal':2}
    owned = ('q','r','w','te','weak','injured','bye') + (('backup',) if extra_qb else ())
    positions = ('QB','RB','WR','TE','FLEX','FLEX') + ('BN',)*(len(owned)-6)
    rules = LeagueRules('synthetic-weekly',2026,2,positions,(('rec',0.5),),
        reserve_slots=int(ir),platform_settings=(('reserve_allow_out',1),))
    players = tuple(Player(pid,'Synthetic '+pid,(pos,),nfl_team='QTEAM' if pid=='q'
        else 'BYETEAM' if pid=='bye' else pid.upper(),active=True,
        injury_status='Out' if pid=='injured' else None) for pid,pos in roles.items())
    team = FantasyTeam('1','u1','Synthetic team',owned,(),(),taxi_ids=())
    other = FantasyTeam('2','u2','Synthetic opponent',(),(),(),taxi_ids=())
    bundle = SleeperBundle(CAPTURED,(('season','2026'),('week',1)),rules,(team,other),players,
        (),(),None,0,(), 'fixture')
    s=build_waiver_snapshot(league_key='league_alpha',user_id='u1',sleeper=bundle,
        expected_user_roster_id='1',availability_by_player={pid:'FREE_AGENT' for pid in roles if pid not in owned},now=NOW)
    weeks=(InSeasonWeek(1,False,('BYETEAM',)),InSeasonWeek(2,False,('QTEAM',)),InSeasonWeek(3,True))
    projections=tuple(Projection(pid,'WEEKLY',week,(),points[pid],'synthetic') for pid in roles for week in (1,2,3))
    vals=tuple(PlayerValueInput(pid,ownership[pid],ownership[pid],points[pid]*3,
        current_week_position_rank=2,rest_of_season_position_rank=2,
        selected_rest_of_season_position_rank=2 if pid=='injured' else 10) for pid in roles)
    policy=load_waiver_policy(Path(__file__).parent/'fixtures/waiver/league_alpha.decision-policy.json')
    # Controlled synthetic limits permit one coverage repair while protecting
    # clearly stronger ownership and known QB coverage.
    policy=replace(policy,maximum_depth_loss=50,maximum_downside_increase=50)
    legality={pid:True for pid in owned}
    news={pid:True for pid in roles}
    evaluations=tuple(apply_waiver_policy(evaluate_waiver(s,add_player_id=pid,weeks=weeks,
        projections=projections,values=vals,drop_legality=legality,news_fresh=news,now=NOW),policy)
        for pid in ('a','b','receiver','marginal'))
    return s,weeks,projections,vals,policy,legality,news,evaluations


def plan(data, **kwargs):
    s,w,p,v,policy,legality,news,e=data
    return build_weekly_plan(s,weeks=w,projections=p,values=v,evaluations=e,policy=policy,
        planning_policy=kwargs.pop('planning_policy',WeeklyPlanPolicy(s.league_key)),
        drop_legality=legality,news_fresh=news,input_hash='synthetic-input',**kwargs)


class WeeklyPlanTests(unittest.TestCase):
    def test_cli_defaults_to_weekly_and_exposes_separate_ros_mode(self):
        parser=build_parser()
        self.assertEqual(parser.parse_args(['waiver','search','home_league']).objective,'weekly')
        self.assertEqual(parser.parse_args(['waiver','search','home_league','--objective','ros']).objective,'ros')

    def test_superflex_does_not_apply_one_qb_holding_rules(self):
        data=list(fixture(ir=False)); s=data[0]
        positions=list(s.league.roster_positions); positions[5]='SUPER_FLEX'
        data[0]=replace(s,league=replace(s.league,roster_positions=tuple(positions)))
        data[1]=tuple(replace(w,bye_teams=tuple(t for t in w.bye_teams if t!='QTEAM')) for w in data[1])
        p=plan(tuple(data))
        self.assertTrue(any(step.player_id=='marginal' for step in p.selected.steps))

    def test_specialist_gaps_do_not_block_joint_skill_safety(self):
        from tests.test_waiver_joint_plans import fixed_specialist_gap_fixture
        from tests.test_waiver_evaluation import weeks,legality
        s,p,v=fixed_specialist_gap_fixture()
        v=tuple(replace(row,season_points=30 if row.player_id.startswith('fa_') else 10,
            season_sample_size=5,performance_as_of=CAPTURED) if row.player_id in {'k','dst','fa_k','fa_dst'}
            else row for row in v)
        policy=load_waiver_policy(Path(__file__).parent/'fixtures/waiver/league_alpha.decision-policy.json')
        q=search_waiver_candidates(s,weeks=weeks(),projections=p,values=v,policy=policy,
            drop_legality={**legality(),'k':True,'dst':True},
            news_fresh={pid:True for pid in ('add','fa_rb','fa_wr','fa_te','fa_k','fa_dst')},
            availability_source='synthetic',input_bundle_hash='synthetic',now=NOW,
            planning_policy=WeeklyPlanPolicy(s.league_key))
        self.assertIsNotNone(q.weekly_plan)
        self.assertEqual(q.schema_version,13)
        self.assertTrue({'fa_k','fa_dst'} <= {step.player_id for step in q.weekly_plan.selected.steps})

    def test_open_spot_does_not_hide_incumbent_specialist_swaps(self):
        from tests.test_waiver_joint_plans import fixed_specialist_gap_fixture
        from tests.test_waiver_evaluation import weeks,legality
        from roster_theory.waiver.snapshot import _capacity
        s,p,v=fixed_specialist_gap_fixture()
        rules=replace(s.league,roster_positions=(*s.league.roster_positions,'BN'))
        s=replace(s,league=rules,roster_capacity=tuple(_capacity(rules,t,s.players) for t in s.teams))
        v=tuple(replace(row,season_points=30 if row.player_id.startswith('fa_') else 10,
            season_sample_size=5,performance_as_of=CAPTURED) if row.player_id in {'k','dst','fa_k','fa_dst'}
            else row for row in v)
        policy=load_waiver_policy(Path(__file__).parent/'fixtures/waiver/league_alpha.decision-policy.json')
        q=search_waiver_candidates(s,weeks=weeks(),projections=p,values=v,policy=policy,
            drop_legality={**legality(),'k':True,'dst':True},
            news_fresh={pid:True for pid in ('add','fa_rb','fa_wr','fa_te','fa_k','fa_dst')},
            availability_source='synthetic',input_bundle_hash='synthetic',now=NOW,
            planning_policy=WeeklyPlanPolicy(s.league_key))
        steps=q.weekly_plan.selected.steps
        self.assertTrue(any(step.kind=='ADD' and step.drop_player_id is None for step in steps))
        self.assertTrue(any(step.player_id=='fa_k' and step.drop_player_id=='k' for step in steps))
        self.assertTrue(any(step.player_id=='fa_dst' and step.drop_player_id=='dst' for step in steps))

    def test_failed_claim_is_excluded_and_successful_prerequisites_are_retained(self):
        data=fixture()
        s,w,p,v,policy,legality,news,e=data
        def exact(branch,add,drop):
            return apply_waiver_policy(evaluate_waiver(branch,add_player_id=add,drop_player_id=drop,
                weeks=w,projections=p,values=v,drop_legality=legality,news_fresh=news,now=NOW),policy)
        result=plan(data,exact_pair=exact)
        self.assertTrue(result.failed_claim_branches)
        for branch in result.failed_claim_branches:
            self.assertTrue(branch['successful_prerequisites'])
            self.assertFalse(any(step.player_id==branch['failed_player_id']
                                 for step in branch['replacement_plan'].steps))
            self.assertEqual(branch['successful_prerequisites'][0].kind,'IR')

    def test_ir_opening_preserves_hold_and_fills_roster_without_drop(self):
        p=plan(fixture())
        self.assertEqual(p.selected.steps[0].kind,'IR')
        self.assertEqual(p.selected.steps[0].player_id,'injured')
        self.assertTrue(any(s.kind=='ADD' and s.drop_player_id is None for s in p.selected.steps))
        self.assertEqual(p.selected.current.filled,p.selected.current.required)
        self.assertTrue(p.selected.return_drop_player_ids)
        self.assertIn('no drop',format_weekly_plan(p,{}))

    def test_outgoing_qb_is_not_replaced_by_an_assumed_streamer(self):
        p=plan(fixture(ir=False))
        self.assertFalse(any(s.drop_player_id=='backup' for s in p.selected.steps))
        rejected=[r for r in p.alternatives if any(s.drop_player_id=='backup' for s in r.steps)
                  and not any(s.player_id=='marginal' for s in r.steps)]
        for r in rejected:
            self.assertIn('OUTGOING_QB_COVERAGE',r.reasons)

    def test_only_te_is_preserved_even_when_rb_points_are_higher(self):
        p=plan(fixture(ir=False))
        self.assertFalse(any(s.drop_player_id=='te' for s in p.selected.steps))
        self.assertTrue(any(slot.startswith('TE:') for slot,_,_ in p.selected.current.starters))

    def test_close_call_prefers_durable_value_over_fractional_weekly_points(self):
        p=plan(fixture())
        adds=[s.player_id for s in p.selected.steps if s.kind=='ADD']
        self.assertIn('a',adds)
        self.assertIn('close call',format_weekly_plan(p,{}))

    def test_marginal_third_qb_has_no_incremental_holding_benefit(self):
        data=fixture()
        s,w,p,v,policy,legality,news,e=data
        qb=next(x for x in e if x.add_player_id=='marginal')
        self.assertTrue(all(c.holding.applicable for c in qb.candidates if c.drop_position != 'QB'))
        # Neither marginal start differences nor an already covered bye make
        # this acquisition meaningfully useful.
        changed=tuple(replace(row,league_points=14.1) if row.player_id=='marginal' and row.week==2 else row for row in p)
        q=plan((s,w,changed,v,policy,legality,news,e))
        self.assertFalse(any(step.player_id=='marginal' for step in q.selected.steps))

    def test_ir_disabled_never_creates_an_opening(self):
        p=plan(fixture(ir=False))
        self.assertFalse(any(s.kind=='IR' for s in p.selected.steps))

    def test_missing_material_news_cannot_be_promoted(self):
        data=list(fixture()); data[6]={pid:False for pid in data[6]}
        p=plan(tuple(data))
        self.assertFalse(p.selected.steps)

    def test_missing_projection_remains_explicit(self):
        data=list(fixture())
        data[2]=tuple(x for x in data[2] if not (x.player_id=='r' and x.week==1))
        from roster_theory.core.errors import CoverageIncomplete
        with self.assertRaises(CoverageIncomplete): plan(tuple(data))

    def test_limits_and_hash_are_deterministic(self):
        data=fixture(); policy=WeeklyPlanPolicy('league_alpha',maximum_comparisons=8)
        first=plan(data,planning_policy=policy); second=plan(data,planning_policy=policy)
        self.assertEqual(first.evidence_hash,second.evidence_hash)
        self.assertEqual(first.evaluated_plans,8)
        self.assertEqual(first.coverage,'BOUNDED_LIMIT_REACHED')

    def test_legal_two_move_coverage_repair(self):
        data=list(fixture(ir=False))
        # Two unavailable flex holdings require two acquisitions. The initial
        # healthy weak runner is unavailable, without valuable retention.
        s=data[0]
        data[0]=replace(s,players=tuple(replace(p,injury_status='Out') if p.player_id=='weak' else p for p in s.players))
        p=plan(tuple(data))
        self.assertEqual(p.selected.current.filled,p.selected.current.required)
        self.assertEqual(sum(s.kind=='ADD' for s in p.selected.steps),2)
        self.assertEqual(len({s.drop_player_id for s in p.selected.steps}),2)

    def test_wrong_league_policy_and_invalid_limits_fail(self):
        with self.assertRaises(ValueError): plan(fixture(),planning_policy=WeeklyPlanPolicy('other'))
        for kwargs in ({'maximum_comparisons':0},{'weekly_close_margin':float('nan')},{'beam_width':True}):
            with self.assertRaises(ValueError): WeeklyPlanPolicy('league_alpha',**kwargs)

    def test_availability_is_expiring_scoped_and_does_not_mutate_sleeper(self):
        s=fixture()[0]
        with tempfile.TemporaryDirectory() as d:
            file=Path(d)/'availability.json'
            data={'league_key':s.league_key,'season':2026,'week':1,'players':[{
                'player_id':'injured','status':'ACTIVE','authority':'USER_SCENARIO',
                'source':'Synthetic user expectation','observed_at':CAPTURED.isoformat(),
                'expires_at':(NOW+timedelta(hours=12)).isoformat()}]}
            file.write_text(json.dumps(data))
            rows=load_availability(file,s,now=NOW)
            p=plan(fixture(),availability=rows)
            self.assertIsNotNone(p.fallback)
            self.assertEqual(next(x for x in s.players if x.player_id=='injured').injury_status,'Out')
            data['players'][0]['expires_at']=CAPTURED.isoformat(); file.write_text(json.dumps(data))
            with self.assertRaises(ValueError): load_availability(file,s,now=NOW)
            file.write_text(json.dumps({'league_key':'other'}))
            with self.assertRaises(ValueError): load_availability(file,s,now=NOW)

    def test_no_drop_plan_policy_scope_is_checked(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'policy.json'; path.write_text(json.dumps({'league_key':'league_beta'}))
            with self.assertRaises(ValueError): load_plan_policy(path,'league_alpha')
            self.assertEqual(load_plan_policy(path,'league_beta').league_key,'league_beta')


if __name__=='__main__': unittest.main()
