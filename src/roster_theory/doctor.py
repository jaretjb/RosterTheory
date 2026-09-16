"""Offline, read-only setup checks with no private IDs or paths in reports."""

from __future__ import annotations

import csv
import json
import re
import textwrap
from pathlib import Path
from typing import Any

from roster_theory.schedule_inputs import default_schedule_path
from roster_theory.sleeper import resolve_league_config_path
from roster_theory.terminal import TerminalCapabilities, status_token, styled
from roster_theory.trade.evaluation import EvaluationOptions
from roster_theory.trade.evaluation_service import _options_from_policy
from roster_theory.trade.search import SearchConfig
from roster_theory.trade.search_service import _config_from_policy
from roster_theory.waiver.policy import load_waiver_policy
from roster_theory.waiver.ww_evidence import load_waiver_wire_config


_SAFE_KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*")
_POLICIES = {
    "Draft": ("draft_preferences",),
    "Trade": ("trade_decision", "trade_search"),
    "Waiver": ("waiver_decision", "waiver_wire"),
}


def _check(
    name: str, status: str, reason: str, next_action: str, *, track: str = "Setup"
) -> dict[str, str]:
    return {
        "check": name,
        "track": track,
        "status": status,
        "reason": reason,
        "next_action": next_action,
    }


def _present(value: Any) -> bool:
    text = str(value or "").strip()
    return bool(text) and not text.lower().startswith(("your_", "current_"))


def _local_file(name: str, path: str | Path | None, action: str, track: str) -> dict[str, str]:
    if path is None:
        return _check(name, "unavailable", "No local input was selected for the offline check.", action, track=track)
    try:
        exists = Path(path).expanduser().is_file()
    except (OSError, ValueError, TypeError):
        return _check(name, "invalid", "The local input path is invalid.", action, track=track)
    if not exists:
        return _check(name, "missing", "The required local input file is absent.", action, track=track)
    return _check(name, "ready", "Local file exists; contents and freshness were not verified.", "Validate this input before analysis.", track=track)


def _policy_check(
    league_key: str,
    policy_name: str,
    policies: Any,
    config_dir: Path,
    track: str,
    *,
    display_key: str | None = None,
) -> dict[str, str]:
    artifact = policy_name.replace("_", "-")
    action = (
        f"Run roster-theory setup scaffold {display_key or league_key} --artifact {artifact} "
        "--update-config."
    )
    if not isinstance(policies, dict):
        return _check(policy_name, "invalid", "Policies must be a JSON object.", action, track=track)
    raw_path = policies.get(policy_name)
    if not raw_path:
        return _check(policy_name, "uncalibrated", "No league-specific policy is configured.", action, track=track)
    if not isinstance(raw_path, str):
        return _check(policy_name, "invalid", "Policy path must be a string.", action, track=track)
    try:
        path = Path(raw_path).expanduser()
        if not path.is_absolute():
            path = config_dir / path
        if not path.is_file():
            return _check(policy_name, "uncalibrated", "Configured policy file is absent.", action, track=track)
        if policy_name == "draft_preferences":
            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                rows = tuple(csv.DictReader(handle))
            scoped = any(
                league_key in {part.strip() for part in str(row.get("league_scope") or "").split("|")}
                for row in rows
            )
            if any(str(row.get("status") or "").upper() == "UNCALIBRATED" for row in rows):
                return _check(policy_name, "uncalibrated", "Draft preference scaffold needs explicit league evidence.", action, track=track)
            if not scoped:
                return _check(policy_name, "uncalibrated", "Draft preferences do not declare this league.", action, track=track)
        else:
            value = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                raise ValueError("Policy must be an object")
            if value.get("league_key") != league_key:
                return _check(policy_name, "uncalibrated", "Policy declares a different league or no league.", action, track=track)
            if str(value.get("status") or "").upper() == "UNCALIBRATED":
                return _check(policy_name, "uncalibrated", "Policy scaffold needs separately supported league thresholds.", action, track=track)
            if policy_name == "waiver_decision":
                load_waiver_policy(path)
            elif policy_name == "waiver_wire":
                load_waiver_wire_config(path, league_key=league_key)
            elif policy_name == "trade_decision":
                _options_from_policy(EvaluationOptions(), path)
            elif policy_name == "trade_search":
                _config_from_policy(SearchConfig(), path)
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return _check(policy_name, "invalid", "Policy file cannot be validated offline.", action, track=track)
    return _check(policy_name, "ready", "Policy file is valid and league-scoped; calibration is not proved.", "Verify league-local evidence before recommendations.", track=track)


