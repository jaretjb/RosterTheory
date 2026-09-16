import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from roster_theory.core.provenance import stable_hash
from roster_theory.inseason.evaluation import InSeasonContext, build_weekly_projection_matrix
from roster_theory.waiver.emergence import (
    FantasyResultComponents,
    GameUsageObservation,
    UsageMeasure,
    build_emergence_evidence,
)
from roster_theory.waiver.emerging_value import (
    SCENARIO_STATES,
    build_emerging_scenario_input,
    calculate_break_even,
    evaluate_emerging_upside,
)
from roster_theory.waiver.evaluation import (
    WaiverEvaluationOptions,
    evaluate_waiver,
    load_waiver_evaluation,
    save_waiver_evaluation,
)
from roster_theory.waiver.policy import apply_waiver_policy, load_waiver_policy
from tests.test_waiver_evaluation import (
    NOW,
    legality,
    projections,
    values,
    waiver_snapshot,
    weeks,
)


SCORING = (
    ("rec", 0.5),
    ("rush_yd", 0.1),
    ("rush_td", 6.0),
    ("rec_yd", 0.1),
    ("rec_td", 6.0),
    ("fum_lost", -2.0),
)


def measure(value, denominator=None, *, share=False):
    return UsageMeasure(
        numerator=float(value),
        team_denominator=float(denominator) if denominator is not None else None,
        reported_share=(
            float(value) / float(denominator) if share and denominator else None
        ),
    )


def usage_row(
    player_id,
    name,
    team,
    position,
    week,
    *,
    carries,
    targets,
    snap_numerator,
    spike=False,
):
    total = carries + targets
    fantasy = (
        FantasyResultComponents(25.0, 4.0, 12.0, 6.0, 3.0, 2, 1)
        if spike
        else FantasyResultComponents(12.0, 9.0, 1.0, 0.0, 2.0)
    )
    return GameUsageObservation(
        player_id=player_id,
        player_name=name,
        team=team,
        position=position,
        season=2026,
        week=week,
        game_id=f"{player_id}-{week}",
        source="fictional normalized usage",
        captured_at=NOW,
        source_updated_at=NOW,
        identity_status="MATCHED",
        coverage_status="COMPLETE",
        game_status="PLAYED",
        overtime=False,
        offensive_snap_share=measure(snap_numerator, 60, share=True),
        route_participation=measure(
            25 if snap_numerator >= 33 else 8,
            35,
            share=True,
        ),
        target_share=measure(targets, 30, share=True),
        targets=measure(targets, 30),
        carries=measure(carries, 25),
        total_opportunities=measure(total, 55),
        goal_line_work=measure(max(0, carries / 8), 5),
        red_zone_work=measure(max(0, total / 5), 12),
        two_minute_usage=measure(max(0, targets / 2), 8),
        designed_touches=measure(total, 35),
        fantasy_result=fantasy,
        teammate_injury_context="NONE",
        role_durability="DURABLE",
        role_news="Fictional durable-role fixture",
    )


def trend_rows(
    player_id,
    name,
    team,
    position,
    *,
    baseline=(2, 1),
    recent=(14, 6),
):
    return (
        usage_row(
            player_id,
            name,
            team,
            position,
            1,
            carries=baseline[0],
            targets=baseline[1],
            snap_numerator=20,
        ),
        usage_row(
            player_id,
            name,
            team,
            position,
            2,
            carries=recent[0],
            targets=recent[1],
            snap_numerator=44,
        ),
        usage_row(
            player_id,
            name,
            team,
            position,
            3,
            carries=recent[0],
            targets=recent[1],
            snap_numerator=44,
        ),
    )


