from __future__ import annotations

from dataclasses import asdict, dataclass
from math import sqrt
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from roster_theory.core.errors import CoverageIncomplete
from roster_theory.core.isotonic import MonotoneCurve, fit_nonincreasing_curve
from roster_theory.core.models import Projection, RankObservation
from roster_theory.core.provenance import DataStamp, stable_hash
from roster_theory.providers.cache import atomic_write_json


SUPPORTED_HORIZONS = frozenset(
    {"WEEKLY-PROXY", "ROS", "EARLY_SEASON_DRAFT_ANCHOR"}
)


@dataclass(frozen=True, slots=True)
class SelectedRank:
    player_id: str
    position: str
    raw_position_rank: float | None
    raw_overall_rank: float | None
    final_position_rank: int
    final_overall_rank: int | None
    market_position_rank: int
    market_overall_rank: int | None
    dispersion: float | None
    contributor_weight: float
    contributions: tuple[tuple[str, float, float], ...]
    omissions: tuple[tuple[str, str], ...]
    shrinkage_to_ecr: float


@dataclass(frozen=True, slots=True)
class ProjectionCurve:
    position: str
    slot_points: tuple[tuple[int, float], ...]
    raw_player_points: tuple[tuple[str, float], ...]
    raw_player_ranks: tuple[tuple[str, int], ...]
    source_mode: str
    weeks: tuple[int, ...]

    def points_for_rank(self, rank: int) -> float:
        values = dict(self.slot_points)
        if rank not in values:
            raise CoverageIncomplete(
                f"{self.position} projection curve lacks rank slot {rank}"
            )
        return values[rank]


@dataclass(frozen=True, slots=True)
class BoardPlayerValue:
    player_id: str
    position: str
    position_rank: int
    overall_rank: int
    raw_projection: float
    raw_projection_rank: int
    aligned_points: float
    replacement_points: float
    positional_vorp: float
    reconciled_vorp: float
    tier: int
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ValueBoard:
    board_id: str
    horizon: str
    players: tuple[BoardPlayerValue, ...]
    curves: tuple[ProjectionCurve, ...]
    replacement_baselines: tuple[tuple[str, float], ...]
    overall_curve: MonotoneCurve
    complete: bool
    stamps: tuple[DataStamp, ...] = ()


@dataclass(frozen=True, slots=True)
class ValuationGap:
    player_id: str
    position: str
    selected_rank: int
    market_rank: int
    rank_gap: int
    selected_tier: int
    market_tier: int
    tier_gap: int
    selected_vorp: float
    market_vorp: float
    value_gap: float
    signal: str


def _integer_rank(value: float | None, label: str) -> int:
    if value is None or value <= 0 or int(value) != value:
        raise CoverageIncomplete(f"{label} must be a positive integer rank")
    return int(value)


