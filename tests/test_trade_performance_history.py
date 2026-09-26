from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import asdict, replace
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from roster_theory.core.provenance import stable_hash
from roster_theory.providers.cache import atomic_write_json
from roster_theory.trade.performance import (
    CompletedPerformanceOutcome,
    PerformancePolicy,
    PregameExpectation,
)
from roster_theory.trade.performance_history import (
    import_completed_outcomes,
    update_performance_history,
)
from roster_theory.trade.target_workflow import (
    _write_feedback_template,
    run_target_workflow,
    target_workflow_report,
)
from tests.test_trade_target_optimizer import optimizer_config, permissive_options
from tests.test_trade_targets import config as target_config
from tests.test_trade_targets import fixture


def policy() -> PerformancePolicy:
    return PerformancePolicy(
        "fixture-provisional", 3, 3.0, 2, 0.3, 21.0,
        (("QB", 6.0), ("RB", 5.0), ("WR", 5.0), ("TE", 4.0)),
        (("QB", 8.0), ("RB", 12.0), ("WR", 12.0), ("TE", 7.0)),
    )


def history(snapshot, *, late_first: bool = False) -> dict:
    now = snapshot.captured_at
    scoring = stable_hash(snapshot.league.scoring)
    expectations = []
    outcomes = []
    for week, days in ((1, 6), (2, 3)):
        started = now - timedelta(days=days)
        expectations.append(PregameExpectation(
            snapshot.league_key, snapshot.league.season, "o_buy", week, "TE",
            started + timedelta(hours=1) if late_first and week == 1 else started - timedelta(hours=1),
            10.0, None, scoring, "fixture-pregame",
        ))
        outcomes.append(CompletedPerformanceOutcome(
            snapshot.league_key, snapshot.league.season, "o_buy", week, "TE",
            started, started + timedelta(hours=4), now - timedelta(days=days - 1),
            1.0, None, "PLAYED", scoring, "fixture-final",
        ))
    return {
        "schema_version": 1, "league_key": snapshot.league_key,
        "season": snapshot.league.season, "scoring_fingerprint": scoring,
        "pregame_expectations": [asdict(row) for row in expectations],
        "completed_outcomes": [asdict(row) for row in outcomes],
    }


