from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from roster_theory.cli import build_parser
from roster_theory.trade.market import ecr_proxy
from roster_theory.trade.target_workflow import (
    format_target_workflow,
    load_target_workflow_evidence,
    run_target_workflow,
    target_workflow_report,
)
from tests.test_trade_consolidation import consolidation_fixture
from tests.test_trade_target_optimizer import optimizer_config, permissive_options
from tests.test_trade_targets import config as target_config


class TargetWorkflowTests(unittest.TestCase):
    def test_targets_and_search_share_cards_and_replay_with_separate_axes(self) -> None:
        snapshot, projections, selected, market_ecr, market = consolidation_fixture()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            policy_path = root / "target-policy.json"
            policy_path.write_text(json.dumps({
                "league_key": "fixture",
                "version": "fixture-target-v1",
                "target_discovery": asdict(target_config()),
                "target_optimizer": asdict(optimizer_config()),
            }), encoding="utf-8")
            refresh = SimpleNamespace(
                refresh=SimpleNamespace(snapshot=snapshot),
                selected_final=selected,
                market=market_ecr,
                weekly_projections=projections,
                output_path=root / "boards.json",
            )
            with (
                patch("roster_theory.trade.target_workflow.resolve_league_policy_path", return_value=policy_path),
                patch("roster_theory.trade.target_workflow._options_from_policy", return_value=permissive_options()),
                patch("roster_theory.trade.target_workflow.refresh_value_boards", return_value=refresh) as board_refresh,
                patch("roster_theory.trade.target_workflow.resolve_trade_market_evidence", side_effect=(market, market, ecr_proxy("chart unavailable"))) as market_resolve,
            ):
                targets = run_target_workflow(
                    "fixture", search=False, target_policy_path=policy_path,
                    output_path=root / "targets.json", proxy_only=True,
                )
                search = run_target_workflow(
                    "fixture", search=True, target_policy_path=policy_path,
                    output_path=root / "search.json", csv_path=root / "search.csv",
                    proxy_only=True,
                )
                proxy = run_target_workflow(
                    "fixture", search=True, target_policy_path=policy_path,
                    output_path=root / "proxy.json", proxy_only=True,
                )
            self.assertEqual(board_refresh.call_count, 3)
            self.assertEqual(market_resolve.call_count, 3)
            self.assertTrue(all(call.kwargs["source"] is None for call in market_resolve.call_args_list))
            self.assertEqual(proxy.targets.pricing_mode, "ECR-PROXY")
            self.assertIn("chart price/change unavailable", format_target_workflow(proxy))
            self.assertTrue(all(
                row.market_fairness.consolidation_premium_value is None
                for row in proxy.packages.evaluated_decisions
            ))
            self.assertEqual(targets.targets.evidence_hash, search.targets.evidence_hash)
            self.assertEqual(search.packages.target_evidence_hash, targets.targets.evidence_hash)
            self.assertIsNone(targets.packages)
            self.assertTrue(search.packages.evaluated_decisions)
            self.assertIn("WATCH", format_target_workflow(targets))
            formatted = format_target_workflow(search)
            self.assertLess(
                formatted.index(search.targets.targets[0].player_name),
                formatted.index("OFFERS"),
            )
            self.assertIn("WIN / FAIR", formatted)
            self.assertIn("Policy: UNVALIDATED", formatted)
            self.assertIn("partner lineup", formatted)
            self.assertIn("Premium sensitivity", formatted)
            self.assertEqual(target_workflow_report(search)["evidence_hash"], search.evidence_hash)
            self.assertNotIn("replay_mode", target_workflow_report(search))
            self.assertEqual(
                load_target_workflow_evidence(search.output_path)["replay_mode"],
                "OFFLINE/NON-CURRENT",
            )
            csv_text = search.csv_path.read_text(encoding="utf-8-sig")
            self.assertIn("TARGET", csv_text)
            self.assertIn("OFFER", csv_text)
            self.assertIn("premium_sensitivity", csv_text)
            self.assertTrue(search.feedback_path.is_file())
            saved = json.loads(search.output_path.read_text(encoding="utf-8"))
            saved["pricing_mode"] = "tampered"
            search.output_path.write_text(json.dumps(saved), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "hash"):
                load_target_workflow_evidence(search.output_path)

    def test_cli_targets_search_and_offline_replay(self) -> None:
        parser = build_parser()
        targets_args = parser.parse_args(["trade", "targets", "fixture", "--json"])
        search_args = parser.parse_args(["trade", "search", "fixture", "--json"])
        replay_args = parser.parse_args([
            "trade", "targets", "fixture", "--snapshot", "saved.json", "--json"
        ])
        result = SimpleNamespace(output_path=Path("saved.json"), csv_path=None)
        with (
            patch("roster_theory.cli._prepare_trade_analysis") as prepare,
            patch("roster_theory.cli.run_target_workflow", return_value=result) as workflow,
            patch("roster_theory.cli.target_workflow_report", return_value={"targets": []}),
            redirect_stdout(io.StringIO()) as output,
            redirect_stderr(io.StringIO()),
        ):
            targets_args.func(targets_args)
            self.assertEqual(json.loads(output.getvalue()), {"targets": []})
            self.assertFalse(workflow.call_args.kwargs["search"])
            self.assertEqual(prepare.call_count, 1)
        with (
            patch("roster_theory.cli._prepare_trade_analysis") as prepare,
            patch("roster_theory.cli.run_target_workflow", return_value=result) as workflow,
            patch("roster_theory.cli.target_workflow_report", return_value={"packages": []}),
            redirect_stdout(io.StringIO()) as output,
            redirect_stderr(io.StringIO()),
        ):
            search_args.func(search_args)
            self.assertEqual(json.loads(output.getvalue()), {"packages": []})
            self.assertTrue(workflow.call_args.kwargs["search"])
            self.assertEqual(prepare.call_count, 1)
        with (
            patch("roster_theory.cli._prepare_trade_analysis") as prepare,
            patch("roster_theory.cli.load_target_workflow_evidence", return_value={"replay_mode": "OFFLINE/NON-CURRENT"}),
            patch("roster_theory.cli.run_target_workflow") as workflow,
            redirect_stdout(io.StringIO()) as output,
        ):
            replay_args.func(replay_args)
            self.assertIn("OFFLINE/NON-CURRENT", output.getvalue())
            prepare.assert_not_called()
            workflow.assert_not_called()


if __name__ == "__main__":
    unittest.main()
