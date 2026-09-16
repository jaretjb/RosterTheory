from __future__ import annotations

from dataclasses import asdict, dataclass
from math import sqrt
from pathlib import Path
from statistics import mean
from typing import Mapping, Sequence

from roster_theory.core.provenance import stable_hash
from roster_theory.providers.cache import atomic_write_json
from roster_theory.trade.horizons import parse_utc


@dataclass(frozen=True, slots=True)
class DraftProxyForecast:
    season: int
    week: int
    player_id: str
    position: str
    draft_rank: float
    weekly_rank: float
    adjusted_weekly_rank: float
    actual_points: float
    actual_lineup_value: float
    forecast_cutoff: str
    draft_published_at: str
    weekly_published_at: str
    outcome_available_at: str


@dataclass(frozen=True, slots=True)
class BacktestMetric:
    holdout_season: int
    week: int
    position: str
    signal_mode: str
    draft_weight: float
    sample_size: int
    point_mae: float
    point_standard_error: float
    lineup_value_mae: float
    ordering_error: float
    selected_on_prior_seasons: bool


@dataclass(frozen=True, slots=True)
class DraftProxyBacktest:
    label: str
    weights: tuple[float, ...]
    metrics: tuple[BacktestMetric, ...]
    selected_weights: tuple[tuple[int, int, str, str, float], ...]
    draft_signal_decay: tuple[tuple[int, str, str, float], ...]
    warnings: tuple[str, ...]
    evidence_hash: str


@dataclass(frozen=True, slots=True)
class HorizonForecast:
    season: int
    week: int
    player_id: str
    position: str
    long_term_rank: float
    weekly_rank: float
    projection_rank: float
    actual_points: float
    actual_lineup_value: float
    forecast_cutoff: str
    long_term_published_at: str
    weekly_published_at: str
    projection_published_at: str
    outcome_available_at: str


@dataclass(frozen=True, slots=True)
class CandidateMetric:
    holdout_season: int
    week: int
    position: str
    candidate: str
    sample_size: int
    point_mae: float
    point_standard_error: float
    lineup_value_mae: float
    ordering_error: float
    selected_on_prior_seasons: bool


@dataclass(frozen=True, slots=True)
class RollingOriginBacktest:
    metrics: tuple[CandidateMetric, ...]
    selected_candidates: tuple[tuple[int, int, str, str], ...]
    warnings: tuple[str, ...]
    evidence_hash: str


def _validate_cutoffs(rows: Sequence[DraftProxyForecast]) -> None:
    for row in rows:
        cutoff = parse_utc(row.forecast_cutoff)
        if parse_utc(row.draft_published_at) > cutoff:
            raise ValueError("Draft rank was published after forecast cutoff")
        if parse_utc(row.weekly_published_at) > cutoff:
            raise ValueError("Weekly rank was published after forecast cutoff")
        if parse_utc(row.outcome_available_at) <= cutoff:
            raise ValueError("Outcome must become available after forecast cutoff")
        if min(row.draft_rank, row.weekly_rank, row.adjusted_weekly_rank) <= 0:
            raise ValueError("Ranks must be positive")


def _rank_slot_values(rows: Sequence[DraftProxyForecast]) -> dict[int, float]:
    return {
        rank: value
        for rank, value in enumerate(
            sorted((row.actual_points for row in rows), reverse=True), 1
        )
    }


def _ordering_error(
    predicted: Mapping[tuple[int, str], float],
    actual: Mapping[tuple[int, str], float],
) -> float:
    player_ids = sorted(predicted)
    pairs = 0
    inversions = 0
    for index, first in enumerate(player_ids):
        for second in player_ids[index + 1 :]:
            actual_delta = actual[first] - actual[second]
            predicted_delta = predicted[first] - predicted[second]
            if actual_delta == 0:
                continue
            pairs += 1
            if actual_delta * predicted_delta < 0:
                inversions += 1
    return inversions / pairs if pairs else 0.0


def _score_candidate(
    rows: Sequence[HorizonForecast],
    scores: Mapping[tuple[int, str], float],
    *,
    holdout_season: int,
    candidate: str,
    selected: bool,
) -> CandidateMetric:
    key = lambda row: (row.season, row.player_id)
    ordered = sorted(rows, key=lambda row: (scores[key(row)], key(row)))
    predicted_rank = {key(row): rank for rank, row in enumerate(ordered, 1)}
    slots = {
        rank: value
        for rank, value in enumerate(
            sorted((row.actual_points for row in rows), reverse=True), 1
        )
    }
    replacement = sorted((row.actual_points for row in rows), reverse=True)[
        min(len(rows), max(1, int(round(len(rows) * 0.60)))) - 1
    ]
    point_errors: list[float] = []
    lineup_errors: list[float] = []
    for row in rows:
        predicted_points = slots[predicted_rank[key(row)]]
        point_errors.append(abs(predicted_points - row.actual_points))
        lineup_errors.append(
            abs(max(0.0, predicted_points - replacement) - row.actual_lineup_value)
        )
    point_mae = mean(point_errors)
    standard_error = (
        sqrt(sum((value - point_mae) ** 2 for value in point_errors) / (len(point_errors) - 1))
        / sqrt(len(point_errors))
        if len(point_errors) > 1
        else 0.0
    )
    return CandidateMetric(
        holdout_season=holdout_season,
        week=rows[0].week,
        position=rows[0].position,
        candidate=candidate,
        sample_size=len(rows),
        point_mae=point_mae,
        point_standard_error=standard_error,
        lineup_value_mae=mean(lineup_errors),
        ordering_error=_ordering_error(
            scores, {key(row): -row.actual_points for row in rows}
        ),
        selected_on_prior_seasons=selected,
    )