def emergence_bundle(*, add=True, drop=None, spike=False, league_key="league_alpha"):
    rows = []
    if add:
        if spike:
            rows.extend(
                (
                    usage_row("fa_rb", "Free Runner", "HHH", "RB", 1, carries=2, targets=1, snap_numerator=20),
                    usage_row("fa_rb", "Free Runner", "HHH", "RB", 2, carries=2, targets=1, snap_numerator=20),
                    usage_row("fa_rb", "Free Runner", "HHH", "RB", 3, carries=2, targets=1, snap_numerator=20, spike=True),
                )
            )
        else:
            rows.extend(trend_rows("fa_rb", "Free Runner", "HHH", "RB"))
    if drop == "bench":
        rows.extend(
            trend_rows(
                "bench",
                "Bench Receiver",
                "DDD",
                "WR",
                baseline=(1, 10),
                recent=(1, 16),
            )
        )
    elif drop == "rb_equal":
        rows.extend(trend_rows("rb", "Roster Runner", "BBB", "RB"))
    return build_emergence_evidence(
        league_key=league_key,
        observations=tuple(rows),
        captured_at=NOW,
    )


def scored_snapshot(*, open_slot=False, full_ppr=False):
    snapshot = waiver_snapshot(open_slot=open_slot)
    scoring = tuple(
        (key, 1.0 if key == "rec" and full_ppr else value)
        for key, value in SCORING
    )
    return replace(snapshot, league=replace(snapshot.league, scoring=scoring))


def evaluate_move(evidence, *, drop="Bench Receiver", snapshot=None):
    original_projections = projections()
    result = evaluate_waiver(
        snapshot or scored_snapshot(),
        add="Free Runner",
        drop=drop,
        weeks=weeks(),
        projections=original_projections,
        values=values(),
        drop_legality=legality(),
        news_fresh={"fa_rb": True},
        emergence_evidence=evidence,
        now=NOW,
    )
    return result, original_projections


