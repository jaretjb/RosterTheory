from __future__ import annotations

import hashlib
import json
import os
import statistics
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from roster_theory.rankings import normalize_name
from roster_theory.sleeper_adp import (
    SKILL_POSITIONS,
    audit_pick_sequence_against_sleeper_adp,
)


def _canonical_report_picks(report: Mapping[str, Any]) -> list[dict[str, Any]]:
    by_number: dict[int, dict[str, Any]] = {}
    for roster in (report.get("rosters") or {}).values():
        for source in roster or []:
            pick_no = int(source.get("pick_no") or 0)
            if pick_no > 0:
                by_number[pick_no] = dict(source)
    return [by_number[number] for number in sorted(by_number)]


def _pick_key(pick: Mapping[str, Any]) -> str:
    player_id = str(pick.get("player_id") or "")
    if player_id:
        return f"sleeper_id:{player_id}"
    metadata = pick.get("metadata") or {}
    name = " ".join(
        part
        for part in (
            str(metadata.get("first_name") or "").strip(),
            str(metadata.get("last_name") or "").strip(),
        )
        if part
    )
    return f"name:{normalize_name(name)}"


def _pick_name(pick: Mapping[str, Any]) -> str:
    metadata = pick.get("metadata") or {}
    name = " ".join(
        part
        for part in (
            str(metadata.get("first_name") or "").strip(),
            str(metadata.get("last_name") or "").strip(),
        )
        if part
    )
    return name or str(metadata.get("player_name") or pick.get("player_id") or "")


def _row_key(row: Mapping[str, Any]) -> str:
    key = str(row.get("player_key") or "")
    if key.isdigit():
        return f"sleeper_id:{key}"
    return key or f"name:{normalize_name(str(row.get('player_name') or ''))}"


def _row_matches_pick(row: Mapping[str, Any], pick: Mapping[str, Any]) -> bool:
    if _row_key(row) == _pick_key(pick):
        return True
    return normalize_name(str(row.get("player_name") or "")) == normalize_name(
        _pick_name(pick)
    )


def _numeric_summary(values: Iterable[Any]) -> dict[str, float | None]:
    numbers = []
    for value in values:
        try:
            numbers.append(float(value))
        except (TypeError, ValueError):
            continue
    return {
        "mean": round(statistics.fmean(numbers), 3) if numbers else None,
        "maximum": round(max(numbers), 3) if numbers else None,
    }


def _calibration_summary(
    observations: list[dict[str, Any]], probability_field: str
) -> dict[str, Any]:
    usable = [
        (float(row[probability_field]), int(bool(row["survived"])))
        for row in observations
        if row.get(probability_field) is not None
    ]
    buckets = []
    for lower, upper in ((0.0, 0.25), (0.25, 0.50), (0.50, 0.75), (0.75, 1.001)):
        rows = [(probability, outcome) for probability, outcome in usable if lower <= probability < upper]
        buckets.append(
            {
                "range": f"{lower:.2f}-{min(upper, 1.0):.2f}",
                "count": len(rows),
                "mean_predicted": (
                    round(statistics.fmean(probability for probability, _ in rows), 6)
                    if rows
                    else None
                ),
                "observed_survival": (
                    round(statistics.fmean(outcome for _, outcome in rows), 6)
                    if rows
                    else None
                ),
            }
        )
    return {
        "observations": len(usable),
        "mean_predicted": (
            round(statistics.fmean(probability for probability, _ in usable), 6)
            if usable
            else None
        ),
        "observed_survival": (
            round(statistics.fmean(outcome for _, outcome in usable), 6)
            if usable
            else None
        ),
        "brier_score": (
            round(
                statistics.fmean(
                    (probability - outcome) ** 2
                    for probability, outcome in usable
                ),
                6,
            )
            if usable
            else None
        ),
        "buckets": buckets,
    }


