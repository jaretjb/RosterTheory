import json
import tempfile
import unittest
from pathlib import Path

from roster_theory.mock_evidence import (
    MockEvidenceRecorder,
    _row_matches_pick,
    audit_mock_evidence,
    build_mock_evidence_audit,
    evidence_paths,
    load_mock_evidence,
)


class MockEvidenceTests(unittest.TestCase):
    @staticmethod
    def pick(number: int, slot: int, player_id: str, name: str, position: str) -> dict:
        first, last = name.split(" ", 1)
        return {
            "pick_no": number,
            "draft_slot": slot,
            "roster_id": slot,
            "player_id": player_id,
            "metadata": {
                "first_name": first,
                "last_name": last,
                "position": position,
            },
        }

    @staticmethod
    def snapshot() -> dict:
        return {
            "schema_version": 1,
            "captured_at": 100,
            "season": 2026,
            "scoring": "half_ppr",
            "adp_field": "adp_half_ppr",
            "players": [
                {
                    "player_id": str(index),
                    "player_name": name,
                    "position": position,
                    "sleeper_adp": adp,
                }
                for index, name, position, adp in (
                    ("1", "Alpha Runner", "RB", 2.0),
                    ("2", "Bravo Receiver", "WR", 1.0),
                    ("3", "Charlie Runner", "RB", 3.0),
                    ("4", "Delta Quarterback", "QB", 4.0),
                    ("5", "Echo Tightend", "TE", 5.0),
                )
            ],
        }

    def initial_report(self) -> dict:
        recommendations = [
            {
                "player_key": "1",
                "player_name": "Alpha Runner",
                "position": "RB",
                "next_pick": 4,
                "market_survival": 0.7,
                "league_survival": 0.8,
                "baseline_league_survival": 0.75,
            },
            {
                "player_key": "5",
                "player_name": "Echo Tightend",
                "position": "TE",
                "next_pick": 4,
                "market_survival": 0.5,
                "league_survival": 0.6,
                "baseline_league_survival": 0.55,
            },
            {
                "player_key": "2",
                "player_name": "Bravo Receiver",
                "position": "WR",
                "next_pick": 4,
                "market_survival": 0.4,
                "league_survival": 0.3,
                "baseline_league_survival": 0.35,
            },
        ]
        return {
            "draft_id": "draft",
            "status": "drafting",
            "teams": 2,
            "rounds": 2,
            "draft_slot": 1,
            "scoring": "half_ppr",
            "current_pick": 1,
            "is_user_turn": True,
            "transition": "initial",
            "removed_pick_numbers": [],
            "edited_pick_numbers": [],
            "rosters": {1: [], 2: []},
            "recommendation": {
                "policies": ["primary"],
                "recommendations": {"primary": recommendations},
                "model_split": True,
                "model_split_policies": ["primary"],
                "room_timing_split": True,
                "room_timing_split_policies": ["primary"],
                "market_leaders": {"primary": "Bravo Receiver"},
                "league_leaders": {"primary": "Alpha Runner"},
                "baseline_league_leaders": {"primary": "Echo Tightend"},
            },
            "recommendation_cached": False,
            "draft_picks_fetch": {
                "cache_busted": True,
                "cache_status": "MISS",
                "cache_age_seconds": None,
                "status_counts": {"MISS": 1},
                "max_cache_age_seconds": 0.0,
            },
            "poll_latency_ms": 12,
            "recommendation_latency_ms": 5,
            "missed_turn": False,
            "stale": False,
            "clock_risk": False,
            "warnings": [],
        }

    def final_report(self) -> dict:
        bravo = self.pick(1, 1, "2", "Bravo Receiver", "WR")
        alpha = self.pick(2, 2, "1", "Alpha Runner", "RB")
        charlie = self.pick(3, 2, "3", "Charlie Runner", "RB")
        delta = self.pick(4, 1, "4", "Delta Quarterback", "QB")
        return {
            "draft_id": "draft",
            "status": "complete",
            "teams": 2,
            "rounds": 2,
            "draft_slot": 1,
            "scoring": "half_ppr",
            "current_pick": None,
            "is_user_turn": False,
            "transition": "append",
            "removed_pick_numbers": [],
            "edited_pick_numbers": [],
            "rosters": {1: [bravo, delta], 2: [alpha, charlie]},
            "recommendation": None,
            "recommendation_cached": False,
            "draft_picks_fetch": {
                "cache_busted": True,
                "cache_status": "MISS",
                "cache_age_seconds": None,
                "status_counts": {"MISS": 2},
                "max_cache_age_seconds": 0.0,
            },
            "poll_latency_ms": 8,
            "recommendation_latency_ms": 0,
            "missed_turn": False,
            "stale": False,
            "clock_risk": False,
            "warnings": [],
        }

    def test_recorder_is_append_only_and_builds_a_complete_audit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            snapshot_path = root / "sleeper.json"
            snapshot_path.write_text(json.dumps(self.snapshot()), encoding="utf-8")
            log_path = root / "mock.ndjson"
            summary_path = root / "mock.summary.json"
            recorder = MockEvidenceRecorder.create(
                log_path,
                summary_path,
                snapshot_path,
                {"draft_id": "draft", "board_path": "board.csv"},
                started_at=200,
            )

            self.assertTrue(recorder.record(self.initial_report(), recorded_at=201))
            duplicate = dict(self.initial_report())
            duplicate["transition"] = "duplicate"
            duplicate["recommendation_cached"] = True
            self.assertFalse(recorder.record(duplicate, recorded_at=202))
            self.assertTrue(recorder.record(self.final_report(), recorded_at=203))
            audit = recorder.finalize("draft_complete")

            self.assertTrue(summary_path.exists())
            session, reports, termination = load_mock_evidence(log_path)
            self.assertEqual(session["sleeper_adp_snapshot"]["captured_at"], 100)
            self.assertEqual(len(reports), 2)
            self.assertEqual(termination, "draft_complete")
            self.assertTrue(audit["reconciliation"]["complete_board"])
            self.assertEqual(audit["reconciliation"]["missed_turn_reports"], 0)
            self.assertTrue(audit["draft_picks_cache"]["cache_busting_active"])
            self.assertEqual(audit["draft_picks_cache"]["logged_hit_reports"], 0)
            self.assertEqual(
                audit["draft_picks_cache"]["status_counts"], {"MISS": 2}
            )
            self.assertEqual(audit["timing_splits"]["model_split_turns"], 1)
            self.assertEqual(audit["timing_splits"]["room_timing_split_turns"], 1)
            self.assertEqual(
                audit["survival_calibration"]["league_room_aware"]["observations"],
                2,
            )
            self.assertEqual(
                audit["survival_calibration"]["censored_by_user_selection"], 1
            )
            self.assertEqual(
                audit["survival_calibration"]["league_room_aware"]["observed_survival"],
                0.5,
            )
            self.assertEqual(
                audit["survival_calibration"]["status"],
                "observed_horizons_only",
            )
            self.assertEqual(audit["recommendations"]["followed_primary_count"], 0)
            self.assertEqual(
                audit["roster_construction"]["position_counts"], {"QB": 1, "WR": 1}
            )
            self.assertEqual(
                audit["sleeper_adp_adherence"]["opponents_only"]["matched_picks"],
                2,
            )

    def test_completion_status_is_preserved_when_picks_do_not_change(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            snapshot_path = root / "sleeper.json"
            snapshot_path.write_text(json.dumps(self.snapshot()), encoding="utf-8")
            recorder = MockEvidenceRecorder.create(
                root / "mock.ndjson",
                root / "mock.summary.json",
                snapshot_path,
                {"draft_id": "draft", "board_path": "board.csv"},
            )
            drafting = self.final_report()
            drafting["status"] = "drafting"
            self.assertTrue(recorder.record(drafting))
            complete = dict(drafting)
            complete["status"] = "complete"
            complete["transition"] = "duplicate"
            self.assertTrue(recorder.record(complete))
            audit = recorder.finalize("draft_complete")

            self.assertTrue(audit["reconciliation"]["complete_board"])
            self.assertEqual(audit["reconciliation"]["final_status"], "complete")
            self.assertFalse(
                audit["reconciliation"]["status_inferred_from_termination"]
            )

    def test_audit_keeps_decision_worthy_counterfactual_offline(self) -> None:
        initial = self.initial_report()
        initial["recommendation"]["decision_signal"] = {
            "kind": "wait_on_qb",
            "player_name": "Alpha Runner",
            "qb_name": "Delta Quarterback",
            "qb_survival": 0.77,
            "turn_package_gap": 0.38,
            "continuation_pick": 4,
        }
        initial["recommendation"]["turn_horizon"] = {
            "planned_turn": {
                "first_pick": 1,
                "first_player_name": "Alpha Runner",
                "second_pick": 4,
                "second_player_name": "Echo Tightend",
            }
        }

        audit = build_mock_evidence_audit(
            {"draft_id": "draft", "sleeper_adp_snapshot": self.snapshot()},
            [initial, self.final_report()],
            "draft_complete",
        )

        rows = audit["recommendations"]["decision_counterfactuals"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["kind"], "wait_on_qb")
        self.assertEqual(rows[0]["planned_turn"]["second_player_name"], "Echo Tightend")

    def test_old_transcript_can_infer_completion_from_terminal_condition(self) -> None:
        drafting = self.final_report()
        drafting["status"] = "drafting"
        audit = build_mock_evidence_audit(
            {"draft_id": "draft", "sleeper_adp_snapshot": self.snapshot()},
            [drafting],
            "draft_complete",
        )

        self.assertTrue(audit["reconciliation"]["complete_board"])
        self.assertEqual(audit["reconciliation"]["reported_final_status"], "drafting")
        self.assertTrue(
            audit["reconciliation"]["status_inferred_from_termination"]
        )

    def test_partial_draft_does_not_score_unobservable_survival(self) -> None:
        initial = self.initial_report()
        user_pick = self.pick(1, 1, "2", "Bravo Receiver", "WR")
        partial = {
            **self.final_report(),
            "status": "paused",
            "transition": "append",
            "rosters": {1: [user_pick], 2: []},
        }
        audit = build_mock_evidence_audit(
            {
                "draft_id": "draft",
                "started_at": 100,
                "sleeper_adp_snapshot": self.snapshot(),
            },
            [initial, partial],
            "user_interrupted",
        )

        self.assertFalse(audit["reconciliation"]["complete_board"])
        self.assertEqual(
            audit["survival_calibration"]["not_yet_observable"], 2
        )
        self.assertEqual(
            audit["survival_calibration"]["censored_by_user_selection"], 1
        )
        self.assertEqual(
            audit["survival_calibration"]["league_room_aware"]["observations"],
            0,
        )

    def test_authoritative_rewrite_requires_survival_review(self) -> None:
        initial = self.initial_report()
        rewritten = {
            **self.final_report(),
            "transition": "rewrite",
            "edited_pick_numbers": [1],
        }
        audit = build_mock_evidence_audit(
            {
                "draft_id": "draft",
                "started_at": 100,
                "sleeper_adp_snapshot": self.snapshot(),
            },
            [initial, rewritten],
            "draft_complete",
        )

        self.assertTrue(audit["reconciliation"]["authoritative_rewrite"])
        self.assertEqual(
            audit["survival_calibration"]["status"],
            "review_required_after_authoritative_rewrite",
        )

    def test_specialist_recommendation_can_match_by_normalized_name(self) -> None:
        pick = self.pick(1, 1, "999", "Pittsburgh Steelers", "DEF")
        self.assertTrue(
            _row_matches_pick(
                {"player_name": "Pittsburgh Steelers", "position": "DST"},
                pick,
            )
        )

    def test_reaudit_and_unique_paths_are_reproducible(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first_log, first_summary = evidence_paths(root, "draft", started_at=100)
            first_log.write_text("", encoding="utf-8")
            second_log, second_summary = evidence_paths(root, "draft", started_at=100)

            self.assertNotEqual(first_log, second_log)
            self.assertNotEqual(first_summary, second_summary)

            snapshot_path = root / "sleeper.json"
            snapshot_path.write_text(json.dumps(self.snapshot()), encoding="utf-8")
            recorder = MockEvidenceRecorder.create(
                second_log,
                second_summary,
                snapshot_path,
                {"draft_id": "draft"},
                started_at=100,
            )
            recorder.record(self.initial_report())
            recorder.record(self.final_report())
            recorder.finalize("draft_complete")

            rebuilt = audit_mock_evidence(second_log)
            self.assertEqual(rebuilt["termination"], "draft_complete")
            self.assertEqual(rebuilt["reconciliation"]["final_pick_count"], 4)


if __name__ == "__main__":
    unittest.main()
