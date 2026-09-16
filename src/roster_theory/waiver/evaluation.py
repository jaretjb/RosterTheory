from __future__ import annotations

import json
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Mapping, Sequence

from roster_theory.core.errors import CoverageIncomplete, IdentityIncomplete, RosterIllegal
from roster_theory.core.models import Player, Projection
from roster_theory.core.provenance import stable_hash
from roster_theory.inseason.evaluation import (
    InSeasonContext,
    InSeasonWeek,
    KNOWN_INACTIVE,
    RiskImpact,
    TeamImpact,
    build_weekly_projection_matrix,
    depth_above_waiver,
    lineup,
    risk_impact,
    team_impact,
)
from roster_theory.providers.cache import atomic_write_json
from roster_theory.waiver.emergence import (
    EmergenceEvidence,
    emergence_evidence_from_json,
)
from roster_theory.waiver.emerging_value import (
    EmergingScenarioInput,
    EmergingUpsideValuation,
    build_emerging_scenario_input,
    evaluate_emerging_upside,
)
from roster_theory.waiver.snapshot import (
    ACQUIRABLE_STATES,
    AcquisitionState,
    WaiverSnapshot,
    assert_current,
    resolve_player_acquisition,
)
from roster_theory.waiver.ww_evidence import (
    WaiverWireEvidence,
    WaiverWireExpertRank,
    WaiverWirePlayerEvidence,
    waiver_wire_evidence_from_json,
)


COMPLETE_PROJECTION_COVERAGE = frozenset(
    {"complete", "verified_bye_zero", "known_inactive_zero"}
)
SKILL_POSITIONS = frozenset({"QB", "RB", "WR", "TE"})
SPECIAL_TEAM_POSITIONS = frozenset({"K", "DST"})
WAIVER_POSITIONS = ("QB", "RB", "WR", "TE", "K", "DST")


def _normalized_positions(player: Player) -> frozenset[str]:
    return frozenset("DST" if value.upper() == "DEF" else value.upper() for value in player.positions)


def _waiver_position(player: Player) -> str:
    matches = tuple(position for position in WAIVER_POSITIONS if position in _normalized_positions(player))
    if not matches:
        raise RosterIllegal(f"{player.name} has no supported Waiver position")
    return matches[0]


def projection_coverage_is_complete(status: str) -> bool:
    return status.casefold() in COMPLETE_PROJECTION_COVERAGE


def reconcile_current_week_inactive_omissions(
    snapshot: WaiverSnapshot, projections: Sequence[Projection]
) -> tuple[Projection, ...]:
    """Use fresh league-local Sleeper status only for this week's omitted zero."""
    players = {player.player_id: player for player in snapshot.players}
    current_week = snapshot.manifest.current_week
    reconciled: list[Projection] = []
    for row in projections:
        player = players.get(row.player_id)
        injury_status = str(player.injury_status or "").upper() if player else ""
        if (
            row.horizon == "WEEKLY"
            and row.week == current_week
            and row.coverage_status.casefold() == "source_omission_zero"
            and row.league_points == 0.0
            and not row.raw_stats
            and injury_status in KNOWN_INACTIVE
        ):
            row = replace(
                row,
                source=f"Sleeper {injury_status} status; FantasyPros current-week omission",
                coverage_status="known_inactive_zero",
            )
        reconciled.append(row)
    return tuple(reconciled)


@dataclass(frozen=True, slots=True)
class WaiverEvaluationOptions:
    playoff_weight: float = 1.0
    allow_partial_schedule: bool = False
    offense_downside_multiplier: float = 0.70
    offense_upside_multiplier: float = 1.20
    qb_streaming_stress_rank: int = 3
    starter_decision_margin: float = 1.5
    contingency_evidence_max_age_hours: float = 72.0


@dataclass(frozen=True, slots=True)
class PlayerValueInput:
    player_id: str
    selected_value: float
    market_value: float
    raw_projection: float
    current_week_position_rank: int | None = None
    rest_of_season_position_rank: int | None = None
    coverage_status: str = "complete"
    warnings: tuple[str, ...] = ()
    normalization_basis: str = "LEAGUE_POSITIONAL_VORP"
    long_term_value_horizon: str = "ROS"


@dataclass(frozen=True, slots=True)
class ContingencyScenarioInput:
    beneficiary_player_id: str
    unavailable_teammate_player_id: str
    relationship: str
    evidence_source: str
    evidence_captured_at: datetime
    relationship_status: str
    projections: tuple[Projection, ...]
    strongest_uncertainty: str


@dataclass(frozen=True, slots=True)
class WaiverEvaluationInputs:
    schema_version: int
    league_key: str
    captured_at: datetime
    availability_source: str
    availability_by_player: tuple[tuple[str, str], ...]
    drop_legality: tuple[tuple[str, bool | None], ...]
    weeks: tuple[InSeasonWeek, ...]
    projections: tuple[Projection, ...]
    values: tuple[PlayerValueInput, ...]
    news_fresh: tuple[tuple[str, bool], ...]
    contingencies: tuple[ContingencyScenarioInput, ...]
    waiver_wire_evidence: WaiverWireEvidence | None
    emergence_evidence: EmergenceEvidence | None
    input_hash: str


@dataclass(frozen=True, slots=True)
class OwnershipDelta:
    selected_add: float
    selected_drop: float
    selected_delta: float
    market_add: float
    market_drop: float
    market_delta: float
    raw_projection_add: float
    raw_projection_drop: float
    raw_projection_delta: float
    waiver_wire_market_add_rank: float | None
    waiver_wire_market_drop_rank: float | None
    waiver_wire_market_add_position_rank: float | None
    waiver_wire_market_drop_position_rank: float | None
    waiver_wire_selected_add_ranks: tuple[WaiverWireExpertRank, ...]
    waiver_wire_selected_drop_ranks: tuple[WaiverWireExpertRank, ...]
    current_week_add_rank: int | None
    current_week_drop_rank: int | None
    rest_of_season_add_rank: int | None
    rest_of_season_drop_rank: int | None
    long_term_value_horizon_add: str
    long_term_value_horizon_drop: str | None
    fresh_rank_dominance: bool


def fresh_rank_dominates(
    add: PlayerValueInput,
    drop: PlayerValueInput | None,
    *,
    same_position: bool,
) -> bool:
    """Prove a narrow fresh-evidence override for a stale common value horizon."""
    if drop is None or not same_position:
        return False
    if (
        add.long_term_value_horizon != drop.long_term_value_horizon
        or add.long_term_value_horizon == "ROS"
    ):
        return False
    ranks = (
        add.current_week_position_rank,
        drop.current_week_position_rank,
        add.rest_of_season_position_rank,
        drop.rest_of_season_position_rank,
    )
    if any(rank is None for rank in ranks):
        return False
    return bool(
        add.current_week_position_rank < drop.current_week_position_rank
        and add.rest_of_season_position_rank < drop.rest_of_season_position_rank
        and round(add.raw_projection - drop.raw_projection, 3) >= 0
    )


@dataclass(frozen=True, slots=True)
class WaiverDecisionGate:
    name: str
    actual: float | bool
    comparison: str
    threshold: float | bool
    passed: bool
    explanation: str


@dataclass(frozen=True, slots=True)
class WaiverDecisionAssessment:
    label: str
    decision_path: str
    policy_version: str
    policy_hash: str
    calibration_mode: str
    priority_score: float
    elite_dst_exception: bool
    gates: tuple[WaiverDecisionGate, ...]
    reversal_conditions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DropExclusion:
    player_id: str
    reason: str


@dataclass(frozen=True, slots=True)
class WeeklyStreamingBaseline:
    week: int
    candidate_ids: tuple[str, ...]
    selected_player_id: str | None
    selected_points: float
    stress_rank: int


@dataclass(frozen=True, slots=True)
class QuarterbackHoldingEvidence:
    applicable: bool
    reason: str
    one_qb_format: bool
    cross_position_drop: bool
    streaming_candidate_ids: tuple[str, ...]
    streaming_omission_ids: tuple[str, ...]
    weekly_streaming_baselines: tuple[WeeklyStreamingBaseline, ...]
    streaming_replacement_value: float
    holding_period: int
    required_bye_weeks: tuple[int, ...]
    required_bye_coverage_value: float
    injury_insurance_value: float
    discretionary_start_weeks: tuple[int, ...]
    discretionary_start_value: float
    close_call_weeks: tuple[int, ...]
    unused_weeks: tuple[int, ...]
    starter_decision_margin: float
    bench_replacement_candidate_ids: tuple[str, ...]
    bench_slot_opportunity_cost: float
    net_hold_value: float


