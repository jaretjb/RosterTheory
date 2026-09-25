from __future__ import annotations

import json
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Mapping, Sequence

from roster_theory.core.errors import CoverageIncomplete, RosterIllegal
from roster_theory.core.models import Projection
from roster_theory.core.projections import projection_is_complete
from roster_theory.core.provenance import stable_hash
from roster_theory.inseason.evaluation import (
    InSeasonContext,
    InSeasonWeek,
    build_weekly_projection_matrix,
    weighted_lineup_score,
)
from roster_theory.providers.cache import atomic_write_json
from roster_theory.waiver.emergence import EmergenceEvidence
from roster_theory.waiver.evaluation import (
    ContingencyScenarioInput,
    PlayerValueInput,
    WaiverEvaluation,
    WaiverEvaluationOptions,
    evaluate_waiver,
    fresh_rank_dominates,
    reconcile_current_week_inactive_omissions,
)
from roster_theory.waiver.ww_evidence import WaiverWireEvidence
from roster_theory.waiver.policy import (
    WaiverDecisionPolicy,
    apply_waiver_policy,
    emerging_role_signal_strength,
    evaluation_options_for_policy,
)
from roster_theory.waiver.priority import (
    WaiverPriorityWeights,
    build_waiver_priority_scores,
)
from roster_theory.waiver.snapshot import (
    ACQUIRABLE_STATES,
    AcquisitionState,
    WaiverSnapshot,
    assert_current,
)


SUPPORTED_POSITIONS = frozenset({"QB", "RB", "WR", "TE", "K", "DST", "DEF"})
AFFIRMATIVE_LABELS = frozenset({"ADD NOW", "CLAIM", "ACQUIRE"})
PRUNING_VERSION = "wa-026-partial-roster-coverage-v12"
LABEL_TIER = {"ADD NOW": 0, "CLAIM": 0, "ACQUIRE": 0, "WATCH": 1, "PASS": 2}


@dataclass(frozen=True, slots=True)
class WaiverSearchCandidateBound:
    player_id: str
    acquisition_state: str
    maximum_after_weighted_points: float


@dataclass(frozen=True, slots=True)
class WaiverSearchOmission:
    player_id: str
    acquisition_state: str
    reason: str


@dataclass(frozen=True, slots=True)
class WaiverSearchPruning:
    player_id: str
    maximum_after_weighted_points: float
    incumbent_after_weighted_points: float
    reason: str


@dataclass(frozen=True, slots=True)
class WaiverSearchNotableCandidate:
    player_id: str
    category: str
    position: str
    nfl_team: str | None
    current_week_position_rank: int | None
    rest_of_season_position_rank: int | None
    waiver_wire_market_rank: float | None
    waiver_wire_position_rank: float | None
    roster_comparison: str | None
    reason: str


@dataclass(frozen=True, slots=True)
class WaiverNoActionOption:
    after_weighted_points: float
    selected: bool
    reason: str


@dataclass(frozen=True, slots=True)
class WaiverClaimRecommendation:
    priority: int
    add_player_id: str
    drop_player_id: str | None
    position: str
    decision_label: str
    claim_group: str
    mutually_exclusive_priorities: tuple[int, ...]
    waiver_value: float | None
    performance_adjustment: float


@dataclass(frozen=True, slots=True)
class WaiverSearch:
    schema_version: int
    evaluation_schema_version: int
    product: str
    operation: str
    league_key: str
    manifest_id: str
    current_week: int
    horizon: tuple[int, ...]
    policy_version: str
    policy_hash: str
    pruning_version: str
    pruning_enabled: bool
    ranking_basis: str
    eligible_candidate_ids: tuple[str, ...]
    candidate_bounds: tuple[WaiverSearchCandidateBound, ...]
    exact_evaluations: tuple[WaiverEvaluation, ...]
    pruned_candidates: tuple[WaiverSearchPruning, ...]
    omissions: tuple[WaiverSearchOmission, ...]
    notable_candidates: tuple[WaiverSearchNotableCandidate, ...]
    claim_plan: tuple[WaiverClaimRecommendation, ...]
    best_add_player_id: str | None
    best_drop_player_id: str | None
    best_decision_label: str | None
    recommended_action: str
    no_action: WaiverNoActionOption
    candidate_hash: str
    value_input_hash: str
    snapshot_hash: str
    input_bundle_hash: str
    availability_source: str
    emergence_evidence: EmergenceEvidence | None
    ros_panel_evidence: Mapping[str, object] | None
    strongest_uncertainty: str
    warnings: tuple[str, ...]
    sleeper_write_performed: bool
    evidence_hash: str


def _evaluation_sort_key(evaluation: WaiverEvaluation) -> tuple[object, ...]:
    selected = evaluation.candidates[0]
    priority_score = (
        evaluation.decision.priority_score
        if evaluation.decision is not None
        else selected.lineup.after_weighted_points
    )
    acquisition_priority = (
        evaluation.waiver_priority.composite_score
        if evaluation.waiver_priority is not None
        and evaluation.waiver_priority.composite_score is not None
        else -1.0
    )
    return (
        LABEL_TIER[evaluation.decision_label or "PASS"],
        -priority_score,
        -acquisition_priority,
        -selected.lineup.after_weighted_points,
        selected.ownership.current_week_add_rank or 10_000,
        selected.ownership.rest_of_season_add_rank or 10_000,
        -selected.ownership.selected_delta,
        -selected.ownership.market_delta,
        -selected.ownership.raw_projection_delta,
        -selected.current_week_delta,
        -selected.lineup.depth_delta,
        evaluation.add_player_id,
        selected.drop_player_id or "",
    )


def _rank_projection_dominates(
    add: PlayerValueInput,
    drop: PlayerValueInput,
    *,
    same_position: bool,
) -> bool:
    """Protect a potential exact upgrade without bypassing decision gates."""
    if not same_position:
        return False
    add_ros = (
        add.selected_rest_of_season_position_rank
        if add.selected_rest_of_season_position_rank is not None
        else add.rest_of_season_position_rank
    )
    drop_ros = (
        drop.selected_rest_of_season_position_rank
        if drop.selected_rest_of_season_position_rank is not None
        else drop.rest_of_season_position_rank
    )
    ranks = (
        add.current_week_position_rank,
        drop.current_week_position_rank,
        add_ros,
        drop_ros,
    )
    if any(rank is None for rank in ranks):
        return False
    assert add.current_week_position_rank is not None
    assert drop.current_week_position_rank is not None
    assert add_ros is not None
    assert drop_ros is not None
    return bool(
        add.current_week_position_rank < drop.current_week_position_rank
        and add_ros < drop_ros
        and add.raw_projection >= drop.raw_projection
    )


