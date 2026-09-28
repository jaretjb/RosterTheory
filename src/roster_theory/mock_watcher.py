"""Legacy Draft watcher imports, report rendering, and polling effects."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from roster_theory.core.errors import CoverageIncomplete
from roster_theory.draft.analysis import HistoricalPositionCurves
from roster_theory.draft_preferences import DraftPreferenceBook
from roster_theory.providers.sleeper_draft_rules import draft_position_limit_advisory
from roster_theory.sleeper import SleeperClient
from roster_theory.draft.watcher import (
    ACQUISITION_MODES,
    EXPERT_DISAGREEMENT_SD_THRESHOLD,
    EXPERT_DISAGREEMENT_RELATIVE_THRESHOLD,
    EXPERT_DISAGREEMENT_MIN_EXPERTS,
    EXPERT_DISAGREEMENT_MIN_WEIGHT_COVERAGE,
    rank_user_candidates,
    SKILL_POSITIONS,
    _validate_sleeper_cpu_snapshot,
    _apply_sleeper_cpu_adp,
    _human_acquisition_metadata,
    parse_draft_id,
    scoring_family,
    policy_pair_for_scoring,
    resolve_draft_slot,
    roster_positions_from_draft,
    _canonical_picks,
    _pick_identity,
    _transition,
    MockDraftState,
    reconcile_draft_state,
    _pick_position,
    _drafted_probability_by,
    live_position_pace,
    _seat_position_factor,
    room_survival_probabilities,
    _picked_board_keys,
    _board_indexes,
    _validate_board_scoring,
    _pick_to_player,
    _explain_leader,
    _compact_decision_signal,
    _preserve_planned_turn,
    recommend_for_state,
)


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
    last_position_limit_evidence: tuple[tuple[str, str, tuple[str, ...]], ...] | None = None
    draft_pick_cache_status_counts: dict[str, int] = field(default_factory=dict)
    draft_pick_cache_max_age_seconds: float = 0.0

    def poll_once(self, now: float | None = None) -> dict[str, Any]:
        started = time.perf_counter()
        draft_id = parse_draft_id(self.draft_reference)
        draft = self.client.draft(draft_id, fresh=True)
        try:
            position_limits, position_warning = draft_position_limit_advisory(draft)
        except CoverageIncomplete:
            self.last_recommendation = None
            self.planned_turn = None
            self.last_position_limit_evidence = None
            raise
        position_evidence = tuple(
            (row.rule, row.classification, row.evidence) for row in position_limits.checks
        )
        if (self.last_position_limit_evidence is not None
                and self.last_position_limit_evidence != position_evidence):
            self.last_recommendation = None
            self.planned_turn = None
        self.last_position_limit_evidence = position_evidence
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
        if position_warning:
            warnings.append(position_warning)
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
        result = {
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
        if position_warning:
            result["position_limit_status"] = position_limits.status
        return result
