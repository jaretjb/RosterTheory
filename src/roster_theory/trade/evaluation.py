from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, replace
from itertools import combinations
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from roster_theory.core.errors import (
    CoverageIncomplete,
    IdentityIncomplete,
    RosterIllegal,
)
from roster_theory.core.lineup import LineupPlayer, LineupResult, optimize_lineup
from roster_theory.core.models import Player, Projection
from roster_theory.core.provenance import stable_hash
from roster_theory.inseason.evaluation import (
    InSeasonContext,
    InSeasonWeek,
    OffenseExposure,
    PairExposure,
    ProjectionCell,
    RiskImpact,
    RiskProfile,
    RiskScenario,
    TeamImpact,
    WeeklyLineupImpact,
    WeeklyProjectionMatrix,
    build_weekly_projection_matrix as build_inseason_projection_matrix,
    depth_above_waiver as inseason_depth_above_waiver,
    lineup as inseason_lineup,
    plausible_unowned_players,
    risk_impact as inseason_risk_impact,
    risk_profile as inseason_risk_profile,
    team_impact as inseason_team_impact,
    weighted_lineup_score as inseason_weighted_lineup_score,
)
from roster_theory.providers.cache import atomic_write_json
from roster_theory.trade.boards import BoardPlayerValue, ValueBoard
from roster_theory.trade.snapshot import SKILL_POSITIONS, TradeSnapshot, assert_current


MAX_PACKAGE_PLAYERS_PER_TEAM = 4
MAX_SECONDARY_MOVES = 3
MAX_SECONDARY_PLAYER_POOL = 18
MAX_SECONDARY_COMBINATIONS = 1_000
STARTABLE_SKILL_SLOTS = frozenset(
    {"QB", "RB", "WR", "TE", "FLEX", "WRRB_FLEX", "REC_FLEX", "SUPER_FLEX"}
)
KNOWN_INACTIVE = frozenset({"IR", "PUP", "SUSP", "OUT"})


@dataclass(frozen=True, slots=True)
class PlayerAsset:
    player_id: str


@dataclass(frozen=True, slots=True)
class TradePackage:
    roster_a_id: str
    roster_b_id: str
    from_a: tuple[PlayerAsset, ...]
    from_b: tuple[PlayerAsset, ...]


@dataclass(frozen=True, slots=True)
class SecondaryCandidate:
    player_ids: tuple[str, ...]
    weighted_lineup_points: float

    @property
    def player_id(self) -> str | None:
        return self.player_ids[0] if len(self.player_ids) == 1 else None


@dataclass(frozen=True, slots=True)
class SecondaryMove:
    roster_id: str
    kind: str
    chosen_player_ids: tuple[str, ...]
    next_best_player_ids: tuple[str, ...]
    candidates: tuple[SecondaryCandidate, ...]
    candidate_pool_size: int = 0
    eligible_player_count: int = 0
    combinations_considered: int = 0
    search_truncated: bool = False
    manual_legality: bool = False

    @property
    def chosen_player_id(self) -> str | None:
        return self.chosen_player_ids[0] if len(self.chosen_player_ids) == 1 else None

    @property
    def next_best_player_id(self) -> str | None:
        return self.next_best_player_ids[0] if len(self.next_best_player_ids) == 1 else None


@dataclass(frozen=True, slots=True)
class PositionDiagnosis:
    position: str
    roster_player_ids: tuple[str, ...]
    starter_player_ids: tuple[str, ...]
    never_started_player_ids: tuple[str, ...]
    usable_surplus_player_ids: tuple[str, ...]
    waiver_player_id: str | None
    waiver_average_points: float
    weakest_starter_player_id: str | None
    weakest_starter_average_points: float | None
    need_above_waiver: float


@dataclass(frozen=True, slots=True)
class RosterDiagnosis:
    roster_id: str
    weekly_optimal_points: tuple[tuple[int, float], ...]
    positions: tuple[PositionDiagnosis, ...]
    bye_gap_weeks: tuple[int, ...]
    smallest_useful_change: str
    risk: RiskProfile


@dataclass(frozen=True, slots=True)
class DecisionGate:
    name: str
    actual: float | bool | None
    comparison: str
    threshold: float | bool | None
    passed: bool
    explanation: str


@dataclass(frozen=True, slots=True)
class DecisionAssessment:
    label: str
    posture: str
    policy_version: str
    gates: tuple[DecisionGate, ...]


@dataclass(frozen=True, slots=True)
class OwnershipImpact:
    roster_id: str
    selected_sent: float | None
    selected_received: float | None
    selected_package_delta: float | None
    selected_secondary_delta: float | None
    market_sent: float
    market_received: float
    market_package_delta: float
    market_secondary_delta: float
    raw_projection_sent: float
    raw_projection_received: float
    raw_projection_package_delta: float
    raw_projection_secondary_delta: float


@dataclass(frozen=True, slots=True)
class ReversalCondition:
    component: str
    condition: str
    affected_roster_id: str | None = None


@dataclass(frozen=True, slots=True)
class ProjectionCoverageIssue:
    player_id: str
    player_name: str
    scope: str
    missing_weeks: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class ProjectionCoverage:
    missing_player_count: int
    missing_player_week_count: int
    relevant_player_count: int
    relevant_player_week_count: int
    outside_player_count: int
    outside_player_week_count: int
    issues: tuple[ProjectionCoverageIssue, ...]


@dataclass(frozen=True, slots=True)
class EvaluationOptions:
    playoff_weight: float = 1.0
    allow_partial_schedule: bool = False
    allow_rank_only: bool = False
    drop_override: str | None = None
    add_override: str | None = None
    drop_overrides: tuple[str, ...] = ()
    add_overrides: tuple[str, ...] = ()
    risk_posture: str = "BALANCED"
    risk_policy_version: str = "scenario-v1"
    offense_downside_multiplier: float = 0.70
    offense_upside_multiplier: float = 1.20
    user_selected_floor: float = 0.0
    partner_market_floor: float = -5.0
    max_depth_loss: float = 25.0
    max_downside_increase: float = 5.0


