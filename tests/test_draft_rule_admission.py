"""Room admission must happen before recommendations, including cache reuse."""
from types import SimpleNamespace
from contextlib import redirect_stdout
from dataclasses import asdict
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from roster_theory.cli import command_recommend
from roster_theory.core.errors import CoverageIncomplete
from roster_theory.mock_watcher import MockDraftWatcher
from roster_theory.core.capabilities import CapabilityAssessment, RuleCapability
from roster_theory.core.errors import RosterIllegal
from roster_theory.core.provenance import canonical_json
from roster_theory.core.run_contract import restore_record
from roster_theory.providers.sleeper_draft_rules import assess_draft_position_limits
from scripts.ma002_draft_rules import main as inspect_rules
from tests.ma001_fixtures import PROFILES, rules


def draft_room(enforcement=0):
    return {'draft_id': '123456789012345678', 'status': 'drafting', 'type': 'snake',
            'metadata': {'scoring_type': 'half_ppr'},
            'settings': {'teams': 10, 'rounds': 15, 'enforce_position_limits': enforcement}}


class DraftRoomAdmissionTests(unittest.TestCase):
    def test_watcher_blocks_unknown_rules_before_fetching_picks_or_computing(self):
        client = Mock()
        room = draft_room()
        del room['settings']['enforce_position_limits']
        client.draft.return_value = room
        client.draft_picks.return_value = []
        client.last_get_metadata = {}
        watcher = MockDraftWatcher(client, room['draft_id'], [], claimed_slot=1)
        with patch('roster_theory.mock_watcher.recommend_for_state', return_value={}) as recommend:
            with self.assertRaisesRegex(CoverageIncomplete, 'position'):
                watcher.poll_once(now=100)
        client.draft_picks.assert_not_called()
        client.draft.assert_called_once_with(room['draft_id'], fresh=True)
        recommend.assert_not_called()

    def test_recommend_command_blocks_enabled_limits_before_loading_the_board(self):
        client = Mock()
        client.draft.return_value = draft_room(1)
        client.draft_picks.return_value = []
        args = SimpleNamespace(league='synthetic', board='unused', slot=1, limit=3)
        with patch('roster_theory.cli.SleeperClient', return_value=client), \
             patch('roster_theory.cli.find_league_config', return_value={'draft_id': 'synthetic'}), \
             patch('roster_theory.cli._load_board') as board, \
             patch('roster_theory.cli.recommend_available', return_value=[]) as recommend, \
             patch('roster_theory.cli._print_json'):
            with self.assertRaisesRegex(CoverageIncomplete, 'position'):
                command_recommend(args)
        client.draft_picks.assert_not_called()
        client.draft.assert_called_once_with('synthetic', fresh=True)
        board.assert_not_called()
        recommend.assert_not_called()

    def test_rule_change_blocks_cached_recommendation_and_clears_planned_turn(self):
        room = draft_room()
        client = Mock(last_get_metadata={})
        client.draft.return_value = room
        client.draft_picks.return_value = []
        watcher = MockDraftWatcher(client, room['draft_id'], [], claimed_slot=1)
        with patch('roster_theory.mock_watcher.recommend_for_state', return_value={'recommendations': {}}) as recommend:
            first = watcher.poll_once(now=100)
            duplicate = watcher.poll_once(now=101)
            self.assertEqual(first['recommendation'], duplicate['recommendation'])
            self.assertTrue(duplicate['recommendation_cached'])
            self.assertEqual(recommend.call_count, 1)
            watcher.planned_turn = {'second_pick': 2}
            room['settings']['enforce_position_limits'] = 1
            with self.assertRaises(CoverageIncomplete):
                watcher.poll_once(now=102)
            self.assertIsNone(watcher.last_recommendation)
            self.assertIsNone(watcher.planned_turn)
            self.assertEqual(client.draft_picks.call_count, 2)
            room['settings']['enforce_position_limits'] = 0
            refreshed = watcher.poll_once(now=103)
            self.assertFalse(refreshed['recommendation_cached'])
            self.assertEqual(recommend.call_count, 2)

    def test_disabled_command_preserves_existing_output_and_taxi_rejection(self):
        room = draft_room()
        client = Mock()
        client.draft.return_value = room
        client.draft_picks.return_value = []
        args = SimpleNamespace(league='synthetic', board='unused', slot=1, limit=3)
        with patch('roster_theory.cli.SleeperClient', return_value=client), \
             patch('roster_theory.cli.find_league_config', return_value={'draft_id': room['draft_id']}), \
             patch('roster_theory.cli._load_board', return_value=[]), \
             patch('roster_theory.cli.recommend_available', return_value=['synthetic']) as recommend, \
             patch('roster_theory.cli._print_json') as output:
            command_recommend(args)
            self.assertEqual(output.call_args.args[0], {'draft_id': room['draft_id'],
                'draft_status': 'drafting', 'current_pick': 1, 'draft_slot': 1,
                'recommendations': ['synthetic']})
            room['settings']['taxi_slots'] = 1
            with self.assertRaises(RosterIllegal):
                command_recommend(args)
            self.assertEqual(recommend.call_count, 1)
            self.assertEqual(client.draft_picks.call_count, 1)


