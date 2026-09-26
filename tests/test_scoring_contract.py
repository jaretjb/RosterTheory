from dataclasses import replace
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from roster_theory.core.errors import CoverageIncomplete
from roster_theory.core.provenance import canonical_json, stable_hash
from roster_theory.core.run_contract import restore_record
from roster_theory.core.scoring_contract import (
    LinearScoringRule, RuleAssessment, ScoredEvidence, ScoringScope,
    StatEvidence, StatObservation, assess_scoring_rules, observed_statistics, score_evidence,
)
from tests.ma001_fixtures import rules
from scripts.ma002_scoring_inventory import inventory


OFFENSE = ('QB', 'RB', 'WR', 'TE', 'K')


def catalogue(*settings, positions=OFFENSE):
    return tuple(LinearScoringRule(key, key, positions, 'Synthetic canonical event counts') for key in settings)


def assess(scoring, *, definitions=None, scope=None):
    return assess_scoring_rules(scoring,
        scope=scope or ScoringScope('synthetic-a', 2026, 'weekly-projection', 'WEEKLY', 1),
        catalogue=definitions if definitions is not None else catalogue(*scoring),
        catalogue_version='synthetic-arithmetic-v1')


def observe(stats, **changes):
    arguments = dict(source='Synthetic source', source_schema='synthetic-event-counts-v1',
                     season=2026, horizon='WEEKLY', week=1, position='QB')
    return observed_statistics(stats, **(arguments | changes))