def _survival_audit(
    reports: list[Mapping[str, Any]], final_picks: list[Mapping[str, Any]]
) -> dict[str, Any]:
    pick_by_number = {int(pick.get("pick_no") or 0): pick for pick in final_picks}
    picked_at = {_pick_key(pick): int(pick.get("pick_no") or 0) for pick in final_picks}
    final_pick_number = max(pick_by_number, default=0)
    observations = []
    censored_by_user = 0
    not_yet_observable = 0
    for report in reports:
        recommendation = report.get("recommendation") or {}
        policies = list(recommendation.get("policies") or [])
        if not report.get("is_user_turn") or not policies:
            continue
        primary = policies[0]
        current_pick = int(report.get("current_pick") or 0)
        current_selection = pick_by_number.get(current_pick)
        for row in (recommendation.get("recommendations") or {}).get(primary) or []:
            try:
                target_pick = int(row.get("next_pick") or 0)
            except (TypeError, ValueError):
                continue
            if target_pick <= current_pick:
                continue
            key = _row_key(row)
            if current_selection and _row_matches_pick(row, current_selection):
                censored_by_user += 1
                continue
            if final_pick_number < target_pick - 1:
                not_yet_observable += 1
                continue
            drafted_at = picked_at.get(key)
            survived = drafted_at is None or drafted_at >= target_pick
            observations.append(
                {
                    "current_pick": current_pick,
                    "target_pick": target_pick,
                    "player_key": key,
                    "player_name": str(row.get("player_name") or ""),
                    "position": str(row.get("position") or ""),
                    "drafted_at": drafted_at,
                    "survived": survived,
                    "market_survival": row.get("market_survival"),
                    "league_survival": row.get("league_survival"),
                    "generic_league_survival": row.get("baseline_league_survival"),
                }
            )
    return {
        "scope": "displayed_primary_policy_candidates",
        "censored_by_user_selection": censored_by_user,
        "not_yet_observable": not_yet_observable,
        "market": _calibration_summary(observations, "market_survival"),
        "league_room_aware": _calibration_summary(observations, "league_survival"),
        "league_generic": _calibration_summary(
            observations, "generic_league_survival"
        ),
        "outcomes": observations,
    }


