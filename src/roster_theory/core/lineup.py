from __future__ import annotations

from dataclasses import dataclass
from itertools import product
from typing import Iterable, Mapping


FLEX_ELIGIBILITY: dict[str, tuple[str, ...]] = {
    "FLEX": ("RB", "WR", "TE"),
    "WRRB_FLEX": ("RB", "WR"),
    "REC_FLEX": ("WR", "TE"),
    "SUPER_FLEX": ("QB", "RB", "WR", "TE"),
}
NON_STARTERS = {"BN", "BENCH", "IR", "RESERVE", "TAXI"}


@dataclass(frozen=True, slots=True)
class LineupPlayer:
    player_id: str
    positions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class LineupAssignment:
    slot: str
    player_id: str
    points: float


@dataclass(frozen=True, slots=True)
class LineupResult:
    assignments: tuple[LineupAssignment, ...]
    unused_player_ids: tuple[str, ...]
    score: float
    filled_slots: int
    total_slots: int


def _normalize_position(position: str) -> str:
    value = position.upper()
    return "DST" if value == "DEF" else value


def lineup_slots(roster_positions: Iterable[str]) -> tuple[tuple[str, tuple[str, ...]], ...]:
    counts: dict[str, int] = {}
    slots: list[tuple[str, tuple[str, ...]]] = []
    for raw_position in roster_positions:
        position = _normalize_position(raw_position)
        if position in NON_STARTERS:
            continue
        eligible = FLEX_ELIGIBILITY.get(position, (position,))
        counts[position] = counts.get(position, 0) + 1
        slots.append((f"{position}:{counts[position]}", eligible))
    return tuple(slots)


def _single_position_lineup(
    player_list: list[LineupPlayer],
    slots: tuple[tuple[str, tuple[str, ...]], ...],
    points: Mapping[str, float],
) -> LineupResult | None:
    normalized = [
        tuple(dict.fromkeys(_normalize_position(value) for value in player.positions))
        for player in player_list
    ]
    if any(len(positions) != 1 for positions in normalized):
        return None
    available_positions = {positions[0] for positions in normalized}
    slot_options = tuple(
        tuple(position for position in eligible if position in available_positions)
        for _, eligible in slots
    )
    allocation_count = 1
    for options in slot_options:
        # Include the empty-slot branch: it is required whenever the roster
        # cannot fill every configured starter slot and is the expensive case.
        allocation_count *= 1 + len(options)
    # Enumerating position allocations is faster for ordinary lineups, but it
    # becomes exponential when several FLEX/SUPER_FLEX slots overlap. The
    # general bitmask optimizer below has a bounded state space by slot count.
    if allocation_count > 256:
        return None
    ranked: dict[str, tuple[tuple[float, str], ...]] = {}
    for player, positions in zip(player_list, normalized):
        position = positions[0]
        ranked.setdefault(position, ())
        ranked[position] = (
            *ranked[position],
            (float(points.get(player.player_id, 0.0)), player.player_id),
        )
    ranked = {
        position: tuple(sorted(rows, key=lambda row: (-row[0], row[1])))
        for position, rows in ranked.items()
    }

    def candidates(include_empty: bool):
        options = tuple(
            ((None, *eligible) if include_empty else eligible)
            for eligible in slot_options
        )
        if any(not values for values in options):
            return ()
        return product(*options)

    best: tuple[
        tuple[int, float, tuple[tuple[int, str], ...]],
        tuple[tuple[int, str], ...],
        float,
    ] | None = None
    for include_empty in (False, True):
        for allocation in candidates(include_empty):
            counts: dict[str, int] = {}
            for position in allocation:
                if position is not None:
                    counts[position] = counts.get(position, 0) + 1
            if any(count > len(ranked.get(position, ())) for position, count in counts.items()):
                continue
            selected_by_position = {
                position: tuple(
                    sorted(player_id for _, player_id in ranked[position][:count])
                )
                for position, count in counts.items()
            }
            next_index = {position: 0 for position in counts}
            assignments: list[tuple[int, str]] = []
            for slot_index, position in enumerate(allocation):
                if position is None:
                    continue
                player_ids = selected_by_position[position]
                player_id = player_ids[next_index[position]]
                next_index[position] += 1
                assignments.append((slot_index, player_id))
            selected = tuple(assignments)
            score = sum(
                sum(value for value, _ in ranked[position][:count])
                for position, count in counts.items()
            )
            key = (-len(selected), -score, selected)
            if best is None or key < best[0]:
                best = (key, selected, score)
        if best is not None:
            break
    if best is None:
        return None
    _, selected, score = best
    selected_ids = {player_id for _, player_id in selected}
    return LineupResult(
        assignments=tuple(
            LineupAssignment(
                slots[slot_index][0],
                player_id,
                float(points.get(player_id, 0.0)),
            )
            for slot_index, player_id in selected
        ),
        unused_player_ids=tuple(
            player.player_id
            for player in player_list
            if player.player_id not in selected_ids
        ),
        score=round(score, 3),
        filled_slots=len(selected),
        total_slots=len(slots),
    )


def optimize_lineup(
    players: Iterable[LineupPlayer],
    roster_positions: Iterable[str],
    points: Mapping[str, float],
) -> LineupResult:
    """Return a deterministic maximum-point legal assignment."""
    player_list = sorted(players, key=lambda player: player.player_id)
    slots = lineup_slots(roster_positions)
    single_position_result = _single_position_lineup(player_list, slots, points)
    if single_position_result is not None:
        return single_position_result
    slot_count = len(slots)
    empty_assignments = ("",) * slot_count
    # mask -> (score, player ID by slot; empty slots contain "")
    states: dict[int, tuple[float, tuple[str, ...]]] = {
        0: (0.0, empty_assignments)
    }
    for player in player_list:
        player_positions = {_normalize_position(value) for value in player.positions}
        eligible_mask = 0
        for slot_index, (_, eligible) in enumerate(slots):
            if not player_positions.isdisjoint(eligible):
                eligible_mask |= 1 << slot_index
        if not eligible_mask:
            continue
        player_points = float(points.get(player.player_id, 0.0))
        updated = dict(states)
        for mask, (score, assignments) in states.items():
            available = eligible_mask & ~mask
            while available:
                bit = available & -available
                available ^= bit
                slot_index = bit.bit_length() - 1
                candidate_assignments = list(assignments)
                candidate_assignments[slot_index] = player.player_id
                candidate = (
                    score + player_points,
                    tuple(candidate_assignments),
                )
                existing = updated.get(mask | bit)
                if existing is None or candidate[0] > existing[0] or (
                    candidate[0] == existing[0] and candidate[1] < existing[1]
                ):
                    updated[mask | bit] = candidate
        states = updated
    mask, (score, selected_by_slot) = min(
        states.items(),
        key=lambda item: (
            -item[0].bit_count(),
            -item[1][0],
            tuple(
                (slot_index, player_id)
                for slot_index, player_id in enumerate(item[1][1])
                if player_id
            ),
        ),
    )
    selected = tuple(
        (slot_index, player_id)
        for slot_index, player_id in enumerate(selected_by_slot)
        if player_id
    )
    selected_ids = {player_id for _, player_id in selected}
    assignments = tuple(
        LineupAssignment(slots[slot_index][0], player_id, float(points.get(player_id, 0.0)))
        for slot_index, player_id in sorted(selected)
    )
    return LineupResult(
        assignments=assignments,
        unused_player_ids=tuple(
            player.player_id
            for player in player_list
            if player.player_id not in selected_ids
        ),
        score=round(score, 3),
        filled_slots=mask.bit_count(),
        total_slots=len(slots),
    )