def _claim_plan(
    evaluations: Sequence[WaiverEvaluation],
) -> tuple[WaiverClaimRecommendation, ...]:
    affirmative = tuple(
        row
        for row in evaluations
        if row.decision_label in AFFIRMATIVE_LABELS
        and row.candidates
        and (row.candidates[0].same_position or row.candidates[0].drop_player_id is None)
    )

    def skill_key(row: WaiverEvaluation) -> tuple[object, ...]:
        priority = row.waiver_priority
        performance = priority.performance_score if priority else None
        selected = row.candidates[0]
        ww_rank = selected.ownership.waiver_wire_market_add_rank
        return (
            -float(performance if performance is not None else -1.0),
            ww_rank if ww_rank is not None else 10_000,
            selected.ownership.current_week_add_rank or 10_000,
            selected.ownership.rest_of_season_add_rank or 10_000,
            row.add_player_id,
        )

    skill_pool = sorted(
        (row for row in affirmative if row.add_position in {"QB", "RB", "WR", "TE"}),
        key=lambda row: (
            -float(
                row.waiver_priority.composite_score
                if row.waiver_priority is not None
                and row.waiver_priority.composite_score is not None
                else -1.0
            ),
            row.add_player_id,
        ),
    )
    skill: list[WaiverEvaluation] = []
    while skill_pool and len(skill) < 4:
        leader = skill_pool[0]
        leader_score = float(
            leader.waiver_priority.composite_score
            if leader.waiver_priority is not None
            and leader.waiver_priority.composite_score is not None
            else -1.0
        )
        band = tuple(
            row
            for row in skill_pool
            if float(
                row.waiver_priority.composite_score
                if row.waiver_priority is not None
                and row.waiver_priority.composite_score is not None
                else -1.0
            )
            >= leader_score - 2.0
        )
        skill.extend(sorted(band, key=skill_key))
        band_ids = {id(row) for row in band}
        skill_pool = [row for row in skill_pool if id(row) not in band_ids]

    def specialist_key(row: WaiverEvaluation) -> tuple[object, ...]:
        selected = row.candidates[0]
        return (
            -(row.decision.priority_score if row.decision else -100.0),
            selected.ownership.current_week_add_rank or 10_000,
            row.add_player_id,
        )

    skill = skill[:4]
    kickers = sorted(
        (row for row in affirmative if row.add_position == "K"),
        key=specialist_key,
    )[:2]
    defenses = sorted(
        (row for row in affirmative if row.add_position == "DST"),
        key=specialist_key,
    )[:3]
    selected_rows = tuple(skill + kickers + defenses)
    groups = tuple(
        (
            f"DROP:{row.selected_drop_player_id}"
            if row.selected_drop_player_id is not None
            else f"OPEN_SLOT:{index}"
        )
        for index, row in enumerate(selected_rows, 1)
    )
    result: list[WaiverClaimRecommendation] = []
    for priority_number, (row, group) in enumerate(zip(selected_rows, groups), 1):
        evidence = row.waiver_priority
        result.append(
            WaiverClaimRecommendation(
                priority=priority_number,
                add_player_id=row.add_player_id,
                drop_player_id=row.selected_drop_player_id,
                position=row.add_position,
                decision_label=str(row.decision_label),
                claim_group=group,
                mutually_exclusive_priorities=tuple(
                    other_priority
                    for other_priority, other_group in enumerate(groups, 1)
                    if other_group == group and other_priority != priority_number
                ),
                waiver_value=(evidence.composite_score if evidence else None),
                performance_adjustment=(
                    evidence.performance_adjustment if evidence else 0.0
                ),
            )
        )
    return tuple(result)


