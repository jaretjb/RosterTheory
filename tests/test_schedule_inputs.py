import json
import tempfile
import unittest
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from unittest.mock import patch

from roster_theory.cli import build_parser
from roster_theory.core.errors import ScheduleIncomplete, SourceUnavailable
from roster_theory.providers.nflverse import (
    EVIDENCE_SCHEMA,
    NflverseScheduleEvidence,
    fetch_nflverse_schedule,
)
from roster_theory.schedule_inputs import (
    NFL_TEAMS,
    inspect_schedule_input,
    normalize_schedule,
    prepare_schedule_input,
    validate_schedule_document,
)
from roster_theory.trade.service import refresh_trade_snapshot


NOW = datetime(2099, 5, 20, 12, tzinfo=timezone.utc)


def schedule_csv(*, duplicate=False, correction=False) -> str:
    rows = ["game_id,season,game_type,week,gameday,gametime,away_team,home_team"]
    pairs = [(NFL_TEAMS[index], NFL_TEAMS[index + 1]) for index in range(0, 32, 2)]
    for index, (away, home) in enumerate(pairs):
        week = 2 if index < 2 else 1
        if correction and index == 2:
            away, home = home, away
        rows.append(f"2099_{week}_{index},2099,REG,{week},2099-09-01,13:00,{away},{home}")
    if duplicate:
        rows.append(rows[-1].replace("2099_1_15", "duplicate"))
    rows.append("2099_post,2099,WC,19,2100-01-01,13:00,ARI,ATL")
    rows.append("2098_old,2098,REG,1,2098-09-01,13:00,ARI,ATL")
    return "\n".join(rows) + "\n"


def evidence(content: str | None = None) -> NflverseScheduleEvidence:
    content = content or schedule_csv()
    return NflverseScheduleEvidence(
        schema_version=EVIDENCE_SCHEMA,
        source="Synthetic authorized source",
        source_url="https://example.test/schedule",
        endpoint="https://example.test/schedule.csv",
        upstream_release="synthetic-release",
        upstream_asset="schedule.csv",
        captured_at=NOW.isoformat(),
        response_hash=sha256(content.encode()).hexdigest(),
        license="SYNTHETIC_FIXTURE",
        use_restriction="Tests only",
        content=content,
    )


def write_config(path: Path) -> None:
    path.write_text(
        json.dumps({"owner": {}, "leagues": [{"key": "league_alpha", "season": "2099"}]}),
        encoding="utf-8",
    )


class ScheduleInputTests(unittest.TestCase):
    def test_normalization_filters_other_seasons_and_postseason_and_derives_byes(self):
        document = normalize_schedule(evidence(), season=2099)
        self.assertEqual(document["schema_version"], "roster-theory.nfl-schedule/v1")
        self.assertEqual(document["weeks"], [1, 2])
        self.assertEqual(len(document["games"]), 16)
        self.assertTrue(all(game["game_type"] == "REG" for game in document["games"]))
        self.assertEqual(document["bye_weeks"]["ARI"], 1)
        self.assertEqual(document["bye_weeks"]["CAR"], 2)

    def test_validation_rejects_duplicate_impossible_and_season_mismatch(self):
        with self.assertRaisesRegex(ScheduleIncomplete, "more than once|duplicate"):
            normalize_schedule(evidence(schedule_csv(duplicate=True)), season=2099)
        document = normalize_schedule(evidence(), season=2099)
        broken = json.loads(json.dumps(document))
        broken["games"][0]["home_team"] = broken["games"][0]["away_team"]
        broken.pop("payload_hash")
        with self.assertRaisesRegex(ScheduleIncomplete, "impossible"):
            validate_schedule_document(broken, expected_season=2099)
        with self.assertRaisesRegex(ScheduleIncomplete, "does not match"):
            validate_schedule_document(document, expected_season=2098)

    def test_refresh_replay_and_correction_replace_the_artifact(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "leagues.json"
            output = root / "nested path" / "schedule.json"
            source_output = root / "nested path" / "evidence.json"
            write_config(config)
            first = prepare_schedule_input(
                "league_alpha",
                config_path=config,
                output_path=output,
                evidence_output_path=source_output,
                fetcher=lambda: evidence(),
            )
            self.assertEqual(first["status"], "ready")
            self.assertTrue(output.is_file())
            replay = prepare_schedule_input(
                "league_alpha",
                config_path=config,
                output_path=root / "replay.json",
                replay_path=source_output,
            )
            self.assertEqual(replay["operation"], "replay")
            corrected = prepare_schedule_input(
                "league_alpha",
                config_path=config,
                output_path=output,
                evidence_output_path=source_output,
                fetcher=lambda: evidence(schedule_csv(correction=True)),
            )
            self.assertNotEqual(first["response_hash"], corrected["response_hash"])
            self.assertEqual(inspect_schedule_input(
                "league_alpha", config_path=config, path=output
            )["status"], "ready")

    def test_import_requires_provenance_and_dry_run_writes_nothing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "leagues.json"
            imported = root / "authorized schedule.csv"
            output = root / "schedule.json"
            write_config(config)
            imported.write_text(schedule_csv(), encoding="utf-8")
            with self.assertRaisesRegex(ScheduleIncomplete, "--source"):
                prepare_schedule_input(
                    "league_alpha", config_path=config, import_path=imported
                )
            result = prepare_schedule_input(
                "league_alpha",
                config_path=config,
                import_path=imported,
                source="User authorized",
                source_url="https://example.test/authorized",
                license_name="SYNTHETIC_FIXTURE",
                captured_at=NOW.isoformat(),
                output_path=output,
                dry_run=True,
            )
            self.assertEqual(result["writes"], [])
            self.assertFalse(output.exists())
            self.assertFalse(result["sleeper_write_performed"])

    def test_provider_unavailability_is_typed(self):
        def unavailable(*_args, **_kwargs):
            raise OSError("offline")

        with self.assertRaises(SourceUnavailable):
            fetch_nflverse_schedule(opener=unavailable)

    def test_cli_exposes_all_schedule_operations(self):
        parser = build_parser()
        for operation in ("inspect", "validate", "refresh", "import"):
            args = ["inputs", "schedule", operation, "league_alpha"]
            if operation == "import":
                args.extend([
                    "--input", "C:\\input path\\schedule.csv",
                    "--source", "authorized",
                    "--source-url", "https://example.test",
                    "--license", "local",
                    "--captured-at", NOW.isoformat(),
                ])
            parsed = parser.parse_args(args)
            self.assertEqual(parsed.schedule_input_command, operation)

    def test_trade_refresh_resolves_schedule_from_configured_season(self):
        with (
            patch(
                "roster_theory.trade.service.find_league_config",
                return_value={"league_id": "league-1", "season": "2099"},
            ),
            patch(
                "roster_theory.trade.service.load_owner_config",
                return_value={"sleeper_user_id": "user-1"},
            ),
            patch(
                "roster_theory.trade.service.load_schedule",
                side_effect=ScheduleIncomplete("stop after path resolution"),
            ) as loader,
        ):
            with self.assertRaisesRegex(ScheduleIncomplete, "path resolution"):
                refresh_trade_snapshot("league_alpha")
        loader.assert_called_once_with(
            Path("data/cache/nflverse/2099/schedule.json"), expected_season=2099
        )


if __name__ == "__main__":
    unittest.main()
