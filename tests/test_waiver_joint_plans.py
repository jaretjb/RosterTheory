import unittest
from dataclasses import replace
from unittest.mock import patch

from roster_theory.inseason.evaluation import (
    InSeasonContext,
    build_weekly_projection_matrix,
    team_impact,
)
from roster_theory.waiver.evaluation import evaluate_waiver, WaiverEvaluationOptions
from roster_theory.waiver.plans import hypothetical_claim, validate_claim_branch
from roster_theory.waiver.priority import build_waiver_priority_scores

from roster_theory.waiver.policy import apply_waiver_policy, load_waiver_policy
from roster_theory.waiver.search import _claim_plan, search_waiver_candidates
from roster_theory.waiver.service import _special_team_lines
from tests import test_candidate_safety as safety_fixtures
from tests.test_waiver_policy import POLICY_PATH
from tests.test_waiver_search import search
from tests.test_waiver_search import (
    complete_search_snapshot,
    complete_projections,
    complete_values,
    news,
)
from tests.test_waiver_evaluation import weeks, legality, NOW


class JointWaiverTests(unittest.TestCase):
    def test_named_and_search_quarantine_the_same_missing_roster_projection(self):
        projection_rows = tuple(row for row in complete_projections() if row.player_id != "wr")
        policy = replace(load_waiver_policy(POLICY_PATH), priority_enabled=False)
        result = search(projection_rows=projection_rows)
        for found in result.exact_evaluations:
            named = apply_waiver_policy(
                evaluate_waiver(
                    complete_search_snapshot(),
                    add_player_id=found.add_player_id,
                    weeks=weeks(),
                    projections=projection_rows,
                    values=complete_values(),
                    drop_legality=legality(),
                    news_fresh=news(),
                    now=NOW,
                ),
                policy,
            )
            self.assertEqual(named.selected_drop_player_id, found.selected_drop_player_id)
            self.assertEqual(named.decision, found.decision)
            self.assertFalse(named.projection_inputs_complete)
            self.assertIn("wr", {row.player_id for row in named.exclusions})

    def test_cli_budget_is_opt_in_and_positive(self):
        from roster_theory.cli import build_parser

        parser = build_parser()
        args = parser.parse_args(["waiver", "search", "league_alpha"])
        self.assertIsNone(args.exact_candidate_budget)
        args = parser.parse_args(
            ["waiver", "search", "league_alpha", "--exact-candidate-budget", "2"]
        )
        self.assertEqual(args.exact_candidate_budget, 2)
        for invalid in (0, -1, True, 1.5):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                search(exact_candidate_budget=invalid)

    def test_named_and_search_select_identical_pair_and_gates(self):
        policy = replace(load_waiver_policy(POLICY_PATH), priority_enabled=False)
        result = search()
        for found in result.exact_evaluations:
            named = apply_waiver_policy(
                evaluate_waiver(
                    complete_search_snapshot(),
                    add_player_id=found.add_player_id,
                    weeks=weeks(),
                    projections=complete_projections(),
                    values=complete_values(),
                    drop_legality=legality(),
                    news_fresh=news(),
                    now=NOW,
                ),
                policy,
            )
            self.assertEqual(named.selected_drop_player_id, found.selected_drop_player_id)
            self.assertEqual(named.decision, found.decision)

    def test_budget_can_miss_best_joint_move_and_never_claims_dominance(self):
        ranks = {"add": 1, "fa_rb": 10, "rb": 40, "bench": 49}
        ranked_values = tuple(
            replace(
                row,
                current_week_position_rank=ranks.get(row.player_id, 90),
                rest_of_season_position_rank=ranks.get(row.player_id, 90),
            )
            for row in complete_values()
        )
        projection_rows = tuple(
            replace(row, league_points=0 if row.player_id == "add" else 20)
            if row.player_id in {"add", "fa_rb"}
            else row
            for row in complete_projections()
        )
        kwargs = dict(
            weeks=weeks(),
            projections=projection_rows,
            values=ranked_values,
            drop_legality=legality(),
            news_fresh=news(),
            input_bundle_hash="adversarial-fixture",
            availability_source="fixture",
            policy=load_waiver_policy(POLICY_PATH),
            now=NOW,
        )
        bounded = search_waiver_candidates(
            complete_search_snapshot(), exact_candidate_budget=1, **kwargs
        )
        exhaustive = search_waiver_candidates(complete_search_snapshot(), **kwargs)
        self.assertEqual(bounded.exact_evaluations[0].add_player_id, "add")
        self.assertEqual(exhaustive.best_add_player_id, "fa_rb")
        self.assertIn(exhaustive.best_add_player_id, bounded.budget_excluded_player_ids)
        self.assertEqual(exhaustive.best_decision_label, "ADD NOW")
        self.assertEqual(bounded.recommended_action, "NO ACTION")
        self.assertEqual(bounded.coverage_status, "BUDGET_LIMITED")
        snapshot = complete_search_snapshot()
        priorities = build_waiver_priority_scores(
            players=snapshot.players,
            values=ranked_values,
            owner_by_player=dict(snapshot.owner_by_player),
            current_bye_teams=(),
            waiver_wire_evidence=None,
        )
        named = apply_waiver_policy(
            evaluate_waiver(
                snapshot,
                add="Free Runner",
                weeks=weeks(),
                projections=projection_rows,
                values=ranked_values,
                drop_legality=legality(),
                news_fresh=news(),
                waiver_priorities=priorities,
                now=NOW,
            ),
            kwargs["policy"],
        )
        self.assertEqual(named.selected_drop_player_id, exhaustive.best_drop_player_id)
        self.assertEqual(named.decision, exhaustive.exact_evaluations[0].decision)

    def test_specialist_can_drop_skill_bench_but_not_protected_injured_asset(self):
        snapshot = complete_search_snapshot()
        snapshot = replace(
            snapshot,
            league=replace(
                snapshot.league, roster_positions=(*snapshot.league.roster_positions[:-1], "K")
            ),
            players=tuple(
                replace(row, positions=("K",)) if row.player_id == "fa_te" else row
                for row in snapshot.players
            ),
        )
        value_rows = tuple(
            replace(
                row,
                current_week_position_rank=1,
                rest_of_season_position_rank=1,
                selected_value=40,
                market_value=40,
                raw_projection=36,
            )
            if row.player_id == "fa_te"
            else replace(row, rest_of_season_position_rank=1)
            for row in complete_values()
        )
        projection_rows = tuple(
            replace(row, league_points=12) if row.player_id == "fa_te" else row
            for row in complete_projections()
        )

        def evaluate(state):
            priorities = build_waiver_priority_scores(
                players=state.players,
                values=value_rows,
                owner_by_player=dict(state.owner_by_player),
                current_bye_teams=(),
                waiver_wire_evidence=None,
            )
            return apply_waiver_policy(
                evaluate_waiver(
                    state,
                    add_player_id="fa_te",
                    drop_player_id="bench",
                    weeks=weeks(),
                    projections=projection_rows,
                    values=value_rows,
                    drop_legality=legality(),
                    news_fresh=news(),
                    waiver_priorities=priorities,
                    now=NOW,
                ),
                load_waiver_policy(POLICY_PATH),
            )

        result = evaluate(snapshot)
        self.assertEqual(result.decision_label, "CLAIM")
        injured = replace(
            snapshot,
            players=tuple(
                replace(row, injury_status="IR") if row.player_id == "bench" else row
                for row in snapshot.players
            ),
        )
        protected = evaluate(injured)
        self.assertNotIn(protected.decision_label, {"ADD NOW", "CLAIM", "ACQUIRE"})
        self.assertTrue(protected.candidates[0].waiver_value.drop.retention_protected)
        unsafe = replace(
            result,
            candidates=(
                replace(
                    result.candidates[0],
                    lineup=replace(result.candidates[0].lineup, depth_delta=-1000),
                ),
            ),
        )
        self.assertNotIn(
            apply_waiver_policy(unsafe, load_waiver_policy(POLICY_PATH)).decision_label,
            {"ADD NOW", "CLAIM", "ACQUIRE"},
        )

    def test_skill_add_considers_legal_specialist_drop(self):
        snapshot = complete_search_snapshot()
        snapshot = replace(
            snapshot,
            players=tuple(
                replace(row, positions=("K",)) if row.player_id == "bench" else row
                for row in snapshot.players
            ),
        )
        result = search(snapshot=snapshot)
        for evaluated in result.exact_evaluations:
            self.assertIn("bench", {row.drop_player_id for row in evaluated.candidates})

    def branch_fixture(self, open_slots=False):
        snapshot = complete_search_snapshot(open_slot=open_slots)
        context = InSeasonContext(
            snapshot.players,
            snapshot.league.roster_positions,
            weeks(),
            ("add", "fa_rb", "fa_wr", "fa_te"),
            current_week=1,
        )
        matrix = build_weekly_projection_matrix(context, complete_projections())
        return snapshot, dict(
            context=context,
            matrix=matrix,
            roster_player_ids={"qb", "rb", "wr", "bench"},
            options=WaiverEvaluationOptions(),
            policy=replace(load_waiver_policy(POLICY_PATH), priority_enabled=False),
        )

    def test_cumulative_branch_rejects_combined_depth_loss(self):
        snapshot, kwargs = self.branch_fixture()
        original = search().exact_evaluations[0]
        rows = (
            replace(original, add_player_id="fa_rb", selected_drop_player_id="bench"),
            replace(original, add_player_id="fa_wr", selected_drop_player_id="wr"),
        )
        calls = []

        def recheck(branch, add, drop):
            calls.append(branch)
            return rows[1]

        def cumulative(*args, **kw):
            actual = team_impact(*args, **kw)
            # Each independent move fits one loss budget, but together exceed it.
            loss = kwargs["policy"].maximum_depth_loss * (1.5 if "fa_wr" in args[4] else 0.75)
            return replace(actual, depth_delta=-loss, weighted_delta=5.0)

        with patch("roster_theory.waiver.plans.team_impact", side_effect=cumulative):
            checks = validate_claim_branch(snapshot, rows, evaluate_pair=recheck, **kwargs)
        self.assertTrue(checks[0].accepted)
        self.assertFalse(checks[1].accepted)
        self.assertEqual(checks[1].priorities, (1, 2))
        self.assertIn("cumulative depth loss", checks[1].reason)
        self.assertIn("fa_rb", dict(calls[0].owner_by_player))
        self.assertNotIn("bench", dict(calls[0].owner_by_player))
        dropped = next(row for row in calls[0].acquisitions if row.player_id == "bench")
        self.assertEqual(dropped.state, "LOCKED")

    def test_changed_roster_rejection_is_not_combined_even_with_distinct_drops(self):
        snapshot, kwargs = self.branch_fixture()
        template = search().exact_evaluations[0]
        rows = (
            replace(template, add_player_id="fa_rb", selected_drop_player_id="bench"),
            replace(template, add_player_id="fa_wr", selected_drop_player_id="wr"),
        )
        checks = validate_claim_branch(
            snapshot,
            rows,
            evaluate_pair=lambda *args: replace(
                rows[1],
                decision_label="PASS",
                strongest_uncertainty="Starter no longer improves lineup",
            ),
            **kwargs,
        )
        self.assertFalse(checks[1].accepted)
        self.assertIn("Changed-roster evaluation is PASS", checks[1].reason)

    def test_shared_open_slot_branch_is_rejected_after_first_claim(self):
        snapshot, kwargs = self.branch_fixture(open_slots=True)
        template = search(snapshot=snapshot).exact_evaluations[0]
        rows = tuple(
            replace(template, add_player_id=pid, selected_drop_player_id=None)
            for pid in ("fa_rb", "fa_wr")
        )
        checks = validate_claim_branch(
            snapshot, rows, evaluate_pair=lambda *args: self.fail("No slot left"), **kwargs
        )
        self.assertTrue(checks[0].accepted)
        self.assertFalse(checks[1].accepted)
        self.assertIn("Open slot already consumed", checks[1].reason)

    def test_hypothetical_claim_updates_capacity_without_mutating_snapshot(self):
        snapshot, _ = self.branch_fixture(open_slots=True)
        result = hypothetical_claim(snapshot, "fa_rb", None)
        self.assertNotIn("fa_rb", dict(snapshot.owner_by_player))
        self.assertEqual(dict(result.owner_by_player)["fa_rb"], snapshot.user_roster_id)
        self.assertEqual(
            next(
                row.open_active_slots
                for row in result.roster_capacity
                if row.roster_id == snapshot.user_roster_id
            ),
            0,
        )

    def test_better_cross_position_pair_beats_affirmative_same_position_pair(self):
        original = safety_fixtures.CandidateSafetyTests().evaluated()
        cross = original.candidates[0]
        same = replace(
            cross,
            drop_player_id="qb",
            drop_position="QB",
            same_position=True,
            lineup=replace(
                cross.lineup,
                weighted_delta=1,
                after_weighted_points=cross.lineup.before_weighted_points + 1,
            ),
        )
        policy = replace(load_waiver_policy(POLICY_PATH), priority_enabled=False)
        self.assertEqual(
            apply_waiver_policy(replace(original, candidates=(same,)), policy).decision_label,
            "ADD NOW",
        )
        result = apply_waiver_policy(replace(original, candidates=(same, cross)), policy)
        self.assertEqual(result.selected_drop_player_id, cross.drop_player_id)

    def test_all_approved_pairs_appear_in_plan_in_exact_order(self):
        result = search()
        approved = [
            (row.add_player_id, row.selected_drop_player_id)
            for row in result.exact_evaluations
            if row.decision_label in {"ADD NOW", "CLAIM", "ACQUIRE"}
        ]
        self.assertTrue(approved)
        self.assertEqual(
            [(row.add_player_id, row.drop_player_id) for row in result.claim_plan], approved
        )
        self.assertEqual((result.best_add_player_id, result.best_drop_player_id), approved[0])
        self.assertEqual(len(result.claim_branch_checks), len(result.claim_plan))
        self.assertTrue(result.claim_branch_checks[0].accepted)

    def test_specialist_display_does_not_hide_approved_fourth_ranked_option(self):
        template = search().exact_evaluations[0]
        rows = tuple(
            replace(
                template,
                add_player_id=f"k{rank}",
                add_position="K",
                decision_label="ADD NOW" if rank == 4 else "PASS",
                candidates=(
                    replace(
                        template.candidates[0],
                        ownership=replace(
                            template.candidates[0].ownership, current_week_add_rank=rank
                        ),
                    ),
                ),
            )
            for rank in range(1, 5)
        )
        text = "\n".join(_special_team_lines(rows, {}, "K"))
        self.assertIn("k4", text)
        self.assertLess(text.index("k4"), text.index("k1"))

    def test_budget_is_visible_and_does_not_label_unevaluated_moves_inferior(self):
        result = search(exact_candidate_budget=1)
        self.assertEqual(len(result.exact_evaluations), 1)
        self.assertEqual(result.coverage_status, "BUDGET_LIMITED")
        self.assertEqual(
            len(result.budget_excluded_player_ids), len(result.eligible_candidate_ids) - 1
        )
        self.assertFalse(result.pruned_candidates)
        self.assertTrue(any("unproved" in warning.lower() for warning in result.warnings))

    def test_shared_open_slot_claims_are_alternatives(self):
        template = search().exact_evaluations[0]
        rows = tuple(
            replace(
                template,
                add_player_id=pid,
                selected_drop_player_id=None,
                candidates=(replace(template.candidates[0], drop_player_id=None),),
            )
            for pid in ("one", "two")
        )
        plan = _claim_plan(rows)
        self.assertEqual(plan[0].claim_group, plan[1].claim_group)
        self.assertEqual(plan[0].mutually_exclusive_priorities, (2,))
