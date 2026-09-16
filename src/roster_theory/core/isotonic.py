from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True, slots=True)
class MonotoneCurve:
    """Piecewise-linear, non-increasing value as rank gets worse."""

    points: tuple[tuple[float, float], ...]
    observation_count: int
    block_count: int

    def value(self, rank: float) -> float:
        if not self.points:
            raise ValueError("Cannot evaluate an empty monotone curve")
        if rank <= self.points[0][0]:
            return self.points[0][1]
        if rank >= self.points[-1][0]:
            return self.points[-1][1]
        for (left_x, left_y), (right_x, right_y) in zip(
            self.points, self.points[1:]
        ):
            if left_x <= rank <= right_x:
                fraction = (rank - left_x) / (right_x - left_x)
                return left_y + fraction * (right_y - left_y)
        raise AssertionError("Rank interpolation failed")


def fit_nonincreasing_curve(
    observations: Iterable[tuple[float, float]],
) -> MonotoneCurve:
    grouped: dict[float, list[float]] = {}
    count = 0
    for raw_rank, raw_value in observations:
        rank = float(raw_rank)
        value = float(raw_value)
        if rank <= 0:
            raise ValueError("Overall ranks must be positive")
        grouped.setdefault(rank, []).append(value)
        count += 1
    if not grouped:
        raise ValueError("At least one rank/value observation is required")
    blocks: list[dict[str, float]] = []
    for rank in sorted(grouped):
        values = grouped[rank]
        blocks.append(
            {
                "rank_sum": rank * len(values),
                "value_sum": sum(values),
                "count": float(len(values)),
            }
        )
        while len(blocks) >= 2:
            left, right = blocks[-2], blocks[-1]
            if left["value_sum"] / left["count"] >= right["value_sum"] / right["count"]:
                break
            blocks[-2:] = [
                {
                    "rank_sum": left["rank_sum"] + right["rank_sum"],
                    "value_sum": left["value_sum"] + right["value_sum"],
                    "count": left["count"] + right["count"],
                }
            ]
    points = tuple(
        (
            block["rank_sum"] / block["count"],
            block["value_sum"] / block["count"],
        )
        for block in blocks
    )
    return MonotoneCurve(points, count, len(blocks))

