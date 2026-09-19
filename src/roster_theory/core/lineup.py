from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
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


@lru_cache(maxsize=256)
def _single_position_allocations(
    slots: tuple[tuple[str, tuple[str, ...]], ...],
    available_positions: tuple[str, ...],
    capacities: tuple[tuple[str, int], ...],
) -> tuple[tuple[tuple[str | None, ...], tuple[tuple[str, int], ...]], ...]:
    """Cache legal slot-allocation shapes independently of points and players."""

    available = set(available_positions)
    capacity = dict(capacities)
    slot_options = tuple(
        tuple(position for position in eligible if position in available)
        for _, eligible in slots
    )
    for include_empty in (False, True):
        options = tuple(
            ((None, *eligible) if include_empty else eligible)
            for eligible in slot_options
        )
        if any(not values for values in options):
            continue
        result = []
        for allocation in product(*options):
            counts: dict[str, int] = {}
            for position in allocation:
                if position is not None:
                    counts[position] = counts.get(position, 0) + 1
            if any(count > capacity.get(position, 0) for position, count in counts.items()):
                continue
            result.append((allocation, tuple(sorted(counts.items()))))
        if result:
            return tuple(result)
    return ()


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
        # First try the full-lineup shapes that _single_position_allocations
        # itself considers first. Counting an empty branch for every fixed
        # QB/RB/WR/TE slot made ordinary two-FLEX leagues appear exponential
        # (4,096 shapes instead of nine) and unnecessarily selected the much
        # slower player-by-player bitmask solver. If no full allocation is
        # legal, the cached helper can still consider empty slots below.
        allocation_count *= len(options)
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

    best: tuple[
        tuple[int, float, tuple[tuple[int, str], ...]],
        tuple[tuple[int, str], ...],
        float,
    ] | None = None
    allocations = _single_position_allocations(
        slots,
        tuple(sorted(available_positions)),
        tuple(sorted((position, len(rows)) for position, rows in ranked.items())),
    )
    required_counts = {
        (position, count)
        for _, count_rows in allocations
        for position, count in count_rows
    }
    selected_for_count = {
        (position, count): tuple(
            sorted(player_id for _, player_id in ranked[position][:count])
        )
        for position, count in required_counts
    }
    score_for_count = {
        (position, count): sum(
            value for value, _ in ranked[position][:count]
        )
        for position, count in required_counts
    }
    for allocation, count_rows in allocations:
        counts = dict(count_rows)
        selected_by_position = {
            position: selected_for_count[(position, count)]
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
        score = sum(score_for_count[(position, count)] for position, count in counts.items())
        key = (-len(selected), -score, selected)
        if best is None or key < best[0]:
            best = (key, selected, score)
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
    *,
    limited_player_ids: Iterable[str] = (),
    maximum_limited_players: int | None = None,
    required_filled_slots: Iterable[str] = (),
) -> LineupResult:
    """Return a deterministic maximum-point legal assignment.

    ``maximum_limited_players`` supports replacement-counterfactual lineups:
    callers may expose several legal waiver choices while limiting the lineup
    to the number of roster slots that were otherwise uncovered.

    ``required_filled_slots`` prevents a replacement from filling an unrelated
    higher-scoring slot while leaving the original uncovered slot empty.  This
    matters for fixed positions such as DST and K in mixed-position contexts.
    """
    player_list = sorted(players, key=lambda player: player.player_id)
    slots = lineup_slots(roster_positions)
    slot_index_by_id = {slot_id: index for index, (slot_id, _) in enumerate(slots)}
    required_slot_ids = frozenset(required_filled_slots)
    unknown_required = tuple(sorted(required_slot_ids - set(slot_index_by_id)))
    if unknown_required:
        raise ValueError(
            "required_filled_slots contains unknown slot(s): "
            + ", ".join(unknown_required)
        )
    required_mask = sum(1 << slot_index_by_id[slot_id] for slot_id in required_slot_ids)
    limited_ids = frozenset(limited_player_ids)
    if maximum_limited_players is not None and maximum_limited_players < 0:
        raise ValueError("maximum_limited_players must be non-negative")
    constrained = maximum_limited_players is not None and bool(limited_ids)
    single_position_result = (
        None
        if constrained or required_mask
        else _single_position_lineup(player_list, slots, points)
    )
    if single_position_result is not None:
        return single_position_result
    slot_count = len(slots)
    empty_assignments = ("",) * slot_count
    # (mask, limited players used) -> (score, player ID by slot; empty slots contain "")
    states: dict[tuple[int, int], tuple[float, tuple[str, ...]]] = {
        (0, 0): (0.0, empty_assignments)
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
        limited_increment = int(player.player_id in limited_ids)
        updated = dict(states)
        for (mask, limited_count), (score, assignments) in states.items():
            next_limited_count = limited_count + limited_increment
            if (
                maximum_limited_players is not None
                and next_limited_count > maximum_limited_players
            ):
                continue
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
                state_key = (mask | bit, next_limited_count)
                existing = updated.get(state_key)
                if existing is None or candidate[0] > existing[0] or (
                    candidate[0] == existing[0] and candidate[1] < existing[1]
                ):
                    updated[state_key] = candidate
        states = updated
    eligible_states = {
        key: value
        for key, value in states.items()
        if key[0] & required_mask == required_mask
    }
    if required_mask and not eligible_states:
        raise ValueError("No legal lineup can fill every required slot")
    (mask, _), (score, selected_by_slot) = min(
        (eligible_states or states).items(),
        key=lambda item: (
            -item[0][0].bit_count(),
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
