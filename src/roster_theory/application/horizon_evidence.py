"""Read Draft anchors and persist prospective in-season horizon evidence."""

from __future__ import annotations

import csv
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from roster_theory.core.errors import CoverageIncomplete
from roster_theory.core.models import RankObservation
from roster_theory.core.provenance import stable_hash
from roster_theory.inseason.horizons import EARLY_SEASON_DRAFT_ANCHOR, SnapshotDatum, parse_utc
from roster_theory.providers.cache import atomic_write_json


def load_draft_anchor(
    path: str | Path,
    *,
    updated_at: str,
    scope: str = "skills_half_ppr",
    scoring: str | None = None,
) -> tuple[tuple[RankObservation, ...], tuple[RankObservation, ...]]:
    def optional_float(value: str | None) -> float | None:
        return float(value) if value not in (None, "") else None

    with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
        rows = tuple(row for row in csv.DictReader(handle) if row.get("scope") == scope)
    selected: list[RankObservation] = []
    market: list[RankObservation] = []
    for row in rows:
        if scoring is not None and str(row.get("scoring") or "").upper() != scoring:
            raise CoverageIncomplete("Draft anchor scoring does not match the league ranking format")
        sleeper_id = str(row.get("sleeper_id") or "").strip()
        fantasypros_id = str(row.get("fantasypros_id") or "").strip()
        player_id = sleeper_id or (f"fp:{fantasypros_id}" if fantasypros_id else "")
        position = str(row.get("position") or "").strip().upper()
        if (
            not player_id
            or position not in {"QB", "RB", "WR", "TE"}
            or row.get("weighted_position_rank") in (None, "")
            or row.get("ecr") in (None, "")
        ):
            continue
        selected.append(
            RankObservation(
                player_id=player_id,
                horizon=EARLY_SEASON_DRAFT_ANCHOR,
                board_source="final_draft_selected",
                expert_id=None,
                position=position,
                position_rank=float(row["weighted_position_rank"]),
                overall_rank=optional_float(row.get("weighted_overall_rank")),
                scoring=str(row.get("scoring") or "") or None,
                updated_at=updated_at,
            )
        )
        market.append(
            RankObservation(
                player_id=player_id,
                horizon=EARLY_SEASON_DRAFT_ANCHOR,
                board_source="final_draft_market",
                expert_id=None,
                position=position,
                position_rank=float(row["ecr"]),
                overall_rank=optional_float(row.get("overall_ecr")),
                scoring=str(row.get("scoring") or "") or None,
                updated_at=updated_at,
            )
        )
    if not selected or len(selected) != len(market):
        raise CoverageIncomplete("Final Draft anchor is empty or asymmetric")
    return tuple(selected), tuple(market)


def capture_prospective_snapshot(
    path: str | Path,
    *,
    season: int,
    week: int,
    cutoff: datetime,
    mode: str,
    data: Sequence[SnapshotDatum],
    product: str = "TRADE ASSISTANT",
) -> Path:
    normalized_cutoff = cutoff.astimezone(timezone.utc)
    future = [row for row in data if parse_utc(row.published_at) > normalized_cutoff]
    if future:
        raise ValueError("Prospective snapshot contains information after its cutoff")
    ordered = tuple(
        sorted(data, key=lambda row: (row.kind, row.position, row.player_id, row.source))
    )
    payload = {
        "schema_version": 1,
        "product": product,
        "purpose": "PROSPECTIVE_HORIZON_VALIDATION",
        "season": season,
        "week": week,
        "cutoff": normalized_cutoff.isoformat(),
        "mode": mode,
        "data": [asdict(row) for row in ordered],
    }
    payload["snapshot_hash"] = stable_hash(payload)
    return atomic_write_json(path, payload)
