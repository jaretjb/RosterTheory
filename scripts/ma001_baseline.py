"""Offline MA-001 characterization. Run with PYTHONPATH=src;. from the repo root.

--capture writes reviewable semantic evidence; --benchmark measures frozen scope.
No provider client is constructed. Network connects are rejected during workloads.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import fields, is_dataclass
import json
from pathlib import Path
import platform
import statistics
import sys
import tempfile
import time
import tracemalloc
from unittest.mock import patch

from roster_theory.cli import build_parser
from roster_theory.core.errors import CoverageIncomplete
from roster_theory.inseason.evaluation import InSeasonWeek
from roster_theory.core.provenance import canonical_json, stable_hash
from roster_theory.core.run_contract import (
    build_run_manifest, evaluation_as_of, load_run_manifest, save_run_manifest,
)
from roster_theory.mock_watcher import reconcile_draft_state, recommend_for_state
from roster_theory.simulation import compare_strategies
from roster_theory.trade.boards import valuation_gaps
from roster_theory.trade.evaluation import PlayerAsset, TradePackage, diagnose_roster, evaluate_trade
from roster_theory.trade.search import SearchConfig, search_league
from roster_theory.trade.market import ecr_proxy
from roster_theory.trade.targets import discover_trade_targets
from roster_theory.waiver.search import search_waiver_candidates
from tests.ma001_fixtures import AS_OF, PROFILES, ROOT, draft_fixture, policy, reference_fixture, rules
from tests.test_trade_targets import config as target_config


@contextmanager
def offline():
    with patch('socket.socket.connect', side_effect=AssertionError('MA-001 must stay offline')), \
            patch('socket.create_connection', side_effect=AssertionError('MA-001 must stay offline')), \
            evaluation_as_of(AS_OF):
        yield


def plain(value):
    return json.loads(canonical_json(value))


def compatibility():
    """Public parser grammar, including hidden flags; no environment-derived defaults."""
    rows = {}

    def visit(parser, path):
        actions = []
        for action in parser._actions:
            if isinstance(action, argparse._SubParsersAction):
                for name, child in action.choices.items():
                    visit(child, (*path, name))
            else:
                default = action.default
                if isinstance(default, Path):
                    default = default.as_posix()
                actions.append({'flags': action.option_strings, 'destination': action.dest,
                                'required': action.required, 'nargs': action.nargs,
                                'choices': list(action.choices) if action.choices is not None else None,
                                'default': default, 'action': type(action).__name__})
        rows[' '.join(path) or 'root'] = actions
    visit(build_parser(), ())
    return plain(rows)


def workloads(profile, metrics=None):
    fixture = reference_fixture(profile)
    draft, board = draft_fixture(profile)
    state = reconcile_draft_state(draft, (), 1)
    common = dict(projections=fixture.projections, selected_board=fixture.selected,
                  market_board=fixture.market)

    def trade(unequal=False):
        sent = ('r1_1', 'r1_2') if unequal else ('r1_1',)
        return evaluate_trade(fixture.trade, TradePackage('1', '2',
            tuple(PlayerAsset(p) for p in sent), (PlayerAsset('r2_1'),)), **common)

    def waiver():
        return search_waiver_candidates(fixture.waiver(),
            weeks=(InSeasonWeek(1, False),),
            projections=fixture.projections, values=fixture.values(),
            drop_legality={p: True for p in fixture.bundle.teams[0].player_ids},
            news_fresh={p.player_id: True for p in fixture.bundle.players},
            input_bundle_hash='synthetic', availability_source='synthetic',
            policy=policy(profile), now=AS_OF, enable_pruning=False, metrics=metrics)

    def replay():
        manifest = build_run_manifest(as_of=AS_OF, verified_at=AS_OF, snapshot=fixture.trade,
            inputs={'projections': fixture.projections}, policy={'synthetic': profile},
            sources=fixture.bundle.stamps, scoring=fixture.bundle.league.scoring,
            readiness='SYNTHETIC / NON-ACTIONABLE', revalidation={'status': 'SYNTHETIC'})
        with tempfile.TemporaryDirectory() as directory:
            path = save_run_manifest(Path(directory) / 'run.json', manifest)
            result = load_run_manifest(path)
        # Build-specific hashes are verified by the loader, not pinned across refactors.
        return {k: result[k] for k in ('schema_version', 'replay_hash', 'policy_hash',
                'scoring_hash', 'readiness', 'current', 'replay_status')}

    def sparse():
        incomplete = reference_fixture(profile, sparse=True)
        try:
            diagnose_roster(incomplete.trade, projections=incomplete.projections)
        except CoverageIncomplete as error:
            return {'error': type(error).__name__, 'message': str(error)}
        raise AssertionError('Sparse fixture unexpectedly passed coverage')

    encoded = canonical_json(fixture.bundle)
    from roster_theory.core.run_contract import restore_record
    from roster_theory.providers.sleeper import SleeperBundle
    return {
        'prepare_cold': lambda: reference_fixture(profile).bundle,
        'prepare_warm': lambda: restore_record(SleeperBundle, json.loads(encoded)),
        'draft_turn': lambda: recommend_for_state(state, draft, board, limit=3),
        'draft_strategy': lambda: compare_strategies(board, fixture.bundle.league.team_count,
            1, rules(profile)['roster_positions'], 15, trials=2, seed=2026,
            strategies=('scenario_safe',), include_special_teams=True,
            availability_rates=(0.1,), availability_samples=2, bench_weights=(0.2,),
            rank_weights=(0.0,), include_trial_records=True),
        'trade_diagnose': lambda: diagnose_roster(fixture.trade, projections=fixture.projections),
        'trade_exact': trade,
        'trade_unequal': lambda: trade(True),
        'trade_targets': lambda: discover_trade_targets(fixture.trade,
            projections=fixture.projections, selected_board=fixture.selected,
            market_ecr_board=fixture.market, trade_market=ecr_proxy('synthetic benchmark'),
            config=target_config()),
        'trade_search': lambda: search_league(fixture.trade, **common,
            gaps=valuation_gaps(fixture.selected, fixture.market),
            config=SearchConfig(small_pool_per_team=2, large_pool_per_team=0,
                               max_exact_per_opponent=1, max_large_exact_per_opponent=0), metrics=metrics),
        'waiver_search': waiver,
        'offline_replay': replay,
        'sparse_rejection': sparse,
    }


def evidence(result):
    value = plain(result)
    row = {'semantic_hash': stable_hash(value), 'bytes': len(canonical_json(value).encode())}
    if is_dataclass(result):
        row['schema_fields'] = [f.name for f in fields(result)]
    if isinstance(value, dict):
        for key in ('decision', 'coverage', 'coverage_status',
                    'exhaustive_large_search', 'roster_exclusions', 'warnings', 'error',
                    'message', 'weekly_lineup_points', 'best_add_player_id', 'best_drop_player_id'):
            if key in value:
                row[key] = value[key]
        if 'exact_evaluations' in value:
            row['exact_count'] = len(value['exact_evaluations'])
            row['candidate_decisions'] = [{key: item[key] for key in
                ('add_player_id', 'selected_drop_player_id', 'decision')}
                for item in value['exact_evaluations']]
    return row


def capture():
    results = {}
    with offline():
        for profile in PROFILES:
            results[profile] = {}
            for name, function in workloads(profile).items():
                print(f'Capture {profile} {name}', file=sys.stderr, flush=True)
                results[profile][name] = evidence(function())
    return {'schema_version': 1, 'as_of': AS_OF.isoformat(), 'profiles': results}


def benchmark(repeat):
    results = {}
    with offline():
        for profile in PROFILES:
            results[profile] = {}
            for name, function in workloads(profile).items():
                print(f'Measure {profile} {name}', file=sys.stderr, flush=True)
                expected = evidence(function())  # warm-up, excluded from timing
                runs = []
                for _ in range(repeat):
                    start = time.perf_counter()
                    result = function()
                    runs.append(time.perf_counter() - start)
                    if evidence(result) != expected:
                        raise AssertionError(f'Non-deterministic: {profile}/{name}')
                # Separate memory measurement so tracing overhead cannot distort runtime.
                tracemalloc.start()
                function()
                _, peak = tracemalloc.get_traced_memory()
                tracemalloc.stop()
                results[profile][name] = {'median_seconds': statistics.median(runs),
                    'seconds': runs, 'peak_python_bytes': peak, 'evidence': expected}
    return {'schema_version': 1, 'environment': {'python': platform.python_version(),
        'os': platform.platform(), 'architecture': platform.machine()},
        'repeat': repeat, 'memory_method': 'one separate traced run after timed repetitions',
        'profiles': results}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--capture', action='store_true')
    parser.add_argument('--benchmark', action='store_true')
    parser.add_argument('--search-metrics', action='store_true')
    parser.add_argument('--repeat', type=int, default=5)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.repeat < 5:
        parser.error('At least five measured repetitions are required')
    if args.capture:
        ROOT.joinpath('compatibility.json').write_text(json.dumps(compatibility(), indent=2) + '\n', encoding='utf-8')
        ROOT.joinpath('semantics.json').write_text(json.dumps(capture(), indent=2) + '\n', encoding='utf-8')
    if args.benchmark:
        if args.output is None:
            parser.error('--benchmark requires --output')
        args.output.write_text(json.dumps(benchmark(args.repeat), indent=2) + '\n', encoding='utf-8')
    if args.search_metrics:
        if args.output is None:
            parser.error('--search-metrics requires --output')
        results = {}
        with offline():
            for profile in PROFILES:
                results[profile] = {}
                for name in ('trade_search', 'waiver_search'):
                    metrics = {}
                    result = workloads(profile, metrics)[name]()
                    results[profile][name] = {'metrics': metrics, 'evidence': evidence(result)}
        args.output.write_text(json.dumps(results, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
