"""Diagnostic observations, not assertions that current defects are correct behavior."""
from __future__ import annotations

import inspect
import json
from pathlib import Path
import tempfile

from roster_theory.core.scoring import score_stats
from roster_theory.providers.cache import DailyRequestBudget, atomic_write_json
from roster_theory.providers.fantasypros import FantasyProsAdapter
from roster_theory.providers.sleeper import normalize_teams
from roster_theory.simulation import Player, _can_draft, deterministic_roster_strength
from scripts.ma001_baseline import offline
from tests.ma001_fixtures import AS_OF, PROFILES, rules
from roster_theory.trade.board_service import classify_trade_scoring
from dataclasses import asdict


def observations():
    scoring = {'pass_yd': 0.04, 'pass_td': 6}
    missing = score_stats({'pass_yd': 250}, scoring, position='QB')
    zero = score_stats({'pass_yd': 250, 'pass_td': 0}, scoring, position='QB')

    class FakeClient:
        def projections(self, season, **params):
            return {'season': season, 'week': params['week'], 'scoring': params['scoring'],
                    'players': [{'fpid': 'synthetic-qb', 'position_id': 'QB',
                                 'stats': {'pass_yd': 250}}]}
    adapter = FantasyProsAdapter(FakeClient())
    unsupported = adapter.weekly_projections(2026, 1, 'QB', {**scoring, 'bonus_pass_300': 3})
    team = normalize_teams([], [{'roster_id': 1, 'players': ['active', 'taxi'],
                                 'starters': ['active'], 'taxi': ['taxi']}])[0]
    qbs = [Player(str(i), 'Synthetic QB', 'QB', 100, i, 10, i, team='ARI') for i in range(3)]
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / 'budget.json'
        initial = DailyRequestBudget(budget_date=AS_OF.date()).to_json()
        atomic_write_json(path, initial)
        first = DailyRequestBudget.from_json(json.loads(path.read_text()))
        second = DailyRequestBudget.from_json(json.loads(path.read_text()))
        first.reserve(499, today=AS_OF.date())
        second.reserve(499, today=AS_OF.date())
        atomic_write_json(path, first.to_json())
        atomic_write_json(path, second.to_json())
        used = json.loads(path.read_text())['used']
    return {
        'missing_statistics': {'missing_points': missing.points, 'missing_complete': missing.complete,
            'explicit_zero_complete': zero.complete, 'expected': 'Missing TD is unknown; explicit zero is complete.'},
        'adapter_unsupported': {'coverage': unsupported.projections[0].coverage_status,
            'core_unsupported': score_stats({'pass_yd': 250}, {**scoring, 'bonus_pass_300': 3}).unsupported_settings,
            'expected': 'Adapter propagates unsupported categories and missing applicable statistics.'},
        'taxi_membership': {'normalized_players': team.player_ids,
            'taxi_field_present': hasattr(team, 'taxi_ids'),
            'expected': 'Preserve taxi membership for capability rejection; never infer active membership.'},
        'draft_cap': {'third_qb_allowed': _can_draft(qbs[2], qbs[:2]),
            'expected': 'Distinguish legal roster capacity from feature recommendation policy.'},
        'draft_season': {'default_byes': inspect.signature(deterministic_roster_strength).parameters['bye_weeks'].default,
            'expected': 'Require season-matched schedule evidence, not an implicit 2026 default.'},
        'budget_contention': {'accepted_reservations': 998, 'persisted_used': used, 'limit': 500,
            'expected': 'Only one reservation succeeds under shared process-safe accounting.'},
        'reference_scoring': {p: {'trade_classification': asdict(classify_trade_scoring(rules(p)['scoring_settings'])),
            'core_unsupported_nonzero': score_stats({}, rules(p)['scoring_settings']).unsupported_settings,
            'provider_stat_coverage': 'UNVERIFIED: no live projection retrieval'} for p in PROFILES},
    }


if __name__ == '__main__':
    with offline():
        print(json.dumps(observations(), indent=2))