def _validate_search_inputs(
    snapshot: WaiverSnapshot,
    *,
    weeks: Sequence[InSeasonWeek],
    projections: Sequence[Projection],
    values: Sequence[PlayerValueInput],
    drop_legality: Mapping[str, bool | None],
    news_fresh: Mapping[str, bool],
    input_bundle_hash: str,
    availability_source: str,
) -> tuple[
    tuple[str, ...],
    tuple[WaiverSearchOmission, ...],
    dict[str, PlayerValueInput],
    dict[tuple[str, int], Projection],
    set[str],
    dict[str, str],
    dict[str, str],
]:
    if not snapshot.completeness.snapshot_complete:
        failed = tuple(
            name
            for name, complete in asdict(snapshot.completeness).items()
            if not complete
        )
        raise CoverageIncomplete(
            "Complete Waiver search requires a complete snapshot: " + ", ".join(failed)
        )
    if not input_bundle_hash:
        raise CoverageIncomplete("Complete Waiver search requires a verified input hash")
    if not availability_source:
        raise CoverageIncomplete("Complete Waiver search requires availability provenance")

    ordered_weeks = tuple(sorted(weeks, key=lambda row: row.week))
    if not ordered_weeks or ordered_weeks[0].week != snapshot.manifest.current_week:
        raise CoverageIncomplete("Search weeks must begin at the snapshot current week")
    if tuple(row.week for row in ordered_weeks) != tuple(
        range(ordered_weeks[0].week, ordered_weeks[-1].week + 1)
    ):
        raise CoverageIncomplete("Search weeks must be continuous")

    player_by_id = {player.player_id: player for player in snapshot.players}
    acquisition_by_id = {row.player_id: row for row in snapshot.acquisitions}
    if len(player_by_id) != len(snapshot.players):
        raise CoverageIncomplete("Waiver snapshot contains duplicate player IDs")
    if (
        len(acquisition_by_id) != len(snapshot.acquisitions)
        or set(acquisition_by_id) != set(player_by_id)
    ):
        raise CoverageIncomplete("Waiver snapshot acquisition coverage is incomplete")

    acquirable: list[str] = []
    omissions: list[WaiverSearchOmission] = []
    moves_locked = dict(snapshot.league.platform_settings).get("disable_adds") == 1
    for player in snapshot.players:
        acquisition = acquisition_by_id[player.player_id]
        if not SUPPORTED_POSITIONS.intersection(player.positions):
            omissions.append(
                WaiverSearchOmission(
                    player.player_id, acquisition.state, "OUT_OF_SCOPE_POSITION"
                )
            )
        elif moves_locked and acquisition.state in ACQUIRABLE_STATES:
            omissions.append(WaiverSearchOmission(player.player_id, acquisition.state, "LEAGUE_MOVES_LOCKED"))
        elif acquisition.state in ACQUIRABLE_STATES:
            acquirable.append(player.player_id)
        else:
            omissions.append(
                WaiverSearchOmission(
                    player.player_id,
                    acquisition.state,
                    f"ACQUISITION_{acquisition.state}",
                )
            )

    team = next(
        (row for row in snapshot.teams if row.roster_id == snapshot.user_roster_id),
        None,
    )
    if team is None:
        raise CoverageIncomplete("Waiver user roster is missing from the snapshot")
    active_roster = set(team.player_ids) - set(team.reserve_ids)
    supported_roster = {
        player_id
        for player_id in active_roster
        if player_id in player_by_id
        and SUPPORTED_POSITIONS.intersection(player_by_id[player_id].positions)
    }
    capacity = next(
        row for row in snapshot.roster_capacity if row.roster_id == snapshot.user_roster_id
    )
    value_map = {row.player_id: row for row in values}
    if len(value_map) != len(values):
        raise CoverageIncomplete("Waiver search values contain duplicate player IDs")
    missing_league_rostered_values = tuple(
        sorted(set(dict(snapshot.owner_by_player)) - set(value_map))
    )
    omissions.extend(
        WaiverSearchOmission(
            player_id,
            acquisition_by_id[player_id].state,
            "ROSTER_VALUE_UNAVAILABLE",
        )
        for player_id in missing_league_rostered_values
    )
    missing_values = tuple(sorted(supported_roster - set(value_map)))
    partial_values = tuple(
        sorted(
            player_id
            for player_id in supported_roster
            if player_id in value_map
            if value_map[player_id].coverage_status.casefold() != "complete"
        )
    )
    drop_evidence_exclusions = {
        player_id: "INCOMPLETE_VALUE_EVIDENCE"
        for player_id in (*missing_values, *partial_values)
    }
    omissions.extend(
        WaiverSearchOmission(
            player_id,
            acquisition_by_id[player_id].state,
            (
                "ROSTER_VALUE_UNAVAILABLE"
                if player_id in missing_values
                else "ROSTER_VALUE_INCOMPLETE"
            ),
        )
        for player_id in (*missing_values, *partial_values)
        if player_id not in missing_league_rostered_values
    )

    projection_map: dict[tuple[str, int], Projection] = {}
    for row in projections:
        if row.horizon != "WEEKLY" or row.week is None:
            continue
        key = (row.player_id, row.week)
        if key in projection_map:
            raise CoverageIncomplete(
                f"Waiver search projections duplicate {row.player_id}/W{row.week}"
            )
        projection_map[key] = row
    skill_roster = {
        player_id
        for player_id in supported_roster
        if {
            "DST" if position.upper() == "DEF" else position.upper()
            for position in player_by_id[player_id].positions
        }.intersection({"QB", "RB", "WR", "TE"})
    }
    roster_projection_keys = {
        (player_id, week.week)
        for player_id in skill_roster
        for week in ordered_weeks
    }
    missing_projections = tuple(sorted(roster_projection_keys - set(projection_map)))
    partial_projections = tuple(
        sorted(
            key
            for key in roster_projection_keys
            if key in projection_map
            if not projection_is_complete(
                projection_map[key], current_week=snapshot.manifest.current_week
            )
        )
    )
    roster_projection_exclusions = {
        player_id
        for player_id, _week in (*missing_projections, *partial_projections)
    }
    roster_evidence_exclusions = {
        player_id: "INCOMPLETE_PROJECTION_EVIDENCE"
        for player_id in roster_projection_exclusions
    }
    drop_evidence_exclusions.update(roster_evidence_exclusions)
    omissions.extend(
        WaiverSearchOmission(
            player_id,
            acquisition_by_id[player_id].state,
            "ROSTER_PROJECTION_INCOMPLETE",
        )
        for player_id in sorted(roster_projection_exclusions)
    )

    eligible: list[str] = []
    for player_id in sorted(acquirable):
        acquisition = acquisition_by_id[player_id]
        value = value_map.get(player_id)
        if value is None:
            omissions.append(
                WaiverSearchOmission(
                    player_id, acquisition.state, "NO_AUTHORITATIVE_VALUE"
                )
            )
            continue
        if value.coverage_status.casefold() != "complete":
            omissions.append(
                WaiverSearchOmission(
                    player_id, acquisition.state, "INCOMPLETE_VALUE_COVERAGE"
                )
            )
            continue
        normalized_positions = {
            "DST" if position.upper() == "DEF" else position.upper()
            for position in player_by_id[player_id].positions
        }
        special_positions = normalized_positions.intersection({"K", "DST"})
        if (
            special_positions
            and (
                value.current_week_position_rank is None
                or value.current_week_position_rank < 1
            )
        ):
            omissions.append(
                WaiverSearchOmission(
                    player_id,
                    acquisition.state,
                    "CURRENT_WEEK_POSITION_RANK_UNAVAILABLE",
                )
            )
            continue
        incumbent_special_ids = {
            roster_id
            for roster_id in supported_roster
            if special_positions.intersection(
                {
                    "DST" if position.upper() == "DEF" else position.upper()
                    for position in player_by_id[roster_id].positions
                }
            )
        }
        incumbent_special_keys = {
            (roster_id, week.week)
            for roster_id in incumbent_special_ids
            for week in ordered_weeks
        }
        if special_positions and (
            not incumbent_special_keys.issubset(projection_map)
            or any(
                not projection_is_complete(
                    projection_map[key], current_week=snapshot.manifest.current_week
                )
                for key in incumbent_special_keys
                if key in projection_map
            )
        ):
            omissions.append(
                WaiverSearchOmission(
                    player_id,
                    acquisition.state,
                    "ROSTER_POSITION_PROJECTION_UNAVAILABLE",
                )
            )
            continue
        expected = {(player_id, week.week) for week in ordered_weeks}
        if not expected.issubset(projection_map):
            omissions.append(
                WaiverSearchOmission(
                    player_id, acquisition.state, "INCOMPLETE_PROJECTION_COVERAGE"
                )
            )
            continue
        if any(
            not projection_is_complete(
                projection_map[key], current_week=snapshot.manifest.current_week
            )
            for key in expected
        ):
            omissions.append(
                WaiverSearchOmission(
                    player_id, acquisition.state, "INCOMPLETE_PROJECTION_COVERAGE"
                )
            )
            continue
        if news_fresh.get(player_id) is not True:
            omissions.append(
                WaiverSearchOmission(
                    player_id, acquisition.state, "MATERIAL_NEWS_NOT_FRESH"
                )
            )
            continue
        eligible.append(player_id)

    if capacity.open_active_slots == 0 and eligible:
        unknown_legality = tuple(
            sorted(
                player_id
                for player_id in supported_roster - set(drop_evidence_exclusions)
                if not isinstance(drop_legality.get(player_id), bool)
            )
        )
        for player_id in unknown_legality:
            drop_evidence_exclusions[player_id] = "DROP_LEGALITY_UNKNOWN"
            omissions.append(WaiverSearchOmission(
                player_id, acquisition_by_id[player_id].state, "DROP_LEGALITY_UNKNOWN"
            ))
        legal_drops = {
            player_id for player_id in supported_roster - set(drop_evidence_exclusions)
            if drop_legality.get(player_id) is True
        }
        for player_id in tuple(eligible):
            positions = set(player_by_id[player_id].positions)
            category = positions & {"K", "DST", "DEF"} or {"QB", "RB", "WR", "TE"}
            if not any(category.intersection(player_by_id[drop_id].positions) for drop_id in legal_drops):
                eligible.remove(player_id)
                omissions.append(WaiverSearchOmission(
                    player_id, acquisition_by_id[player_id].state, "NO_PROVED_LEGAL_DROP"
                ))
    return (
        tuple(sorted(eligible)),
        tuple(sorted(omissions, key=lambda row: (row.reason, row.player_id))),
        value_map,
        projection_map,
        supported_roster - set(roster_evidence_exclusions),
        drop_evidence_exclusions,
        roster_evidence_exclusions,
    )