def build_mock_evidence_audit(
    session: Mapping[str, Any],
    reports: Iterable[Mapping[str, Any]],
    termination: str,
) -> dict[str, Any]:
    report_list = list(reports)
    final_report = report_list[-1] if report_list else {}
    final_picks = _canonical_report_picks(final_report)
    teams = int(final_report.get("teams") or len(final_report.get("rosters") or {}))
    rounds = int(final_report.get("rounds") or 0)
    expected_picks = teams * rounds if teams and rounds else None
    reported_final_status = str(final_report.get("status") or "")
    status_inferred_from_termination = bool(
        reported_final_status != "complete" and termination == "draft_complete"
    )
    effective_final_status = (
        "complete" if status_inferred_from_termination else reported_final_status
    )
    draft_slot = int(final_report.get("draft_slot") or 0)
    transitions = Counter(str(report.get("transition") or "unknown") for report in report_list)
    removed_pick_numbers = sum(
        len(report.get("removed_pick_numbers") or []) for report in report_list
    )
    edited_pick_numbers = sum(
        len(report.get("edited_pick_numbers") or []) for report in report_list
    )
    authoritative_rewrite = bool(
        removed_pick_numbers
        or edited_pick_numbers
        or any(name in transitions for name in ("undo", "rewrite"))
    )
    warnings = Counter(
        str(warning)
        for report in report_list
        for warning in report.get("warnings") or []
    )
    recommendation_reports = [
        report
        for report in report_list
        if report.get("is_user_turn") and report.get("recommendation")
    ]
    split_events = []
    recommendation_turns = []
    decision_counterfactuals = []
    pick_by_number = {int(pick.get("pick_no") or 0): pick for pick in final_picks}
    followed_primary = 0
    followed_evaluated = 0
    for report in recommendation_reports:
        recommendation = report.get("recommendation") or {}
        policies = list(recommendation.get("policies") or [])
        primary = policies[0] if policies else None
        primary_rows = (
            (recommendation.get("recommendations") or {}).get(primary) or []
            if primary
            else []
        )
        leader = primary_rows[0] if primary_rows else None
        current_pick = int(report.get("current_pick") or 0)
        actual = pick_by_number.get(current_pick)
        followed = None
        if leader and actual:
            followed = _row_matches_pick(leader, actual)
            followed_evaluated += 1
            followed_primary += int(followed)
        turn = {
            "pick": current_pick,
            "round": ((current_pick - 1) // teams) + 1 if current_pick and teams else None,
            "primary_policy": primary,
            "primary_leader": str((leader or {}).get("player_name") or ""),
            "actual_pick": _pick_name(actual) if actual else None,
            "followed_primary": followed,
        }
        decision_signal = dict(recommendation.get("decision_signal") or {})
        if decision_signal:
            turn["decision_signal"] = decision_signal
            counterfactual = {
                "pick": current_pick,
                "actual_pick": _pick_name(actual) if actual else None,
                **decision_signal,
            }
            planned_turn = (
                (recommendation.get("turn_horizon") or {}).get("planned_turn")
                or {}
            )
            if planned_turn:
                counterfactual["planned_turn"] = dict(planned_turn)
            decision_counterfactuals.append(counterfactual)
        recommendation_turns.append(turn)
        if recommendation.get("model_split") or recommendation.get("room_timing_split"):
            split_events.append(
                {
                    **turn,
                    "model_split": bool(recommendation.get("model_split")),
                    "model_split_policies": list(
                        recommendation.get("model_split_policies") or []
                    ),
                    "room_timing_split": bool(
                        recommendation.get("room_timing_split")
                    ),
                    "room_timing_split_policies": list(
                        recommendation.get("room_timing_split_policies") or []
                    ),
                    "market_leaders": dict(recommendation.get("market_leaders") or {}),
                    "league_leaders": dict(recommendation.get("league_leaders") or {}),
                    "generic_league_leaders": dict(
                        recommendation.get("baseline_league_leaders") or {}
                    ),
                }
            )
    sleeper_snapshot = session.get("sleeper_adp_snapshot") or {}
    by_slot = {}
    for slot in range(1, teams + 1):
        slot_picks = [
            pick for pick in final_picks if int(pick.get("draft_slot") or 0) == slot
        ]
        by_slot[str(slot)] = audit_pick_sequence_against_sleeper_adp(
            slot_picks, sleeper_snapshot
        )
    opponent_adherence = audit_pick_sequence_against_sleeper_adp(
        final_picks, sleeper_snapshot, excluded_draft_slot=draft_slot
    )
    scoring_warnings = []
    snapshot_scoring = str(sleeper_snapshot.get("scoring") or "")
    report_scoring = str(final_report.get("scoring") or "")
    if snapshot_scoring and report_scoring and snapshot_scoring != report_scoring:
        scoring_warnings.append(
            f"Sleeper ADP snapshot is {snapshot_scoring}; mock report is {report_scoring}"
        )
    user_roster = [
        pick for pick in final_picks if int(pick.get("draft_slot") or 0) == draft_slot
    ]
    position_counts = Counter(
        str((pick.get("metadata") or {}).get("position") or "")
        .upper()
        .replace("DEF", "DST")
        for pick in user_roster
    )
    survival_calibration = _survival_audit(report_list, final_picks)
    survival_calibration["status"] = (
        "review_required_after_authoritative_rewrite"
        if authoritative_rewrite
        else "observed_horizons_only"
    )
    cache_fetches = [
        dict(report.get("draft_picks_fetch") or {})
        for report in report_list
        if report.get("draft_picks_fetch")
    ]
    final_cache_fetch = cache_fetches[-1] if cache_fetches else {}
    return {
        "schema_version": 1,
        "generated_at": int(time.time()),
        "draft_id": str(final_report.get("draft_id") or session.get("draft_id") or ""),
        "termination": termination,
        "read_only": True,
        "recommendation_model_changed": False,
        "session_started_at": session.get("started_at"),
        "sleeper_adp_snapshot": {
            "captured_at": sleeper_snapshot.get("captured_at"),
            "season": sleeper_snapshot.get("season"),
            "scoring": snapshot_scoring,
            "adp_field": sleeper_snapshot.get("adp_field"),
            "sha256": session.get("sleeper_adp_snapshot_sha256"),
            "active_recommendation_use": False,
        },
        "reconciliation": {
            "logged_reports": len(report_list),
            "transition_counts": dict(sorted(transitions.items())),
            "removed_pick_numbers": removed_pick_numbers,
            "edited_pick_numbers": edited_pick_numbers,
            "authoritative_rewrite": authoritative_rewrite,
            "missed_turn_reports": sum(bool(report.get("missed_turn")) for report in report_list),
            "stale_reports": sum(bool(report.get("stale")) for report in report_list),
            "clock_risk_reports": sum(bool(report.get("clock_risk")) for report in report_list),
            "final_status": effective_final_status,
            "reported_final_status": reported_final_status,
            "status_inferred_from_termination": status_inferred_from_termination,
            "final_pick_count": len(final_picks),
            "expected_pick_count": expected_picks,
            "complete_board": bool(
                effective_final_status == "complete"
                and expected_picks is not None
                and len(final_picks) == expected_picks
            ),
            "warnings": dict(sorted(warnings.items())),
        },
        "latency_ms": {
            "poll": _numeric_summary(
                report.get("poll_latency_ms") for report in report_list
            ),
            "recommendation": _numeric_summary(
                report.get("recommendation_latency_ms") for report in report_list
            ),
        },
        "draft_picks_cache": {
            "cache_busting_active": any(
                bool(fetch.get("cache_busted")) for fetch in cache_fetches
            ),
            "logged_hit_reports": sum(
                str(fetch.get("cache_status") or "").upper() == "HIT"
                for fetch in cache_fetches
            ),
            "max_cache_age_seconds": max(
                (
                    float(fetch.get("max_cache_age_seconds") or 0.0)
                    for fetch in cache_fetches
                ),
                default=0.0,
            ),
            "status_counts": dict(final_cache_fetch.get("status_counts") or {}),
        },
        "recommendations": {
            "turns_logged": len(recommendation_turns),
            "followed_primary_evaluated": followed_evaluated,
            "followed_primary_count": followed_primary,
            "followed_primary_rate": (
                round(followed_primary / followed_evaluated, 6)
                if followed_evaluated
                else None
            ),
            "early_rounds": [
                turn for turn in recommendation_turns if int(turn.get("round") or 99) <= 4
            ],
            "all_turns": recommendation_turns,
            "decision_counterfactuals": decision_counterfactuals,
        },
        "timing_splits": {
            "events": split_events,
            "model_split_turns": sum(event["model_split"] for event in split_events),
            "room_timing_split_turns": sum(
                event["room_timing_split"] for event in split_events
            ),
        },
        "survival_calibration": survival_calibration,
        "sleeper_adp_adherence": {
            "status": "forward_same_day_snapshot",
            "warnings": scoring_warnings,
            "all_managers": audit_pick_sequence_against_sleeper_adp(
                final_picks, sleeper_snapshot
            ),
            "opponents_only": opponent_adherence,
            "by_draft_slot": by_slot,
        },
        "roster_construction": {
            "draft_slot": draft_slot,
            "position_counts": dict(sorted(position_counts.items())),
            "players": [
                {
                    "pick_no": int(pick.get("pick_no") or 0),
                    "player_name": _pick_name(pick),
                    "position": str(
                        (pick.get("metadata") or {}).get("position") or ""
                    )
                    .upper()
                    .replace("DEF", "DST"),
                }
                for pick in user_roster
            ],
            "external_grade": "not_recorded",
        },
    }


def load_mock_evidence(path: str | Path) -> tuple[dict[str, Any], list[dict[str, Any]], str]:
    session: dict[str, Any] | None = None
    reports = []
    termination = "open_or_interrupted"
    with Path(path).open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            value = json.loads(line)
            record_type = value.get("record_type")
            if record_type == "session" and session is None:
                session = value
            elif record_type == "state":
                reports.append(value.get("report") or {})
            elif record_type == "session_end":
                termination = str(value.get("termination") or termination)
            elif record_type not in {"session", "state", "session_end"}:
                raise ValueError(f"Unknown evidence record at line {line_number}")
    if session is None:
        raise ValueError("Evidence log does not contain a session header")
    return session, reports, termination


def audit_mock_evidence(path: str | Path) -> dict[str, Any]:
    session, reports, termination = load_mock_evidence(path)
    return build_mock_evidence_audit(session, reports, termination)


def evidence_paths(
    directory: str | Path, draft_id: str, started_at: int | None = None
) -> tuple[Path, Path]:
    timestamp = datetime.fromtimestamp(
        int(started_at if started_at is not None else time.time()), timezone.utc
    ).strftime("%Y%m%dT%H%M%SZ")
    base = Path(directory) / f"{draft_id}-{timestamp}"
    log_path = base.with_suffix(".ndjson")
    summary_path = Path(f"{base}.summary.json")
    counter = 2
    while log_path.exists() or summary_path.exists():
        alternative = Path(f"{base}-{counter}")
        log_path = alternative.with_suffix(".ndjson")
        summary_path = Path(f"{alternative}.summary.json")
        counter += 1
    return log_path, summary_path


@dataclass(slots=True)
class MockEvidenceRecorder:
    log_path: Path
    summary_path: Path
    sequence: int = 0
    finalized: bool = False

    @classmethod
    def create(
        cls,
        log_path: str | Path,
        summary_path: str | Path,
        sleeper_adp_snapshot_path: str | Path,
        metadata: Mapping[str, Any],
        started_at: int | None = None,
    ) -> "MockEvidenceRecorder":
        target = Path(log_path)
        summary = Path(summary_path)
        if target.exists() or summary.exists():
            raise FileExistsError("Evidence output already exists; choose a new session path")
        snapshot_path = Path(sleeper_adp_snapshot_path)
        raw_snapshot = snapshot_path.read_bytes()
        sleeper_snapshot = json.loads(raw_snapshot.decode("utf-8"))
        if not sleeper_snapshot.get("players") or not sleeper_snapshot.get("captured_at"):
            raise ValueError("Sleeper ADP snapshot is missing players or capture time")
        target.parent.mkdir(parents=True, exist_ok=True)
        summary.parent.mkdir(parents=True, exist_ok=True)
        recorder = cls(target, summary)
        recorder._append(
            {
                "record_type": "session",
                "schema_version": 1,
                "started_at": int(started_at if started_at is not None else time.time()),
                **dict(metadata),
                "sleeper_adp_snapshot_path": str(snapshot_path),
                "sleeper_adp_snapshot_sha256": hashlib.sha256(raw_snapshot).hexdigest(),
                "sleeper_adp_snapshot": sleeper_snapshot,
                "read_only": True,
                "recommendation_model_changed": False,
            }
        )
        return recorder

    def _append(self, value: Mapping[str, Any]) -> None:
        with self.log_path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(value, sort_keys=True, separators=(",", ":")))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())

    def record(self, report: Mapping[str, Any], recorded_at: float | None = None) -> bool:
        should_record = bool(
            str(report.get("transition") or "") != "duplicate"
            or str(report.get("status") or "").lower() == "complete"
            or (
                report.get("is_user_turn")
                and report.get("recommendation")
                and not report.get("recommendation_cached")
            )
            or report.get("missed_turn")
        )
        if not should_record:
            return False
        self.sequence += 1
        self._append(
            {
                "record_type": "state",
                "sequence": self.sequence,
                "recorded_at": float(
                    recorded_at if recorded_at is not None else time.time()
                ),
                "report": dict(report),
            }
        )
        return True

    def finalize(self, termination: str) -> dict[str, Any]:
        if self.finalized:
            return audit_mock_evidence(self.log_path)
        self._append(
            {
                "record_type": "session_end",
                "ended_at": int(time.time()),
                "termination": termination,
            }
        )
        self.finalized = True
        audit = audit_mock_evidence(self.log_path)
        self.summary_path.write_text(
            json.dumps(audit, indent=2, sort_keys=True), encoding="utf-8"
        )
        return audit
