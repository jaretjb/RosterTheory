from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


def frozen_pairs(values: Mapping[str, Any] | None) -> tuple[tuple[str, Any], ...]:
    """Return a deterministic immutable representation of a flat mapping."""
    return tuple(sorted((str(key), value) for key, value in (values or {}).items()))


@dataclass(frozen=True, slots=True)
class Player:
    player_id: str
    name: str
    positions: tuple[str, ...]
    sleeper_id: str | None = None
    fantasypros_id: str | None = None
    nfl_team: str | None = None
    active: bool | None = None
    injury_status: str | None = None
    external_ids: tuple[tuple[str, str], ...] = ()
    identity_confidence: str = "unverified"


@dataclass(frozen=True, slots=True)
class LeagueRules:
    league_id: str
    season: int
    team_count: int
    roster_positions: tuple[str, ...]
    scoring: tuple[tuple[str, float], ...]
    playoff_start_week: int | None = None
    championship_week: int | None = None
    reserve_slots: int | None = None
    trade_deadline_raw: Any = None
    platform_settings: tuple[tuple[str, Any], ...] = ()


@dataclass(frozen=True, slots=True)
class FantasyTeam:
    roster_id: str
    owner_id: str | None
    display_name: str
    player_ids: tuple[str, ...]
    starter_ids: tuple[str, ...] = ()
    reserve_ids: tuple[str, ...] = ()
    waiver_position: int | None = None
    waiver_budget_used: int | None = None
    platform_settings: tuple[tuple[str, Any], ...] = ()


@dataclass(frozen=True, slots=True)
class FantasyWeek:
    week: int
    matchup_id: str | None = None
    opponent_roster_id: str | None = None
    playoff_weight: float = 1.0
    status: str = "scheduled"


@dataclass(frozen=True, slots=True)
class Projection:
    player_id: str
    horizon: str
    week: int | None
    raw_stats: tuple[tuple[str, float], ...]
    league_points: float
    source: str
    coverage_status: str = "complete"


@dataclass(frozen=True, slots=True)
class RankObservation:
    player_id: str
    horizon: str
    board_source: str
    expert_id: str | None
    position: str
    position_rank: float | None
    overall_rank: float | None
    tier: int | None = None
    scoring: str | None = None
    updated_at: str | None = None
    rank_min: float | None = None
    rank_max: float | None = None
    rank_std: float | None = None
