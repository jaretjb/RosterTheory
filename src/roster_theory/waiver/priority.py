from __future__ import annotations

from dataclasses import dataclass
from statistics import median
from typing import TYPE_CHECKING, Mapping, Sequence

from roster_theory.core.models import Player
from roster_theory.waiver.ww_evidence import WaiverWireEvidence

if TYPE_CHECKING:
    from roster_theory.waiver.evaluation import PlayerValueInput


@dataclass(frozen=True, slots=True)
class WaiverPriorityWeights:
    weekly: float = 0.50
    waiver: float = 0.30
    ros: float = 0.20

    def __post_init__(self) -> None:
        values = (self.weekly, self.waiver, self.ros)
        if any(value <= 0 for value in values):
            raise ValueError("Waiver value weights must be positive")
        if not self.weekly > self.waiver > self.ros:
            raise ValueError("Waiver value weights must be ordered weekly > waiver > ROS")
        if abs(sum(values) - 1.0) > 1e-6:
            raise ValueError("Waiver value weights must sum to one")


@dataclass(frozen=True, slots=True)
class WaiverPriorityComponent:
    signal: str
    raw_rank: float
    rank_scope: str
    scope_size: int
    replacement_rank: int | None
    normalized_score: float
    configured_weight: float
    applied_weight: float
    source: str


@dataclass(frozen=True, slots=True)
class WaiverPriorityEvidence:
    player_id: str
    composite_score: float | None
    coverage_status: str
    components: tuple[WaiverPriorityComponent, ...]
    missing_signals: tuple[tuple[str, str], ...]
    configured_weights: WaiverPriorityWeights
    weighting_method: str
    acquisition_only: bool


@dataclass(frozen=True, slots=True)
class WaiverValueComparison:
    add: WaiverPriorityEvidence | None
    drop: WaiverPriorityEvidence | None
    drop_player_id: str | None
    value_delta: float | None
    comparable: bool
    explanation: str


def _position(player: Player) -> str | None:
    normalized = {
        "DST" if item.upper() == "DEF" else item.upper()
        for item in player.positions
    }
    return next(
        (
            position
            for position in ("QB", "RB", "WR", "TE", "K", "DST")
            if position in normalized
        ),
        None,
    )


def league_replacement_ranks(
    players: Sequence[Player],
    owner_by_player: Mapping[str, str],
) -> dict[str, int]:
    """Return the first unowned rank slot for each position in this league."""

    counts: dict[str, int] = {}
    for player in players:
        position = _position(player)
        if position is not None and player.player_id in owner_by_player:
            counts[position] = counts.get(position, 0) + 1
    return {position: count + 1 for position, count in counts.items()}


def _rank_score(rank: float, scope_size: int) -> float:
    if rank <= 0 or scope_size <= 0:
        raise ValueError("Waiver value ranks and scope sizes must be positive")
    bounded = min(float(rank), float(scope_size))
    return round(100.0 * (1.0 - (bounded - 1.0) / scope_size), 6)


def _replacement_adjusted_rank_score(
    rank: float,
    *,
    replacement_rank: int,
    scope_size: int,
) -> float:
    """Put position ranks on a league-relative scale with replacement at 50."""

    if rank <= 0 or replacement_rank <= 0 or scope_size <= 0:
        raise ValueError("Ranks, replacement rank, and scope size must be positive")
    bounded_scope = max(scope_size, replacement_rank + 1)
    bounded_rank = min(float(rank), float(bounded_scope))
    if bounded_rank <= replacement_rank:
        denominator = max(1.0, replacement_rank - 1.0)
        score = 50.0 + 50.0 * (replacement_rank - bounded_rank) / denominator
    else:
        denominator = max(1.0, bounded_scope - replacement_rank)
        score = 50.0 * (bounded_scope - bounded_rank) / denominator
    return round(max(0.0, min(100.0, score)), 6)


