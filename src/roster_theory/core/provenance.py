from __future__ import annotations

import json
from dataclasses import asdict, dataclass, is_dataclass
from datetime import date, datetime
from enum import Enum
from hashlib import sha256
from pathlib import Path
from typing import Any, Mapping


def _canonical(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return _canonical(asdict(value))
    if isinstance(value, Mapping):
        return {
            str(key): _canonical(child)
            for key, child in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_canonical(child) for child in value]
    if isinstance(value, (set, frozenset)):
        return sorted((_canonical(child) for child in value), key=repr)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, (Path, Enum)):
        return str(value)
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise ValueError("Non-finite floats cannot be serialized canonically")
    return value


def canonical_json(value: Any) -> str:
    return json.dumps(
        _canonical(value),
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def stable_hash(value: Any) -> str:
    return sha256(canonical_json(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class DataStamp:
    source: str
    endpoint: str
    captured_at: datetime
    season: int | None = None
    week: int | None = None
    horizon_start: int | None = None
    horizon_end: int | None = None
    scoring_label: str | None = None
    scoring_hash: str | None = None
    parameter_hash: str | None = None
    payload_hash: str | None = None
    cache_status: str = "miss"
    freshness_seconds: int | None = None
    fresh: bool | None = None
    export_restriction: str | None = None
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class AnalysisManifest:
    analysis_id: str
    league_id: str
    user_id: str
    current_week: int
    horizon_start: int
    horizon_end: int
    configuration_hash: str
    scenario_seed: str
    data_stamps: tuple[DataStamp, ...]
    coverage_checks: tuple[tuple[str, bool], ...] = ()
    warnings: tuple[str, ...] = ()
    input_hashes: tuple[tuple[str, str], ...] = ()

    @classmethod
    def build(
        cls,
        *,
        league_id: str,
        user_id: str,
        current_week: int,
        horizon_start: int,
        horizon_end: int,
        configuration: Any,
        normalized_inputs: Any,
        data_stamps: tuple[DataStamp, ...],
        coverage_checks: tuple[tuple[str, bool], ...] = (),
        warnings: tuple[str, ...] = (),
        input_hashes: tuple[tuple[str, str], ...] = (),
    ) -> "AnalysisManifest":
        configuration_hash = stable_hash(configuration)
        identity = {
            "league_id": league_id,
            "user_id": user_id,
            "current_week": current_week,
            "horizon": [horizon_start, horizon_end],
            "configuration_hash": configuration_hash,
            "normalized_inputs": normalized_inputs,
            "data_stamps": data_stamps,
            "coverage_checks": coverage_checks,
            "warnings": warnings,
            "input_hashes": input_hashes,
        }
        analysis_id = stable_hash(identity)
        return cls(
            analysis_id=analysis_id,
            league_id=league_id,
            user_id=user_id,
            current_week=current_week,
            horizon_start=horizon_start,
            horizon_end=horizon_end,
            configuration_hash=configuration_hash,
            scenario_seed=analysis_id[:16],
            data_stamps=data_stamps,
            coverage_checks=coverage_checks,
            warnings=warnings,
            input_hashes=input_hashes,
        )
