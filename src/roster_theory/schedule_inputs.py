from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from roster_theory.core.errors import ScheduleIncomplete
from roster_theory.core.provenance import stable_hash
from roster_theory.providers.nflverse import (
    NflverseScheduleEvidence,
    fetch_nflverse_schedule,
    import_schedule_csv,
    load_schedule_evidence,
    save_schedule_evidence,
)
from roster_theory.sleeper import find_league_config


SCHEMA_VERSION = "roster-theory.nfl-schedule/v1"
RESULT_SCHEMA = "roster-theory.inputs/v1"
TRANSFORMATION_VERSION = "os-016-v1"
NFL_TEAMS = (
    "ARI", "ATL", "BAL", "BUF", "CAR", "CHI", "CIN", "CLE",
    "DAL", "DEN", "DET", "GB", "HOU", "IND", "JAX", "KC",
    "LAC", "LAR", "LV", "MIA", "MIN", "NE", "NO", "NYG",
    "NYJ", "PHI", "PIT", "SEA", "SF", "TB", "TEN", "WAS",
)
TEAM_ALIASES = {"JAC": "JAX", "LA": "LAR", "OAK": "LV", "SD": "LAC", "STL": "LAR"}


def default_schedule_path(season: int) -> Path:
    return Path("data/cache/nflverse") / str(season) / "schedule.json"


def default_evidence_path(season: int) -> Path:
    return Path("data/cache/nflverse") / str(season) / "schedule_source.json"


def _team(value: Any) -> str:
    team = str(value or "").strip().upper()
    return TEAM_ALIASES.get(team, team)


def _require_timestamp(value: str, field: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ScheduleIncomplete(f"Schedule {field} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def normalize_schedule(
    evidence: NflverseScheduleEvidence,
    *,
    season: int,
) -> dict[str, Any]:
    """Transform provider-shaped CSV evidence into the schedule contract."""

    reader = csv.DictReader(io.StringIO(evidence.content.lstrip("\ufeff")))
    required = {"season", "game_type", "week", "away_team", "home_team"}
    if not reader.fieldnames or not required.issubset(reader.fieldnames):
        missing = sorted(required.difference(reader.fieldnames or ()))
        raise ScheduleIncomplete(f"Schedule CSV is missing columns: {', '.join(missing)}")
    games: list[dict[str, Any]] = []
    selected_season_rows = 0
    for row_number, row in enumerate(reader, start=2):
        try:
            row_season = int(str(row.get("season") or ""))
        except ValueError as exc:
            raise ScheduleIncomplete(f"Invalid season at CSV row {row_number}") from exc
        if row_season != season:
            continue
        selected_season_rows += 1
        game_type = str(row.get("game_type") or "").strip().upper()
        if game_type != "REG":
            continue
        try:
            week = int(str(row.get("week") or ""))
        except ValueError as exc:
            raise ScheduleIncomplete(f"Invalid week at CSV row {row_number}") from exc
        games.append(
            {
                "game_id": str(row.get("game_id") or f"{season}_{week}_{row_number}"),
                "season": season,
                "game_type": "REG",
                "week": week,
                "away_team": _team(row.get("away_team")),
                "home_team": _team(row.get("home_team")),
                "gameday": str(row.get("gameday") or ""),
                "gametime": str(row.get("gametime") or ""),
            }
        )
    if not selected_season_rows:
        raise ScheduleIncomplete(f"Schedule source has no rows for season {season}")
    captured_at = _require_timestamp(evidence.captured_at, "captured_at")
    value: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "season": season,
        "weeks": sorted({game["week"] for game in games}),
        "teams": list(NFL_TEAMS),
        "games": sorted(games, key=lambda game: (game["week"], game["game_id"])),
        "bye_weeks": {},
        "source": evidence.source,
        "source_url": evidence.source_url,
        "endpoint": evidence.endpoint,
        "upstream_release": evidence.upstream_release,
        "upstream_asset": evidence.upstream_asset,
        "captured_at": captured_at,
        "verified_at": captured_at,
        "response_hash": evidence.response_hash,
        "license": evidence.license,
        "use_restriction": evidence.use_restriction,
        "attribution": (
            f"Schedule data from {evidence.source}; transformed by RosterTheory. "
            "No nflverse, NFL, or club endorsement is implied."
        ),
        "transformation_version": TRANSFORMATION_VERSION,
    }
    appearances: dict[tuple[str, int], int] = {}
    for game in games:
        for team in (game["away_team"], game["home_team"]):
            appearances[(team, game["week"])] = appearances.get((team, game["week"]), 0) + 1
    value["bye_weeks"] = {
        team: missing[0]
        for team in NFL_TEAMS
        if len(missing := [week for week in value["weeks"] if not appearances.get((team, week))]) == 1
    }
    validate_schedule_document(value, expected_season=season)
    value["payload_hash"] = stable_hash({key: child for key, child in value.items() if key != "payload_hash"})
    return value


