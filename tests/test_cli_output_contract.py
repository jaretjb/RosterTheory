import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from roster_theory.cli import build_parser, main
from roster_theory.core.errors import (
    CoverageIncomplete,
    SourceUnavailable,
    StaleData,
    Uncalibrated,
)
from roster_theory.mock_watcher import format_mock_report
from roster_theory.terminal import TerminalCapabilities, detect_stdout


ROOT = Path(__file__).resolve().parents[1]


@dataclass
class ReportRow:
    finding: str = "evidence retained"


class FakeStream:
    def __init__(self, tty):
        self.tty = tty

    def isatty(self):
        return self.tty


class TerminalCapabilityTests(unittest.TestCase):
    def test_pipe_narrow_no_color_and_linux_term(self):
        pipe = detect_stdout(FakeStream(False), environ={}, platform_name="posix", width=28)
        self.assertEqual(pipe.width, 28)
        self.assertTrue(pipe.redirected)
        self.assertFalse(pipe.ansi_supported)
        self.assertFalse(pipe.color_enabled)
        self.assertFalse(pipe.unicode_supported)

        tty = detect_stdout(FakeStream(True), environ={}, platform_name="posix", width=28)
        self.assertTrue(tty.interactive)
        self.assertTrue(tty.color_enabled)
        no_color = detect_stdout(
            FakeStream(True), environ={"NO_COLOR": ""}, platform_name="posix", width=28
        )
        self.assertTrue(no_color.ansi_supported)
        self.assertFalse(no_color.color_enabled)
        dumb = detect_stdout(
            FakeStream(True), environ={"TERM": "dumb"}, platform_name="posix", width=28
        )
        self.assertFalse(dumb.ansi_supported)

    def test_width_tiers_and_windows_unicode_fallback(self):
        for width, expected in ((120, "wide"), (80, "standard"), (50, "compact"), (30, "narrow")):
            with self.subTest(width=width):
                value = detect_stdout(
                    FakeStream(True), environ={}, platform_name="posix", width=width
                )
                self.assertEqual(value.width_tier.value, expected)

        windows = FakeStream(True)
        windows.encoding = "cp1252"
        value = detect_stdout(
            windows,
            environ={},
            platform_name="nt",
            width=100,
            windows_vt=lambda _stream: True,
        )
        self.assertFalse(value.unicode_supported)

    def test_windows_requires_virtual_terminal_support(self):
        for supported in (False, True):
            with self.subTest(supported=supported):
                capabilities = detect_stdout(
                    FakeStream(True),
                    environ={},
                    platform_name="nt",
                    width=32,
                    windows_vt=lambda _stream: supported,
                )
                self.assertEqual(capabilities.color_enabled, supported)
                self.assertEqual(capabilities.ansi_supported, supported)


