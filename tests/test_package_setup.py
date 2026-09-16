from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stdout
from importlib import resources
from pathlib import Path
from tempfile import TemporaryDirectory

from roster_theory.cli import build_parser
from roster_theory.rankings import load_accuracy, load_expert_pool
from roster_theory.trade.schedule import load_schedule


class PackageSetupTests(unittest.TestCase):
    def test_bundled_config_is_synthetic_and_available_without_checkout_path(self) -> None:
        source = resources.files("roster_theory").joinpath("resources/leagues.example.json")
        config = json.loads(source.read_text(encoding="utf-8"))
        self.assertEqual(config["leagues"][0]["key"], "synthetic_league")
        self.assertEqual(config["leagues"][0]["policies"], {})
        self.assertIn("Synthetic", config["leagues"][0]["notes"])

    def test_example_config_prints_one_json_value_without_provider_calls(self) -> None:
        args = build_parser().parse_args(["example-config"])
        output = io.StringIO()
        with redirect_stdout(output):
            args.func(args)
        payload = json.loads(output.getvalue())
        self.assertEqual(payload["leagues"][0]["key"], "synthetic_league")
        self.assertNotIn("\x1b[", output.getvalue())

    def test_unbundled_inputs_have_actionable_missing_file_errors(self) -> None:
        with TemporaryDirectory() as directory:
            missing = Path(directory) / "missing.csv"
            with self.assertRaisesRegex(FileNotFoundError, "--accuracy PATH"):
                load_accuracy(missing)
            with self.assertRaisesRegex(FileNotFoundError, "--expert-pool PATH"):
                load_expert_pool(missing, {})
            with self.assertRaisesRegex(FileNotFoundError, "--schedule PATH"):
                load_schedule(missing)


if __name__ == "__main__":
    unittest.main()