def _summary(checks: list[dict[str, str]], names: tuple[str, ...]) -> str:
    statuses = {row["check"]: row["status"] for row in checks}
    relevant = [statuses.get(name, "unavailable") for name in names]
    for status in ("invalid", "missing", "uncalibrated", "unavailable"):
        if status in relevant:
            return status
    return "ready"


def audit_setup(
    *,
    config_path: str | Path | None = None,
    league_key: str | None = None,
    schedule_path: str | Path | None = None,
    expert_pool_path: str | Path | None = None,
    draft_board_path: str | Path | None = None,
    waiver_inputs_path: str | Path | None = None,
) -> dict[str, Any]:
    """Inspect only local paths; return diagnostic success even when setup fails."""

    resolved = resolve_league_config_path(config_path)
    report: dict[str, Any] = {"offline": True, "provider_calls": 0, "sleeper_writes": 0, "checks": [], "leagues": []}
    try:
        if not resolved.is_file():
            report["checks"].append(_check("config", "missing", "League configuration is absent.", "Run roster-theory setup init, or roster-theory setup import --input PATH."))
            return report
        value = json.loads(resolved.read_text(encoding="utf-8"))
        if not isinstance(value, dict) or not isinstance(value.get("leagues"), list):
            raise ValueError("Invalid league configuration")
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        report["checks"].append(_check("config", "invalid", "League configuration is not a valid JSON object with a leagues array.", "Run roster-theory setup import --input VALID_PATH --replace after reviewing the backup."))
        return report

    report["checks"].append(_check("config", "ready", "League configuration was found and parsed.", "Review each league check below."))
    owner = value.get("owner")
    owner_ready = isinstance(owner, dict) and _present(owner.get("sleeper_user_id"))
    if not isinstance(owner, dict):
        report["checks"].append(_check("owner", "invalid", "Owner must be a JSON object.", "Run roster-theory setup owner --sleeper-username NAME --sleeper-user-id ID --update."))
    elif not owner_ready:
        report["checks"].append(_check("owner", "missing", "Sleeper owner identity is incomplete.", "Run roster-theory setup owner --sleeper-username NAME --sleeper-user-id ID --update."))
    else:
        report["checks"].append(_check("owner", "ready", "Local owner ID is present; it was not verified with Sleeper.", "Confirm ownership with a read-only refresh."))
    if not value["leagues"]:
        report["checks"].append(_check("league", "missing", "No leagues are configured.", "Run roster-theory setup add-league KEY --season YYYY --name NAME --league-id ID --user-roster-id N --update."))
    keys = [row.get("key") for row in value["leagues"] if isinstance(row, dict)]
    duplicates = {key for key in keys if isinstance(key, str) and keys.count(key) > 1}
    for index, league in enumerate(value["leagues"], start=1):
        if not isinstance(league, dict):
            name = f"entry_{index}"
            report["leagues"].append({"league": name, "checks": [_check("identity", "invalid", "League entry must be a JSON object.", "Repair this leagues[] entry.")], "tracks": {}})
            continue
        raw_key = league.get("key")
        safe_key = isinstance(raw_key, str) and bool(_SAFE_KEY.fullmatch(raw_key))
        name = raw_key if safe_key and not raw_key.isdigit() else f"entry_{index}"
        if league_key is not None and raw_key != league_key:
            continue
        checks: list[dict[str, str]] = []
        if not safe_key or raw_key in duplicates:
            checks.append(_check("identity", "invalid", "League key is missing, unsafe, or duplicated.", "Run roster-theory setup add-league SAFE_KEY with explicit values and --update."))
        elif not _present(league.get("league_id")) or not league.get("season") or league.get("user_roster_id") is None or not owner_ready:
            checks.append(_check("identity", "missing", "Sleeper league, season, roster, or owner identity is incomplete.", f"Run roster-theory setup add-league {name} with explicit identity values and --update."))
        elif not re.fullmatch(r"\d{4}", str(league["season"])) or type(league["user_roster_id"]) is not int or league["user_roster_id"] <= 0:
            checks.append(_check("identity", "invalid", "Season or roster identity has an invalid format.", f"Run roster-theory setup add-league {name} with corrected values and --update."))
        else:
            checks.append(_check("identity", "ready", "Local league and owner identity fields are present; Sleeper has not been queried.", "Confirm identity with a read-only provider refresh."))

        if not _present(league.get("draft_id")) or league.get("user_draft_slot") is None:
            checks.append(_check("draft_identity", "missing", "Draft ID or draft slot is incomplete.", f"Run roster-theory setup add-league {name} with --draft-id, --user-draft-slot, and --update.", track="Draft"))
        elif type(league["user_draft_slot"]) is not int or league["user_draft_slot"] <= 0:
            checks.append(_check("draft_identity", "invalid", "Draft slot must be a positive integer.", f"Run roster-theory setup add-league {name} with a positive --user-draft-slot and --update.", track="Draft"))
        else:
            checks.append(_check("draft_identity", "ready", "Local draft fields are present; current room was not queried.", "Confirm the draft room read-only before use.", track="Draft"))

        for track, policy_names in _POLICIES.items():
            for policy_name in policy_names:
                checks.append(_policy_check(
                    str(raw_key), policy_name, league.get("policies"), resolved.parent,
                    track, display_key=name,
                ))
        resolved_expert_pool_path = expert_pool_path or (
            Path("data")
            / "manual"
            / "policies"
            / str(raw_key)
            / str(league.get("season") or "unknown")
            / "inseason_experts.csv"
        )
        resolved_schedule_path = schedule_path or default_schedule_path(
            int(league["season"]) if str(league.get("season") or "").isdigit() else 0
        )
        checks.extend((
            _local_file("draft_board", draft_board_path, f"Run roster-theory fantasypros-league-boards --league {name}, then pass its board with --draft-board PATH.", "Draft"),
            _local_file("schedule", resolved_schedule_path, f"Run roster-theory inputs schedule refresh {name}, or pass --schedule PATH.", "Trade"),
            _local_file("expert_pool", resolved_expert_pool_path, f"Run roster-theory inputs experts refresh {name} --artifact inseason-pool, or pass --expert-pool PATH.", "Trade"),
            _local_file("waiver_inputs", waiver_inputs_path, f"Run roster-theory waiver inputs {name}, then pass its output with --waiver-inputs PATH.", "Waiver"),
        ))
        tracks = {
            "Draft": {
                "data_only": _summary(checks, ("identity", "draft_identity")),
                "decision": _summary(checks, ("identity", "draft_identity", "draft_preferences", "draft_board")),
            },
            "Trade": {
                "data_only": _summary(checks, ("identity", "schedule")),
                "decision": _summary(checks, ("identity", "schedule", "expert_pool", "trade_decision", "trade_search")),
            },
            "Waiver": {
                "data_only": _summary(checks, ("identity",)),
                "decision": _summary(checks, ("identity", "waiver_decision", "waiver_wire", "waiver_inputs")),
            },
        }
        for track in tracks.values():
            if track["decision"] == "ready":
                track["decision"] = "unavailable"  # Offline checks cannot prove fresh evidence/calibration.
        report["leagues"].append({"league": name, "checks": checks, "tracks": tracks})

    if league_key is not None and not report["leagues"]:
        report["checks"].append(_check("league", "missing", "Selected league key was not found.", "Use roster-theory leagues to list configured keys."))
    return report