@dataclass(frozen=True, slots=True)
class WeeklyContingencyImpact:
    week: int
    weight: float
    standalone_projection_points: float
    scenario_projection_points: float
    projection_delta: float
    standalone_lineup_points: float
    scenario_lineup_points: float
    lineup_delta: float
    standalone_starters: tuple[str, ...]
    scenario_starters: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PlayerContingencyEvidence:
    player_id: str
    evidence_status: str
    current_authoritative: bool
    unavailable_teammate_player_id: str | None
    relationship: str | None
    evidence_source: str | None
    evidence_captured_at: datetime | None
    role_expansion_weighted_points: float
    standalone_weighted_lineup_points: float
    scenario_weighted_lineup_points: float
    lineup_ceiling_gain: float
    standalone_depth_above_waiver: float
    scenario_depth_above_waiver: float
    depth_delta: float
    replacement_exposure: float
    weekly_impacts: tuple[WeeklyContingencyImpact, ...]
    strongest_uncertainty: str


@dataclass(frozen=True, slots=True)
class ContingentUpsideEvidence:
    add: PlayerContingencyEvidence
    drop: PlayerContingencyEvidence | None
    retained_option_ceiling: float
    acquisition_option_ceiling: float
    incremental_option_value: float
    add_protected: bool
    drop_protected: bool
    required_incremental_value: float
    incremental_gate_passed: bool
    protection_reason: str
    strongest_uncertainty: str


@dataclass(frozen=True, slots=True)
class SkillPlayerDecisionEvidence:
    schema_version: int
    applicable: bool
    ownership_normalization_basis_add: str
    ownership_normalization_basis_drop: str | None
    selected_ownership_add: float
    selected_ownership_drop: float
    selected_ownership_delta: float
    market_ownership_add: float
    market_ownership_drop: float
    market_ownership_delta: float
    holding_method: str
    holding_cost: float
    streaming_baseline: float
    credited_starter_weeks: tuple[int, ...]
    standalone_weighted_lineup_delta: float
    contingency_scenarios: tuple[PlayerContingencyEvidence, ...]


@dataclass(frozen=True, slots=True)
class DropCandidateEvaluation:
    drop_player_id: str | None
    ownership: OwnershipDelta
    lineup: TeamImpact
    risk: RiskImpact
    added_start_weeks: tuple[int, ...]
    added_bye_weeks: tuple[int, ...]
    dropped_bye_weeks: tuple[int, ...]
    current_week_delta: float
    holding: QuarterbackHoldingEvidence
    contingency: ContingentUpsideEvidence
    emerging_upside: EmergingUpsideValuation
    skill_player: SkillPlayerDecisionEvidence
    current_week_add_points: float
    current_week_drop_points: float | None


@dataclass(frozen=True, slots=True)
class WaiverEvaluation:
    schema_version: int
    product: str
    operation: str
    league_key: str
    manifest_id: str
    evaluated_at: datetime
    current_week: int
    horizon: tuple[int, ...]
    add_player_id: str
    add_position: str
    acquisition_state: str
    selected_drop_player_id: str | None
    selection_basis: str
    candidates: tuple[DropCandidateEvaluation, ...]
    next_best_drop_player_ids: tuple[str, ...]
    exclusions: tuple[DropExclusion, ...]
    user_waiver_position: int | None
    user_waiver_budget_used: int | None
    user_waiver_budget_total: int | None
    candidate_hash: str
    value_input_hash: str
    input_bundle_hash: str | None
    availability_source: str | None
    waiver_wire_evidence: WaiverWireEvidence | None
    emergence_evidence: EmergenceEvidence | None
    material_news_fresh: bool
    add_currently_active: bool
    value_inputs_complete: bool
    projection_inputs_complete: bool
    policy_version: str | None
    policy_hash: str | None
    decision: WaiverDecisionAssessment | None
    strongest_uncertainty: str
    warnings: tuple[str, ...]
    decision_label: str | None
    recommendation_generated: bool
    sleeper_write_performed: bool
    evidence_hash: str


def _resolve_player(snapshot: WaiverSnapshot, name: str) -> Player:
    normalized = name.strip().casefold()
    matches = tuple(player for player in snapshot.players if player.name.casefold() == normalized)
    if not matches:
        raise IdentityIncomplete(f"Waiver player did not resolve exactly: {name}")
    if len(matches) != 1:
        raise IdentityIncomplete(f"Waiver player is ambiguous: {name}")
    return matches[0]


def _ownership_delta(
    add_id: str,
    drop_id: str | None,
    values: Mapping[str, PlayerValueInput],
    waiver_wire: Mapping[str, WaiverWirePlayerEvidence],
    *,
    same_position: bool,
) -> OwnershipDelta:
    required = {add_id}
    if drop_id is not None:
        required.add(drop_id)
    missing = sorted(required - set(values))
    if missing:
        raise CoverageIncomplete("Value inputs miss evaluated player(s): " + ", ".join(missing))
    add = values[add_id]
    drop = values.get(drop_id) if drop_id is not None else None
    add_waiver = waiver_wire.get(add_id)
    drop_waiver = waiver_wire.get(drop_id) if drop_id is not None else None

    def delta(add_value: float, drop_value: float) -> float:
        result = round(float(add_value) - float(drop_value), 3)
        return 0.0 if result == 0.0 else result

    return OwnershipDelta(
        selected_add=float(add.selected_value),
        selected_drop=float(drop.selected_value) if drop else 0.0,
        selected_delta=delta(add.selected_value, drop.selected_value if drop else 0.0),
        market_add=float(add.market_value),
        market_drop=float(drop.market_value) if drop else 0.0,
        market_delta=delta(add.market_value, drop.market_value if drop else 0.0),
        raw_projection_add=float(add.raw_projection),
        raw_projection_drop=float(drop.raw_projection) if drop else 0.0,
        raw_projection_delta=delta(
            add.raw_projection, drop.raw_projection if drop else 0.0
        ),
        waiver_wire_market_add_rank=(
            add_waiver.market_overall_rank if add_waiver else None
        ),
        waiver_wire_market_drop_rank=(
            drop_waiver.market_overall_rank if drop_waiver else None
        ),
        waiver_wire_market_add_position_rank=(
            add_waiver.market_position_rank if add_waiver else None
        ),
        waiver_wire_market_drop_position_rank=(
            drop_waiver.market_position_rank if drop_waiver else None
        ),
        waiver_wire_selected_add_ranks=(
            add_waiver.selected_expert_ranks if add_waiver else ()
        ),
        waiver_wire_selected_drop_ranks=(
            drop_waiver.selected_expert_ranks if drop_waiver else ()
        ),
        current_week_add_rank=add.current_week_position_rank,
        current_week_drop_rank=drop.current_week_position_rank if drop else None,
        rest_of_season_add_rank=add.rest_of_season_position_rank,
        rest_of_season_drop_rank=(
            drop.rest_of_season_position_rank if drop else None
        ),
        long_term_value_horizon_add=add.long_term_value_horizon,
        long_term_value_horizon_drop=(drop.long_term_value_horizon if drop else None),
        fresh_rank_dominance=fresh_rank_dominates(
            add,
            drop,
            same_position=same_position,
        ),
    )


def _validate_inputs(
    snapshot: WaiverSnapshot,
    weeks: Sequence[InSeasonWeek],
    projections: Sequence[Projection],
    values: Sequence[PlayerValueInput],
    options: WaiverEvaluationOptions,
) -> tuple[dict[str, PlayerValueInput], InSeasonContext]:
    if options.playoff_weight <= 0:
        raise ValueError("playoff_weight must be positive")
    if not 0 <= options.offense_downside_multiplier < 1:
        raise ValueError("offense_downside_multiplier must be at least 0 and below 1")
    if options.offense_upside_multiplier <= 1:
        raise ValueError("offense_upside_multiplier must be above 1")
    if (
        isinstance(options.qb_streaming_stress_rank, bool)
        or options.qb_streaming_stress_rank < 1
    ):
        raise ValueError("qb_streaming_stress_rank must be a positive integer")
    if options.starter_decision_margin < 0:
        raise ValueError("starter_decision_margin must be nonnegative")
    if options.contingency_evidence_max_age_hours <= 0:
        raise ValueError("contingency_evidence_max_age_hours must be positive")
    ordered_weeks = tuple(sorted(weeks, key=lambda row: row.week))
    current_week = snapshot.manifest.current_week
    if not ordered_weeks or ordered_weeks[0].week != current_week:
        raise CoverageIncomplete("Evaluation weeks must begin at the snapshot current week")
    if tuple(row.week for row in ordered_weeks) != tuple(
        range(current_week, ordered_weeks[-1].week + 1)
    ):
        raise CoverageIncomplete("Evaluation weeks must be continuous")
    value_map = {row.player_id: row for row in values}
    if len(value_map) != len(values):
        raise CoverageIncomplete("Value inputs contain duplicate player IDs")
    missing_normalization = tuple(
        sorted(
            row.player_id for row in values if not row.normalization_basis.strip()
        )
    )
    if missing_normalization:
        raise CoverageIncomplete(
            "Ownership values miss normalization basis: "
            + ", ".join(missing_normalization)
        )
    projected_ids = {row.player_id for row in projections if row.horizon == "WEEKLY"}
    relevant_ids = set(value_map) | projected_ids | set(dict(snapshot.owner_by_player))
    players = tuple(player for player in snapshot.players if player.player_id in relevant_ids)
    context = InSeasonContext(
        players=players,
        roster_positions=snapshot.league.roster_positions,
        weeks=ordered_weeks,
        unowned_player_ids=tuple(
            sorted(player.player_id for player in players if player.player_id not in dict(snapshot.owner_by_player))
        ),
        evaluation_positions=WAIVER_POSITIONS,
        current_status_week_only=True,
    )
    return value_map, context


