"""Feature-neutral projection evidence; no acquisition or trade policy."""

from __future__ import annotations

from dataclasses import replace
from math import isfinite
from typing import Sequence

from roster_theory.core.models import Player, Projection


KNOWN_INACTIVE = frozenset({"IR", "PUP", "SUSP", "OUT"})
COMPLETE_PROJECTION_COVERAGE = frozenset({
    "complete", "verified_bye_zero", "known_inactive_zero", "verified_inactive_zero",
})


def currently_inactive(player: Player) -> bool:
    return player.active is False or str(player.injury_status or "").upper() in KNOWN_INACTIVE


def projection_coverage_is_complete(status: str) -> bool:
    """Status vocabulary only; use projection_is_complete for a usable row."""
    return status.casefold() in COMPLETE_PROJECTION_COVERAGE


def projection_coverage_issue(
    row: Projection,
    *,
    current_week: int | None,
    allow_scenario: bool = False,
) -> str | None:
    status = row.coverage_status.casefold()
    if not projection_coverage_is_complete(status) and not (
        allow_scenario and status == "scenario_inactive_zero"
    ):
        return f"Incomplete projection coverage: {row.coverage_status}"
    if not isfinite(row.league_points):
        return "Nonfinite projection points"
    if not row.source.strip():
        return "Missing projection source"
    if status.endswith("_zero"):
        if row.league_points != 0.0 or row.horizon != "WEEKLY" or row.week is None:
            return "Invalid week-scoped zero projection"
    if status == "known_inactive_zero" and (current_week is None or row.week != current_week):
        return "Current inactive status cannot establish future absence"
    return None


def projection_is_complete(
    row: Projection, *, current_week: int | None, allow_scenario: bool = False
) -> bool:
    return projection_coverage_issue(
        row, current_week=current_week, allow_scenario=allow_scenario
    ) is None


def reconcile_current_inactive_omissions(
    players: Sequence[Player], current_week: int, projections: Sequence[Projection]
) -> tuple[Projection, ...]:
    """Current directory evidence repairs only this week's empty omission row."""
    by_id = {player.player_id: player for player in players}
    result = []
    for row in projections:
        player = by_id.get(row.player_id)
        if (
            player is not None and currently_inactive(player)
            and row.horizon == "WEEKLY" and row.week == current_week
            and row.coverage_status.casefold() == "source_omission_zero"
            and row.league_points == 0.0 and not row.raw_stats
        ):
            row = replace(
                row, coverage_status="known_inactive_zero",
                source=f"Sleeper {player.injury_status or 'inactive'} status; current-week omission",
            )
        result.append(row)
    return tuple(result)
