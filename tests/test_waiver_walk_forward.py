import json
import tempfile
import unittest
from dataclasses import asdict, replace
from datetime import timedelta
from pathlib import Path

from roster_theory.core.provenance import stable_hash
from roster_theory.waiver.walk_forward import (
    ImmutableEvidenceConflict,
    LookAheadLeakage,
    PlayerWeekOutcome,
    build_outcome_window,
    build_walk_forward_report,
    capture_decision_time_snapshot,
    default_walk_forward_policy_path,
    format_walk_forward_report,
    load_decision_time_snapshot,
    load_outcome_window,
    load_walk_forward_report,
    load_walk_forward_policy,
    save_decision_time_snapshot,
    save_outcome_window,
    save_walk_forward_report,
)
from tests.test_waiver_emerging_policy import NOW, decide


WAIVER_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "waiver"


def _rehash(value, field):
    return replace(value, **{field: stable_hash(asdict(replace(value, **{field: ""})))})


def decision_snapshot(index=0):
    evaluation = decide()
    evaluation = _rehash(replace(evaluation, current_week=3), "evidence_hash")
    policy = load_walk_forward_policy(
        default_walk_forward_policy_path(
            "league_alpha", config_dir=WAIVER_FIXTURE_DIR
        ),
        league_key="league_alpha",
    )
    snapshot = capture_decision_time_snapshot(evaluation, policy, captured_at=NOW)
    if index:
        snapshot = _rehash(replace(snapshot, decision_id=f"decision-{index}"), "snapshot_hash")
    return snapshot, policy


def observation(
    player_id,
    week,
    *,
    opportunities=20.0,
    points=15.0,
    replacement=7.0,
    started=False,
    available=None,
    reacquirable=None,
    identity="MATCHED",
    coverage="COMPLETE",
):
    observed_at = NOW + timedelta(days=week - 3)
    return PlayerWeekOutcome(
        player_id=player_id,
        week=week,
        captured_at=observed_at,
        source_updated_at=observed_at,
        source="controlled league-scored outcome",
        identity_status=identity,
        coverage_status=coverage,
        total_opportunities=opportunities,
        league_points=points,
        replacement_value=replacement,
        started=started,
        available_at_next_decision=available,
        reacquirable_at_next_decision=reacquirable,
    )


def outcome(snapshot, policy, window, *, hit=True, coverage="COMPLETE"):
    candidate = tuple(
        observation(
            snapshot.candidate_player_id,
            week,
            opportunities=20.0 if hit else 3.0,
            points=15.0 if hit else 4.0,
            started=week == 4,
            available=week == 4,
            coverage=coverage,
        )
        for week in range(4, 4 + window)
    )
    drop = tuple(
        observation(
            snapshot.drop_player_id,
            week,
            opportunities=10.0,
            points=8.0 if hit else 12.0,
            reacquirable=week == 4,
            coverage=coverage,
        )
        for week in range(4, 4 + window)
    )
    return build_outcome_window(
        snapshot,
        policy,
        window_weeks=window,
        as_of_week=7,
        captured_at=NOW + timedelta(days=10),
        candidate_observations=candidate,
        drop_observations=drop,
    )


