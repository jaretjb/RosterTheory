"""Lineup dependency mechanics, independent of recommendation policy."""
from collections.abc import Iterable, Mapping, Sequence

from roster_theory.core.lineup import lineup_slots
from roster_theory.core.models import Player


def lineup_dependency_positions(
    roster_positions: Sequence[str], players: Sequence[Player], changed_ids: Iterable[str],
) -> frozenset[str]:
    """Close changed eligibility over shared slots and multi-position players.

    This proves only lineup separation. Feature policies must separately account
    for risk, retention, replacement, legality and secondary-move dependencies.
    """
    def normalize(position: str) -> str:
        return "DST" if position.upper() == "DEF" else position.upper()
    groups = [set(eligible) for _, eligible in lineup_slots(roster_positions)]
    allowed = set().union(*groups) if groups else set()
    by_id = {player.player_id: {normalize(p) for p in player.positions} for player in players}
    groups.extend(positions & allowed for positions in by_id.values())
    changed = tuple(changed_ids)
    if any(not by_id.get(pid) for pid in changed):
        return frozenset(allowed)
    reached = set().union(*(by_id[pid] for pid in changed)) if changed else set()
    while True:
        expanded = reached | set().union(*(group for group in groups if group & reached))
        if expanded == reached:
            return frozenset(reached)
        reached = expanded


def maximum_delta_bound(
    before: Mapping[str, float], after: Mapping[str, float], *, rounding_allowance: float = 0.0,
) -> float:
    """Bound change in a maximum when unknown additive components stay fixed.

    Callers must prove independence before applying this inequality. It is not
    a forecast for the missing component or a bound on its absolute value.
    For scores rounded to 0.001, a 0.004 allowance covers the four loss
    calculations (subset/full, before/after), each a difference of two scores.
    """
    return max([0.0, *(after.get(key, 0.0) - before.get(key, 0.0)
                      for key in before.keys() | after.keys())]) + rounding_allowance
