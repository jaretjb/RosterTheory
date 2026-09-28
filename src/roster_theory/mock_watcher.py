"""Compatibility imports for Draft watcher decisions, polling and formatting."""

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


from roster_theory.application.draft_watcher import MockDraftWatcher
from roster_theory.presentation.draft_watcher import (
    EXPERT_DISAGREEMENT_SD_THRESHOLD,
    EXPERT_DISAGREEMENT_RELATIVE_THRESHOLD,
    EXPERT_DISAGREEMENT_MIN_EXPERTS,
    EXPERT_DISAGREEMENT_MIN_WEIGHT_COVERAGE,
    _pick_player_label,
    _pick_notation,
    _display_number,
    _ANSI_RED,
    _ANSI_GREEN,
    _ANSI_RESET,
    _color_text,
    _construction_flags,
    _expert_disagreement_warning,
    _format_recommendation_rows,
    _format_preference_overlay,
    format_mock_report,
)
