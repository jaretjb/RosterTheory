"""Draft watcher state transitions and recommendation policy."""

from __future__ import annotations

import re
import time
from collections import Counter
from dataclasses import dataclass, field, replace
from typing import Any, Iterable, Mapping

from roster_theory.draft.analysis import HistoricalPositionCurves
from roster_theory.core.roster import require_no_taxi_settings
from roster_theory.draft_preferences import DraftPreferenceBook, evaluate_draft_preferences
from roster_theory.rankings import normalize_name
from roster_theory.specialist_preferences import defense_draft_rank, defense_draft_sort_key
from roster_theory.draft.simulation import (
    Player,
    POSITION_CAPS,
    SKILL_POSITIONS,
    _filled_starter_slots,
    acquisition_adp_metadata,
    apply_acquisition_adp,
    bounded_multi_turn_rollout,
    expert_ordered_projection_players,
    fit_rank_vorp_curve,
    market_replacement_baselines,
    next_pick_for_slot,
    rank_user_candidates,
    rank_adjusted_players,
    snake_slot,
    survival_probability,
)
from roster_theory.sleeper_adp import scoring_adp_field


ACQUISITION_MODES = ("human_league", "sleeper_cpu")
EXPERT_DISAGREEMENT_SD_THRESHOLD = 6.0
EXPERT_DISAGREEMENT_RELATIVE_THRESHOLD = 0.25
EXPERT_DISAGREEMENT_MIN_EXPERTS = 8
EXPERT_DISAGREEMENT_MIN_WEIGHT_COVERAGE = 0.8


def _validate_sleeper_cpu_snapshot(
    snapshot: Mapping[str, Any] | None,
    scoring: str,
) -> None:
    if snapshot is None:
        raise ValueError("Sleeper CPU acquisition mode requires a Sleeper ADP snapshot")
    snapshot_scoring = str(snapshot.get("scoring") or "")
    if snapshot_scoring != scoring:
        raise ValueError(
            "Sleeper ADP snapshot scoring does not match the draft: "
            f"{snapshot_scoring or 'missing'} versus {scoring}"
        )
    expected_field = scoring_adp_field(scoring)
    if str(snapshot.get("adp_field") or "") != expected_field:
        raise ValueError(
            "Sleeper ADP snapshot field does not match the draft scoring: "
            f"expected {expected_field}"
        )
    if not isinstance(snapshot.get("players"), list) or not snapshot.get("players"):
        raise ValueError("Sleeper ADP snapshot contains no usable players")


def _apply_sleeper_cpu_adp(
    players: Iterable[Player],
    snapshot: Mapping[str, Any],
) -> tuple[list[Player], dict[str, Any]]:
    """Attach Sleeper's player ADP for CPU-room timing only."""

    adp_by_id: dict[str, float] = {}
    for row in snapshot.get("players") or []:
        player_id = str(row.get("player_id") or "")
        try:
            sleeper_adp = float(row.get("sleeper_adp"))
        except (TypeError, ValueError):
            continue
        if player_id and 0.0 < sleeper_adp < 999.0:
            adp_by_id[player_id] = sleeper_adp

    adjusted: list[Player] = []
    eligible = matched = fallback = 0
    for player in players:
        sleeper_id = (
            player.key.split(":", 1)[1]
            if player.key.startswith("sleeper_id:")
            else player.key
        )
        sleeper_adp = adp_by_id.get(sleeper_id)
        if player.position in SKILL_POSITIONS:
            eligible += 1
            if sleeper_adp is None:
                fallback += 1
            else:
                matched += 1
        adjusted.append(
            replace(
                player,
                acquisition_adp=(
                    sleeper_adp
                    if player.position in SKILL_POSITIONS and sleeper_adp is not None
                    else player.adp
                ),
                acquisition_position_slot=None,
            )
        )

    source = snapshot.get("source") or {}
    return adjusted, {
        "mode": "sleeper_cpu",
        "variant_enabled": True,
        "adjustment_applied": matched > 0,
        "history_weight": None,
        "history_available": False,
        "history_applied": False,
        "history_source": None,
        "history_sources": [],
        "draft_count": 0,
        "draft_end_pick": None,
        "excluded_user_ids": [],
        "exclusion_audit": [],
        "fallback_state": "unmatched_players_use_market_adp" if fallback else None,
        "issues": [],
        "cpu_mock_only": True,
        "raw_adp_preserved": True,
        "source_type": "sleeper_scoring_specific_adp_snapshot",
        "source_endpoint": source.get("endpoint"),
        "snapshot_scoring": snapshot.get("scoring"),
        "snapshot_adp_field": snapshot.get("adp_field"),
        "snapshot_captured_at": snapshot.get("captured_at"),
        "snapshot_players": len(adp_by_id),
        "eligible_board_players": eligible,
        "matched_board_players": matched,
        "market_adp_fallback_players": fallback,
        "coverage": round(matched / eligible, 6) if eligible else 0.0,
    }


def _human_acquisition_metadata(
    history: HistoricalPositionCurves | None,
    history_weight: float | None,
) -> dict[str, Any]:
    metadata = acquisition_adp_metadata(history, history_weight)
    metadata["mode"] = "human_league"
    metadata["adjustment_applied"] = metadata["history_applied"]
    metadata["cpu_mock_only"] = False
    metadata["raw_adp_preserved"] = True
    return metadata



def parse_draft_id(value: str) -> str:
    text = value.strip()
    if text.isdigit():
        return text
    matches = re.findall(r"(?<!\d)(\d{10,})(?!\d)", text)
    if len(matches) != 1:
        raise ValueError("Provide one Sleeper draft_id or draftboard URL")
    return matches[0]


def scoring_family(draft: Mapping[str, Any]) -> str:
    value = str((draft.get("metadata") or {}).get("scoring_type") or "").lower()
    normalized = value.replace("-", "_").replace(" ", "_")
    if normalized in {"std", "standard", "non_ppr"}:
        return "standard"
    if normalized in {"half", "half_ppr", "0.5_ppr"}:
        return "half_ppr"
    if normalized in {"ppr", "full_ppr"}:
        return "ppr"
    return "unknown"


