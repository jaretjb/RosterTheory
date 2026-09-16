from __future__ import annotations

import csv
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from roster_theory.rankings import normalize_name


RECENCY_WEIGHTS: Mapping[int, float] = {
    2021: 0.08,
    2022: 0.15,
    2023: 0.21,
    2024: 0.26,
    2025: 0.30,
}
ACCURACY_URL = "https://www.fantasypros.com/nfl/accuracy/draft.php?year={year}"
_ROW_PATTERN = re.compile(
    r'\{"id":(?P<expert_id>\d+),"rank":(?P<rank>\d+),'
    r'"expert":(?P<expert>\{.*?\}|"(?:\\.|[^"\\])+")(?=,"qb":)',
)


@dataclass(frozen=True, slots=True)
class AnnualAccuracy:
    year: int
    expert_id: int
    expert_name: str
    overall_rank: int
    field_size: int
    overall_percentile: float


@dataclass(frozen=True, slots=True)
class RecencyAccuracy:
    expert_name: str
    score: float
    weighted_percentile: float
    years: int
    annual_ranks: tuple[tuple[int, int], ...]
    eligible: bool
    eligibility: str


def _expert_name(label: str) -> str:
    name, separator, publisher = label.partition(" - ")
    name = name.strip()
    if separator and name in {"Site Rankings", "Staff Rankings"}:
        return f"{name} ({publisher.strip()})"
    return name


def parse_accuracy_page(html: str, year: int) -> list[AnnualAccuracy]:
    raw_rows: list[tuple[int, int, str]] = []
    for match in _ROW_PATTERN.finditer(html):
        expert = json.loads(match.group("expert"))
        label = expert["label"] if isinstance(expert, dict) else expert
        raw_rows.append(
            (
                int(match.group("expert_id")),
                int(match.group("rank")),
                _expert_name(str(label)),
            )
        )
    if not raw_rows:
        raise ValueError(f"FantasyPros {year} draft-accuracy page contained no rows")
    ranks = [rank for _, rank, _ in raw_rows]
    expected = list(range(1, len(raw_rows) + 1))
    if ranks != expected:
        raise ValueError(
            f"FantasyPros {year} draft-accuracy ranks were incomplete or out of order"
        )
    field_size = len(raw_rows)
    return [
        AnnualAccuracy(
            year=year,
            expert_id=expert_id,
            expert_name=name,
            overall_rank=rank,
            field_size=field_size,
            overall_percentile=(
                1.0 - (rank - 1.0) / (field_size - 1.0) if field_size > 1 else 1.0
            ),
        )
        for expert_id, rank, name in raw_rows
    ]


def fetch_accuracy_history(
    years: Iterable[int] = RECENCY_WEIGHTS,
    *,
    minimum_interval_seconds: float = 1.0,
    timeout_seconds: float = 20.0,
) -> list[AnnualAccuracy]:
    rows: list[AnnualAccuracy] = []
    last_request = 0.0
    for year in years:
        elapsed = time.monotonic() - last_request
        if last_request and elapsed < minimum_interval_seconds:
            time.sleep(minimum_interval_seconds - elapsed)
        request = Request(
            ACCURACY_URL.format(year=year),
            headers={"Accept": "text/html", "User-Agent": "RosterTheory/0.1"},
        )
        try:
            with urlopen(request, timeout=timeout_seconds) as response:
                html = response.read().decode("utf-8", errors="replace")
        except (HTTPError, URLError, TimeoutError) as exc:
            raise RuntimeError(
                f"Unable to load FantasyPros {year} draft accuracy: {exc}"
            ) from exc
        last_request = time.monotonic()
        rows.extend(parse_accuracy_page(html, year))
    return rows


def write_accuracy_history(rows: Iterable[AnnualAccuracy], path: str | Path) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=(
                "year",
                "expert_id",
                "expert_name",
                "overall_rank",
                "field_size",
                "overall_percentile",
            ),
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "year": row.year,
                    "expert_id": row.expert_id,
                    "expert_name": row.expert_name,
                    "overall_rank": row.overall_rank,
                    "field_size": row.field_size,
                    "overall_percentile": f"{row.overall_percentile:.6f}",
                }
            )


def load_accuracy_history(path: str | Path) -> list[AnnualAccuracy]:
    with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    return [
        AnnualAccuracy(
            year=int(row["year"]),
            expert_id=int(row["expert_id"]),
            expert_name=row["expert_name"],
            overall_rank=int(row["overall_rank"]),
            field_size=int(row["field_size"]),
            overall_percentile=float(row["overall_percentile"]),
        )
        for row in rows
    ]


def recency_accuracy_scores(
    rows: Iterable[AnnualAccuracy],
    *,
    weights: Mapping[int, float] = RECENCY_WEIGHTS,
) -> dict[str, RecencyAccuracy]:
    grouped: dict[str, list[AnnualAccuracy]] = {}
    for row in rows:
        if row.year not in weights:
            continue
        grouped.setdefault(normalize_name(row.expert_name), []).append(row)

    scores: dict[str, RecencyAccuracy] = {}
    for key, observations in grouped.items():
        observations.sort(key=lambda row: row.year)
        years = len(observations)
        annual_ranks = tuple((row.year, row.overall_rank) for row in observations)
        if years == 1:
            eligible = False
            eligibility = "ineligible_one_year"
        elif years == 2:
            consecutive = observations[1].year == observations[0].year + 1
            top_ten = all(row.overall_rank <= 10 for row in observations)
            eligible = consecutive and top_ten
            eligibility = (
                "eligible_two_year_consecutive_top10"
                if eligible
                else "ineligible_two_year_gate"
            )
        else:
            eligible = True
            eligibility = "eligible_three_plus_years"

        weight_total = sum(weights[row.year] for row in observations)
        weighted_percentile = (
            sum(weights[row.year] * row.overall_percentile for row in observations)
            / weight_total
        )
        coverage = 0.80 + 0.20 * min(5, years) / 5
        scores[key] = RecencyAccuracy(
            expert_name=observations[-1].expert_name,
            score=weighted_percentile * coverage,
            weighted_percentile=weighted_percentile,
            years=years,
            annual_ranks=annual_ranks,
            eligible=eligible,
            eligibility=eligibility,
        )
    return scores