@dataclass(frozen=True, slots=True)
class TradeEvaluation:
    schema_version: int
    product: str
    operation: str
    manifest_id: str
    league_key: str
    current_week: int
    horizon: tuple[int, ...]
    package: TradePackage
    resolved_players: tuple[tuple[str, str], ...]
    secondary_moves: tuple[SecondaryMove, ...]
    ownership_impacts: tuple[OwnershipImpact, ...]
    team_impacts: tuple[TeamImpact, ...]
    risk_impacts: tuple[RiskImpact, ...]
    provisional_reversal_conditions: tuple[ReversalCondition, ...]
    projection_coverage: ProjectionCoverage
    decision: DecisionAssessment | None
    modes: tuple[str, ...]
    decision_label: str | None
    summary: str
    source_times: tuple[tuple[str, str], ...]
    warnings: tuple[str, ...]
    evidence_hash: str


def _normalized_name(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip()).casefold()


def resolve_player(
    snapshot: TradeSnapshot,
    query: str,
    *,
    roster_id: str | None = None,
    require_unrostered: bool = False,
) -> Player:
    player_by_id = {player.player_id: player for player in snapshot.players}
    owner_by_player = dict(snapshot.owner_by_player)
    if query in player_by_id:
        candidates = (player_by_id[query],)
    else:
        normalized = _normalized_name(query)
        candidates = tuple(
            player
            for player in snapshot.players
            if _normalized_name(player.name) == normalized
        )
    if roster_id is not None:
        candidates = tuple(
            player
            for player in candidates
            if owner_by_player.get(player.player_id) == roster_id
        )
    if require_unrostered:
        candidates = tuple(
            player for player in candidates if player.player_id not in owner_by_player
        )
    if not candidates:
        qualifier = "unrostered " if require_unrostered else ""
        raise IdentityIncomplete(f"No exact {qualifier}player match for {query!r}")
    if len(candidates) > 1:
        raise IdentityIncomplete(f"Ambiguous exact player name {query!r}")
    return candidates[0]


def build_entered_package(
    snapshot: TradeSnapshot,
    *,
    send: Sequence[str],
    receive: Sequence[str],
) -> TradePackage:
    assert_current(snapshot)
    if not (
        1 <= len(send) <= MAX_PACKAGE_PLAYERS_PER_TEAM
        and 1 <= len(receive) <= MAX_PACKAGE_PLAYERS_PER_TEAM
    ):
        raise RosterIllegal(
            "Supported packages require one through four players from each team"
        )
    sent = tuple(
        resolve_player(snapshot, query, roster_id=snapshot.user_roster_id)
        for query in send
    )
    received = tuple(resolve_player(snapshot, query) for query in receive)
    owner_by_player = dict(snapshot.owner_by_player)
    partner_ids = {owner_by_player.get(player.player_id) for player in received}
    if None in partner_ids or len(partner_ids) != 1:
        raise RosterIllegal("All received players must belong to one opponent")
    partner_id = str(next(iter(partner_ids)))
    package = TradePackage(
        roster_a_id=snapshot.user_roster_id,
        roster_b_id=partner_id,
        from_a=tuple(PlayerAsset(player.player_id) for player in sent),
        from_b=tuple(PlayerAsset(player.player_id) for player in received),
    )
    validate_package(snapshot, package)
    return package


def validate_package(snapshot: TradeSnapshot, package: TradePackage) -> None:
    if package.roster_a_id == package.roster_b_id:
        raise RosterIllegal("A trade requires two different rosters")
    roster_ids = {team.roster_id for team in snapshot.teams}
    if package.roster_a_id not in roster_ids or package.roster_b_id not in roster_ids:
        raise RosterIllegal("Trade package references an unknown roster")
    if not (
        1 <= len(package.from_a) <= MAX_PACKAGE_PLAYERS_PER_TEAM
        and 1 <= len(package.from_b) <= MAX_PACKAGE_PLAYERS_PER_TEAM
    ):
        raise RosterIllegal(
            "Supported packages require one through four players from each team"
        )
    ids = tuple(asset.player_id for asset in (*package.from_a, *package.from_b))
    if len(ids) != len(set(ids)):
        raise RosterIllegal("A player may appear only once in a trade package")
    player_by_id = {player.player_id: player for player in snapshot.players}
    owner_by_player = dict(snapshot.owner_by_player)
    for asset in package.from_a:
        if asset.player_id not in player_by_id:
            raise IdentityIncomplete(f"Unknown trade asset {asset.player_id}")
        if owner_by_player.get(asset.player_id) != package.roster_a_id:
            raise RosterIllegal(f"{asset.player_id} is not owned by roster {package.roster_a_id}")
    for asset in package.from_b:
        if asset.player_id not in player_by_id:
            raise IdentityIncomplete(f"Unknown trade asset {asset.player_id}")
        if owner_by_player.get(asset.player_id) != package.roster_b_id:
            raise RosterIllegal(f"{asset.player_id} is not owned by roster {package.roster_b_id}")


def build_weekly_projection_matrix(
    snapshot: TradeSnapshot,
    projections: Sequence[Projection],
) -> WeeklyProjectionMatrix:
    return build_inseason_projection_matrix(_inseason_context(snapshot), projections)


def _inseason_context(snapshot: TradeSnapshot) -> InSeasonContext:
    return InSeasonContext(
        players=snapshot.players,
        roster_positions=snapshot.league.roster_positions,
        weeks=tuple(
            InSeasonWeek(week.week, week.playoff, week.bye_teams)
            for week in snapshot.weeks
        ),
        unowned_player_ids=snapshot.free_agent_ids,
    )


