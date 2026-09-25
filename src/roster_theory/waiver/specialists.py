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