def _unavailable_contingency_evidence(
    player_id: str,
    *,
    status: str,
    uncertainty: str,
    scenario: ContingencyScenarioInput | None = None,
) -> PlayerContingencyEvidence:
    return PlayerContingencyEvidence(
        player_id=player_id,
        evidence_status=status,
        current_authoritative=False,
        unavailable_teammate_player_id=(
            scenario.unavailable_teammate_player_id if scenario else None
        ),
        relationship=scenario.relationship if scenario else None,
        evidence_source=scenario.evidence_source if scenario else None,
        evidence_captured_at=scenario.evidence_captured_at if scenario else None,
        role_expansion_weighted_points=0.0,
        standalone_weighted_lineup_points=0.0,
        scenario_weighted_lineup_points=0.0,
        lineup_ceiling_gain=0.0,
        standalone_depth_above_waiver=0.0,
        scenario_depth_above_waiver=0.0,
        depth_delta=0.0,
        replacement_exposure=0.0,
        weekly_impacts=(),
        strongest_uncertainty=uncertainty,
    )


def _player_contingency_evidence(
    *,
    player_id: str,
    roster: set[str],
    scenarios: Sequence[ContingencyScenarioInput],
    snapshot: WaiverSnapshot,
    context: InSeasonContext,
    central_matrix: object,
    projections: Sequence[Projection],
    options: WaiverEvaluationOptions,
    now: datetime,
) -> PlayerContingencyEvidence:
    matches = tuple(row for row in scenarios if row.beneficiary_player_id == player_id)
    if not matches:
        return _unavailable_contingency_evidence(
            player_id,
            status="NOT_PROVIDED",
            uncertainty="No contingency relationship was provided for this player",
        )
    if len(matches) != 1:
        return _unavailable_contingency_evidence(
            player_id,
            status="AMBIGUOUS",
            uncertainty=(
                "Multiple contingency relationships were supplied; committee role expansion "
                "cannot be attributed to one unavailable teammate"
            ),
        )
    scenario = matches[0]
    declared_status = scenario.relationship_status.strip().upper()
    if declared_status != "CURRENT_AUTHORITATIVE":
        status = declared_status if declared_status in {"MISSING", "AMBIGUOUS", "STALE"} else "INVALID"
        return _unavailable_contingency_evidence(
            player_id,
            status=status,
            uncertainty=scenario.strongest_uncertainty,
            scenario=scenario,
        )
    if scenario.evidence_captured_at.tzinfo is None:
        return _unavailable_contingency_evidence(
            player_id,
            status="STALE",
            uncertainty="Contingency role evidence has no timezone-aware timestamp",
            scenario=scenario,
        )
    if now - scenario.evidence_captured_at.astimezone(timezone.utc) > timedelta(
        hours=options.contingency_evidence_max_age_hours
    ):
        return _unavailable_contingency_evidence(
            player_id,
            status="STALE",
            uncertainty="Contingency role evidence exceeds the policy freshness window",
            scenario=scenario,
        )
    player_by_id = {row.player_id: row for row in snapshot.players}
    beneficiary = player_by_id.get(player_id)
    teammate = player_by_id.get(scenario.unavailable_teammate_player_id)
    if beneficiary is None or teammate is None:
        return _unavailable_contingency_evidence(
            player_id,
            status="UNMATCHED",
            uncertainty="Contingency beneficiary or unavailable teammate did not resolve",
            scenario=scenario,
        )
    if (
        beneficiary.player_id == teammate.player_id
        or not beneficiary.nfl_team
        or beneficiary.nfl_team != teammate.nfl_team
    ):
        return _unavailable_contingency_evidence(
            player_id,
            status="TEAM_MISMATCH",
            uncertainty="Contingency relationship does not identify a distinct same-team teammate",
            scenario=scenario,
        )
    if not scenario.relationship.strip() or not scenario.evidence_source.strip():
        return _unavailable_contingency_evidence(
            player_id,
            status="MISSING",
            uncertainty="Contingency relationship lacks authoritative role provenance",
            scenario=scenario,
        )
    projection_by_week = {
        row.week: row
        for row in scenario.projections
        if row.player_id == player_id and row.horizon == "WEEKLY" and row.week is not None
    }
    required_weeks = tuple(row.week for row in context.weeks)
    complete = (
        len(projection_by_week) == len(scenario.projections) == len(required_weeks)
        and tuple(sorted(projection_by_week)) == required_weeks
        and all(
            projection_coverage_is_complete(row.coverage_status)
            and bool(row.source.strip())
            and row.league_points >= 0
            for row in projection_by_week.values()
        )
    )
    if not complete:
        return _unavailable_contingency_evidence(
            player_id,
            status="PARTIAL_PROJECTION",
            uncertainty="Contingency projections do not completely cover the evaluation horizon",
            scenario=scenario,
        )

    overrides = {
        (row.player_id, row.week): row
        for row in projections
        if row.horizon == "WEEKLY" and row.week is not None
    }
    for week, projection in projection_by_week.items():
        overrides[(player_id, week)] = projection
    for week in required_weeks:
        teammate_key = (teammate.player_id, week)
        if teammate_key in overrides:
            central = overrides[teammate_key]
            overrides[teammate_key] = replace(
                central,
                raw_stats=(),
                league_points=0.0,
                source=f"{scenario.evidence_source}; teammate unavailable",
                coverage_status="known_inactive_zero",
            )
    scenario_matrix = build_weekly_projection_matrix(context, tuple(overrides.values()))
    weekly: list[WeeklyContingencyImpact] = []
    role_expansion = 0.0
    standalone_total = 0.0
    scenario_total = 0.0
    for week in context.weeks:
        central_projection = central_matrix.cell(player_id, week.week)
        scenario_projection = scenario_matrix.cell(player_id, week.week)
        central_points = float(central_projection.points or 0.0)
        scenario_points = float(scenario_projection.points or 0.0)
        weight = options.playoff_weight if week.playoff else 1.0
        central_lineup = lineup(
            context,
            central_matrix,
            roster,
            week.week,
            allow_partial=options.allow_partial_schedule,
        )
        scenario_lineup = lineup(
            context,
            scenario_matrix,
            roster,
            week.week,
            allow_partial=options.allow_partial_schedule,
        )
        role_expansion += (scenario_points - central_points) * weight
        standalone_total += central_lineup.score * weight
        scenario_total += scenario_lineup.score * weight
        weekly.append(
            WeeklyContingencyImpact(
                week=week.week,
                weight=weight,
                standalone_projection_points=round(central_points, 3),
                scenario_projection_points=round(scenario_points, 3),
                projection_delta=round(scenario_points - central_points, 3),
                standalone_lineup_points=round(central_lineup.score, 3),
                scenario_lineup_points=round(scenario_lineup.score, 3),
                lineup_delta=round(scenario_lineup.score - central_lineup.score, 3),
                standalone_starters=tuple(
                    sorted(row.player_id for row in central_lineup.assignments)
                ),
                scenario_starters=tuple(
                    sorted(row.player_id for row in scenario_lineup.assignments)
                ),
            )
        )
    standalone_depth = depth_above_waiver(context, central_matrix, roster, options)
    scenario_depth = depth_above_waiver(context, scenario_matrix, roster, options)
    depth_delta = round(scenario_depth - standalone_depth, 3)
    return PlayerContingencyEvidence(
        player_id=player_id,
        evidence_status="CURRENT_AUTHORITATIVE",
        current_authoritative=True,
        unavailable_teammate_player_id=teammate.player_id,
        relationship=scenario.relationship,
        evidence_source=scenario.evidence_source,
        evidence_captured_at=scenario.evidence_captured_at.astimezone(timezone.utc),
        role_expansion_weighted_points=round(role_expansion, 3),
        standalone_weighted_lineup_points=round(standalone_total, 3),
        scenario_weighted_lineup_points=round(scenario_total, 3),
        lineup_ceiling_gain=round(scenario_total - standalone_total, 3),
        standalone_depth_above_waiver=standalone_depth,
        scenario_depth_above_waiver=scenario_depth,
        depth_delta=depth_delta,
        replacement_exposure=round(max(0.0, -depth_delta), 3),
        weekly_impacts=tuple(weekly),
        strongest_uncertainty=(
            scenario.strongest_uncertainty
            or "Teammate-unavailability probability is intentionally not estimated"
        ),
    )