def aggregate_selected_ranks(
    market: Sequence[RankObservation],
    contributor_ballots: Sequence[RankObservation],
    selected_weights: Mapping[str, float],
    *,
    horizon: str,
) -> tuple[SelectedRank, ...]:
    """Aggregate selected ballots while using absent weight as an ECR anchor."""
    if horizon not in SUPPORTED_HORIZONS:
        raise ValueError(
            "horizon must be WEEKLY-PROXY, ROS, or EARLY_SEASON_DRAFT_ANCHOR"
        )
    if not selected_weights or any(weight <= 0 for weight in selected_weights.values()):
        raise ValueError("Selected expert weights must be positive")
    total_weight = sum(float(weight) for weight in selected_weights.values())
    weights = {str(key): float(value) / total_weight for key, value in selected_weights.items()}
    market_by_id = {row.player_id: row for row in market}
    if len(market_by_id) != len(market):
        raise CoverageIncomplete("Market board contains duplicate players")
    ballots_by_player: dict[str, list[RankObservation]] = {}
    for ballot in contributor_ballots:
        if ballot.expert_id in weights:
            ballots_by_player.setdefault(ballot.player_id, []).append(ballot)

    provisional: list[dict[str, object]] = []
    for player_id, market_row in market_by_id.items():
        if market_row.horizon != horizon:
            raise CoverageIncomplete("Selected and market ranking horizons differ")
        market_position = _integer_rank(
            market_row.position_rank, f"Market position rank for {player_id}"
        )
        matching = [
            ballot
            for ballot in ballots_by_player.get(player_id, ())
            if ballot.position == market_row.position and ballot.position_rank is not None
        ]
        contribution_ids = {str(ballot.expert_id) for ballot in matching}
        present_weight = sum(weights[expert_id] for expert_id in contribution_ids)
        contributions = tuple(
            sorted(
                (
                    str(ballot.expert_id),
                    float(ballot.position_rank),
                    weights[str(ballot.expert_id)],
                )
                for ballot in matching
            )
        )
        if matching:
            raw_position = sum(rank * weight for _, rank, weight in contributions) / present_weight
            variance = sum(
                weight * (rank - raw_position) ** 2 for _, rank, weight in contributions
            ) / present_weight
            dispersion = sqrt(variance)
        else:
            raw_position = None
            dispersion = None
        final_position_score = (
            (raw_position * present_weight if raw_position is not None else 0.0)
            + market_position * (1.0 - present_weight)
        )

        overall_contributions = [
            (
                str(ballot.expert_id),
                float(ballot.overall_rank),
                weights[str(ballot.expert_id)],
            )
            for ballot in ballots_by_player.get(player_id, ())
            if ballot.expert_id in weights and ballot.overall_rank is not None
        ]
        overall_present = sum(weight for _, _, weight in overall_contributions)
        raw_overall = (
            sum(rank * weight for _, rank, weight in overall_contributions) / overall_present
            if overall_present
            else None
        )
        market_overall = (
            _integer_rank(market_row.overall_rank, f"Market overall rank for {player_id}")
            if market_row.overall_rank is not None
            else None
        )
        final_overall_score = (
            (raw_overall * overall_present if raw_overall is not None else 0.0)
            + market_overall * (1.0 - overall_present)
            if market_overall is not None
            else None
        )
        omissions = tuple(
            (expert_id, "missing_player_ballot")
            for expert_id in sorted(weights)
            if expert_id not in contribution_ids
        )
        provisional.append(
            {
                "player_id": player_id,
                "position": market_row.position,
                "market_position": market_position,
                "market_overall": market_overall,
                "raw_position": raw_position,
                "raw_overall": raw_overall,
                "final_position_score": final_position_score,
                "final_overall_score": final_overall_score,
                "dispersion": dispersion,
                "present_weight": present_weight,
                "contributions": contributions,
                "omissions": omissions,
            }
        )

    position_ordinals: dict[str, int] = {}
    final_position: dict[str, int] = {}
    for item in sorted(
        provisional,
        key=lambda row: (
            str(row["position"]),
            float(row["final_position_score"]),
            int(row["market_position"]),
            str(row["player_id"]),
        ),
    ):
        position = str(item["position"])
        position_ordinals[position] = position_ordinals.get(position, 0) + 1
        final_position[str(item["player_id"])] = position_ordinals[position]

    overall_items = [item for item in provisional if item["final_overall_score"] is not None]
    final_overall = {
        str(item["player_id"]): rank
        for rank, item in enumerate(
            sorted(
                overall_items,
                key=lambda row: (
                    float(row["final_overall_score"]),
                    int(row["market_overall"]),
                    str(row["player_id"]),
                ),
            ),
            1,
        )
    }
    return tuple(
        SelectedRank(
            player_id=str(item["player_id"]),
            position=str(item["position"]),
            raw_position_rank=item["raw_position"],  # type: ignore[arg-type]
            raw_overall_rank=item["raw_overall"],  # type: ignore[arg-type]
            final_position_rank=final_position[str(item["player_id"])],
            final_overall_rank=final_overall.get(str(item["player_id"])),
            market_position_rank=int(item["market_position"]),
            market_overall_rank=item["market_overall"],  # type: ignore[arg-type]
            dispersion=item["dispersion"],  # type: ignore[arg-type]
            contributor_weight=float(item["present_weight"]),
            contributions=item["contributions"],  # type: ignore[arg-type]
            omissions=item["omissions"],  # type: ignore[arg-type]
            shrinkage_to_ecr=1.0 - float(item["present_weight"]),
        )
        for item in sorted(provisional, key=lambda row: str(row["player_id"]))
    )