class DecisionTimeCaptureTests(unittest.TestCase):
    def test_capture_freezes_every_decision_time_evidence_channel(self):
        snapshot, policy = decision_snapshot()
        self.assertEqual(snapshot.outcome_windows, (1, 2, 4))
        self.assertEqual(
            snapshot.policy_version,
            "test-league-alpha-emerging-upside-v1",
        )
        self.assertEqual(snapshot.decision_path, "EMERGING_UPSIDE")
        self.assertTrue(snapshot.ww_evidence_hash)
        self.assertTrue(snapshot.ww_selected_expert_ranks)
        self.assertTrue(snapshot.role_evidence_hash)
        self.assertTrue(snapshot.role_metrics)
        self.assertEqual({row.state for row in snapshot.scenarios}, {"MISS", "USEFUL_ROLE", "BREAKOUT"})
        self.assertEqual(snapshot.break_even_status, "NO_MISS_DOWNSIDE")
        self.assertEqual(snapshot.break_even_hit_rate, 0.0)
        self.assertTrue(snapshot.sensitivity)
        self.assertTrue(snapshot.roster_state_hash)
        self.assertTrue(snapshot.availability_hash)
        self.assertTrue(snapshot.projection_value_hash)
        self.assertIn(snapshot.evaluation_evidence_hash, snapshot.source_evaluation_json)
        self.assertEqual(policy.league_key, snapshot.league_key)
        self.assertFalse(snapshot.sleeper_write_performed)

    def test_future_decision_observation_is_rejected(self):
        evaluation = decide()
        role = evaluation.emergence_evidence
        player = role.players[0]
        future_observation = replace(player.observations[-1], week=4)
        player = replace(
            player,
            observations=(*player.observations[:-1], future_observation),
        )
        role = _rehash(replace(role, players=(player,)), "evidence_hash")
        evaluation = _rehash(
            replace(evaluation, current_week=3, emergence_evidence=role),
            "evidence_hash",
        )
        policy = load_walk_forward_policy(
            default_walk_forward_policy_path(
                "league_alpha", config_dir=WAIVER_FIXTURE_DIR
            ),
            league_key="league_alpha",
        )
        with self.assertRaises(LookAheadLeakage):
            capture_decision_time_snapshot(evaluation, policy, captured_at=NOW)

    def test_immutable_save_is_idempotent_and_refuses_mutation(self):
        snapshot, _ = decision_snapshot()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "decision.json"
            save_decision_time_snapshot(snapshot, path)
            original = path.read_bytes()
            save_decision_time_snapshot(snapshot, path)
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(load_decision_time_snapshot(path), snapshot)
            changed = _rehash(
                replace(snapshot, warnings=(*snapshot.warnings, "changed")),
                "snapshot_hash",
            )
            with self.assertRaises(ImmutableEvidenceConflict):
                save_decision_time_snapshot(changed, path)
            self.assertEqual(path.read_bytes(), original)

    def test_league_local_policies_are_independent(self):
        league_alpha = load_walk_forward_policy(
            default_walk_forward_policy_path(
                "league_alpha", config_dir=WAIVER_FIXTURE_DIR
            ),
            league_key="league_alpha",
        )
        league_beta = load_walk_forward_policy(
            default_walk_forward_policy_path(
                "league_beta", config_dir=WAIVER_FIXTURE_DIR
            ),
            league_key="league_beta",
        )
        self.assertNotEqual(league_alpha.policy_hash, league_beta.policy_hash)
        self.assertNotEqual(
            league_alpha.minimum_complete_samples,
            league_beta.minimum_complete_samples,
        )
        with self.assertRaises(ValueError):
            load_walk_forward_policy(
                default_walk_forward_policy_path(
                    "league_beta", config_dir=WAIVER_FIXTURE_DIR
                ),
                league_key="league_alpha",
            )


