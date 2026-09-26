from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import json
import tempfile
import unittest

from roster_theory.cli import _product_frame
from roster_theory.core.errors import StaleData
from roster_theory.core.run_contract import (
    evaluation_as_of, evaluation_time, build_run_manifest, load_run_manifest,
    revalidate_snapshot, save_run_manifest,
    validate_sources,
)
from roster_theory.providers.sleeper import SleeperAdapter
from roster_theory.waiver.snapshot import build_waiver_snapshot
from roster_theory.waiver.search import waiver_readiness
from tests.test_waiver_snapshot import FakeSleeperClient


class RunContractTests(unittest.TestCase):
    def test_harmless_warning_does_not_degrade_readiness(self):
        frame = _product_frame('Waiver', 'fixture', (1,), 'No action',
                               warnings=('Informational feed limit',))
        self.assertEqual(frame.readiness, 'READY')

    def test_as_of_is_fixed_and_scope_does_not_leak(self):
        start = datetime(2026, 9, 25, tzinfo=timezone.utc)
        with evaluation_as_of(start):
            self.assertEqual(evaluation_time(), start)
            with evaluation_as_of(start + timedelta(hours=1)):
                self.assertEqual(evaluation_time(), start + timedelta(hours=1))
            self.assertEqual(evaluation_time(), start)
        self.assertNotEqual(evaluation_time(), start)

    def test_cache_hit_keeps_original_player_observation_time(self):
        with tempfile.TemporaryDirectory() as directory:
            adapter = SleeperAdapter(FakeSleeperClient(), player_cache_path=Path(directory)/'players.json')
            first = adapter.fetch_waiver('league-1')
            second = adapter.fetch_waiver('league-1')
        old = next(s for s in first.stamps if s.endpoint == '/players/nfl')
        new = next(s for s in second.stamps if s.endpoint == '/players/nfl')
        self.assertEqual(old.captured_at, new.captured_at)
        self.assertEqual(new.cache_status, 'hit')
        self.assertIsNotNone(new.payload_hash)

    def test_trade_admission_does_not_use_yesterdays_player_status(self):
        from roster_theory.providers.cache import atomic_write_json
        from roster_theory.trade.service import _player_cache_fresh
        from tests.test_trade_snapshot import FakeSleeperClient as TradeClient
        now = datetime.now(timezone.utc)
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory)/'players.json'
            client = TradeClient()
            atomic_write_json(cache, {'captured_at': (now-timedelta(minutes=6)).isoformat(),
                                     'players': {}})
            self.assertFalse(_player_cache_fresh(cache, now))
            result = SleeperAdapter(client, player_cache_path=cache).fetch('league-1', [1, 2])
            self.assertEqual(result.player_directory_cache_status, 'miss')
            self.assertEqual(client.players_calls, 1)

    def test_revalidation_rejects_changed_ownership(self):
        with tempfile.TemporaryDirectory() as directory:
            client = FakeSleeperClient()
            bundle = SleeperAdapter(client, player_cache_path=Path(directory)/'players.json').fetch_waiver('league-1')
            snapshot = build_waiver_snapshot(league_key='fixture', user_id='u1', sleeper=bundle)
            changed = replace(bundle, teams=(replace(bundle.teams[0], player_ids=()), *bundle.teams[1:]))
            with self.assertRaisesRegex(StaleData, 'changed'):
                revalidate_snapshot(snapshot, bundle=changed)
            self.assertEqual(revalidate_snapshot(snapshot, bundle=bundle)['status'], 'UNCHANGED')
            injured = replace(bundle, players=(replace(bundle.players[0], injury_status='Out'), *bundle.players[1:]))
            with self.assertRaisesRegex(StaleData, 'availability'):
                revalidate_snapshot(snapshot, bundle=injured)
            with self.assertRaisesRegex(StaleData, 'expired'):
                revalidate_snapshot(snapshot, bundle=bundle,
                    clock=lambda: bundle.captured_at + timedelta(minutes=6))

    def test_cache_expiry_is_measured_from_source_not_run_start(self):
        now = datetime.now(timezone.utc)
        sources = [{'name': 'rankings', 'captured_at': (now-timedelta(hours=2)).isoformat(),
                    'maximum_age_seconds': 7200}]
        validate_sources(sources, now=now)
        with self.assertRaises(StaleData):
            validate_sources(sources, now=now+timedelta(seconds=1))

    def test_news_refresh_plan_reuses_a_feed_for_one_hour(self):
        from roster_theory.trade.board_service import _input_calls
        from roster_theory.providers.cache import DailyRequestBudget, atomic_write_json, cache_key
        now = datetime.now(timezone.utc)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            atomic_write_json(root/(cache_key('/nfl/news', {'limit': 100})+'.json'),
                              {'captured_at': now.isoformat(), 'payload': {'items': []}})
            for age, hit in ((0, True), (59, True), (60, True), (61, False)):
                with self.subTest(minutes=age):
                    plan, _, _ = _input_calls(2026, 1, (1,), root,
                        now+timedelta(minutes=age), DailyRequestBudget())
                    call = next(row for row in plan.calls if row.name == 'material_news')
                    self.assertIs(call.fresh_cache_hit, hit)

    def test_empty_exhaustive_search_is_ready_and_budget_is_separate(self):
        omission = SimpleNamespace(reason='ACQUISITION_LOCKED')
        search = SimpleNamespace(omissions=(omission,), budget_excluded_player_ids=(),
                                 exact_evaluations=(), warnings=('Informational',))
        result = waiver_readiness(search)
        self.assertTrue(result['inputs_complete'])
        self.assertTrue(result['search_complete'])
        search.budget_excluded_player_ids = ('p1',)
        self.assertTrue(waiver_readiness(search)['inputs_complete'])
        self.assertFalse(waiver_readiness(search)['search_complete'])
        search.omissions = (SimpleNamespace(reason='NO_AUTHORITATIVE_VALUE'),)
        self.assertFalse(waiver_readiness(search)['inputs_complete'])

    def test_finite_news_feed_cannot_claim_complete_player_coverage(self):
        from roster_theory.waiver.service import _news_freshness
        now = datetime.now(timezone.utc)
        inputs = SimpleNamespace(values=(SimpleNamespace(player_id='p1'),), news_fresh=(),
            news_coverage={'scope': 'FINITE_GLOBAL_FEED', 'captured_at': now.isoformat(),
                           'per_player_complete': False, 'records': 0})
        self.assertTrue(_news_freshness(inputs, now)['p1'])
        self.assertTrue(_news_freshness(inputs, now+timedelta(minutes=59))['p1'])
        self.assertFalse(inputs.news_coverage['per_player_complete'])
        self.assertFalse(_news_freshness(inputs, now+timedelta(minutes=61))['p1'])

    def test_long_waiver_search_does_not_freeze_publication_clock(self):
        from roster_theory.waiver.service import WaiverRefreshResult, search_waivers, waiver_refresh_plan
        from roster_theory.waiver.search import search_waiver_candidates
        from tests.test_waiver_search import complete_search_snapshot, input_payload, NOW, POLICY_PATH
        time = [NOW]
        def slow_search(*args, **kwargs):
            result = search_waiver_candidates(*args, **kwargs)
            time[0] += timedelta(minutes=11)
            return result
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            from roster_theory.providers.cache import atomic_write_json
            atomic_write_json(root/'inputs.json', input_payload())
            refresh = WaiverRefreshResult(complete_search_snapshot(),
                waiver_refresh_plan('league-1', 1, player_cache_hit=True), root/'snapshot.json')
            with (patch('roster_theory.waiver.service.refresh_waiver_snapshot', return_value=refresh),
                  patch('roster_theory.waiver.service.search_waiver_candidates', side_effect=slow_search),
                  patch('roster_theory.waiver.service.revalidate_snapshot') as recheck):
                with self.assertRaisesRegex(StaleData, 'completion gate'):
                    search_waivers('league_alpha', inputs_path=root/'inputs.json',
                        output_path=root/'report.json', policy_path=POLICY_PATH,
                        now=NOW, clock=lambda: time[0], enable_pruning=False)
                recheck.assert_not_called()
                self.assertFalse((root/'report.json').exists())

    def test_publication_rechecks_matchup_starters_and_kickoff(self):
        from roster_theory.waiver.service import _publication_check
        from tests.test_waiver_search import complete_search_snapshot, NOW
        snapshot = complete_search_snapshot()
        end = NOW+timedelta(minutes=2)
        inputs = SimpleNamespace(captured_at=NOW, source_evidence=(),
            drop_legality_context=None,
            drop_legality_evidence={'p1': {'legal': True, 'kickoff_at': (NOW+timedelta(minutes=1)).isoformat()}})
        with patch('roster_theory.waiver.service.revalidate_snapshot', return_value={
            'verified_at': end.isoformat(), 'status': 'UNCHANGED',
        }):
            with self.assertRaisesRegex(StaleData, 'game started'):
                _publication_check(inputs, snapshot, client=None, clock=lambda: end)
            inputs.drop_legality_context = {'starters': ['p1']}
            client = SimpleNamespace(league_matchups=lambda *_: [
                {'roster_id': snapshot.user_roster_id, 'starters': ['p2']}])
            with self.assertRaisesRegex(StaleData, 'Matchup starters changed'):
                _publication_check(inputs, snapshot, client=client, clock=lambda: end)

    def test_manifest_records_distinct_source_age_policy_scoring_and_build(self):
        now = datetime.now(timezone.utc)
        source = {'captured_at': (now-timedelta(hours=1)).isoformat(), 'cache_status': 'hit'}
        manifest = build_run_manifest(as_of=now, verified_at=now,
            snapshot={}, inputs={}, policy={'a': 1}, sources=(source,), scoring={'rec': 1},
            readiness={}, revalidation={})
        self.assertEqual(manifest['source_stamps'][0], source)
        self.assertEqual(len(manifest['build_hash']), 64)
        self.assertNotEqual(manifest['policy_hash'], manifest['scoring_hash'])
        json.dumps(manifest, allow_nan=False)

    def test_trade_long_run_uses_admitted_as_of_not_changing_wall_clock(self):
        from roster_theory.trade.snapshot import assert_current
        from tests.test_trade_consolidation import consolidation_fixture
        snapshot = consolidation_fixture()[0]
        past = datetime.now(timezone.utc)-timedelta(minutes=10)
        snapshot = replace(snapshot, captured_at=past)
        with evaluation_as_of(past+timedelta(seconds=1)):
            assert_current(snapshot)
        with self.assertRaises(StaleData):
            assert_current(snapshot)

    def test_trade_exact_compare_and_legacy_search_publish_replayable_evidence(self):
        from roster_theory.trade.evaluation_service import evaluate_entered_trade
        from roster_theory.trade.search_service import run_package_comparison, run_league_search
        from roster_theory.trade.replay import replay_trade_manifest
        from roster_theory.trade.search import SearchConfig
        from tests.test_trade_consolidation import consolidation_fixture
        from tests.test_trade_target_optimizer import permissive_options
        snapshot, projections, selected, market, _ = consolidation_fixture()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            refresh = SimpleNamespace(refresh=SimpleNamespace(snapshot=snapshot),
                weekly_projections=projections, selected_final=selected, market=market,
                gaps=(), output_path=root/'boards.json')
            with (
                patch('roster_theory.trade.evaluation_service.refresh_value_boards', return_value=refresh),
                patch('roster_theory.trade.search_service._refresh', return_value=refresh),
                patch('roster_theory.trade.evaluation_service._options_from_policy', return_value=permissive_options()),
                patch('roster_theory.trade.search_service._options_from_policy', return_value=permissive_options()),
                patch('roster_theory.trade.search_service._config_from_policy', return_value=SearchConfig()),
                patch('roster_theory.trade.evaluation_service.resolve_league_policy_path', return_value=root/'policy'),
                patch('roster_theory.trade.search_service.resolve_league_policy_path', return_value=root/'policy'),
                patch('roster_theory.trade.evaluation_service.revalidate_snapshot', return_value={
                    'verified_at': snapshot.captured_at.isoformat(), 'status': 'UNCHANGED'}) as recheck,
            ):
                exact = evaluate_entered_trade('fixture', send=('u_rb',), receive=('o_buy',), output_path=root/'exact.json')
                compare = run_package_comparison('fixture', packages=({'send': ['u_rb'], 'receive': ['o_buy']},),
                    output_path=root/'compare.json')
                search = run_league_search('fixture', output_path=root/'search.json')
                self.assertEqual(recheck.call_count, 3)
                for result in (exact, compare, search):
                    self.assertFalse(replay_trade_manifest(result.output_path.with_suffix('.manifest.json'))['current'])
                recheck.side_effect = StaleData('Ownership changed')
                with self.assertRaisesRegex(StaleData, 'changed'):
                    evaluate_entered_trade('fixture', send=('u_rb',), receive=('o_buy',), output_path=root/'blocked.json')
                self.assertFalse((root/'blocked.json').exists())

    def test_manifest_replay_and_tampering(self):
        now = datetime.now(timezone.utc)
        manifest = build_run_manifest(as_of=now, verified_at=now,
            snapshot={'league': 'fixture'}, inputs={'points': [1, 2]},
            policy={'threshold': 2}, sources=(), scoring={'rec': 0.5},
            readiness={'inputs_complete': True, 'search_complete': True},
            revalidation={'status': 'UNCHANGED'})
        with tempfile.TemporaryDirectory() as directory:
            path = save_run_manifest(Path(directory)/'report.json', manifest)
            replay = load_run_manifest(path)
            self.assertEqual(replay['replay']['inputs'], {'points': [1, 2]})
            self.assertEqual(replay['as_of'], now.isoformat())
            manifest['replay']['inputs']['points'] = [99]
            save_run_manifest(Path(directory)/'report.json', manifest)
            with self.assertRaisesRegex(ValueError, 'hash'):
                load_run_manifest(path)
