from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass, field
from itertools import combinations
from typing import Iterable, Mapping, Protocol, Sequence

from roster_theory.core.errors import CoverageIncomplete
from roster_theory.core.lineup import LineupPlayer, LineupResult, optimize_lineup
from roster_theory.core.models import Player, Projection


SKILL_POSITIONS = frozenset({"QB", "RB", "WR", "TE"})
STARTABLE_SKILL_SLOTS = frozenset(
    {"QB", "RB", "WR", "TE", "FLEX", "WRRB_FLEX", "REC_FLEX", "SUPER_FLEX"}
)
DEFAULT_EVALUATION_POSITIONS = ("QB", "RB", "WR", "TE")
KNOWN_INACTIVE = frozenset({"IR", "PUP", "SUSP", "OUT"})


class ImpactOptions(Protocol):
    allow_partial_schedule: bool
    playoff_weight: float
    offense_downside_multiplier: float
    offense_upside_multiplier: float


@dataclass(frozen=True, slots=True)
class InSeasonWeek:
    week: int
    playoff: bool
    bye_teams: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class InSeasonContext:
    players: tuple[Player, ...]
    roster_positions: tuple[str, ...]
    weeks: tuple[InSeasonWeek, ...]
    unowned_player_ids: tuple[str, ...]
    evaluation_positions: tuple[str, ...] = DEFAULT_EVALUATION_POSITIONS
    current_status_week_only: bool = False


@dataclass(frozen=True, slots=True)
class ProjectionCell:
    player_id: str
    week: int
    points: float | None
    availability: str
    source: str | None
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class WeeklyProjectionMatrix:
    weeks: tuple[int, ...]
    cells: tuple[ProjectionCell, ...]
    keys: tuple[tuple[str, int], ...]
    complete: bool
    warnings: tuple[str, ...]
    lineup_cache: dict[tuple[tuple[str, ...], int, bool], LineupResult] = field(
        default_factory=dict, compare=False, hash=False, repr=False
    )
    replacement_lineup_cache: dict[
        tuple[tuple[str, ...], int, bool, tuple[str, ...]], "ReplacementLineupResult"
    ] = field(default_factory=dict, compare=False, hash=False, repr=False)
    depth_cache: dict[tuple[tuple[str, ...], bool], float] = field(
        default_factory=dict, compare=False, hash=False, repr=False
    )
    risk_cache: dict[tuple[object, ...], "RiskProfile"] = field(
        default_factory=dict, compare=False, hash=False, repr=False
    )

    def cell(self, player_id: str, week: int) -> ProjectionCell | None:
        key = (player_id, week)
        index = bisect_left(self.keys, key)
        return self.cells[index] if index < len(self.keys) and self.keys[index] == key else None


@dataclass(frozen=True, slots=True)
class WeeklyLineupImpact:
    week: int
    playoff: bool
    weight: float
    before_points: float
    after_points: float
    delta: float
    before_starters: tuple[str, ...]
    after_starters: tuple[str, ...]
    lineup_entrants: tuple[str, ...]
    lineup_exits: tuple[str, ...]
    before_replacements: tuple[str, ...] = ()
    after_replacements: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ReplacementLineupResult:
    lineup: LineupResult
    roster_starter_ids: tuple[str, ...]
    replacement_player_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TeamImpact:
    roster_id: str
    before_weighted_points: float
    after_weighted_points: float
    weighted_delta: float
    playoff_delta: float
    best_week: int | None
    best_week_delta: float | None
    worst_week: int | None
    worst_week_delta: float | None
    before_depth_above_waiver: float
    after_depth_above_waiver: float
    depth_delta: float
    weeks: tuple[WeeklyLineupImpact, ...]