def _cached_player_contingency_evidence(
    *,
    player_id: str,
    roster: set[str],
    scenarios: Sequence[ContingencyScenarioInput],
    snapshot: WaiverSnapshot,
    context: InSeasonContext,
    central_matrix: object,
    projections: Sequence[Projection],
    options: WaiverEvaluationOptions,
    now: datetime,
    cache: dict[
        tuple[str, frozenset[str]], PlayerContingencyEvidence
    ] | None,
) -> PlayerContingencyEvidence:
    key = (player_id, frozenset(roster))
    if cache is not None and key in cache:
        return cache[key]
    evidence = _player_contingency_evidence(
        player_id=player_id,
        roster=roster,
        scenarios=scenarios,
        snapshot=snapshot,
        context=context,
        central_matrix=central_matrix,
        projections=projections,
        options=options,
        now=now,
    )
    if cache is not None:
        cache[key] = evidence
    return evidence


def _one_qb_format(roster_positions: Sequence[str]) -> bool:
    normalized = tuple(position.upper() for position in roster_positions)
    return normalized.count("QB") == 1 and "SUPER_FLEX" not in normalized


def _not_applicable_qb_holding(
    *,
    reason: str,
    one_qb_format: bool,
    cross_position_drop: bool,
    options: WaiverEvaluationOptions,
) -> QuarterbackHoldingEvidence:
    return QuarterbackHoldingEvidence(
        applicable=False,
        reason=reason,
        one_qb_format=one_qb_format,
        cross_position_drop=cross_position_drop,
        streaming_candidate_ids=(),
        streaming_omission_ids=(),
        weekly_streaming_baselines=(),
        streaming_replacement_value=0.0,
        holding_period=0,
        required_bye_weeks=(),
        required_bye_coverage_value=0.0,
        injury_insurance_value=0.0,
        discretionary_start_weeks=(),
        discretionary_start_value=0.0,
        close_call_weeks=(),
        unused_weeks=(),
        starter_decision_margin=options.starter_decision_margin,
        bench_replacement_candidate_ids=(),
        bench_slot_opportunity_cost=0.0,
        net_hold_value=0.0,
    )


def _quarterback_holding_evidence(
    *,
    snapshot: WaiverSnapshot,
    add_player: Player,
    drop_id: str | None,
    supported_roster: set[str],
    player_by_id: Mapping[str, Player],
    value_map: Mapping[str, PlayerValueInput],
    context: InSeasonContext,
    matrix: object,
    projection_by_key: Mapping[tuple[str, int], Projection],
    lineup_impact: TeamImpact,
    options: WaiverEvaluationOptions,
) -> QuarterbackHoldingEvidence:
    one_qb = _one_qb_format(snapshot.league.roster_positions)
    drop_position = _waiver_position(player_by_id[drop_id]) if drop_id else None
    cross_position_drop = drop_position is not None and drop_position != "QB"
    if "QB" not in _normalized_positions(add_player):
        return _not_applicable_qb_holding(
            reason="ADD_IS_NOT_QB",
            one_qb_format=one_qb,
            cross_position_drop=cross_position_drop,
            options=options,
        )
    if not one_qb:
        return _not_applicable_qb_holding(
            reason="MULTI_QB_FORMAT",
            one_qb_format=False,
            cross_position_drop=cross_position_drop,
            options=options,
        )
    if drop_position == "QB":
        return _not_applicable_qb_holding(
            reason="SAME_POSITION_REPLACEMENT",
            one_qb_format=True,
            cross_position_drop=False,
            options=options,
        )

    roster_qb_ids = tuple(
        sorted(
            player_id
            for player_id in supported_roster
            if "QB" in _normalized_positions(player_by_id[player_id])
        )
    )
    current_row = next(
        row for row in lineup_impact.weeks if row.week == snapshot.manifest.current_week
    )
    current_qbs_on_bye = bool(roster_qb_ids) and all(
        (cell := matrix.cell(player_id, current_row.week)) is not None
        and cell.availability == "BYE"
        for player_id in roster_qb_ids
    )
    if add_player.player_id in current_row.after_starters and not current_qbs_on_bye:
        return _not_applicable_qb_holding(
            reason="CURRENT_STARTER_UPGRADE",
            one_qb_format=True,
            cross_position_drop=cross_position_drop,
            options=options,
        )

    acquisitions = {row.player_id: row.state for row in snapshot.acquisitions}
    unowned_qb_ids = tuple(
        sorted(
            player.player_id
            for player in snapshot.players
            if player.player_id != add_player.player_id
            and "QB" in _normalized_positions(player)
            and acquisitions.get(player.player_id) in ACQUIRABLE_STATES
        )
    )
    streamer_ids: list[str] = []
    omission_ids: list[str] = []
    for player_id in unowned_qb_ids:
        value = value_map.get(player_id)
        complete = value is not None and value.coverage_status.casefold() == "complete"
        for week in context.weeks:
            projection = projection_by_key.get((player_id, week.week))
            cell = matrix.cell(player_id, week.week)
            complete = complete and projection is not None and cell is not None and cell.points is not None
            if projection is not None:
                complete = complete and projection_coverage_is_complete(
                    projection.coverage_status
                )
        (streamer_ids if complete else omission_ids).append(player_id)

    weekly_baselines: list[WeeklyStreamingBaseline] = []
    baseline_by_week: dict[int, float] = {}
    for week in context.weeks:
        ranked = tuple(
            sorted(
                (
                    (float(matrix.cell(player_id, week.week).points), player_id)
                    for player_id in streamer_ids
                ),
                key=lambda row: (-row[0], row[1]),
            )
        )
        selected_index = min(options.qb_streaming_stress_rank, len(ranked)) - 1
        selected_player_id = ranked[selected_index][1] if ranked else None
        selected_points = ranked[selected_index][0] if ranked else 0.0
        baseline_by_week[week.week] = selected_points
        weekly_baselines.append(
            WeeklyStreamingBaseline(
                week=week.week,
                candidate_ids=tuple(player_id for _, player_id in ranked),
                selected_player_id=selected_player_id,
                selected_points=round(selected_points, 3),
                stress_rank=options.qb_streaming_stress_rank,
            )
        )

    required_bye_weeks: list[int] = []
    discretionary_start_weeks: list[int] = []
    close_call_weeks: list[int] = []
    required_value = 0.0
    discretionary_value = 0.0
    insurance_values: list[float] = []
    for row in lineup_impact.weeks:
        add_cell = matrix.cell(add_player.player_id, row.week)
        add_points = float(add_cell.points) if add_cell is not None and add_cell.points is not None else 0.0
        baseline_points = baseline_by_week[row.week]
        existing_qbs_on_bye = bool(roster_qb_ids) and all(
            (cell := matrix.cell(player_id, row.week)) is not None
            and cell.availability == "BYE"
            for player_id in roster_qb_ids
        )
        add_starts = add_player.player_id in row.after_starters
        before_qb_points = max(
            (
                float(cell.points)
                for player_id in row.before_starters
                if "QB" in _normalized_positions(player_by_id[player_id])
                and (cell := matrix.cell(player_id, row.week)) is not None
                and cell.points is not None
            ),
            default=0.0,
        )
        if add_starts and existing_qbs_on_bye:
            required_bye_weeks.append(row.week)
            required_value += (add_points - baseline_points) * row.weight
        elif add_starts:
            edge = add_points - before_qb_points
            if edge >= options.starter_decision_margin:
                discretionary_start_weeks.append(row.week)
                discretionary_value += (
                    edge - options.starter_decision_margin
                ) * row.weight
            elif edge > 0:
                close_call_weeks.append(row.week)
        insurance_values.append(max(0.0, add_points - baseline_points))

    credited_weeks = set(required_bye_weeks) | set(discretionary_start_weeks)
    ordered_week_numbers = tuple(week.week for week in context.weeks)
    if credited_weeks:
        last_credited_index = max(
            index
            for index, week in enumerate(ordered_week_numbers)
            if week in credited_weeks
        )
        held_weeks = ordered_week_numbers[: last_credited_index + 1]
    else:
        held_weeks = ordered_week_numbers
    unused_weeks = tuple(
        week for week in held_weeks if week not in credited_weeks
    )
    replacement_ids: tuple[str, ...] = ()
    bench_cost = 0.0
    if cross_position_drop and drop_id is not None:
        replacement_ids = tuple(
            sorted(
                player_id
                for player_id, value in value_map.items()
                if player_id not in {add_player.player_id, drop_id}
                and player_id in player_by_id
                and drop_position in _normalized_positions(player_by_id[player_id])
                and acquisitions.get(player_id) in ACQUIRABLE_STATES
                and value.coverage_status.casefold() == "complete"
            )
        )
        replacement_selected = max(
            (value_map[player_id].selected_value for player_id in replacement_ids),
            default=0.0,
        )
        replacement_market = max(
            (value_map[player_id].market_value for player_id in replacement_ids),
            default=0.0,
        )
        drop_value = value_map[drop_id]
        raw_bench_cost = max(
            0.0,
            drop_value.selected_value - replacement_selected,
            drop_value.market_value - replacement_market,
        )
        bench_cost = raw_bench_cost * (len(unused_weeks) / len(held_weeks))

    streaming_replacement_value = sum(
        baseline_by_week[week] * next(row.weight for row in lineup_impact.weeks if row.week == week)
        for week in required_bye_weeks
    )
    injury_insurance = (
        sum(insurance_values) / len(insurance_values) if insurance_values else 0.0
    )
    net_hold = required_value + discretionary_value - bench_cost
    return QuarterbackHoldingEvidence(
        applicable=True,
        reason="ONE_QB_BACKUP_HOLD",
        one_qb_format=True,
        cross_position_drop=cross_position_drop,
        streaming_candidate_ids=tuple(streamer_ids),
        streaming_omission_ids=tuple(omission_ids),
        weekly_streaming_baselines=tuple(weekly_baselines),
        streaming_replacement_value=round(streaming_replacement_value, 3),
        holding_period=len(held_weeks),
        required_bye_weeks=tuple(required_bye_weeks),
        required_bye_coverage_value=round(required_value, 3),
        injury_insurance_value=round(injury_insurance, 3),
        discretionary_start_weeks=tuple(discretionary_start_weeks),
        discretionary_start_value=round(discretionary_value, 3),
        close_call_weeks=tuple(close_call_weeks),
        unused_weeks=unused_weeks,
        starter_decision_margin=options.starter_decision_margin,
        bench_replacement_candidate_ids=replacement_ids,
        bench_slot_opportunity_cost=round(bench_cost, 3),
        net_hold_value=round(net_hold, 3),
    )