def _waiver_wire_ranks(
    evidence: WaiverWireEvidence | None,
) -> tuple[dict[str, tuple[float, str]], int]:
    if evidence is None or not evidence.market_complete:
        return {}, 0
    matched = tuple(
        row
        for row in evidence.players
        if row.match_status == "MATCHED" and row.market_overall_rank is not None
    )
    if evidence.ranking_source != "TRUSTED_EXPERT_PANEL":
        return (
            {
                row.player_id: (
                    float(row.market_overall_rank),
                    "FantasyPros Latest ECR",
                )
                for row in matched
            },
            len(matched),
        )

    aggregate: list[tuple[str, float, str]] = []
    for row in matched:
        panel_ranks = tuple(
            float(item.overall_rank)
            for item in row.selected_expert_ranks
            if item.overall_rank is not None
        )
        if len(panel_ranks) >= 2:
            aggregate.append(
                (
                    row.player_id,
                    float(median(panel_ranks)),
                    "accuracy-filtered three-expert WW median",
                )
            )
        else:
            aggregate.append(
                (
                    row.player_id,
                    float(row.market_overall_rank),
                    "FantasyPros Latest ECR (insufficient per-player panel coverage)",
                )
            )
    ordered = sorted(aggregate, key=lambda item: (item[1], item[0]))
    return (
        {
            player_id: (float(rank), source)
            for rank, (player_id, _aggregate_rank, source) in enumerate(ordered, 1)
        },
        len(ordered),
    )