@dataclass(frozen=True, slots=True)
class OffenseExposure:
    nfl_team: str
    full_roster_player_ids: tuple[str, ...]
    starter_player_ids: tuple[str, ...]
    starter_appearances: int
    projected_starter_points: float
    projected_starter_share: float
    bye_weeks: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class PairExposure:
    nfl_team: str
    player_ids: tuple[str, str]
    pair_type: str
    shared_starter_weeks: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class RiskScenario:
    kind: str
    nfl_team: str | None
    affected_player_ids: tuple[str, ...]
    weighted_points: float
    delta_from_central: float


@dataclass(frozen=True, slots=True)
class RiskProfile:
    roster_id: str
    central_weighted_points: float
    max_offense_share: float
    max_offense_team: str | None
    independent_absence_loss: float
    independent_absence_player_id: str | None
    offense_downside_loss: float
    offense_downside_team: str | None
    offense_upside_gain: float
    offense_upside_team: str | None
    exposures: tuple[OffenseExposure, ...]
    pairs: tuple[PairExposure, ...]
    scenarios: tuple[RiskScenario, ...]


@dataclass(frozen=True, slots=True)
class RiskImpact:
    roster_id: str
    before: RiskProfile
    after: RiskProfile
    max_offense_share_delta: float
    independent_absence_loss_delta: float
    offense_downside_loss_delta: float
    offense_upside_gain_delta: float


def build_weekly_projection_matrix(
    context: InSeasonContext,
    projections: Sequence[Projection],
) -> WeeklyProjectionMatrix:
    by_key: dict[tuple[str, int], Projection] = {}
    for projection in projections:
        if projection.horizon != "WEEKLY" or projection.week is None:
            continue
        key = (projection.player_id, projection.week)
        if key in by_key:
            raise CoverageIncomplete(
                f"Duplicate weekly projection for {projection.player_id} Week {projection.week}"
            )
        by_key[key] = projection
    cells: list[ProjectionCell] = []
    warnings: list[str] = []
    evaluation_positions = set(context.evaluation_positions)
    for player in context.players:
        normalized_positions = {
            "DST" if position.upper() == "DEF" else position.upper()
            for position in player.positions
        }
        if not evaluation_positions.intersection(normalized_positions):
            continue
        for week in context.weeks:
            projection = by_key.get((player.player_id, week.week))
            cell_warnings: list[str] = []
            if projection is None:
                points = None
                source = None
                availability = "MISSING"
                cell_warnings.append("Missing weekly projection")
                warnings.append(f"{player.player_id} Week {week.week}: missing projection")
            elif player.nfl_team in week.bye_teams:
                points = 0.0
                source = projection.source
                availability = "BYE"
            elif (
                (not context.current_status_week_only or week.week == context.weeks[0].week)
                and (not player.active or str(player.injury_status or "").upper() in KNOWN_INACTIVE)
            ):
                points = 0.0
                source = projection.source
                availability = "INACTIVE"
                cell_warnings.append(
                    f"Current status: {player.injury_status or 'inactive player directory row'}"
                )
            else:
                points = float(projection.league_points)
                source = projection.source
                availability = "ACTIVE"
                if player.injury_status:
                    cell_warnings.append(
                        f"Current status: {player.injury_status}"
                        + (
                            "; future availability is unverified"
                            if context.current_status_week_only
                            and week.week != context.weeks[0].week
                            else ""
                        )
                    )
            cells.append(
                ProjectionCell(
                    player_id=player.player_id,
                    week=week.week,
                    points=points,
                    availability=availability,
                    source=source,
                    warnings=tuple(cell_warnings),
                )
            )
    ordered = tuple(sorted(cells, key=lambda row: (row.player_id, row.week)))
    return WeeklyProjectionMatrix(
        weeks=tuple(week.week for week in context.weeks),
        cells=ordered,
        keys=tuple((row.player_id, row.week) for row in ordered),
        complete=not warnings,
        warnings=tuple(sorted(set(warnings))),
    )


