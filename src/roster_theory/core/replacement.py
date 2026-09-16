from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

from roster_theory.core.models import Player


@dataclass(frozen=True, slots=True)
class WaiverBaseline:
    position: str
    player_id: str
    points: float
    available_count: int


def current_free_agents(
    players: Iterable[Player], owned_player_ids: Iterable[str]
) -> tuple[Player, ...]:
    owned = {str(player_id) for player_id in owned_player_ids}
    return tuple(
        sorted(
            (player for player in players if player.player_id not in owned),
            key=lambda player: player.player_id,
        )
    )


def positional_waiver_baselines(
    players: Iterable[Player],
    owned_player_ids: Iterable[str],
    points: Mapping[str, float],
    *,
    positions: Iterable[str] = ("QB", "RB", "WR", "TE"),
    depth: int = 1,
) -> dict[str, WaiverBaseline]:
    """Choose the Nth-best currently unowned player at each position."""
    if depth < 1:
        raise ValueError("Waiver baseline depth must be at least one")
    free_agents = current_free_agents(players, owned_player_ids)
    baselines: dict[str, WaiverBaseline] = {}
    for raw_position in positions:
        position = raw_position.upper()
        eligible = [
            player
            for player in free_agents
            if position in {value.upper() for value in player.positions}
        ]
        ordered = sorted(
            eligible,
            key=lambda player: (-float(points.get(player.player_id, 0.0)), player.player_id),
        )
        if len(ordered) < depth:
            continue
        player = ordered[depth - 1]
        baselines[position] = WaiverBaseline(
            position=position,
            player_id=player.player_id,
            points=round(float(points.get(player.player_id, 0.0)), 3),
            available_count=len(ordered),
        )
    return baselines

