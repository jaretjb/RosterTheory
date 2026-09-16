import csv
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from roster_theory.cli import build_parser, command_leagues, command_waiver_evaluate
from roster_theory.core.errors import Uncalibrated
from roster_theory.sleeper import (
    find_league_config,
    load_league_config,
    resolve_league_config_path,
    resolve_league_policy_path,
)


class LeagueConfigurationTests(unittest.TestCase):
    @staticmethod
    def _write_config(root: Path, league_key: str, policy_key: str | None = None) -> Path:
        policies = {policy_key: "policies/decision.json"} if policy_key else {}
        path = root / "leagues.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "owner": {"sleeper_user_id": f"owner-{league_key}"},
                    "leagues": [
                        {
                            "key": league_key,
                            "league_id": f"id-{league_key}",
                            "policies": policies,
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        return path

    def test_explicit_cli_config_reaches_two_independent_leagues_outside_repo(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            alpha = self._write_config(root / "alpha", "league_alpha")
            beta = self._write_config(root / "beta", "league_beta")
            previous = Path.cwd()
            os.chdir(root)
            try:
                for path, key in ((alpha, "league_alpha"), (beta, "league_beta")):
                    args = build_parser().parse_args(
                        ["--config", str(path), "leagues"]
                    )
                    output = io.StringIO()
                    with redirect_stdout(output):
                        command_leagues(args)
                    self.assertEqual(json.loads(output.getvalue())[0]["key"], key)
                    self.assertEqual(find_league_config(key, path)["league_id"], f"id-{key}")
            finally:
                os.chdir(previous)

    def test_environment_config_path_is_supported(self):
        with tempfile.TemporaryDirectory() as directory:
            config = self._write_config(Path(directory), "league_alpha")
            with patch.dict(os.environ, {"ROSTER_THEORY_CONFIG": str(config)}):
                self.assertEqual(resolve_league_config_path(), config)
                self.assertEqual(load_league_config()[0]["key"], "league_alpha")

    def test_relative_policy_is_anchored_to_config_and_cross_league_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = self._write_config(root, "league_alpha", "trade_decision")
            policy = root / "policies" / "decision.json"
            policy.parent.mkdir(parents=True)
            policy.write_text(
                json.dumps({"league_key": "league_alpha", "version": "alpha-v1"}),
                encoding="utf-8",
            )
            self.assertEqual(
                resolve_league_policy_path(
                    "league_alpha", "trade_decision", config_path=config
                ),
                policy,
            )
            policy.write_text(
                json.dumps({"league_key": "league_beta", "version": "beta-v1"}),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(Uncalibrated, "not 'league_alpha'"):
                resolve_league_policy_path(
                    "league_alpha", "trade_decision", config_path=config
                )

    def test_missing_policy_fails_closed_as_uncalibrated(self):
        with tempfile.TemporaryDirectory() as directory:
            config = self._write_config(Path(directory), "league_alpha")
            with self.assertRaisesRegex(Uncalibrated, "uncalibrated"):
                resolve_league_policy_path(
                    "league_alpha", "waiver_decision", config_path=config
                )

    def test_cli_reports_uncalibrated_as_a_machine_readable_result(self):
        with tempfile.TemporaryDirectory() as directory:
            config = self._write_config(Path(directory), "league_alpha")
            args = build_parser().parse_args(
                [
                    "--config",
                    str(config),
                    "waiver",
                    "evaluate",
                    "league_alpha",
                    "--add",
                    "Synthetic Player",
                    "--inputs",
                    "inputs.json",
                ]
            )
            error = Uncalibrated("uncalibrated: no proved policy")
            output = io.StringIO()
            with patch(
                "roster_theory.cli.evaluate_entered_waiver", side_effect=error
            ), redirect_stderr(output), self.assertRaisesRegex(SystemExit, "2"):
                command_waiver_evaluate(args)
            result = json.loads(output.getvalue())
            self.assertEqual(result["status"], "uncalibrated")
            self.assertEqual(result["league"], "league_alpha")

    def test_draft_preferences_must_name_the_selected_league(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = self._write_config(root, "league_alpha", "draft_preferences")
            preferences = root / "policies" / "decision.json"
            preferences = preferences.with_suffix(".csv")
            preferences.parent.mkdir(parents=True)
            with preferences.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=("league_scope", "player_name"))
                writer.writeheader()
                writer.writerow({"league_scope": "league_beta", "player_name": "Example"})
            payload = json.loads(config.read_text(encoding="utf-8"))
            payload["leagues"][0]["policies"]["draft_preferences"] = (
                "policies/decision.csv"
            )
            config.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(Uncalibrated, "do not declare"):
                resolve_league_policy_path(
                    "league_alpha", "draft_preferences", config_path=config
                )


if __name__ == "__main__":
    unittest.main()
