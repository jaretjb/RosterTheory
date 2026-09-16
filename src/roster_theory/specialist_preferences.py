from __future__ import annotations

import csv
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable


DEFAULT_DEFENSE_DRAFT_ORDER_2026 = Path("config/defense_draft_order_2026.csv")


@dataclass(frozen=True, slots=True)
class DefenseDraftPreference:
    rank: int
    team: str
    player_name: str
    source: str


def _normalize_team(team: str) -> str:
    normalized = str(team or "").strip().upper()
    return "JAX" if normalized == "JAC" else normalized


@lru_cache(maxsize=8)
def load_defense_draft_order(
    path: str | Path = DEFAULT_DEFENSE_DRAFT_ORDER_2026,
) -> tuple[DefenseDraftPreference, ...]:
    source_path = Path(path)
    with source_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"rank", "team", "player_name", "source"}
        missing = required - set(reader.fieldnames or ())
        if missing:
            raise ValueError(
                "Defense draft order is missing columns: "
                + ", ".join(sorted(missing))
            )
        entries = []
        for line_number, row in enumerate(reader, start=2):
            try:
                rank = int(str(row.get("rank") or ""))
            except ValueError as exc:
                raise ValueError(
                    f"Defense draft order line {line_number} has an invalid rank"
                ) from exc
            team = _normalize_team(str(row.get("team") or ""))
            player_name = str(row.get("player_name") or "").strip()
            source = str(row.get("source") or "").strip()
            if rank <= 0 or not team or not player_name or not source:
                raise ValueError(
                    f"Defense draft order line {line_number} is incomplete"
                )
            entries.append(
                DefenseDraftPreference(rank, team, player_name, source)
            )
    if not entries:
        raise ValueError("Defense draft order is empty")
    ranks = [entry.rank for entry in entries]
    teams = [entry.team for entry in entries]
    if len(ranks) != len(set(ranks)):
        raise ValueError("Defense draft order contains duplicate ranks")
    if len(teams) != len(set(teams)):
        raise ValueError("Defense draft order contains duplicate teams")
    if sorted(ranks) != list(range(1, len(entries) + 1)):
        raise ValueError("Defense draft order ranks must be contiguous from 1")
    return tuple(sorted(entries, key=lambda entry: entry.rank))


def defense_draft_rank(
    team: str,
    order: Iterable[DefenseDraftPreference] | None = None,
) -> int | None:
    normalized_team = _normalize_team(team)
    for entry in order or load_defense_draft_order():
        if entry.team == normalized_team:
            return entry.rank
    return None


def defense_draft_sort_key(player: Any) -> tuple[float, ...]:
    user_rank = defense_draft_rank(str(getattr(player, "team", "")))
    expert_rank = float(getattr(player, "rank_score", 999.0))
    adp = float(getattr(player, "adp", 999.0))
    if user_rank is not None:
        return 0.0, float(user_rank), expert_rank, adp
    return 1.0, expert_rank, adp
