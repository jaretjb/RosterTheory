from __future__ import annotations

from typing import Any, Iterable, Mapping

from roster_theory.mock_watcher import roster_positions_from_draft
from roster_theory.rankings import normalize_name
from roster_theory.simulation import (
    Player,
    SKILL_POSITIONS,
    deterministic_roster_strength,
    expert_ordered_projection_players,
    fit_rank_vorp_curve,
    market_replacement_baselines,
    rank_adjusted_players,
    weekly_use_roster_strength,
)


def build_draft_board_replay_reports(
    draft_board_by_round_and_seat: Iterable[Iterable[str]],
    board: Iterable[Mapping[str, Any]],
    *,
    draft_slot: int,
    scoring: str = "half_ppr",
) -> list[dict[str, Any]]:
    """Build read-only turn states from a complete snake draft board.

    Board columns are seats, even when the displayed round runs right-to-left.
    The reports preserve the actual roster at each turn.  They support an
    independent decision replay, not a claim that later opponents would keep
    making the same picks after a counterfactual user selection.
    """
    rounds = [list(round_row) for round_row in draft_board_by_round_and_seat]
    if not rounds:
        raise ValueError("Draft board is empty")
    teams = len(rounds[0])
    if teams < 2 or any(len(round_row) != teams for round_row in rounds):
        raise ValueError("Every draft-board round must contain the same team count")
    if not 1 <= draft_slot <= teams:
        raise ValueError("Draft slot is outside the draft-board team count")

    player_rows: dict[str, list[dict[str, Any]]] = {}
    for source in board:
        if not source.get("player_name"):
            continue
        player_rows.setdefault(
            normalize_name(str(source.get("player_name") or "")), []
        ).append(dict(source))
    picks = []
    identity_errors = []
    for round_index, round_row in enumerate(rounds, start=1):
        for seat, player_name in enumerate(round_row, start=1):
            normalized = normalize_name(player_name)
            matches = player_rows.get(normalized, [])
            if len(matches) != 1:
                label = "absent" if not matches else "ambiguous"
                identity_errors.append(f"{player_name} ({label})")
                continue
            row = matches[0]
            pick_in_round = seat if round_index % 2 else teams - seat + 1
            pick_no = (round_index - 1) * teams + pick_in_round
            position = str(row.get("position") or "").upper().replace("DEF", "DST")
            name_parts = player_name.rsplit(" ", 1)
            picks.append(
                {
                    "pick_no": pick_no,
                    "round": round_index,
                    "draft_slot": seat,
                    "player_id": str(row.get("sleeper_id") or row.get("player_key") or ""),
                    "metadata": {
                        "first_name": name_parts[0],
                        "last_name": name_parts[1] if len(name_parts) > 1 else "",
                        "position": "DEF" if position == "DST" else position,
                    },
                }
            )
    if identity_errors:
        raise ValueError(
            "Draft-board player identity errors: "
            + ", ".join(sorted(identity_errors))
        )
    picks.sort(key=lambda pick: int(pick["pick_no"]))

    def rosters(visible: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
        return {
            str(seat): [
                pick for pick in visible if int(pick["draft_slot"]) == seat
            ]
            for seat in range(1, teams + 1)
        }

    reports = []
    for round_index in range(1, len(rounds) + 1):
        pick_in_round = draft_slot if round_index % 2 else teams - draft_slot + 1
        current_pick = (round_index - 1) * teams + pick_in_round
        visible = [pick for pick in picks if int(pick["pick_no"]) < current_pick]
        reports.append(
            {
                "draft_id": "manual-draft-board-replay",
                "status": "drafting",
                "teams": teams,
                "rounds": len(rounds),
                "draft_slot": draft_slot,
                "scoring": scoring,
                "picks": visible,
                "rosters": rosters(visible),
                "current_pick": current_pick,
                "next_user_pick": None,
                "is_user_turn": True,
                "transition": "synthetic_actual_board_turn",
                "recommendation": {"captured": True},
            }
        )
    reports.append(
        {
            "draft_id": "manual-draft-board-replay",
            "status": "complete",
            "teams": teams,
            "rounds": len(rounds),
            "draft_slot": draft_slot,
            "scoring": scoring,
            "picks": picks,
            "rosters": rosters(picks),
            "current_pick": None,
            "next_user_pick": None,
            "is_user_turn": False,
            "transition": "synthetic_actual_board_complete",
        }
    )
    return reports


def evaluate_mock_rosters(
    final_report: Mapping[str, Any],
    board: Iterable[Mapping[str, Any]],
    draft: Mapping[str, Any],
    *,
    rank_weights: Iterable[float] = (0.0, 0.5, 1.0),
    bench_weight: float = 0.30,
) -> dict[str, Any]:
    """Evaluate a completed mock with the watcher's deterministic team metric."""
    rows = list(board)
    players = expert_ordered_projection_players(
        [
            Player.from_mapping(row)
            for row in rows
            if str(row.get("position") or "").upper().replace("DEF", "DST")
            in SKILL_POSITIONS
        ]
    )
    by_id = {
        str(row.get("sleeper_id")): Player.from_mapping(row)
        for row in rows
        if row.get("sleeper_id") not in (None, "")
        and str(row.get("position") or "").upper().replace("DEF", "DST")
        in SKILL_POSITIONS
    }
    by_name = {
        normalize_name(str(row.get("player_name") or "")): Player.from_mapping(row)
        for row in rows
        if str(row.get("position") or "").upper().replace("DEF", "DST")
        in SKILL_POSITIONS
    }
    roster_positions = roster_positions_from_draft(draft)
    teams = int(final_report.get("teams") or (draft.get("settings") or {}).get("teams") or 0)
    rounds = int(final_report.get("rounds") or (draft.get("settings") or {}).get("rounds") or 0)
    special_rounds = sum(
        position in {"K", "DEF", "DST"} for position in roster_positions
    )
    skill_rounds = max(1, rounds - special_rounds)
    raw_baselines = market_replacement_baselines(players, teams, skill_rounds)
    curve = fit_rank_vorp_curve(
        players, raw_baselines, maximum_rank=teams * skill_rounds
    )
    roster_player_keys: dict[int, list[str]] = {}
    unmatched = []
    for slot_value, picks in (final_report.get("rosters") or {}).items():
        slot = int(slot_value)
        roster_player_keys[slot] = []
        for pick in picks or []:
            player = by_id.get(str(pick.get("player_id") or ""))
            if player is None:
                metadata = pick.get("metadata") or {}
                name = " ".join(
                    part
                    for part in (
                        str(metadata.get("first_name") or "").strip(),
                        str(metadata.get("last_name") or "").strip(),
                    )
                    if part
                )
                player = by_name.get(normalize_name(name))
            if player is not None:
                roster_player_keys[slot].append(player.key)
            elif str((pick.get("metadata") or {}).get("position") or "").upper() in (
                *SKILL_POSITIONS,
            ):
                unmatched.append(
                    {
                        "slot": slot,
                        "pick_no": int(pick.get("pick_no") or 0),
                        "player_id": str(pick.get("player_id") or ""),
                    }
                )

    channels = {}
    draft_slot = int(final_report.get("draft_slot") or 0)
    for rank_weight in rank_weights:
        adjusted = {
            player.key: player
            for player in rank_adjusted_players(
                players, curve, float(rank_weight), raw_baselines
            )
        }
        baselines = market_replacement_baselines(
            list(adjusted.values()), teams, skill_rounds
        )
        strengths = {}
        weekly_use = {}
        for slot, keys in roster_player_keys.items():
            strength = deterministic_roster_strength(
                [adjusted[key] for key in keys], roster_positions, baselines
            )
            weekly_use[slot] = weekly_use_roster_strength(
                [adjusted[key] for key in keys], roster_positions, baselines
            )
            strength["policy_score"] = (
                strength["bye_adjusted_lineup_score"]
                + bench_weight * strength["usable_bench_vorp"]
            )
            strengths[slot] = {
                key: round(float(value), 3) for key, value in strength.items()
            }
        ordered = sorted(
            strengths,
            key=lambda slot: (-strengths[slot]["policy_score"], slot),
        )
        channels[f"{float(rank_weight):.2f}"] = {
            "user": strengths.get(draft_slot),
            "user_rank": ordered.index(draft_slot) + 1 if draft_slot in ordered else None,
            "team_count": len(ordered),
            "ordered_slots": ordered,
            "policy_scores": {
                str(slot): strengths[slot]["policy_score"] for slot in ordered
            },
            "weekly_use": {str(slot): weekly_use[slot] for slot in ordered},
        }
    return {
        "method": "deterministic_lineup_plus_0.30_usable_bench_vorp",
        "projection_value_method": "expert_ordered_positional_projection_curve",
        "raw_projections_preserved": True,
        "bench_weight": bench_weight,
        "primary_objective_method": "no_bye_common_absence_and_projection_miss",
        "draft_slot": draft_slot,
        "skill_rounds": skill_rounds,
        "unmatched_skill_picks": unmatched,
        "channels": channels,
    }