def policy_pair_for_scoring(
    scoring: str,
    teams: int | None = None,
    roster_positions: Iterable[str] | None = None,
) -> tuple[str, str]:
    if scoring == "standard":
        return "standard_reconciled", "standard_expert_ordered_curve"
    if scoring == "half_ppr":
        positions = tuple(roster_positions or ())
        calibrated_ten_team_roster = (
            positions.count("QB") == 1
            and positions.count("RB") == 2
            and positions.count("WR") == 2
            and positions.count("TE") == 1
            and positions.count("WRRB_FLEX") == 1
            and positions.count("FLEX") == 0
            and positions.count("REC_FLEX") == 0
            and positions.count("SUPER_FLEX") == 0
        )
        if teams == 10 and calibrated_ten_team_roster:
            return (
                "half_ppr_reconciled_tol05",
                "half_ppr_expert_ordered_curve",
            )
        calibrated_league_beta_roster = (
            positions.count("QB") == 1
            and positions.count("RB") == 2
            and positions.count("WR") == 2
            and positions.count("TE") == 1
            and positions.count("FLEX") == 2
            and positions.count("SUPER_FLEX") == 0
        )
        if teams == 12 and calibrated_league_beta_roster:
            return (
                "half_ppr_reconciled_horizon_guard",
                "half_ppr_expert_ordered_curve",
            )
        return "half_ppr_reconciled", "half_ppr_expert_ordered_curve"
    raise ValueError(f"No calibrated policy pair is available for {scoring} scoring")


def resolve_draft_slot(
    draft: Mapping[str, Any],
    claimed_slot: int | None = None,
    user_id: str | None = None,
) -> int:
    teams = int((draft.get("settings") or {}).get("teams") or 0)
    if claimed_slot is not None:
        if not 1 <= claimed_slot <= teams:
            raise ValueError(f"Draft slot must be between 1 and {teams}")
        return claimed_slot
    order = draft.get("draft_order") or {}
    if user_id and isinstance(order, Mapping):
        direct = order.get(str(user_id))
        if direct is not None:
            return int(direct)
        for slot, ordered_user_id in order.items():
            if str(ordered_user_id) == str(user_id) and str(slot).isdigit():
                return int(slot)
    raise ValueError("Claim a draft slot with --slot or provide --user-id present in draft_order")


def roster_positions_from_draft(draft: Mapping[str, Any]) -> list[str]:
    settings = draft.get("settings") or {}
    mapping = (
        ("slots_qb", "QB"),
        ("slots_rb", "RB"),
        ("slots_wr", "WR"),
        ("slots_te", "TE"),
        ("slots_flex", "FLEX"),
        ("slots_wrrb_flex", "WRRB_FLEX"),
        ("slots_rec_flex", "REC_FLEX"),
        ("slots_super_flex", "SUPER_FLEX"),
        ("slots_k", "K"),
        ("slots_def", "DEF"),
        ("slots_bn", "BN"),
    )
    result: list[str] = []
    for key, position in mapping:
        result.extend([position] * int(settings.get(key) or 0))
    return result


