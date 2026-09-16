from __future__ import annotations

import csv
import json
import os
import re
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from roster_theory.core.errors import CoverageIncomplete, IdentityIncomplete
from roster_theory.core.provenance import stable_hash
from roster_theory.expert_accuracy_history import (
    ACCURACY_URL,
    AnnualAccuracy,
    load_accuracy_history,
    parse_accuracy_page,
    write_accuracy_history,
)
from roster_theory.fantasypros import FantasyProsClient
from roster_theory.providers.cache import DailyRequestBudget, atomic_write_json
from roster_theory.rankings import ACCURACY_POSITIONS, load_accuracy, normalize_name
from roster_theory.sleeper import find_league_config
from roster_theory.trade.board_service import load_expert_pool
from roster_theory.trade.experts import (
    INSEASON_ACCURACY_URL,
    CurrentExpert,
    InSeasonAccuracy,
    normalize_current_experts,
    parse_inseason_accuracy_page,
    score_experts,
    write_inseason_accuracy,
)


SCHEMA_VERSION = "roster-theory.inputs/v1"
EVIDENCE_SCHEMA_VERSION = "roster-theory.expert-provider-evidence/v1"
POOL_AUDIT_SCHEMA_VERSION = "roster-theory.expert-pool/v1"
ARTIFACTS = ("draft-accuracy", "inseason-pool", "all")
SKILL_POSITIONS = ("QB", "RB", "WR", "TE")
_RECENCY_SHARES = (0.08, 0.15, 0.21, 0.26, 0.30)
_DRAFT_DETAIL_PATTERN = re.compile(
    r'\{"id":(?P<expert_id>\d+),"rank":(?P<overall>\d+),'
    r'"expert":(?P<expert>\{.*?\}|"(?:\\.|[^"\\])+")'
    r',"qb":(?P<qb>null|\d+),"rb":(?P<rb>null|\d+),'
    r'"wr":(?P<wr>null|\d+),"te":(?P<te>null|\d+),'
    r'"k":(?P<k>null|\d+),"dst":(?P<dst>null|\d+),'
    r'"idp":(?P<idp>null|\d+)',
)


@dataclass(frozen=True, slots=True)
class ExpertInputPaths:
    draft_category: Path
    draft_annual: Path
    inseason_accuracy: Path
    inseason_pool: Path
    audit: Path
    evidence_dir: Path
    budget: Path


@dataclass(frozen=True, slots=True)
class DraftAccuracyDetail:
    year: int
    expert_id: str
    expert_name: str
    ranks: tuple[tuple[str, int | None], ...]
    source_url: str
    captured_at: str
    payload_hash: str


def _expert_label(value: str) -> str:
    decoded = json.loads(value)
    label = str(decoded.get("label") if isinstance(decoded, dict) else decoded)
    name, separator, publisher = label.partition(" - ")
    name = name.strip()
    if separator and name in {"Site Rankings", "Staff Rankings"}:
        return f"{name} ({publisher.strip()})"
    return name


def _nullable_rank(value: str) -> int | None:
    return None if value == "null" else int(value)


def parse_draft_accuracy_details(
    html: str,
    year: int,
    *,
    source_url: str,
    captured_at: str,
    payload_hash: str,
) -> tuple[DraftAccuracyDetail, ...]:
    rows: list[DraftAccuracyDetail] = []
    for match in _DRAFT_DETAIL_PATTERN.finditer(html):
        ranks = (
            ("OVERALL", int(match.group("overall"))),
            *((position, _nullable_rank(match.group(position.lower()))) for position in ACCURACY_POSITIONS),
        )
        rows.append(
            DraftAccuracyDetail(
                year=year,
                expert_id=match.group("expert_id"),
                expert_name=_expert_label(match.group("expert")),
                ranks=tuple(ranks),
                source_url=source_url,
                captured_at=captured_at,
                payload_hash=payload_hash,
            )
        )
    if not rows:
        raise CoverageIncomplete(
            f"FantasyPros {year} Draft accuracy lacks category-level rows"
        )
    for position in ("OVERALL", *ACCURACY_POSITIONS):
        observed = sorted(
            rank for row in rows if (rank := dict(row.ranks).get(position)) is not None
        )
        if observed and observed != list(range(1, len(observed) + 1)):
            raise CoverageIncomplete(
                f"FantasyPros {year} {position} Draft accuracy is partial or duplicated"
            )
    return tuple(rows)


def _weights(years: Sequence[int]) -> dict[int, float]:
    if len(years) != len(_RECENCY_SHARES):
        raise ValueError("Expert input refresh requires exactly five historical seasons")
    return dict(zip(years, _RECENCY_SHARES))


def _percentile(rank: int, field_size: int) -> float:
    return 1.0 - (rank - 1.0) / (field_size - 1.0) if field_size > 1 else 1.0


