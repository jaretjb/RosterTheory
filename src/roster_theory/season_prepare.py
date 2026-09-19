"""Plan and prepare season inputs without crossing league authority boundaries."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from roster_theory.doctor import audit_setup
from roster_theory.expert_inputs import (
    default_expert_input_paths,
    inspect_expert_inputs,
    refresh_expert_inputs,
)
from roster_theory.private_setup import (
    inspect_private_setup,
    migrate_legacy_trade_policy_metadata,
    migrate_legacy_waiver_policy_metadata,
)
from roster_theory.schedule_inputs import inspect_schedule_input, prepare_schedule_input
from roster_theory.sleeper import load_league_config


SCHEMA_VERSION = "roster-theory.season-preparation/v1"
ASSISTANTS = ("draft", "trade", "waiver", "all")
REFRESH_MODES = ("auto", "force")
_MODE_ARTIFACTS = {
    "draft": ("draft-preferences",),
    "trade": ("trade-decision", "trade-search"),
    "waiver": ("waiver-decision", "waiver-wire"),
    "all": (
        "draft-preferences", "trade-decision", "trade-search",
        "waiver-decision", "waiver-wire",
    ),
}


def _utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _stale(path: Path, hours: float, now: datetime) -> bool:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return now - _utc(str(value["captured_at"])) > timedelta(hours=hours)
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return True


def _selected_leagues(
    league: str | None, *, all_leagues: bool, config_path: str | Path | None
) -> list[dict[str, Any]]:
    configured = load_league_config(config_path)
    if all_leagues:
        if league:
            raise ValueError("Choose a league or --all-leagues, not both")
        if not configured:
            raise ValueError("No leagues are configured")
        return configured
    if not league:
        raise ValueError("A league is required unless --all-leagues is used")
    selected = [row for row in configured if row.get("key") == league]
    if not selected:
        raise KeyError(f"Unknown league key: {league}")
    return selected


def _expert_kind(assistant: str) -> str | None:
    if assistant == "draft":
        return "draft-accuracy"
    if assistant in {"trade", "waiver"}:
        return "inseason-pool"
    if assistant == "all":
        return "all"
    return None


def _schedule_paths(data_dir: str | Path, season: int) -> tuple[Path, Path]:
    root = Path(data_dir) / "cache" / "nflverse" / str(season)
    return root / "schedule.json", root / "schedule_source.json"


def inspect_season_inputs(
    league: str | None = None,
    *,
    all_leagues: bool = False,
    assistant: str = "all",
    config_path: str | Path | None = None,
    data_dir: str | Path = "data",
    now: datetime | None = None,
    expert_freshness_hours: float = 48.0,
    schedule_freshness_hours: float = 24.0,
    include_experts: bool = True,
) -> dict[str, Any]:
    """Inspect preparation inputs offline and return exact recovery commands."""

    if assistant not in ASSISTANTS:
        raise ValueError(f"Unsupported assistant: {assistant}")
    captured = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    selected = _selected_leagues(league, all_leagues=all_leagues, config_path=config_path)
    reports: list[dict[str, Any]] = []
    for configured in selected:
        key, season = str(configured["key"]), int(configured["season"])
        artifacts: list[dict[str, Any]] = []
        kind = _expert_kind(assistant) if include_experts else None
        if kind:
            expert = inspect_expert_inputs(
                key, config_path=config_path, artifact=kind, data_dir=data_dir
            )
            expert_status = expert["status"]
            expert_reason = (
                "complete and valid" if expert_status == "ready" else
                "; ".join(str(row.get("reason") or "incomplete") for row in expert.get("errors", []))
            )
            if kind in {"inseason-pool", "all"} and expert_status == "ready":
                audit_path = default_expert_input_paths(key, season, data_dir=data_dir).audit
                if _stale(audit_path, expert_freshness_hours, captured):
                    expert_status, expert_reason = "stale", "in-season expert evidence exceeded its freshness window"
            artifacts.append({
                "artifact": f"experts.{kind}", "status": expert_status,
                "authority": "provider/derived",
                "scope": "shared" if kind == "draft-accuracy" else "shared_source/league_derived",
                "horizon": "preseason" if kind == "draft-accuracy" else "ROS",
                "reason": expert_reason,
                "next_command": f"roster-theory inputs prepare {key} --assistant {assistant}",
            })
        schedule_path, _ = _schedule_paths(data_dir, season)
        if assistant in {"trade", "all"}:
            schedule = inspect_schedule_input(
                key, config_path=config_path, path=schedule_path
            )
            schedule_status = schedule["status"]
            reason = str(schedule.get("reason") or "complete and valid")
            if schedule_status == "ready" and _stale(schedule_path, schedule_freshness_hours, captured):
                schedule_status, reason = "stale", "schedule release evidence exceeded its freshness window"
            artifacts.append({
                "artifact": "schedule", "status": schedule_status,
                "authority": "provider_fact", "scope": f"season:{season}",
                "horizon": str(season), "reason": reason,
                "next_command": f"roster-theory inputs prepare {key} --assistant {assistant}",
            })
        private = inspect_private_setup(
            operation="season-status", config_path=config_path, league_key=key
        )
        private_rows = private.get("leagues", [{}])[0].get("artifacts", [])
        required_private = set(_MODE_ARTIFACTS[assistant])
        for row in private_rows:
            if row.get("artifact") not in required_private:
                continue
            artifacts.append({
                **row, "authority": "human_decision", "scope": "league",
                "horizon": str(season),
                "next_command": f"roster-theory setup scaffold {key} --artifact {row['artifact']} --update-config",
            })
        if assistant in {"draft", "all"}:
            rankings = Path(data_dir) / "exports" / f"fantasypros_{season}" / "weighted_rankings.csv"
            artifacts.append({
                "artifact": "draft_rankings", "status": "ready" if rankings.is_file() else "missing",
                "authority": "derived_fact", "scope": "season", "horizon": "preseason",
                "path": str(rankings), "reason": "current weighted rankings exist" if rankings.is_file() else "current weighted rankings are absent",
                "next_command": f"roster-theory fantasypros-grouped-rankings --season {season} --accuracy \"{default_expert_input_paths(key, season, data_dir=data_dir).draft_category}\" --annual-accuracy \"{default_expert_input_paths(key, season, data_dir=data_dir).draft_annual}\" --output-dir \"{rankings.parent}\"",
            })
            board = Path(data_dir) / "exports" / f"league_boards_{season}" / f"{key}_board.csv"
            metadata = board.with_name(f"{key}_metadata.json")
            board_ready = board.is_file() and metadata.is_file()
            board_status = "ready" if board_ready else "missing"
            board_reason = "current league board exists" if board_ready else "current league board or metadata is absent"
            if board_ready:
                try:
                    board_metadata = json.loads(metadata.read_text(encoding="utf-8"))
                    if not bool(board_metadata.get("draft_ready")):
                        board_status, board_reason = "partial", "league board completeness gates did not pass"
                    elif captured - _utc(str(board_metadata["generated_at"])) > timedelta(hours=24):
                        board_status, board_reason = "stale", "league board exceeded its freshness window"
                except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
                    board_status, board_reason = "invalid", "league board metadata cannot be validated"
            artifacts.append({
                "artifact": "draft_board", "status": board_status,
                "authority": "derived_fact", "scope": "league", "horizon": "preseason",
                "path": str(board), "reason": board_reason,
                "next_command": f"roster-theory fantasypros-league-boards --season {season} --league {key} --rankings \"{rankings}\" --output-dir \"{board.parent}\"",
            })
        if assistant in {"waiver", "all"}:
            waiver = Path(data_dir) / "cache" / "waiver" / f"{key}_live_inputs.json"
            waiver_status = "ready" if waiver.is_file() else "missing"
            waiver_reason = "current Waiver bundle exists" if waiver.is_file() else "current Waiver input bundle is absent"
            if waiver.is_file() and _stale(waiver, 5.0 / 60.0, captured):
                waiver_status, waiver_reason = (
                    "stale",
                    "Waiver input bundle exceeded its five-minute freshness window",
                )
            artifacts.append({
                "artifact": "waiver_inputs", "status": waiver_status,
                "authority": "derived_fact", "scope": "league", "horizon": "weekly/ROS",
                "path": str(waiver), "reason": waiver_reason,
                "next_command": f"roster-theory waiver inputs {key} --output \"{waiver}\"",
            })
        reports.append({
            "league": key, "season": season,
            "status": "ready" if all(row["status"] in {"ready", "optional"} for row in artifacts) else "attention_required",
            "artifacts": artifacts,
        })
    return {
        "schema_version": SCHEMA_VERSION, "operation": "status",
        "status": "ready" if all(row["status"] == "ready" for row in reports) else "attention_required",
        "assistant": assistant, "offline": True, "dry_run": False,
        "provider_calls": [], "writes": [], "leagues": reports,
        "recommendation_generated": False, "sleeper_write_performed": False,
    }


def _plan(status: Mapping[str, Any], refresh: str, data_dir: str | Path) -> list[dict[str, Any]]:
    operations: list[dict[str, Any]] = []
    seen_schedule: set[int] = set()
    seen_draft: set[int] = set()
    first_inseason: dict[int, str] = {}
    for report in status["leagues"]:
        key, season = str(report["league"]), int(report["season"])
        by_name = {row["artifact"]: row for row in report["artifacts"]}
        for name, row in by_name.items():
            if name == "schedule" and (refresh == "force" or row["status"] != "ready"):
                if season not in seen_schedule:
                    schedule_path, evidence_path = _schedule_paths(data_dir, season)
                    operations.append({
                        "kind": "schedule", "league": key, "season": season,
                        "mode": "provider", "provider_calls": 1,
                        "writes": [str(evidence_path), str(schedule_path)],
                    })
                    seen_schedule.add(season)
            elif name.startswith("experts.") and (refresh == "force" or row["status"] != "ready"):
                artifact = name.split(".", 1)[1]
                if artifact in {"draft-accuracy", "all"} and season not in seen_draft:
                    paths = default_expert_input_paths(key, season, data_dir=data_dir)
                    operations.append({
                        "kind": "experts", "artifact": "draft-accuracy",
                        "league": key, "season": season, "mode": "provider",
                        "provider_calls": 5,
                        "writes": [str(paths.draft_category), str(paths.draft_annual), str(paths.evidence_dir), str(paths.budget)],
                    })
                    seen_draft.add(season)
                if artifact in {"inseason-pool", "all"}:
                    if season in first_inseason:
                        paths = default_expert_input_paths(key, season, data_dir=data_dir)
                        operations.append({
                            "kind": "experts", "artifact": "inseason-pool",
                            "league": key, "season": season, "mode": "replay",
                            "replay_from": first_inseason[season], "provider_calls": 0,
                            "writes": [str(paths.inseason_accuracy), str(paths.inseason_pool), str(paths.audit)],
                        })
                    else:
                        paths = default_expert_input_paths(key, season, data_dir=data_dir)
                        reuse_historical = (
                            refresh == "auto" and paths.inseason_accuracy.is_file()
                        )
                        operations.append({
                            "kind": "experts", "artifact": "inseason-pool",
                            "league": key, "season": season, "mode": "provider",
                            "provider_calls": 1 if reuse_historical else 6,
                            "reuse_historical": reuse_historical,
                            "writes": [str(paths.inseason_accuracy), str(paths.inseason_pool), str(paths.audit), str(paths.evidence_dir), str(paths.budget)],
                        })
                        first_inseason[season] = key
    return operations


def prepare_season_inputs(
    league: str | None = None,
    *,
    all_leagues: bool = False,
    assistant: str = "all",
    config_path: str | Path | None = None,
    data_dir: str | Path = "data",
    refresh: str = "auto",
    offline: bool = False,
    dry_run: bool = False,
    now: datetime | None = None,
    expert_refresh: Callable[..., dict[str, Any]] = refresh_expert_inputs,
    schedule_refresh: Callable[..., dict[str, Any]] = prepare_schedule_input,
    trade_policy_migrate: Callable[..., dict[str, Any]] = migrate_legacy_trade_policy_metadata,
    waiver_policy_migrate: Callable[..., dict[str, Any]] = migrate_legacy_waiver_policy_metadata,
    include_experts: bool = True,
) -> dict[str, Any]:
    """Prepare only stale or missing provider facts; keep human policy explicit."""

    if refresh not in REFRESH_MODES:
        raise ValueError(f"Unsupported refresh mode: {refresh}")
    migrations: list[dict[str, Any]] = []
    if assistant in {"trade", "all"}:
        for selected in _selected_leagues(
            league, all_leagues=all_leagues, config_path=config_path
        ):
            migrations.append(
                trade_policy_migrate(
                    str(selected["key"]), config_path=config_path, dry_run=dry_run
                )
            )
    if assistant in {"waiver", "all"}:
        for selected in _selected_leagues(
            league, all_leagues=all_leagues, config_path=config_path
        ):
            migrations.append(
                waiver_policy_migrate(
                    str(selected["key"]), config_path=config_path, dry_run=dry_run
                )
            )
    before = inspect_season_inputs(
        league, all_leagues=all_leagues, assistant=assistant,
        config_path=config_path, data_dir=data_dir, now=now,
        include_experts=include_experts,
    )
    operations = _plan(before, refresh, data_dir)
    for operation in operations:
        operation["status"] = "blocked_offline" if offline else "planned"
    if dry_run or offline:
        after = before
        errors = ([{
            "type": "OfflineRefreshRequired", "reason": "Provider refresh is required but --offline forbids network calls.",
            "next_command": f"roster-theory inputs prepare {operations[0]['league']} --assistant {assistant}",
        }] if offline and operations else [])
    else:
        errors: list[dict[str, Any]] = []
        for operation in operations:
            key, season = operation["league"], operation["season"]
            try:
                if operation["kind"] == "schedule":
                    schedule_path, evidence_path = _schedule_paths(data_dir, season)
                    schedule_refresh(
                        key, config_path=config_path, output_path=schedule_path,
                        evidence_output_path=evidence_path,
                    )
                else:
                    replay_dir = None
                    if operation["mode"] == "replay":
                        replay_dir = default_expert_input_paths(
                            operation["replay_from"], season, data_dir=data_dir
                        ).evidence_dir
                    expert_refresh(
                        key, config_path=config_path, artifact=operation["artifact"],
                        data_dir=data_dir, replay_dir=replay_dir, now=now,
                        reuse_historical=bool(operation.get("reuse_historical")),
                    )
                operation["status"] = "completed"
            except Exception as exc:  # Preserve completed work so rerun can resume.
                operation["status"] = "failed"
                operation["reason"] = str(exc)
                errors.append({
                    "type": type(exc).__name__, "league": key,
                    "reason": str(exc),
                    "next_command": f"roster-theory inputs prepare {key} --assistant {assistant}",
                })
        after = inspect_season_inputs(
            league, all_leagues=all_leagues, assistant=assistant,
            config_path=config_path, data_dir=data_dir, now=now,
            include_experts=include_experts,
        )
    doctor = audit_setup(config_path=config_path, league_key=league if not all_leagues else None)
    return {
        **after, "operation": "prepare", "dry_run": dry_run,
        "offline": offline, "refresh": refresh, "preflight": operations,
        "policy_migrations": migrations,
        "provider_calls": sum(int(row["provider_calls"]) for row in operations if not offline),
        "errors": errors, "doctor": doctor,
        "status": (
            "planned" if dry_run else
            "blocked" if errors else
            after["status"]
        ),
    }