def _lineup_slots(snapshot: TradeSnapshot) -> tuple[str, ...]:
    return tuple(
        position
        for position in snapshot.league.roster_positions
        if position.upper() in STARTABLE_SKILL_SLOTS
    )


def _lineup(
    snapshot: TradeSnapshot,
    matrix: WeeklyProjectionMatrix,
    roster: Iterable[str],
    week: int,
    *,
    allow_partial: bool,
) -> LineupResult:
    return inseason_lineup(
        _inseason_context(snapshot),
        matrix,
        roster,
        week,
        allow_partial=allow_partial,
    )


def _weighted_lineup_score(
    snapshot: TradeSnapshot,
    matrix: WeeklyProjectionMatrix,
    roster: Iterable[str],
    options: EvaluationOptions,
) -> float:
    return inseason_weighted_lineup_score(
        _inseason_context(snapshot), matrix, roster, options
    )


def _plausible_free_agents(
    snapshot: TradeSnapshot,
    matrix: WeeklyProjectionMatrix,
    *,
    per_position_week: int = 5,
    allowed_player_ids: set[str] | None = None,
) -> tuple[str, ...]:
    return plausible_unowned_players(
        _inseason_context(snapshot),
        matrix,
        per_position_week=per_position_week,
        allowed_player_ids=allowed_player_ids,
    )


def _requested_secondary_overrides(
    options: EvaluationOptions,
    *,
    dropping: bool,
) -> tuple[str, ...]:
    plural = options.drop_overrides if dropping else options.add_overrides
    singular = options.drop_override if dropping else options.add_override
    values = tuple(plural)
    if singular is not None and singular not in values:
        values = (*values, singular)
    if len(values) != len(set(values)):
        kind = "drop" if dropping else "add"
        raise RosterIllegal(f"Explicit {kind} overrides contain a duplicate player")
    return values


def _secondary_move(
    snapshot: TradeSnapshot,
    matrix: WeeklyProjectionMatrix,
    roster_id: str,
    roster: set[str],
    target_count: int,
    options: EvaluationOptions,
    unavailable_free_agents: set[str],
    valued_player_ids: set[str],
    lineup_available: bool,
) -> tuple[set[str], SecondaryMove]:
    delta = len(roster) - target_count
    required = abs(delta)
    if required > MAX_SECONDARY_MOVES:
        raise RosterIllegal(
            f"Supported packages may require at most {MAX_SECONDARY_MOVES} secondary moves"
        )
    if delta == 0:
        return roster, SecondaryMove(roster_id, "NONE", (), (), ())

    dropping = delta > 0
    kind = "DROP" if dropping else "ADD"
    overrides = _requested_secondary_overrides(options, dropping=dropping)
    if len(overrides) > required:
        raise RosterIllegal(
            f"Roster {roster_id} requires {required} {kind.lower()}(s), but "
            f"{len(overrides)} overrides were supplied"
        )

    if dropping:
        eligible = tuple(sorted(roster))
        automatic_candidates = eligible
    else:
        eligible = tuple(
            sorted(
                player_id
                for player_id in snapshot.free_agent_ids
                if player_id in valued_player_ids
                and player_id not in unavailable_free_agents
                and player_id not in roster
            )
        )
        automatic_candidates = _plausible_free_agents(
            snapshot,
            matrix,
            allowed_player_ids=set(eligible),
        )

    ineligible_overrides = tuple(player_id for player_id in overrides if player_id not in eligible)
    if ineligible_overrides:
        raise RosterIllegal(
            f"Explicit {kind.lower()} override is not eligible for roster {roster_id}: "
            + ", ".join(ineligible_overrides)
        )
    if not lineup_available:
        if len(overrides) != required:
            raise CoverageIncomplete(
                f"Rank-only unequal packages require exactly {required} explicit "
                f"{kind.lower()} override(s) for roster {roster_id}"
            )
        candidate_sets = (tuple(sorted(overrides)),)
        pool_size = len(overrides)
        eligible_count = len(eligible)
        search_truncated = False
    else:
        if len(automatic_candidates) < required - len(overrides):
            raise RosterIllegal(
                f"No eligible player combination exists for {required} required "
                f"{kind.lower()} moves"
            )
        individually_scored: list[tuple[float, str]] = []
        for player_id in automatic_candidates:
            candidate_roster = set(roster)
            if dropping:
                candidate_roster.remove(player_id)
            else:
                candidate_roster.add(player_id)
            individually_scored.append(
                (
                    _weighted_lineup_score(snapshot, matrix, candidate_roster, options),
                    player_id,
                )
            )
        ranked_players = tuple(
            player_id
            for _, player_id in sorted(
                individually_scored,
                key=lambda row: (-row[0], row[1]),
            )
        )
        bounded_pool = tuple(
            dict.fromkeys((*overrides, *ranked_players[:MAX_SECONDARY_PLAYER_POOL]))
        )
        remaining_pool = tuple(
            player_id for player_id in bounded_pool if player_id not in overrides
        )
        choose_count = required - len(overrides)
        candidate_sets_list: list[tuple[str, ...]] = []
        combination_truncated = False
        for extra in combinations(remaining_pool, choose_count):
            if len(candidate_sets_list) >= MAX_SECONDARY_COMBINATIONS:
                combination_truncated = True
                break
            candidate_sets_list.append(tuple(sorted((*overrides, *extra))))
        candidate_sets = tuple(candidate_sets_list)
        pool_size = len(bounded_pool)
        eligible_count = len(automatic_candidates)
        search_truncated = (
            len(ranked_players) > MAX_SECONDARY_PLAYER_POOL or combination_truncated
        )

    if not candidate_sets:
        raise RosterIllegal("No eligible player combination exists for the required secondary moves")
    scored: list[SecondaryCandidate] = []
    for player_ids in candidate_sets:
        candidate_roster = set(roster)
        if dropping:
            candidate_roster.difference_update(player_ids)
        else:
            candidate_roster.update(player_ids)
        score = (
            _weighted_lineup_score(snapshot, matrix, candidate_roster, options)
            if lineup_available
            else 0.0
        )
        scored.append(SecondaryCandidate(player_ids, score))
    ordered = tuple(
        sorted(scored, key=lambda row: (-row.weighted_lineup_points, row.player_ids))
    )
    chosen = ordered[0].player_ids
    final_roster = set(roster)
    if dropping:
        final_roster.difference_update(chosen)
    else:
        final_roster.update(chosen)
    return final_roster, SecondaryMove(
        roster_id=roster_id,
        kind=kind,
        chosen_player_ids=chosen,
        next_best_player_ids=ordered[1].player_ids if len(ordered) > 1 else (),
        candidates=ordered,
        candidate_pool_size=pool_size,
        eligible_player_count=eligible_count,
        combinations_considered=len(ordered),
        search_truncated=search_truncated,
    )


