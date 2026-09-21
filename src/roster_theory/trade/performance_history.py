"""Ignored, league-scoped prospective captures for Trade performance context.

Completed outcomes are imported into the same local file from an authorized
source. No current projection is ever substituted for a missing pregame one.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from roster_theory.core.provenance import stable_hash
from roster_theory.providers.cache import atomic_write_json
from roster_theory.trade.board_service import BoardRefreshResult
from roster_theory.trade.performance import (
    CompletedPerformanceOutcome,
    PerformanceEvidence,
    PerformancePolicy,
    PregameExpectation,
    build_performance_evidence,
)
from roster_theory.trade.snapshot import SKILL_POSITIONS


@dataclass(frozen=True, slots=True)
class PerformanceHistoryResult:
    path: Path
    evidence: PerformanceEvidence | None
    captured_expectations: int
    total_expectations: int
    total_outcomes: int
    compatible_contexts: int
    status: str
    history_hash: str


def default_performance_history_path(
    league_key: str, season: int, scoring_fingerprint: str
) -> Path:
    identity = (league_key, season, scoring_fingerprint)
    return Path("data/cache/trade/performance") / f"{stable_hash(identity)[:20]}.json"


def _datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("Performance history timestamps must have a timezone")
    return result


def _load(path: Path, league_key: str, season: int, scoring: str) -> dict:
    if not path.is_file():
        return {"schema_version": 1, "league_key": league_key, "season": season,
                "scoring_fingerprint": scoring, "pregame_expectations": [],
                "completed_outcomes": []}
    value = json.loads(path.read_text(encoding="utf-8"))
    if (value.get("schema_version") != 1 or value.get("league_key") != league_key
            or value.get("season") != season
            or value.get("scoring_fingerprint") != scoring):
        raise ValueError("Performance history league, season, or scoring does not match")
    if not isinstance(value.get("pregame_expectations"), list) or not isinstance(
        value.get("completed_outcomes"), list
    ):
        raise ValueError("Performance history rows must be lists")
    return value


def _expectation(row: dict) -> PregameExpectation:
    return PregameExpectation(**{**row, "captured_at": _datetime(row["captured_at"])})


def _outcome(row: dict) -> CompletedPerformanceOutcome:
    return CompletedPerformanceOutcome(**{
        **row,
        "game_started_at": _datetime(row.get("game_started_at")),
        "game_completed_at": _datetime(row.get("game_completed_at")),
        "captured_at": _datetime(row["captured_at"]),
    })


def update_performance_history(
    refresh: BoardRefreshResult,
    *,
    policy: PerformancePolicy,
    path: str | Path | None = None,
) -> PerformanceHistoryResult:
    """Append current weekly expectations, then build prior-week context only."""
    snapshot = refresh.refresh.snapshot
    week = snapshot.manifest.current_week
    scoring = stable_hash(snapshot.league.scoring)
    target = (
        Path(path) if path is not None else default_performance_history_path(
            snapshot.league_key, snapshot.league.season, scoring,
        )
    )
    value = _load(target, snapshot.league_key, snapshot.league.season, scoring)
    expectations = [_expectation(row) for row in value["pregame_expectations"]]
    outcomes = [_outcome(row) for row in value["completed_outcomes"]]
    # Validation happens before any write. An incomplete or foreign row cannot
    # contaminate a prospective capture ledger.
    if week > 1:
        build_performance_evidence(
            snapshot.league_key, snapshot.league.season, week - 1,
            snapshot.captured_at, expectations=expectations, outcomes=outcomes,
            policy=policy,
        )
    positions = {
        row.player_id: row.position for row in refresh.selected_final.players
        if row.position in SKILL_POSITIONS
    }
    consensus_ranks: dict[str, set[float]] = {}
    for rank in getattr(refresh, "weekly_rankings", ()):
        if (
            rank.player_id in positions
            and rank.position == positions[rank.player_id]
            and rank.expert_id is None
            and rank.position_rank is not None
        ):
            consensus_ranks.setdefault(rank.player_id, set()).add(rank.position_rank)
    existing = {(row.player_id, row.week, row.captured_at, row.source) for row in expectations}
    added = 0
    if snapshot.current and week > 0:
        for projection in refresh.weekly_projections:
            if projection.week != week or projection.player_id not in positions:
                continue
            if projection.coverage_status != "complete":
                continue
            row = PregameExpectation(
                league_key=snapshot.league_key,
                season=snapshot.league.season,
                player_id=projection.player_id,
                week=week,
                position=positions[projection.player_id],
                captured_at=snapshot.captured_at,
                projected_points=projection.league_points,
                projected_position_rank=(
                    next(iter(consensus_ranks[projection.player_id]))
                    if len(consensus_ranks.get(projection.player_id, ())) == 1 else None
                ),
                scoring_fingerprint=scoring,
                source=projection.source,
            )
            key = (row.player_id, row.week, row.captured_at, row.source)
            if key not in existing:
                expectations.append(row)
                existing.add(key)
                added += 1
    value["pregame_expectations"] = [asdict(row) for row in expectations]
    # Preserve imported outcomes unchanged. The ledger is local and ignored.
    atomic_write_json(target, value)
    evidence = (
        build_performance_evidence(
            snapshot.league_key, snapshot.league.season, week - 1,
            snapshot.captured_at, expectations=expectations, outcomes=outcomes,
            policy=policy,
        ) if week > 1 else None
    )
    compatible = sum(row.compatible for row in evidence.contexts) if evidence else 0
    return PerformanceHistoryResult(
        path=target,
        evidence=evidence,
        captured_expectations=added,
        total_expectations=len(expectations),
        total_outcomes=len(outcomes),
        compatible_contexts=compatible,
        status="SUPPORTED" if compatible else "INSUFFICIENT_HISTORY",
        history_hash=stable_hash(value),
    )


def import_completed_outcomes(
    history_path: str | Path, import_path: str | Path
) -> int:
    """Merge verified, source-attributed outcomes without replacing captures."""
    target = Path(history_path)
    if not target.is_file():
        raise FileNotFoundError("Capture pregame expectations before importing outcomes")
    value = json.loads(target.read_text(encoding="utf-8"))
    value = _load(
        target, str(value["league_key"]), int(value["season"]),
        str(value["scoring_fingerprint"]),
    )
    incoming = json.loads(Path(import_path).read_text(encoding="utf-8"))
    for field in ("league_key", "season", "scoring_fingerprint"):
        if incoming.get(field) != value[field]:
            raise ValueError(f"Completed outcome import has incompatible {field}")
    if incoming.get("schema_version") != 1 or not isinstance(
        incoming.get("completed_outcomes"), list
    ):
        raise ValueError("Completed outcome import schema is incomplete")
    existing = {
        (row.player_id, row.week, row.captured_at, row.source): row
        for row in (_outcome(item) for item in value["completed_outcomes"])
    }
    added = 0
    for item in incoming["completed_outcomes"]:
        row = _outcome(item)
        if (
            row.league_key != value["league_key"]
            or row.season != value["season"]
            or row.scoring_fingerprint != value["scoring_fingerprint"]
            or not row.player_id or not row.source
            or row.availability not in {"PLAYED", "BYE", "INACTIVE", "PARTIAL", "UNKNOWN"}
            or row.game_started_at is None
            or row.game_completed_at is None
            or row.game_started_at >= row.game_completed_at
            or row.captured_at < row.game_completed_at
            or (row.availability == "PLAYED" and row.actual_points is None
                and row.actual_position_rank is None)
        ):
            raise ValueError("Completed outcome lacks verified timing, availability, or identity")
        key = (row.player_id, row.week, row.captured_at, row.source)
        if key in existing and existing[key] != row:
            raise ValueError("Conflicting completed outcome import row")
        if key not in existing:
            value["completed_outcomes"].append(asdict(row))
            existing[key] = row
            added += 1
    atomic_write_json(target, value)
    return added


def main() -> None:
    parser = argparse.ArgumentParser(description="Import verified local Trade outcomes")
    parser.add_argument("history", type=Path)
    parser.add_argument("outcomes", type=Path)
    args = parser.parse_args()
    added = import_completed_outcomes(args.history, args.outcomes)
    print(json.dumps({"added_outcomes": added, "history": str(args.history)}))


if __name__ == "__main__":
    main()
