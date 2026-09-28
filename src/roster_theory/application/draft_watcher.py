"""Read-only Sleeper polling and lifecycle for the Draft watcher."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Mapping

from roster_theory.core.errors import CoverageIncomplete
from roster_theory.draft.analysis import HistoricalPositionCurves
from roster_theory.draft_preferences import DraftPreferenceBook
from roster_theory.draft.watcher import (
    MockDraftState,
    _validate_sleeper_cpu_snapshot,
    parse_draft_id,
    recommend_for_state,
    reconcile_draft_state,
    resolve_draft_slot,
    scoring_family,
)
from roster_theory.providers.sleeper_draft_rules import draft_position_limit_advisory
from roster_theory.sleeper import SleeperClient


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