def run_rolling_origin_backtest(
    rows: Sequence[HorizonForecast],
    *,
    blend_weights: Sequence[float] = (0.25, 0.5, 0.75),
) -> RollingOriginBacktest:
    if not rows:
        raise ValueError("Rolling-origin backtest requires forecast rows")
    weights = tuple(sorted({float(value) for value in blend_weights}))
    if any(value <= 0.0 or value >= 1.0 for value in weights):
        raise ValueError("Candidate blend weights must be strictly between zero and one")
    for row in rows:
        cutoff = parse_utc(row.forecast_cutoff)
        for field in (
            "long_term_published_at",
            "weekly_published_at",
            "projection_published_at",
        ):
            if parse_utc(getattr(row, field)) > cutoff:
                raise ValueError(f"{field} is after forecast cutoff")
        if parse_utc(row.outcome_available_at) <= cutoff:
            raise ValueError("Outcome must become available after forecast cutoff")
        if min(row.long_term_rank, row.weekly_rank, row.projection_rank) <= 0:
            raise ValueError("Ranks must be positive")

    def candidates(
        group: Sequence[HorizonForecast],
    ) -> dict[str, dict[tuple[int, str], float]]:
        key = lambda row: (row.season, row.player_id)
        result = {
            "LONG_TERM_ONLY": {key(row): row.long_term_rank for row in group},
            "WEEKLY_ONLY": {key(row): row.weekly_rank for row in group},
            "PROJECTION_ONLY": {key(row): row.projection_rank for row in group},
        }
        for weight in weights:
            result[f"BLEND_LONG_TERM_{weight:.2f}"] = {
                key(row): weight * row.long_term_rank
                + (1.0 - weight) * row.weekly_rank
                for row in group
            }
        return result

    seasons = sorted({row.season for row in rows})
    if len(seasons) < 2:
        raise ValueError("Rolling-origin evaluation requires at least two seasons")
    metrics: list[CandidateMetric] = []
    selected_candidates: list[tuple[int, int, str, str]] = []
    for holdout in seasons[1:]:
        train = [row for row in rows if row.season < holdout]
        test = [row for row in rows if row.season == holdout]
        for week, position in sorted({(row.week, row.position) for row in test}):
            train_group = [row for row in train if row.week == week and row.position == position]
            test_group = [row for row in test if row.week == week and row.position == position]
            if not train_group or not test_group:
                continue
            training = [
                _score_candidate(
                    train_group,
                    scores,
                    holdout_season=holdout,
                    candidate=name,
                    selected=False,
                )
                for name, scores in candidates(train_group).items()
            ]
            winner = min(
                training,
                key=lambda item: (item.point_mae, item.lineup_value_mae, item.candidate),
            ).candidate
            selected_candidates.append((holdout, week, position, winner))
            metrics.extend(
                _score_candidate(
                    test_group,
                    scores,
                    holdout_season=holdout,
                    candidate=name,
                    selected=name == winner,
                )
                for name, scores in candidates(test_group).items()
            )
    if not metrics:
        raise ValueError("No matching rolling-origin train/holdout groups")
    payload = {
        "metrics": [asdict(row) for row in metrics],
        "selected_candidates": selected_candidates,
        "warnings": ["BLENDED remains disabled unless holdout evidence passes a separate gate"],
    }
    return RollingOriginBacktest(
        metrics=tuple(metrics),
        selected_candidates=tuple(selected_candidates),
        warnings=tuple(payload["warnings"]),
        evidence_hash=stable_hash(payload),
    )


