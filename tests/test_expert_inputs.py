import csv
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from roster_theory.cli import build_parser
from roster_theory.core.errors import CoverageIncomplete
from roster_theory.expert_inputs import (
    default_expert_input_paths,
    inspect_expert_inputs,
    refresh_expert_inputs,
)
from roster_theory.trade.board_service import (
    default_inseason_expert_pool_path,
    load_expert_pool,
)


NOW = datetime(2099, 9, 1, 12, tzinfo=timezone.utc)


def accuracy_html() -> str:
    sources = ("Site A", "Site A", "Site B", "Site B", "Site C", "Site C")
    rows = []
    for index, source in enumerate(sources, start=1):
        rows.append(
            "{" + (
                f'"id":{index},"rank":{index},'
                f'"expert":{{"label":"Expert {index} - {source}"}},'
                f'"qb":{index},"rb":{index},"wr":{index},"te":{index},'
                f'"k":{index},"dst":{index},"idp":{index}'
            ) + "}"
        )
    return "<script>[" + ",".join(rows) + "]</script>"


def current_experts() -> dict:
    captured = NOW.isoformat()
    sources = ("Site A", "Site A", "Site B", "Site B", "Site C", "Site C")
    return {
        "experts": [
            {
                "expert_id": index,
                "name": f"Expert {index}",
                "source": source,
                "positions": {position: captured for position in ("QB", "RB", "WR", "TE")},
                "accuracy_weekly": {"ALL": index},
                "accuracy_weekly_last_season": {"ALL": index},
            }
            for index, source in enumerate(sources, start=1)
        ]
    }


class FakeFantasyPros:
    base_url = "https://api.example.test"

    def ranking_experts(self, season, **params):
        self.season = season
        self.params = params
        return current_experts()


def write_config(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "owner": {"sleeper_username": "synthetic"},
                "leagues": [{"key": "league_alpha", "season": "2099"}],
            }
        ),
        encoding="utf-8",
    )