class EmergingScenarioEvaluationTests(unittest.TestCase):
    def test_high_upside_cheap_drop_exposes_all_three_states(self):
        result, central = evaluate_move(emergence_bundle())
        value = result.candidates[0].emerging_upside
        self.assertEqual(value.status, "COMPLETE")
        self.assertEqual(
            tuple(row.state for row in value.scenario_comparisons),
            SCENARIO_STATES,
        )
        self.assertGreater(value.breakout_gain, 0)
        self.assertGreater(value.useful_role_gain, 0)
        self.assertEqual(value.break_even.status, "NO_MISS_DOWNSIDE")
        self.assertGreaterEqual(value.add_miss_protection, 0)
        self.assertEqual(central, projections())
        self.assertEqual(
            value.add_input.central_projection_hash,
            stable_hash(tuple(row for row in central if row.player_id == "fa_rb")),
        )
        self.assertTrue(value.named_teammate_contingency_kept_separate)

    def test_protected_drop_is_valued_symmetrically_and_no_action_can_win(self):
        result, _ = evaluate_move(emergence_bundle(drop="bench"))
        value = result.candidates[0].emerging_upside
        self.assertEqual(value.status, "COMPLETE")
        self.assertIsNotNone(value.drop_input)
        self.assertGreater(value.drop_central_projection_points, 0)
        self.assertGreater(value.retained_option_ceiling, value.acquisition_option_ceiling)
        self.assertLess(value.incremental_option_value, 0)
        self.assertTrue(value.no_action.best_in_every_scenario)

    def test_low_volume_box_score_spike_fails_closed(self):
        bundle = emergence_bundle(spike=True)
        self.assertEqual(bundle.players[0].classification, "EFFICIENCY_ONLY")
        result, _ = evaluate_move(bundle)
        value = result.candidates[0].emerging_upside
        self.assertEqual(value.status, "ADD_EVIDENCE_NOT_READY")
        self.assertEqual(value.scenario_comparisons, ())

    def test_useful_role_state_has_independent_roster_value(self):
        result, _ = evaluate_move(emergence_bundle())
        value = result.candidates[0].emerging_upside
        useful = next(
            row for row in value.scenario_comparisons if row.state == "USEFUL_ROLE"
        )
        self.assertGreater(useful.act_now.weighted_effect, 0)
        self.assertTrue(useful.act_now.starter_weeks)
        self.assertEqual(value.useful_role_gain, useful.act_now_minus_retain_drop)
        self.assertTrue(value.sensitivity)
        self.assertIn("probabilities sum to 1", value.expected_value_equation)

    def test_equal_rb_scenarios_produce_equal_option_ceilings(self):
        result, _ = evaluate_move(
            emergence_bundle(drop="rb_equal"),
            drop="Roster Runner",
        )
        value = result.candidates[0].emerging_upside
        self.assertEqual(value.acquisition_option_ceiling, value.retained_option_ceiling)
        self.assertEqual(value.incremental_option_value, 0.0)
        self.assertTrue(value.no_action.best_in_every_scenario)

    def test_no_drop_capacity_keeps_explicit_no_action_alternative(self):
        result, _ = evaluate_move(
            emergence_bundle(),
            drop=None,
            snapshot=scored_snapshot(open_slot=True),
        )
        value = result.candidates[0].emerging_upside
        self.assertIsNone(result.selected_drop_player_id)
        self.assertIsNone(value.no_action.retained_player_id)
        self.assertEqual(
            value.no_action.weighted_lineup_points,
            value.central_retain_drop_weighted_points,
        )

    def test_actual_sleeper_reception_scoring_changes_scenario_points(self):
        half, _ = evaluate_move(emergence_bundle(), snapshot=scored_snapshot())
        full, _ = evaluate_move(
            emergence_bundle(),
            snapshot=scored_snapshot(full_ppr=True),
        )
        half_projection = half.candidates[0].emerging_upside.scenario_comparisons[1].act_now.scenario_projections[0]
        full_projection = full.candidates[0].emerging_upside.scenario_comparisons[1].act_now.scenario_projections[0]
        receptions = dict(full_projection.raw_stats)["rec"]
        self.assertAlmostEqual(
            full_projection.league_points - half_projection.league_points,
            receptions * 0.5,
        )

    def test_repeated_valuation_and_hash_are_deterministic(self):
        first, _ = evaluate_move(emergence_bundle())
        second, _ = evaluate_move(emergence_bundle())
        first_value = first.candidates[0].emerging_upside
        second_value = second.candidates[0].emerging_upside
        self.assertEqual(first_value, second_value)
        self.assertEqual(first_value.valuation_hash, second_value.valuation_hash)

    def test_scenario_evidence_does_not_change_wa014_decision_policy(self):
        snapshot = scored_snapshot()
        common = {
            "add": "Free Runner",
            "drop": "Bench Receiver",
            "weeks": weeks(),
            "projections": projections(),
            "values": values(),
            "drop_legality": legality(),
            "news_fresh": {"fa_rb": True},
            "now": NOW,
        }
        policy = load_waiver_policy(
            Path(__file__).parent
            / "fixtures"
            / "waiver"
            / "league_alpha.decision-policy.json"
        )
        baseline = apply_waiver_policy(evaluate_waiver(snapshot, **common), policy)
        enhanced = apply_waiver_policy(
            evaluate_waiver(
                snapshot,
                emergence_evidence=emergence_bundle(),
                **common,
            ),
            policy,
        )
        self.assertEqual(enhanced.decision_label, baseline.decision_label)
        self.assertEqual(enhanced.selected_drop_player_id, baseline.selected_drop_player_id)

    def test_unsupported_league_scoring_fails_closed(self):
        snapshot = scored_snapshot()
        unsupported = replace(
            snapshot,
            league=replace(
                snapshot.league,
                scoring=(*snapshot.league.scoring, ("bonus_first_down", 0.5)),
            ),
        )
        result, _ = evaluate_move(emergence_bundle(), snapshot=unsupported)
        value = result.candidates[0].emerging_upside
        self.assertEqual(value.status, "SCORING_OR_ADD_INPUT_INCOMPLETE")
        self.assertIn("bonus_first_down", value.strongest_uncertainty)

    def test_hash_verified_offline_replay_preserves_scenario_values(self):
        result, _ = evaluate_move(emergence_bundle())
        expected = result.candidates[0].emerging_upside.valuation_hash
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "wa014-evaluation.json"
            save_waiver_evaluation(result, path)
            replay = load_waiver_evaluation(path)
            self.assertEqual(
                replay["candidates"][0]["emerging_upside"]["valuation_hash"],
                expected,
            )
            raw = json.loads(path.read_text(encoding="utf-8"))
            raw["candidates"][0]["emerging_upside"]["breakout_gain"] = -999
            path.write_text(json.dumps(raw), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "hash verification"):
                load_waiver_evaluation(path)