def lineup_slots(context: InSeasonContext) -> tuple[str, ...]:
    allowed = {"DST" if value.upper() == "DEF" else value.upper() for value in context.evaluation_positions}
    return tuple(
        position
        for position in context.roster_positions
        if ("DST" if position.upper() == "DEF" else position.upper()) in allowed
        or position.upper() in STARTABLE_SKILL_SLOTS
        and bool(allowed.intersection(STARTABLE_SKILL_SLOTS))
    )


def lineup(
    context: InSeasonContext,
    matrix: WeeklyProjectionMatrix,
    roster: Iterable[str],
    week: int,
    *,
    allow_partial: bool,
) -> LineupResult:
    player_by_id = {player.player_id: player for player in context.players}
    roster_ids = tuple(sorted(player_id for player_id in roster if player_id in player_by_id))
    cache_key = (roster_ids, week, allow_partial)
    cached = matrix.lineup_cache.get(cache_key)
    if cached is not None:
        return cached
    missing = tuple(
        player_id
        for player_id in roster_ids
        if (cell := matrix.cell(player_id, week)) is None or cell.points is None
    )
    if missing and not allow_partial:
        raise CoverageIncomplete(
            f"Week {week} projections missing for evaluated roster: " + ", ".join(missing)
        )
    points = {
        player_id: float(cell.points)
        for player_id in roster_ids
        if (cell := matrix.cell(player_id, week)) is not None and cell.points is not None
    }
    result = optimize_lineup(
        tuple(LineupPlayer(player_id, player_by_id[player_id].positions) for player_id in roster_ids),
        lineup_slots(context),
        points,
    )
    matrix.lineup_cache[cache_key] = result
    return result


def weighted_lineup_score(
    context: InSeasonContext,
    matrix: WeeklyProjectionMatrix,
    roster: Iterable[str],
    options: ImpactOptions,
) -> float:
    return round(
        sum(
            lineup(
                context,
                matrix,
                roster,
                week.week,
                allow_partial=options.allow_partial_schedule,
            ).score
            * (options.playoff_weight if week.playoff else 1.0)
            for week in context.weeks
        ),
        3,
    )


def plausible_unowned_players(
    context: InSeasonContext,
    matrix: WeeklyProjectionMatrix,
    *,
    per_position_week: int = 5,
    allowed_player_ids: set[str] | None = None,
) -> tuple[str, ...]:
    player_by_id = {player.player_id: player for player in context.players}
    result: set[str] = set()
    for week in context.weeks:
        for position in sorted(set(context.evaluation_positions)):
            ranked = sorted(
                (
                    (float(cell.points), player_id)
                    for player_id in context.unowned_player_ids
                    if (player := player_by_id.get(player_id)) is not None
                    and (allowed_player_ids is None or player_id in allowed_player_ids)
                    and position
                    in {
                        "DST" if value.upper() == "DEF" else value.upper()
                        for value in player.positions
                    }
                    and (cell := matrix.cell(player_id, week.week)) is not None
                    and cell.points is not None
                ),
                key=lambda item: (-item[0], item[1]),
            )
            result.update(player_id for _, player_id in ranked[:per_position_week])
    return tuple(sorted(result))


