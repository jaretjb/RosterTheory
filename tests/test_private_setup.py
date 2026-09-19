import csv
import json
import tempfile
import unittest
from pathlib import Path

from roster_theory.cli import build_parser
from roster_theory.core.errors import Uncalibrated
from roster_theory.doctor import audit_setup
from roster_theory.grouped_rankings import load_expert_pool_overrides
from roster_theory.private_setup import (
    ARTIFACTS,
    add_league,
    artifact_paths,
    import_private_runtime,
    initialize_private_runtime,
    inspect_private_setup,
    migrate_legacy_trade_policy_metadata,
    migrate_legacy_waiver_policy_metadata,
    scaffold_private_inputs,
    set_owner,
    show_redacted_setup,
    update_override,
)
from roster_theory.trade.board_service import load_inseason_identity_overrides
from roster_theory.sleeper import resolve_league_policy_path


def configured_runtime(root: Path) -> Path:
    config = root / "private runtime" / "leagues.json"
    initialize_private_runtime(config_path=config)
    set_owner(
        sleeper_username="private-user",
        sleeper_user_id="private-user-id",
        config_path=config,
        update=True,
    )
    add_league(
        "league_alpha",
        season=2099,
        name="Private League",
        league_id="private-league-id",
        user_roster_id=1,
        draft_id="private-draft-id",
        user_draft_slot=2,
        team_count=12,
        config_path=config,
        update=True,
    )
    return config