class TradePerformanceHistoryTests(unittest.TestCase):
    def test_import_is_league_scoped_idempotent_and_checks_conflicts(self) -> None:
        snapshot, _, _, _, _ = fixture()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "history.json"
            incoming_path = root / "outcomes.json"
            value = history(snapshot)
            incoming = {key: value[key] for key in (
                "schema_version", "league_key", "season", "scoring_fingerprint",
                "completed_outcomes",
            )}
            value["completed_outcomes"] = []
            atomic_write_json(path, value)
            atomic_write_json(incoming_path, incoming)
            self.assertEqual(import_completed_outcomes(path, incoming_path), 2)
            self.assertEqual(import_completed_outcomes(path, incoming_path), 0)
            incoming["completed_outcomes"][0]["actual_points"] = 99.0
            atomic_write_json(incoming_path, incoming)
            with self.assertRaisesRegex(ValueError, "Conflicting"):
                import_completed_outcomes(path, incoming_path)
            incoming["league_key"] = "other"
            atomic_write_json(incoming_path, incoming)
            with self.assertRaisesRegex(ValueError, "league_key"):
                import_completed_outcomes(path, incoming_path)

    def test_prospective_capture_and_compatible_context(self) -> None:
        snapshot, projections, selected, _, _ = fixture()
        snapshot = replace(snapshot, manifest=replace(snapshot.manifest, current_week=3))
        refresh = SimpleNamespace(
            refresh=SimpleNamespace(snapshot=snapshot), selected_final=selected,
            weekly_projections=projections,
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "history.json"
            atomic_write_json(path, history(snapshot))
            result = update_performance_history(refresh, policy=policy(), path=path)
            self.assertEqual(result.status, "SUPPORTED")
            self.assertGreater(result.captured_expectations, 0)
            context = next(row for row in result.evidence.contexts if row.player_id == "o_buy")
            self.assertEqual(context.signal, "UNDERPERFORMING")
            self.assertEqual(context.sample_size, 2)
            self.assertTrue(context.compatible)
            self.assertEqual(update_performance_history(
                refresh, policy=policy(), path=path,
            ).captured_expectations, 0)

    def test_late_capture_is_excluded_not_backfilled(self) -> None:
        snapshot, projections, selected, _, _ = fixture()
        snapshot = replace(snapshot, manifest=replace(snapshot.manifest, current_week=3))
        refresh = SimpleNamespace(
            refresh=SimpleNamespace(snapshot=snapshot), selected_final=selected,
            weekly_projections=projections,
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "history.json"
            atomic_write_json(path, history(snapshot, late_first=True))
            result = update_performance_history(refresh, policy=policy(), path=path)
            self.assertEqual(result.status, "INSUFFICIENT_HISTORY")
            context = next(row for row in result.evidence.contexts if row.player_id == "o_buy")
            self.assertEqual(context.sample_size, 1)
            self.assertFalse(context.compatible)
            self.assertIn("W1:POSTGAME_OR_FUTURE_CAPTURE", context.exclusions)

    def test_normal_finder_receives_context_and_labels_policy(self) -> None:
        snapshot, projections, selected, market_ecr, market = fixture()
        snapshot = replace(snapshot, manifest=replace(snapshot.manifest, current_week=3))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            policy_path = root / "policy.json"
            policy_path.write_text(json.dumps({
                "league_key": "fixture", "version": "fixture-provisional-v1",
                "evidence_status": "PROVISIONAL_HEURISTIC",
                "basis": "Synthetic starting values, not calibrated",
                "target_discovery": asdict(target_config()),
                "target_optimizer": asdict(optimizer_config()),
                "performance_policy": asdict(policy()),
            }), encoding="utf-8")
            history_path = root / "history.json"
            atomic_write_json(history_path, history(snapshot))
            refresh = SimpleNamespace(
                refresh=SimpleNamespace(snapshot=snapshot), selected_final=selected,
                market=market_ecr, weekly_projections=projections,
                output_path=root / "boards.json",
            )
            with (
                patch('roster_theory.trade.evaluation_service.revalidate_snapshot', return_value={
                    'verified_at': snapshot.captured_at.isoformat(), 'status': 'UNCHANGED',
                }),
                patch("roster_theory.trade.target_workflow.resolve_league_policy_path", return_value=policy_path),
                patch("roster_theory.trade.target_workflow._options_from_policy", return_value=permissive_options()),
                patch("roster_theory.trade.target_workflow.refresh_value_boards", return_value=refresh),
                patch("roster_theory.trade.target_workflow.resolve_trade_market_evidence", return_value=market),
            ):
                result = run_target_workflow(
                    "fixture", search=False, target_policy_path=policy_path,
                    performance_history_path=history_path,
                    output_path=root / "targets.json",
                )
            buy_low = next(row for row in result.targets.targets if row.player_id == "o_buy")
            self.assertEqual(buy_low.performance_support, "SUPPORTS")
            self.assertEqual(result.policy_status, "PROVISIONAL_HEURISTIC")
            from roster_theory.trade.replay import replay_trade_manifest
            self.assertEqual(replay_trade_manifest(result.output_path.with_suffix('.manifest.json'))
                             ['result']['targets']['evidence_hash'], result.targets.evidence_hash)
            saved = target_workflow_report(result)
            self.assertEqual(saved["performance_history"]["status"], "SUPPORTED")
            self.assertEqual(saved["target_policy"]["evidence_status"], "PROVISIONAL_HEURISTIC")
            self.assertTrue(result.feedback_path.is_file())
            result.feedback_path.write_text("manager notes", encoding="utf-8")
            _write_feedback_template(result.feedback_path, result)
            self.assertEqual(result.feedback_path.read_text(encoding="utf-8"), "manager notes")


if __name__ == "__main__":
    unittest.main()
