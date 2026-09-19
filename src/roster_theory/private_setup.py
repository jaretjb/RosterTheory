from __future__ import annotations

import csv
import io
import json
import os
import re
import shutil
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from roster_theory.sleeper import find_league_config, resolve_league_config_path


RESULT_SCHEMA = "roster-theory.setup/v1"
SAFE_KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*")
ARTIFACTS = (
    "expert-overrides",
    "identity-overrides",
    "draft-preferences",
    "trade-decision",
    "trade-search",
    "waiver-decision",
    "waiver-wire",
    "contingencies",
)
POLICY_KEYS = {
    "draft-preferences": "draft_preferences",
    "trade-decision": "trade_decision",
    "trade-search": "trade_search",
    "waiver-decision": "waiver_decision",
    "waiver-wire": "waiver_wire",
}
FILENAMES = {
    "expert-overrides": "expert-overrides.csv",
    "identity-overrides": "identity-overrides.csv",
    "draft-preferences": "draft-preferences.csv",
    "trade-decision": "trade-decision.json",
    "trade-search": "trade-search.json",
    "waiver-decision": "waiver-decision.json",
    "waiver-wire": "waiver-wire.json",
    "contingencies": "contingencies.json",
}
EXPERT_OVERRIDE_FIELDS = (
    "scope", "expert_name", "action", "value", "reason", "evidence_date", "source"
)
IDENTITY_OVERRIDE_FIELDS = (
    "scope", "fantasypros_id", "sleeper_id", "player_name", "team", "position",
    "evidence", "action", "reason", "evidence_date", "source",
)
DRAFT_PREFERENCE_FIELDS = (
    "player_name", "position", "stance", "category", "take_at_or_after",
    "condition", "linked_player", "source", "league_scope", "reason",
    "evidence_date", "status",
)
DRAFT_PREFERENCE_REQUIRED_FIELDS = DRAFT_PREFERENCE_FIELDS[:9]


def _config_value(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or not isinstance(value.get("owner"), dict):
        raise ValueError("League configuration must contain an owner object")
    if not isinstance(value.get("leagues"), list):
        raise ValueError("League configuration must contain a leagues array")
    keys: list[str] = []
    for league in value["leagues"]:
        if not isinstance(league, dict):
            raise ValueError("Each leagues entry must be an object")
        key = str(league.get("key") or "")
        if not SAFE_KEY.fullmatch(key):
            raise ValueError(f"Unsafe or missing league key: {key!r}")
        if key in keys:
            raise ValueError(f"Duplicate league key: {key}")
        keys.append(key)
        season = str(league.get("season") or "")
        if not re.fullmatch(r"\d{4}", season):
            raise ValueError(f"League {key} requires a four-digit season")
        policies = league.get("policies", {})
        if not isinstance(policies, dict):
            raise ValueError(f"League {key} policies must be an object")
    return value


def _backup_path(path: Path) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    candidate = path.with_name(f"{path.name}.bak.{stamp}")
    counter = 1
    while candidate.exists():
        candidate = path.with_name(f"{path.name}.bak.{stamp}.{counter}")
        counter += 1
    return candidate


def _atomic_write(
    path: Path,
    content: str,
    *,
    allow_existing: bool,
    dry_run: bool,
) -> tuple[Path, Path | None]:
    if path.exists() and not allow_existing:
        raise FileExistsError(
            f"Refusing to replace existing private file: {path}. "
            "Use the command's explicit update or replace option."
        )
    backup = _backup_path(path) if path.exists() else None
    if dry_run:
        return path, backup
    path.parent.mkdir(parents=True, exist_ok=True)
    if backup is not None:
        shutil.copy2(path, backup)
    temp_name = ""
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            delete=False,
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
        ) as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
            temp_name = handle.name
        os.replace(temp_name, path)
    finally:
        if temp_name and Path(temp_name).exists():
            Path(temp_name).unlink()
    return path, backup


def _json_text(value: Mapping[str, Any]) -> str:
    return json.dumps(value, indent=2, sort_keys=True) + "\n"


def _csv_text(fields: Sequence[str], rows: Sequence[Mapping[str, Any]] = ()) -> str:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()