class ScoringContractTests(unittest.TestCase):
    def test_missing_is_not_zero_and_partial_points_are_not_usable(self):
        assessment = assess({'pass_yd': 0.04, 'pass_td': 6})
        missing = score_evidence(assessment, observe({'pass_yd': 250}))
        zero = score_evidence(assessment, observe({'pass_yd': 250, 'pass_td': 0}))
        self.assertEqual(assessment.support, 'SUPPORTED')
        self.assertEqual(missing.diagnostic_points, 10)
        self.assertEqual([(i.setting, i.category) for i in missing.issues], [('pass_td', 'missing_statistic')])
        with self.assertRaisesRegex(CoverageIncomplete, 'pass_td: missing_statistic'):
            missing.require_points()
        self.assertTrue(zero.complete)
        self.assertEqual(zero.require_points(), 10)

    def test_hand_scored_qb_receiver_kicker_and_defense(self):
        cases = (
            ('QB', {'pass_yd': 0.04, 'pass_td': 4, 'pass_int': -2, 'rush_yd': 0.1},
             {'pass_yd': 250, 'pass_td': 2, 'pass_int': 1, 'rush_yd': 10}, 17),
            ('WR', {'rec': 0.5, 'rec_yd': 0.1, 'rec_td': 6},
             {'rec': 5, 'rec_yd': 70, 'rec_td': 1}, 15.5),
            ('K', {'fgm_40_49': 4, 'fgm_60p': 6, 'xpm': 1, 'xpmiss': -1},
             {'fgm_40_49': 2, 'fgm_60p': 1, 'xpm': 3, 'xpmiss': 1}, 16),
            ('DST', {'sack': 1, 'int': 2, 'def_td': 6, 'pts_allow_1_6': 7},
             {'sack': 3, 'int': 2, 'def_td': 1, 'pts_allow_1_6': 1}, 20),
        )
        for position, scoring, stats, expected in cases:
            with self.subTest(position=position):
                result = score_evidence(assess(scoring, definitions=catalogue(*scoring, positions=(position,))),
                                        observe(stats, position=position))
                self.assertTrue(result.complete)
                self.assertEqual(result.require_points(), expected)

    def test_each_reference_scores_the_same_raw_qb_evidence_independently(self):
        keys = ('pass_yd', 'pass_td', 'pass_int', 'rush_yd')
        raw = observe({'pass_yd': 250, 'pass_td': 2, 'pass_int': 1, 'rush_yd': 10})
        before = stable_hash(raw)
        results = []
        for profile in ('reference_a', 'reference_b'):
            # Explicit subset: whole-profile support remains unverified.
            scoring = {key: rules(profile)['scoring_settings'][key] for key in keys}
            scope = ScoringScope(profile, 2026, 'weekly-projection', 'WEEKLY', 1)
            results.append(score_evidence(assess(scoring, scope=scope), raw))
        self.assertEqual([r.require_points() for r in results], [17, 18])
        self.assertNotEqual(results[0].assessment.scoring_hash, results[1].assessment.scoring_hash)
        self.assertNotEqual(results[0].assessment.rules_hash, results[1].assessment.rules_hash)
        self.assertEqual(stable_hash(raw), before)

    def test_structural_zero_requires_a_source_rule_and_stays_distinct(self):
        assessment = assess({'pass_td': 6})
        zero = observe({}, structural_zeros={'pass_td': 'synthetic-event-counts-v1 section 2: omitted TD is zero'})
        result = score_evidence(assessment, zero)
        self.assertEqual(result.require_points(), 0)
        self.assertEqual(result.structural_zero_settings, ('pass_td',))
        self.assertEqual(zero.observations[0].kind, 'STRUCTURAL_ZERO')
        self.assertNotEqual(stable_hash(zero), stable_hash(observe({'pass_td': 0})))
        with self.assertRaisesRegex(ValueError, 'source-schema zero rule'):
            observe({}, structural_zeros={'pass_td': ''})
        with self.assertRaisesRegex(ValueError, 'Duplicate or conflicting'):
            observe({'pass_td': 1}, structural_zeros={'pass_td': 'synthetic schema'})

    def test_invalid_statistics_remain_visible_and_json_serializable(self):
        for value in (None, '', '-', 'NaN', '4', True, float('nan'), float('inf'), -float('inf'), 10**400):
            with self.subTest(value_type=type(value).__name__):
                result = score_evidence(assess({'pass_td': 6}), observe({'pass_td': value}))
                self.assertFalse(result.complete)
                self.assertEqual(result.issues[0].category, 'invalid_statistic')
                self.assertEqual(result.source_evidence.observations[0].kind, 'INVALID')
                self.assertEqual(result.diagnostic_points, 0)
                json.loads(canonical_json(result))
                with self.assertRaises(CoverageIncomplete):
                    result.require_points()

    def test_invalid_rules_cannot_masquerade_as_disabled_settings(self):
        for value in ('0', None, True, float('nan'), float('inf')):
            with self.subTest(value=value):
                assessment = assess({'unknown': value}, definitions=())
                self.assertEqual(assessment.support, 'UNSUPPORTED')
                self.assertEqual(assessment.disabled_settings, ())
                self.assertEqual(assessment.issues[0].category, 'invalid_multiplier')
                json.loads(canonical_json(assessment))
        disabled = assess({'unknown': 0}, definitions=())
        self.assertEqual(disabled.support, 'SUPPORTED')
        self.assertEqual(disabled.disabled_settings, ('unknown',))

    def test_unknown_rules_are_not_made_supported_by_having_a_similar_stat(self):
        assessment = assess({'bonus_pass_300': 3}, definitions=())
        result = score_evidence(assessment, observe({'pass_yd': 350, 'bonus_pass_300': 1}))
        self.assertEqual(assessment.support, 'UNSUPPORTED')
        self.assertEqual(result.issues[0].category, 'unsupported_rule')
        self.assertFalse(result.complete)

    def test_threshold_rule_requires_an_explicit_event_not_average_yards(self):
        rule = LinearScoringRule('bonus_pass_300', 'games_pass_300', OFFENSE, 'Synthetic event-count schema')
        assessment = assess({'bonus_pass_300': 3}, definitions=(rule,))
        absent = score_evidence(assessment, observe({'pass_yd': 350}))
        self.assertFalse(absent.complete)
        event = score_evidence(assessment, observe({'games_pass_300': 0.25}))
        self.assertEqual(event.require_points(), 0.75)

    def test_inapplicable_and_unknown_position_are_not_missing_zeroes(self):
        definitions = (LinearScoringRule('rec', 'rec', OFFENSE, 'Synthetic reception schema'),
                       LinearScoringRule('bonus_rec_te', 'rec', ('TE',), 'Synthetic TE premium'))
        assessment = assess({'rec': 0.5, 'bonus_rec_te': 1}, definitions=definitions)
        receiver = score_evidence(assessment, observe({'rec': 4}, position='WR'))
        tight_end = score_evidence(assessment, observe({'rec': 4}, position='TE'))
        unknown = score_evidence(assessment, observe({'rec': 4}, position=None))
        self.assertEqual(receiver.require_points(), 2)
        self.assertEqual(receiver.inapplicable_settings, ('bonus_rec_te',))
        self.assertEqual(tight_end.require_points(), 6)
        self.assertFalse(unknown.complete)
        self.assertEqual({i.category for i in unknown.issues}, {'missing_position'})
        with self.assertRaisesRegex(ValueError, 'canonical'):
            observe({'rec': 4}, position='UNKNOWN')

    def test_unverified_applicability_is_limited_even_with_full_stats(self):
        rule = LinearScoringRule('fum_rec', 'fum_rec', None, 'Applicability not established')
        assessment = assess({'fum_rec': 2}, definitions=(rule,))
        result = score_evidence(assessment, observe({'fum_rec': 1}))
        self.assertEqual(assessment.support, 'LIMITED')
        self.assertFalse(result.complete)
        self.assertEqual(result.issues[0].category, 'unknown_applicability')

    def test_horizon_season_week_mismatches_never_produce_usable_points(self):
        for changes in ({'season': 2027}, {'week': 2}, {'horizon': 'ROS'}, {'horizon': 'SEASON', 'week': None}):
            result = score_evidence(assess({'pass_td': 6}), observe({'pass_td': 2}, **changes))
            self.assertFalse(result.complete)
            self.assertIn('source_scope_mismatch', {i.category for i in result.issues})
            with self.assertRaises(CoverageIncomplete):
                result.require_points()

    def test_scope_hashes_prevent_cross_league_operation_and_season_reuse(self):
        original = ScoringScope('synthetic-a', 2026, 'weekly-projection', 'WEEKLY', 1)
        scopes = (original, replace(original, league_id='synthetic-b'),
                  replace(original, operation='observed-production'), replace(original, season=2027),
                  replace(original, week=2), replace(original, horizon='ROS'))
        results = [assess({'pass_td': 6}, scope=scope) for scope in scopes]
        self.assertEqual(len({r.rules_hash for r in results}), len(scopes))
        self.assertEqual(len({r.scoring_hash for r in results}), 1)

    def test_deterministic_serialization_and_explicit_schema_rejection(self):
        first = assess({'pass_td': 4, 'pass_yd': 0.04}, definitions=catalogue('pass_td', 'pass_yd'))
        second = assess({'pass_yd': 0.04, 'pass_td': 4}, definitions=catalogue('pass_yd', 'pass_td'))
        self.assertEqual(first, second)
        result = score_evidence(first, observe({'pass_yd': 250, 'pass_td': 2}))
        serialized = json.loads(canonical_json(result))
        self.assertEqual(restore_record(ScoredEvidence, serialized), result)
        for record_type, record in ((RuleAssessment, first), (StatEvidence, result.source_evidence),
                                    (ScoredEvidence, result)):
            with self.assertRaisesRegex(ValueError, 'Unsupported'):
                restore_record(record_type, {**json.loads(canonical_json(record)), 'schema_version': 2})

    def test_invalid_record_shapes_and_provenance_are_rejected(self):
        for arguments in ({'source': ''}, {'source_schema': ''}, {'horizon': 'DRAFT'},
                          {'week': None}, {'season': True}, {'week': True}):
            with self.subTest(arguments=arguments), self.assertRaises(ValueError):
                observe({}, **arguments)
        with self.assertRaises(ValueError):
            observe({'pass_td': {'not': 'a scalar'}})
        with self.assertRaises(ValueError):
            assess({'pass_td': 6}, definitions=catalogue('pass_td', 'pass_td'))
        with self.assertRaises(ValueError):
            StatObservation('pass_td', float('inf'), 'OBSERVED')
        with self.assertRaises(ValueError):
            StatObservation('pass_td', 3, 'STRUCTURAL_ZERO', 'synthetic rule')

    def test_overflow_never_leaks_nonfinite_points(self):
        for scoring, stats in (({'pass_td': 1e308}, {'pass_td': 2}),
                               ({'pass_td': 1e308, 'pass_yd': 1e308}, {'pass_td': 1, 'pass_yd': 1})):
            result = score_evidence(assess(scoring), observe(stats))
            self.assertFalse(result.complete)
            self.assertIn('nonfinite_result', {i.category for i in result.issues})
            json.loads(canonical_json(result))

    def test_core_calculation_never_contacts_network_or_uses_a_clock(self):
        with patch('socket.socket.connect', side_effect=AssertionError('network')), \
                patch('time.time', side_effect=AssertionError('clock')):
            self.assertEqual(score_evidence(assess({'pass_td': 6}), observe({'pass_td': 2})).require_points(), 12)

    def test_reference_inventory_accounts_for_every_rule_without_claiming_support(self):
        result = inventory()
        expected = json.loads(Path(__file__).with_name('fixtures').joinpath('modular/scoring_inventory.json').read_text())
        self.assertEqual(result, expected)
        for profile, record in result['profiles'].items():
            scoring = rules(profile)['scoring_settings']
            rows = record['nonzero_settings']
            self.assertEqual({r['setting'] for r in rows}, {k for k, v in scoring.items() if v != 0})
            self.assertEqual(set(record['disabled_settings']), {k for k, v in scoring.items() if v == 0})
            self.assertEqual(record['support'], 'UNSUPPORTED')
            self.assertTrue(all(r['verified_provider_fields'] is None for r in rows))
            self.assertTrue(all(r['missing_data_behavior'].startswith('BLOCK:') for r in rows))