class BreakEvenAndSymmetryTests(unittest.TestCase):
    def test_break_even_handles_zero_negative_and_dominated_inputs(self):
        no_stakes = calculate_break_even(breakout_gain=0, miss_loss=0)
        self.assertIsNone(no_stakes.hit_rate)
        no_downside = calculate_break_even(breakout_gain=10, miss_loss=0)
        self.assertEqual(no_downside.hit_rate, 0.0)
        dominated = calculate_break_even(breakout_gain=-1, miss_loss=5)
        self.assertEqual(dominated.status, "DOMINATED")
        self.assertIsNone(dominated.hit_rate)
        self.assertIn("no breakout belief", dominated.explanation)
        negative_loss = calculate_break_even(breakout_gain=10, miss_loss=-2)
        self.assertEqual(negative_loss.hit_rate, 0.0)
        available = calculate_break_even(breakout_gain=9, miss_loss=3)
        self.assertEqual(available.hit_rate, 0.25)
        self.assertIn("breakout belief exceeds 25.0%", available.explanation)

    def test_break_even_threshold_rises_monotonically_with_miss_loss(self):
        rates = tuple(
            calculate_break_even(breakout_gain=10, miss_loss=loss).hit_rate
            for loss in (1, 2, 5, 10)
        )
        self.assertEqual(rates, tuple(sorted(rates)))

    def test_add_drop_swap_negates_every_state_delta(self):
        evidence = emergence_bundle(drop="rb_equal")
        snapshot = scored_snapshot()
        context = InSeasonContext(
            players=snapshot.players,
            roster_positions=snapshot.league.roster_positions,
            weeks=weeks(),
            unowned_player_ids=("fa_rb", "fa_wr"),
            evaluation_positions=("QB", "RB", "WR", "TE", "K", "DST"),
        )
        central = projections()
        matrix = build_weekly_projection_matrix(context, central)
        horizon = tuple(row.week for row in weeks())
        add_input = build_emerging_scenario_input(
            evidence,
            player_id="fa_rb",
            weeks=horizon,
            central_projections=central,
        )
        drop_input = build_emerging_scenario_input(
            evidence,
            player_id="rb",
            weeks=horizon,
            central_projections=central,
        )
        before = {"qb", "rb", "wr", "bench"}
        after = {"qb", "fa_rb", "wr", "bench"}
        options = WaiverEvaluationOptions()
        forward = evaluate_emerging_upside(
            context=context,
            central_matrix=matrix,
            central_projections=central,
            before_roster=before,
            after_roster=after,
            add_player_id="fa_rb",
            drop_player_id="rb",
            add_input=add_input,
            drop_input=drop_input,
            scoring=dict(snapshot.league.scoring),
            current_week=1,
            options=options,
        )
        reverse = evaluate_emerging_upside(
            context=context,
            central_matrix=matrix,
            central_projections=central,
            before_roster=after,
            after_roster=before,
            add_player_id="rb",
            drop_player_id="fa_rb",
            add_input=drop_input,
            drop_input=add_input,
            scoring=dict(snapshot.league.scoring),
            current_week=1,
            options=options,
        )
        for left, right in zip(forward.scenario_comparisons, reverse.scenario_comparisons):
            self.assertEqual(left.state, right.state)
            self.assertAlmostEqual(
                left.act_now_minus_retain_drop,
                -right.act_now_minus_retain_drop,
            )


if __name__ == "__main__":
    unittest.main()