def build_projection_curves(
    projections: Sequence[Projection],
    player_positions: Mapping[str, str],
    *,
    required_counts: Mapping[str, int],
    expected_weeks: Sequence[int] = (),
) -> tuple[ProjectionCurve, ...]:
    by_player: dict[str, list[Projection]] = {}
    for projection in projections:
        by_player.setdefault(projection.player_id, []).append(projection)
    curves: list[ProjectionCurve] = []
    for position, required_count in sorted(required_counts.items()):
        candidates: list[tuple[str, float]] = []
        source_modes: set[str] = set()
        for player_id, player_position in player_positions.items():
            if player_position != position:
                continue
            rows = by_player.get(player_id, [])
            if not rows:
                continue
            horizons = {row.horizon for row in rows}
            if horizons == {"ROS"}:
                if len(rows) != 1:
                    raise CoverageIncomplete(f"Duplicate direct ROS projection for {player_id}")
                source_modes.add("DIRECT-ROS")
            elif horizons == {"WEEKLY"}:
                weeks = {row.week for row in rows}
                if expected_weeks and weeks != set(expected_weeks):
                    continue
                source_modes.add("SUMMED-WEEKLY")
            else:
                raise CoverageIncomplete(f"Mixed projection horizons for {player_id}")
            candidates.append((player_id, sum(row.league_points for row in rows)))
        if len(candidates) < required_count:
            raise CoverageIncomplete(
                f"{position} projection distribution has {len(candidates)} players; "
                f"requires {required_count}"
            )
        if len(source_modes) != 1:
            raise CoverageIncomplete("A projection curve cannot mix direct ROS and weekly sums")
        ordered = sorted(candidates, key=lambda item: (-item[1], item[0]))
        raw_ranks = tuple((player_id, rank) for rank, (player_id, _) in enumerate(ordered, 1))
        curves.append(
            ProjectionCurve(
                position=position,
                slot_points=tuple(
                    (rank, points)
                    for rank, (_, points) in enumerate(ordered[:required_count], 1)
                ),
                raw_player_points=tuple(sorted(candidates)),
                raw_player_ranks=tuple(sorted(raw_ranks)),
                source_mode=next(iter(source_modes)),
                weeks=tuple(sorted(expected_weeks)),
            )
        )
    return tuple(curves)


def _curve_tiers(values: Sequence[tuple[str, float]], fraction: float = 0.08) -> dict[str, int]:
    if not values:
        return {}
    ordered = sorted(values, key=lambda item: (-item[1], item[0]))
    spread = max(ordered[0][1] - ordered[-1][1], 0.0)
    threshold = spread * fraction
    tier = 1
    result = {ordered[0][0]: tier}
    for (previous_id, previous), (player_id, current) in zip(ordered, ordered[1:]):
        del previous_id
        if threshold > 0 and previous - current >= threshold:
            tier += 1
        result[player_id] = tier
    return result


def build_value_board(
    *,
    board_id: str,
    horizon: str,
    position_ranks: Mapping[str, int],
    positions: Mapping[str, str],
    curves: Sequence[ProjectionCurve],
    replacement_baselines: Mapping[str, float],
    overall_ranks: Mapping[str, int] | None = None,
    player_warnings: Mapping[str, tuple[str, ...]] | None = None,
    stamps: Sequence[DataStamp] = (),
) -> ValueBoard:
    if horizon not in SUPPORTED_HORIZONS:
        raise ValueError(
            "horizon must be WEEKLY-PROXY, ROS, or EARLY_SEASON_DRAFT_ANCHOR"
        )
    curve_by_position = {curve.position: curve for curve in curves}
    provisional: list[dict[str, float | int | str]] = []
    for player_id, rank in position_ranks.items():
        position = positions.get(player_id)
        if position is None or position not in curve_by_position:
            raise CoverageIncomplete(f"Missing position/curve for {player_id}")
        curve = curve_by_position[position]
        aligned = curve.points_for_rank(int(rank))
        raw_points = dict(curve.raw_player_points).get(player_id)
        raw_rank = dict(curve.raw_player_ranks).get(player_id)
        if raw_points is None or raw_rank is None:
            raise CoverageIncomplete(f"Missing raw projection evidence for {player_id}")
        if position not in replacement_baselines:
            raise CoverageIncomplete(f"Missing common {position} replacement baseline")
        baseline = float(replacement_baselines[position])
        provisional.append(
            {
                "player_id": player_id,
                "position": position,
                "position_rank": int(rank),
                "raw_projection": raw_points,
                "raw_projection_rank": raw_rank,
                "aligned_points": aligned,
                "replacement": baseline,
                "positional_vorp": aligned - baseline,
            }
        )
    required_ids = set(position_ranks)
    if required_ids != set(positions):
        missing = sorted(set(positions) - required_ids)
        raise CoverageIncomplete("Board ranks do not cover fixed universe: " + ", ".join(missing))
    if overall_ranks is None:
        derived = {
            str(row["player_id"]): index
            for index, row in enumerate(
                sorted(
                    provisional,
                    key=lambda item: (-float(item["positional_vorp"]), str(item["player_id"])),
                ),
                1,
            )
        }
    else:
        if set(overall_ranks) != required_ids:
            raise CoverageIncomplete("Overall ranks do not cover the fixed universe")
        derived = {key: int(value) for key, value in overall_ranks.items()}
    overall_curve = fit_nonincreasing_curve(
        (derived[str(row["player_id"])], float(row["positional_vorp"]))
        for row in provisional
    )
    reconciled = {
        str(row["player_id"]): overall_curve.value(derived[str(row["player_id"])])
        for row in provisional
    }
    for position in sorted(set(positions.values())):
        ordered = sorted(
            (row for row in provisional if row["position"] == position),
            key=lambda item: (int(item["position_rank"]), str(item["player_id"])),
        )
        ceiling = float("inf")
        for row in ordered:
            player_id = str(row["player_id"])
            ceiling = min(ceiling, reconciled[player_id])
            reconciled[player_id] = ceiling
    tiers = _curve_tiers(tuple((key, value) for key, value in reconciled.items()))
    players = tuple(
        BoardPlayerValue(
            player_id=str(row["player_id"]),
            position=str(row["position"]),
            position_rank=int(row["position_rank"]),
            overall_rank=derived[str(row["player_id"])],
            raw_projection=float(row["raw_projection"]),
            raw_projection_rank=int(row["raw_projection_rank"]),
            aligned_points=float(row["aligned_points"]),
            replacement_points=float(row["replacement"]),
            positional_vorp=float(row["positional_vorp"]),
            reconciled_vorp=reconciled[str(row["player_id"])],
            tier=tiers[str(row["player_id"])],
            warnings=(player_warnings or {}).get(str(row["player_id"]), ()),
        )
        for row in sorted(provisional, key=lambda item: derived[str(item["player_id"])])
    )
    return ValueBoard(
        board_id=board_id,
        horizon=horizon,
        players=players,
        curves=tuple(curves),
        replacement_baselines=tuple(sorted((key, float(value)) for key, value in replacement_baselines.items())),
        overall_curve=overall_curve,
        complete=True,
        stamps=tuple(stamps),
    )