def _depth_above_waiver(
    snapshot: TradeSnapshot,
    matrix: WeeklyProjectionMatrix,
    roster: set[str],
    options: EvaluationOptions,
) -> float:
    return inseason_depth_above_waiver(
        _inseason_context(snapshot), matrix, roster, options
    )


def _team_impact(
    snapshot: TradeSnapshot,
    matrix: WeeklyProjectionMatrix,
    roster_id: str,
    before: set[str],
    after: set[str],
    options: EvaluationOptions,
) -> TeamImpact:
    return inseason_team_impact(
        _inseason_context(snapshot), matrix, roster_id, before, after, options
    )


def _scenario_score(
    snapshot: TradeSnapshot,
    matrix: WeeklyProjectionMatrix,
    roster: set[str],
    options: EvaluationOptions,
    multipliers: Mapping[str, float],
) -> float:
    player_by_id = {player.player_id: player for player in snapshot.players}
    total = 0.0
    for week in snapshot.weeks:
        roster_ids = tuple(sorted(player_id for player_id in roster if player_id in player_by_id))
        missing = tuple(
            player_id
            for player_id in roster_ids
            if (cell := matrix.cell(player_id, week.week)) is None or cell.points is None
        )
        if missing and not options.allow_partial_schedule:
            raise CoverageIncomplete(
                f"Week {week.week} projections missing for evaluated roster: "
                + ", ".join(missing)
            )
        points = {
            player_id: float(cell.points) * float(multipliers.get(player_id, 1.0))
            for player_id in roster_ids
            if (cell := matrix.cell(player_id, week.week)) is not None and cell.points is not None
        }
        lineup = optimize_lineup(
            tuple(
                LineupPlayer(player_id, player_by_id[player_id].positions)
                for player_id in roster_ids
            ),
            _lineup_slots(snapshot),
            points,
        )
        total += lineup.score * (options.playoff_weight if week.playoff else 1.0)
    return round(total, 3)


def _pair_type(player_a: Player, player_b: Player) -> str:
    positions_a = set(player_a.positions)
    positions_b = set(player_b.positions)
    if "QB" in positions_a or "QB" in positions_b:
        return "QB_PASS_CATCHER" if ({"WR", "TE"} & (positions_a | positions_b)) else "QB_TEAMMATE"
    if "RB" in positions_a and "RB" in positions_b:
        return "BACKFIELD"
    if "RB" in positions_a or "RB" in positions_b:
        return "RB_PASS_CATCHER" if ({"WR", "TE"} & (positions_a | positions_b)) else "SAME_OFFENSE"
    if {"WR", "TE"} & positions_a and {"WR", "TE"} & positions_b:
        return "PASS_CATCHER_PAIR"
    return "SAME_OFFENSE"


def _risk_profile(
    snapshot: TradeSnapshot,
    matrix: WeeklyProjectionMatrix,
    roster_id: str,
    roster: set[str],
    options: EvaluationOptions,
) -> RiskProfile:
    return inseason_risk_profile(
        _inseason_context(snapshot), matrix, roster_id, roster, options
    )


def _risk_impact(
    snapshot: TradeSnapshot,
    matrix: WeeklyProjectionMatrix,
    roster_id: str,
    before: set[str],
    after: set[str],
    options: EvaluationOptions,
) -> RiskImpact:
    return inseason_risk_impact(
        _inseason_context(snapshot), matrix, roster_id, before, after, options
    )


