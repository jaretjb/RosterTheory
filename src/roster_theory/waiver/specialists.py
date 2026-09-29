"""Universal, manually chosen specialist policy; not historical calibration."""
from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True, slots=True)
class SpecialistPerformance:
    score: float | None
    weekly_advantage: float | None
    production_advantage: float | None
    confidence: float
    production_weight: float
    prior_games: float
    status: str


def specialist_performance(
    *, add_rank: int | None, drop_rank: int | None,
    add_points: float | None, drop_points: float | None,
    add_samples: int | None, drop_samples: int | None,
    weight: float, prior_games: float,
) -> SpecialistPerformance:
    """Bounded weekly-rank/season-total comparison, invariant to scoring scale.

    Total production (not PPG) is retained. The smaller observed game count
    shrinks its influence by n/(n+prior_games); bye weeks are not zero games.
    Missing samples are unknown, not a full season or a zero-point performance.
    """
    if not isfinite(weight) or not 0 < weight < 1 or not isfinite(prior_games) or prior_games <= 0:
        raise ValueError("Specialist weight must be in (0,1) and prior games finite/positive")
    weekly = ((drop_rank - add_rank) / 15
              if all(r is not None and isfinite(r) and 1 <= r <= 16 for r in (add_rank, drop_rank))
              else None)
    points_valid = all(p is not None and isfinite(p) for p in (add_points, drop_points))
    samples_valid = all(isinstance(n, int) and not isinstance(n, bool) and n > 0
                        for n in (add_samples, drop_samples))
    if weekly is None or not points_valid or not samples_valid:
        return SpecialistPerformance(None, weekly, None, 0, weight, prior_games,
                                     "INCOMPLETE_RANK_TOTAL_OR_GAME_SAMPLE")
    scale = max(abs(add_points), abs(drop_points))
    production = (add_points - drop_points) / scale if scale else 0.0
    production = max(-1.0, min(1.0, production))
    n = min(add_samples, drop_samples)
    confidence = n / (n + prior_games)
    score = (1 - weight) * weekly + weight * confidence * production
    return SpecialistPerformance(round(score, 6), weekly, production, confidence,
                                 weight, prior_games, "COMPLETE")


def raw_specialist_performance(
    *, position: str, add_rank: int | None, drop_rank: int | None,
    season_add_rank: int | None, season_drop_rank: int | None,
    recent_add_rank: int | None, recent_drop_rank: int | None,
    ros_add_rank: int | None, ros_drop_rank: int | None,
    add_points: float | None, drop_points: float | None,
    current_week_delta: float, weight: float,
) -> SpecialistPerformance:
    """WA-027's original score, with the saved weight in raw point units.

    This is only for policies saved before NORMALIZED_SEASON_V1. The caller
    independently checks freshness, league scope, and the current safety gates.
    """
    if position not in {"K", "DST"} or not isfinite(weight) or weight < 0:
        raise ValueError("Raw specialist method requires K/DST and a nonnegative finite weight")
    weekly_valid = (add_rank is not None and isinstance(add_rank, int)
                    and not isinstance(add_rank, bool) and 1 <= add_rank <= 16)
    rank_context = any(rank is not None for rank in (season_add_rank, recent_add_rank, ros_add_rank))
    points_valid = (weight == 0 or (add_points is not None and drop_points is not None
                                   and isfinite(add_points) and isfinite(drop_points)))
    if not weekly_valid or not rank_context or not points_valid:
        return SpecialistPerformance(None, None, None, 1.0, weight, 0.0,
                                     "INCOMPLETE_RANK_OR_SEASON_TOTAL")

    def advantage(add: int | None, drop: int | None) -> float:
        return float(drop - add) if add is not None and drop is not None else 0.0

    weekly = advantage(add_rank, drop_rank)
    season = advantage(season_add_rank, season_drop_rank)
    recent = advantage(recent_add_rank, recent_drop_rank)
    ros = advantage(ros_add_rank, ros_drop_rank)
    production = float(add_points - drop_points) if add_points is not None and drop_points is not None else 0.0
    if position == "K":
        score = (5.0 * weekly + season + 0.5 * recent + 0.25 * ros
                 + weight * production + (15.0 if season_add_rank == 1 else 0.0))
    else:
        score = (3.0 * weekly + season + 0.5 * recent + 0.5 * ros
                 + weight * production + 2.0 * current_week_delta)
    return SpecialistPerformance(round(score, 3), weekly, production, 1.0,
                                 weight, 0.0, "COMPLETE")