class JsonCommandTests(unittest.TestCase):
    def _invoke(self, arguments, service_name, service_result, report_name=None, report=None):
        args = build_parser().parse_args(arguments)
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch(f"roster_theory.cli.{service_name}", return_value=service_result):
            if report_name:
                with patch(f"roster_theory.cli.{report_name}", return_value=report):
                    with redirect_stdout(stdout), redirect_stderr(stderr):
                        args.func(args)
            else:
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    args.func(args)
        return json.loads(stdout.getvalue()), stderr.getvalue()

    def test_each_json_decision_command_has_one_stdout_value(self):
        cases = (
            (["waiver", "evaluate", "league", "--add", "A", "--inputs", "inputs", "--json"],
             "evaluate_entered_waiver", SimpleNamespace(), "waiver_evaluation_report", {"finding": "waiver"}),
            (["waiver", "search", "league", "--inputs", "inputs", "--json"],
             "search_waivers", SimpleNamespace(), "waiver_search_report", {"finding": "search"}),
            (["trade", "evaluate", "league", "--send", "A", "--receive", "B", "--json"],
             "evaluate_entered_trade", SimpleNamespace(output_path="eval.json"), "evaluation_report", {"finding": "trade"}),
        )
        for arguments, service, result, report_name, report in cases:
            with self.subTest(arguments=arguments):
                parsed, notice = self._invoke(arguments, service, result, report_name, report)
                self.assertEqual(parsed, report)
                if arguments[0] == "trade":
                    self.assertIn("Saved evidence", notice)

        result = SimpleNamespace(
            diagnosis=ReportRow(), evidence_hash="hash", output_path="diagnosis.json"
        )
        parsed, notice = self._invoke(
            ["trade", "diagnose", "league", "--json"], "diagnose_current_roster", result
        )
        self.assertEqual(parsed["diagnosis"]["finding"], "evidence retained")
        self.assertEqual(notice, "")

        result = SimpleNamespace(gaps=ReportRow(), output_path="gaps.json", csv_path="gaps.csv")
        parsed, notice = self._invoke(
            ["trade", "gaps", "league", "--json"], "run_gap_report", result
        )
        self.assertEqual(parsed["finding"], "evidence retained")
        self.assertIn("Saved CSV", notice)

        result = SimpleNamespace(search=ReportRow(), output_path="search.json", csv_path="search.csv")
        parsed, notice = self._invoke(
            ["trade", "search", "league", "--json"], "run_league_search", result
        )
        self.assertEqual(parsed["finding"], "evidence retained")
        self.assertIn("Saved evidence", notice)

        with tempfile.TemporaryDirectory() as directory:
            packages = Path(directory) / "packages.json"
            packages.write_text("[]", encoding="utf-8")
            result = SimpleNamespace(
                evaluations=[ReportRow()], evidence_hash="hash", output_path="compare.json"
            )
            parsed, notice = self._invoke(
                ["trade", "compare", "league", "--packages", str(packages), "--json"],
                "run_package_comparison", result,
            )
            self.assertEqual(parsed["evaluations"][0]["finding"], "evidence retained")
            self.assertIn("Saved evidence", notice)

    def test_json_failures_keep_status_type_and_reason(self):
        args = build_parser().parse_args(
            ["waiver", "evaluate", "league", "--add", "A", "--inputs", "inputs", "--json"]
        )
        for error, expected in (
            (Uncalibrated("uncalibrated: policy belongs to another league"), "uncalibrated"),
            (SourceUnavailable("selected expert source unavailable"), "unavailable"),
            (CoverageIncomplete("partial expert coverage: 7 unmatched players"), "incomplete"),
            (StaleData("weekly projections are stale"), "stale"),
            (ValueError("ambiguous player identity: A"), "error"),
        ):
            with self.subTest(error=error):
                stdout, stderr = io.StringIO(), io.StringIO()
                with patch("roster_theory.cli.evaluate_entered_waiver", side_effect=error), \
                     redirect_stdout(stdout), redirect_stderr(stderr), \
                     self.assertRaisesRegex(SystemExit, "2"):
                    args.func(args)
                payload = json.loads(stdout.getvalue())
                self.assertEqual(payload["status"], expected)
                self.assertEqual(payload["error_type"], type(error).__name__)
                self.assertEqual(payload["reason"], str(error))
                self.assertEqual(stderr.getvalue(), "")

    def test_machine_parser_failure_is_one_json_value_from_other_directory(self):
        env = os.environ.copy()
        env["PYTHONPATH"] = str(ROOT / "src")
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(
                [sys.executable, "-m", "roster_theory", "waiver", "evaluate", "--json"],
                cwd=directory, env=env, capture_output=True, text=True, check=False,
            )
        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(result.stdout)["status"], "invalid_arguments")
        self.assertEqual(result.stderr, "")

    def test_runtime_machine_failure_exits_two_in_python_process(self):
        env = os.environ.copy()
        env["PYTHONPATH"] = str(ROOT / "src")
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(
                [sys.executable, "-m", "roster_theory", "waiver", "evaluate", "league", "--json"],
                cwd=directory, env=env, capture_output=True, text=True, check=False,
            )
        self.assertEqual(result.returncode, 2)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "error")
        self.assertIn("--add and --inputs", payload["reason"])
        self.assertEqual(result.stderr, "")

    def test_main_rejects_stray_human_stdout_in_json_mode(self):
        fake_args = SimpleNamespace(
            command="waiver", waiver_command="search", json=True,
            func=lambda _args: print("progress banner"),
        )
        stdout = io.StringIO()
        with patch.object(sys, "argv", ["roster-theory", "waiver", "search", "--json"]), \
             patch("roster_theory.cli.build_parser") as parser, redirect_stdout(stdout), \
             self.assertRaisesRegex(SystemExit, "2"):
            parser.return_value.parse_args.return_value = fake_args
            main()
        self.assertEqual(json.loads(stdout.getvalue())["status"], "output_error")

    def test_main_preserves_failure_reason_after_progress_and_exit_codes(self):
        def partial_failure(_args):
            print("progress")
            raise SourceUnavailable("selected expert rows unavailable")

        for json_mode in (False, True):
            with self.subTest(json_mode=json_mode):
                fake_args = SimpleNamespace(
                    command="trade", trade_command="search", json=json_mode, func=partial_failure
                )
                stdout, stderr = io.StringIO(), io.StringIO()
                with patch.object(sys, "argv", ["roster-theory", "trade", "search"]), \
                     patch("roster_theory.cli.build_parser") as parser, \
                     redirect_stdout(stdout), redirect_stderr(stderr), \
                     self.assertRaisesRegex(SystemExit, "2"):
                    parser.return_value.parse_args.return_value = fake_args
                    main()
                if json_mode:
                    payload = json.loads(stdout.getvalue())
                    self.assertEqual(payload["status"], "unavailable")
                    self.assertEqual(payload["reason"], "selected expert rows unavailable")
                    self.assertEqual(stderr.getvalue(), "")
                else:
                    self.assertIn("selected expert rows unavailable", stderr.getvalue())

        fake_args = SimpleNamespace(
            command="trade", trade_command="search", json=True,
            func=lambda _args: (_ for _ in ()).throw(TypeError("programmer defect")),
        )
        stdout = io.StringIO()
        with patch.object(sys, "argv", ["roster-theory", "trade", "search", "--json"]), \
             patch("roster_theory.cli.build_parser") as parser, redirect_stdout(stdout), \
             self.assertRaisesRegex(SystemExit, "1"):
            parser.return_value.parse_args.return_value = fake_args
            main()
        self.assertEqual(json.loads(stdout.getvalue())["status"], "internal_error")