def diagnose_roster(
    snapshot: TradeSnapshot,
    projections: Sequence[Projection],
    *,
    roster_id: str | None = None,
    options: EvaluationOptions = EvaluationOptions(),
    projection_matrix: WeeklyProjectionMatrix | None = None,
) -> RosterDiagnosis:
    assert_current(snapshot)
    target_id = roster_id or snapshot.user_roster_id
    team_by_id = {team.roster_id: team for team in snapshot.teams}
    if target_id not in team_by_id:
        raise RosterIllegal(f"Unknown roster {target_id}")
    matrix = projection_matrix or build_weekly_projection_matrix(snapshot, projections)
    team = team_by_id[target_id]
    roster = set(team.player_ids) - set(team.reserve_ids)
    player_by_id = {player.player_id: player for player in snapshot.players}
    lineups = {
        week.week: _lineup(
            snapshot,
            matrix,
            roster,
            week.week,
            allow_partial=options.allow_partial_schedule,
        )
        for week in snapshot.weeks
    }
    starter_ids = {
        assignment.player_id for lineup in lineups.values() for assignment in lineup.assignments
    }

    def average_points(player_id: str) -> float:
        values = tuple(
            float(cell.points)
            for week in snapshot.weeks
            if (cell := matrix.cell(player_id, week.week)) is not None
            and cell.points is not None
        )
        return sum(values) / len(values) if values else 0.0

    position_rows: list[PositionDiagnosis] = []
    for position in sorted(SKILL_POSITIONS):
        roster_position_ids = tuple(
            sorted(
                player_id
                for player_id in roster
                if (player := player_by_id.get(player_id)) is not None
                and position in player.positions
            )
        )
        if not roster_position_ids:
            continue
        position_starters = tuple(
            player_id for player_id in roster_position_ids if player_id in starter_ids
        )
        never_started = tuple(
            player_id for player_id in roster_position_ids if player_id not in starter_ids
        )
        waiver_candidates = tuple(
            player_id
            for player_id in snapshot.free_agent_ids
            if (player := player_by_id.get(player_id)) is not None
            and position in player.positions
            and any(
                (cell := matrix.cell(player_id, week.week)) is not None
                and cell.points is not None
                for week in snapshot.weeks
            )
        )
        waiver_id = max(
            waiver_candidates,
            key=lambda player_id: (average_points(player_id), player_id),
            default=None,
        )
        waiver_average = average_points(waiver_id) if waiver_id else 0.0
        weakest_id = min(
            position_starters,
            key=lambda player_id: (average_points(player_id), player_id),
            default=None,
        )
        weakest_average = average_points(weakest_id) if weakest_id else None
        usable_surplus = tuple(
            player_id
            for player_id in never_started
            if average_points(player_id) > waiver_average
        )
        position_rows.append(
            PositionDiagnosis(
                position=position,
                roster_player_ids=roster_position_ids,
                starter_player_ids=position_starters,
                never_started_player_ids=never_started,
                usable_surplus_player_ids=usable_surplus,
                waiver_player_id=waiver_id,
                waiver_average_points=round(waiver_average, 3),
                weakest_starter_player_id=weakest_id,
                weakest_starter_average_points=(
                    round(weakest_average, 3) if weakest_average is not None else None
                ),
                need_above_waiver=round(
                    max(0.0, waiver_average - (weakest_average or 0.0)), 3
                ),
            )
        )
    bye_gaps = tuple(
        week.week
        for week in snapshot.weeks
        if any(
            (cell := matrix.cell(assignment.player_id, week.week)) is not None
            and cell.availability == "BYE"
            for assignment in lineups[week.week].assignments
        )
    )
    needs = tuple(
        row for row in position_rows if row.need_above_waiver > 0.0
    )
    if needs:
        strongest_need = max(needs, key=lambda row: (row.need_above_waiver, row.position))
        weakest_name = player_by_id[strongest_need.weakest_starter_player_id].name
        waiver_name = (
            player_by_id[strongest_need.waiver_player_id].name
            if strongest_need.waiver_player_id
            else "the waiver baseline"
        )
        smallest_change = (
            f"Improve {strongest_need.position}: {weakest_name} trails "
            f"{waiver_name} by {strongest_need.need_above_waiver:.2f} average weekly points"
        )
    elif bye_gaps:
        smallest_change = "Add targeted bye coverage for Week " + ", ".join(map(str, bye_gaps))
    else:
        smallest_change = "No waiver-level starting upgrade is identified"
    return RosterDiagnosis(
        roster_id=target_id,
        weekly_optimal_points=tuple(
            (week, round(lineup.score, 3)) for week, lineup in sorted(lineups.items())
        ),
        positions=tuple(position_rows),
        bye_gap_weeks=bye_gaps,
        smallest_useful_change=smallest_change,
        risk=_risk_profile(snapshot, matrix, target_id, roster, options),
    )


def _board_map(board: ValueBoard | None) -> dict[str, BoardPlayerValue]:
    return {row.player_id: row for row in board.players} if board is not None else {}


def _sum_field(
    player_ids: Iterable[str],
    values: Mapping[str, BoardPlayerValue],
    field: str,
) -> float:
    missing = sorted(set(player_ids) - set(values))
    if missing:
        raise CoverageIncomplete("Value board misses package player(s): " + ", ".join(missing))
    return round(sum(float(getattr(values[player_id], field)) for player_id in player_ids), 3)


def _ownership_impact(
    roster_id: str,
    sent: tuple[str, ...],
    received: tuple[str, ...],
    move: SecondaryMove,
    selected: ValueBoard | None,
    market: ValueBoard,
) -> OwnershipImpact:
    def rounded(value: float) -> float:
        result = round(float(value), 3)
        return 0.0 if result == 0.0 else result

    selected_values = _board_map(selected)
    market_values = _board_map(market)
    selected_sent = (
        _sum_field(sent, selected_values, "reconciled_vorp") if selected is not None else None
    )
    selected_received = (
        _sum_field(received, selected_values, "reconciled_vorp")
        if selected is not None
        else None
    )
    market_sent = _sum_field(sent, market_values, "reconciled_vorp")
    market_received = _sum_field(received, market_values, "reconciled_vorp")
    raw_sent = _sum_field(sent, market_values, "raw_projection")
    raw_received = _sum_field(received, market_values, "raw_projection")
    secondary_sign = 1.0 if move.kind == "ADD" else -1.0 if move.kind == "DROP" else 0.0
    secondary_players = move.chosen_player_ids
    if secondary_players:
        missing_market_players = tuple(
            player_id for player_id in secondary_players if player_id not in market_values
        )
        missing_selected_players = tuple(
            player_id
            for player_id in secondary_players
            if selected is not None and player_id not in selected_values
        )
        missing_market = bool(missing_market_players)
        missing_selected = bool(missing_selected_players)
        if missing_market or missing_selected:
            missing_boards = ", ".join(
                name
                for name, missing in (
                    ("market", missing_market),
                    ("selected", missing_selected),
                )
                if missing
            )
            raise CoverageIncomplete(
                f"{missing_boards.capitalize()} value board misses secondary player(s): "
                + ", ".join((*missing_market_players, *missing_selected_players))
            )
    selected_secondary = (
        secondary_sign
        * sum(
            max(0.0, selected_values[player_id].reconciled_vorp)
            for player_id in secondary_players
        )
        if selected is not None and secondary_players
        else 0.0 if selected is not None else None
    )
    market_secondary = (
        secondary_sign
        * sum(
            max(0.0, market_values[player_id].reconciled_vorp)
            for player_id in secondary_players
        )
        if secondary_players
        else 0.0
    )
    raw_secondary = (
        secondary_sign
        * sum(market_values[player_id].raw_projection for player_id in secondary_players)
        if secondary_players
        else 0.0
    )
    return OwnershipImpact(
        roster_id=roster_id,
        selected_sent=selected_sent,
        selected_received=selected_received,
        selected_package_delta=(
            rounded(float(selected_received) - float(selected_sent))
            if selected is not None
            else None
        ),
        selected_secondary_delta=(
            rounded(float(selected_secondary)) if selected_secondary is not None else None
        ),
        market_sent=market_sent,
        market_received=market_received,
        market_package_delta=rounded(market_received - market_sent),
        market_secondary_delta=rounded(market_secondary),
        raw_projection_sent=raw_sent,
        raw_projection_received=raw_received,
        raw_projection_package_delta=rounded(raw_received - raw_sent),
        raw_projection_secondary_delta=rounded(raw_secondary),
    )


