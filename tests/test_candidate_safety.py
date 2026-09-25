import unittest
from dataclasses import replace

from roster_theory.waiver.evaluation import evaluate_waiver
from roster_theory.waiver.policy import apply_waiver_policy, load_waiver_policy
from roster_theory.waiver.priority import WaiverPriorityEvidence, WaiverPriorityWeights
from roster_theory.core.errors import RosterIllegal
from tests.test_waiver_evaluation import NOW, legality, projections, values, waiver_snapshot, weeks
from tests.test_waiver_policy import POLICY_PATH
from tests.test_waiver_search import search


class CandidateSafetyTests(unittest.TestCase):
    def evaluated(self):
        priorities = {
            pid: WaiverPriorityEvidence(
                player_id=pid, composite_score=score, coverage_status="COMPLETE",
                components=(), missing_signals=(), configured_weights=WaiverPriorityWeights(),
                weighting_method="fixture", acquisition_only=False,
            )
            for pid, score in (("add", 80), ("bench", 40))
        }
        return evaluate_waiver(
            waiver_snapshot(), add="Target Quarterback", drop="Bench Receiver",
            weeks=weeks(), projections=projections(), values=values(),
            drop_legality=legality(), news_fresh={"add": True},
            waiver_priorities=priorities, now=NOW,
        )

    def assess(self, evaluation):
        return apply_waiver_policy(
            evaluation, replace(load_waiver_policy(POLICY_PATH), priority_enabled=True)
        )

    def test_priority_path_cannot_bypass_required_evidence(self):
        for field in ("projection_inputs_complete", "value_inputs_complete"):
            with self.subTest(field=field):
                result = self.assess(replace(self.evaluated(), **{field: False}))
                self.assertNotIn(result.decision_label, {"ADD NOW", "CLAIM", "ACQUIRE"})
                self.assertIn("complete_required_evidence", {g.name for g in result.decision.gates if not g.passed})

    def test_priority_path_rejects_severe_losses_including_watch(self):
        original = self.evaluated()
        candidate = original.candidates[0]
        cases = (
            replace(candidate, current_week_delta=-100),
            replace(candidate, lineup=replace(candidate.lineup, weighted_delta=-257)),
            replace(candidate, holding=replace(candidate.holding, applicable=False),
                    lineup=replace(candidate.lineup, depth_delta=-100)),
            replace(candidate, risk=replace(candidate.risk, offense_downside_loss_delta=100)),
        )
        for index, candidate in enumerate(cases):
            with self.subTest(case=index):
                result = self.assess(replace(original, candidates=(candidate,)))
                self.assertEqual(result.decision_label, "PASS")

    def test_unknown_drop_is_excluded_without_aborting_other_moves(self):
        result = search(drop_legality={**legality(), "bench": None})
        self.assertTrue(result.exact_evaluations)
        self.assertTrue(any(row.reason == "DROP_LEGALITY_UNKNOWN" for row in result.omissions))
        self.assertFalse(any(c.drop_player_id == "bench" for row in result.exact_evaluations for c in row.candidates))

    def test_no_legal_drops_returns_visible_exclusions_not_report_failure(self):
        result = search(drop_legality={})
        self.assertFalse(result.exact_evaluations)
        self.assertTrue(any(row.reason == "NO_PROVED_LEGAL_DROP" for row in result.omissions))

    def test_league_lock_applies_even_with_open_roster_slot(self):
        from tests.test_waiver_search import complete_search_snapshot
        snapshot = complete_search_snapshot()
        snapshot = replace(snapshot, league=replace(snapshot.league, platform_settings=(("disable_adds", 1),)),
                           roster_capacity=tuple(replace(row, open_active_slots=1) for row in snapshot.roster_capacity))
        result = search(snapshot=snapshot)
        self.assertFalse(result.exact_evaluations)
        self.assertTrue(any(row.reason == "LEAGUE_MOVES_LOCKED" for row in result.omissions))
        with self.assertRaisesRegex(RosterIllegal, "League.*locked"):
            evaluate_waiver(snapshot, add_player_id="add", weeks=weeks(), projections=projections(),
                            values=values(), drop_legality=legality(), now=NOW)

    def test_watch_has_reversible_news_blocker_and_holding_unknown_is_not_affirmative(self):
        original = self.evaluated()
        watch = self.assess(replace(original, material_news_fresh=False))
        self.assertEqual(watch.decision_label, "WATCH")
        self.assertEqual(watch.decision.decision_path, "THREE_SIGNAL_WAIVER_VALUE_BLOCKED")
        self.assertIn("news", watch.strongest_uncertainty.lower())
        candidate = original.candidates[0]
        missing_pool = replace(candidate, holding=replace(candidate.holding, applicable=True,
                                                          streaming_omission_ids=("unknown",)))
        self.assertEqual(self.assess(replace(original, candidates=(missing_pool,))).decision_label, "PASS")

    def test_retention_protection_cannot_be_watch_despite_high_acquisition_value(self):
        original = self.evaluated()
        candidate = original.candidates[0]
        comparison = replace(candidate.waiver_value, drop=replace(candidate.waiver_value.drop, retention_protected=True))
        result = self.assess(replace(original, candidates=(replace(candidate, waiver_value=comparison),)))
        self.assertEqual(result.decision_label, "PASS")

    def test_unknown_value_on_alternative_drop_does_not_veto_exact_automatic_search(self):
        result = evaluate_waiver(
            waiver_snapshot(), add_player_id="add", weeks=weeks(), projections=projections(),
            values=tuple(row for row in values() if row.player_id != "wr"),
            drop_legality=legality(), news_fresh={"add": True}, now=NOW,
        )
        self.assertNotIn("wr", {row.drop_player_id for row in result.candidates})
        self.assertTrue(result.value_inputs_complete)
        self.assertTrue(any(row.player_id == "wr" and row.reason == "INCOMPLETE_VALUE_EVIDENCE" for row in result.exclusions))