def evaluate_waiver(
    snapshot: WaiverSnapshot,
    *,
    add: str | None = None,
    add_player_id: str | None = None,
    weeks: Sequence[InSeasonWeek],
    projections: Sequence[Projection],
    values: Sequence[PlayerValueInput],
    drop_legality: Mapping[str, bool | None],
    drop: str | None = None,
    news_fresh: Mapping[str, bool] | None = None,
    contingencies: Sequence[ContingencyScenarioInput] = (),
    waiver_wire_evidence: WaiverWireEvidence | None = None,
    emergence_evidence: EmergenceEvidence | None = None,
    input_bundle_hash: str | None = None,
    availability_source: str | None = None,
    options: WaiverEvaluationOptions = WaiverEvaluationOptions(),
    now: datetime | None = None,
    contingency_cache: dict[
        tuple[str, frozenset[str]], PlayerContingencyEvidence
    ] | None = None,
) -> WaiverEvaluation:
    assert_current(snapshot, now=now)
    projections = reconcile_current_week_inactive_omissions(snapshot, projections)
    evaluation_time = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if (add is None) == (add_player_id is None):
        raise ValueError("Provide exactly one of add or add_player_id")
    if waiver_wire_evidence is not None:
        if waiver_wire_evidence.league_key != snapshot.league_key:
            raise CoverageIncomplete(
                "Waiver Wire evidence belongs to a different league"
            )
        expected_waiver_hash = stable_hash(
            asdict(replace(waiver_wire_evidence, evidence_hash=""))
        )
        if waiver_wire_evidence.evidence_hash != expected_waiver_hash:
            raise CoverageIncomplete("Waiver Wire evidence hash is invalid")
    if emergence_evidence is not None:
        if emergence_evidence.league_key != snapshot.league_key:
            raise CoverageIncomplete(
                "Emergence evidence belongs to a different league"
            )
        expected_emergence_hash = stable_hash(
            asdict(replace(emergence_evidence, evidence_hash=""))
        )
        if emergence_evidence.evidence_hash != expected_emergence_hash:
            raise CoverageIncomplete("Emergence evidence hash is invalid")
    waiver_wire_by_id = {
        row.player_id: row
        for row in (waiver_wire_evidence.players if waiver_wire_evidence else ())
        if row.match_status == "MATCHED"
    }
    if waiver_wire_evidence is not None and len(waiver_wire_by_id) != sum(
        row.match_status == "MATCHED" for row in waiver_wire_evidence.players
    ):
        raise CoverageIncomplete("Waiver Wire evidence has duplicate matched players")
    if add_player_id is not None:
        player_matches = tuple(
            player for player in snapshot.players if player.player_id == add_player_id
        )
        if len(player_matches) != 1:
            raise IdentityIncomplete(
                f"Waiver player ID did not resolve exactly: {add_player_id}"
            )
        add_player = player_matches[0]
        acquisition_matches = tuple(
            row for row in snapshot.acquisitions if row.player_id == add_player_id
        )
        if len(acquisition_matches) != 1:
            raise IdentityIncomplete(
                f"Waiver acquisition state did not resolve exactly: {add_player_id}"
            )
        acquisition = acquisition_matches[0]
        target_description = add_player.name
    else:
        assert add is not None
        acquisition = resolve_player_acquisition(snapshot, add)
        add_player = _resolve_player(snapshot, add)
        target_description = add
    if acquisition.state not in ACQUIRABLE_STATES:
        raise RosterIllegal(
            f"{target_description} acquisition state is {acquisition.state}; evaluation requires "
            "current non-ownership and supported-position eligibility"
        )
    add_position = _waiver_position(add_player)
    team = next(team for team in snapshot.teams if team.roster_id == snapshot.user_roster_id)
    capacity = next(
        row for row in snapshot.roster_capacity if row.roster_id == snapshot.user_roster_id
    )
    if not capacity.capacity_legal or not capacity.reserve_legality_known or not capacity.reserve_legal:
        raise RosterIllegal("Current roster capacity or reserve legality is incomplete")
    player_by_id = {player.player_id: player for player in snapshot.players}
    active_roster = set(team.player_ids) - set(team.reserve_ids)
    active_supported_roster = {
        player_id
        for player_id in active_roster
        if player_id in player_by_id
        and _normalized_positions(player_by_id[player_id]).intersection(WAIVER_POSITIONS)
    }
    add_drop_category = (
        frozenset({add_position})
        if add_position in SPECIAL_TEAM_POSITIONS
        else SKILL_POSITIONS
    )
    supported_roster = {
        player_id
        for player_id in active_supported_roster
        if _normalized_positions(player_by_id[player_id]).intersection(add_drop_category)
    }
    droppable_roster = set(supported_roster)
    exclusions: list[DropExclusion] = [
        DropExclusion(player_id, "RESERVE")
        for player_id in sorted(team.reserve_ids)
    ]
    exclusions.extend(
        DropExclusion(player_id, "OUT_OF_SCOPE_POSITION")
        for player_id in sorted(active_roster - active_supported_roster)
    )

    requested_drop_id: str | None = None
    if drop is not None:
        drop_player = _resolve_player(snapshot, drop)
        requested_drop_id = drop_player.player_id
        if requested_drop_id not in droppable_roster:
            category = add_position if add_position in SPECIAL_TEAM_POSITIONS else "skill-player"
            raise RosterIllegal(f"{drop} is not an active droppable {category} replacement")
        legality = drop_legality.get(requested_drop_id)
        if legality is not True:
            status = "locked" if legality is False else "unknown"
            raise RosterIllegal(f"{drop} drop legality is {status}")

    drop_ids: tuple[str | None, ...]
    if requested_drop_id is not None:
        drop_ids = (requested_drop_id,)
    elif capacity.open_active_slots > 0:
        drop_ids = (None,)
    else:
        unknown = tuple(
                sorted(player_id for player_id in droppable_roster if drop_legality.get(player_id) is None)
        )
        if unknown:
            coverage_description = (
                "every same-position special-team player"
                if add_position in SPECIAL_TEAM_POSITIONS
                else "every skill player"
            )
            raise RosterIllegal(
                "Automatic drop selection requires proved legality for "
                + coverage_description
                + ": "
                + ", ".join(unknown)
            )
        locked = tuple(
            sorted(player_id for player_id in droppable_roster if drop_legality[player_id] is False)
        )
        exclusions.extend(DropExclusion(player_id, "ROSTER_LOCKED") for player_id in locked)
        legal = tuple(
            sorted(player_id for player_id in droppable_roster if drop_legality[player_id] is True)
        )
        if not legal:
            raise RosterIllegal("No proved-legal same-category replacement is droppable")
        drop_ids = legal

    value_map, context = _validate_inputs(snapshot, weeks, projections, values, options)
    matrix = build_weekly_projection_matrix(context, projections)
    evaluated_ids = {add_player.player_id} | supported_roster
    missing_projection_weeks = tuple(
        (player_id, week.week)
        for player_id in sorted(evaluated_ids)
        for week in context.weeks
        if (cell := matrix.cell(player_id, week.week)) is None or cell.points is None
    )
    if missing_projection_weeks and not options.allow_partial_schedule:
        raise CoverageIncomplete(
            "Weekly projections miss evaluated player-weeks: "
            + ", ".join(f"{player_id}/W{week}" for player_id, week in missing_projection_weeks)
        )
    projection_by_key = {
        (row.player_id, row.week): row
        for row in projections
        if row.horizon == "WEEKLY" and row.week is not None
    }
    projection_inputs_complete = not missing_projection_weeks and all(
        projection_coverage_is_complete(
            projection_by_key[(player_id, week.week)].coverage_status
        )
        for player_id in evaluated_ids
        for week in context.weeks
        if (player_id, week.week) in projection_by_key
    )

    emergence_player_ids = {
        row.player_id for row in emergence_evidence.players
    } if emergence_evidence is not None else set()
    affirmative_emergence_ids = {
        row.player_id
        for row in (emergence_evidence.players if emergence_evidence else ())
        if row.affirmative_eligible
    }
    emerging_input_cache: dict[str, EmergingScenarioInput] = {}

    def emerging_input(player_id: str | None) -> EmergingScenarioInput | None:
        if (
            player_id is None
            or emergence_evidence is None
            or player_id not in emergence_player_ids
        ):
            return None
        if player_id not in emerging_input_cache:
            emerging_input_cache[player_id] = build_emerging_scenario_input(
                emergence_evidence,
                player_id=player_id,
                weeks=tuple(week.week for week in context.weeks),
                central_projections=projections,
            )
        return emerging_input_cache[player_id]

    candidates: list[DropCandidateEvaluation] = []
    for drop_id in drop_ids:
        after = (supported_roster - ({drop_id} if drop_id else set())) | {add_player.player_id}
        lineup_impact = team_impact(
            context,
            matrix,
            snapshot.user_roster_id,
            supported_roster,
            after,
            options,
        )
        before_skill = {
            player_id
            for player_id in supported_roster
            if _normalized_positions(player_by_id[player_id]).intersection(SKILL_POSITIONS)
        }
        after_skill = (before_skill - ({drop_id} if drop_id else set())) | (
            {add_player.player_id} if add_position in SKILL_POSITIONS else set()
        )
        scenario_impact = risk_impact(
            context,
            matrix,
            snapshot.user_roster_id,
            before_skill,
            after_skill,
            options,
        )
        added_start_weeks = tuple(
            row.week for row in lineup_impact.weeks if add_player.player_id in row.after_starters
        )
        current_row = next(
            row for row in lineup_impact.weeks if row.week == snapshot.manifest.current_week
        )
        holding = _quarterback_holding_evidence(
            snapshot=snapshot,
            add_player=add_player,
            drop_id=drop_id,
            supported_roster=supported_roster,
            player_by_id=player_by_id,
            value_map=value_map,
            context=context,
            matrix=matrix,
            projection_by_key=projection_by_key,
            lineup_impact=lineup_impact,
            options=options,
        )
        add_contingency = _cached_player_contingency_evidence(
            player_id=add_player.player_id,
            roster=after,
            scenarios=contingencies,
            snapshot=snapshot,
            context=context,
            central_matrix=matrix,
            projections=projections,
            options=options,
            now=evaluation_time,
            cache=contingency_cache,
        )
        drop_contingency = (
            _cached_player_contingency_evidence(
                player_id=drop_id,
                roster=supported_roster,
                scenarios=contingencies,
                snapshot=snapshot,
                context=context,
                central_matrix=matrix,
                projections=projections,
                options=options,
                now=evaluation_time,
                cache=contingency_cache,
            )
            if drop_id is not None
            else None
        )
        retained_ceiling = lineup_impact.before_weighted_points + (
            max(0.0, drop_contingency.lineup_ceiling_gain)
            if drop_contingency is not None and drop_contingency.current_authoritative
            else 0.0
        )
        acquisition_ceiling = lineup_impact.after_weighted_points + (
            max(0.0, add_contingency.lineup_ceiling_gain)
            if add_contingency.current_authoritative
            else 0.0
        )
        contingency_uncertainties = tuple(
            row.strongest_uncertainty
            for row in (add_contingency, drop_contingency)
            if row is not None and row.evidence_status != "NOT_PROVIDED"
        )
        contingency = ContingentUpsideEvidence(
            add=add_contingency,
            drop=drop_contingency,
            retained_option_ceiling=round(retained_ceiling, 3),
            acquisition_option_ceiling=round(acquisition_ceiling, 3),
            incremental_option_value=round(acquisition_ceiling - retained_ceiling, 3),
            add_protected=False,
            drop_protected=False,
            required_incremental_value=0.0,
            incremental_gate_passed=True,
            protection_reason="No contingent-upside policy was applied",
            strongest_uncertainty=(
                contingency_uncertainties[0]
                if contingency_uncertainties
                else "No current authoritative contingency relationship was provided"
            ),
        )
        emerging_upside = evaluate_emerging_upside(
            context=context,
            central_matrix=matrix,
            central_projections=projections,
            before_roster=supported_roster,
            after_roster=after,
            add_player_id=add_player.player_id,
            drop_player_id=drop_id,
            add_input=emerging_input(add_player.player_id),
            drop_input=(
                emerging_input(drop_id)
                if drop_id in affirmative_emergence_ids
                else None
            ),
            scoring=dict(snapshot.league.scoring),
            current_week=snapshot.manifest.current_week,
            options=options,
            named_teammate_acquisition_ceiling=contingency.acquisition_option_ceiling,
            named_teammate_retained_ceiling=contingency.retained_option_ceiling,
        )
        ownership = _ownership_delta(
            add_player.player_id,
            drop_id,
            value_map,
            waiver_wire_by_id,
            same_position=(
                drop_id is not None
                and add_position == _waiver_position(player_by_id[drop_id])
            ),
        )
        skill_applicable = add_position in SKILL_POSITIONS
        credited_starter_weeks = (
            tuple(
                sorted(
                    set(holding.required_bye_weeks)
                    | set(holding.discretionary_start_weeks)
                )
            )
            if holding.applicable
            else added_start_weeks
        )
        skill_player = SkillPlayerDecisionEvidence(
            schema_version=1,
            applicable=skill_applicable,
            ownership_normalization_basis_add=value_map[
                add_player.player_id
            ].normalization_basis,
            ownership_normalization_basis_drop=(
                value_map[drop_id].normalization_basis if drop_id is not None else None
            ),
            selected_ownership_add=ownership.selected_add,
            selected_ownership_drop=ownership.selected_drop,
            selected_ownership_delta=ownership.selected_delta,
            market_ownership_add=ownership.market_add,
            market_ownership_drop=ownership.market_drop,
            market_ownership_delta=ownership.market_delta,
            holding_method=holding.reason,
            holding_cost=holding.bench_slot_opportunity_cost,
            streaming_baseline=holding.streaming_replacement_value,
            credited_starter_weeks=credited_starter_weeks,
            standalone_weighted_lineup_delta=lineup_impact.weighted_delta,
            contingency_scenarios=(
                tuple(
                    row
                    for row in (add_contingency, drop_contingency)
                    if row is not None
                )
                if skill_applicable
                else ()
            ),
        )
        candidates.append(
            DropCandidateEvaluation(
                drop_player_id=drop_id,
                ownership=ownership,
                lineup=lineup_impact,
                risk=scenario_impact,
                added_start_weeks=added_start_weeks,
                added_bye_weeks=tuple(
                    week.week
                    for week in context.weeks
                    if add_player.nfl_team in week.bye_teams
                ),
                dropped_bye_weeks=(
                    tuple(
                        week.week
                        for week in context.weeks
                        if player_by_id[drop_id].nfl_team in week.bye_teams
                    )
                    if drop_id is not None
                    else ()
                ),
                current_week_delta=current_row.delta,
                holding=holding,
                contingency=contingency,
                emerging_upside=emerging_upside,
                skill_player=skill_player,
                current_week_add_points=projection_by_key[
                    (add_player.player_id, snapshot.manifest.current_week)
                ].league_points,
                current_week_drop_points=(
                    projection_by_key[
                        (drop_id, snapshot.manifest.current_week)
                    ].league_points
                    if drop_id is not None
                    else None
                ),
            )
        )
    ordered = tuple(
        sorted(
            candidates,
            key=lambda row: (
                -row.lineup.after_weighted_points,
                -row.ownership.selected_delta,
                -row.ownership.market_delta,
                row.drop_player_id or "",
            ),
        )
    )
    selected = ordered[0]
    candidate_hash = stable_hash(
        {
            "add": add_player.player_id,
            "drop_ids": drop_ids,
            "drop_legality": tuple(sorted(drop_legality.items())),
            "exclusions": exclusions,
        }
    )
    value_input_hash = stable_hash(
        {
            "weeks": context.weeks,
            "projections": projections,
            "values": values,
            "news_fresh": tuple(sorted((news_fresh or {}).items())),
            "contingencies": contingencies,
            "waiver_wire_evidence": waiver_wire_evidence,
            "emergence_evidence": emergence_evidence,
        }
    )
    warnings = list(snapshot.warnings)
    if waiver_wire_evidence is None:
        warnings.append("FantasyPros Waiver Wire acquisition evidence was not provided")
    else:
        warnings.extend(waiver_wire_evidence.warnings)
        if not waiver_wire_evidence.complete:
            warnings.append(
                "FantasyPros Waiver Wire acquisition evidence is incomplete and is not decision-ready"
            )
    if emergence_evidence is None:
        warnings.append("Role and volume emergence evidence was not provided")
    else:
        warnings.extend(emergence_evidence.warnings)
        if not emergence_evidence.complete:
            warnings.append(
                "Role and volume emergence evidence is incomplete and fails closed"
            )
    contingency_counts: dict[str, int] = {}
    for scenario in contingencies:
        contingency_counts[scenario.beneficiary_player_id] = (
            contingency_counts.get(scenario.beneficiary_player_id, 0) + 1
        )
        missing_roles = tuple(
            player_id
            for player_id in (
                scenario.beneficiary_player_id,
                scenario.unavailable_teammate_player_id,
            )
            if player_id not in player_by_id
        )
        if missing_roles:
            warnings.append(
                "Contingency relationship contains unmatched player IDs: "
                + ", ".join(missing_roles)
            )
    warnings.extend(
        f"Contingency relationship is ambiguous for {player_id}: {count} records supplied"
        for player_id, count in sorted(contingency_counts.items())
        if count > 1
    )
    unavailable_emerging = tuple(
        sorted(
            {
                (candidate.drop_player_id, candidate.emerging_upside.status)
                for candidate in ordered
                if candidate.emerging_upside.status != "COMPLETE"
            },
            key=lambda row: (row[0] or "", row[1]),
        )
    )
    warnings.extend(
        "Emerging-upside valuation for drop "
        f"{drop_id or 'OPEN_SLOT'} is {status}"
        for drop_id, status in unavailable_emerging
    )
    if any(candidate.emerging_upside.status == "COMPLETE" for candidate in ordered):
        warnings.append(
            "Emerging-upside state probabilities, availability decay, claim success, "
            "FAAB price, and waiver-priority cost are intentionally not estimated"
        )
    described_ids = {add_player.player_id} | {
        row.drop_player_id for row in ordered if row.drop_player_id is not None
    }
    value_inputs_complete = all(
        value_map[player_id].coverage_status.casefold() == "complete"
        for player_id in described_ids
    )
    for player_id in sorted(described_ids):
        warnings.extend(value_map[player_id].warnings)
        for week in context.weeks:
            cell = matrix.cell(player_id, week.week)
            if cell is not None:
                warnings.extend(
                    f"{player_by_id[player_id].name} Week {week.week}: {warning}"
                    for warning in cell.warnings
                )
    news_is_fresh = (news_fresh or {}).get(add_player.player_id) is True
    if not news_is_fresh:
        warnings.append(f"Material-news freshness is unproved for {add_player.name}")
    if not value_inputs_complete:
        warnings.append("Selected or alternative ownership-value evidence is partial")
    if not projection_inputs_complete:
        warnings.append("Evaluated weekly projection evidence is partial")
    holding_omissions = tuple(
        sorted(
            {
                player_id
                for candidate in ordered
                for player_id in candidate.holding.streaming_omission_ids
            }
        )
    )
    if holding_omissions:
        warnings.append(
            "QB streaming baseline omitted incomplete candidates: "
            + ", ".join(holding_omissions)
        )
    if any(candidate.holding.applicable for candidate in ordered):
        warnings.append(
            "QB injury insurance is scenario advantage only; no injury probability is assumed"
        )
    invalid_contingencies = tuple(
        sorted(
            {
                (row.player_id, row.evidence_status, row.strongest_uncertainty)
                for candidate in ordered
                for row in (candidate.contingency.add, candidate.contingency.drop)
                if row is not None
                and row.evidence_status not in {"NOT_PROVIDED", "CURRENT_AUTHORITATIVE"}
            }
        )
    )
    warnings.extend(
        f"Contingency evidence for {player_id} failed closed as {status}: {uncertainty}"
        for player_id, status, uncertainty in invalid_contingencies
    )
    if any(
        row.current_authoritative
        for candidate in ordered
        for row in (candidate.contingency.add, candidate.contingency.drop)
        if row is not None
    ):
        warnings.append(
            "Contingency output preserves scenario magnitude without assigning a teammate-unavailability probability"
        )
    warnings.append("No Waiver decision policy was applied; no final label is available")
    user_settings = dict(snapshot.league.platform_settings)
    base = WaiverEvaluation(
        schema_version=11,
        product="WAIVER ASSISTANT",
        operation="ENTERED ADD/DROP EVALUATION",
        league_key=snapshot.league_key,
        manifest_id=snapshot.manifest.analysis_id,
        evaluated_at=evaluation_time,
        current_week=snapshot.manifest.current_week,
        horizon=tuple(week.week for week in context.weeks),
        add_player_id=add_player.player_id,
        add_position=add_position,
        acquisition_state=acquisition.state,
        selected_drop_player_id=selected.drop_player_id,
        selection_basis=(
            "maximum remaining-week optimal-lineup points before policy; one-QB "
            "backup holds are re-ranked by net hold value when policy is applied"
        ),
        candidates=ordered,
        next_best_drop_player_ids=tuple(
            row.drop_player_id for row in ordered[1:] if row.drop_player_id is not None
        ),
        exclusions=tuple(sorted(exclusions, key=lambda row: (row.reason, row.player_id))),
        user_waiver_position=team.waiver_position,
        user_waiver_budget_used=team.waiver_budget_used,
        user_waiver_budget_total=(
            int(user_settings["waiver_budget"])
            if user_settings.get("waiver_budget") is not None
            else None
        ),
        candidate_hash=candidate_hash,
        value_input_hash=value_input_hash,
        input_bundle_hash=input_bundle_hash,
        availability_source=availability_source,
        waiver_wire_evidence=waiver_wire_evidence,
        emergence_evidence=emergence_evidence,
        material_news_fresh=news_is_fresh,
        add_currently_active=(
            add_player.active
            and str(add_player.injury_status or "").upper() not in KNOWN_INACTIVE
        ),
        value_inputs_complete=value_inputs_complete,
        projection_inputs_complete=projection_inputs_complete,
        policy_version=None,
        policy_hash=None,
        decision=None,
        strongest_uncertainty=(
            f"Material-news freshness is unproved for {add_player.name}"
            if not news_is_fresh
            else "No Waiver decision policy was applied"
        ),
        warnings=tuple(sorted(set(warnings))),
        decision_label=None,
        recommendation_generated=False,
        sleeper_write_performed=False,
        evidence_hash="",
    )
    assert_current(snapshot, now=now)
    return replace(base, evidence_hash=stable_hash(asdict(base)))


