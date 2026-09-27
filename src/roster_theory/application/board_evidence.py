"""Persistence for shared in-season value-board evidence."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Mapping, Sequence

from roster_theory.core.errors import CoverageIncomplete
from roster_theory.core.provenance import stable_hash
from roster_theory.inseason.boards import SelectedRank, ValueBoard, ValuationGap
from roster_theory.providers.cache import atomic_write_json


def export_board_evidence(
    path: str | Path,
    *,
    selected_ranks: Sequence[SelectedRank],
    selected: ValueBoard,
    market: ValueBoard,
    gaps: Sequence[ValuationGap],
    manifest_id: str,
    selected_raw: ValueBoard | None = None,
    warnings: Sequence[str] = (),
    additional_evidence: Mapping[str, object] | None = None,
    product: str = "TRADE ASSISTANT",
) -> Path:
    if selected.horizon != market.horizon:
        raise CoverageIncomplete("Cannot export mismatched board horizons")
    payload = {
        "schema_version": 1,
        "product": product,
        "manifest_id": manifest_id,
        "horizon": selected.horizon,
        "selected_rank_evidence": [asdict(row) for row in selected_ranks],
        "selected_raw_board": asdict(selected_raw) if selected_raw else None,
        "selected_board": asdict(selected),
        "market_board": asdict(market),
        "valuation_gaps": [asdict(row) for row in gaps],
        "warnings": list(warnings),
        "additional_evidence": dict(additional_evidence or {}),
    }
    payload["evidence_hash"] = stable_hash(payload)
    return atomic_write_json(path, payload)
