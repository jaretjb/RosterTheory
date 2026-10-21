"""Waiver-owned required starter coverage, without assumed future acquisitions."""
from dataclasses import dataclass

from roster_theory.core.lineup import LineupPlayer, optimize_lineup
from roster_theory.core.projections import currently_inactive


@dataclass(frozen=True)
class CoverageRepair:
    position: str
    safe_drop: bool
    owned_points_gain: float | None
    future_gaps: tuple[int, ...]
    reason: str
    specialist_priority: float | None = None
    production_score: float | None = None
    production_samples: int | None = None


def required_coverage(snapshot, context, matrix, values, roster, add_id, drop_id):
    players = {p.player_id: p for p in snapshot.players}
    add = players[add_id]
    position = next((p for p in add.positions if p in {'QB', 'K', 'DST', 'DEF'}), None)
    position = 'DST' if position == 'DEF' else position
    slots = tuple('DST' if s == 'DEF' else s for s in snapshot.league.roster_positions)
    if position not in {'QB', 'K'} or slots.count(position) != 1:
        return None
    week = next(w for w in context.weeks if w.week == context.current_week)
    incumbents = [pid for pid in roster if position in players[pid].positions]
    def unavailable(pid):
        cell = matrix.cell(pid, week.week)
        return players[pid].nfl_team in week.bye_teams or (
            cell is not None and cell.availability in {'BYE', 'INACTIVE'})
    if any(not unavailable(pid) for pid in incumbents):
        return None
    cell = matrix.cell(add_id, week.week)
    if currently_inactive(add) or add.nfl_team in week.bye_teams:
        return None
    if position != 'K' and (cell is None or cell.availability != 'ACTIVE'):
        return None
    if position == 'K' and cell is not None and cell.availability in {'BYE','INACTIVE'}:
        return None
    value = values.get(add_id)
    if value is None:
        return None
    if position == 'K':
        # A known bye is not an unknown rank. Do not manufacture a rank or
        # complete custom-scoring forecast for the unavailable incumbent.
        if drop_id is not None and drop_id not in incumbents:
            return None
        rank = value.current_week_position_rank
        samples, points = value.season_sample_size, value.season_points
        if rank is None or not 1 <= rank <= 16 or not samples or points is None:
            return None
        peers = [v.season_points / v.season_sample_size for pid, v in values.items()
                 if pid in players and 'K' in players[pid].positions and v.season_points is not None
                 and v.season_sample_size and v.current_week_position_rank is not None]
        production = (points / samples) / max(peers) if peers and max(peers) > 0 else 0
        return CoverageRepair(position, True, None, (),
            'Required kicker slot; incumbent is confirmed unavailable', (17-rank)/16, production, samples)
    if cell.points is None or cell.points <= 0:
        return None
    skill_slots = tuple(s for s in slots if s not in {'BN', 'K', 'DST'})
    def solve(ids, w):
        active = [pid for pid in ids if {'QB','RB','WR','TE'}.intersection(players[pid].positions)
                  and (c := matrix.cell(pid, w)) is not None and c.points is not None
                  and c.availability == 'ACTIVE']
        return optimize_lineup(tuple(LineupPlayer(pid, players[pid].positions) for pid in active),
            skill_slots, {pid: matrix.cell(pid, w).points for pid in active})
    after = (set(roster) - ({drop_id} if drop_id else set())) | {add_id}
    before_now, after_now = solve(roster, week.week), solve(after, week.week)
    gaps = tuple(w.week for w in context.weeks[:3]
                 if solve(after, w.week).filled_slots < solve(roster, w.week).filled_slots)
    drop_is_starter = drop_id is not None and any(
        a.player_id == drop_id for w in context.weeks[:3] for a in solve(roster, w.week).assignments)
    drop_value = values.get(drop_id)
    drop_position = next((p for p in players[drop_id].positions if p in {'QB','RB','WR','TE'}), None) if drop_id else None
    rank = (drop_value.selected_rest_of_season_position_rank or drop_value.rest_of_season_position_rank) if drop_value else None
    # Protect top starting-quality holdings even when they happen to be on bye.
    population = len(snapshot.teams) * slots.count(drop_position) if drop_position else 0
    protected = drop_id is not None and (rank is None or rank <= population)
    safe = not gaps and not drop_is_starter and not protected and after_now.filled_slots > before_now.filled_slots
    return CoverageRepair(position, safe, round(after_now.score - before_now.score, 3), gaps,
        'Required QB slot; actual owned coverage improves' if safe else
        'Required QB slot; proposed drop risks starter coverage or a protected holding')
