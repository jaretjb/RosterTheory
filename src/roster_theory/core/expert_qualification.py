"""Historical qualification shared by the three assistant ranking workflows."""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass


HISTORY_WEIGHTS = (8, 15, 21, 26, 30)
MAXIMUM_WEIGHTED_AVERAGE_RANK = 20
MINIMUM_HISTORICAL_SEASONS = 2


@dataclass(frozen=True)
class HistoricalQualification:
    weighted_average_rank: float | None
    issue: str | None


def qualify_expert(
    annual_ranks: Iterable[tuple[int, int]],
    years: Sequence[int],
) -> HistoricalQualification:
    weights = dict(zip(years, HISTORY_WEIGHTS, strict=True))
    observed = {}
    for year, rank in annual_ranks:
        if year not in weights:
            continue
        if year in observed or isinstance(rank, bool) or not isinstance(rank, int) or rank < 1:
            return HistoricalQualification(None, "invalid_historical_accuracy")
        observed[year] = rank
    denominator = sum(weights[year] for year in observed)
    numerator = sum(weights[year] * rank for year, rank in observed.items())
    average = numerator / denominator if denominator else None
    if len(observed) < MINIMUM_HISTORICAL_SEASONS:
        issue = "insufficient_historical_accuracy"
    elif numerator > denominator * MAXIMUM_WEIGHTED_AVERAGE_RANK:
        issue = "historical_rank_above_quality_cutoff"
    else:
        issue = None
    return HistoricalQualification(average, issue)