def valuation_gaps(selected: ValueBoard, market: ValueBoard) -> tuple[ValuationGap, ...]:
    if selected.horizon != market.horizon:
        raise CoverageIncomplete("Selected and market boards have different horizons")
    selected_by_id = {row.player_id: row for row in selected.players}
    market_by_id = {row.player_id: row for row in market.players}
    if set(selected_by_id) != set(market_by_id):
        raise CoverageIncomplete("Selected and market boards have different universes")
    result: list[ValuationGap] = []
    for player_id in sorted(selected_by_id):
        ours = selected_by_id[player_id]
        public = market_by_id[player_id]
        gap = public.reconciled_vorp - ours.reconciled_vorp
        signal = "SELL-HIGH" if gap > 0 else "BUY-LOW" if gap < 0 else "ALIGNED"
        result.append(
            ValuationGap(
                player_id=player_id,
                position=ours.position,
                selected_rank=ours.overall_rank,
                market_rank=public.overall_rank,
                rank_gap=public.overall_rank - ours.overall_rank,
                selected_tier=ours.tier,
                market_tier=public.tier,
                tier_gap=public.tier - ours.tier,
                selected_vorp=ours.reconciled_vorp,
                market_vorp=public.reconciled_vorp,
                value_gap=gap,
                signal=signal,
            )
        )
    return tuple(result)


def export_board_evidence(
    path: str | Path,
    *,
    selected_ranks: Sequence[SelectedRank],
    selected: ValueBoard,
    market: ValueBoard,
    gaps: Sequence[ValuationGap],
    manifest_id: str,
    selected_raw: ValueBoard | None = None,
    warnings: Sequence[str] = (),
    additional_evidence: Mapping[str, object] | None = None,
) -> Path:
    if selected.horizon != market.horizon:
        raise CoverageIncomplete("Cannot export mismatched board horizons")
    payload = {
        "schema_version": 1,
        "product": "TRADE ASSISTANT",
        "manifest_id": manifest_id,
        "horizon": selected.horizon,
        "selected_rank_evidence": [asdict(row) for row in selected_ranks],
        "selected_raw_board": asdict(selected_raw) if selected_raw else None,
        "selected_board": asdict(selected),
        "market_board": asdict(market),
        "valuation_gaps": [asdict(row) for row in gaps],
        "warnings": list(warnings),
        "additional_evidence": dict(additional_evidence or {}),
    }
    payload["evidence_hash"] = stable_hash(payload)
    return atomic_write_json(path, payload)