def _coverage_factor(years: int) -> float:
    return 0.80 + 0.20 * min(5, max(0, years)) / 5


def draft_accuracy_master_rows(
    rows: Iterable[DraftAccuracyDetail],
    *,
    years: Sequence[int],
) -> list[dict[str, Any]]:
    source_rows = tuple(rows)
    expected_years = set(years)
    if {row.year for row in source_rows} != expected_years:
        raise CoverageIncomplete("Draft category accuracy does not cover every required season")

    names_by_id: dict[str, set[str]] = {}
    ids_by_name: dict[str, set[str]] = {}
    for row in source_rows:
        names_by_id.setdefault(row.expert_id, set()).add(row.expert_name)
        ids_by_name.setdefault(normalize_name(row.expert_name), set()).add(row.expert_id)
    ambiguous_ids = sorted(key for key, names in names_by_id.items() if len(names) != 1)
    ambiguous_names = sorted(key for key, ids in ids_by_name.items() if len(ids) != 1)
    if ambiguous_ids or ambiguous_names:
        raise IdentityIncomplete(
            "Ambiguous Draft expert identity across historical seasons: "
            + ", ".join((*ambiguous_ids, *ambiguous_names))
        )

    field_sizes: dict[tuple[int, str], int] = {}
    for year in years:
        year_rows = tuple(row for row in source_rows if row.year == year)
        for position in ("OVERALL", *ACCURACY_POSITIONS):
            field_sizes[(year, position)] = sum(
                dict(row.ranks).get(position) is not None for row in year_rows
            )

    by_expert: dict[str, list[DraftAccuracyDetail]] = {}
    for row in source_rows:
        by_expert.setdefault(row.expert_id, []).append(row)
    scored: dict[str, dict[str, tuple[float, int]]] = {}
    for expert_id, observations in by_expert.items():
        position_scores: dict[str, tuple[float, int]] = {}
        for position in ("OVERALL", *ACCURACY_POSITIONS):
            percentiles = [
                _percentile(rank, field_sizes[(row.year, position)])
                for row in observations
                if (rank := dict(row.ranks).get(position)) is not None
            ]
            if percentiles:
                average = sum(percentiles) / len(percentiles)
                position_scores[position] = (average, len(percentiles))
        scored[expert_id] = position_scores

    aggregate_ranks: dict[str, dict[str, int]] = {expert_id: {} for expert_id in scored}
    for position in ("OVERALL", *ACCURACY_POSITIONS):
        ordered = sorted(
            (
                (expert_id, values[position][0])
                for expert_id, values in scored.items()
                if position in values
            ),
            key=lambda item: (
                -item[1] * _coverage_factor(scored[item[0]][position][1]),
                names_by_id[item[0]].copy().pop(),
            ),
        )
        for rank, (expert_id, _) in enumerate(ordered, start=1):
            aggregate_ranks[expert_id][position] = rank

    ordered_ids = sorted(
        (expert_id for expert_id in scored if "OVERALL" in scored[expert_id]),
        key=lambda expert_id: (
            -scored[expert_id]["OVERALL"][0]
            * _coverage_factor(scored[expert_id]["OVERALL"][1]),
            names_by_id[expert_id].copy().pop(),
        ),
    )
    result: list[dict[str, Any]] = []
    for master_rank, expert_id in enumerate(ordered_ids, start=1):
        name = next(iter(names_by_id[expert_id]))
        values: dict[str, Any] = {
            "master_rank": master_rank,
            "expert_name": name,
            "master_score": f"{scored[expert_id]['OVERALL'][0] * _coverage_factor(scored[expert_id]['OVERALL'][1]):.6f}",
            "overall_rank": aggregate_ranks[expert_id]["OVERALL"],
            "overall_percentile": f"{scored[expert_id]['OVERALL'][0]:.6f}",
            "overall_years": scored[expert_id]["OVERALL"][1],
        }
        for position in ACCURACY_POSITIONS:
            if position in scored[expert_id]:
                values[position] = aggregate_ranks[expert_id][position]
                values[f"{position}_percentile"] = f"{scored[expert_id][position][0]:.6f}"
                values[f"{position}_years"] = scored[expert_id][position][1]
            else:
                values[position] = ""
                values[f"{position}_percentile"] = ""
                values[f"{position}_years"] = ""
        result.append(values)
    if not result:
        raise CoverageIncomplete("Draft accuracy aggregation produced no experts")
    return result