def _doctor_status(status: str, capabilities: TerminalCapabilities | None) -> str:
    label = status.upper()
    return styled(label, status_token(status), capabilities) if capabilities else label


def _doctor_wrap(text: str, *, width: int, prefix: str = "") -> list[str]:
    available = max(24, width - len(prefix))
    wrapped = textwrap.wrap(
        text,
        width=available,
        break_long_words=False,
        break_on_hyphens=False,
    ) or [""]
    return [prefix + wrapped[0], *(" " * len(prefix) + line for line in wrapped[1:])]


def format_doctor(
    report: dict[str, Any],
    *,
    details: bool = False,
    capabilities: TerminalCapabilities | None = None,
) -> str:
    """Render a deterministic human health board without changing audit data."""

    width = max(32, capabilities.width if capabilities else 80)
    global_checks = list(report.get("checks", []))
    leagues = list(report.get("leagues", []))
    scoped_checks = [("Setup", check) for check in global_checks] + [
        (str(league["league"]), check)
        for league in leagues
        for check in league.get("checks", [])
    ]
    ready_count = sum(
        check.get("status") == "ready" for _, check in scoped_checks
    )
    findings = [
        (scope, check)
        for scope, check in scoped_checks
        if check.get("status") != "ready"
    ]

    lines = ["DOCTOR / OFFLINE / READ-ONLY", ""]
    summary = {check.get("check"): check for check in global_checks}
    summary_parts = []
    for name in ("config", "owner"):
        if name in summary:
            summary_parts.append(
                f"{name.title()} {_doctor_status(str(summary[name]['status']), capabilities)}"
            )
    summary_parts.extend(
        (
            f"Provider calls {report.get('provider_calls', 0)}",
            f"Sleeper writes {report.get('sleeper_writes', 0)}",
        )
    )
    lines.extend(("CHECKUP", "  " + " | ".join(summary_parts), ""))

    if leagues:
        lines.append("LEAGUE HEALTH")
        for league in leagues:
            lines.append(f"  {league['league']}")
            tracks = league.get("tracks", {})
            if width >= 72 and tracks:
                lines.append("    Track       Data              Decision")
                for track in ("Draft", "Trade", "Waiver"):
                    if track not in tracks:
                        continue
                    row = tracks[track]
                    raw_data = str(row["data_only"])
                    data = _doctor_status(raw_data, capabilities)
                    decision = _doctor_status(str(row["decision"]), capabilities)
                    lines.append(
                        f"    {track:<11} {data}{' ' * max(1, 17 - len(raw_data))}{decision}"
                    )
            else:
                for track in ("Draft", "Trade", "Waiver"):
                    if track not in tracks:
                        continue
                    row = tracks[track]
                    data = _doctor_status(str(row["data_only"]), capabilities)
                    decision = _doctor_status(str(row["decision"]), capabilities)
                    lines.append(f"    {track}: data {data}")
                    lines.append(f"      decision {decision}")
            lines.append("")

    shown_checks = scoped_checks if details else findings
    if shown_checks:
        lines.append("ALL CHECKS" if details else "NEXT ON THE BOARD")
        for index, (scope, check) in enumerate(shown_checks, start=1):
            status = _doctor_status(str(check["status"]), capabilities)
            location = (
                f"{scope} / {check['check']}"
                if scope == "Setup"
                else f"{scope} / {check['track']} / {check['check']}"
            )
            heading = f"  {index}. {location} [{status}]"
            lines.append(heading)
            lines.extend(
                _doctor_wrap(str(check["reason"]), width=width, prefix="     Why: ")
            )
            if check["status"] != "ready" or details:
                lines.extend(
                    _doctor_wrap(
                        str(check["next_action"]), width=width, prefix="     Next: "
                    )
                )
        lines.append("")
    else:
        lines.extend(("NEXT ON THE BOARD", "  Nothing found by the offline checks.", ""))

    if not details and ready_count:
        noun = "check" if ready_count == 1 else "checks"
        lines.append(f"{ready_count} ready {noun} summarized. Run with --details to show every check.")
    lines.append("Local readiness does not prove live-data freshness or league calibration.")
    return "\n".join(lines)