def lineup_with_replacement_floor(
    context: InSeasonContext,
    matrix: WeeklyProjectionMatrix,
    roster: Iterable[str],
    week: int,
    *,
    allow_partial: bool,
    replacement_exclusions: Iterable[str] = (),
) -> ReplacementLineupResult:
    """Optimize a roster, then fill only uncovered capacity from waivers.

    Active bench players are considered first by the ordinary lineup. Waiver
    candidates can enter only up to the number of starting slots that remain
    uncovered, so this establishes a replacement floor without treating the
    entire free-agent pool as part of the roster.
    """
    player_by_id = {player.player_id: player for player in context.players}
    roster_ids = tuple(sorted(player_id for player_id in roster if player_id in player_by_id))
    exclusions = tuple(sorted(set(replacement_exclusions)))
    cache_key = (roster_ids, week, allow_partial, exclusions)
    cached = matrix.replacement_lineup_cache.get(cache_key)
    if cached is not None:
        return cached

    # Preserve the ordinary completeness contract and the roster's healthy
    # positional capacity before filtering players who are known unavailable
    # for this particular week. Structural holes created by an imbalanced
    # roster or an add/drop are not permission to assume a second transaction.
    full_lineup = lineup(
        context, matrix, roster_ids, week, allow_partial=allow_partial
    )
    available_roster = tuple(
        player_id
        for player_id in roster_ids
        if (cell := matrix.cell(player_id, week)) is not None
        and cell.points is not None
        and cell.availability == "ACTIVE"
    )
    roster_lineup = lineup(
        context,
        matrix,
        available_roster,
        week,
        allow_partial=allow_partial,
    )
    uncovered_slots = full_lineup.filled_slots - roster_lineup.filled_slots
    if uncovered_slots <= 0:
        result = ReplacementLineupResult(
            lineup=roster_lineup,
            roster_starter_ids=tuple(
                sorted(row.player_id for row in roster_lineup.assignments)
            ),
            replacement_player_ids=(),
        )
        matrix.replacement_lineup_cache[cache_key] = result
        return result

    excluded = set(exclusions) | set(roster_ids)
    plausible = plausible_unowned_players(
        context,
        matrix,
        per_position_week=max(5, uncovered_slots + 1),
    )
    replacements = tuple(
        player_id
        for player_id in plausible
        if player_id not in excluded
        and (cell := matrix.cell(player_id, week)) is not None
        and cell.points is not None
        and cell.availability == "ACTIVE"
    )
    if not replacements:
        result = ReplacementLineupResult(
            lineup=roster_lineup,
            roster_starter_ids=tuple(
                sorted(row.player_id for row in roster_lineup.assignments)
            ),
            replacement_player_ids=(),
        )
        matrix.replacement_lineup_cache[cache_key] = result
        return result

    candidates = (*available_roster, *replacements)
    points = {
        player_id: float(cell.points)
        for player_id in candidates
        if (cell := matrix.cell(player_id, week)) is not None and cell.points is not None
    }
    optimized = optimize_lineup(
        tuple(LineupPlayer(player_id, player_by_id[player_id].positions) for player_id in candidates),
        lineup_slots(context),
        points,
        limited_player_ids=replacements,
        maximum_limited_players=uncovered_slots,
        required_filled_slots=tuple(
            row.slot
            for row in full_lineup.assignments
            if row.slot.split(":", 1)[0] in {"DST", "K"}
        ),
    )
    selected = {row.player_id for row in optimized.assignments}
    replacement_ids = tuple(sorted(selected.intersection(replacements)))
    result = ReplacementLineupResult(
        lineup=optimized,
        roster_starter_ids=tuple(sorted(selected.difference(replacement_ids))),
        replacement_player_ids=replacement_ids,
    )
    matrix.replacement_lineup_cache[cache_key] = result
    return result


