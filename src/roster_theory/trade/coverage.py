"""Scope missing lineup evidence to the rosters whose decisions depend on it."""

from dataclasses import dataclass

from roster_theory.inseason.evaluation import WeeklyProjectionMatrix
from roster_theory.trade.snapshot import SKILL_POSITIONS, TradeSnapshot


@dataclass(frozen=True, slots=True)
class RosterCoverageExclusion:
    roster_id: str
    missing_player_weeks: tuple[tuple[str, int], ...]
    reason: str = "INCOMPLETE_ROSTER_PROJECTIONS"


def roster_projection_exclusions(
    snapshot: TradeSnapshot, matrix: WeeklyProjectionMatrix,
) -> tuple[RosterCoverageExclusion, ...]:
    players = {row.player_id: row for row in snapshot.players}
    excluded_players = dict(snapshot.player_exclusions)
    result = []
    for team in sorted(snapshot.teams, key=lambda row: row.roster_id):
        missing = tuple(
            (player_id, week.week)
            for player_id in sorted(set(team.player_ids) - set(team.reserve_ids))
            if player_id in snapshot.tradeable_player_ids
            or player_id in excluded_players
            or (player_id in players and SKILL_POSITIONS.intersection(players[player_id].positions))
            for week in snapshot.weeks
            if player_id in excluded_players
            or (cell := matrix.cell(player_id, week.week)) is None or cell.points is None
        )
        if missing:
            reason = ("ROSTER_PLAYER_IDENTITY_OR_TEAM_UNAVAILABLE"
                      if any(pid in excluded_players for pid, _ in missing)
                      else "INCOMPLETE_ROSTER_PROJECTIONS")
            result.append(RosterCoverageExclusion(team.roster_id, missing, reason))
    return tuple(result)