class WatcherOutputTests(unittest.TestCase):
    def test_json_watcher_collects_reports_and_human_pipe_stays_readable(self):
        report = {
            "draft_id": "synthetic-draft",
            "draft_slot": 1,
            "rosters": {},
            "recommendation": {},
            "transition": "initial",
            "status": "pending",
            "warnings": ["partial data"],
        }
        for json_mode in (False, True):
            with self.subTest(json_mode=json_mode):
                argv = ["watch-mock", "draft", "--board", "board.csv", "--once"]
                if json_mode:
                    argv.append("--json")
                args = build_parser().parse_args(argv)
                stdout = io.StringIO()
                capabilities = TerminalCapabilities(False, True, 28, False, False)
                with patch("roster_theory.cli._load_board", return_value=[]), \
                     patch("roster_theory.cli.SleeperClient"), \
                     patch("roster_theory.cli.MockDraftWatcher") as watcher, \
                     patch("roster_theory.cli.detect_stdout", return_value=capabilities), \
                     redirect_stdout(stdout):
                    watcher.return_value.poll_once.return_value = report
                    args.func(args)
                if json_mode:
                    payload = json.loads(stdout.getvalue())
                    self.assertEqual(payload["reports"], [report])
                    self.assertEqual(payload["termination"], "single_poll")
                else:
                    self.assertEqual(stdout.getvalue(), format_mock_report(report, color=False) + "\n")
                    self.assertIn("ROSTER THEORY - READ ONLY", stdout.getvalue())
                    self.assertNotIn("\x1b[", stdout.getvalue())

    def test_multi_poll_json_watcher_still_writes_one_value(self):
        args = build_parser().parse_args(
            ["watch-mock", "draft", "--board", "board.csv", "--max-polls", "2", "--json"]
        )
        first = {"transition": "initial", "status": "pending", "warnings": ["partial"]}
        second = {"transition": "changed", "status": "pending", "warnings": ["unavailable"]}
        stdout = io.StringIO()
        with patch("roster_theory.cli._load_board", return_value=[]), \
             patch("roster_theory.cli.SleeperClient"), \
             patch("roster_theory.cli.MockDraftWatcher") as watcher, \
             patch("roster_theory.cli.time.sleep"), redirect_stdout(stdout):
            watcher.return_value.poll_once.side_effect = [first, second]
            args.func(args)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["reports"], [first, second])
        self.assertEqual(payload["polls"], 2)
        self.assertEqual(payload["termination"], "maximum_polls")

    def test_json_watcher_interruption_has_one_result_and_code_130(self):
        args = build_parser().parse_args(
            ["watch-mock", "draft", "--board", "board.csv", "--json"]
        )
        stdout = io.StringIO()
        with patch("roster_theory.cli._load_board", return_value=[]), \
             patch("roster_theory.cli.SleeperClient"), \
             patch("roster_theory.cli.MockDraftWatcher") as watcher, \
             redirect_stdout(stdout), self.assertRaisesRegex(SystemExit, "130"):
            watcher.return_value.poll_once.side_effect = KeyboardInterrupt()
            args.func(args)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["status"], "interrupted")
        self.assertEqual(payload["termination"], "user_interrupted")
        self.assertEqual(payload["reason"], "User interrupted watcher")


if __name__ == "__main__":
    unittest.main()