def depth_above_waiver(
    context: InSeasonContext,
    matrix: WeeklyProjectionMatrix,
    roster: set[str],
    options: ImpactOptions,
) -> float:
    cache_key = (tuple(sorted(roster)), options.allow_partial_schedule)
    cached = matrix.depth_cache.get(cache_key)
    if cached is not None:
        return cached
    free_agents = plausible_unowned_players(context, matrix, per_position_week=2)
    player_by_id = {player.player_id: player for player in context.players}
    total = 0.0
    for week in context.weeks:
        representatives: dict[tuple[str, ...], tuple[float, str]] = {}
        for player_id in free_agents:
            if player_id in roster or player_id not in player_by_id:
                continue
            cell = matrix.cell(player_id, week.week)
            if cell is None or cell.points is None:
                continue
            signature = tuple(sorted(player_by_id[player_id].positions))
            candidate = (float(cell.points), player_id)
            if candidate > representatives.get(signature, (float("-inf"), "")):
                representatives[signature] = candidate
        waiver_candidates = tuple(
            player_id for _, player_id in sorted(representatives.values(), reverse=True)
        )
        baseline = lineup(
            context,
            matrix,
            roster,
            week.week,
            allow_partial=options.allow_partial_schedule,
        )
        starter_ids = {row.player_id for row in baseline.assignments}
        for absent in sorted(starter_ids):
            base_without = baseline.score - next(
                row.points for row in baseline.assignments if row.player_id == absent
            )
            internal = lineup(
                context,
                matrix,
                roster - {absent},
                week.week,
                allow_partial=options.allow_partial_schedule,
            ).score - base_without
            starter_remainder = starter_ids - {absent}
            waiver = max(
                (
                    lineup(
                        context,
                        matrix,
                        {*starter_remainder, player_id},
                        week.week,
                        allow_partial=options.allow_partial_schedule,
                    ).score
                    - base_without
                    for player_id in waiver_candidates
                ),
                default=0.0,
            )
            total += max(0.0, internal - waiver)
    result = round(total, 3)
    matrix.depth_cache[cache_key] = result
    return result


def team_impact(
    context: InSeasonContext,
    matrix: WeeklyProjectionMatrix,
    roster_id: str,
    before: set[str],
    after: set[str],
    options: ImpactOptions,
    *,
    replacement_exclusions: Iterable[str] = (),
) -> TeamImpact:
    rows: list[WeeklyLineupImpact] = []
    for week in context.weeks:
        before_result = lineup_with_replacement_floor(
            context,
            matrix,
            before,
            week.week,
            allow_partial=options.allow_partial_schedule,
            replacement_exclusions=replacement_exclusions,
        )
        after_result = lineup_with_replacement_floor(
            context,
            matrix,
            after,
            week.week,
            allow_partial=options.allow_partial_schedule,
            replacement_exclusions=replacement_exclusions,
        )
        before_lineup = before_result.lineup
        after_lineup = after_result.lineup
        before_ids = before_result.roster_starter_ids
        after_ids = after_result.roster_starter_ids
        weight = options.playoff_weight if week.playoff else 1.0
        rows.append(
            WeeklyLineupImpact(
                week=week.week,
                playoff=week.playoff,
                weight=weight,
                before_points=before_lineup.score,
                after_points=after_lineup.score,
                delta=round(after_lineup.score - before_lineup.score, 3),
                before_starters=before_ids,
                after_starters=after_ids,
                lineup_entrants=tuple(sorted(set(after_ids) - set(before_ids))),
                lineup_exits=tuple(sorted(set(before_ids) - set(after_ids))),
                before_replacements=before_result.replacement_player_ids,
                after_replacements=after_result.replacement_player_ids,
            )
        )
    before_total = sum(row.before_points * row.weight for row in rows)
    after_total = sum(row.after_points * row.weight for row in rows)
    best = max(rows, key=lambda row: (row.delta, -row.week), default=None)
    worst = min(rows, key=lambda row: (row.delta, row.week), default=None)
    before_depth = depth_above_waiver(context, matrix, before, options)
    after_depth = depth_above_waiver(context, matrix, after, options)
    return TeamImpact(
        roster_id=roster_id,
        before_weighted_points=round(before_total, 3),
        after_weighted_points=round(after_total, 3),
        weighted_delta=round(after_total - before_total, 3),
        playoff_delta=round(sum(row.delta for row in rows if row.playoff), 3),
        best_week=best.week if best else None,
        best_week_delta=best.delta if best else None,
        worst_week=worst.week if worst else None,
        worst_week_delta=worst.delta if worst else None,
        before_depth_above_waiver=before_depth,
        after_depth_above_waiver=after_depth,
        depth_delta=round(after_depth - before_depth, 3),
        weeks=tuple(rows),
    )