def _atomic_write_csv(path: Path, rows: Sequence[Mapping[str, Any]], fields: Sequence[str]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()
    return path


def write_draft_accuracy_master(rows: Sequence[Mapping[str, Any]], path: str | Path) -> Path:
    fields = [
        "master_rank",
        "expert_name",
        "master_score",
        "overall_rank",
        "overall_percentile",
        "overall_years",
    ]
    for position in ACCURACY_POSITIONS:
        fields.extend((position, f"{position}_percentile", f"{position}_years"))
    return _atomic_write_csv(Path(path), rows, fields)


def default_expert_input_paths(
    league: str,
    season: int,
    *,
    data_dir: str | Path = "data",
    draft_category: str | Path | None = None,
    draft_annual: str | Path | None = None,
    inseason_accuracy: str | Path | None = None,
    inseason_pool: str | Path | None = None,
    audit: str | Path | None = None,
    evidence_dir: str | Path | None = None,
    budget: str | Path | None = None,
) -> ExpertInputPaths:
    root = Path(data_dir)
    first, last = season - 5, season - 1
    label = f"{first}_{last}"
    return ExpertInputPaths(
        draft_category=Path(draft_category or root / "manual" / "fantasypros" / f"expert_accuracy_{label}.csv"),
        draft_annual=Path(draft_annual or root / "manual" / "fantasypros" / f"expert_accuracy_annual_{label}.csv"),
        inseason_accuracy=Path(inseason_accuracy or root / "manual" / "fantasypros" / f"inseason_accuracy_{label}.csv"),
        inseason_pool=Path(inseason_pool or root / "manual" / "policies" / league / str(season) / "inseason_experts.csv"),
        audit=Path(audit or root / "exports" / f"fantasypros_{season}" / f"{league}_inseason_expert_pool_audit.json"),
        evidence_dir=Path(evidence_dir or root / "cache" / "fantasypros" / str(season) / "expert_evidence"),
        budget=Path(budget or root / "cache" / "trade" / "fantasypros" / "daily_budget.json"),
    )


def _resolve_season(league: str, config_path: str | Path | None, season: int | None) -> int:
    configured = int(find_league_config(league, config_path).get("season") or 0)
    if configured <= 0:
        raise ValueError(f"League {league!r} does not declare a valid season")
    if season is not None and int(season) != configured:
        raise ValueError(
            f"Explicit season {season} does not match league {league!r} season {configured}"
        )
    return configured


def _read_budget(path: Path) -> DailyRequestBudget:
    if not path.is_file():
        return DailyRequestBudget()
    return DailyRequestBudget.from_json(json.loads(path.read_text(encoding="utf-8")))


def _http_text(url: str, timeout_seconds: float) -> str:
    request = Request(
        url,
        headers={"Accept": "text/html", "User-Agent": "RosterTheory/0.1"},
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            return response.read().decode("utf-8", errors="replace")
    except (HTTPError, URLError, TimeoutError) as exc:
        raise RuntimeError(f"Unable to load FantasyPros expert evidence: {exc}") from exc


def _evidence_path(directory: Path, kind: str, year: int) -> Path:
    return directory / f"{kind}_{year}.json"


def _evidence_record(kind: str, year: int, url: str, captured_at: str, payload: Any) -> dict[str, Any]:
    payload_hash = (
        sha256(payload.encode("utf-8")).hexdigest()
        if isinstance(payload, str)
        else stable_hash(payload)
    )
    return {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "kind": kind,
        "year": year,
        "source_url": url,
        "captured_at": captured_at,
        "payload_hash": payload_hash,
        "payload": payload,
    }


def _load_evidence(path: Path, *, kind: str, year: int) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("schema_version") != EVIDENCE_SCHEMA_VERSION:
        raise ValueError(f"Unsupported expert evidence schema in {path}")
    if value.get("kind") != kind or int(value.get("year") or 0) != year:
        raise ValueError(f"Expert evidence kind/year mismatch in {path}")
    payload = value.get("payload")
    expected = (
        sha256(payload.encode("utf-8")).hexdigest()
        if isinstance(payload, str)
        else stable_hash(payload)
    )
    if value.get("payload_hash") != expected:
        raise ValueError(f"Expert evidence payload hash mismatch in {path}")
    return value


def _page_evidence(
    kind: str,
    years: Sequence[int],
    *,
    url_template: str,
    evidence_dir: Path,
    replay_dir: Path | None,
    captured_at: str,
    minimum_interval: float,
    timeout_seconds: float,
    fetch_text: Callable[[str, float], str],
) -> tuple[dict[str, Any], ...]:
    records: list[dict[str, Any]] = []
    last_request = 0.0
    for year in years:
        source_path = _evidence_path(replay_dir, kind, year) if replay_dir else None
        if source_path is not None:
            records.append(_load_evidence(source_path, kind=kind, year=year))
            continue
        elapsed = time.monotonic() - last_request
        if last_request and elapsed < minimum_interval:
            time.sleep(minimum_interval - elapsed)
        url = url_template.format(year=year)
        payload = fetch_text(url, timeout_seconds)
        last_request = time.monotonic()
        record = _evidence_record(kind, year, url, captured_at, payload)
        atomic_write_json(_evidence_path(evidence_dir, kind, year), record)
        records.append(record)
    return tuple(records)


def _validate_current_identity(current: Sequence[CurrentExpert]) -> None:
    ids: set[str] = set()
    names: dict[str, str] = {}
    for expert in current:
        if expert.expert_id in ids:
            raise IdentityIncomplete(f"Duplicate current expert ID {expert.expert_id}")
        ids.add(expert.expert_id)
        key = normalize_name(expert.name)
        prior = names.get(key)
        if prior is not None and prior != expert.expert_id:
            raise IdentityIncomplete(
                f"Ambiguous current expert identity for normalized name {expert.name!r}"
            )
        names[key] = expert.expert_id


def build_inseason_pool(
    accuracy: Sequence[InSeasonAccuracy],
    current: Sequence[CurrentExpert],
    *,
    now: datetime,
    years: Sequence[int],
    pool_size: int = 5,
    maximum_source_count: int = 2,
    freshness_hours: float = 48.0,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    _validate_current_identity(current)
    scores = score_experts(accuracy, weights=_weights(years))
    current_by_id = {row.expert_id: row for row in current}
    selected: list[tuple[Any, CurrentExpert]] = []
    source_counts: dict[str, int] = {}
    audit: list[dict[str, Any]] = []
    normalized_now = now.astimezone(timezone.utc)
    for score in scores:
        active = current_by_id.get(score.expert_id)
        reason = "selected"
        if active is None:
            reason = "not_currently_available"
        else:
            updates = dict(active.position_updates)
            if any(position not in updates for position in SKILL_POSITIONS):
                reason = "incomplete_position_availability"
            else:
                parsed_updates = {
                    position: datetime.fromisoformat(updates[position].replace("Z", "+00:00"))
                    for position in SKILL_POSITIONS
                }
                if any(value.tzinfo is None for value in parsed_updates.values()):
                    reason = "undated_position_availability"
                elif any(
                    not 0 <= (normalized_now - value.astimezone(timezone.utc)).total_seconds()
                    <= freshness_hours * 3600
                    for value in parsed_updates.values()
                ):
                    reason = "stale_position_availability"
                elif source_counts.get(active.source_name.casefold(), 0) >= maximum_source_count:
                    reason = "source_concentration_limit"
                elif len(selected) >= pool_size:
                    reason = "below_selection_cutoff"
        if reason == "selected" and active is not None:
            selected.append((score, active))
            key = active.source_name.casefold()
            source_counts[key] = source_counts.get(key, 0) + 1
        audit.append(
            {
                "expert_id": score.expert_id,
                "expert_name": active.name if active else score.expert_name,
                "source_name": active.source_name if active else score.source_name,
                "status": reason,
                "historical_score": round(score.score, 8),
                "seasons": score.seasons,
                "annual_ranks": [list(row) for row in score.annual_ranks],
                "position_updates": dict(active.position_updates) if active else {},
            }
        )
    scored_ids = {row.expert_id for row in scores}
    for active in current:
        if active.expert_id not in scored_ids:
            audit.append(
                {
                    "expert_id": active.expert_id,
                    "expert_name": active.name,
                    "source_name": active.source_name,
                    "status": "insufficient_historical_accuracy",
                    "historical_score": None,
                    "seasons": 0,
                    "annual_ranks": [],
                    "position_updates": dict(active.position_updates),
                }
            )
    if len(selected) != pool_size:
        raise CoverageIncomplete(
            f"Only {len(selected)} historically eligible, fresh experts satisfy a pool of {pool_size}"
        )
    score_total = sum(score.score for score, _ in selected)
    pool_rows = [
        {
            "expert_id": score.expert_id,
            "expert_name": active.name,
            "source_name": active.source_name,
            "weight": f"{score.score / score_total:.12f}",
            "historical_score": f"{score.score:.8f}",
            "seasons": score.seasons,
            "annual_ranks": "|".join(f"{year}:{rank}" for year, rank in score.annual_ranks),
            "accuracy_authority": "weekly_inseason",
            "current_horizon": "ROS",
            "selection_method": "recency_weighted_percentile_with_coverage_and_source_cap",
            "freshness_hours": f"{freshness_hours:g}",
            "position_updates": json.dumps(dict(active.position_updates), sort_keys=True),
        }
        for score, active in selected
    ]
    return pool_rows, sorted(audit, key=lambda row: (row["status"] != "selected", row["expert_id"]))


def _write_pool(rows: Sequence[Mapping[str, Any]], path: Path) -> Path:
    return _atomic_write_csv(
        path,
        rows,
        (
            "expert_id",
            "expert_name",
            "source_name",
            "weight",
            "historical_score",
            "seasons",
            "annual_ranks",
            "accuracy_authority",
            "current_horizon",
            "selection_method",
            "freshness_hours",
            "position_updates",
        ),
    )


def _artifact_report(
    artifact_id: str,
    path: Path,
    *,
    authority: str,
    scope: str,
    horizon: str,
    status: str,
    action: str,
    reason: str,
    captured_at: str | None = None,
) -> dict[str, Any]:
    return {
        "id": artifact_id,
        "authority": authority,
        "scope": scope,
        "horizon": horizon,
        "status": status,
        "freshness_rule": "validate_each_use",
        "path": str(path),
        "source": "FantasyPros authorized evidence",
        "captured_at": captured_at,
        "content_hash": sha256(path.read_bytes()).hexdigest() if path.is_file() else None,
        "action": action,
        "reason": reason,
    }


def _result(
    operation: str,
    league: str,
    season: int,
    *,
    status: str,
    dry_run: bool,
    artifacts: Sequence[Mapping[str, Any]],
    provider_calls: Sequence[Mapping[str, Any]] = (),
    writes: Sequence[Mapping[str, Any]] = (),
    errors: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    counts = {"ready": 0, "refreshed": 0, "blocked": 0, "declined": 0}
    for artifact in artifacts:
        artifact_status = str(artifact.get("status") or "")
        if artifact_status in counts:
            counts[artifact_status] += 1
    return {
        "schema_version": SCHEMA_VERSION,
        "operation": operation,
        "status": status,
        "league": league,
        "season": season,
        "assistant": "all",
        "mode": "replay" if any(call.get("mode") == "replay" for call in provider_calls) else "auto",
        "dry_run": dry_run,
        "artifacts": list(artifacts),
        "provider_calls": list(provider_calls),
        "writes": list(writes),
        "summary": counts,
        "errors": list(errors),
        "sleeper_write_performed": False,
    }


def _current_expert_evidence(
    season: int,
    *,
    evidence_dir: Path,
    replay_dir: Path | None,
    captured_at: str,
    client: FantasyProsClient,
) -> dict[str, Any]:
    path = _evidence_path(replay_dir or evidence_dir, "current_experts", season)
    if replay_dir is not None:
        return _load_evidence(path, kind="current_experts", year=season)
    payload = client.ranking_experts(season, type="ROS", include_overall="true")
    record = _evidence_record(
        "current_experts",
        season,
        f"{client.base_url.rstrip('/')}/nfl/{season}/rankings/experts",
        captured_at,
        payload,
    )
    atomic_write_json(path, record)
    return record


def refresh_expert_inputs(
    league: str,
    *,
    config_path: str | Path | None = None,
    season: int | None = None,
    artifact: str = "all",
    data_dir: str | Path = "data",
    draft_category: str | Path | None = None,
    draft_annual: str | Path | None = None,
    inseason_accuracy: str | Path | None = None,
    inseason_pool: str | Path | None = None,
    audit: str | Path | None = None,
    evidence_dir: str | Path | None = None,
    budget: str | Path | None = None,
    replay_dir: str | Path | None = None,
    dry_run: bool = False,
    minimum_interval: float = 1.0,
    timeout_seconds: float = 20.0,
    pool_size: int = 5,
    maximum_source_count: int = 2,
    freshness_hours: float = 48.0,
    now: datetime | None = None,
    client: FantasyProsClient | None = None,
    fetch_text: Callable[[str, float], str] = _http_text,
) -> dict[str, Any]:
    if artifact not in ARTIFACTS:
        raise ValueError(f"Unsupported expert artifact: {artifact}")
    if minimum_interval < 1.0:
        raise ValueError("FantasyPros minimum request interval cannot be below one second")
    if pool_size < 1 or maximum_source_count < 1 or freshness_hours <= 0:
        raise ValueError("Expert pool limits and freshness must be positive")
    resolved_season = _resolve_season(league, config_path, season)
    years = tuple(range(resolved_season - 5, resolved_season))
    paths = default_expert_input_paths(
        league,
        resolved_season,
        data_dir=data_dir,
        draft_category=draft_category,
        draft_annual=draft_annual,
        inseason_accuracy=inseason_accuracy,
        inseason_pool=inseason_pool,
        audit=audit,
        evidence_dir=evidence_dir,
        budget=budget,
    )
    replay = Path(replay_dir) if replay_dir else None
    call_count = 0 if replay else (5 if artifact in {"draft-accuracy", "all"} else 0) + (6 if artifact in {"inseason-pool", "all"} else 0)
    budget_state = _read_budget(paths.budget)
    budget_state.reserve(call_count, today=(now or datetime.now(timezone.utc)).date())
    planned_calls = [
        {
            "provider": "FantasyPros",
            "endpoint_class": (
                "saved expert evidence" if replay else "draft/in-season accuracy and current experts"
            ),
            "budget_cost": call_count,
            "cache_disposition": "replay" if replay else "write replayable evidence",
            "status": "planned" if dry_run else "completed",
            "mode": "replay" if replay else "provider",
        }
    ]
    planned_paths: list[tuple[str, Path]] = []
    if artifact in {"draft-accuracy", "all"}:
        planned_paths.extend(
            (("accuracy.draft.category", paths.draft_category), ("accuracy.draft.annual", paths.draft_annual))
        )
    if artifact in {"inseason-pool", "all"}:
        planned_paths.extend(
            (
                ("accuracy.inseason", paths.inseason_accuracy),
                ("experts.inseason_pool", paths.inseason_pool),
                ("experts.inseason_pool.audit", paths.audit),
            )
        )
    if dry_run:
        artifacts = [
            _artifact_report(
                artifact_id,
                path,
                authority="provider_fact" if "accuracy" in artifact_id else "derived_fact",
                scope="shared" if "accuracy" in artifact_id else "league",
                horizon=f"historical:{years[0]}-{years[-1]}" if "accuracy" in artifact_id else "ROS",
                status="refresh_planned",
                action="replay" if replay else "refresh",
                reason="dry-run; no provider call or local write performed",
            )
            for artifact_id, path in planned_paths
        ]
        planned_writes = [
            {"artifact": key, "destination": str(path), "overwrite": path.exists(), "status": "planned"}
            for key, path in planned_paths
        ]
        if not replay:
            planned_writes.append(
                {
                    "artifact": "provider.expert_evidence",
                    "destination": str(paths.evidence_dir),
                    "overwrite": paths.evidence_dir.exists(),
                    "status": "planned",
                }
            )
        if call_count:
            planned_writes.append(
                {
                    "artifact": "provider.request_budget",
                    "destination": str(paths.budget),
                    "overwrite": paths.budget.exists(),
                    "status": "planned",
                }
            )
        return _result(
            "refresh",
            league,
            resolved_season,
            status="planned",
            dry_run=True,
            artifacts=artifacts,
            provider_calls=planned_calls,
            writes=planned_writes,
        )

    if call_count:
        # Reserve before the first request so a partial provider failure cannot
        # make a retry invisible to the shared daily budget.
        atomic_write_json(paths.budget, budget_state.to_json())
    captured = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    captured_at = captured.isoformat()
    artifacts: list[dict[str, Any]] = []
    writes: list[dict[str, Any]] = []
    if not replay:
        writes.append(
            {
                "artifact": "provider.expert_evidence",
                "destination": str(paths.evidence_dir),
                "overwrite": True,
                "status": "completed",
            }
        )
    if call_count:
        writes.append(
            {
                "artifact": "provider.request_budget",
                "destination": str(paths.budget),
                "overwrite": True,
                "status": "completed",
            }
        )
    if artifact in {"draft-accuracy", "all"}:
        evidence = _page_evidence(
            "draft_accuracy",
            years,
            url_template=ACCURACY_URL,
            evidence_dir=paths.evidence_dir,
            replay_dir=replay,
            captured_at=captured_at,
            minimum_interval=minimum_interval,
            timeout_seconds=timeout_seconds,
            fetch_text=fetch_text,
        )
        annual: list[AnnualAccuracy] = []
        detail: list[DraftAccuracyDetail] = []
        for record in evidence:
            year = int(record["year"])
            payload = str(record["payload"])
            annual.extend(parse_accuracy_page(payload, year))
            detail.extend(
                parse_draft_accuracy_details(
                    payload,
                    year,
                    source_url=str(record["source_url"]),
                    captured_at=str(record["captured_at"]),
                    payload_hash=str(record["payload_hash"]),
                )
            )
        write_accuracy_history(annual, paths.draft_annual)
        write_draft_accuracy_master(
            draft_accuracy_master_rows(detail, years=years), paths.draft_category
        )
        validate_draft_accuracy(paths.draft_category, paths.draft_annual, years=years)
        for artifact_id, path in (
            ("accuracy.draft.category", paths.draft_category),
            ("accuracy.draft.annual", paths.draft_annual),
        ):
            artifacts.append(
                _artifact_report(
                    artifact_id,
                    path,
                    authority="provider_fact",
                    scope="shared",
                    horizon=f"historical:{years[0]}-{years[-1]}",
                    status="refreshed",
                    action="replay" if replay else "refresh",
                    reason="complete five-season Draft accuracy evidence",
                    captured_at=captured_at,
                )
            )
            writes.append({"artifact": artifact_id, "destination": str(path), "overwrite": True, "status": "completed"})

    if artifact in {"inseason-pool", "all"}:
        evidence = _page_evidence(
            "inseason_accuracy",
            years,
            url_template=INSEASON_ACCURACY_URL,
            evidence_dir=paths.evidence_dir,
            replay_dir=replay,
            captured_at=captured_at,
            minimum_interval=minimum_interval,
            timeout_seconds=timeout_seconds,
            fetch_text=fetch_text,
        )
        accuracy_rows: list[InSeasonAccuracy] = []
        for record in evidence:
            accuracy_rows.extend(
                parse_inseason_accuracy_page(
                    str(record["payload"]),
                    int(record["year"]),
                    retrieved_at=str(record["captured_at"]),
                    source_url=str(record["source_url"]),
                )
            )
        if not replay:
            time.sleep(minimum_interval)
        current_record = _current_expert_evidence(
            resolved_season,
            evidence_dir=paths.evidence_dir,
            replay_dir=replay,
            captured_at=captured_at,
            client=client or FantasyProsClient(),
        )
        current = normalize_current_experts(current_record["payload"])
        pool_rows, selection_audit = build_inseason_pool(
            tuple(accuracy_rows),
            current,
            now=captured,
            years=years,
            pool_size=pool_size,
            maximum_source_count=maximum_source_count,
            freshness_hours=freshness_hours,
        )
        write_inseason_accuracy(accuracy_rows, paths.inseason_accuracy)
        _write_pool(pool_rows, paths.inseason_pool)
        audit_value = {
            "schema_version": POOL_AUDIT_SCHEMA_VERSION,
            "league": league,
            "season": resolved_season,
            "horizon": "ROS",
            "accuracy_authority": "weekly_inseason",
            "historical_years": list(years),
            "captured_at": captured_at,
            "selection_policy": {
                "recency_weights": _weights(years),
                "pool_size": pool_size,
                "minimum_seasons": 2,
                "coverage_floor": 0.8,
                "maximum_source_count": maximum_source_count,
                "freshness_hours": freshness_hours,
                "required_positions": list(SKILL_POSITIONS),
                "preseason_proxy_permitted": False,
            },
            "provider_evidence_hashes": {
                str(record["year"]): record["payload_hash"] for record in evidence
            }
            | {"current_experts": current_record["payload_hash"]},
            "selection": selection_audit,
            "pool_hash": stable_hash(pool_rows),
            "sleeper_write_performed": False,
        }
        atomic_write_json(paths.audit, audit_value)
        validate_inseason_pool(
            paths.inseason_accuracy,
            paths.inseason_pool,
            paths.audit,
            years=years,
            league=league,
            season=resolved_season,
            pool_size=pool_size,
        )
        for artifact_id, path, authority, scope in (
            ("accuracy.inseason", paths.inseason_accuracy, "provider_fact", "shared"),
            ("experts.inseason_pool", paths.inseason_pool, "derived_fact", "league"),
            ("experts.inseason_pool.audit", paths.audit, "derived_fact", "league"),
        ):
            artifacts.append(
                _artifact_report(
                    artifact_id,
                    path,
                    authority=authority,
                    scope=scope,
                    horizon=f"historical:{years[0]}-{years[-1]}" if authority == "provider_fact" else "ROS",
                    status="refreshed",
                    action="replay" if replay else "refresh",
                    reason="auditable weekly in-season authority; no preseason proxy",
                    captured_at=captured_at,
                )
            )
            writes.append({"artifact": artifact_id, "destination": str(path), "overwrite": True, "status": "completed"})

    return _result(
        "refresh",
        league,
        resolved_season,
        status="ready",
        dry_run=False,
        artifacts=artifacts,
        provider_calls=planned_calls,
        writes=writes,
    )


def validate_draft_accuracy(
    category_path: str | Path,
    annual_path: str | Path,
    *,
    years: Sequence[int],
) -> None:
    records = load_accuracy(category_path)
    if not records:
        raise CoverageIncomplete("Draft category accuracy contains no usable experts")
    with Path(category_path).open("r", encoding="utf-8-sig", newline="") as handle:
        fields = set((csv.DictReader(handle).fieldnames or ()))
    required = {"master_rank", "expert_name", "master_score", "overall_years"}
    required.update(ACCURACY_POSITIONS)
    missing = required - fields
    if missing:
        raise CoverageIncomplete(
            "Draft category accuracy is missing columns: " + ", ".join(sorted(missing))
        )
    annual = load_accuracy_history(annual_path)
    if {row.year for row in annual} != set(years):
        raise CoverageIncomplete("Draft annual accuracy does not cover every required season")
    if len({(row.year, row.expert_id) for row in annual}) != len(annual):
        raise IdentityIncomplete("Draft annual accuracy repeats a provider expert ID within a season")


def validate_inseason_pool(
    accuracy_path: str | Path,
    pool_path: str | Path,
    audit_path: str | Path,
    *,
    years: Sequence[int],
    league: str,
    season: int,
    pool_size: int = 5,
) -> None:
    from roster_theory.trade.experts import load_inseason_accuracy

    accuracy = load_inseason_accuracy(accuracy_path)
    if {row.year for row in accuracy} != set(years):
        raise CoverageIncomplete("In-season accuracy does not cover every required season")
    pool = load_expert_pool(pool_path)
    if len(pool) != pool_size or len({row.expert_id for row in pool}) != len(pool):
        raise CoverageIncomplete(
            f"In-season expert pool must contain {pool_size} unique experts"
        )
    with Path(pool_path).open("r", encoding="utf-8-sig", newline="") as handle:
        rows = tuple(csv.DictReader(handle))
    required = {
        "expert_id",
        "expert_name",
        "source_name",
        "weight",
        "historical_score",
        "seasons",
        "annual_ranks",
        "accuracy_authority",
        "current_horizon",
        "selection_method",
        "freshness_hours",
        "position_updates",
    }
    if not rows or required - set(rows[0]):
        raise CoverageIncomplete("In-season expert pool lacks the auditable consumer schema")
    if any(row["accuracy_authority"] != "weekly_inseason" for row in rows):
        raise CoverageIncomplete("In-season pool uses an undeclared or preseason authority")
    if any(row["current_horizon"] != "ROS" for row in rows):
        raise CoverageIncomplete("In-season pool does not declare the ROS horizon")
    audit = json.loads(Path(audit_path).read_text(encoding="utf-8"))
    if audit.get("schema_version") != POOL_AUDIT_SCHEMA_VERSION:
        raise ValueError("Unsupported in-season expert-pool audit schema")
    if audit.get("league") != league or int(audit.get("season") or 0) != season:
        raise CoverageIncomplete("In-season expert-pool audit belongs to another league or season")
    if audit.get("accuracy_authority") != "weekly_inseason":
        raise CoverageIncomplete("In-season expert-pool audit uses the wrong authority")
    if bool((audit.get("selection_policy") or {}).get("preseason_proxy_permitted")):
        raise CoverageIncomplete("In-season pool unexpectedly permits a preseason proxy")


def inspect_expert_inputs(
    league: str,
    *,
    config_path: str | Path | None = None,
    season: int | None = None,
    artifact: str = "all",
    data_dir: str | Path = "data",
    **path_overrides: Any,
) -> dict[str, Any]:
    resolved_season = _resolve_season(league, config_path, season)
    years = tuple(range(resolved_season - 5, resolved_season))
    paths = default_expert_input_paths(
        league, resolved_season, data_dir=data_dir, **path_overrides
    )
    checks: list[tuple[str, Path, Callable[[], None]]] = []
    if artifact in {"draft-accuracy", "all"}:
        checks.extend(
            (
                ("accuracy.draft.category", paths.draft_category, lambda: validate_draft_accuracy(paths.draft_category, paths.draft_annual, years=years)),
                ("accuracy.draft.annual", paths.draft_annual, lambda: validate_draft_accuracy(paths.draft_category, paths.draft_annual, years=years)),
            )
        )
    if artifact in {"inseason-pool", "all"}:
        validate = lambda: validate_inseason_pool(
            paths.inseason_accuracy,
            paths.inseason_pool,
            paths.audit,
            years=years,
            league=league,
            season=resolved_season,
        )
        checks.extend(
            (
                ("accuracy.inseason", paths.inseason_accuracy, validate),
                ("experts.inseason_pool", paths.inseason_pool, validate),
                ("experts.inseason_pool.audit", paths.audit, validate),
            )
        )
    artifacts: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for artifact_id, path, validate in checks:
        try:
            validate()
            artifact_status, reason = "ready", "complete and valid"
        except (OSError, ValueError, CoverageIncomplete, IdentityIncomplete) as exc:
            artifact_status, reason = "blocked", str(exc)
            errors.append(
                {
                    "type": type(exc).__name__,
                    "artifact": artifact_id,
                    "reason": str(exc),
                    "next_command": f"roster-theory inputs experts refresh {league} --artifact {artifact}",
                }
            )
        artifacts.append(
            _artifact_report(
                artifact_id,
                path,
                authority="provider_fact" if "accuracy" in artifact_id else "derived_fact",
                scope="shared" if "accuracy" in artifact_id else "league",
                horizon=f"historical:{years[0]}-{years[-1]}" if "accuracy" in artifact_id else "ROS",
                status=artifact_status,
                action="validate",
                reason=reason,
            )
        )
    return _result(
        "inspect",
        league,
        resolved_season,
        status="ready" if not errors else "blocked",
        dry_run=False,
        artifacts=artifacts,
        errors=errors,
    )
