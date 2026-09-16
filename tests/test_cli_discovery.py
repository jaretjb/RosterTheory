import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class CliDiscoveryTests(unittest.TestCase):
    def test_guidance_and_help_work_offline_outside_repository(self):
        env = os.environ.copy()
        env["PYTHONPATH"] = str(ROOT / "src")
        env["ROSTER_THEORY_CONFIG"] = str(ROOT / "missing-leagues.json")
        env.pop("FANTASYPROS_API_KEY", None)

        with tempfile.TemporaryDirectory() as directory:
            for arguments, expected in (
                ([], "roster-theory help"),
                (["help"], "League setup"),
                (["--config", env["ROSTER_THEORY_CONFIG"], "help"], "ROSTER_THEORY_CONFIG"),
                (["--help"], "help"),
                (["trade", "--help"], "diagnose"),
                (["waiver", "evaluate", "--help"], "--inputs"),
            ):
                with self.subTest(arguments=arguments):
                    result = subprocess.run(
                        [sys.executable, "-m", "roster_theory", *arguments],
                        cwd=directory,
                        env=env,
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertIn(expected, result.stdout)
                    self.assertEqual(result.stderr, "")

            guidance = subprocess.run(
                [sys.executable, "-m", "roster_theory", "help"],
                cwd=directory,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            ).stdout
            for group in ("League setup", "Draft", "Trade", "Waiver", "Diagnostics"):
                self.assertIn(group, guidance)
            self.assertEqual(guidance.count("Example: roster-theory"), 5)
            self.assertIn("uncalibrated", guidance)
            self.assertIn("never submit a pick, trade, waiver claim, or lineup change", guidance)

            invalid = subprocess.run(
                [sys.executable, "-m", "roster_theory", "unknown-command"],
                cwd=directory,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(invalid.returncode, 2)
            self.assertIn("invalid choice", invalid.stderr)


if __name__ == "__main__":
    unittest.main()