def save_waiver_evaluation(evaluation: WaiverEvaluation, path: str | Path) -> Path:
    return atomic_write_json(path, evaluation)


def save_waiver_evaluation_inputs(
    path: str | Path,
    *,
    league_key: str,
    captured_at: datetime,
    availability_source: str,
    availability_by_player: Mapping[str, str],
    drop_legality: Mapping[str, bool | None],
    weeks: Sequence[InSeasonWeek],
    projections: Sequence[Projection],
    values: Sequence[PlayerValueInput],
    news_fresh: Mapping[str, bool],
    contingencies: Sequence[ContingencyScenarioInput] = (),
    waiver_wire_evidence: WaiverWireEvidence | None = None,
    emergence_evidence: EmergenceEvidence | None = None,
) -> Path:
    if captured_at.tzinfo is None:
        raise ValueError("Waiver evaluation-input timestamp must be timezone-aware")
    if not availability_source.strip():
        raise ValueError("Waiver evaluation inputs require availability provenance")
    unsigned = {
        "schema_version": 6,
        "product": "WAIVER ASSISTANT",
        "league_key": league_key,
        "captured_at": captured_at.astimezone(timezone.utc),
        "availability_source": availability_source,
        "availability_by_player": dict(sorted(availability_by_player.items())),
        "drop_legality": dict(sorted(drop_legality.items())),
        "weeks": tuple(sorted(weeks, key=lambda row: row.week)),
        "projections": tuple(
            sorted(
                projections,
                key=lambda row: (row.player_id, row.week or 0, row.horizon),
            )
        ),
        "values": tuple(sorted(values, key=lambda row: row.player_id)),
        "news_fresh": dict(sorted(news_fresh.items())),
        "contingencies": tuple(
            sorted(
                contingencies,
                key=lambda row: (
                    row.beneficiary_player_id,
                    row.unavailable_teammate_player_id,
                    row.relationship,
                ),
            )
        ),
        "waiver_wire_evidence": waiver_wire_evidence,
        "emergence_evidence": emergence_evidence,
    }
    return atomic_write_json(
        path,
        {**unsigned, "input_hash": stable_hash(unsigned)},
    )


