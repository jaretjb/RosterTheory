"""Normalize current expert directory facts without selecting a feature panel."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Any, Mapping, Sequence


def published_contributor_positions(datasets: Sequence[Any]) -> dict[str, set[str]]:
    """Report observed expert ballots; directory advertising is not publication."""
    result: dict[str, set[str]] = {}
    for dataset in datasets:
        for expert_id in dataset.contributor_ids:
            result.setdefault(str(expert_id), set())
        if not dataset.complete_horizon:
            continue
        for row in dataset.contributor_observations:
            rank = row.position_rank if row.position_rank is not None else row.overall_rank
            if (
                row.expert_id is not None and row.horizon == dataset.horizon
                and isinstance(rank, (int, float)) and not isinstance(rank, bool)
                and isfinite(rank) and rank > 0
            ):
                result.setdefault(str(row.expert_id), set()).add(row.position)
    return result


@dataclass(frozen=True, slots=True)
class CurrentExpert:
    expert_id: str
    name: str
    source_name: str
    position_updates: tuple[tuple[str, str], ...]
    latest_weekly_accuracy: tuple[tuple[str, int], ...]
    prior_weekly_accuracy: tuple[tuple[str, int], ...]

    def update_for(self, position: str) -> str | None:
        return dict(self.position_updates).get(position.upper())


def normalize_current_experts(value: Mapping[str, Any]) -> tuple[CurrentExpert, ...]:
    result: list[CurrentExpert] = []
    for raw in value.get("experts") or ():
        if not isinstance(raw, Mapping) or raw.get("expert_id") is None:
            continue
        position_updates = raw.get("positions") or {}
        weekly = raw.get("accuracy_weekly") or {}
        prior = raw.get("accuracy_weekly_last_season") or {}
        result.append(
            CurrentExpert(
                expert_id=str(raw["expert_id"]),
                name=str(raw.get("name") or raw["expert_id"]).strip(),
                source_name=str(raw.get("source") or "Unknown").strip(),
                position_updates=tuple(
                    sorted((str(key).upper(), str(item)) for key, item in position_updates.items())
                ),
                latest_weekly_accuracy=tuple(
                    sorted((str(key).upper(), int(item)) for key, item in weekly.items())
                ),
                prior_weekly_accuracy=tuple(
                    sorted((str(key).upper(), int(item)) for key, item in prior.items())
                ),
            )
        )
    return tuple(sorted(result, key=lambda item: int(item.expert_id)))
