"""Migration compatibility guards; correctness oracles are independent of golden capture."""
from dataclasses import replace
import json
import unittest

from scripts.ma001_baseline import compatibility, evidence, offline, workloads
from tests.ma001_fixtures import AS_OF, PROFILES, ROOT, draft_fixture, policy, reference_fixture, rules
from roster_theory.core.provenance import stable_hash
from roster_theory.core.scoring import score_stats
from roster_theory.mock_watcher import reconcile_draft_state
from roster_theory.waiver.evaluation import evaluate_waiver
from roster_theory.waiver.policy import apply_waiver_policy
from roster_theory.inseason.evaluation import InSeasonWeek
from roster_theory.trade.evaluation import diagnose_roster


class ModularBaselineTests(unittest.TestCase):
    def test_public_parser_compatibility(self):
        self.assertEqual(compatibility(), json.loads((ROOT / 'compatibility.json').read_text()))

    def test_synthetic_reference_completeness_and_independence(self):
        left, right = (reference_fixture(p) for p in PROFILES)
        for f, size, starters, reserve in ((left, 10, 9, 0), (right, 12, 10, 1)):
            self.assertEqual(len(f.bundle.teams), size)
            ids = {p.player_id for p in f.bundle.players}
            self.assertEqual(len(ids), len(f.bundle.players))
            self.assertTrue(all(p.name.startswith('Synthetic ') for p in f.bundle.players))
            for team in f.bundle.teams:
                self.assertTrue(team.owner_id.startswith('synthetic-owner-'))
                self.assertEqual(len(set(team.player_ids) - set(team.reserve_ids)), 15)
                self.assertEqual(len(team.starter_ids), starters)
                self.assertTrue(set(team.player_ids) <= ids)
            self.assertEqual(len(f.bundle.teams[0].reserve_ids), reserve)
            self.assertEqual({(p.player_id, p.week) for p in f.projections},
                             {(pid, week) for pid in ids for week in (1, 2, 3)})
        self.assertNotEqual(policy(PROFILES[0]).policy_hash, policy(PROFILES[1]).policy_hash)
        self.assertNotEqual(stable_hash(left.trade.manifest), stable_hash(right.trade.manifest))

    def test_rule_inventory_contains_rules_not_provider_identities(self):
        for profile in PROFILES:
            value = rules(profile)
            self.assertEqual(set(value), {'draft', 'observed_at', 'source', 'team_count',
                'roster_positions', 'scoring_settings', 'settings',
                'omitted_operational_setting_keys', 'policy_status'})
            for mapping in (value['settings'], value['scoring_settings'], value['draft']['settings']):
                self.assertTrue(all(isinstance(v, (int, float)) for v in mapping.values()))
                self.assertTrue(all(not k.endswith('_id') for k in mapping))

    def test_same_raw_stats_obey_each_scoring_map(self):
        # Only this deliberately bounded QB line is scored; not a whole-provider completeness claim.
        stats = {'pass_yd': 250, 'pass_td': 2, 'pass_int': 1, 'rush_yd': 10, 'rush_td': 0,
                 'pass_2pt': 0, 'rush_2pt': 0, 'fum_lost': 0}
        scores = [score_stats(stats, rules(p)['scoring_settings'], position='QB').points for p in PROFILES]
        self.assertEqual(scores, [17.0, 18.0])  # 10 yards + 8 TD - 2/1 INT + 1 rushing
        self.assertEqual(stats['pass_int'], 1)

    def test_semantic_baseline(self):
        golden = json.loads((ROOT / 'semantics-membership-v2.json').read_text())['profiles']
        with offline():
            for profile in PROFILES:
                for name, function in workloads(profile).items():
                    with self.subTest(profile=profile, operation=name):
                        self.assertEqual(evidence(function()), golden[profile][name])

    def test_skill_lineup_totals_have_an_independent_expected_value(self):
        with offline():
            for profile, expected in zip(PROFILES, (126.0, 140.0)):
                f = reference_fixture(profile)
                result = diagnose_roster(f.trade, projections=f.projections)
                # A: QB21 + RB20/19 + WR18/17 + TE16 + FLEX15 = 126.
                # B adds a second FLEX14 = 140. K/DST are outside this Trade scope.
                self.assertEqual(dict(result.weekly_optimal_points), {1: expected, 2: expected, 3: expected})

    def test_watch_transitions_at_both_reference_sizes(self):
        for profile in PROFILES:
            draft, _ = draft_fixture(profile)
            picks = [{'pick_no': 1, 'draft_slot': 1, 'roster_id': 1,
                      'player_id': 'synthetic-1', 'metadata': {'position': 'QB'}}]
            initial = reconcile_draft_state(draft, (), 1)
            appended = reconcile_draft_state(draft, picks, 1, initial)
            duplicate = reconcile_draft_state(draft, picks, 1, appended)
            edited = reconcile_draft_state(draft, [{**picks[0], 'player_id': 'synthetic-2'}], 1, duplicate)
            undo = reconcile_draft_state(draft, (), 1, edited)
            self.assertEqual([s.transition for s in (appended, duplicate, edited, undo)],
                             ['append', 'duplicate', 'edit', 'undo'])
            self.assertEqual(appended.next_user_pick, 2 * rules(profile)['team_count'])
            self.assertTrue(undo.is_user_turn)

    def test_named_waiver_open_slot_specialists_and_no_mutation(self):
        with offline():
            for profile in PROFILES:
                f = reference_fixture(profile, open_slot=True)
                snapshot = f.waiver()
                before = stable_hash(snapshot)
                for position in ('K', 'DST'):
                    result = apply_waiver_policy(evaluate_waiver(snapshot,
                        add_player_id='fa_' + position, weeks=(InSeasonWeek(1, False),),
                        projections=f.projections, values=f.values(),
                        drop_legality={p: False for p in f.bundle.teams[0].player_ids},
                        news_fresh={p.player_id: True for p in f.bundle.players}, now=AS_OF),
                        replace(policy(profile), priority_enabled=False))
                    self.assertIsNone(result.selected_drop_player_id)
                self.assertEqual(stable_hash(snapshot), before)