def _scenario_score(
    context: InSeasonContext,
    matrix: WeeklyProjectionMatrix,
    roster: set[str],
    options: ImpactOptions,
    multipliers: Mapping[str, float],
) -> float:
    player_by_id = {player.player_id: player for player in context.players}
    total = 0.0
    for week in context.weeks:
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
        optimized = optimize_lineup(
            tuple(LineupPlayer(player_id, player_by_id[player_id].positions) for player_id in roster_ids),
            lineup_slots(context),
            points,
        )
        total += optimized.score * (options.playoff_weight if week.playoff else 1.0)
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


def risk_profile(
    context: InSeasonContext,
    matrix: WeeklyProjectionMatrix,
    roster_id: str,
    roster: set[str],
    options: ImpactOptions,
) -> RiskProfile:
    cache_key = (
        roster_id,
        tuple(sorted(roster)),
        options.allow_partial_schedule,
        options.playoff_weight,
        options.offense_downside_multiplier,
        options.offense_upside_multiplier,
    )
    cached = matrix.risk_cache.get(cache_key)
    if cached is not None:
        return cached
    player_by_id = {player.player_id: player for player in context.players}
    weekly_lineups = {
        week.week: lineup(
            context,
            matrix,
            roster,
            week.week,
            allow_partial=options.allow_partial_schedule,
        )
        for week in context.weeks
    }
    central = round(
        sum(
            weekly_lineups[week.week].score
            * (options.playoff_weight if week.playoff else 1.0)
            for week in context.weeks
        ),
        3,
    )
    starter_weeks: dict[str, set[int]] = {}
    starter_points_by_team: dict[str, float] = {}
    starter_appearances_by_team: dict[str, int] = {}
    starter_ids_by_team: dict[str, set[str]] = {}
    for week in context.weeks:
        weight = options.playoff_weight if week.playoff else 1.0
        for assignment in weekly_lineups[week.week].assignments:
            player = player_by_id[assignment.player_id]
            starter_weeks.setdefault(player.player_id, set()).add(week.week)
            if not player.nfl_team:
                continue
            starter_ids_by_team.setdefault(player.nfl_team, set()).add(player.player_id)
            starter_appearances_by_team[player.nfl_team] = (
                starter_appearances_by_team.get(player.nfl_team, 0) + 1
            )
            starter_points_by_team[player.nfl_team] = (
                starter_points_by_team.get(player.nfl_team, 0.0) + assignment.points * weight
            )
    roster_ids_by_team: dict[str, set[str]] = {}
    for player_id in roster:
        player = player_by_id.get(player_id)
        if player is not None and player.nfl_team:
            roster_ids_by_team.setdefault(player.nfl_team, set()).add(player_id)
    exposures = tuple(
        OffenseExposure(
            nfl_team=team,
            full_roster_player_ids=tuple(sorted(roster_ids_by_team.get(team, set()))),
            starter_player_ids=tuple(sorted(starter_ids_by_team.get(team, set()))),
            starter_appearances=starter_appearances_by_team.get(team, 0),
            projected_starter_points=round(starter_points_by_team.get(team, 0.0), 3),
            projected_starter_share=(
                round(starter_points_by_team.get(team, 0.0) / central, 6)
                if central > 0
                else 0.0
            ),
            bye_weeks=tuple(week.week for week in context.weeks if team in week.bye_teams),
        )
        for team in sorted(roster_ids_by_team)
    )
    pairs: list[PairExposure] = []
    for exposure in exposures:
        for first, second in combinations(exposure.full_roster_player_ids, 2):
            pairs.append(
                PairExposure(
                    nfl_team=exposure.nfl_team,
                    player_ids=(first, second),
                    pair_type=_pair_type(player_by_id[first], player_by_id[second]),
                    shared_starter_weeks=tuple(
                        sorted(starter_weeks.get(first, set()) & starter_weeks.get(second, set()))
                    ),
                )
            )
    scenarios: list[RiskScenario] = []
    for player_id in sorted(starter_weeks):
        score = _scenario_score(context, matrix, roster, options, {player_id: 0.0})
        scenarios.append(
            RiskScenario(
                kind="INDEPENDENT_ABSENCE",
                nfl_team=player_by_id[player_id].nfl_team,
                affected_player_ids=(player_id,),
                weighted_points=score,
                delta_from_central=round(score - central, 3),
            )
        )
    for exposure in exposures:
        if not exposure.starter_player_ids:
            continue
        for kind, multiplier in (
            ("OFFENSE_DOWNSIDE", options.offense_downside_multiplier),
            ("OFFENSE_UPSIDE", options.offense_upside_multiplier),
        ):
            score = _scenario_score(
                context,
                matrix,
                roster,
                options,
                {player_id: multiplier for player_id in exposure.full_roster_player_ids},
            )
            scenarios.append(
                RiskScenario(
                    kind=kind,
                    nfl_team=exposure.nfl_team,
                    affected_player_ids=exposure.full_roster_player_ids,
                    weighted_points=score,
                    delta_from_central=round(score - central, 3),
                )
            )
    absence = min(
        (row for row in scenarios if row.kind == "INDEPENDENT_ABSENCE"),
        key=lambda row: (row.delta_from_central, row.affected_player_ids),
        default=None,
    )
    downside = min(
        (row for row in scenarios if row.kind == "OFFENSE_DOWNSIDE"),
        key=lambda row: (row.delta_from_central, row.nfl_team or ""),
        default=None,
    )
    upside = max(
        (row for row in scenarios if row.kind == "OFFENSE_UPSIDE"),
        key=lambda row: (row.delta_from_central, row.nfl_team or ""),
        default=None,
    )
    max_exposure = max(
        exposures,
        key=lambda row: (row.projected_starter_share, row.nfl_team),
        default=None,
    )
    result = RiskProfile(
        roster_id=roster_id,
        central_weighted_points=central,
        max_offense_share=max_exposure.projected_starter_share if max_exposure else 0.0,
        max_offense_team=max_exposure.nfl_team if max_exposure else None,
        independent_absence_loss=round(-absence.delta_from_central, 3) if absence else 0.0,
        independent_absence_player_id=absence.affected_player_ids[0] if absence else None,
        offense_downside_loss=round(-downside.delta_from_central, 3) if downside else 0.0,
        offense_downside_team=downside.nfl_team if downside else None,
        offense_upside_gain=round(upside.delta_from_central, 3) if upside else 0.0,
        offense_upside_team=upside.nfl_team if upside else None,
        exposures=exposures,
        pairs=tuple(sorted(pairs, key=lambda row: (row.nfl_team, row.player_ids))),
        scenarios=tuple(
            sorted(scenarios, key=lambda row: (row.kind, row.nfl_team or "", row.affected_player_ids))
        ),
    )
    matrix.risk_cache[cache_key] = result
    return result


def risk_impact(
    context: InSeasonContext,
    matrix: WeeklyProjectionMatrix,
    roster_id: str,
    before: set[str],
    after: set[str],
    options: ImpactOptions,
) -> RiskImpact:
    before_profile = risk_profile(context, matrix, roster_id, before, options)
    after_profile = risk_profile(context, matrix, roster_id, after, options)
    return RiskImpact(
        roster_id=roster_id,
        before=before_profile,
        after=after_profile,
        max_offense_share_delta=round(
            after_profile.max_offense_share - before_profile.max_offense_share, 6
        ),
        independent_absence_loss_delta=round(
            after_profile.independent_absence_loss - before_profile.independent_absence_loss, 3
        ),
        offense_downside_loss_delta=round(
            after_profile.offense_downside_loss - before_profile.offense_downside_loss, 3
        ),
        offense_upside_gain_delta=round(
            after_profile.offense_upside_gain - before_profile.offense_upside_gain, 3
        ),
    )