def validate_schedule_document(
    value: Mapping[str, Any], *, expected_season: int | None = None
) -> dict[str, Any]:
    if value.get("schema_version") != SCHEMA_VERSION:
        raise ScheduleIncomplete(f"Schedule schema must be {SCHEMA_VERSION}")
    try:
        season = int(value["season"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ScheduleIncomplete("Schedule season is missing or invalid") from exc
    if expected_season is not None and season != expected_season:
        raise ScheduleIncomplete(
            f"Schedule season {season} does not match requested season {expected_season}"
        )
    teams = tuple(sorted(_team(item) for item in value.get("teams") or ()))
    if teams != tuple(sorted(NFL_TEAMS)):
        raise ScheduleIncomplete("Schedule must contain exactly the current 32 NFL teams")
    weeks = tuple(sorted(int(item) for item in value.get("weeks") or ()))
    if not weeks or weeks != tuple(range(weeks[0], weeks[-1] + 1)) or weeks[0] != 1:
        raise ScheduleIncomplete("Regular-season weeks must be contiguous and begin at week 1")
    synthetic = str(value.get("license") or "") == "SYNTHETIC_FIXTURE"
    expected_weeks = tuple(range(1, 19 if season >= 2021 else 18))
    if not synthetic and weeks != expected_weeks:
        raise ScheduleIncomplete(
            f"Season {season} must contain regular-season weeks "
            f"1-{expected_weeks[-1]}; found {list(weeks)}"
        )
    games = value.get("games")
    if not isinstance(games, list) or not games:
        raise ScheduleIncomplete("Schedule games are missing")
    seen_ids: set[str] = set()
    appearances: dict[tuple[str, int], int] = {}
    pairings: set[tuple[int, str, str]] = set()
    for index, game in enumerate(games, start=1):
        if not isinstance(game, Mapping):
            raise ScheduleIncomplete(f"Schedule game {index} is not an object")
        if int(game.get("season") or season) != season:
            raise ScheduleIncomplete("Schedule contains a game from another season")
        if str(game.get("game_type") or "").upper() != "REG":
            raise ScheduleIncomplete("Schedule contains postseason or non-regular-season games")
        week = int(game.get("week") or 0)
        away, home = _team(game.get("away_team")), _team(game.get("home_team"))
        game_id = str(game.get("game_id") or "")
        if week not in weeks or away not in NFL_TEAMS or home not in NFL_TEAMS or away == home:
            raise ScheduleIncomplete(f"Schedule game {index} has an impossible pairing")
        if not game_id or game_id in seen_ids:
            raise ScheduleIncomplete("Schedule contains a duplicate or missing game_id")
        pairing = (week, *sorted((away, home)))
        if pairing in pairings:
            raise ScheduleIncomplete("Schedule contains a duplicate weekly pairing")
        seen_ids.add(game_id)
        pairings.add(pairing)
        for team in (away, home):
            key = (team, week)
            appearances[key] = appearances.get(key, 0) + 1
            if appearances[key] > 1:
                raise ScheduleIncomplete(f"{team} appears more than once in week {week}")
    derived_byes: dict[str, int] = {}
    for team in NFL_TEAMS:
        missing = [week for week in weeks if not appearances.get((team, week))]
        if len(missing) != 1:
            raise ScheduleIncomplete(f"{team} must have exactly one bye; found {len(missing)}")
        derived_byes[team] = missing[0]
    declared = {_team(team): int(week) for team, week in (value.get("bye_weeks") or {}).items()}
    if declared != derived_byes:
        raise ScheduleIncomplete("Declared bye weeks do not match the game schedule")
    for field in (
        "source", "source_url", "endpoint", "upstream_release", "upstream_asset",
        "response_hash", "license", "use_restriction", "attribution",
        "transformation_version",
    ):
        if not str(value.get(field) or "").strip():
            raise ScheduleIncomplete(f"Schedule provenance is missing {field}")
    captured_at = _require_timestamp(str(value.get("captured_at") or ""), "captured_at")
    expected_hash = stable_hash({key: child for key, child in value.items() if key != "payload_hash"})
    if value.get("payload_hash") and value["payload_hash"] != expected_hash:
        raise ScheduleIncomplete("Schedule payload hash does not match its contents")
    return {
        "season": season,
        "weeks": len(weeks),
        "games": len(games),
        "teams": len(teams),
        "captured_at": captured_at,
        "payload_hash": expected_hash,
    }


def write_schedule(value: Mapping[str, Any], path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target


def prepare_schedule_input(
    league_key: str,
    *,
    config_path: str | Path | None = None,
    season: int | None = None,
    output_path: str | Path | None = None,
    evidence_output_path: str | Path | None = None,
    replay_path: str | Path | None = None,
    import_path: str | Path | None = None,
    source: str | None = None,
    source_url: str | None = None,
    license_name: str | None = None,
    captured_at: str | None = None,
    use_restriction: str | None = None,
    dry_run: bool = False,
    fetcher: Any = fetch_nflverse_schedule,
) -> dict[str, Any]:
    league = find_league_config(league_key, config_path)
    configured_season = int(league["season"])
    selected_season = season or configured_season
    if selected_season != configured_season:
        raise ScheduleIncomplete(
            f"Requested season {selected_season} does not match {league_key} season {configured_season}"
        )
    target = Path(output_path) if output_path else default_schedule_path(selected_season)
    evidence_target = (
        Path(evidence_output_path) if evidence_output_path else default_evidence_path(selected_season)
    )
    if replay_path:
        evidence = load_schedule_evidence(replay_path)
        mode = "replay"
    elif import_path:
        missing = [
            name for name, value in (
                ("--source", source), ("--source-url", source_url),
                ("--license", license_name), ("--captured-at", captured_at),
            ) if not value
        ]
        if missing:
            raise ScheduleIncomplete(f"Schedule import requires {', '.join(missing)}")
        evidence = import_schedule_csv(
            import_path,
            source=str(source),
            source_url=str(source_url),
            license_name=str(license_name),
            captured_at=str(captured_at),
            use_restriction=use_restriction or "User-authorized local source; redistribution not assumed.",
        )
        mode = "import"
    else:
        evidence = fetcher()
        mode = "refresh"
    document = normalize_schedule(evidence, season=selected_season)
    validation = validate_schedule_document(document, expected_season=selected_season)
    if not dry_run:
        save_schedule_evidence(evidence, evidence_target)
        write_schedule(document, target)
    return {
        "schema_version": RESULT_SCHEMA,
        "operation": mode,
        "status": "ready",
        "league": league_key,
        "season": selected_season,
        "source": evidence.source,
        "source_url": evidence.source_url,
        "endpoint": evidence.endpoint,
        "upstream_release": evidence.upstream_release,
        "upstream_asset": evidence.upstream_asset,
        "captured_at": evidence.captured_at,
        "response_hash": evidence.response_hash,
        "license": evidence.license,
        "use_restriction": evidence.use_restriction,
        "validation": validation,
        "schedule_path": str(target),
        "evidence_path": str(evidence_target),
        "writes": [] if dry_run else [str(evidence_target), str(target)],
        "dry_run": dry_run,
        "sleeper_write_performed": False,
    }


def inspect_schedule_input(
    league_key: str,
    *,
    config_path: str | Path | None = None,
    season: int | None = None,
    path: str | Path | None = None,
) -> dict[str, Any]:
    league = find_league_config(league_key, config_path)
    configured_season = int(league["season"])
    selected_season = season or configured_season
    if selected_season != configured_season:
        raise ScheduleIncomplete(
            f"Requested season {selected_season} does not match {league_key} season {configured_season}"
        )
    target = Path(path) if path else default_schedule_path(selected_season)
    if not target.is_file():
        return {
            "schema_version": RESULT_SCHEMA,
            "operation": "inspect",
            "status": "missing",
            "league": league_key,
            "season": selected_season,
            "schedule_path": str(target),
            "reason": "Schedule artifact does not exist",
            "next_command": f"roster-theory inputs schedule refresh {league_key}",
            "sleeper_write_performed": False,
        }
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
        validation = validate_schedule_document(value, expected_season=selected_season)
    except (OSError, ValueError, TypeError, json.JSONDecodeError, ScheduleIncomplete) as exc:
        return {
            "schema_version": RESULT_SCHEMA,
            "operation": "inspect",
            "status": "invalid",
            "league": league_key,
            "season": selected_season,
            "schedule_path": str(target),
            "reason": str(exc),
            "next_command": f"roster-theory inputs schedule refresh {league_key}",
            "sleeper_write_performed": False,
        }
    return {
        "schema_version": RESULT_SCHEMA,
        "operation": "inspect",
        "status": "ready",
        "league": league_key,
        "season": selected_season,
        "schedule_path": str(target),
        "source": value["source"],
        "source_url": value["source_url"],
        "endpoint": value["endpoint"],
        "upstream_release": value["upstream_release"],
        "upstream_asset": value["upstream_asset"],
        "captured_at": value["captured_at"],
        "response_hash": value["response_hash"],
        "license": value["license"],
        "use_restriction": value["use_restriction"],
        "validation": validation,
        "sleeper_write_performed": False,
    }
