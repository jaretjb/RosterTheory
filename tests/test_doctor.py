import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from roster_theory import cli
from roster_theory.doctor import audit_setup, format_doctor
from roster_theory.terminal import TerminalCapabilities


WAIVER_FIXTURE = Path(__file__).parent / "fixtures" / "waiver" / "league_alpha.decision-policy.json"


class DoctorTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.config = self.root / "secret-owner-config.json"

    def _write(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding="utf-8")
        return path

    def _league(self, key, *, policies=None):
        return {
            "key": key,
            "league_id": f"private-{key}-league-id",
            "draft_id": f"private-{key}-draft-id",
            "season": "2026",
            "user_roster_id": 1,
            "user_draft_slot": 2,
            "policies": policies or {},
        }

    def _config(self, leagues):
        self._write(
            self.config,
            {
                "owner": {"sleeper_user_id": "private-owner-id", "api_key": "secret-api-key"},
                "leagues": leagues,
            },
        )
        return self.config

    def _policy_files(self, key):
        policy_dir = self.root / "policies" / key
        draft = policy_dir / "draft.csv"
        draft.parent.mkdir(parents=True, exist_ok=True)
        draft.write_text(
            f"player_name,league_scope\nExample Player,{key}\n", encoding="utf-8"
        )
        trade_decision = self._write(
            policy_dir / "trade-decision.json",
            {
                "league_key": key,
                "version": "synthetic-v1",
                "scenario": {"offense_downside_multiplier": 0.7, "offense_upside_multiplier": 1.2},
                "decision": {
                    "user_selected_floor": 0,
                    "partner_market_floor": -5,
                    "postures": {
                        posture: {"max_depth_loss": 10, "max_downside_increase": 2}
                        for posture in ("CONSERVATIVE", "BALANCED", "CEILING")
                    },
                },
            },
        )
        trade_search = self._write(
            policy_dir / "trade-search.json",
            {
                "league_key": key,
                "version": "synthetic-v1",
                "target": {
                    "market_value_floor": 0,
                    "raw_projection_floor": 0,
                    "material_gap_floor": 5,
                    "max_partner_lineup_loss": 10,
                    "reject_received_asset_drop": True,
                },
            },
        )
        waiver = json.loads(WAIVER_FIXTURE.read_text(encoding="utf-8"))
        waiver["league_key"] = key
        waiver["validation_scope"]["league"] = key
        waiver_decision = self._write(policy_dir / "waiver-decision.json", waiver)
        waiver_wire = self._write(
            policy_dir / "waiver-wire.json",
            {
                "schema_version": 1,
                "product": "WAIVER ASSISTANT",
                "league_key": key,
                "scoring": "HALF",
                "position": "ALL",
                "maximum_age_hours": 24,
                "trusted_expert_ids": [],
            },
        )
        return {
            "draft_preferences": str(draft.relative_to(self.root)),
            "trade_decision": str(trade_decision.relative_to(self.root)),
            "trade_search": str(trade_search.relative_to(self.root)),
            "waiver_decision": str(waiver_decision.relative_to(self.root)),
            "waiver_wire": str(waiver_wire.relative_to(self.root)),
        }

    def _inputs(self):
        paths = {}
        for name in ("schedule", "expert_pool", "draft_board", "waiver_inputs"):
            path = self.root / f"{name}.synthetic"
            path.write_text("synthetic", encoding="utf-8")
            paths[f"{name}_path"] = path
        return paths

    def test_absent_and_invalid_config_are_diagnostic_success_without_leakage(self):
        missing = audit_setup(config_path=self.config)
        self.assertEqual(missing["checks"][0]["status"], "missing")
        self.assertEqual(missing["leagues"], [])
        self.assertTrue(missing["offline"])
        self.assertEqual(missing["provider_calls"], 0)
        self.assertNotIn(str(self.config), json.dumps(missing))

        self.config.write_text('{"owner": "secret-api-key",', encoding="utf-8")
        invalid = audit_setup(config_path=self.config)
        self.assertEqual(invalid["checks"][0]["status"], "invalid")
        self.assertNotIn("secret-api-key", json.dumps(invalid))

    def test_empty_leagues_and_bad_identity_have_clear_statuses(self):
        self._config([])
        empty = audit_setup(config_path=self.config)
        self.assertEqual(
            next(row for row in empty["checks"] if row["check"] == "league")["status"],
            "missing",
        )
        bad = self._league("league_alpha")
        bad["user_roster_id"] = "not-a-roster-number"
        bad["user_draft_slot"] = 0
        self._config([bad])
        report = audit_setup(config_path=self.config)
        checks = {row["check"]: row["status"] for row in report["leagues"][0]["checks"]}
        self.assertEqual(checks["identity"], "invalid")
        self.assertEqual(checks["draft_identity"], "invalid")

    def test_numeric_league_key_is_redacted_as_an_entry_number(self):
        self._config([self._league("123456789")])
        report = audit_setup(config_path=self.config)
        self.assertEqual(report["leagues"][0]["league"], "entry_1")
        self.assertNotIn("123456789", json.dumps(report))

    def test_two_leagues_are_separate_and_wrong_league_policy_is_uncalibrated(self):
        alpha = self._policy_files("league_alpha")
        beta = self._policy_files("league_beta")
        beta["waiver_decision"] = alpha["waiver_decision"]
        self._config([self._league("league_alpha", policies=alpha), self._league("league_beta", policies=beta)])
        report = audit_setup(config_path=self.config, **self._inputs())
        self.assertEqual([row["league"] for row in report["leagues"]], ["league_alpha", "league_beta"])
        first, second = report["leagues"]
        self.assertEqual(first["tracks"]["Waiver"]["data_only"], "ready")
        self.assertEqual(second["tracks"]["Waiver"]["data_only"], "ready")
        self.assertEqual(first["tracks"]["Waiver"]["decision"], "unavailable")
        self.assertEqual(second["tracks"]["Waiver"]["decision"], "uncalibrated")
        self.assertEqual(
            next(row for row in second["checks"] if row["check"] == "waiver_decision")["status"],
            "uncalibrated",
        )
        self.assertNotIn("private-owner-id", json.dumps(report))
        self.assertNotIn("private-league-id", json.dumps(report))

    def test_missing_policy_and_input_files_do_not_hide_data_only_readiness(self):
        self._config([self._league("league_alpha")])
        report = audit_setup(
            config_path=self.config,
            schedule_path=self.root / "missing-schedule.json",
            expert_pool_path=self.root / "missing-experts.csv",
        )
        league = report["leagues"][0]
        self.assertEqual(league["tracks"]["Waiver"]["data_only"], "ready")
        self.assertEqual(league["tracks"]["Waiver"]["decision"], "uncalibrated")
        self.assertEqual(league["tracks"]["Trade"]["data_only"], "missing")
        self.assertEqual(league["tracks"]["Draft"]["data_only"], "ready")
        self.assertIn("Next:", format_doctor(report))
        self.assertNotIn(str(self.root), format_doctor(report))

    def test_fully_configured_offline_example_passes_local_checks_only(self):
        policies = self._policy_files("league_alpha")
        self._config([self._league("league_alpha", policies=policies)])
        with patch("roster_theory.sleeper.SleeperClient", side_effect=AssertionError("provider called")), \
                patch("roster_theory.fantasypros.FantasyProsClient", side_effect=AssertionError("provider called")):
            report = audit_setup(config_path=self.config, **self._inputs())
        checks = report["leagues"][0]["checks"]
        self.assertTrue(all(row["status"] == "ready" for row in checks))
        self.assertTrue(all(row["data_only"] == "ready" for row in report["leagues"][0]["tracks"].values()))
        self.assertTrue(all(row["decision"] == "unavailable" for row in report["leagues"][0]["tracks"].values()))
        self.assertEqual(report["sleeper_writes"], 0)

    def test_cli_json_is_one_redacted_value_and_selected_league_is_scoped(self):
        alpha = self._policy_files("league_alpha")
        beta = self._policy_files("league_beta")
        self._config([self._league("league_alpha", policies=alpha), self._league("league_beta", policies=beta)])
        stream = io.StringIO()
        arguments = ["roster-theory", "--config", str(self.config), "doctor", "league_beta", "--json"]
        with patch("sys.argv", arguments), redirect_stdout(stream):
            cli.main()
        output = stream.getvalue()
        result = json.loads(output)
        self.assertEqual(len(result["leagues"]), 1)
        self.assertEqual(result["leagues"][0]["league"], "league_beta")
        for private in ("secret-api-key", "private-owner-id", "private-league-id", str(self.root)):
            self.assertNotIn(private, output)
        self.assertNotIn("[RT]", output)

    def test_human_board_separates_league_health_and_scopes_every_finding(self):
        self._config([self._league("league_alpha"), self._league("league_beta")])
        report = audit_setup(
            config_path=self.config,
            schedule_path=self.root / "missing-schedule.json",
            expert_pool_path=self.root / "missing-experts.csv",
        )

        output = format_doctor(report)

        self.assertIn("DOCTOR / OFFLINE / READ-ONLY", output)
        self.assertIn("Provider calls 0", output)
        self.assertIn("Sleeper writes 0", output)
        self.assertIn("LEAGUE HEALTH", output)
        self.assertIn("league_alpha / Trade / schedule", output)
        self.assertIn("league_beta / Waiver / waiver_inputs", output)
        self.assertIn("NEXT ON THE BOARD", output)
        self.assertIn("ready checks summarized", output)

    def test_details_shows_ready_checks_while_default_summarizes_them(self):
        policies = self._policy_files("league_alpha")
        self._config([self._league("league_alpha", policies=policies)])
        report = audit_setup(config_path=self.config, **self._inputs())

        concise = format_doctor(report)
        detailed = format_doctor(report, details=True)

        self.assertNotIn("league_alpha / Setup / identity [READY]", concise)
        self.assertIn("league_alpha / Setup / identity [READY]", detailed)
        self.assertIn("ALL CHECKS", detailed)
        self.assertNotIn("ready checks summarized", detailed)

    def test_cli_human_doctor_opens_with_full_name_hero_and_doctor_masthead(self):
        self._config([self._league("league_alpha")])
        stream = io.StringIO()
        capabilities = TerminalCapabilities(
            interactive=True,
            redirected=False,
            width=100,
            ansi_supported=False,
            color_enabled=False,
        )
        arguments = ["roster-theory", "--config", str(self.config), "doctor"]

        with patch("sys.argv", arguments), patch(
            "roster_theory.cli.detect_stdout", return_value=capabilities
        ), redirect_stdout(stream):
            cli.main()

        output = stream.getvalue()
        self.assertIn("FANTASY FOOTBALL ASSISTANT", output)
        self.assertIn("DRAFT  ◆  TRADE  ◆  WAIVER", output)
        self.assertGreaterEqual(output.count("█"), 200)
        self.assertIn("ROSTER THEORY / DOCTOR", output)
        self.assertEqual(output.count("ROSTER THEORY / DOCTOR"), 1)
        self.assertIn("DOCTOR / OFFLINE / READ-ONLY", output)


if __name__ == "__main__":
    unittest.main()