def _group_metric(
    rows: Sequence[DraftProxyForecast],
    *,
    holdout_season: int,
    signal_mode: str,
    draft_weight: float,
    selected: bool,
) -> BacktestMetric:
    weekly_field = "weekly_rank" if signal_mode == "RAW" else "adjusted_weekly_rank"
    key = lambda row: (row.season, row.player_id)
    blended = {
        key(row): draft_weight * row.draft_rank
        + (1.0 - draft_weight) * getattr(row, weekly_field)
        for row in rows
    }
    ordered = sorted(rows, key=lambda row: (blended[key(row)], key(row)))
    predicted_rank = {key(row): rank for rank, row in enumerate(ordered, 1)}
    slots = _rank_slot_values(rows)
    replacement = sorted((row.actual_points for row in rows), reverse=True)[
        min(len(rows), max(1, int(round(len(rows) * 0.60)))) - 1
    ]
    point_errors: list[float] = []
    lineup_errors: list[float] = []
    for row in rows:
        predicted_points = slots[predicted_rank[key(row)]]
        point_errors.append(abs(predicted_points - row.actual_points))
        predicted_lineup = max(0.0, predicted_points - replacement)
        lineup_errors.append(abs(predicted_lineup - row.actual_lineup_value))
    point_mae = mean(point_errors)
    standard_error = (
        sqrt(sum((value - point_mae) ** 2 for value in point_errors) / (len(point_errors) - 1))
        / sqrt(len(point_errors))
        if len(point_errors) > 1
        else 0.0
    )
    return BacktestMetric(
        holdout_season=holdout_season,
        week=rows[0].week,
        position=rows[0].position,
        signal_mode=signal_mode,
        draft_weight=draft_weight,
        sample_size=len(rows),
        point_mae=point_mae,
        point_standard_error=standard_error,
        lineup_value_mae=mean(lineup_errors),
        ordering_error=_ordering_error(
            blended, {key(row): -row.actual_points for row in rows}
        ),
        selected_on_prior_seasons=selected,
    )


def run_draft_proxy_backtest(
    rows: Sequence[DraftProxyForecast],
    *,
    weights: Sequence[float] = tuple(index / 10 for index in range(11)),
) -> DraftProxyBacktest:
    if not rows:
        raise ValueError("Draft-proxy backtest requires forecast rows")
    normalized_weights = tuple(sorted({float(value) for value in weights}))
    if not normalized_weights or normalized_weights[0] != 0.0 or normalized_weights[-1] != 1.0:
        raise ValueError("Weight grid must include weekly-only 0 and Draft-only 1")
    if any(value < 0.0 or value > 1.0 for value in normalized_weights):
        raise ValueError("Draft weights must be between zero and one")
    _validate_cutoffs(rows)
    seasons = sorted({row.season for row in rows})
    if len(seasons) < 2:
        raise ValueError("Rolling-origin evaluation requires at least two seasons")
    metrics: list[BacktestMetric] = []
    selected_weights: list[tuple[int, int, str, str, float]] = []
    for holdout in seasons[1:]:
        train = [row for row in rows if row.season < holdout]
        test = [row for row in rows if row.season == holdout]
        keys = sorted({(row.week, row.position) for row in test})
        for week, position in keys:
            train_group = [row for row in train if row.week == week and row.position == position]
            test_group = [row for row in test if row.week == week and row.position == position]
            if not train_group or not test_group:
                continue
            for signal_mode in ("RAW", "MATCHUP_BYE_AWARE"):
                training_metrics = [
                    _group_metric(
                        train_group,
                        holdout_season=holdout,
                        signal_mode=signal_mode,
                        draft_weight=weight,
                        selected=False,
                    )
                    for weight in normalized_weights
                ]
                winner = min(
                    training_metrics,
                    key=lambda item: (item.point_mae, item.lineup_value_mae, item.draft_weight),
                ).draft_weight
                selected_weights.append((holdout, week, position, signal_mode, winner))
                metrics.extend(
                    _group_metric(
                        test_group,
                        holdout_season=holdout,
                        signal_mode=signal_mode,
                        draft_weight=weight,
                        selected=weight == winner,
                    )
                    for weight in normalized_weights
                )
    if not metrics:
        raise ValueError("No matching rolling-origin train/holdout groups")
    decay: list[tuple[int, str, str, float]] = []
    for week, position, mode in sorted(
        {(row.week, row.position, row.signal_mode) for row in metrics}
    ):
        selected = [
            row.draft_weight
            for row in metrics
            if row.week == week
            and row.position == position
            and row.signal_mode == mode
            and row.selected_on_prior_seasons
        ]
        if selected:
            decay.append((week, position, mode, mean(selected)))
    payload = {
        "label": "DRAFT_PROXY",
        "weights": normalized_weights,
        "metrics": [asdict(row) for row in metrics],
        "selected_weights": selected_weights,
        "draft_signal_decay": decay,
        "warnings": [
            "Final Draft rank proxies for unavailable historical point-in-time ROS rank",
            "Results do not validate a true ROS/weekly blend",
        ],
    }
    return DraftProxyBacktest(
        label="DRAFT_PROXY",
        weights=normalized_weights,
        metrics=tuple(metrics),
        selected_weights=tuple(selected_weights),
        draft_signal_decay=tuple(decay),
        warnings=tuple(payload["warnings"]),
        evidence_hash=stable_hash(payload),
    )


def write_draft_proxy_backtest(path: str | Path, result: DraftProxyBacktest) -> Path:
    payload = asdict(result)
    payload["schema_version"] = 1
    payload["product"] = "TRADE ASSISTANT"
    return atomic_write_json(path, payload)