class ExpertInputTests(unittest.TestCase):
    def test_generated_pool_path_matches_trade_and_waiver_default(self):
        generated = default_expert_input_paths("league_alpha", 2099).inseason_pool
        consumed = default_inseason_expert_pool_path("league_alpha", 2099)
        self.assertEqual(generated, consumed)

    def test_refresh_builds_every_consumed_artifact_and_audits_selection(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "leagues.json"
            write_config(config)
            with patch("roster_theory.expert_inputs.time.sleep"):
                result = refresh_expert_inputs(
                    "league_alpha",
                    config_path=config,
                    data_dir=root / "data",
                    artifact="all",
                    now=NOW,
                    client=FakeFantasyPros(),
                    fetch_text=lambda _url, _timeout: accuracy_html(),
                )

            self.assertEqual(result["schema_version"], "roster-theory.inputs/v1")
            self.assertEqual(result["status"], "ready")
            self.assertFalse(result["sleeper_write_performed"])
            self.assertEqual(result["provider_calls"][0]["budget_cost"], 11)
            paths = default_expert_input_paths(
                "league_alpha", 2099, data_dir=root / "data"
            )
            for path in (
                paths.draft_category,
                paths.draft_annual,
                paths.inseason_accuracy,
                paths.inseason_pool,
                paths.audit,
            ):
                self.assertTrue(path.is_file(), path)

            pool = load_expert_pool(paths.inseason_pool)
            self.assertEqual([row.expert_id for row in pool], ["1", "2", "3", "4", "5"])
            self.assertAlmostEqual(sum(row.weight for row in pool), 1.0)
            with paths.inseason_pool.open("r", encoding="utf-8", newline="") as handle:
                rows = tuple(csv.DictReader(handle))
            self.assertTrue(all(row["accuracy_authority"] == "weekly_inseason" for row in rows))
            self.assertTrue(all(row["current_horizon"] == "ROS" for row in rows))
            audit = json.loads(paths.audit.read_text(encoding="utf-8"))
            self.assertFalse(audit["selection_policy"]["preseason_proxy_permitted"])
            self.assertEqual(
                [row["status"] for row in audit["selection"]].count("selected"), 5
            )
            self.assertIn("below_selection_cutoff", {row["status"] for row in audit["selection"]})

            inspected = inspect_expert_inputs(
                "league_alpha", config_path=config, data_dir=root / "data"
            )
            self.assertEqual(inspected["status"], "ready")

    def test_saved_provider_evidence_replays_without_network(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "leagues.json"
            write_config(config)
            with patch("roster_theory.expert_inputs.time.sleep"):
                refresh_expert_inputs(
                    "league_alpha",
                    config_path=config,
                    data_dir=root / "first",
                    now=NOW,
                    client=FakeFantasyPros(),
                    fetch_text=lambda _url, _timeout: accuracy_html(),
                )
            replay = default_expert_input_paths(
                "league_alpha", 2099, data_dir=root / "first"
            ).evidence_dir

            result = refresh_expert_inputs(
                "league_alpha",
                config_path=config,
                data_dir=root / "second",
                replay_dir=replay,
                now=NOW,
                client=None,
                fetch_text=lambda *_args: self.fail("network fetch during replay"),
            )

            self.assertEqual(result["status"], "ready")
            self.assertEqual(result["mode"], "replay")
            self.assertEqual(result["provider_calls"][0]["budget_cost"], 0)

    def test_dry_run_makes_no_provider_call_or_write(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "leagues.json"
            write_config(config)
            result = refresh_expert_inputs(
                "league_alpha",
                config_path=config,
                data_dir=root / "data",
                dry_run=True,
                fetch_text=lambda *_args: self.fail("provider call during dry-run"),
            )
            self.assertEqual(result["status"], "planned")
            self.assertTrue(result["dry_run"])
            self.assertFalse((root / "data").exists())

    def test_partial_current_availability_fails_closed(self):
        class PartialClient(FakeFantasyPros):
            def ranking_experts(self, season, **params):
                value = current_experts()
                value["experts"] = value["experts"][:4]
                return value

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "leagues.json"
            write_config(config)
            with patch("roster_theory.expert_inputs.time.sleep"), self.assertRaises(
                CoverageIncomplete
            ):
                refresh_expert_inputs(
                    "league_alpha",
                    config_path=config,
                    data_dir=root / "data",
                    artifact="inseason-pool",
                    now=NOW,
                    client=PartialClient(),
                    fetch_text=lambda _url, _timeout: accuracy_html(),
                )

    def test_empty_limited_directory_persists_history_and_reports_access(self):
        class LimitedClient(FakeFantasyPros):
            def ranking_experts(self, season, **params):
                return {"experts": [], "count": 0, "public_api_limited": True}

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "leagues.json"
            write_config(config)
            paths = default_expert_input_paths(
                "league_alpha", 2099, data_dir=root / "data"
            )
            with patch("roster_theory.expert_inputs.time.sleep"), self.assertRaisesRegex(
                CoverageIncomplete, "public_api_limited=true"
            ):
                refresh_expert_inputs(
                    "league_alpha",
                    config_path=config,
                    data_dir=root / "data",
                    artifact="inseason-pool",
                    now=NOW,
                    client=LimitedClient(),
                    fetch_text=lambda _url, _timeout: accuracy_html(),
                )
            self.assertTrue(paths.inseason_accuracy.is_file())

            with patch("roster_theory.expert_inputs.time.sleep"), self.assertRaises(
                CoverageIncomplete
            ):
                refresh_expert_inputs(
                    "league_alpha",
                    config_path=config,
                    data_dir=root / "data",
                    artifact="inseason-pool",
                    reuse_historical=True,
                    now=NOW,
                    client=LimitedClient(),
                    fetch_text=lambda *_args: self.fail("historical refetch"),
                )

    def test_provider_naive_update_timestamps_are_conservatively_utc(self):
        class NaiveClient(FakeFantasyPros):
            def ranking_experts(self, season, **params):
                value = current_experts()
                for expert in value["experts"]:
                    expert["positions"] = {
                        position: timestamp.replace("+00:00", "")
                        for position, timestamp in expert["positions"].items()
                    }
                return value

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "leagues.json"
            write_config(config)
            with patch("roster_theory.expert_inputs.time.sleep"):
                result = refresh_expert_inputs(
                    "league_alpha",
                    config_path=config,
                    data_dir=root / "data",
                    artifact="inseason-pool",
                    now=NOW,
                    client=NaiveClient(),
                    fetch_text=lambda _url, _timeout: accuracy_html(),
                )
            self.assertEqual(result["status"], "ready")
            audit = json.loads(default_expert_input_paths(
                "league_alpha", 2099, data_dir=root / "data"
            ).audit.read_text(encoding="utf-8"))
            self.assertTrue(
                audit["selection_policy"]["naive_provider_timestamps_assumed_utc"]
            )


    def test_cli_exposes_inspect_refresh_validate_and_import(self):
        parser = build_parser()
        for operation in ("inspect", "refresh", "validate"):
            args = parser.parse_args(
                ["inputs", "experts", operation, "league_alpha", "--json"]
            )
            self.assertEqual(args.inputs_group, "experts")
            self.assertEqual(args.expert_input_command, operation)
        imported = parser.parse_args(
            [
                "inputs",
                "experts",
                "import",
                "league_alpha",
                "--input",
                "saved-evidence",
            ]
        )
        self.assertEqual(imported.input, "saved-evidence")


if __name__ == "__main__":
    unittest.main()