def _decision_assessment(
    impacts: Sequence[TeamImpact],
    risk_impacts: Sequence[RiskImpact],
    ownership: Sequence[OwnershipImpact],
    modes: Sequence[str],
    options: EvaluationOptions,
) -> DecisionAssessment | None:
    if not impacts or not risk_impacts or len(ownership) != 2:
        return None
    user_impact, partner_impact = impacts
    user_risk = risk_impacts[0]
    user_value, partner_value = ownership
    user_selected_total = (
        user_value.selected_package_delta + user_value.selected_secondary_delta
        if user_value.selected_package_delta is not None
        and user_value.selected_secondary_delta is not None
        else None
    )
    partner_market_total = (
        partner_value.market_package_delta + partner_value.market_secondary_delta
    )
    blocking_modes = {"RANK-ONLY", "SCHEDULE-PARTIAL", "MANUAL-LEGALITY"}
    complete = not bool(blocking_modes.intersection(modes)) and user_selected_total is not None
    gates = (
        DecisionGate(
            "complete_evidence",
            complete,
            "==",
            True,
            complete,
            "Current ownership, weekly lineup, legality, and selected-value evidence must be complete",
        ),
        DecisionGate(
            "user_expected_lineup_delta",
            user_impact.weighted_delta,
            ">=",
            0.0,
            user_impact.weighted_delta >= 0.0,
            "Expected points remain the default objective",
        ),
        DecisionGate(
            "user_selected_value_delta",
            user_selected_total,
            ">=",
            options.user_selected_floor,
            user_selected_total is not None
            and user_selected_total >= options.user_selected_floor,
            "The package plus required roster move must clear selected-model value",
        ),
        DecisionGate(
            "user_depth_delta",
            user_impact.depth_delta,
            ">=",
            -options.max_depth_loss,
            user_impact.depth_delta >= -options.max_depth_loss,
            f"{options.risk_posture.upper()} posture limits loss of usable depth",
        ),
        DecisionGate(
            "user_offense_downside_increase",
            user_risk.offense_downside_loss_delta,
            "<=",
            options.max_downside_increase,
            user_risk.offense_downside_loss_delta <= options.max_downside_increase,
            f"{options.risk_posture.upper()} posture limits added offense-wide downside",
        ),
        DecisionGate(
            "partner_market_delta",
            partner_market_total,
            ">=",
            options.partner_market_floor,
            partner_market_total >= options.partner_market_floor,
            "The partner must be near-neutral by market value before preference is inferred",
        ),
    )
    if all(gate.passed for gate in gates):
        label = "ACCEPTABLE"
    elif not complete:
        label = "DECLINE"
    elif (
        user_impact.weighted_delta < 0.0
        and (user_selected_total is None or user_selected_total < options.user_selected_floor)
    ) or (
        user_selected_total is not None
        and user_selected_total < options.user_selected_floor - 10.0
    ) or user_impact.depth_delta < -(options.max_depth_loss * 2.0):
        label = "DECLINE"
    else:
        label = "COUNTER"
    return DecisionAssessment(
        label=label,
        posture=options.risk_posture.upper(),
        policy_version=options.risk_policy_version,
        gates=gates,
    )


def _reversal_conditions(
    snapshot: TradeSnapshot,
    package: TradePackage,
    impacts: Sequence[TeamImpact],
    ownership: Sequence[OwnershipImpact],
    moves: Sequence[SecondaryMove],
    warnings: Sequence[str],
) -> tuple[ReversalCondition, ...]:
    result: list[ReversalCondition] = []
    player_by_id = {player.player_id: player for player in snapshot.players}
    for asset in (*package.from_a, *package.from_b):
        player = player_by_id.get(asset.player_id)
        if player is not None and player.injury_status:
            result.append(
                ReversalCondition(
                    "availability",
                    f"Result may change if {player.name}'s current "
                    f"{player.injury_status} status changes",
                )
            )
    if any("missing" in warning.casefold() for warning in warnings):
        result.append(
            ReversalCondition(
                "coverage",
                "Weekly result may change when missing projections become available",
            )
        )
    for move in moves:
        if move.kind != "NONE" and move.chosen_player_ids:
            names = tuple(
                player_by_id[player_id].name
                if player_id in player_by_id
                else player_id
                for player_id in move.chosen_player_ids
            )
            result.append(
                ReversalCondition(
                    "secondary_move",
                    f"Result depends on the {move.kind.lower()} move set: "
                    + ", ".join(names),
                    move.roster_id,
                )
            )
    for impact, value in zip(impacts, ownership):
        if (
            value.selected_package_delta is not None
            and value.selected_package_delta * value.market_package_delta < 0
        ):
            result.append(
                ReversalCondition(
                    "model_disagreement",
                    "Selected and market ownership-value deltas have opposite signs",
                    impact.roster_id,
                )
            )
        if impact.weighted_delta * impact.playoff_delta < 0:
            result.append(
                ReversalCondition(
                    "playoff_sensitivity",
                    "Playoff-week impact has the opposite sign from the full horizon",
                    impact.roster_id,
                )
            )
    return tuple(result)