def load_waiver_evaluation_inputs(path: str | Path) -> WaiverEvaluationInputs:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    schema_version = int(value.get("schema_version") or 0)
    if schema_version not in {1, 2, 3, 4, 5, 6}:
        raise ValueError("Unsupported Waiver evaluation-input schema")
    if str(value.get("product") or "") != "WAIVER ASSISTANT":
        raise ValueError("Evaluation inputs must be Waiver-scoped")
    captured_at = datetime.fromisoformat(str(value["captured_at"]))
    if captured_at.tzinfo is None:
        raise ValueError("Waiver evaluation-input timestamp must be timezone-aware")
    availability_source = str(value.get("availability_source") or "")
    if not availability_source:
        raise ValueError("Waiver evaluation inputs require availability provenance")
    weeks = tuple(
        InSeasonWeek(
            week=int(row["week"]),
            playoff=bool(row.get("playoff")),
            bye_teams=tuple(row.get("bye_teams") or ()),
        )
        for row in value.get("weeks") or ()
    )
    projections = tuple(
        Projection(
            player_id=str(row["player_id"]),
            horizon=str(row.get("horizon") or "WEEKLY"),
            week=int(row["week"]) if row.get("week") is not None else None,
            raw_stats=tuple(
                (str(key), float(raw)) for key, raw in row.get("raw_stats") or ()
            ),
            league_points=float(row["league_points"]),
            source=str(row["source"]),
            coverage_status=str(row.get("coverage_status") or "complete"),
        )
        for row in value.get("projections") or ()
    )
    values = tuple(
        PlayerValueInput(
            player_id=str(row["player_id"]),
            selected_value=float(row["selected_value"]),
            market_value=float(row["market_value"]),
            raw_projection=float(row["raw_projection"]),
            current_week_position_rank=(
                int(row["current_week_position_rank"])
                if row.get("current_week_position_rank") is not None
                else None
            ),
            rest_of_season_position_rank=(
                int(row["rest_of_season_position_rank"])
                if row.get("rest_of_season_position_rank") is not None
                else None
            ),
            coverage_status=str(row.get("coverage_status") or "complete"),
            warnings=tuple(row.get("warnings") or ())
            + (
                (
                    "Legacy ambiguous waiver_wire_rank was ignored; genuine Waiver Wire evidence was not supplied",
                )
                if schema_version <= 3 and row.get("waiver_wire_rank") is not None
                else ()
            ),
            normalization_basis=str(
                row.get("normalization_basis") or "LEAGUE_POSITIONAL_VORP"
            ),
            long_term_value_horizon=str(
                row.get("long_term_value_horizon") or "ROS"
            ),
        )
        for row in value.get("values") or ()
    )
    contingencies = tuple(
        ContingencyScenarioInput(
            beneficiary_player_id=str(row["beneficiary_player_id"]),
            unavailable_teammate_player_id=str(row["unavailable_teammate_player_id"]),
            relationship=str(row.get("relationship") or ""),
            evidence_source=str(row.get("evidence_source") or ""),
            evidence_captured_at=datetime.fromisoformat(
                str(row["evidence_captured_at"])
            ),
            relationship_status=str(row.get("relationship_status") or "MISSING"),
            projections=tuple(
                Projection(
                    player_id=str(projection["player_id"]),
                    horizon=str(projection.get("horizon") or "WEEKLY"),
                    week=(
                        int(projection["week"])
                        if projection.get("week") is not None
                        else None
                    ),
                    raw_stats=tuple(
                        (str(key), float(raw))
                        for key, raw in projection.get("raw_stats") or ()
                    ),
                    league_points=float(projection["league_points"]),
                    source=str(projection.get("source") or ""),
                    coverage_status=str(
                        projection.get("coverage_status") or "complete"
                    ),
                )
                for projection in row.get("projections") or ()
            ),
            strongest_uncertainty=str(row.get("strongest_uncertainty") or ""),
        )
        for row in value.get("contingencies") or ()
    )
    waiver_wire_evidence = (
        waiver_wire_evidence_from_json(value["waiver_wire_evidence"])
        if value.get("waiver_wire_evidence") is not None
        else None
    )
    emergence_evidence = (
        emergence_evidence_from_json(value["emergence_evidence"])
        if value.get("emergence_evidence") is not None
        else None
    )
    unsigned = {
        key: child for key, child in value.items() if key != "input_hash"
    }
    computed_hash = stable_hash(unsigned)
    declared_hash = str(value.get("input_hash") or "")
    if not declared_hash:
        raise ValueError("Waiver evaluation inputs require an input hash")
    if declared_hash != computed_hash:
        raise ValueError("Waiver evaluation inputs failed hash verification")
    return WaiverEvaluationInputs(
        schema_version=schema_version,
        league_key=str(value["league_key"]),
        captured_at=captured_at.astimezone(timezone.utc),
        availability_source=availability_source,
        availability_by_player=tuple(
            sorted(
                (str(key), str(raw))
                for key, raw in (value.get("availability_by_player") or {}).items()
            )
        ),
        drop_legality=tuple(
            sorted(
                (str(key), raw if isinstance(raw, bool) else None)
                for key, raw in (value.get("drop_legality") or {}).items()
            )
        ),
        weeks=weeks,
        projections=projections,
        values=values,
        news_fresh=tuple(
            sorted(
                (str(key), raw if isinstance(raw, bool) else False)
                for key, raw in (value.get("news_fresh") or {}).items()
            )
        ),
        contingencies=contingencies,
        waiver_wire_evidence=waiver_wire_evidence,
        emergence_evidence=emergence_evidence,
        input_hash=computed_hash,
    )


def load_waiver_evaluation(path: str | Path) -> dict[str, object]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    expected = str(value.get("evidence_hash") or "")
    unsigned = dict(value)
    unsigned["evidence_hash"] = ""
    actual = stable_hash(unsigned)
    if not expected or expected != actual:
        raise ValueError("Waiver evaluation evidence failed hash verification")
    value["current"] = False
    value["offline_replay"] = True
    value.setdefault("warnings", []).append("OFFLINE/NON-CURRENT Waiver evaluation")
    return value
