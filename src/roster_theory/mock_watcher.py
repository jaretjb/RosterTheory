from __future__ import annotations

import re
import time
from collections import Counter
from dataclasses import dataclass, field, replace
from typing import Any, Iterable, Mapping

from roster_theory.draft_analysis import HistoricalPositionCurves
from roster_theory.draft_preferences import (
    DraftPreferenceBook,
    evaluate_draft_preferences,
)
from roster_theory.rankings import normalize_name
from roster_theory.specialist_preferences import (
    defense_draft_rank,
    defense_draft_sort_key,
)
from roster_theory.simulation import (
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
from roster_theory.sleeper import SleeperClient
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


def _pick_player_label(pick: Mapping[str, Any]) -> str:
    metadata = pick.get("metadata") or {}
    first = str(metadata.get("first_name") or "").strip()
    last = str(metadata.get("last_name") or "").strip()
    name = " ".join(part for part in (first, last) if part)
    if not name:
        name = str(metadata.get("player_name") or pick.get("player_id") or "Unknown")
    position = str(metadata.get("position") or "?").upper().replace("DEF", "DST")
    team = str(metadata.get("team") or "FA").upper()
    return f"{name} ({position}, {team})"


def _pick_notation(pick_number: int | None, teams: int) -> str:
    if pick_number is None:
        return "complete"
    if teams <= 0:
        return f"overall {pick_number}"
    round_number = ((pick_number - 1) // teams) + 1
    within_round = ((pick_number - 1) % teams) + 1
    return f"{round_number}.{within_round:02d} (overall {pick_number})"


def _display_number(value: Any, digits: int = 1) -> str:
    if value is None:
        return "-"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if number == 999.0:
        return "-"
    return f"{number:.{digits}f}"


_ANSI_RED = "\033[31m"
_ANSI_GREEN = "\033[32m"
_ANSI_RESET = "\033[0m"


def _color_text(text: str, color: str, enabled: bool) -> str:
    return f"{color}{text}{_ANSI_RESET}" if enabled else text


def _construction_flags(
    row: Mapping[str, Any],
    current_pick: int | None,
    teams: int,
    one_qb: bool = True,
) -> tuple[str, ...]:
    """Return compact construction and strategy flags for the lead row."""

    position = str(row.get("position") or "").upper().replace("DEF", "DST")
    flags = []
    if row.get("sequence_option_promoted"):
        flags.append("ELITE TE OPTION")
    try:
        position_rank = float(row.get("position_expert_rank"))
    except (TypeError, ValueError):
        return tuple(flags)
    current_round = (
        ((int(current_pick) - 1) // teams) + 1
        if current_pick is not None and teams > 0
        else None
    )
    if position == "RB" and 12.0 < position_rank <= 30.0:
        flags.append("RB13-30")
    if current_round is not None and current_round <= 8:
        if position == "QB" and one_qb:
            flags.append("EARLY QB")
        if position == "TE" and position_rank > 2.0:
            flags.append("NON-ELITE TE")
    return tuple(flags)


def _expert_disagreement_warning(row: Mapping[str, Any]) -> str | None:
    """Return a display-only warning for unusually dispersed overall ballots."""

    try:
        standard_deviation = float(row.get("overall_rank_stddev"))
        overall_rank = float(row.get("overall_expert_rank"))
        minimum_rank = float(row.get("overall_rank_min"))
        maximum_rank = float(row.get("overall_rank_max"))
        expert_count = int(row.get("overall_rank_experts"))
        weight_coverage = float(row.get("overall_rank_weight_coverage"))
    except (TypeError, ValueError):
        return None
    if overall_rank <= 0.0:
        return None
    if standard_deviation < EXPERT_DISAGREEMENT_SD_THRESHOLD:
        return None
    if standard_deviation / overall_rank < EXPERT_DISAGREEMENT_RELATIVE_THRESHOLD:
        return None
    if expert_count < EXPERT_DISAGREEMENT_MIN_EXPERTS:
        return None
    if weight_coverage < EXPERT_DISAGREEMENT_MIN_WEIGHT_COVERAGE:
        return None
    rank_range = f"{minimum_rank:g}-{maximum_rank:g}"
    return (
        f"HIGH EXPERT DISAGREEMENT: {row.get('player_name') or 'Unknown'} | "
        f"Ovr SD {standard_deviation:.1f} | ranks {rank_range} | "
        f"{expert_count} experts"
    )


def _format_recommendation_rows(
    rows: Iterable[Mapping[str, Any]],
    *,
    overlay: Mapping[str, Any] | None = None,
    current_pick: int | None = None,
    teams: int = 0,
    one_qb: bool = True,
    color: bool = False,
    acquisition_mode: str = "human_league",
) -> list[str]:
    acquisition_pick_label = (
        "CPU Pick" if acquisition_mode == "sleeper_cpu" else "Lg Pick"
    )
    acquisition_survival_label = (
        "CPU Surv%" if acquisition_mode == "sleeper_cpu" else "Lg Surv%"
    )
    columns = (
        ("#", 2, ">"),
        ("Player", 23, "<"),
        ("Pos", 4, "<"),
        ("Score", 7, ">"),
        ("OvrRk", 6, ">"),
        ("PosRk", 6, ">"),
        ("Market ADP", 10, ">"),
        (acquisition_pick_label, 8, ">"),
        ("Market Surv%", 12, ">"),
        (acquisition_survival_label, 9, ">"),
        ("VONA", 6, ">"),
    )
    lines = [
        "  " + " ".join(f"{label:{alignment}{width}}" for label, width, alignment in columns)
    ]
    preference_overlay = overlay or {}
    target_keys = {
        str(row.get("player_key") or "")
        for row in preference_overlay.get("targets") or []
    }
    caution_keys = {
        str(row.get("player_key") or "")
        for row in (
            preference_overlay.get("table_cautions")
            or preference_overlay.get("cautions")
            or []
        )
    }
    for index, row in enumerate(rows, start=1):
        player = str(row.get("player_name") or "Unknown")[:23]
        position = str(row.get("position") or "?")[:4]
        market_survival = row.get("market_survival")
        league_survival = row.get("league_survival")
        market_survival_text = (
            f"{100 * float(market_survival):5.1f}%"
            if market_survival is not None
            else "     -"
        )
        league_survival_text = (
            f"{100 * float(league_survival):5.1f}%"
            if league_survival is not None
            else "     -"
        )
        player_text = f"{player:<23}"
        player_key = str(row.get("player_key") or "")
        if player_key in caution_keys:
            player_text = _color_text(player_text, _ANSI_RED, color)
        elif player_key in target_keys:
            player_text = _color_text(player_text, _ANSI_GREEN, color)
        position_rank_text = f"{_display_number(row.get('position_expert_rank')):>6}"
        if _construction_flags(row, current_pick, teams, one_qb):
            position_rank_text = _color_text(position_rank_text, _ANSI_RED, color)
        lines.append(
            f"  {index:>2} {player_text} {position:<4} "
            f"{_display_number(row.get('final_score')):>7} "
            f"{_display_number(row.get('overall_expert_rank')):>6} "
            f"{position_rank_text} "
            f"{_display_number(row.get('market_adp', row.get('adp'))):>10} "
            f"{_display_number(row.get('league_expected_pick', row.get('acquisition_adp'))):>8} "
            f"{market_survival_text:>12} "
            f"{league_survival_text:>9} "
            f"{_display_number(row.get('vona')):>6}"
        )
        expected_next = row.get("expected_next_path_player")
        if row.get("starter_deferred") and expected_next:
            effect = _display_number(row.get("starter_deferral_effect"))
            lines.append(f"     Defers starter; expects {expected_next} next (effect {effect})")
    return lines


def _format_preference_overlay(
    overlay: Mapping[str, Any],
    acquisition_mode: str = "human_league",
    color: bool = False,
) -> list[str]:
    targets = list(overlay.get("display_targets") or [])
    cautions = list(overlay.get("cautions") or [])
    if not targets and not cautions:
        return []
    lines = ["UPSIDE TARGETS"]
    if targets:
        timing_label = (
            "CPU Surv%" if acquisition_mode == "sleeper_cpu" else "Lg Surv%"
        )
        lines.append(
            f"  Player                  Pos  Call   Market Surv%  {timing_label:<9}  Note"
        )
        for row in targets:
            player = str(row.get("player_name") or "Unknown")[:23]
            position = str(row.get("position") or "?")[:4]
            call = str(row.get("call") or "?")[:5]
            player_text = f"{player:<23}"
            if call == "NOW":
                player_text = _color_text(player_text, _ANSI_GREEN, color)
            market = 100.0 * float(row.get("market_survival") or 0.0)
            league = 100.0 * float(row.get("league_survival") or 0.0)
            note = str(row.get("note") or "")
            lines.append(
                f"  {player_text} {position:<4} {call:<5} "
                f"{market:11.1f}% {league:8.1f}%  {note}"
            )
    for row in cautions:
        lines.append(
            _color_text(
                f"  ! PRICE CAUTION: {row.get('player_name')} - {row.get('reason')}",
                _ANSI_RED,
                color,
            )
        )
    return lines


def format_mock_report(report: Mapping[str, Any], *, color: bool = False) -> str:
    """Render a poll report for fast reading during a live mock draft."""

    teams = len(report.get("rosters") or {})
    current_pick = report.get("current_pick")
    next_user_pick = report.get("next_user_pick")
    is_user_turn = bool(report.get("is_user_turn"))
    turn_label = "YOU ARE ON THE CLOCK" if is_user_turn else "WAITING"
    if str(report.get("status") or "").lower() == "complete":
        turn_label = "DRAFT COMPLETE"

    lines = [
        "=" * 108,
        "ROSTER THEORY - READ ONLY",
        (
            f"Draft {report.get('draft_id')} | {str(report.get('scoring') or '?').upper()} "
            f"| Slot {report.get('draft_slot')} | {str(report.get('status') or '?').upper()}"
        ),
        (
            f"{turn_label} | Current {_pick_notation(current_pick, teams)} "
            f"| Your next {_pick_notation(next_user_pick, teams)}"
        ),
        (
            f"State {str(report.get('transition') or '?').upper()} | "
            f"poll {_display_number(report.get('poll_latency_ms'))} ms | "
            f"recommendation {_display_number(report.get('recommendation_latency_ms'))} ms | "
            f"age {_display_number(report.get('state_age_seconds'))} s"
        ),
    ]

    warnings = list(report.get("warnings") or [])
    if warnings:
        lines.append(_color_text("WARNINGS", _ANSI_RED, color))
        lines.extend(
            _color_text(f"  ! {warning}", _ANSI_RED, color)
            for warning in warnings
        )

    draft_slot = report.get("draft_slot")
    rosters = report.get("rosters") or {}
    user_roster = list(rosters.get(draft_slot) or rosters.get(str(draft_slot)) or [])
    lines.append(f"YOUR ROSTER ({len(user_roster)})")
    if user_roster:
        by_position: dict[str, list[str]] = {}
        for pick in user_roster:
            metadata = pick.get("metadata") or {}
            position = str(metadata.get("position") or "?").upper().replace("DEF", "DST")
            label = _pick_player_label(pick).split(" (", 1)[0]
            by_position.setdefault(position, []).append(label)
        position_order = ("QB", "RB", "WR", "TE", "K", "DST")
        ordered_positions = [position for position in position_order if position in by_position]
        ordered_positions.extend(
            sorted(position for position in by_position if position not in position_order)
        )
        for position in ordered_positions:
            lines.append(f"  {position:<3} " + ", ".join(by_position[position]))
    else:
        lines.append("  No selections yet")

    recommendation = report.get("recommendation") or {}
    policies = list(recommendation.get("policies") or [])
    recommendations = recommendation.get("recommendations") or {}
    explanations = recommendation.get("explanations") or {}
    if is_user_turn and policies:
        lines.append("RECOMMENDATIONS")
        if recommendation.get("model_split"):
            lines.append(_color_text("  ! MODEL SPLIT", _ANSI_RED, color))
        if recommendation.get("room_timing_split"):
            lines.append(_color_text("  ! ROOM TIMING SPLIT", _ANSI_RED, color))
        acquisition = recommendation.get("acquisition_adp") or {}
        acquisition_mode = str(acquisition.get("mode") or "human_league")
        fallback = acquisition.get("fallback_state") or "historical slot curve applied"
        weight = acquisition.get("history_weight")
        draft_count = int(acquisition.get("draft_count") or 0)
        draft_label = "draft" if draft_count == 1 else "drafts"
        if acquisition_mode == "sleeper_cpu":
            captured = acquisition.get("snapshot_captured_at")
            try:
                captured_label = time.strftime(
                    "%Y-%m-%d", time.gmtime(float(captured))
                )
            except (TypeError, ValueError, OverflowError):
                captured_label = str(captured) if captured is not None else None
            coverage = float(acquisition.get("coverage") or 0.0)
            model_label = (
                f"SLEEPER CPU MOCK | {coverage:.1%} board coverage"
                + (f" | snapshot {captured_label}" if captured_label else "")
            )
        else:
            model_label = (
                f"{100 * float(weight):.0f}% league history | {draft_count} {draft_label}"
                if weight is not None and acquisition.get("history_available")
                else f"market only | {fallback}"
            )
        lines.append(f"  Acquisition: {model_label}")
        pace = (
            ((recommendation.get("room_survival") or {}).get("league") or {})
            .get("position_pace")
            or {}
        )
        material_pace = []
        for position in SKILL_POSITIONS:
            multiplier = float((pace.get(position) or {}).get("multiplier") or 1.0)
            if abs(multiplier - 1.0) >= 0.08:
                material_pace.append(f"{position} {(multiplier - 1.0):+.0%}")
        if material_pace:
            lines.append("  Room pace: " + " | ".join(material_pace))
        overlay = recommendation.get("preference_overlay") or {}
        construction_context = recommendation.get("construction_context") or {}
        one_qb = bool(construction_context.get("one_qb", True))
        if overlay.get("active"):
            lines.extend(
                _format_preference_overlay(
                    overlay,
                    acquisition_mode,
                    color=color,
                )
            )
        signal = recommendation.get("decision_signal") or {}
        if signal.get("kind") == "wait_on_qb":
            lines.append(
                _color_text(
                    "  DECISION: "
                    f"{signal.get('player_name')}; wait on {signal.get('qb_name')} "
                    f"({100 * float(signal.get('qb_survival') or 0.0):.1f}% to "
                    f"{_pick_notation(signal.get('continuation_pick'), teams).split(' (', 1)[0]}, "
                    "turn-package gap "
                    f"{float(signal.get('turn_package_gap') or 0.0):.3g})",
                    _ANSI_GREEN,
                    color,
                )
            )
        elif signal.get("kind") == "consider_sean_now":
            lines.append(
                _color_text(
                    "  CONSIDER: "
                    f"{signal.get('player_name')} instead (Sean Koerner NOW; "
                    f"{_display_number(signal.get('primary_score_gap'))} behind primary)",
                    _ANSI_GREEN,
                    color,
                )
            )
        elif signal.get("kind") == "plan_changed":
            lines.append(
                _color_text(
                    "  PLAN CHANGED: "
                    f"{signal.get('player_name')} now leads planned "
                    f"{signal.get('planned_player_name')} by "
                    f"{_display_number(signal.get('score_gap'))}",
                    _ANSI_RED,
                    color,
                )
            )
        primary_rows = list(recommendations.get(policies[0]) or [])
        if primary_rows:
            for row in primary_rows:
                disagreement_warning = _expert_disagreement_warning(row)
                if disagreement_warning:
                    lines.append(
                        _color_text(
                            f"  ! {disagreement_warning}", _ANSI_RED, color
                        )
                    )
            strategy_flags = _construction_flags(
                primary_rows[0], current_pick, teams, one_qb
            )
            if strategy_flags:
                lines.append(
                    _color_text(
                        "  ! STRATEGY: " + " | ".join(strategy_flags),
                        _ANSI_RED,
                        color,
                    )
                )
        for index, policy in enumerate(policies):
            role = (
                "PRIMARY"
                if index == 0
                else "EXPERT-ORDERED VALUE-CURVE CHECK"
                if index == 1 and "expert_ordered_curve" in str(policy)
                else "ALTERNATIVE"
            )
            lines.append(f"{role} - {str(policy).replace('_', ' ')}")
            rows = list(recommendations.get(policy) or [])
            if rows:
                lines.extend(
                    _format_recommendation_rows(
                        rows,
                        overlay=overlay,
                        current_pick=current_pick,
                        teams=teams,
                        one_qb=one_qb,
                        color=color,
                        acquisition_mode=acquisition_mode,
                    )
                )
                explanation = explanations.get(policy)
                if explanation:
                    lines.append(f"  Why: {explanation}")
            else:
                lines.append("  No eligible recommendations")
    elif is_user_turn:
        lines.append("RECOMMENDATIONS")
        lines.append(f"  {recommendation.get('reason') or 'No recommendation available'}")
    elif current_pick is not None and next_user_pick is not None:
        picks_away = max(0, int(next_user_pick) - int(current_pick))
        lines.append(f"Waiting: {picks_away} pick{'s' if picks_away != 1 else ''} until your turn")

    lines.append("=" * 108)
    return "\n".join(lines)


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


@dataclass(slots=True)
class MockDraftWatcher:
    client: SleeperClient
    draft_reference: str
    board: list[dict[str, Any]]
    claimed_slot: int | None = None
    user_id: str | None = None
    recommendation_limit: int = 5
    poll_interval_seconds: float = 0.5
    scoring_override: str | None = None
    acquisition_history: HistoricalPositionCurves | None = None
    history_weight: float | None = None
    acquisition_mode: str = "human_league"
    sleeper_adp_snapshot: Mapping[str, Any] | None = None
    draft_preferences: DraftPreferenceBook | None = None
    preference_scoring_settings: Mapping[str, Any] = field(default_factory=dict)
    preference_display_limit: int = 3
    previous_state: MockDraftState | None = None
    last_change_at: float | None = None
    last_recommendation: dict[str, Any] | None = None
    planned_turn: dict[str, Any] | None = None
    draft_pick_cache_status_counts: dict[str, int] = field(default_factory=dict)
    draft_pick_cache_max_age_seconds: float = 0.0

    def poll_once(self, now: float | None = None) -> dict[str, Any]:
        started = time.perf_counter()
        draft_id = parse_draft_id(self.draft_reference)
        draft = self.client.draft(draft_id)
        picks = self.client.draft_picks(draft_id)
        pick_fetch = dict(self.client.last_get_metadata)
        cache_status = str(pick_fetch.get("cache_status") or "").upper()
        if cache_status:
            self.draft_pick_cache_status_counts[cache_status] = (
                self.draft_pick_cache_status_counts.get(cache_status, 0) + 1
            )
        cache_age = float(pick_fetch.get("cache_age_seconds") or 0.0)
        self.draft_pick_cache_max_age_seconds = max(
            self.draft_pick_cache_max_age_seconds, cache_age
        )
        fetched_at = time.time() if now is None else now
        slot = resolve_draft_slot(draft, self.claimed_slot, self.user_id)
        state = reconcile_draft_state(
            draft,
            picks,
            slot,
            self.previous_state,
            self.scoring_override,
        )
        if self.acquisition_mode == "sleeper_cpu":
            _validate_sleeper_cpu_snapshot(self.sleeper_adp_snapshot, state.scoring)
        if self.previous_state is None or state.transition != "duplicate":
            self.last_change_at = fetched_at
        missed_turn = False
        if self.previous_state and self.previous_state.is_user_turn:
            prior_pick = self.previous_state.current_pick
            if prior_pick is not None and state.current_pick != prior_pick:
                authoritative = next(
                    (pick for pick in state.picks if int(pick["pick_no"]) == prior_pick),
                    None,
                )
                missed_turn = authoritative is None or int(
                    authoritative.get("draft_slot") or 0
                ) != slot
        recommendation_started = time.perf_counter()
        recommendation_cached = bool(
            state.is_user_turn
            and state.transition == "duplicate"
            and self.last_recommendation is not None
        )
        if recommendation_cached:
            recommendation = self.last_recommendation
        elif state.is_user_turn:
            recommendation = recommend_for_state(
                state,
                draft,
                self.board,
                self.recommendation_limit,
                self.acquisition_history,
                self.history_weight,
                draft_preferences=self.draft_preferences,
                preference_scoring_settings=self.preference_scoring_settings,
                preference_display_limit=self.preference_display_limit,
                acquisition_mode=self.acquisition_mode,
                sleeper_adp_snapshot=self.sleeper_adp_snapshot,
                planned_turn=self.planned_turn,
            )
            self.last_recommendation = recommendation
            turn_horizon = recommendation.get("turn_horizon") or {}
            new_plan = turn_horizon.get("planned_turn")
            if new_plan:
                self.planned_turn = dict(new_plan)
            elif (
                self.planned_turn
                and state.current_pick is not None
                and int(state.current_pick)
                >= int(self.planned_turn.get("second_pick") or 0)
            ):
                self.planned_turn = None
        else:
            recommendation = None
            self.last_recommendation = None
            if (
                self.planned_turn
                and state.current_pick is not None
                and int(state.current_pick)
                > int(self.planned_turn.get("second_pick") or 0)
            ):
                self.planned_turn = None
        recommendation_ms = (time.perf_counter() - recommendation_started) * 1000.0
        poll_ms = (time.perf_counter() - started) * 1000.0
        state_age = max(0.0, fetched_at - (self.last_change_at or fetched_at))
        pick_timer = int((draft.get("settings") or {}).get("pick_timer") or 0)
        stale = bool(
            state.status == "drafting"
            and pick_timer > 0
            and state_age > max(10.0, float(pick_timer))
        )
        clock_risk = bool(
            state.is_user_turn
            and pick_timer > 0
            and (
                poll_ms / 1000.0 > max(1.0, pick_timer * 0.35)
                or 2.0 * self.poll_interval_seconds + recommendation_ms / 1000.0
                >= pick_timer * 0.5
            )
        )
        warnings = list(state.warnings)
        if self.acquisition_mode == "sleeper_cpu":
            warnings.append(
                "CPU MOCK MODE: Sleeper timing only; values unchanged"
            )
        if stale:
            warnings.append("draft state is stale relative to the configured pick clock")
        if clock_risk:
            warnings.append("poll and recommendation latency consume too much of the pick clock")
        if cache_status == "HIT" or cache_age > 0.0:
            warnings.append(
                "draft-picks cache bypass returned "
                f"{cache_status or 'unknown status'} at age {cache_age:.0f}s"
            )
        if missed_turn:
            warnings.append("the draft advanced past a detected user turn without a matching slot pick")
        self.previous_state = state
        return {
            "draft_id": state.draft_id,
            "status": state.status,
            "teams": state.teams,
            "rounds": state.rounds,
            "pick_timer_seconds": pick_timer,
            "authoritative_pick_count": len(state.picks),
            "scoring": state.scoring,
            "draft_reported_scoring": scoring_family(draft),
            "draft_slot": state.draft_slot,
            "current_pick": state.current_pick,
            "next_user_pick": state.next_user_pick,
            "is_user_turn": state.is_user_turn,
            "transition": state.transition,
            "newly_drafted": state.newly_drafted,
            "removed_pick_numbers": state.removed_pick_numbers,
            "edited_pick_numbers": state.edited_pick_numbers,
            "rosters": state.rosters,
            "recommendation": recommendation,
            "poll_latency_ms": round(poll_ms, 2),
            "draft_picks_fetch": {
                **pick_fetch,
                "status_counts": dict(sorted(self.draft_pick_cache_status_counts.items())),
                "max_cache_age_seconds": round(
                    self.draft_pick_cache_max_age_seconds, 3
                ),
            },
            "recommendation_latency_ms": round(recommendation_ms, 2),
            "recommendation_cached": recommendation_cached,
            "state_age_seconds": round(state_age, 2),
            "missed_turn": missed_turn,
            "stale": stale,
            "clock_risk": clock_risk,
            "warnings": warnings,
            "read_only": True,
        }