class CapabilityContractTests(unittest.TestCase):
    def test_status_and_admission_are_scoped_and_fail_closed(self):
        for classification, status, admitted in (('SUPPORTED', 'SUPPORTED', True),
                ('IRRELEVANT', 'SUPPORTED', True), ('UNKNOWN', 'LIMITED', False),
                ('UNSUPPORTED', 'UNSUPPORTED', False)):
            with self.subTest(classification=classification):
                row = RuleCapability('fixture.rule', classification, 'Synthetic rule evidence')
                result = CapabilityAssessment('fixture', 'operation', 'one_rule', (row,))
                self.assertEqual(result.status, status)
                self.assertEqual(result.scope_admitted, admitted)
                self.assertEqual(bool(result.blockers), not admitted)
                self.assertEqual(restore_record(CapabilityAssessment, json.loads(canonical_json(result))), result)
        empty = CapabilityAssessment('fixture', 'operation', 'one_rule', ())
        self.assertFalse(empty.scope_admitted)
        self.assertEqual(empty.status, 'LIMITED')

    def test_bad_classifications_duplicate_rules_and_future_schemas_are_rejected(self):
        with self.assertRaises(ValueError):
            RuleCapability('rule', 'IGNORED', 'Typo must not admit a rule')
        row = RuleCapability('rule', 'UNKNOWN', 'Missing')
        with self.assertRaises(ValueError):
            CapabilityAssessment('draft', 'operation', 'scope', (row, row))
        with self.assertRaises(ValueError):
            CapabilityAssessment('draft', 'operation', 'scope', (row,), schema_version=2)

    def test_absent_null_malformed_and_non_binary_enforcement_stay_unknown(self):
        for value in (None, True, False, '0', '1', 0.0, 1.0, -1, 2, [], {}):
            with self.subTest(value=value):
                result = assess_draft_position_limits(draft_room(value))
                self.assertEqual(result.status, 'LIMITED')
                self.assertEqual(result.checks[0].classification, 'UNKNOWN')
        absent = assess_draft_position_limits({'settings': {}})
        explicit_null = assess_draft_position_limits(draft_room(None))
        self.assertNotEqual(absent.checks[0].evidence, explicit_null.checks[0].evidence)
        for settings in (None, [], 'invalid', 1):
            self.assertFalse(assess_draft_position_limits({'settings': settings}).scope_admitted)

    def test_disabled_enforcement_does_not_claim_that_the_league_has_no_limits(self):
        room = draft_room()
        room['settings'].update({'slots_qb': 1, 'max_qb': 2})
        result = assess_draft_position_limits(room)
        self.assertEqual(result.status, 'SUPPORTED')
        self.assertEqual(result.scope, 'position_limits')
        self.assertEqual(result.checks[1].classification, 'IRRELEVANT')

    def test_enabled_limits_never_come_from_slots_preferences_or_unverified_fields(self):
        room = draft_room(1)
        room['settings'].update({'slots_qb': 1, 'slots_bn': 6, 'max_qb': 2,
                                 'position_limits': {'QB': 2}})
        original = copy.deepcopy(room)
        result = assess_draft_position_limits(room)
        self.assertEqual(result.checks[0].classification, 'SUPPORTED')
        self.assertEqual(result.checks[1].classification, 'UNKNOWN')
        self.assertFalse(result.scope_admitted)
        self.assertEqual(room, original)

    def test_reference_profiles_do_not_imply_verified_caps(self):
        for profile, enforcement in zip(PROFILES, ('UNKNOWN', 'SUPPORTED')):
            result = assess_draft_position_limits(rules(profile)['draft'])
            self.assertEqual(result.status, 'LIMITED')
            self.assertEqual(result.checks[0].classification, enforcement)
            self.assertEqual(result.checks[1].classification, 'UNKNOWN')

    def test_saved_rule_inspection_is_read_only_scoped_and_machine_readable(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'draft.json'
            for flag, expected_code in ((0, 0), (1, 2)):
                encoded = json.dumps(draft_room(flag))
                path.write_text(encoded, encoding='utf-8')
                output = io.StringIO()
                with patch('sys.argv', ['inspect', str(path)]), redirect_stdout(output):
                    self.assertEqual(inspect_rules(), expected_code)
                result = json.loads(output.getvalue())
                self.assertEqual(result['scope'], 'position_limits')
                self.assertEqual(result['checks'], json.loads(json.dumps(asdict(
                    assess_draft_position_limits(draft_room(flag)))) )['checks'])
                self.assertEqual(path.read_text(encoding='utf-8'), encoded)