class PrivateSetupTests(unittest.TestCase):
    def test_legacy_trade_policy_metadata_migration_preserves_calibration(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = configured_runtime(root)
            policy_dir = config.parent / "legacy"
            policy_dir.mkdir()
            decision = policy_dir / "trade-decision.json"
            search = policy_dir / "trade-search.json"
            for path, version in (
                (decision, "decision-v1"),
                (search, "search-v1"),
            ):
                path.write_text(json.dumps({
                    "schema_version": 1,
                    "product": "TRADE ASSISTANT",
                    "league_key": "league_alpha",
                    "version": version,
                    "calibrated_value": 4.5,
                }), encoding="utf-8")
            value = json.loads(config.read_text(encoding="utf-8"))
            value["leagues"][0]["policies"] = {
                "trade_decision": "legacy/trade-decision.json",
                "trade_search": "legacy/trade-search.json",
            }
            config.write_text(json.dumps(value), encoding="utf-8")

            result = migrate_legacy_trade_policy_metadata(
                "league_alpha", config_path=config
            )

            self.assertEqual(len(result["writes"]), 2)
            self.assertEqual(len(result["backups"]), 2)
            migrated = json.loads(search.read_text(encoding="utf-8"))
            self.assertEqual(migrated["season"], 2099)
            self.assertEqual(migrated["artifact"], "trade-search")
            self.assertEqual(migrated["calibrated_value"], 4.5)
            self.assertEqual(migrated["version"], "search-v1")

    def test_legacy_waiver_policy_metadata_migration_preserves_calibration(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = configured_runtime(root)
            policy_dir = config.parent / "legacy"
            policy_dir.mkdir()
            decision = policy_dir / "decision.json"
            wire = policy_dir / "wire.json"
            decision.write_text(json.dumps({
                "schema_version": 1, "product": "WAIVER ASSISTANT",
                "league_key": "league_alpha", "version": "calibrated-v1",
                "threshold": 7.25,
            }), encoding="utf-8")
            wire.write_text(json.dumps({
                "schema_version": 1, "product": "WAIVER ASSISTANT",
                "league_key": "league_alpha", "trusted_expert_ids": ["17"],
            }), encoding="utf-8")
            value = json.loads(config.read_text(encoding="utf-8"))
            value["leagues"][0]["policies"] = {
                "waiver_decision": "legacy/decision.json",
                "waiver_wire": "legacy/wire.json",
            }
            config.write_text(json.dumps(value), encoding="utf-8")

            result = migrate_legacy_waiver_policy_metadata(
                "league_alpha", config_path=config
            )

            self.assertEqual(len(result["writes"]), 2)
            self.assertEqual(len(result["backups"]), 2)
            migrated = json.loads(decision.read_text(encoding="utf-8"))
            self.assertEqual(migrated["season"], 2099)
            self.assertEqual(migrated["artifact"], "waiver-decision")
            self.assertEqual(migrated["threshold"], 7.25)
            self.assertEqual(migrated["version"], "calibrated-v1")

    def test_init_is_previewable_non_destructive_and_backed_up_on_replace(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "path with spaces" / "leagues.json"
            preview = initialize_private_runtime(config_path=config, dry_run=True)
            self.assertFalse(config.exists())
            self.assertEqual(preview["writes"], [str(config)])

            initialize_private_runtime(config_path=config)
            with self.assertRaises(FileExistsError):
                initialize_private_runtime(config_path=config)
            replaced = initialize_private_runtime(config_path=config, replace=True)
            self.assertEqual(len(replaced["backups"]), 1)
            self.assertTrue(Path(replaced["backups"][0]).is_file())

    def test_import_validates_and_requires_replace_for_existing_config(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.json"
            target = root / "target.json"
            source.write_text(
                json.dumps({
                    "owner": {},
                    "leagues": [{"key": "league_alpha", "season": "2099", "policies": {}}],
                }),
                encoding="utf-8",
            )
            imported = import_private_runtime(source, config_path=target)
            self.assertEqual(imported["league_count"], 1)
            with self.assertRaises(FileExistsError):
                import_private_runtime(source, config_path=target)
            replaced = import_private_runtime(source, config_path=target, replace=True)
            self.assertEqual(len(replaced["backups"]), 1)

    def test_import_rebases_relative_policy_paths_to_the_source_runtime(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source runtime" / "leagues.json"
            source.parent.mkdir()
            source.write_text(json.dumps({
                "owner": {},
                "leagues": [{
                    "key": "league_alpha", "season": "2099",
                    "policies": {"waiver_decision": "policies/waiver.json"},
                }],
            }), encoding="utf-8")
            target = root / "user config" / "leagues.json"

            import_private_runtime(source, config_path=target)

            imported = json.loads(target.read_text(encoding="utf-8"))
            self.assertEqual(
                Path(imported["leagues"][0]["policies"]["waiver_decision"]),
                (source.parent / "policies/waiver.json").resolve(),
            )

    def test_owner_and_league_updates_are_explicit_and_redacted(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "leagues.json"
            initialize_private_runtime(config_path=config)
            with self.assertRaises(FileExistsError):
                set_owner(
                    sleeper_username="private-user",
                    sleeper_user_id="private-id",
                    config_path=config,
                )
            set_owner(
                sleeper_username="private-user",
                sleeper_user_id="private-id",
                config_path=config,
                update=True,
            )
            with self.assertRaises(FileExistsError):
                add_league(
                    "league_alpha", season=2099, name="Private", league_id="league-id",
                    user_roster_id=1, config_path=config,
                )
            result = add_league(
                "league_alpha", season=2099, name="Private", league_id="league-id",
                user_roster_id=1, config_path=config, update=True,
            )
            self.assertEqual(len(result["backups"]), 1)
            shown = show_redacted_setup(config_path=config)
            rendered = json.dumps(shown)
            self.assertNotIn("private-user", rendered)
            self.assertNotIn("private-id", rendered)
            self.assertNotIn("league-id", rendered)

    def test_scaffold_is_season_aware_uncalibrated_and_updates_config(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = configured_runtime(root)
            with self.assertRaisesRegex(ValueError, "update-config"):
                scaffold_private_inputs("league_alpha", config_path=config)

            result = scaffold_private_inputs(
                "league_alpha", config_path=config, update_config=True
            )
            self.assertEqual(set(result["artifacts"]), set(ARTIFACTS))
            self.assertEqual(result["policy_status"], "UNCALIBRATED")
            paths = artifact_paths("league_alpha", config_path=config)
            self.assertTrue(all("2099" in str(path) for path in paths.values()))
            self.assertTrue(all(path.is_file() for path in paths.values()))
            config_value = json.loads(config.read_text(encoding="utf-8"))
            policies = config_value["leagues"][0]["policies"]
            self.assertEqual(set(policies), {
                "draft_preferences", "trade_decision", "trade_search",
                "waiver_decision", "waiver_wire",
            })
            inspected = inspect_private_setup(
                operation="validate", config_path=config, league_key="league_alpha"
            )
            self.assertEqual(inspected["status"], "uncalibrated")
            self.assertTrue(all(
                row["status"] == "uncalibrated"
                for row in inspected["leagues"][0]["artifacts"]
                if row["artifact"] in {
                    "draft-preferences", "trade-decision", "trade-search",
                    "waiver-decision", "waiver-wire",
                }
            ))
            with self.assertRaisesRegex(Uncalibrated, "separately supported thresholds"):
                resolve_league_policy_path(
                    "league_alpha", "trade_decision", config_path=config
                )
            with self.assertRaises(FileExistsError):
                scaffold_private_inputs(
                    "league_alpha", config_path=config, update_config=True
                )
            replaced = scaffold_private_inputs(
                "league_alpha", config_path=config, update_config=True, replace=True
            )
            self.assertGreaterEqual(len(replaced["backups"]), len(ARTIFACTS))

    def test_override_add_remove_requires_human_audit_fields_and_keeps_backups(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = configured_runtime(root)
            scaffold_private_inputs(
                "league_alpha",
                artifact="expert-overrides",
                config_path=config,
            )
            with self.assertRaises(FileExistsError):
                update_override(
                    "league_alpha", operation="add", kind="expert",
                    scope="skills_half_ppr", subject="Expert A", action="exclude",
                    reason="Documented conflict", evidence_date="2099-08-01",
                    source="User review", config_path=config,
                )
            added = update_override(
                "league_alpha", operation="add", kind="expert",
                scope="skills_half_ppr", subject="Expert A", action="exclude",
                reason="Documented conflict", evidence_date="2099-08-01",
                source="User review", config_path=config, update=True,
            )
            self.assertEqual(added["override_count"], 1)
            path = artifact_paths("league_alpha", config_path=config)["expert-overrides"]
            loaded = load_expert_pool_overrides(path)
            self.assertEqual(loaded["skills_half_ppr"]["excluded_experts"][0]["expert_name"], "Expert A")
            removed = update_override(
                "league_alpha", operation="remove", kind="expert",
                scope="skills_half_ppr", subject="Expert A", action="exclude",
                reason="Conflict resolved", evidence_date="2099-08-02",
                source="User review", config_path=config, update=True,
            )
            self.assertEqual(removed["override_count"], 0)
            audit = json.loads((path.parent / "override-audit.json").read_text(encoding="utf-8"))
            self.assertEqual([row["operation"] for row in audit["events"]], ["add", "remove"])
            self.assertTrue(removed["backups"])

    def test_identity_override_uses_existing_consumer_schema(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = configured_runtime(root)
            added = update_override(
                "league_alpha", operation="add", kind="identity", scope="inseason",
                subject="Player A", action="map", reason="Exact profile match",
                evidence_date="2099-08-01", source="User-authorized lookup",
                fantasypros_id="fp-1", sleeper_id="sl-1", team="ari", position="rb",
                config_path=config,
            )
            path = artifact_paths("league_alpha", config_path=config)["identity-overrides"]
            self.assertEqual(added["override_count"], 1)
            self.assertEqual(load_inseason_identity_overrides(path), {"fp-1": "sl-1"})
            with path.open(encoding="utf-8", newline="") as handle:
                row = next(csv.DictReader(handle))
            self.assertEqual(row["evidence_date"], "2099-08-01")
            self.assertEqual(row["source"], "User-authorized lookup")

    def test_doctor_points_to_concrete_setup_commands(self):
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "missing.json"
            report = audit_setup(config_path=missing)
            self.assertIn("roster-theory setup init", report["checks"][0]["next_action"])

            config = configured_runtime(Path(directory))
            report = audit_setup(config_path=config, league_key="league_alpha")
            policy_actions = [
                row["next_action"]
                for row in report["leagues"][0]["checks"]
                if row["check"] in {"trade_decision", "waiver_decision"}
            ]
            self.assertTrue(all("roster-theory setup scaffold" in action for action in policy_actions))

    def test_scaffolds_never_transfer_policy_between_leagues(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = configured_runtime(root)
            add_league(
                "league_beta", season=2099, name="Second Private League",
                league_id="second-private-id", user_roster_id=2,
                config_path=config, update=True,
            )
            scaffold_private_inputs(
                "league_alpha", artifact="trade-decision", config_path=config,
                update_config=True,
            )
            scaffold_private_inputs(
                "league_beta", artifact="trade-decision", config_path=config,
                update_config=True,
            )
            alpha = artifact_paths("league_alpha", config_path=config)["trade-decision"]
            beta = artifact_paths("league_beta", config_path=config)["trade-decision"]
            self.assertNotEqual(alpha, beta)
            self.assertEqual(json.loads(alpha.read_text(encoding="utf-8"))["league_key"], "league_alpha")
            self.assertEqual(json.loads(beta.read_text(encoding="utf-8"))["league_key"], "league_beta")

    def test_cli_exposes_setup_lifecycle_and_override_operations(self):
        parser = build_parser()
        commands = (
            ["setup", "init"],
            ["setup", "import", "--input", "C:\\private path\\leagues.json"],
            ["setup", "list"],
            ["setup", "validate"],
            ["setup", "show-redacted"],
            ["setup", "explain"],
            ["setup", "scaffold", "league_alpha", "--update-config"],
        )
        for command in commands:
            parsed = parser.parse_args(command)
            self.assertEqual(parsed.command, "setup")
        override = parser.parse_args([
            "setup", "override", "remove", "league_alpha", "--kind", "expert",
            "--scope", "skills", "--subject", "Expert A", "--action", "exclude",
            "--reason", "Resolved", "--evidence-date", "2099-08-02",
            "--source", "User review", "--update",
        ])
        self.assertEqual(override.override_operation, "remove")


if __name__ == "__main__":
    unittest.main()