def _candidate_upper_bounds(
    snapshot: WaiverSnapshot,
    *,
    candidate_ids: Sequence[str],
    roster_player_ids: set[str],
    weeks: Sequence[InSeasonWeek],
    projections: Sequence[Projection],
    options: WaiverEvaluationOptions,
) -> dict[str, float]:
    player_by_id = {player.player_id: player for player in snapshot.players}
    relevant_ids = roster_player_ids | set(candidate_ids)
    context = InSeasonContext(
        players=tuple(player_by_id[player_id] for player_id in sorted(relevant_ids)),
        roster_positions=snapshot.league.roster_positions,
        weeks=tuple(weeks),
        unowned_player_ids=tuple(sorted(candidate_ids)),
        evaluation_positions=("QB", "RB", "WR", "TE", "K", "DST"),
        current_status_week_only=True,
        current_week=snapshot.manifest.current_week,
    )
    matrix = build_weekly_projection_matrix(context, projections)
    return {
        player_id: weighted_lineup_score(
            context,
            matrix,
            roster_player_ids | {player_id},
            options,
        )
        for player_id in candidate_ids
    }


def _notable_candidates(
    snapshot: WaiverSnapshot,
    *,
    omissions: Sequence[WaiverSearchOmission],
    pruned: Sequence[WaiverSearchPruning],
    value_map: Mapping[str, PlayerValueInput],
    drop_legality: Mapping[str, bool | None],
    waiver_wire_evidence: WaiverWireEvidence | None,
    emergence_evidence: EmergenceEvidence | None,
    limit: int = 5,
) -> tuple[WaiverSearchNotableCandidate, ...]:
    """Select a small explanatory shortlist without changing search eligibility."""
    player_by_id = {player.player_id: player for player in snapshot.players}
    omission_by_id = {row.player_id: row for row in omissions}
    pruning_by_id = {row.player_id: row for row in pruned}
    waiver_by_id = {
        row.player_id: row
        for row in (waiver_wire_evidence.players if waiver_wire_evidence else ())
        if row.match_status == "MATCHED"
    }
    emergence_by_id = {
        row.player_id: row
        for row in (emergence_evidence.players if emergence_evidence else ())
    }
    user_team = next(
        row for row in snapshot.teams if row.roster_id == snapshot.user_roster_id
    )
    roster_ids = set(user_team.player_ids)

    omission_reasons = {
        "NO_AUTHORITATIVE_VALUE": (
            "MISSING_EVIDENCE",
            "authoritative rest-of-season value is missing, so a safe add/drop "
            "comparison is unavailable",
        ),
        "INCOMPLETE_VALUE_COVERAGE": (
            "MISSING_EVIDENCE",
            "authoritative value coverage is incomplete",
        ),
        "INCOMPLETE_PROJECTION_COVERAGE": (
            "MISSING_EVIDENCE",
            "weekly projection coverage is incomplete",
        ),
        "MATERIAL_NEWS_NOT_FRESH": (
            "MISSING_EVIDENCE",
            "material-news evidence is not fresh",
        ),
        "CURRENT_WEEK_POSITION_RANK_UNAVAILABLE": (
            "MISSING_EVIDENCE",
            "the current-week position rank is unavailable",
        ),
        "ROSTER_POSITION_PROJECTION_UNAVAILABLE": (
            "MISSING_EVIDENCE",
            "the roster comparison is missing complete weekly projections",
        ),
    }
    rows: list[tuple[tuple[object, ...], WaiverSearchNotableCandidate]] = []
    candidate_ids = set(omission_by_id) | set(pruning_by_id)
    for player_id in candidate_ids:
        player = player_by_id.get(player_id)
        if player is None:
            continue
        waiver = waiver_by_id.get(player_id)
        emergence = emergence_by_id.get(player_id)
        high_waiver_rank = (
            waiver is not None
            and waiver.market_overall_rank is not None
            and waiver.market_overall_rank <= 10
        )
        role_signal = emergence is not None and emergence.affirmative_eligible
        value = value_map.get(player_id)
        normalized_positions = tuple(
            "DST" if position.upper() == "DEF" else position.upper()
            for position in player.positions
        )
        position = next(
            (item for item in ("QB", "RB", "WR", "TE", "K", "DST") if item in normalized_positions),
            normalized_positions[0] if normalized_positions else "?",
        )

        comparison: str | None = None
        if value is not None:
            comparable = []
            for roster_id in roster_ids:
                roster_player = player_by_id.get(roster_id)
                roster_value = value_map.get(roster_id)
                if (
                    roster_player is None
                    or roster_value is None
                    or drop_legality.get(roster_id) is not True
                    or position not in {
                        "DST" if item.upper() == "DEF" else item.upper()
                        for item in roster_player.positions
                    }
                ):
                    continue
                if (
                    value.current_week_position_rank is not None
                    and roster_value.current_week_position_rank is not None
                    and value.current_week_position_rank
                    < roster_value.current_week_position_rank
                ):
                    comparable.append(
                        (
                            roster_value.current_week_position_rank
                            - value.current_week_position_rank,
                            f"Week {snapshot.manifest.current_week} {position}"
                            f"{value.current_week_position_rank} is ahead of "
                            f"{roster_player.name} {position}"
                            f"{roster_value.current_week_position_rank}",
                        )
                    )
            if comparable:
                comparison = max(comparable, key=lambda row: (row[0], row[1]))[1]

        omission = omission_by_id.get(player_id)
        pruning = pruning_by_id.get(player_id)
        if pruning is not None:
            if pruning.reason.startswith("WAIVER_VALUE_BELOW_EXACT_CUTOFF"):
                category = "NOT_EXACTLY_EVALUATED"
                reason = (
                    "ranked outside the bounded exact-evaluation portfolio; "
                    "no move-level conclusion was made"
                )
            else:
                category = "BELOW_THRESHOLD"
            if pruning.reason.startswith("OWNERSHIP_UPPER_BOUND_BELOW_WATCH_FLOORS"):
                reason = (
                    "considered, but no legal drop cleared both trusted-expert "
                    "and market ownership-value floors"
                )
            elif not pruning.reason.startswith("WAIVER_VALUE_BELOW_EXACT_CUTOFF"):
                reason = "considered, but safely bounded below the stronger exact option"
        elif omission is not None and omission.reason.startswith("ACQUISITION_"):
            category = "NOT_AVAILABLE"
            reason = "not currently available to add in this league"
        elif omission is not None and omission.reason in omission_reasons:
            category, reason = omission_reasons[omission.reason]
            if (
                omission.reason == "INCOMPLETE_VALUE_COVERAGE"
                and value is not None
                and any(
                    "outside complete selected/market value-board coverage"
                    in warning
                    for warning in value.warnings
                )
            ):
                reason = (
                    "ranked outside complete trusted-expert and market value-board "
                    "coverage; retained for visibility, not recommendation"
                )
        else:
            continue

        if not (high_waiver_rank or role_signal or comparison):
            continue
        market_rank = waiver.market_overall_rank if waiver else None
        current_rank = value.current_week_position_rank if value else None
        ros_rank = value.rest_of_season_position_rank if value else None
        signal_priority = (
            0
            if role_signal
            else 1
            if category != "NOT_AVAILABLE"
            and market_rank is not None
            and market_rank <= 3
            else 2
            if category != "NOT_AVAILABLE" and comparison
            else 3
            if category != "NOT_AVAILABLE"
            else 4
        )
        sort_key = (
            signal_priority,
            market_rank if market_rank is not None else float("inf"),
            current_rank if current_rank is not None else 10_000,
            ros_rank if ros_rank is not None else 10_000,
            player_id,
        )
        rows.append(
            (
                sort_key,
                WaiverSearchNotableCandidate(
                    player_id=player_id,
                    category=category,
                    position=position,
                    nfl_team=player.nfl_team,
                    current_week_position_rank=current_rank,
                    rest_of_season_position_rank=ros_rank,
                    waiver_wire_market_rank=market_rank,
                    waiver_wire_position_rank=(
                        waiver.market_position_rank if waiver else None
                    ),
                    roster_comparison=comparison,
                    reason=reason,
                ),
            )
        )
    return tuple(row for _, row in sorted(rows, key=lambda item: item[0])[:limit])


