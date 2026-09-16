from __future__ import annotations

import math
from collections import Counter
from typing import Any, Iterable, Mapping

from roster_theory.rankings import normalize_name
from roster_theory.simulation import next_pick_for_slot, survival_probability


def _picked_keys(picks: Iterable[Mapping[str, Any]]) -> set[str]:
    keys: set[str] = set()
    for pick in picks:
        player_id = pick.get("player_id")
        if player_id:
            keys.add(f"sleeper_id:{player_id}")
            keys.add(str(player_id))
        metadata = pick.get("metadata") or {}
        name = f"{metadata.get('first_name', '')} {metadata.get('last_name', '')}".strip()
        if name:
            keys.add("name:" + normalize_name(name))
    return keys


def recommend_available(
    board: Iterable[Mapping[str, Any]],
    picks: Iterable[Mapping[str, Any]],
    current_pick: int,
    teams: int,
    draft_slot: int,
    limit: int = 10,
) -> list[dict[str, Any]]:
    pick_list = list(picks)
    picked = _picked_keys(pick_list)
    roster_counts = Counter(
        str((pick.get("metadata") or {}).get("position", "UNKNOWN")).upper()
        for pick in pick_list
        if int(pick.get("draft_slot") or -1) == draft_slot
    )
    next_pick = next_pick_for_slot(current_pick, draft_slot, teams) or current_pick + teams
    available: list[dict[str, Any]] = []
    for source in board:
        player = dict(source)
        keys = {
            str(player.get("player_key") or ""),
            str(player.get("sleeper_id") or ""),
            "name:" + normalize_name(str(player.get("player_name") or "")),
        }
        if keys & picked:
            continue
        adp = float(player.get("adp") or player.get("rank_score") or 999.0)
        survival = survival_probability(adp, current_pick, next_pick)
        vbd = float(player.get("vbd") or 0.0)
        position = str(player.get("position") or "").upper()
        need_adjustment = 0.0
        if position in ("RB", "WR") and roster_counts[position] < 2:
            need_adjustment += 4.0
        if position in ("QB", "TE") and roster_counts[position] >= 1:
            need_adjustment -= 7.0
        urgency = (1.0 - survival) * 20.0
        player["survival_to_next_pick"] = round(survival, 3)
        player["next_user_pick"] = next_pick
        player["mvor_score"] = round(vbd + urgency + need_adjustment, 3)
        available.append(player)
    return sorted(
        available,
        key=lambda player: (-float(player["mvor_score"]), float(player.get("rank_score") or math.inf)),
    )[:limit]