def _projection_coverage(
    snapshot: TradeSnapshot,
    matrix: WeeklyProjectionMatrix,
    package: TradePackage,
    moves: Sequence[SecondaryMove],
    evaluated_rosters: Sequence[set[str]],
) -> ProjectionCoverage:
    player_by_id = {player.player_id: player for player in snapshot.players}
    package_ids = {
        asset.player_id for asset in (*package.from_a, *package.from_b)
    }
    chosen_ids = {
        player_id for move in moves for player_id in move.chosen_player_ids
    }
    alternative_ids = {
        player_id for move in moves for player_id in move.next_best_player_ids
    }
    roster_ids = set().union(*evaluated_rosters)
    issues: list[ProjectionCoverageIssue] = []
    for player in snapshot.players:
        if not SKILL_POSITIONS.intersection(player.positions):
            continue
        missing_weeks = tuple(
            week.week
            for week in snapshot.weeks
            if (cell := matrix.cell(player.player_id, week.week)) is None
            or cell.points is None
        )
        if not missing_weeks:
            continue
        if player.player_id in package_ids:
            scope = "PACKAGE"
        elif player.player_id in chosen_ids:
            scope = "SECONDARY_MOVE"
        elif player.player_id in alternative_ids:
            scope = "SECONDARY_ALTERNATIVE"
        elif player.player_id in roster_ids:
            scope = "EVALUATED_ROSTER"
        else:
            scope = "OUTSIDE_EVALUATION"
        issues.append(
            ProjectionCoverageIssue(
                player_id=player.player_id,
                player_name=player.name,
                scope=scope,
                missing_weeks=missing_weeks,
            )
        )
    ordered = tuple(sorted(issues, key=lambda row: (row.scope, row.player_id)))
    relevant = tuple(row for row in ordered if row.scope != "OUTSIDE_EVALUATION")
    outside = tuple(row for row in ordered if row.scope == "OUTSIDE_EVALUATION")
    return ProjectionCoverage(
        missing_player_count=len(ordered),
        missing_player_week_count=sum(len(row.missing_weeks) for row in ordered),
        relevant_player_count=len(relevant),
        relevant_player_week_count=sum(len(row.missing_weeks) for row in relevant),
        outside_player_count=len(outside),
        outside_player_week_count=sum(len(row.missing_weeks) for row in outside),
        issues=ordered,
    )


