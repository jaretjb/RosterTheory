"""Full Waiver search evidence for the exact synthetic reference leagues."""

import unittest

from roster_theory.core.provenance import stable_hash
from roster_theory.inseason.evaluation import InSeasonWeek
from roster_theory.waiver.search import search_waiver_candidates
from scripts.ma001_baseline import offline
from tests.ma001_fixtures import AS_OF, PROFILES, policy, reference_fixture


def search_reference(profile, *, open_slot=False, missing_add=None):
    fixture = reference_fixture(profile, open_slot=open_slot)
    snapshot = fixture.waiver()
    projections = tuple(
        row for row in fixture.projections if row.player_id != missing_add
    )
    result = search_waiver_candidates(
        snapshot,
        weeks=tuple(InSeasonWeek(week, False) for week in (1, 2, 3)),
        projections=projections,
        values=fixture.values(),
        drop_legality={
            player_id: True for player_id in fixture.bundle.teams[0].player_ids
        },
        news_fresh={player.player_id: True for player in fixture.bundle.players},
        input_bundle_hash=stable_hash((profile, open_slot, missing_add)),
        availability_source="synthetic reference fixture",
        policy=policy(profile),
        enable_pruning=False,
        now=AS_OF,
    )
    return fixture, result


class ExactReferenceWaiverSearchTests(unittest.TestCase):
    def test_full_search_keeps_league_policy_and_drop_capacity(self):
        with offline():
            for profile in PROFILES:
                for open_slot in (False, True):
                    with self.subTest(profile=profile, open_slot=open_slot):
                        fixture, result = search_reference(profile, open_slot=open_slot)
                        self.assertEqual(result.league_key, fixture.trade.league_key)
                        self.assertEqual(result.policy_hash, policy(profile).policy_hash)
                        self.assertTrue(result.evidence_hash)
                        owned = {
                            player_id
                            for team in fixture.bundle.teams
                            for player_id in team.player_ids
                        }
                        self.assertEqual(
                            set(result.eligible_candidate_ids),
                            {
                                player.player_id
                                for player in fixture.bundle.players
                                if player.player_id not in owned
                            },
                        )
                        self.assertEqual(
                            {row.add_player_id for row in result.exact_evaluations},
                            set(result.eligible_candidate_ids),
                        )
                        self.assertFalse(result.budget_excluded_player_ids)
                        self.assertFalse(result.sleeper_write_performed)
                        for evaluation in result.exact_evaluations:
                            self.assertEqual(
                                evaluation.selected_drop_player_id is None,
                                open_slot,
                            )

    def test_missing_add_projection_is_visible_without_global_veto(self):
        with offline():
            for profile in PROFILES:
                with self.subTest(profile=profile):
                    _, result = search_reference(profile, missing_add="fa_RB")
                    self.assertNotIn("fa_RB", result.eligible_candidate_ids)
                    self.assertIn(
                        ("fa_RB", "INCOMPLETE_PROJECTION_COVERAGE"),
                        {(row.player_id, row.reason) for row in result.omissions},
                    )
                    self.assertTrue(result.exact_evaluations)
                    self.assertFalse(result.sleeper_write_performed)


if __name__ == "__main__":
    unittest.main()