def _baseline_score(
    snapshot: WaiverSnapshot,
    *,
    roster_player_ids: set[str],
    weeks: Sequence[InSeasonWeek],
    projections: Sequence[Projection],
    options: WaiverEvaluationOptions,
) -> float:
    player_by_id = {player.player_id: player for player in snapshot.players}
    context = InSeasonContext(
        players=tuple(player_by_id[player_id] for player_id in sorted(roster_player_ids)),
        roster_positions=snapshot.league.roster_positions,
        weeks=tuple(weeks),
        unowned_player_ids=(),
        evaluation_positions=("QB", "RB", "WR", "TE", "K", "DST"),
        current_status_week_only=True,
        current_week=snapshot.manifest.current_week,
    )
    matrix = build_weekly_projection_matrix(context, projections)
    return weighted_lineup_score(context, matrix, roster_player_ids, options)


def search_waiver_candidates(
    snapshot: WaiverSnapshot,
    *,
    weeks: Sequence[InSeasonWeek],
    projections: Sequence[Projection],
    values: Sequence[PlayerValueInput],
    drop_legality: Mapping[str, bool | None],
    news_fresh: Mapping[str, bool],
    contingencies: Sequence[ContingencyScenarioInput] = (),
    waiver_wire_evidence: WaiverWireEvidence | None = None,
    ros_panel_evidence: Mapping[str, object] | None = None,
    emergence_evidence: EmergenceEvidence | None = None,
    input_bundle_hash: str,
    availability_source: str,
    policy: WaiverDecisionPolicy,
    options: WaiverEvaluationOptions = WaiverEvaluationOptions(),
    enable_pruning: bool = True,
    now: datetime | None = None,
) -> WaiverSearch:
    assert_current(snapshot, now=now)
    projections = reconcile_current_week_inactive_omissions(snapshot, projections)
    if snapshot.league_key != policy.league_key:
        raise ValueError("Waiver search policy is for a different league")
    if emergence_evidence is not None:
        if emergence_evidence.league_key != snapshot.league_key:
            raise CoverageIncomplete("Emergence evidence belongs to a different league")
        expected_emergence_hash = stable_hash(
            asdict(replace(emergence_evidence, evidence_hash=""))
        )
        if emergence_evidence.evidence_hash != expected_emergence_hash:
            raise CoverageIncomplete("Emergence evidence hash is invalid")
    if options.playoff_weight <= 0:
        raise ValueError("playoff_weight must be positive")
    if not 0 <= options.offense_downside_multiplier < 1:
        raise ValueError("offense_downside_multiplier must be at least 0 and below 1")
    if options.offense_upside_multiplier <= 1:
        raise ValueError("offense_upside_multiplier must be above 1")
    options = evaluation_options_for_policy(policy, options)
    ordered_weeks = tuple(sorted(weeks, key=lambda row: row.week))
    (
        eligible_ids,
        omissions,
        value_map,
        projection_map,
        supported_roster,
        drop_evidence_exclusions,
        roster_evidence_exclusions,
    ) = _validate_search_inputs(
        snapshot,
        weeks=ordered_weeks,
        projections=projections,
        values=values,
        drop_legality=drop_legality,
        news_fresh=news_fresh,
        input_bundle_hash=input_bundle_hash,
        availability_source=availability_source,
    )
    acquisition_by_id = {row.player_id: row for row in snapshot.acquisitions}
    player_by_id = {row.player_id: row for row in snapshot.players}
    special_team_candidates = {
        player_id
        for player_id in eligible_ids
        if {
            "DST" if position.upper() == "DEF" else position.upper()
            for position in player_by_id[player_id].positions
        }.intersection({"K", "DST"})
    }
    priority_by_id = (
        build_waiver_priority_scores(
            players=snapshot.players,
            values=values,
            waiver_wire_evidence=waiver_wire_evidence,
            owner_by_player=dict(snapshot.owner_by_player),
            current_bye_teams=ordered_weeks[0].bye_teams,
            weights=WaiverPriorityWeights(
                weekly=policy.priority_weekly_weight,
                waiver=policy.priority_waiver_weight,
                ros=policy.priority_ros_weight,
            ),
        )
        if policy.priority_enabled
        else {}
    )
    scored_priority_candidates = tuple(
        sorted(
            (
                player_id
                for player_id in eligible_ids
                if player_id not in special_team_candidates
                and priority_by_id.get(player_id) is not None
                and priority_by_id[player_id].composite_score is not None
            ),
            key=lambda player_id: (
                not bool(player_by_id[player_id].active),
                str(player_by_id[player_id].injury_status or "").upper()
                in {"IR", "PUP", "SUSP", "OUT"},
                not news_fresh.get(player_id, False),
                -float(priority_by_id[player_id].composite_score or 0.0),
                player_id,
            ),
        )
    )
    if enable_pruning and scored_priority_candidates:
        cutoff_index = min(
            policy.priority_exact_candidate_count,
            len(scored_priority_candidates),
        ) - 1
        cutoff_score = priority_by_id[
            scored_priority_candidates[cutoff_index]
        ].composite_score
        priority_exact_candidates = {
            player_id
            for player_id in scored_priority_candidates
            if (
                priority_by_id[player_id].composite_score is not None
                and priority_by_id[player_id].composite_score >= float(cutoff_score or 0.0)
            )
        }
    else:
        priority_exact_candidates = set(scored_priority_candidates)
    priority_prunable_candidates = (
        set(scored_priority_candidates) - priority_exact_candidates
        if enable_pruning
        else set()
    )
    skill_roster = {
        player_id
        for player_id in supported_roster
        if {
            "DST" if position.upper() == "DEF" else position.upper()
            for position in player_by_id[player_id].positions
        }.intersection({"QB", "RB", "WR", "TE"})
    }
    normalized_slots = tuple(slot.upper() for slot in snapshot.league.roster_positions)
    roster_qb_ids = tuple(
        player_id
        for player_id in supported_roster
        if "QB" in {position.upper() for position in player_by_id[player_id].positions}
    )
    current_week_row = ordered_weeks[0]
    roster_qbs_all_bye = bool(roster_qb_ids) and all(
        player_by_id[player_id].nfl_team in current_week_row.bye_teams
        for player_id in roster_qb_ids
    )
    current_roster_qb_points = max(
        (
            projection_map[(player_id, current_week_row.week)].league_points
            for player_id in roster_qb_ids
            if player_by_id[player_id].nfl_team not in current_week_row.bye_teams
        ),
        default=0.0,
    )
    qb_hold_candidates = {
        player_id
        for player_id in eligible_ids
        if normalized_slots.count("QB") == 1
        and "SUPER_FLEX" not in normalized_slots
        and "QB" in {position.upper() for position in player_by_id[player_id].positions}
        and (
            roster_qbs_all_bye
            or projection_map[(player_id, current_week_row.week)].league_points
            <= current_roster_qb_points
        )
    }
    user_team = next(
        team for team in snapshot.teams if team.roster_id == snapshot.user_roster_id
    )
    user_capacity = next(
        row
        for row in snapshot.roster_capacity
        if row.roster_id == snapshot.user_roster_id
    )
    possible_skill_drops: tuple[str | None, ...] = (
        (None,)
        if user_capacity.open_active_slots > 0
        else tuple(
            sorted(
                player_id
                for player_id in user_team.player_ids
                if player_id in skill_roster and drop_legality.get(player_id) is True
                and player_id not in drop_evidence_exclusions
            )
        )
    )
    ownership_watch_possible_candidates = {
        player_id
        for player_id in eligible_ids
        if player_id not in special_team_candidates
        and any(
            value_map[player_id].selected_value
            - (value_map[drop_id].selected_value if drop_id is not None else 0.0)
            >= policy.watch_selected_value_floor
            and value_map[player_id].market_value
            - (value_map[drop_id].market_value if drop_id is not None else 0.0)
            >= policy.watch_market_value_floor
            for drop_id in possible_skill_drops
        )
    }
    rank_dominance_candidates = {
        player_id
        for player_id in eligible_ids
        if player_id not in special_team_candidates
        and any(
            drop_id is not None
            and fresh_rank_dominates(
                value_map[player_id],
                value_map[drop_id],
                same_position=bool(
                    {position.upper() for position in player_by_id[player_id].positions}
                    & {position.upper() for position in player_by_id[drop_id].positions}
                    & {"QB", "RB", "WR", "TE"}
                ),
            )
            for drop_id in possible_skill_drops
        )
    }
    rank_projection_dominance_candidates = {
        player_id
        for player_id in eligible_ids
        if player_id not in special_team_candidates
        and any(
            drop_id is not None
            and _rank_projection_dominates(
                value_map[player_id],
                value_map[drop_id],
                same_position=bool(
                    {
                        position.upper()
                        for position in player_by_id[player_id].positions
                    }
                    & {
                        position.upper()
                        for position in player_by_id[drop_id].positions
                    }
                    & {"QB", "RB", "WR", "TE"}
                ),
            )
            and priority_by_id.get(player_id) is not None
            and priority_by_id[player_id].composite_score is not None
            and priority_by_id.get(drop_id) is not None
            and priority_by_id[drop_id].composite_score is not None
            and float(priority_by_id[player_id].composite_score or 0.0)
            - float(priority_by_id[drop_id].composite_score or 0.0)
            >= policy.priority_minimum_value_gain
            for drop_id in possible_skill_drops
        )
    }
    ownership_policy_prunable_candidates = (
        {
            player_id
            for player_id in eligible_ids
            if player_id not in special_team_candidates
            and player_id not in ownership_watch_possible_candidates
        }
        if enable_pruning
        else set()
    )
    non_lineup_priority_candidates = special_team_candidates | qb_hold_candidates
    contingency_add_candidates = {
        scenario.beneficiary_player_id
        for scenario in contingencies
        if scenario.beneficiary_player_id in eligible_ids
    }
    emerging_candidate_ids = {
        row.player_id
        for row in (emergence_evidence.players if emergence_evidence else ())
        if row.player_id in eligible_ids
        and row.classification != "EFFICIENCY_ONLY"
        and emerging_role_signal_strength(row)
        >= policy.emerging_minimum_role_signal_strength
        * (1 - policy.emerging_near_threshold_fraction)
    }
    ownership_policy_prunable_candidates -= emerging_candidate_ids
    ownership_policy_prunable_candidates -= rank_dominance_candidates
    ownership_policy_prunable_candidates -= set(scored_priority_candidates)
    must_exact_candidates = (
        set(special_team_candidates)
        | rank_dominance_candidates
        | rank_projection_dominance_candidates
        | priority_exact_candidates
        | (
            (set(qb_hold_candidates) | contingency_add_candidates | emerging_candidate_ids)
            & ownership_watch_possible_candidates
        )
        | emerging_candidate_ids
    )
    # Must-exact safety proofs take precedence over the bounded acquisition
    # score budget. Otherwise a same-position exact upgrade can be hidden by a
    # crowded higher-scoring acquisition pool.
    priority_prunable_candidates -= must_exact_candidates
    effective_pruning = enable_pruning
    raw_bounds = _candidate_upper_bounds(
        snapshot,
        candidate_ids=eligible_ids,
        roster_player_ids=skill_roster,
        weeks=ordered_weeks,
        projections=projections,
        options=options,
    )
    search_order = tuple(
        sorted(
            eligible_ids,
            key=lambda player_id: (
                player_id not in must_exact_candidates,
                -float(
                    priority_by_id[player_id].composite_score
                    if priority_by_id.get(player_id) is not None
                    and priority_by_id[player_id].composite_score is not None
                    else -1.0
                ),
                -raw_bounds[player_id],
                -value_map[player_id].selected_value,
                -value_map[player_id].market_value,
                player_id,
            ),
        )
    )
    if ownership_policy_prunable_candidates == set(eligible_ids) and search_order:
        # Preserve one exact PASS as the ranked representative when every
        # acquisition is below the necessary ownership floors.
        ownership_policy_prunable_candidates.remove(search_order[0])
    bounds = tuple(
        WaiverSearchCandidateBound(
            player_id=player_id,
            acquisition_state=acquisition_by_id[player_id].state,
            maximum_after_weighted_points=round(raw_bounds[player_id], 3),
        )
        for player_id in search_order
    )

    exact: list[WaiverEvaluation] = []
    pruned: list[WaiverSearchPruning] = []
    contingency_cache = {}
    evaluation_cache = {}
    baseline_score: float | None = None
    for index, bound in enumerate(bounds):
        if bound.player_id in priority_prunable_candidates:
            if baseline_score is None:
                baseline_score = _baseline_score(
                    snapshot,
                    roster_player_ids=skill_roster,
                    weeks=ordered_weeks,
                    projections=projections,
                    options=options,
                )
            pruned.append(
                WaiverSearchPruning(
                    player_id=bound.player_id,
                    maximum_after_weighted_points=bound.maximum_after_weighted_points,
                    incumbent_after_weighted_points=baseline_score,
                    reason=(
                        "WAIVER_VALUE_BELOW_EXACT_CUTOFF; a higher-valued active "
                        "candidate faces the same legal skill-player drop pool"
                    ),
                )
            )
            continue
        if bound.player_id in ownership_policy_prunable_candidates:
            if baseline_score is None:
                baseline_score = _baseline_score(
                    snapshot,
                    roster_player_ids=skill_roster,
                    weeks=ordered_weeks,
                    projections=projections,
                    options=options,
                )
            pruned.append(
                WaiverSearchPruning(
                    player_id=bound.player_id,
                    maximum_after_weighted_points=bound.maximum_after_weighted_points,
                    incumbent_after_weighted_points=baseline_score,
                    reason=(
                        "OWNERSHIP_UPPER_BOUND_BELOW_WATCH_FLOORS; no legal drop "
                        "can satisfy both necessary selected and market ownership gates"
                    ),
                )
            )
            continue
        if (
            effective_pruning
            and bound.player_id not in must_exact_candidates
            and exact
        ):
            ordinary_affirmative = tuple(
                row
                for row in exact
                if row.add_player_id not in must_exact_candidates
                and row.decision_label in AFFIRMATIVE_LABELS
            )
            incumbent = (
                min(ordinary_affirmative, key=_evaluation_sort_key)
                if ordinary_affirmative
                else None
            )
            if incumbent is None:
                pass
            else:
                incumbent_selected = incumbent.candidates[0]
                if raw_bounds[bound.player_id] + 1e-9 < incumbent_selected.lineup.after_weighted_points:
                    pruned.extend(
                        WaiverSearchPruning(
                            player_id=remaining.player_id,
                            maximum_after_weighted_points=remaining.maximum_after_weighted_points,
                            incumbent_after_weighted_points=(
                                incumbent_selected.lineup.after_weighted_points
                            ),
                            reason=(
                                "NO_DROP_LINEUP_BELOW_AFFIRMATIVE_INCUMBENT; the exact "
                                "no-drop upper bound cannot reach the incumbent lineup score"
                            ),
                        )
                        for remaining in bounds[index:]
                        if remaining.player_id not in must_exact_candidates
                    )
                    break
        exact.append(
            apply_waiver_policy(
                evaluate_waiver(
                    snapshot,
                    add_player_id=bound.player_id,
                    weeks=ordered_weeks,
                    projections=projections,
                    values=values,
                    drop_legality=drop_legality,
                    news_fresh=news_fresh,
                    contingencies=contingencies,
                    waiver_wire_evidence=waiver_wire_evidence,
                    waiver_priorities=priority_by_id,
                    ros_panel_evidence=ros_panel_evidence,
                    emergence_evidence=emergence_evidence,
                    input_bundle_hash=input_bundle_hash,
                    availability_source=availability_source,
                    options=options,
                    now=now,
                    contingency_cache=contingency_cache,
                    evaluation_cache=evaluation_cache,
                    drop_evidence_exclusions=drop_evidence_exclusions,
                    roster_evidence_exclusions=roster_evidence_exclusions,
                ),
                policy,
            )
        )

    ranked = tuple(sorted(exact, key=_evaluation_sort_key))
    claim_plan = _claim_plan(ranked)
    best = (
        next(
            row
            for row in ranked
            if row.add_player_id == claim_plan[0].add_player_id
            and row.selected_drop_player_id == claim_plan[0].drop_player_id
        )
        if claim_plan and claim_plan[0].drop_player_id is not None
        else ranked[0] if ranked else None
    )
    affirmative = best is not None and best.decision_label in AFFIRMATIVE_LABELS
    if best is not None:
        baseline = best.candidates[0].lineup.before_weighted_points
    else:
        baseline = _baseline_score(
            snapshot,
            roster_player_ids=skill_roster,
            weeks=ordered_weeks,
            projections=projections,
            options=options,
        )
    no_action = WaiverNoActionOption(
        after_weighted_points=baseline,
        selected=not affirmative,
        reason=(
            "An exactly evaluated move passed every affirmative Waiver gate"
            if affirmative
            else "No exactly evaluated move passed every affirmative Waiver gate"
        ),
    )
    notable_candidates = _notable_candidates(
        snapshot,
        omissions=omissions,
        pruned=pruned,
        value_map=value_map,
        drop_legality=drop_legality,
        waiver_wire_evidence=waiver_wire_evidence,
        emergence_evidence=emergence_evidence,
    )
    candidate_hash = stable_hash(
        {
            "eligible_candidate_ids": eligible_ids,
            "candidate_bounds": bounds,
            "drop_legality": tuple(sorted(drop_legality.items())),
            "omissions": omissions,
            "notable_candidates": notable_candidates,
            "claim_plan": claim_plan,
            "pruning_version": PRUNING_VERSION,
            "contingencies": contingencies,
            "emerging_candidate_ids": tuple(sorted(emerging_candidate_ids)),
            "priority_exact_candidate_ids": tuple(sorted(priority_exact_candidates)),
            "priority_prunable_candidate_ids": tuple(
                sorted(priority_prunable_candidates)
            ),
            "waiver_priority": priority_by_id,
            "ros_panel_evidence": ros_panel_evidence,
        }
    )
    value_input_hash = stable_hash(
        {
            "weeks": ordered_weeks,
            "projections": projections,
            "values": values,
            "news_fresh": tuple(sorted(news_fresh.items())),
            "contingencies": contingencies,
            "waiver_wire_evidence": waiver_wire_evidence,
            "emergence_evidence": emergence_evidence,
        }
    )
    warnings = {
        *snapshot.warnings,
        "Search pruning uses an exact no-drop lineup upper bound; every omitted "
        "bound and exact-evaluation count are preserved",
        "No FAAB bid or claim-success probability was generated",
    }
    if emergence_evidence is None:
        warnings.add("Role and volume emergence evidence was not provided")
    else:
        warnings.update(emergence_evidence.warnings)
        if not emergence_evidence.complete:
            warnings.add(
                "Role and volume emergence evidence is incomplete and fails closed"
            )
    if pruned:
        warnings.add(
            f"{len(pruned)} eligible candidate(s) were pruned by audited Waiver "
            "Value, ownership, or lineup bounds"
        )
    if enable_pruning and non_lineup_priority_candidates:
        warnings.add(
            "QB-hold and current-week-weighted K/DST candidates were evaluated "
            "exactly before ordinary skill-player pruning"
        )
    if enable_pruning and contingency_add_candidates:
        warnings.add(
            "Acquirable contingency beneficiaries were evaluated exactly before "
            "ordinary skill-player pruning"
        )
    if enable_pruning and emerging_candidate_ids:
        warnings.add(
            "Potential affirmative or WATCH emergence candidates were evaluated "
            "exactly before ordinary pruning, including every legal drop"
        )
    if enable_pruning and priority_exact_candidates:
        warnings.add(
            f"The top {len(priority_exact_candidates)} candidates by calculable "
            "Waiver Value were evaluated exactly"
        )
    if priority_prunable_candidates:
        warnings.add(
            f"{len(priority_prunable_candidates)} lower Waiver Value candidate(s) "
            "were safely pruned behind higher-valued candidates facing the same drop pool"
        )
    if ownership_policy_prunable_candidates:
        warnings.add(
            f"{len(ownership_policy_prunable_candidates)} skill-player candidate(s) "
            "were proved below both necessary WATCH ownership floors"
        )
    missing_board_roster_ids = tuple(
        sorted(
            str(player_id)
            for player_id in (
                (ros_panel_evidence or {}).get("missing_rostered_player_ids") or ()
            )
        )
    )
    if missing_board_roster_ids:
        warnings.add(
            "Active value-board rankings omitted rostered league player(s): "
            + ", ".join(missing_board_roster_ids)
            + "; only alternatives involving an uncovered user-roster player "
            "are quarantined"
        )
    missing_league_rostered_values = tuple(
        sorted(set(dict(snapshot.owner_by_player)) - set(value_map))
    )
    if missing_league_rostered_values:
        warnings.add(
            "Value evidence is unavailable for rostered league player(s): "
            + ", ".join(missing_league_rostered_values)
            + "; unrelated waiver alternatives remained eligible"
        )
    if drop_evidence_exclusions:
        warnings.add(
            f"{len(drop_evidence_exclusions)} roster player(s) with incomplete "
            "evidence were quarantined from automatic drop selection"
        )
    if roster_evidence_exclusions:
        warnings.add(
            f"{len(roster_evidence_exclusions)} roster player(s) with incomplete "
            "weekly projections were omitted from lineup calculations; affirmative "
            "skill-player labels remain blocked"
        )
    base = WaiverSearch(
        schema_version=10,
        evaluation_schema_version=15,
        product="WAIVER ASSISTANT",
        operation="COMPLETE WAIVER SEARCH",
        league_key=snapshot.league_key,
        manifest_id=snapshot.manifest.analysis_id,
        current_week=snapshot.manifest.current_week,
        horizon=tuple(row.week for row in ordered_weeks),
        policy_version=policy.version,
        policy_hash=policy.policy_hash,
        pruning_version=PRUNING_VERSION,
        pruning_enabled=effective_pruning,
        ranking_basis=(
            "Waiver decision tier, add-minus-drop Waiver Value from weekly/Waiver "
            "Wire/selected-panel ROS ranks, absolute add Waiver Value, then explanatory "
            "lineup, ownership, projection, depth, and stable-ID tie breakers; K/DST "
            "retain their separate streaming policy"
        ),
        eligible_candidate_ids=eligible_ids,
        candidate_bounds=bounds,
        exact_evaluations=ranked,
        pruned_candidates=tuple(pruned),
        omissions=omissions,
        notable_candidates=notable_candidates,
        claim_plan=claim_plan,
        best_add_player_id=best.add_player_id if best else None,
        best_drop_player_id=best.selected_drop_player_id if best else None,
        best_decision_label=best.decision_label if best else None,
        recommended_action="MOVE" if affirmative else "NO ACTION",
        no_action=no_action,
        candidate_hash=candidate_hash,
        value_input_hash=value_input_hash,
        snapshot_hash=stable_hash(snapshot),
        input_bundle_hash=input_bundle_hash,
        availability_source=availability_source,
        emergence_evidence=emergence_evidence,
        ros_panel_evidence=ros_panel_evidence,
        strongest_uncertainty=(
            best.strongest_uncertainty
            if best
            else "No proved FREE_AGENT or WAIVERS supported player is available"
        ),
        warnings=tuple(sorted(warnings)),
        sleeper_write_performed=False,
        evidence_hash="",
    )
    assert_current(snapshot, now=now)
    return replace(base, evidence_hash=stable_hash(asdict(base)))


def save_waiver_search(search: WaiverSearch, path: str | Path) -> Path:
    return atomic_write_json(path, search)


def load_waiver_search(path: str | Path) -> dict[str, object]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if int(value.get("schema_version") or 0) not in {1, 2, 3, 4, 5, 6, 7, 8, 9, 10}:
        raise ValueError("Unsupported Waiver search-evidence schema")
    if str(value.get("product") or "") != "WAIVER ASSISTANT":
        raise ValueError("Search evidence must be Waiver-scoped")
    expected = str(value.get("evidence_hash") or "")
    unsigned = dict(value)
    unsigned["evidence_hash"] = ""
    actual = stable_hash(unsigned)
    if not expected or expected != actual:
        raise ValueError("Waiver search evidence failed hash verification")
    value["current"] = False
    value["offline_replay"] = True
    value.setdefault("warnings", []).append("OFFLINE/NON-CURRENT Waiver search")
    return value