def build_waiver_priority_scores(
    *,
    players: Sequence[Player],
    values: Sequence[PlayerValueInput],
    waiver_wire_evidence: WaiverWireEvidence | None,
    owner_by_player: Mapping[str, str] | None = None,
    current_bye_teams: Sequence[str] = (),
    weights: WaiverPriorityWeights = WaiverPriorityWeights(),
) -> dict[str, WaiverPriorityEvidence]:
    """Create league-relative Waiver Values from available ranking signals."""

    player_by_id = {player.player_id: player for player in players}
    value_by_id = {value.player_id: value for value in values}
    position_by_id = {
        player_id: position
        for player_id, player in player_by_id.items()
        if (position := _position(player)) is not None
    }
    weekly_scope: dict[str, int] = {}
    ros_scope: dict[str, int] = {}
    for value in values:
        position = position_by_id.get(value.player_id)
        if position is None:
            continue
        if value.current_week_position_rank is not None:
            weekly_scope[position] = max(
                weekly_scope.get(position, 0), value.current_week_position_rank
            )
        selected_ros = value.selected_rest_of_season_position_rank
        fallback_ros = value.rest_of_season_position_rank
        ros_rank = selected_ros if selected_ros is not None else fallback_ros
        if ros_rank is not None:
            ros_scope[position] = max(ros_scope.get(position, 0), ros_rank)

    replacement_ranks = league_replacement_ranks(
        players, owner_by_player or {}
    )
    for position, scope in {**weekly_scope, **ros_scope}.items():
        replacement_ranks.setdefault(position, max(1, scope // 2))
    ww_by_id, ww_scope = _waiver_wire_ranks(waiver_wire_evidence)
    bye_teams = {str(team).upper() for team in current_bye_teams}
    configured = {
        "WEEKLY": weights.weekly,
        "WAIVER": weights.waiver,
        "ROS": weights.ros,
    }
    result: dict[str, WaiverPriorityEvidence] = {}
    for player_id, value in value_by_id.items():
        player = player_by_id.get(player_id)
        position = position_by_id.get(player_id)
        available: list[
            tuple[str, float, str, int, int | None, str, float]
        ] = []
        missing: list[tuple[str, str]] = []

        weekly_rank = value.current_week_position_rank
        if (
            weekly_rank is not None
            and position is not None
            and weekly_scope.get(position)
        ):
            replacement = replacement_ranks[position]
            available.append(
                (
                    "WEEKLY",
                    float(weekly_rank),
                    f"{position}_CURRENT_WEEK",
                    weekly_scope[position],
                    replacement,
                    "FantasyPros weekly position rank",
                    _replacement_adjusted_rank_score(
                        weekly_rank,
                        replacement_rank=replacement,
                        scope_size=weekly_scope[position],
                    ),
                )
            )
        else:
            on_bye = bool(
                player is not None
                and player.nfl_team
                and player.nfl_team.upper() in bye_teams
            )
            missing.append(
                ("WEEKLY", "BYE_WEEK" if on_bye else "WEEKLY_RANK_UNAVAILABLE")
            )

        waiver_rank = ww_by_id.get(player_id)
        if waiver_rank is not None and ww_scope:
            rank, source = waiver_rank
            available.append(
                (
                    "WAIVER",
                    rank,
                    "WAIVER_WIRE_OVERALL",
                    ww_scope,
                    None,
                    source,
                    _rank_score(rank, ww_scope),
                )
            )
        else:
            missing.append(
                (
                    "WAIVER",
                    "WW_MARKET_INCOMPLETE"
                    if waiver_wire_evidence is None
                    or not waiver_wire_evidence.market_complete
                    else "NOT_LISTED_OR_ABOVE_WW_OWNERSHIP_SCOPE",
                )
            )

        selected_ros = value.selected_rest_of_season_position_rank
        ros_rank = (
            selected_ros
            if selected_ros is not None
            else value.rest_of_season_position_rank
        )
        if ros_rank is not None and position is not None and ros_scope.get(position):
            replacement = replacement_ranks[position]
            available.append(
                (
                    "ROS",
                    float(ros_rank),
                    f"{position}_REST_OF_SEASON",
                    ros_scope[position],
                    replacement,
                    (
                        "selected dependable ROS panel"
                        if selected_ros is not None
                        else "FantasyPros ROS Latest ECR fallback"
                    ),
                    _replacement_adjusted_rank_score(
                        ros_rank,
                        replacement_rank=replacement,
                        scope_size=ros_scope[position],
                    ),
                )
            )
        else:
            missing.append(("ROS", "ROS_RANK_UNAVAILABLE"))

        available_weight = sum(configured[signal] for signal, *_ in available)
        components = tuple(
            WaiverPriorityComponent(
                signal=signal,
                raw_rank=rank,
                rank_scope=scope,
                scope_size=scope_size,
                replacement_rank=replacement,
                normalized_score=score,
                configured_weight=configured[signal],
                applied_weight=round(configured[signal] / available_weight, 6),
                source=source,
            )
            for signal, rank, scope, scope_size, replacement, source, score in available
        )
        composite = (
            round(
                sum(row.normalized_score * row.applied_weight for row in components),
                6,
            )
            if components
            else None
        )
        coverage = {
            3: "COMPLETE",
            2: "PARTIAL",
            1: "LIMITED",
            0: "MISSING",
        }[len(components)]
        result[player_id] = WaiverPriorityEvidence(
            player_id=player_id,
            composite_score=composite,
            coverage_status=coverage,
            components=components,
            missing_signals=tuple(missing),
            configured_weights=weights,
            weighting_method=(
                "league-replacement-adjusted weekly and ROS ranks plus overall "
                "Waiver Wire rank; missing signals are neutral and weights renormalize"
            ),
            acquisition_only=False,
        )
    return result


def compare_waiver_values(
    priorities: Mapping[str, WaiverPriorityEvidence],
    *,
    add_player_id: str,
    drop_player_id: str | None,
) -> WaiverValueComparison:
    add = priorities.get(add_player_id)
    drop = priorities.get(drop_player_id) if drop_player_id is not None else None
    if add is None or add.composite_score is None:
        return WaiverValueComparison(
            add=add,
            drop=drop,
            drop_player_id=drop_player_id,
            value_delta=None,
            comparable=False,
            explanation="Added player has no usable weekly, Waiver Wire, or ROS rank",
        )
    if drop_player_id is not None and (drop is None or drop.composite_score is None):
        return WaiverValueComparison(
            add=add,
            drop=drop,
            drop_player_id=drop_player_id,
            value_delta=None,
            comparable=False,
            explanation="Drop candidate has no usable weekly, Waiver Wire, or ROS rank",
        )
    drop_score = drop.composite_score if drop is not None else 0.0
    assert drop_score is not None
    return WaiverValueComparison(
        add=add,
        drop=drop,
        drop_player_id=drop_player_id,
        value_delta=round(add.composite_score - drop_score, 6),
        comparable=True,
        explanation=(
            "Open roster slot has no displaced player value"
            if drop_player_id is None
            else "Added-player Waiver Value minus dropped-player Waiver Value"
        ),
    )
