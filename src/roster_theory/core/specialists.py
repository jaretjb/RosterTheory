"""Neutral proof that a singleton specialist swap cannot change other slots."""

from collections.abc import Iterable

from roster_theory.core.lineup import lineup_slots
from roster_theory.core.models import Player


def fixed_specialist_swap(
    players: Iterable[Player], roster_positions: Iterable[str],
    roster_player_ids: Iterable[str], add: str, drop: str | None,
) -> str | None:
    """Return K/DST only for a pure, fixed-slot, one-for-one replacement.

    Multiple holdings, extra slots, shared eligibility and cross-position
    acquisitions require the assistant's ordinary roster evaluation.
    """
    by_id = {player.player_id: player for player in players}
    def positions(pid):
        player = by_id.get(pid)
        return {"DST" if p.upper() == "DEF" else p.upper()
                for p in player.positions} if player else set()
    add_positions = positions(add)
    if len(add_positions) != 1 or drop is None or add_positions != positions(drop):
        return None
    position = next(iter(add_positions))
    if position not in {"K", "DST"}:
        return None
    accepting = [eligible for _, eligible in lineup_slots(roster_positions)
                 if position in eligible]
    roster = set(roster_player_ids)
    if any(not positions(pid) for pid in roster):
        return None
    holders = {pid for pid in roster if position in positions(pid)}
    if accepting != [(position,)] or holders != {drop} or add in roster:
        return None
    return position
