import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from roster_theory.cli import build_parser
from roster_theory.season_prepare import inspect_season_inputs, prepare_season_inputs


def write_config(root: Path, leagues=("alpha",)) -> Path:
    config = root / "private runtime" / "leagues.json"
    config.parent.mkdir(parents=True)
    config.write_text(
        json.dumps({
            "schema_version": 1,
            "owner": {"sleeper_username": "user", "sleeper_user_id": "owner-id"},
            "leagues": [{
                "key": key, "name": key, "league_id": f"{key}-id",
                "season": "2099", "user_roster_id": index,
                "draft_id": f"{key}-draft", "user_draft_slot": index,
                "policies": {},
            } for index, key in enumerate(leagues, start=1)],
        }),
        encoding="utf-8",
    )
    return config


class SeasonPreparationTests(unittest.TestCase):
    def test_cli_exposes_status_and_prepare_modes(self):
        parser = build_parser()
        status = parser.parse_args(["inputs", "status", "alpha", "--assistant", "draft"])
        prepare = parser.parse_args([
            "inputs", "prepare", "--all-leagues", "--assistant", "trade",
            "--refresh", "force", "--offline", "--dry-run", "--json",
        ])
        self.assertEqual(status.inputs_group, "status")
        self.assertEqual(prepare.inputs_group, "prepare")
        self.assertTrue(prepare.all_leagues)
        waiver_inputs = parser.parse_args(["waiver", "inputs", "alpha"])
        self.assertEqual(waiver_inputs.waiver_command, "inputs")

    def test_dry_run_is_a_call_and_write_preflight_with_no_side_effects(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = write_config(root)
            data = root / "path with spaces" / "data"
            calls = []

            result = prepare_season_inputs(
                "alpha", assistant="all", config_path=config, data_dir=data,
                dry_run=True,
                expert_refresh=lambda *args, **kwargs: calls.append("expert"),
                schedule_refresh=lambda *args, **kwargs: calls.append("schedule"),
            )

            self.assertEqual(result["status"], "planned")
            self.assertEqual(result["provider_calls"], 12)
            self.assertEqual(calls, [])
            self.assertTrue(all(operation["writes"] for operation in result["preflight"]))
            self.assertFalse(data.exists())
            self.assertFalse(result["recommendation_generated"])
            self.assertFalse(result["sleeper_write_performed"])

    def test_two_leagues_share_provider_evidence_but_keep_pools_league_scoped(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = write_config(root, ("alpha", "beta"))
            expert_calls = []
            schedule_calls = []

            result = prepare_season_inputs(
                all_leagues=True, assistant="all", config_path=config,
                data_dir=root / "data", refresh="auto",
                expert_refresh=lambda league, **kwargs: expert_calls.append((league, kwargs)),
                schedule_refresh=lambda league, **kwargs: schedule_calls.append((league, kwargs)),
            )

            provider_experts = [row for row in result["preflight"] if row["kind"] == "experts" and row["mode"] == "provider"]
            replay_experts = [row for row in result["preflight"] if row["kind"] == "experts" and row["mode"] == "replay"]
            self.assertEqual(result["provider_calls"], 12)
            self.assertEqual(len(schedule_calls), 1)
            self.assertEqual(len(provider_experts), 2)  # Draft history plus one ROS fetch.
            self.assertEqual(len(replay_experts), 1)
            self.assertEqual({call[0] for call in expert_calls}, {"alpha", "beta"})
            self.assertIn("expert_evidence", str(expert_calls[-1][1]["replay_dir"]))
            self.assertTrue(any("beta" in path for path in replay_experts[0]["writes"]))

    def test_offline_reports_exact_next_command_and_never_calls_provider(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = write_config(root)
            calls = []
            result = prepare_season_inputs(
                "alpha", assistant="trade", config_path=config,
                data_dir=root / "data", offline=True,
                expert_refresh=lambda *args, **kwargs: calls.append("expert"),
                schedule_refresh=lambda *args, **kwargs: calls.append("schedule"),
            )
            self.assertEqual(calls, [])
            self.assertEqual(result["status"], "blocked")
            self.assertEqual(result["provider_calls"], 0)
            self.assertEqual(
                result["errors"][0]["next_command"],
                "roster-theory inputs prepare alpha --assistant trade",
            )

    def test_status_does_not_create_runtime_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = write_config(root)
            data = root / "data"
            result = inspect_season_inputs(
                "alpha", assistant="waiver", config_path=config, data_dir=data
            )
            self.assertTrue(result["offline"])
            self.assertFalse(data.exists())
            self.assertEqual(result["provider_calls"], [])

    def test_fresh_status_avoids_repeating_provider_requests(self):
        ready = {
            "schema_version": "test", "operation": "status", "status": "ready",
            "assistant": "trade", "offline": True, "dry_run": False,
            "provider_calls": [], "writes": [],
            "leagues": [{"league": "alpha", "season": 2099, "status": "ready", "artifacts": []}],
            "recommendation_generated": False, "sleeper_write_performed": False,
        }
        with tempfile.TemporaryDirectory() as directory:
            config = write_config(Path(directory))
            calls = []
            with patch("roster_theory.season_prepare.inspect_season_inputs", return_value=ready):
                result = prepare_season_inputs(
                    "alpha", assistant="trade", config_path=config,
                    expert_refresh=lambda *args, **kwargs: calls.append("expert"),
                    schedule_refresh=lambda *args, **kwargs: calls.append("schedule"),
                )
            self.assertEqual(result["preflight"], [])
            self.assertEqual(result["provider_calls"], 0)
            self.assertEqual(calls, [])

    def test_provider_failure_is_reported_after_independent_work_continues(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = write_config(root)
            expert_calls = []

            def fail_schedule(*args, **kwargs):
                raise RuntimeError("synthetic provider outage")

            result = prepare_season_inputs(
                "alpha", assistant="trade", config_path=config, data_dir=root / "data",
                expert_refresh=lambda league, **kwargs: expert_calls.append(league),
                schedule_refresh=fail_schedule,
            )
            self.assertEqual(result["status"], "blocked")
            self.assertEqual(expert_calls, ["alpha"])
            self.assertEqual([row["status"] for row in result["preflight"]], ["completed", "failed"])
            self.assertEqual(result["errors"][0]["next_command"], "roster-theory inputs prepare alpha --assistant trade")


if __name__ == "__main__":
    unittest.main()