def _result(
    operation: str,
    *,
    status: str = "ready",
    writes: Sequence[Path] = (),
    backups: Sequence[Path | None] = (),
    dry_run: bool = False,
    **extra: Any,
) -> dict[str, Any]:
    return {
        "schema_version": RESULT_SCHEMA,
        "operation": operation,
        "status": status,
        "writes": [str(path) for path in writes],
        "backups": [str(path) for path in backups if path is not None],
        "dry_run": dry_run,
        "sleeper_write_performed": False,
        **extra,
    }


def initialize_private_runtime(
    *, config_path: str | Path | None = None, replace: bool = False, dry_run: bool = False
) -> dict[str, Any]:
    target = resolve_league_config_path(config_path)
    value = {"schema_version": 1, "owner": {}, "leagues": []}
    written, backup = _atomic_write(
        target, _json_text(value), allow_existing=replace, dry_run=dry_run
    )
    return _result(
        "init", writes=(written,), backups=(backup,), dry_run=dry_run,
        config_path=str(target),
        next_command=(
            "roster-theory setup owner --sleeper-username NAME "
            "--sleeper-user-id ID --update"
        ),
    )


def import_private_runtime(
    input_path: str | Path,
    *,
    config_path: str | Path | None = None,
    replace: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    source = Path(input_path)
    value = _config_value(source)
    target = resolve_league_config_path(config_path)
    written, backup = _atomic_write(
        target, _json_text(value), allow_existing=replace, dry_run=dry_run
    )
    return _result(
        "import", writes=(written,), backups=(backup,), dry_run=dry_run,
        config_path=str(target), league_count=len(value["leagues"]),
    )


def set_owner(
    *,
    sleeper_username: str,
    sleeper_user_id: str,
    config_path: str | Path | None = None,
    update: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    target = resolve_league_config_path(config_path)
    value = _config_value(target)
    if not update:
        raise FileExistsError("Updating leagues.json requires the explicit --update option")
    value["owner"] = {
        "sleeper_username": sleeper_username.strip(),
        "sleeper_user_id": sleeper_user_id.strip(),
    }
    if not all(value["owner"].values()):
        raise ValueError("Owner username and user ID must be explicit non-empty values")
    written, backup = _atomic_write(
        target, _json_text(value), allow_existing=True, dry_run=dry_run
    )
    return _result(
        "owner", writes=(written,), backups=(backup,), dry_run=dry_run,
        config_path=str(target), owner="[redacted]",
    )


def add_league(
    key: str,
    *,
    season: int,
    name: str,
    league_id: str,
    user_roster_id: int,
    draft_id: str | None = None,
    user_draft_slot: int | None = None,
    team_count: int | None = None,
    config_path: str | Path | None = None,
    update: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    if not SAFE_KEY.fullmatch(key):
        raise ValueError("League key must contain only letters, numbers, hyphens, or underscores")
    if not 2000 <= season <= 2200 or user_roster_id <= 0:
        raise ValueError("Season and user roster ID are invalid")
    target = resolve_league_config_path(config_path)
    value = _config_value(target)
    if not update:
        raise FileExistsError("Updating leagues.json requires the explicit --update option")
    existing = next((row for row in value["leagues"] if row.get("key") == key), None)
    league: dict[str, Any] = {
        **(existing or {}),
        "key": key,
        "name": name,
        "league_id": league_id,
        "season": str(season),
        "user_roster_id": user_roster_id,
        "history_league_ids": list((existing or {}).get("history_league_ids") or ()),
        "history_excluded_user_ids": list(
            (existing or {}).get("history_excluded_user_ids") or ()
        ),
        "policies": dict((existing or {}).get("policies") or {}),
    }
    if draft_id:
        league["draft_id"] = draft_id
    if user_draft_slot is not None:
        if user_draft_slot <= 0:
            raise ValueError("User draft slot must be positive")
        league["user_draft_slot"] = user_draft_slot
    if team_count is not None:
        if team_count <= 1:
            raise ValueError("Team count must exceed one")
        league["team_count"] = team_count
    if not name.strip() or not league_id.strip():
        raise ValueError("League name and Sleeper league ID are required")
    value["leagues"] = [row for row in value["leagues"] if row.get("key") != key]
    value["leagues"].append(league)
    value["leagues"].sort(key=lambda row: str(row["key"]))
    written, backup = _atomic_write(
        target, _json_text(value), allow_existing=True, dry_run=dry_run
    )
    return _result(
        "add-league", writes=(written,), backups=(backup,), dry_run=dry_run,
        config_path=str(target), league=key, season=season,
    )


def _artifact_root(config_path: Path, league_key: str, season: int) -> Path:
    return config_path.parent / "policies" / league_key / str(season)


def artifact_paths(
    league_key: str,
    *,
    config_path: str | Path | None = None,
    season: int | None = None,
) -> dict[str, Path]:
    resolved = resolve_league_config_path(config_path)
    league = find_league_config(league_key, resolved)
    configured_season = int(league["season"])
    selected = season or configured_season
    if selected != configured_season:
        raise ValueError(
            f"Requested season {selected} does not match {league_key} season {configured_season}"
        )
    root = _artifact_root(resolved, league_key, selected)
    paths = {name: root / filename for name, filename in FILENAMES.items()}
    policies = league.get("policies") or {}
    for artifact, policy_key in POLICY_KEYS.items():
        configured = policies.get(policy_key)
        if configured:
            path = Path(str(configured)).expanduser()
            paths[artifact] = path if path.is_absolute() else resolved.parent / path
    return paths


def _uncalibrated_policy(artifact: str, league_key: str, season: int) -> dict[str, Any]:
    products = {
        "trade-decision": "TRADE ASSISTANT",
        "trade-search": "TRADE ASSISTANT",
        "waiver-decision": "WAIVER ASSISTANT",
        "waiver-wire": "WAIVER ASSISTANT",
    }
    base: dict[str, Any] = {
        "schema_version": 1,
        "product": products[artifact],
        "artifact": artifact,
        "league_key": league_key,
        "season": season,
        "status": "UNCALIBRATED",
        "calibration": {
            "required": True,
            "evidence": [],
            "instructions": (
                "Supply thresholds supported by separate evidence for this league. "
                "Do not copy values or results from another league."
            ),
        },
    }
    if artifact == "trade-decision":
        base.update({
            "version": "UNSET",
            "historical_evidence_mode": "UNSET",
            "historical_evidence_reason": "",
            "scenario": {
                "offense_downside_multiplier": None,
                "offense_upside_multiplier": None,
            },
            "decision": {
                "user_selected_floor": None,
                "partner_market_floor": None,
                "postures": {
                    posture: {"max_depth_loss": None, "max_downside_increase": None}
                    for posture in ("CONSERVATIVE", "BALANCED", "CEILING")
                },
            },
        })
    elif artifact == "trade-search":
        base.update({
            "version": "UNSET",
            "target": {
                "market_value_floor": None,
                "raw_projection_floor": None,
                "material_gap_floor": None,
                "max_partner_lineup_loss": None,
                "near_waiver_need_margin": None,
                "reject_received_asset_drop": None,
                "max_one_starter_reserves": None,
            },
        })
    elif artifact == "waiver-wire":
        base.update({
            "scoring": None,
            "position": "ALL",
            "maximum_age_hours": None,
            "trusted_expert_ids": [],
        })
    elif artifact == "waiver-decision":
        base.update({
            "version": "UNSET",
            "calibration_mode": "UNSET",
            "allow_watch_on_missing_news": None,
            "special_teams": {
                name: None for name in (
                    "current_week_weight", "kicker_current_week_gain_floor",
                    "dst_current_week_gain_floor", "watch_current_week_gain_floor",
                    "elite_dst_ros_rank_cutoff", "elite_dst_maximum_current_week_loss",
                    "elite_dst_weighted_lineup_floor",
                )
            },
            "qb_holding": {
                name: None for name in (
                    "streaming_stress_rank", "starter_decision_margin",
                    "net_hold_value_floor", "watch_net_hold_value_floor",
                    "insurance_advantage_floor", "maximum_bench_slot_opportunity_cost",
                )
            },
            "contingent_upside": {
                name: None for name in (
                    "evidence_max_age_hours", "standalone_selected_value_floor",
                    "standalone_market_value_floor", "material_lineup_ceiling_gain",
                    "acquisition_incremental_value_gate",
                )
            },
            "emerging_upside": {
                name: None for name in (
                    "ww_support_mode", "market_ww_rank_cutoff",
                    "selected_expert_rank_cutoff", "minimum_selected_expert_support",
                    "maximum_miss_case_loss", "maximum_selected_value_deficit",
                    "maximum_market_value_deficit", "maximum_raw_projection_deficit",
                    "maximum_central_lineup_deficit", "minimum_incremental_option_value",
                    "maximum_break_even_hit_rate", "evidence_max_age_hours",
                    "minimum_role_signal_strength", "maximum_replacement_exposure",
                    "maximum_current_week_loss", "maximum_offense_downside_increase",
                    "near_threshold_fraction",
                )
            },
            "validation_scope": {
                "league": league_key,
                "policy_posture": None,
                "fixture_classes": [],
            },
            "thresholds": {
                name: None for name in (
                    "selected_value_floor", "market_value_floor", "raw_projection_floor",
                    "immediate_lineup_gain_floor", "insurance_selected_gain_floor",
                    "insurance_market_gain_floor", "insurance_depth_floor",
                    "maximum_current_week_loss", "maximum_depth_loss",
                    "maximum_downside_increase", "watch_selected_value_floor",
                    "watch_market_value_floor", "watch_raw_projection_floor",
                    "watch_lineup_floor", "watch_maximum_current_week_loss",
                    "watch_maximum_depth_loss", "watch_maximum_downside_increase",
                )
            },
        })
    return base


def _artifact_content(artifact: str, league_key: str, season: int) -> str:
    if artifact == "expert-overrides":
        return _csv_text(EXPERT_OVERRIDE_FIELDS)
    if artifact == "identity-overrides":
        return _csv_text(IDENTITY_OVERRIDE_FIELDS)
    if artifact == "draft-preferences":
        return _csv_text(
            DRAFT_PREFERENCE_FIELDS,
            ({"league_scope": league_key, "status": "UNCALIBRATED"},),
        )
    if artifact == "contingencies":
        return _json_text({
            "schema_version": 1,
            "product": "WAIVER ASSISTANT",
            "artifact": artifact,
            "league_key": league_key,
            "season": season,
            "status": "OPTIONAL_EMPTY",
            "relationships": [],
        })
    return _json_text(_uncalibrated_policy(artifact, league_key, season))


def scaffold_private_inputs(
    league_key: str,
    *,
    artifact: str = "all",
    config_path: str | Path | None = None,
    season: int | None = None,
    replace: bool = False,
    update_config: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    if artifact != "all" and artifact not in ARTIFACTS:
        raise ValueError(f"Unknown setup artifact: {artifact}")
    resolved = resolve_league_config_path(config_path)
    config = _config_value(resolved)
    league = find_league_config(league_key, resolved)
    selected_season = season or int(league["season"])
    paths = artifact_paths(
        league_key, config_path=resolved, season=selected_season
    )
    selected = ARTIFACTS if artifact == "all" else (artifact,)
    configured_policy_names = [name for name in selected if name in POLICY_KEYS]
    if configured_policy_names and not update_config:
        raise ValueError(
            "Policy scaffolding requires --update-config so league references are explicit"
        )
    existing_paths = [paths[name] for name in selected if paths[name].exists()]
    if existing_paths and not replace:
        raise FileExistsError(
            f"Refusing to replace existing private file: {existing_paths[0]}. Pass --replace."
        )
    writes: list[Path] = []
    backups: list[Path | None] = []
    for name in selected:
        written, backup = _atomic_write(
            paths[name],
            _artifact_content(name, league_key, selected_season),
            allow_existing=replace,
            dry_run=dry_run,
        )
        writes.append(written)
        backups.append(backup)
    if configured_policy_names:
        config_league = next(row for row in config["leagues"] if row["key"] == league_key)
        policies = dict(config_league.get("policies") or {})
        for name in configured_policy_names:
            try:
                configured_path = paths[name].relative_to(resolved.parent).as_posix()
            except ValueError:
                configured_path = str(paths[name])
            policies[POLICY_KEYS[name]] = configured_path
        config_league["policies"] = policies
        config_write, config_backup = _atomic_write(
            resolved, _json_text(config), allow_existing=True, dry_run=dry_run
        )
        writes.append(config_write)
        backups.append(config_backup)
    return _result(
        "scaffold", writes=writes, backups=backups, dry_run=dry_run,
        league=league_key, season=selected_season, artifacts=list(selected),
        policy_status="UNCALIBRATED",
    )


def _read_csv(path: Path) -> tuple[tuple[str, ...], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return tuple(reader.fieldnames or ()), [dict(row) for row in reader]


def _validate_date(value: str) -> str:
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise ValueError("Evidence date must be YYYY-MM-DD") from exc


def update_override(
    league_key: str,
    *,
    operation: str,
    kind: str,
    scope: str,
    subject: str,
    action: str,
    reason: str,
    evidence_date: str,
    source: str,
    value: str = "",
    fantasypros_id: str = "",
    sleeper_id: str = "",
    team: str = "",
    position: str = "",
    config_path: str | Path | None = None,
    season: int | None = None,
    update: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    if operation not in {"add", "remove"} or kind not in {"expert", "identity"}:
        raise ValueError("Override operation or kind is unsupported")
    if not all(item.strip() for item in (scope, subject, action, reason, source)):
        raise ValueError("Override scope, subject, action, reason, and source are required")
    evidence_date = _validate_date(evidence_date)
    artifact = "expert-overrides" if kind == "expert" else "identity-overrides"
    path = artifact_paths(league_key, config_path=config_path, season=season)[artifact]
    fields = EXPERT_OVERRIDE_FIELDS if kind == "expert" else IDENTITY_OVERRIDE_FIELDS
    rows: list[dict[str, str]] = []
    if path.exists():
        if not update:
            raise FileExistsError(f"Override file exists: {path}; pass --update")
        actual_fields, rows = _read_csv(path)
        if tuple(actual_fields) != tuple(fields):
            raise ValueError(f"{kind.title()} override file has an unsupported header")
    if kind == "expert":
        if action not in {"exclude", "last_updated_override", "anchor_equivalent"}:
            raise ValueError("Expert action must be exclude, last_updated_override, or anchor_equivalent")
        if action == "last_updated_override":
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        if action == "anchor_equivalent" and float(value) < 1.0:
            raise ValueError("Anchor equivalent value must be at least one")
        row = {
            "scope": scope, "expert_name": subject, "action": action, "value": value,
            "reason": reason, "evidence_date": evidence_date, "source": source,
        }
        matches = lambda candidate: (
            candidate.get("scope") == scope
            and candidate.get("expert_name") == subject
            and candidate.get("action") == action
        )
    else:
        if action != "map" or operation == "add" and not all(
            item.strip() for item in (fantasypros_id, sleeper_id, team, position)
        ):
            raise ValueError("Identity map requires both IDs, team, and position")
        row = {
            "scope": scope, "fantasypros_id": fantasypros_id, "sleeper_id": sleeper_id,
            "player_name": subject, "team": team.upper(), "position": position.upper(),
            "evidence": f"{source}; {reason}; {evidence_date}", "action": action,
            "reason": reason, "evidence_date": evidence_date, "source": source,
        }
        matches = lambda candidate: (
            candidate.get("scope") == scope
            and candidate.get("player_name") == subject
            and candidate.get("action") == action
        )
    matched = [candidate for candidate in rows if matches(candidate)]
    if operation == "add":
        if matched:
            raise ValueError("Matching override already exists; remove it before adding a replacement")
        rows.append(row)
    else:
        if len(matched) != 1:
            raise ValueError(f"Override removal requires one exact match; found {len(matched)}")
        rows = [candidate for candidate in rows if not matches(candidate)]
    rows.sort(key=lambda candidate: tuple(candidate.get(field, "") for field in fields))
    audit_path = path.parent / "override-audit.json"
    if audit_path.exists() and not update:
        raise FileExistsError(f"Override audit exists: {audit_path}; pass --update")
    written, backup = _atomic_write(
        path, _csv_text(fields, rows), allow_existing=path.exists(), dry_run=dry_run
    )
    selected_season = season or int(find_league_config(
        league_key, resolve_league_config_path(config_path)
    )["season"])
    audit: dict[str, Any] = {
        "schema_version": 1,
        "league_key": league_key,
        "season": selected_season,
        "events": [],
    }
    if audit_path.exists():
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
    audit["events"].append({
        "operation": operation, "kind": kind, "scope": scope, "subject": subject,
        "action": action, "reason": reason, "evidence_date": evidence_date,
        "source": source,
    })
    audit_written, audit_backup = _atomic_write(
        audit_path, _json_text(audit), allow_existing=audit_path.exists(), dry_run=dry_run
    )
    return _result(
        f"override-{operation}", writes=(written, audit_written),
        backups=(backup, audit_backup), dry_run=dry_run, league=league_key,
        season=selected_season, kind=kind, scope=scope, subject=subject,
        action=action, override_count=len(rows),
    )


def _artifact_status(
    artifact: str, path: Path, *, league_key: str, season: int
) -> dict[str, Any]:
    if not path.is_file():
        status = (
            "optional"
            if artifact in {"expert-overrides", "identity-overrides", "contingencies"}
            else "missing"
        )
        return {"artifact": artifact, "status": status, "path": str(path)}
    try:
        if path.suffix == ".csv":
            fields, rows = _read_csv(path)
            required = {
                "expert-overrides": set(EXPERT_OVERRIDE_FIELDS),
                "identity-overrides": set(IDENTITY_OVERRIDE_FIELDS),
                "draft-preferences": set(DRAFT_PREFERENCE_REQUIRED_FIELDS),
            }[artifact]
            if not required.issubset(fields):
                raise ValueError("CSV header is incomplete")
            for row in rows:
                if row.get("evidence_date"):
                    _validate_date(row["evidence_date"])
                if artifact != "draft-preferences" and row and not all(
                    str(row.get(field) or "").strip()
                    for field in ("scope", "reason", "evidence_date", "source")
                ):
                    raise ValueError("Override row lacks explicit audit metadata")
            uncalibrated = artifact == "draft-preferences" and (
                not rows or any(row.get("status") == "UNCALIBRATED" for row in rows)
            )
            status = "uncalibrated" if uncalibrated else "ready"
            return {
                "artifact": artifact, "status": status, "path": str(path),
                "row_count": len(rows),
            }
        value = json.loads(path.read_text(encoding="utf-8"))
        if value.get("league_key") != league_key or int(value.get("season") or 0) != season:
            raise ValueError("Artifact league or season does not match")
        if value.get("status") == "UNCALIBRATED":
            status = "uncalibrated"
        elif artifact == "contingencies":
            if value.get("schema_version") != 1 or value.get("product") != "WAIVER ASSISTANT":
                raise ValueError("Contingency schema is invalid")
            if not isinstance(value.get("relationships"), list):
                raise ValueError("Contingency relationships must be a list")
            status = "ready"
        else:
            from roster_theory.trade.evaluation import EvaluationOptions
            from roster_theory.trade.evaluation_service import _options_from_policy
            from roster_theory.trade.search import SearchConfig
            from roster_theory.trade.search_service import _config_from_policy
            from roster_theory.waiver.policy import load_waiver_policy
            from roster_theory.waiver.ww_evidence import load_waiver_wire_config

            if artifact == "trade-decision":
                _options_from_policy(EvaluationOptions(), path)
            elif artifact == "trade-search":
                _config_from_policy(SearchConfig(), path)
            elif artifact == "waiver-decision":
                load_waiver_policy(path)
            elif artifact == "waiver-wire":
                load_waiver_wire_config(path, league_key=league_key)
            status = "ready"
        return {"artifact": artifact, "status": status, "path": str(path)}
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        return {
            "artifact": artifact, "status": "invalid", "path": str(path),
            "reason": str(exc),
        }


def inspect_private_setup(
    *,
    operation: str,
    config_path: str | Path | None = None,
    league_key: str | None = None,
) -> dict[str, Any]:
    resolved = resolve_league_config_path(config_path)
    try:
        config = _config_value(resolved)
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        return _result(
            operation, status="invalid" if resolved.exists() else "missing",
            config_path=str(resolved), reason=str(exc),
            next_command="roster-theory setup init",
        )
    leagues = [row for row in config["leagues"] if league_key is None or row["key"] == league_key]
    if league_key is not None and not leagues:
        raise KeyError(f"Unknown league key: {league_key}")
    reports = []
    for league in leagues:
        key, season = str(league["key"]), int(league["season"])
        paths = artifact_paths(key, config_path=resolved)
        artifacts = [
            _artifact_status(name, paths[name], league_key=key, season=season)
            for name in ARTIFACTS
        ]
        reports.append({"league": key, "season": season, "artifacts": artifacts})
    statuses = [item["status"] for report in reports for item in report["artifacts"]]
    status = (
        "invalid" if "invalid" in statuses else
        "missing" if "missing" in statuses else
        "uncalibrated" if "uncalibrated" in statuses else "ready"
    )
    return _result(
        operation, status=status, config_path=str(resolved), leagues=reports,
        next_command=(
            f"roster-theory setup scaffold {league_key or 'LEAGUE'} --update-config"
            if status != "ready" else None
        ),
    )


def show_redacted_setup(
    *,
    config_path: str | Path | None = None,
    league_key: str | None = None,
    artifact: str = "config",
) -> dict[str, Any]:
    resolved = resolve_league_config_path(config_path)
    config = _config_value(resolved)
    if artifact == "config":
        redacted = json.loads(json.dumps(config))
        for key in tuple(redacted.get("owner", {})):
            redacted["owner"][key] = "[redacted]"
        for league in redacted["leagues"]:
            for key in tuple(league):
                if key.endswith("_id") or key.endswith("_ids") or key in {"name", "user_team_name"}:
                    league[key] = "[redacted]"
            if isinstance(league.get("policies"), dict):
                league["policies"] = {
                    key: Path(str(value)).name
                    for key, value in league["policies"].items()
                }
        return _result("show-redacted", config=redacted)
    if league_key is None or artifact not in ARTIFACTS:
        raise ValueError("Artifact display requires a league and supported artifact")
    league = find_league_config(league_key, resolved)
    season = int(league["season"])
    path = artifact_paths(league_key, config_path=resolved)[artifact]
    report = _artifact_status(artifact, path, league_key=league_key, season=season)
    report["path"] = path.name
    if path.suffix == ".csv" and path.is_file():
        _, rows = _read_csv(path)
        report["rows"] = [
            {
                key: (
                    "[redacted]"
                    if key.endswith("_id")
                    or any(token in key for token in ("name", "subject", "beneficiary", "teammate"))
                    else value
                )
                for key, value in row.items()
            }
            for row in rows
        ]
    elif path.is_file():
        def redact(value: Any, key: str = "") -> Any:
            if isinstance(value, dict):
                return {child_key: redact(child, child_key) for child_key, child in value.items()}
            if isinstance(value, list):
                return [redact(child, key) for child in value]
            if key.endswith("_id") or any(
                token in key for token in ("name", "subject", "beneficiary", "teammate")
            ):
                return "[redacted]"
            return value

        report["document"] = redact(json.loads(path.read_text(encoding="utf-8")))
    return _result("show-redacted", league=league_key, season=season, artifact_report=report)


def explain_private_setup(artifact: str = "all") -> dict[str, Any]:
    explanations = {
        "config": "Private Sleeper identity and league routing; values must be supplied by the user.",
        "expert-overrides": "Explicit expert exclusions, dated freshness corrections, or anchor weights; provider data never creates these decisions.",
        "identity-overrides": "Explicit FantasyPros-to-Sleeper identity mappings with dated source evidence.",
        "draft-preferences": "League-scoped player targets and cautions supplied by the user.",
        "trade-decision": "League-calibrated Trade risk and acceptance thresholds; scaffold remains unusable until supported.",
        "trade-search": "League-calibrated Trade opportunity-search thresholds; no values are borrowed.",
        "waiver-decision": "League-calibrated Waiver decision thresholds and controlled-fixture evidence.",
        "waiver-wire": "League-scoped Waiver Wire expert authority and freshness settings.",
        "contingencies": "Optional named-player role relationships; no injury probability or generic handcuff bonus is inferred.",
    }
    if artifact != "all" and artifact not in explanations:
        raise ValueError(f"Unknown setup artifact: {artifact}")
    selected = explanations if artifact == "all" else {artifact: explanations[artifact]}
    return _result("explain", artifacts=selected)