def _canonical_picks(picks: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    by_number: dict[int, dict[str, Any]] = {}
    for source in picks:
        pick_no = int(source.get("pick_no") or 0)
        if pick_no > 0:
            by_number[pick_no] = dict(source)
    return [by_number[number] for number in sorted(by_number)]


def _pick_identity(pick: Mapping[str, Any]) -> tuple[int, str, int]:
    return (
        int(pick.get("draft_slot") or 0),
        str(pick.get("player_id") or ""),
        int(pick.get("roster_id") or 0),
    )


def _transition(
    previous: "MockDraftState | None", picks: list[dict[str, Any]]
) -> tuple[str, list[dict[str, Any]], list[int], list[int]]:
    if previous is None:
        return "initial", list(picks), [], []
    before = {int(pick["pick_no"]): pick for pick in previous.picks}
    after = {int(pick["pick_no"]): pick for pick in picks}
    removed = sorted(set(before) - set(after))
    edited = sorted(
        number
        for number in set(before) & set(after)
        if _pick_identity(before[number]) != _pick_identity(after[number])
    )
    added_numbers = sorted(set(after) - set(before))
    added = [after[number] for number in added_numbers]
    if removed:
        kind = "undo"
    elif edited:
        kind = "edit"
    elif not added:
        kind = "duplicate"
    elif not before or min(added_numbers) > max(before):
        kind = "append"
    else:
        kind = "rewrite"
    return kind, added, removed, edited


@dataclass(slots=True)
class MockDraftState:
    draft_id: str
    status: str
    teams: int
    rounds: int
    draft_slot: int
    scoring: str
    picks: list[dict[str, Any]]
    rosters: dict[int, list[dict[str, Any]]]
    current_pick: int | None
    next_user_pick: int | None
    is_user_turn: bool
    transition: str
    newly_drafted: list[dict[str, Any]] = field(default_factory=list)
    removed_pick_numbers: list[int] = field(default_factory=list)
    edited_pick_numbers: list[int] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def reconcile_draft_state(
    draft: Mapping[str, Any],
    picks: Iterable[Mapping[str, Any]],
    draft_slot: int,
    previous: MockDraftState | None = None,
    scoring_override: str | None = None,
) -> MockDraftState:
    canonical = _canonical_picks(picks)
    settings = draft.get("settings") or {}
    teams = int(settings.get("teams") or 0)
    rounds = int(settings.get("rounds") or 0)
    require_no_taxi_settings(settings, context="Draft roster membership")
    maximum_pick = teams * rounds
    status = str(draft.get("status") or "unknown")
    current_pick = None if status == "complete" else min(
        maximum_pick + 1,
        (max((int(pick["pick_no"]) for pick in canonical), default=0) + 1),
    )
    if current_pick and current_pick > maximum_pick:
        current_pick = None
    rosters = {slot: [] for slot in range(1, teams + 1)}
    for pick in canonical:
        slot = int(pick.get("draft_slot") or 0)
        if slot in rosters:
            rosters[slot].append(pick)
    transition, added, removed, edited = _transition(previous, canonical)
    warnings: list[str] = []
    pick_numbers = [int(pick["pick_no"]) for pick in canonical]
    if pick_numbers and pick_numbers != list(range(1, max(pick_numbers) + 1)):
        warnings.append("authoritative picks contain gaps; current pick follows the highest pick number")
    if int(settings.get("reversal_round") or 0):
        warnings.append("third-round reversal is not supported by turn projection")
    reported_scoring = scoring_family(draft)
    if scoring_override and scoring_override != reported_scoring:
        warnings.append(
            f"using approved {scoring_override} scoring override; "
            f"Sleeper room reports {reported_scoring}"
        )
    is_user_turn = bool(
        current_pick is not None and snake_slot(current_pick, teams) == draft_slot
    )
    next_user_pick = (
        next_pick_for_slot(
            current_pick if is_user_turn else current_pick - 1,
            draft_slot,
            teams,
            rounds,
        )
        if current_pick is not None
        else None
    )
    return MockDraftState(
        draft_id=str(draft.get("draft_id") or ""),
        status=status,
        teams=teams,
        rounds=rounds,
        draft_slot=draft_slot,
        scoring=scoring_override or reported_scoring,
        picks=canonical,
        rosters=rosters,
        current_pick=current_pick,
        next_user_pick=next_user_pick,
        is_user_turn=is_user_turn,
        transition=transition,
        newly_drafted=added,
        removed_pick_numbers=removed,
        edited_pick_numbers=edited,
        warnings=warnings,
    )


def _pick_position(pick: Mapping[str, Any]) -> str:
    position = str((pick.get("metadata") or {}).get("position") or "").upper()
    return "DST" if position == "DEF" else position


def _drafted_probability_by(adp: float, pick_no: int) -> float:
    if pick_no <= 0 or not 0.0 < adp < 999.0:
        return 0.0
    return 1.0 - survival_probability(adp, 0, pick_no)


def live_position_pace(
    picks: Iterable[Mapping[str, Any]],
    players: Iterable[Player],
    completed_pick: int,
    recent_window: int = 12,
) -> dict[str, dict[str, float]]:
    """Return restrained live-room position multipliers versus acquisition pace."""

    positions = tuple(SKILL_POSITIONS)
    canonical = [
        pick
        for pick in picks
        if 0 < int(pick.get("pick_no") or 0) <= completed_pick
        and _pick_position(pick) in positions
    ]
    if not canonical:
        return {
            position: {
                "observed": 0.0,
                "expected": 0.0,
                "recent_observed": 0.0,
                "recent_expected": 0.0,
                "multiplier": 1.0,
            }
            for position in positions
        }

    player_list = [
        player
        for player in players
        if player.position in positions and 0.0 < player.acquisition_pick < 999.0
    ]
    observed = Counter(_pick_position(pick) for pick in canonical)

    def expected_counts(start_pick: int, end_pick: int, observed_total: int) -> dict[str, float]:
        weights = Counter()
        for player in player_list:
            probability = max(
                0.0,
                _drafted_probability_by(player.acquisition_pick, end_pick)
                - _drafted_probability_by(player.acquisition_pick, start_pick - 1),
            )
            weights[player.position] += probability
        total_weight = sum(weights.values())
        if total_weight <= 0.0 or observed_total <= 0:
            return {position: 0.0 for position in positions}
        return {
            position: observed_total * float(weights[position]) / total_weight
            for position in positions
        }

    expected = expected_counts(1, completed_pick, len(canonical))
    recent_start = max(1, completed_pick - max(1, recent_window) + 1)
    recent_picks = [
        pick for pick in canonical if int(pick.get("pick_no") or 0) >= recent_start
    ]
    recent_observed = Counter(_pick_position(pick) for pick in recent_picks)
    recent_expected = expected_counts(
        recent_start, completed_pick, len(recent_picks)
    )

    def shrunk_ratio(
        position: str,
        actual: Counter[str],
        modeled: Mapping[str, float],
        sample_size: int,
        prior_picks: float,
    ) -> float:
        if sample_size <= 0:
            return 1.0
        expected_value = float(modeled.get(position) or 0.0)
        expected_share = max(0.05, expected_value / sample_size)
        pseudocount = prior_picks * expected_share
        return (float(actual[position]) + pseudocount) / (
            expected_value + pseudocount
        )

    result: dict[str, dict[str, float]] = {}
    for position in positions:
        cumulative = shrunk_ratio(
            position, observed, expected, len(canonical), 24.0
        )
        recent = (
            shrunk_ratio(
                position,
                recent_observed,
                recent_expected,
                len(recent_picks),
                12.0,
            )
            if len(recent_picks) >= 4
            else 1.0
        )
        multiplier = max(0.80, min(1.25, cumulative ** 0.70 * recent ** 0.30))
        result[position] = {
            "observed": float(observed[position]),
            "expected": round(float(expected[position]), 3),
            "recent_observed": float(recent_observed[position]),
            "recent_expected": round(float(recent_expected[position]), 3),
            "multiplier": round(multiplier, 4),
        }
    return result


def _seat_position_factor(
    player: Player,
    roster: list[Player],
    roster_positions: Iterable[str],
    round_no: int,
) -> float:
    counts = Counter(item.position for item in roster)
    if counts[player.position] >= POSITION_CAPS.get(player.position, 99):
        return 0.0
    dedicated = Counter(
        position for position in roster_positions if position in SKILL_POSITIONS
    )
    if counts[player.position] < dedicated[player.position]:
        if player.position in {"QB", "TE"}:
            return 0.90 if round_no < 6 else 1.25
        return 1.20
    before = _filled_starter_slots(roster, roster_positions)
    after = _filled_starter_slots([*roster, player], roster_positions)
    if after > before:
        return 1.10
    return 0.85 if player.position in {"RB", "WR"} else 0.55


def room_survival_probabilities(
    players: Iterable[Player],
    rosters: Mapping[int, list[Player]],
    roster_positions: Iterable[str],
    picks: Iterable[Mapping[str, Any]],
    current_pick: int,
    next_user_pick: int | None,
    teams: int,
) -> tuple[dict[str, float], dict[str, Any]]:
    """Adjust next-pick survival for exact intervening seats and live room pace."""

    player_list = list(players)
    opponent_picks = (
        list(range(current_pick + 1, next_user_pick))
        if next_user_pick is not None
        else []
    )
    pace = live_position_pace(picks, player_list, current_pick - 1)
    if not opponent_picks:
        return (
            {player.key: 1.0 for player in player_list},
            {
                "intervening_picks": [],
                "intervening_slots": [],
                "position_pace": pace,
            },
        )

    result: dict[str, float] = {}
    for player in player_list:
        baseline = survival_probability(
            player.acquisition_pick,
            current_pick,
            next_user_pick,
        )
        one_pick_hazard = 1.0 - baseline ** (1.0 / len(opponent_picks))
        survival = 1.0
        for pick_no in opponent_picks:
            slot = snake_slot(pick_no, teams)
            round_no = ((pick_no - 1) // teams) + 1
            seat_factor = _seat_position_factor(
                player,
                list(rosters.get(slot) or []),
                roster_positions,
                round_no,
            )
            hazard = min(
                0.95,
                one_pick_hazard
                * seat_factor
                * float(pace[player.position]["multiplier"]),
            )
            survival *= 1.0 - hazard
        result[player.key] = max(0.0, min(1.0, survival))
    return (
        result,
        {
            "intervening_picks": opponent_picks,
            "intervening_slots": [snake_slot(pick_no, teams) for pick_no in opponent_picks],
            "position_pace": pace,
        },
    )


def _picked_board_keys(picks: Iterable[Mapping[str, Any]]) -> set[str]:
    result: set[str] = set()
    for pick in picks:
        player_id = str(pick.get("player_id") or "")
        if player_id:
            result.update({player_id, f"sleeper_id:{player_id}"})
        metadata = pick.get("metadata") or {}
        name = normalize_name(
            f"{metadata.get('first_name', '')} {metadata.get('last_name', '')}".strip()
        )
        if name:
            result.add(f"name:{name}")
    return result


def _board_indexes(
    board: Iterable[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    rows = [dict(row) for row in board]
    by_id = {
        str(row.get("sleeper_id")): row
        for row in rows
        if str(row.get("sleeper_id") or "")
    }
    by_name = {
        normalize_name(str(row.get("player_name") or "")): row
        for row in rows
        if str(row.get("player_name") or "")
    }
    return rows, by_id, by_name


def _validate_board_scoring(rows: Iterable[Mapping[str, Any]], scoring: str) -> None:
    expected = {"standard": "STD", "half_ppr": "HALF"}.get(scoring)
    if expected is None:
        raise ValueError(f"No board validation rule is available for {scoring} scoring")
    observed = {
        str(row.get("scoring") or "").upper()
        for row in rows
        if str(row.get("position") or "").upper() in SKILL_POSITIONS
        and str(row.get("scoring") or "")
    }
    if observed and observed != {expected}:
        raise ValueError(
            f"Draft scoring is {scoring}, but skill-player board scoring is {sorted(observed)}"
        )


def _pick_to_player(
    pick: Mapping[str, Any],
    by_id: Mapping[str, Mapping[str, Any]],
    by_name: Mapping[str, Mapping[str, Any]],
) -> tuple[Player, bool]:
    player_id = str(pick.get("player_id") or "")
    metadata = pick.get("metadata") or {}
    name = f"{metadata.get('first_name', '')} {metadata.get('last_name', '')}".strip()
    row = by_id.get(player_id) or by_name.get(normalize_name(name))
    if row is not None:
        return Player.from_mapping(row), True
    position = str(metadata.get("position") or "UNKNOWN").upper().replace("DEF", "DST")
    return Player(
        key=f"sleeper_id:{player_id}" if player_id else f"name:{normalize_name(name)}",
        name=name or f"Unknown pick {pick.get('pick_no')}",
        position=position,
        projected_points=0.0,
        adp=999.0,
        vbd=0.0,
        rank_score=999.0,
        team=str(metadata.get("team") or ""),
    ), False


def _explain_leader(rows: list[dict[str, Any]]) -> str:
    leader = rows[0]
    runner_up = rows[1] if len(rows) > 1 else None
    if leader.get("selection_basis") == "selected_expert_overall_consensus":
        parts = [
            f"{leader['player_name']} is the highest available weighted overall choice",
            f"selected-expert rank {leader.get('overall_expert_rank')}",
        ]
        if runner_up:
            parts.append(
                f"ahead of {runner_up['player_name']} at rank "
                f"{runner_up.get('overall_expert_rank')}"
            )
        return "; ".join(parts)
    parts = [
        f"{leader['player_name']} leads as {leader['roster_need']}",
        f"score {leader['final_score']}",
        f"VONA {leader['vona']}",
        f"next-pick survival {100 * float(leader['next_pick_survival']):.1f}%",
    ]
    if leader.get("turn_aware_qb_deferred"):
        parts.append(
            f"wait on {leader.get('turn_aware_qb_name')} with "
            f"{100 * float(leader.get('turn_aware_qb_survival') or 0.0):.1f}% "
            "survival to the next contested pick"
        )
    if leader.get("starter_deferred"):
        parts.append(
            f"starter deferral effect {leader.get('starter_deferral_effect')}"
        )
    if (
        leader.get("roster_need") == "bench_depth"
        and leader.get("deterministic_bench_marginal") is not None
    ):
        parts.append(
            "roster-adjusted reserve marginal "
            f"{leader.get('deterministic_bench_marginal')}"
        )
    if runner_up:
        difference = float(leader["final_score"]) - float(runner_up["final_score"])
        if difference >= 0.0:
            parts.append(
                f"ahead of {runner_up['player_name']} by {difference:.3f}"
            )
        elif leader.get("turn_aware_qb_deferred"):
            parts.append(
                "turn-horizon QB guard moves this above "
                f"{runner_up['player_name']}; ordinary path score is "
                f"{abs(difference):.3f} lower"
            )
        elif leader.get("planned_turn_preserved"):
            parts.append(
                "adjacent plan keeps this above "
                f"{runner_up['player_name']}; recalculated score is "
                f"{abs(difference):.3f} lower"
            )
        elif leader.get("sequence_option_promoted"):
            parts.append(
                "elite-TE option moves this above "
                f"{runner_up['player_name']}; current-path score is "
                f"{abs(difference):.3f} lower"
            )
        else:
            parts.append(
                f"expert-order constraint keeps this above {runner_up['player_name']}; "
                f"raw model score is {abs(difference):.3f} lower"
            )
    sensitivity = leader.get("rank_adjusted_vorp") or {}
    if sensitivity:
        parts.append(
            "VORP curve/50%-rank/100%-rank "
            + "/".join(
                str(sensitivity.get(key)) for key in ("0.00", "0.50", "1.00")
            )
        )
    return "; ".join(parts)


def _compact_decision_signal(
    recommendations: Mapping[str, list[Mapping[str, Any]]],
    policies: Iterable[str],
    preference_overlay: Mapping[str, Any] | None = None,
    plan_conflict: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Return at most one decision-worthy line for the live watcher."""

    policy_list = list(policies)
    if not policy_list:
        return None
    primary_rows = list(recommendations.get(policy_list[0]) or [])
    if not primary_rows:
        return None
    leader = primary_rows[0]
    if plan_conflict:
        return {"kind": "plan_changed", **dict(plan_conflict)}
    if leader.get("turn_aware_qb_deferred"):
        return {
            "kind": "wait_on_qb",
            "player_name": leader.get("player_name"),
            "qb_name": leader.get("turn_aware_qb_name"),
            "qb_survival": leader.get("turn_aware_qb_survival"),
            "turn_package_gap": leader.get("turn_aware_qb_score_gap"),
            "continuation_pick": leader.get("continuation_pick"),
        }
    sean_now = []
    for target in (preference_overlay or {}).get("targets") or []:
        source = str(target.get("source") or "").lower()
        rank = target.get("candidate_rank")
        gap = target.get("primary_score_gap")
        if (
            target.get("call") == "NOW"
            and source.startswith("sean_koerner")
            and rank is not None
            and int(rank) > 1
            and gap is not None
            and 0.0 <= float(gap) <= 1.0
        ):
            sean_now.append(target)
    if not sean_now:
        return None
    target = min(
        sean_now,
        key=lambda row: (
            float(row.get("primary_score_gap") or 0.0),
            int(row.get("candidate_rank") or 999),
        ),
    )
    return {
        "kind": "consider_sean_now",
        "player_name": target.get("player_name"),
        "primary_player_name": leader.get("player_name"),
        "primary_score_gap": target.get("primary_score_gap"),
        "candidate_rank": target.get("candidate_rank"),
    }


def _preserve_planned_turn(
    ranked: list[dict[str, Any]],
    planned_turn: Mapping[str, Any] | None,
    current_pick: int,
    maximum_score_gap: float = 1.0,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """Keep a near-tied adjacent plan, or expose one material conflict."""

    if not ranked or not planned_turn:
        return ranked, None
    planned_pick = planned_turn.get("second_pick")
    planned_key = str(planned_turn.get("second_player_key") or "")
    if planned_pick != current_pick or not planned_key:
        return ranked, None
    planned_row = next(
        (row for row in ranked if str(row["_player"].key) == planned_key),
        None,
    )
    if planned_row is None or planned_row is ranked[0]:
        return ranked, None
    score_gap = float(ranked[0]["final_score"]) - float(planned_row["final_score"])
    if score_gap <= maximum_score_gap:
        planned_row["planned_turn_preserved"] = True
        planned_row["planned_turn_score_gap"] = round(score_gap, 3)
        return [planned_row, *(row for row in ranked if row is not planned_row)], None
    return ranked, {
        "player_name": ranked[0]["_player"].name,
        "planned_player_name": planned_row["_player"].name,
        "score_gap": round(score_gap, 3),
    }


def recommend_for_state(
    state: MockDraftState,
    draft: Mapping[str, Any],
    board: Iterable[Mapping[str, Any]],
    limit: int = 5,
    acquisition_history: HistoricalPositionCurves | None = None,
    history_weight: float | None = None,
    policy_override: tuple[str, ...] | None = None,
    ballot_preferences: Mapping[tuple[str, str], float] | None = None,
    draft_preferences: DraftPreferenceBook | None = None,
    preference_scoring_settings: Mapping[str, Any] | None = None,
    preference_display_limit: int = 3,
    acquisition_mode: str = "human_league",
    sleeper_adp_snapshot: Mapping[str, Any] | None = None,
    planned_turn: Mapping[str, Any] | None = None,
    rollout_shadow: bool = False,
    rollout_scenarios: int = 8,
    rollout_seed: int | None = None,
    rollout_market_noise: float = 2.5,
    rollout_position_run_sigma: float = 0.18,
    rollout_round_position_rates: Mapping[int, Mapping[str, float]] | None = None,
) -> dict[str, Any]:
    if acquisition_mode not in ACQUISITION_MODES:
        raise ValueError(f"Unsupported acquisition mode: {acquisition_mode}")
    if acquisition_mode == "sleeper_cpu":
        _validate_sleeper_cpu_snapshot(sleeper_adp_snapshot, state.scoring)
        if acquisition_history is not None or history_weight is not None:
            raise ValueError(
                "Sleeper CPU acquisition mode cannot be combined with league history"
            )
    if state.current_pick is None:
        return {"recommendations": {}, "unmatched_user_picks": [], "reason": "draft complete"}
    configured_roster_positions = roster_positions_from_draft(draft)
    policies = policy_override or policy_pair_for_scoring(
        state.scoring, state.teams, configured_roster_positions
    )
    rows, by_id, by_name = _board_indexes(board)
    _validate_board_scoring(rows, state.scoring)
    picked_keys = _picked_board_keys(state.picks)
    available_rows = []
    for row in rows:
        keys = {
            str(row.get("player_key") or ""),
            str(row.get("sleeper_id") or ""),
            f"sleeper_id:{row.get('sleeper_id')}",
            f"name:{normalize_name(str(row.get('player_name') or ''))}",
        }
        if not keys & picked_keys:
            available_rows.append(row)
    raw_source_players = [
        Player.from_mapping(row)
        for row in rows
        if str(row.get("position") or "").upper() in (*SKILL_POSITIONS, "K", "DST", "DEF")
    ]
    market_players = expert_ordered_projection_players(raw_source_players)
    source_vbd_by_key = {player.key: player.vbd for player in raw_source_players}
    if acquisition_mode == "sleeper_cpu":
        acquisition_players, acquisition_metadata = _apply_sleeper_cpu_adp(
            raw_source_players,
            sleeper_adp_snapshot or {},
        )
    else:
        acquisition_players = apply_acquisition_adp(
            raw_source_players,
            acquisition_history,
            float(history_weight or 0.0),
        )
        acquisition_metadata = _human_acquisition_metadata(
            acquisition_history, history_weight
        )
    all_players = expert_ordered_projection_players(acquisition_players)
    available_keys = {
        Player.from_mapping(row).key
        for row in available_rows
        if str(row.get("position") or "").upper() in SKILL_POSITIONS
    }
    available_players = [
        player
        for player in all_players
        if player.position in SKILL_POSITIONS and player.key in available_keys
    ]
    market_by_key = {player.key: player for player in market_players}
    adjusted_by_key = {player.key: player for player in all_players}
    adjusted_rosters: dict[int, list[Player]] = {
        slot: [] for slot in range(1, state.teams + 1)
    }
    market_rosters: dict[int, list[Player]] = {
        slot: [] for slot in range(1, state.teams + 1)
    }
    unmatched: list[dict[str, Any]] = []
    for slot, roster_picks in state.rosters.items():
        for pick in roster_picks:
            player, matched = _pick_to_player(pick, by_id, by_name)
            adjusted_rosters[slot].append(adjusted_by_key.get(player.key, player))
            market_rosters[slot].append(market_by_key.get(player.key, player))
            if slot == state.draft_slot and not matched:
                unmatched.append(
                    {
                        "pick_no": int(pick.get("pick_no") or 0),
                        "player_id": str(pick.get("player_id") or ""),
                        "player_name": player.name,
                        "position": player.position,
                    }
                )
    user_roster = adjusted_rosters[state.draft_slot]
    market_user_roster = market_rosters[state.draft_slot]
    roster_positions = configured_roster_positions
    special_rounds = sum(position in {"K", "DEF", "DST"} for position in roster_positions)
    skill_rounds = max(1, state.rounds - special_rounds)
    replacement_baselines = market_replacement_baselines(
        [player for player in all_players if player.position in SKILL_POSITIONS],
        state.teams,
        skill_rounds,
    )
    rank_weights = (0.0, 0.5, 1.0)
    rank_vorp_curve = fit_rank_vorp_curve(
        [player for player in all_players if player.position in SKILL_POSITIONS],
        replacement_baselines,
        maximum_rank=state.teams * skill_rounds,
    )
    adjusted_players = {
        rank_weight: {
            player.key: player
            for player in rank_adjusted_players(
                [
                    player
                    for player in all_players
                    if player.position in SKILL_POSITIONS
                ],
                rank_vorp_curve,
                rank_weight,
                replacement_baselines,
            )
        }
        for rank_weight in rank_weights
    }
    adjusted_baselines = {
        rank_weight: market_replacement_baselines(
            list(adjusted_players[rank_weight].values()),
            state.teams,
            skill_rounds,
        )
        for rank_weight in rank_weights
    }
    current_round = ((state.current_pick - 1) // state.teams) + 1
    missing_special = [
        position
        for position in ("DST", "K")
        if any(slot in ({"DEF", "DST"} if position == "DST" else {"K"}) for slot in roster_positions)
        and not any(player.position == position for player in user_roster)
    ]
    remaining_user_picks = state.rounds - current_round + 1
    force_special = bool(missing_special and remaining_user_picks <= len(missing_special))
    if force_special:
        position = missing_special[0]
        specialist_reason = (
            f"{position} is required with {remaining_user_picks} picks remaining"
        )
        if set(missing_special) == {"DST", "K"}:
            available_defense_ranks = []
            for row in available_rows:
                if (
                    str(row.get("position") or "")
                    .upper()
                    .replace("DEF", "DST")
                    != "DST"
                ):
                    continue
                user_rank = defense_draft_rank(Player.from_mapping(row).team)
                if user_rank is not None:
                    available_defense_ranks.append(user_rank)
            best_defense_rank = min(available_defense_ranks, default=999.0)
            position = "DST" if best_defense_rank <= 3.0 else "K"
            specialist_reason = (
                f"{position} first with {remaining_user_picks} picks left; "
                "DST exception requires a user top-3 defense"
            )
        candidates = sorted(
            (
                Player.from_mapping(row)
                for row in available_rows
                if str(row.get("position") or "").upper().replace("DEF", "DST") == position
            ),
            key=(
                defense_draft_sort_key
                if position == "DST"
                else lambda player: (player.rank_score, player.adp)
            ),
        )
        if position == "DST" and candidates:
            user_rank = defense_draft_rank(candidates[0].team)
            specialist_reason += (
                f"; {candidates[0].name} is user DST{user_rank}"
                if user_rank is not None
                else "; user DST top 10 exhausted, using specialist experts"
            )
        recommendations = [
            {
                "player_key": player.key,
                "player_name": player.name,
                "position": player.position,
                "expert_rank": player.rank_score,
                "position_expert_rank": player.rank_score,
                "user_dst_rank": (
                    defense_draft_rank(player.team)
                    if player.position == "DST"
                    else None
                ),
                "specialist_rank_source": (
                    "user_2026_weeks_1_3_streaming"
                    if player.position == "DST"
                    and defense_draft_rank(player.team) is not None
                    else "selected_specialist_experts"
                ),
                "final_score": -float(
                    defense_draft_rank(player.team)
                    if player.position == "DST"
                    and defense_draft_rank(player.team) is not None
                    else player.rank_score
                ),
                "roster_need": f"open_{position.lower()}_starter",
            }
            for player in candidates[:limit]
        ]
        return {
            "policies": ["specialist_rank"],
            "recommendations": {"specialist_rank": recommendations},
            "explanations": {
                "specialist_rank": specialist_reason
            },
            "replacement_baselines": replacement_baselines,
            "acquisition_adp": acquisition_metadata,
            "unmatched_user_picks": unmatched,
        }
    result: dict[str, list[dict[str, Any]]] = {}
    explanations: dict[str, str] = {}
    skill_roster = [player for player in user_roster if player.position in SKILL_POSITIONS]
    market_skill_roster = [
        player for player in market_user_roster if player.position in SKILL_POSITIONS
    ]
    market_available_players = [
        player
        for player in market_players
        if player.position in SKILL_POSITIONS and player.key in available_keys
    ]
    league_survival_overrides, league_room_model = room_survival_probabilities(
        available_players,
        adjusted_rosters,
        roster_positions,
        state.picks,
        state.current_pick,
        state.next_user_pick,
        state.teams,
    )
    market_survival_overrides, market_room_model = room_survival_probabilities(
        market_available_players,
        market_rosters,
        roster_positions,
        state.picks,
        state.current_pick,
        state.next_user_pick,
        state.teams,
    )
    continuation_pick = None
    continuation_league_survival_overrides = None
    continuation_market_survival_overrides = None
    if state.next_user_pick == state.current_pick + 1:
        continuation_pick = next_pick_for_slot(
            state.next_user_pick, state.draft_slot, state.teams
        )
        if continuation_pick is not None:
            (
                continuation_league_survival_overrides,
                _,
            ) = room_survival_probabilities(
                available_players,
                adjusted_rosters,
                roster_positions,
                state.picks,
                state.next_user_pick,
                continuation_pick,
                state.teams,
            )
            (
                continuation_market_survival_overrides,
                _,
            ) = room_survival_probabilities(
                market_available_players,
                market_rosters,
                roster_positions,
                state.picks,
                state.next_user_pick,
                continuation_pick,
                state.teams,
            )
    split_policies: list[str] = []
    room_timing_split_policies: list[str] = []
    market_leaders: dict[str, str] = {}
    league_leaders: dict[str, str] = {}
    baseline_league_leaders: dict[str, str] = {}
    preference_candidate_rows: dict[str, dict[str, Any]] = {}
    primary_rollout_candidates: list[Player] = []
    plan_conflict: dict[str, Any] | None = None
    for policy in policies:
        ranked = rank_user_candidates(
            available_players,
            skill_roster,
            policy,
            state.current_pick,
            current_round,
            state.teams,
            state.draft_slot,
            roster_positions,
            skill_rounds,
            replacement_baselines,
            next_pick_survival_overrides=league_survival_overrides,
            rank_vorp_curve=rank_vorp_curve,
            reconciliation_baselines=adjusted_baselines,
            ballot_preferences=ballot_preferences,
            reconciliation_players=adjusted_players,
            continuation_survival_overrides=(
                continuation_league_survival_overrides
            ),
        )
        baseline_ranked = rank_user_candidates(
            available_players,
            skill_roster,
            policy,
            state.current_pick,
            current_round,
            state.teams,
            state.draft_slot,
            roster_positions,
            skill_rounds,
            replacement_baselines,
            rank_vorp_curve=rank_vorp_curve,
            reconciliation_baselines=adjusted_baselines,
            ballot_preferences=ballot_preferences,
            reconciliation_players=adjusted_players,
        )
        market_ranked = rank_user_candidates(
            market_available_players,
            market_skill_roster,
            policy,
            state.current_pick,
            current_round,
            state.teams,
            state.draft_slot,
            roster_positions,
            skill_rounds,
            replacement_baselines,
            next_pick_survival_overrides=market_survival_overrides,
            rank_vorp_curve=rank_vorp_curve,
            reconciliation_baselines=adjusted_baselines,
            ballot_preferences=ballot_preferences,
            reconciliation_players=adjusted_players,
            continuation_survival_overrides=(
                continuation_market_survival_overrides
            ),
        )
        if policy == policies[0]:
            ranked, plan_conflict = _preserve_planned_turn(
                ranked,
                planned_turn,
                int(state.current_pick),
            )
            primary_rollout_candidates = [
                row["_player"] for row in ranked[:3]
            ]
        if ranked:
            league_leaders[policy] = ranked[0]["_player"].name
        if policy == policies[0]:
            leader_score = float(ranked[0]["final_score"]) if ranked else 0.0
            preference_candidate_rows = {
                row["_player"].key: {
                    "roster_need": row.get("roster_need"),
                    "final_score": row.get("final_score"),
                    "candidate_rank": index,
                    "primary_score_gap": round(
                        leader_score - float(row.get("final_score") or 0.0), 3
                    ),
                }
                for index, row in enumerate(ranked, start=1)
            }
        if market_ranked:
            market_leaders[policy] = market_ranked[0]["_player"].name
        if baseline_ranked:
            baseline_league_leaders[policy] = baseline_ranked[0]["_player"].name
        if (
            ranked
            and baseline_ranked
            and ranked[0]["_player"].key != baseline_ranked[0]["_player"].key
        ):
            room_timing_split_policies.append(policy)
        if (
            acquisition_metadata["adjustment_applied"]
            and ranked
            and market_ranked
            and ranked[0]["_player"].key != market_ranked[0]["_player"].key
        ):
            split_policies.append(policy)
        clean = []
        for row in ranked[:limit]:
            player = row["_player"]
            visible = {key: value for key, value in row.items() if key != "_player"}
            visible["market_adp"] = round(player.adp, 3)
            visible["source_vbd"] = round(
                float(source_vbd_by_key.get(player.key) or 0.0), 3
            )
            visible["league_expected_pick"] = round(player.acquisition_pick, 3)
            visible["market_pick_delta"] = round(
                float(state.current_pick) - float(player.adp), 3
            )
            visible["league_pick_delta"] = round(
                float(state.current_pick) - float(player.acquisition_pick), 3
            )
            visible["market_survival"] = round(
                float(market_survival_overrides.get(player.key, 1.0)),
                6,
            )
            visible["league_survival"] = visible["next_pick_survival"]
            visible["acquisition_expected_pick"] = visible["league_expected_pick"]
            visible["acquisition_survival"] = visible["league_survival"]
            if acquisition_mode == "sleeper_cpu":
                visible["cpu_expected_pick"] = visible["league_expected_pick"]
                visible["cpu_survival"] = visible["league_survival"]
            visible["baseline_market_survival"] = round(
                survival_probability(
                    player.adp, state.current_pick, int(row["next_pick"])
                ),
                6,
            )
            visible["baseline_league_survival"] = round(
                survival_probability(
                    player.acquisition_pick,
                    state.current_pick,
                    int(row["next_pick"]),
                ),
                6,
            )
            visible["rank_adjusted_projected_points"] = {
                f"{rank_weight:.2f}": round(
                    adjusted_players[rank_weight][player.key].projected_points, 3
                )
                for rank_weight in rank_weights
            }
            visible["rank_adjusted_vorp"] = {
                f"{rank_weight:.2f}": round(
                    adjusted_players[rank_weight][player.key].projected_points
                    - float(
                        adjusted_baselines[rank_weight].get(player.position) or 0.0
                    ),
                    3,
                )
                for rank_weight in rank_weights
            }
            clean.append(visible)
        result[policy] = clean
        explanations[policy] = _explain_leader(clean)
    primary_rows = list(result.get(policies[0]) or []) if policies else []
    turn_plan = None
    if continuation_pick is not None and primary_rows:
        leader = primary_rows[0]
        second_player = (
            leader.get("turn_aware_next_path_player")
            or leader.get("expected_next_path_player")
        )
        second_player_key = leader.get("turn_aware_next_path_player_key")
        if second_player and second_player_key:
            turn_plan = {
                "first_pick": state.current_pick,
                "first_player_name": leader.get("player_name"),
                "second_pick": state.next_user_pick,
                "second_player_name": second_player,
                "second_player_key": second_player_key,
                "continuation_pick": continuation_pick,
                "continuation_player_name": leader.get(
                    "turn_aware_continuation_path_player"
                ),
            }
    rollout_evidence = None
    if rollout_shadow:
        rollout_started = time.perf_counter()
        if state.next_user_pick != state.current_pick + 1:
            rollout_evidence = {
                "status": "not_applicable",
                "reason": "not the first pick of an adjacent turn",
            }
        else:
            try:
                rollout_evidence = bounded_multi_turn_rollout(
                    available_players,
                    adjusted_rosters,
                    primary_rollout_candidates,
                    policy=policies[0],
                    current_pick=state.current_pick,
                    teams=state.teams,
                    draft_slot=state.draft_slot,
                    roster_positions=roster_positions,
                    total_user_picks=skill_rounds,
                    replacement_baselines=replacement_baselines,
                    scenarios=rollout_scenarios,
                    beam_width=3,
                    branch_width=2,
                    future_user_picks=5,
                    seed=(
                        rollout_seed
                        if rollout_seed is not None
                        else 904_000 + state.current_pick
                    ),
                    market_noise=rollout_market_noise,
                    position_run_sigma=rollout_position_run_sigma,
                    round_position_rates=rollout_round_position_rates,
                    position_pace_multipliers={
                        position: float(
                            (
                                (league_room_model.get("position_pace") or {}).get(
                                    position
                                )
                                or {}
                            ).get("multiplier")
                            or 1.0
                        )
                        for position in SKILL_POSITIONS
                    },
                    rank_vorp_curve=rank_vorp_curve,
                    reconciliation_baselines=adjusted_baselines,
                    reconciliation_players=adjusted_players,
                    evaluation_players_by_channel={
                        "unblended": adjusted_players[0.0],
                        "primary": adjusted_players[0.5],
                        "full_rank": adjusted_players[1.0],
                    },
                    evaluation_baselines_by_channel={
                        "unblended": adjusted_baselines[0.0],
                        "primary": adjusted_baselines[0.5],
                        "full_rank": adjusted_baselines[1.0],
                    },
                )
            except (ValueError, RuntimeError) as error:
                rollout_evidence = {
                    "status": "unavailable",
                    "reason": str(error),
                }
        rollout_evidence["latency_ms"] = round(
            1000.0 * (time.perf_counter() - rollout_started), 2
        )
    report = {
        "policies": list(policies),
        "recommendations": result,
        "explanations": explanations,
        "replacement_baselines": {
            position: round(value, 3) for position, value in replacement_baselines.items()
        },
        "rank_reconciliation": {
            "method": "expert_ordered_positional_curve_with_selected_rank_blend",
            "projection_value_method": "expert_ordered_positional_projection_curve",
            "raw_projections_preserved": True,
            "rank_weights": list(rank_weights),
            "curve_observations": rank_vorp_curve.observation_count,
            "curve_blocks": rank_vorp_curve.block_count,
        },
        "construction_context": {
            "one_qb": roster_positions.count("QB") == 1
            and "SUPER_FLEX" not in roster_positions,
        },
        "turn_horizon": {
            "adjacent_pick": state.next_user_pick == state.current_pick + 1,
            "immediate_next_pick": state.next_user_pick,
            "next_contested_pick": continuation_pick,
            "planned_turn": turn_plan,
            "plan_conflict": plan_conflict,
        },
        "acquisition_adp": acquisition_metadata,
        "model_split": bool(split_policies),
        "model_split_policies": split_policies,
        "room_timing_split": bool(room_timing_split_policies),
        "room_timing_split_policies": room_timing_split_policies,
        "market_leaders": market_leaders,
        "league_leaders": league_leaders,
        "acquisition_leaders": league_leaders,
        "cpu_leaders": league_leaders if acquisition_mode == "sleeper_cpu" else {},
        "baseline_league_leaders": baseline_league_leaders,
        "room_survival": {
            "method": "exact_intervening_seats_with_shrunk_live_position_pace",
            "market": market_room_model,
            "league": league_room_model,
            "acquisition": league_room_model,
            "cpu": league_room_model if acquisition_mode == "sleeper_cpu" else {},
        },
        "unmatched_user_picks": unmatched,
    }
    if rollout_evidence is not None:
        report["rollout_shadow"] = rollout_evidence
    if draft_preferences is not None:
        report["preference_overlay"] = evaluate_draft_preferences(
            draft_preferences,
            market_by_key,
            adjusted_by_key,
            available_keys,
            market_survival_overrides,
            league_survival_overrides,
            state.current_pick,
            result,
            candidate_rows=preference_candidate_rows,
            scoring_settings=preference_scoring_settings,
            display_limit=preference_display_limit,
            last_skill_pick=(
                not force_special
                and remaining_user_picks - 1 <= len(missing_special)
            ),
        )
    report["decision_signal"] = _compact_decision_signal(
        result,
        policies,
        report.get("preference_overlay"),
        plan_conflict,
    )
    return report