def evaluate_trade(
    snapshot: TradeSnapshot,
    package: TradePackage,
    *,
    projections: Sequence[Projection],
    selected_board: ValueBoard | None,
    market_board: ValueBoard,
    options: EvaluationOptions = EvaluationOptions(),
    projection_matrix: WeeklyProjectionMatrix | None = None,
) -> TradeEvaluation:
    assert_current(snapshot)
    validate_package(snapshot, package)
    if options.playoff_weight <= 0:
        raise ValueError("playoff_weight must be positive")
    if options.risk_posture.upper() not in {"CONSERVATIVE", "BALANCED", "CEILING"}:
        raise ValueError("risk_posture must be CONSERVATIVE, BALANCED, or CEILING")
    if not 0.0 <= options.offense_downside_multiplier < 1.0:
        raise ValueError("offense_downside_multiplier must be at least 0 and below 1")
    if options.offense_upside_multiplier <= 1.0:
        raise ValueError("offense_upside_multiplier must be above 1")
    if not market_board.complete:
        raise CoverageIncomplete("Market ownership board is incomplete")
    if market_board.horizon != snapshot.ranking_horizon:
        raise CoverageIncomplete("Market ownership board does not match snapshot horizon")
    if selected_board is not None and selected_board.horizon != market_board.horizon:
        raise CoverageIncomplete("Selected and market ownership boards use different horizons")
    matrix = projection_matrix or build_weekly_projection_matrix(snapshot, projections)
    modes: list[str] = []
    warnings: list[str] = list(snapshot.warnings)
    if selected_board is not None and not selected_board.complete:
        selected_board = None
        warnings.append("Selected-expert board is incomplete")
    if selected_board is None:
        modes.append("ECR-ONLY")
        warnings.append("Selected-expert board unavailable; valuation-gap claims disabled")
    if not projections:
        if not options.allow_rank_only:
            raise CoverageIncomplete("Weekly projections are required for lineup impact")
        modes.append("RANK-ONLY")
        warnings.append("Rank-only: projected weekly and lineup effects are unavailable")
    team_by_id = {team.roster_id: team for team in snapshot.teams}
    team_a = team_by_id[package.roster_a_id]
    team_b = team_by_id[package.roster_b_id]
    evaluated_player_ids = {player.player_id for player in snapshot.players}
    before_a = (set(team_a.player_ids) & evaluated_player_ids) - set(team_a.reserve_ids)
    before_b = (set(team_b.player_ids) & evaluated_player_ids) - set(team_b.reserve_ids)
    sent_a = tuple(asset.player_id for asset in package.from_a)
    sent_b = tuple(asset.player_id for asset in package.from_b)
    after_exchange_a = (before_a - set(sent_a)) | set(sent_b)
    after_exchange_b = (before_b - set(sent_b)) | set(sent_a)
    reserve_assets = (set(sent_a) & set(team_a.reserve_ids)) | (
        set(sent_b) & set(team_b.reserve_ids)
    )
    if reserve_assets:
        modes.append("MANUAL-LEGALITY")
        warnings.append("A traded reserve player requires a manual Sleeper legality check")

    unavailable = set(sent_a) | set(sent_b)
    valued_player_ids = {row.player_id for row in market_board.players}
    final_a, move_a = _secondary_move(
        snapshot,
        matrix,
        package.roster_a_id,
        after_exchange_a,
        len(before_a),
        options,
        unavailable,
        valued_player_ids,
        bool(projections),
    )
    unavailable.update(final_a)
    final_b, move_b = _secondary_move(
        snapshot,
        matrix,
        package.roster_b_id,
        after_exchange_b,
        len(before_b),
        options,
        unavailable,
        valued_player_ids,
        bool(projections),
    )
    moves = (move_a, move_b)
    if reserve_assets:
        moves = tuple(replace(move, manual_legality=True) for move in moves)
    if any(move.search_truncated for move in moves):
        modes.append("BOUNDED-SECONDARY-SEARCH")
        warnings.append(
            "Secondary add/drop search used the documented deterministic candidate bound"
        )

    if projections:
        projection_coverage = _projection_coverage(
            snapshot,
            matrix,
            package,
            moves,
            (before_a, before_b, final_a, final_b),
        )
        relevant_issues = tuple(
            row
            for row in projection_coverage.issues
            if row.scope != "OUTSIDE_EVALUATION"
        )
        if relevant_issues and not options.allow_partial_schedule:
            raise CoverageIncomplete(
                "Weekly projections missing for evaluated players: "
                + "; ".join(
                    f"{row.player_name} ({row.scope}) Weeks "
                    + ",".join(str(week) for week in row.missing_weeks)
                    for row in relevant_issues
                )
            )
        if relevant_issues:
            modes.append("SCHEDULE-PARTIAL")
            warnings.extend(
                f"{row.player_name} ({row.scope}) is missing projection data for Weeks "
                + ", ".join(str(week) for week in row.missing_weeks)
                for row in relevant_issues
            )
    else:
        projection_coverage = ProjectionCoverage(0, 0, 0, 0, 0, 0, ())

    impacts = (
        _team_impact(snapshot, matrix, package.roster_a_id, before_a, final_a, options),
        _team_impact(snapshot, matrix, package.roster_b_id, before_b, final_b, options),
    ) if projections else ()
    risk_impacts = (
        _risk_impact(snapshot, matrix, package.roster_a_id, before_a, final_a, options),
        _risk_impact(snapshot, matrix, package.roster_b_id, before_b, final_b, options),
    ) if projections else ()
    if risk_impacts:
        modes.append("SCENARIO-ONLY-RISK")
    ownership = (
        _ownership_impact(
            package.roster_a_id,
            sent_a,
            sent_b,
            move_a,
            selected_board,
            market_board,
        ),
        _ownership_impact(
            package.roster_b_id,
            sent_b,
            sent_a,
            move_b,
            selected_board,
            market_board,
        ),
    )
    decision = _decision_assessment(impacts, risk_impacts, ownership, modes, options)
    if impacts:
        summary = (
            f"Roster {package.roster_a_id} changes projected starter points by "
            f"{impacts[0].weighted_delta:+.2f}; roster {package.roster_b_id} changes by "
            f"{impacts[1].weighted_delta:+.2f}. "
            + (
                f"Decision: {decision.label}."
                if decision is not None
                else "No decision label is available."
            )
        )
    else:
        summary = "Ownership values are shown without projected lineup impact; no decision label is applied."
    source_times = tuple(
        sorted(
            {
                (f"{stamp.source}:{stamp.endpoint}", stamp.captured_at.isoformat())
                for stamp in (
                    *snapshot.stamps,
                    *market_board.stamps,
                    *(selected_board.stamps if selected_board is not None else ()),
                )
            }
        )
    )
    described_player_ids = {
        *sent_a,
        *sent_b,
        *(
            player_id
            for move in moves
            for player_id in (*move.chosen_player_ids, *move.next_best_player_ids)
        ),
    }
    base = TradeEvaluation(
        schema_version=4,
        product="TRADE ASSISTANT",
        operation="ENTERED PACKAGE EVALUATION",
        manifest_id=snapshot.manifest.analysis_id,
        league_key=snapshot.league_key,
        current_week=snapshot.manifest.current_week,
        horizon=tuple(week.week for week in snapshot.weeks),
        package=package,
        resolved_players=tuple(
            sorted(
                (player.player_id, player.name)
                for player in snapshot.players
                if player.player_id in described_player_ids
            )
        ),
        secondary_moves=moves,
        ownership_impacts=ownership,
        team_impacts=impacts,
        risk_impacts=risk_impacts,
        provisional_reversal_conditions=_reversal_conditions(
            snapshot, package, impacts, ownership, moves, warnings
        ),
        projection_coverage=projection_coverage,
        decision=decision,
        modes=tuple(sorted(set(modes))) or ("FULL",),
        decision_label=decision.label if decision is not None else None,
        summary=summary,
        source_times=source_times,
        warnings=tuple(sorted(set(warnings))),
        evidence_hash="",
    )
    return replace(base, evidence_hash=stable_hash(asdict(base)))


def save_trade_evaluation(
    evaluation: TradeEvaluation,
    path: str | Path,
) -> Path:
    return atomic_write_json(path, evaluation)


def load_trade_evaluation(path: str | Path) -> dict[str, object]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if value.get("product") != "TRADE ASSISTANT" or value.get("operation") != "ENTERED PACKAGE EVALUATION":
        raise ValueError("File is not a Trade Assistant entered-package evaluation")
    saved_hash = value.get("evidence_hash")
    unhashed = dict(value)
    unhashed["evidence_hash"] = ""
    if not isinstance(saved_hash, str) or stable_hash(unhashed) != saved_hash:
        raise ValueError("Trade evaluation evidence hash does not match its contents")
    value["replay_mode"] = "OFFLINE/NON-CURRENT"
    return value