class OutcomeCaptureTests(unittest.TestCase):
    def test_complete_window_records_availability_starts_points_and_regret(self):
        snapshot, policy = decision_snapshot()
        result = outcome(snapshot, policy, 2, hit=True)
        self.assertEqual(result.coverage_status, "COMPLETE")
        self.assertTrue(result.role_persisted)
        self.assertEqual(result.realized_state, "BREAKOUT")
        self.assertTrue(result.candidate_remained_available)
        self.assertTrue(result.drop_reacquirable)
        self.assertEqual(result.candidate_start_weeks, (4,))
        self.assertEqual(result.candidate_league_points, 30.0)
        self.assertEqual(result.drop_league_points, 16.0)
        self.assertEqual(result.replacement_value, 14.0)
        self.assertGreater(result.realized_act_now_minus_retain_drop, 0)
        self.assertEqual(result.act_now_regret, 0.0)
        self.assertGreater(result.retain_drop_regret, 0)
        self.assertFalse(result.sleeper_write_performed)

    def test_future_outcome_week_exposes_lookahead_leakage(self):
        snapshot, policy = decision_snapshot()
        with self.assertRaises(LookAheadLeakage):
            build_outcome_window(
                snapshot,
                policy,
                window_weeks=1,
                as_of_week=4,
                captured_at=NOW + timedelta(days=10),
                candidate_observations=(observation("fa_rb", 5),),
                drop_observations=(observation("bench", 4),),
            )

    def test_touchdown_points_do_not_override_weak_opportunity_process(self):
        snapshot, policy = decision_snapshot()
        result = build_outcome_window(
            snapshot,
            policy,
            window_weeks=1,
            as_of_week=4,
            captured_at=NOW + timedelta(days=10),
            candidate_observations=(
                observation("fa_rb", 4, opportunities=3.0, points=30.0),
            ),
            drop_observations=(observation("bench", 4, points=8.0),),
        )
        self.assertFalse(result.role_persisted)
        self.assertEqual(result.realized_state, "MISS")
        self.assertGreater(result.candidate_league_points, result.drop_league_points)

    def test_partial_unavailable_unmatched_and_censored_are_explicit(self):
        snapshot, policy = decision_snapshot()
        results = {}
        for status in ("PARTIAL", "UNAVAILABLE"):
            results[status] = build_outcome_window(
                snapshot,
                policy,
                window_weeks=1,
                as_of_week=4,
                captured_at=NOW + timedelta(days=10),
                candidate_observations=(observation("fa_rb", 4, coverage=status),),
                drop_observations=(observation("bench", 4),),
            )
        results["UNMATCHED"] = build_outcome_window(
            snapshot,
            policy,
            window_weeks=1,
            as_of_week=4,
            captured_at=NOW + timedelta(days=10),
            candidate_observations=(observation("fa_rb", 4, identity="UNMATCHED"),),
            drop_observations=(observation("bench", 4),),
        )
        results["CENSORED"] = build_outcome_window(
            snapshot,
            policy,
            window_weeks=1,
            as_of_week=4,
            captured_at=NOW + timedelta(days=10),
            candidate_observations=(),
            drop_observations=(),
        )
        self.assertEqual(set(results), {row.coverage_status for row in results.values()})
        self.assertTrue(all(row.role_persisted is None for row in results.values()))
        self.assertTrue(all(row.realized_state == "UNKNOWN" for row in results.values()))

    def test_outcome_replay_is_hash_verified_and_immutable(self):
        snapshot, policy = decision_snapshot()
        result = outcome(snapshot, policy, 1)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "outcome.json"
            save_outcome_window(result, path)
            self.assertEqual(load_outcome_window(path), result)
            raw = json.loads(path.read_text(encoding="utf-8"))
            raw["realized_state"] = "MISS"
            path.write_text(json.dumps(raw), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_outcome_window(path)


class WalkForwardReportTests(unittest.TestCase):
    def synthetic_report(self):
        base, policy = decision_snapshot()
        snapshots = []
        outcomes = []
        for index in range(10):
            snapshot = _rehash(
                replace(base, decision_id=f"synthetic-{index}"),
                "snapshot_hash",
            )
            snapshots.append(snapshot)
            for window in policy.outcome_windows:
                outcomes.append(outcome(snapshot, policy, window, hit=index < 6))
        return snapshots, outcomes, policy

    def test_synthetic_walk_forward_recovers_known_hit_rate_for_all_baselines(self):
        snapshots, outcomes, policy = self.synthetic_report()
        report = build_walk_forward_report(
            snapshots,
            outcomes,
            policy,
            generated_at=NOW + timedelta(days=20),
        )
        self.assertTrue(all(row.role_hit_rate == 0.6 for row in report.windows))
        self.assertTrue(all(row.hit_rate == 0.6 for row in report.baselines))
        self.assertTrue(all(row.calibration_error is None for row in report.baselines))
        self.assertEqual(report.state_probability_evidence.status, "GATED_OFF")
        self.assertEqual(report.state_probability_evidence.probabilities, ())
        self.assertEqual(len(report.break_even_evidence), 10)
        self.assertTrue(all(row.sensitivity for row in report.break_even_evidence))
        self.assertFalse(report.policy_promotion_performed)
        self.assertFalse(report.sleeper_write_performed)
        self.assertEqual(
            report.retained_waiver_policy_versions,
            ("test-league-alpha-emerging-upside-v1",),
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.json"
            save_walk_forward_report(report, path)
            replay = load_walk_forward_report(path)
            self.assertTrue(replay["offline_replay"])
            self.assertFalse(replay["policy_promotion_performed"])
            raw = json.loads(path.read_text(encoding="utf-8"))
            raw["decision_count"] = 999
            path.write_text(json.dumps(raw), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_walk_forward_report(path)

    def test_report_keeps_all_coverage_exceptions(self):
        base, policy = decision_snapshot()
        snapshots = []
        outcomes = []
        statuses = ("PARTIAL", "UNAVAILABLE", "UNMATCHED", "CENSORED")
        for index, status in enumerate(statuses):
            snapshot = _rehash(
                replace(base, decision_id=f"coverage-{index}"),
                "snapshot_hash",
            )
            snapshots.append(snapshot)
            candidate = () if status == "CENSORED" else (
                observation(
                    "fa_rb",
                    4,
                    coverage=status if status in {"PARTIAL", "UNAVAILABLE"} else "COMPLETE",
                    identity="UNMATCHED" if status == "UNMATCHED" else "MATCHED",
                ),
            )
            drop = () if status == "CENSORED" else (observation("bench", 4),)
            outcomes.append(
                build_outcome_window(
                    snapshot,
                    policy,
                    window_weeks=1,
                    as_of_week=4,
                    captured_at=NOW + timedelta(days=10),
                    candidate_observations=candidate,
                    drop_observations=drop,
                )
            )
        report = build_walk_forward_report(
            snapshots,
            outcomes,
            policy,
            generated_at=NOW + timedelta(days=20),
        )
        self.assertEqual(report.coverage.total, 12)
        self.assertEqual(report.coverage.complete, 0)
        self.assertEqual(report.coverage.partial, 1)
        self.assertEqual(report.coverage.unavailable, 1)
        self.assertEqual(report.coverage.unmatched, 1)
        self.assertEqual(report.coverage.censored, 9)
        self.assertEqual(report.coverage.missing_outcome_windows, 8)
        rendered = format_walk_forward_report(report)
        self.assertIn("partial 1; censored 9; unavailable 1; unmatched 1; missing windows 8", rendered)
        self.assertIn("State probabilities: GATED_OFF", rendered)
        self.assertIn("Policy promotion: none", rendered)
        self.assertIn("break-even evidence retained", rendered)

    def test_missing_decision_signal_is_not_scored_as_a_negative_call(self):
        snapshot, policy = decision_snapshot()
        snapshot = _rehash(replace(snapshot, ww_complete=False), "snapshot_hash")
        outcomes = tuple(outcome(snapshot, policy, window) for window in policy.outcome_windows)
        report = build_walk_forward_report(
            (snapshot,),
            outcomes,
            policy,
            generated_at=NOW + timedelta(days=20),
        )
        ww_rows = tuple(row for row in report.baselines if row.baseline == "WW_ONLY")
        combined_rows = tuple(
            row for row in report.baselines if row.baseline == "ROLE_PLUS_WW"
        )
        self.assertTrue(all(row.eligible_samples == 0 for row in ww_rows + combined_rows))
        self.assertTrue(
            all(row.unavailable_signal_samples == 1 for row in ww_rows + combined_rows)
        )

    def test_missing_role_outcome_is_not_scored_as_a_miss(self):
        snapshot, policy = decision_snapshot()
        snapshot = _rehash(replace(snapshot, role_metrics=()), "snapshot_hash")
        outcomes = tuple(outcome(snapshot, policy, window) for window in policy.outcome_windows)
        report = build_walk_forward_report(
            (snapshot,),
            outcomes,
            policy,
            generated_at=NOW + timedelta(days=20),
        )
        self.assertTrue(all(row.complete_samples == 1 for row in report.windows))
        self.assertTrue(all(row.role_evaluable_samples == 0 for row in report.windows))
        self.assertTrue(all(row.role_hit_rate is None for row in report.windows))
        self.assertTrue(any("lack evaluable" in warning for warning in report.warnings))

    def test_report_rejects_outcomes_not_yet_available_at_generation_time(self):
        snapshot, policy = decision_snapshot()
        result = outcome(snapshot, policy, 1)
        with self.assertRaises(LookAheadLeakage):
            build_walk_forward_report(
                (snapshot,),
                (result,),
                policy,
                generated_at=NOW + timedelta(days=5),
            )

    def test_probability_estimate_requires_and_can_clear_all_shadow_gates(self):
        base, policy = decision_snapshot()
        snapshots = []
        outcomes = []
        for index in range(20):
            snapshot = _rehash(
                replace(base, decision_id=f"gated-estimate-{index}"),
                "snapshot_hash",
            )
            snapshots.append(snapshot)
            for window in policy.outcome_windows:
                outcomes.append(outcome(snapshot, policy, window, hit=index < 12))
        report = build_walk_forward_report(
            snapshots,
            outcomes,
            policy,
            generated_at=NOW + timedelta(days=20),
        )
        self.assertEqual(
            report.state_probability_evidence.status,
            "EMPIRICAL_ESTIMATE",
        )
        self.assertEqual(
            dict(report.state_probability_evidence.probabilities),
            {"MISS": 0.4, "USEFUL_ROLE": 0.0, "BREAKOUT": 0.6},
        )
        self.assertTrue(report.state_probability_evidence.stable)
        self.assertFalse(report.policy_promotion_performed)

    def test_large_sample_with_unstable_windows_still_emits_no_probability(self):
        base, policy = decision_snapshot()
        snapshots = []
        outcomes = []
        hit_counts = {1: 20, 2: 10, 4: 0}
        for index in range(20):
            snapshot = _rehash(
                replace(base, decision_id=f"unstable-{index}"),
                "snapshot_hash",
            )
            snapshots.append(snapshot)
            for window in policy.outcome_windows:
                outcomes.append(
                    outcome(snapshot, policy, window, hit=index < hit_counts[window])
                )
        report = build_walk_forward_report(
            snapshots,
            outcomes,
            policy,
            generated_at=NOW + timedelta(days=20),
        )
        self.assertEqual(report.state_probability_evidence.status, "GATED_OFF")
        self.assertFalse(report.state_probability_evidence.stable)
        self.assertIn("stability", report.state_probability_evidence.reason)
        self.assertEqual(report.state_probability_evidence.probabilities, ())
        self.assertFalse(report.policy_promotion_performed)

    def test_cross_league_report_use_fails_closed(self):
        snapshots, outcomes, _ = self.synthetic_report()
        league_beta = load_walk_forward_policy(
            default_walk_forward_policy_path(
                "league_beta", config_dir=WAIVER_FIXTURE_DIR
            ),
            league_key="league_beta",
        )
        with self.assertRaises(ValueError):
            build_walk_forward_report(
                snapshots,
                outcomes,
                league_beta,
                generated_at=NOW + timedelta(days=20),
            )


if __name__ == "__main__":
    unittest.main()
