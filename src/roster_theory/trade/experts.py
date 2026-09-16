from __future__ import annotations

import csv
import json
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


INSEASON_ACCURACY_URL = "https://www.fantasypros.com/nfl/accuracy/?year={year}"
DEFAULT_YEARS = (2021, 2022, 2023, 2024, 2025)
DEFAULT_RECENCY_WEIGHTS: Mapping[int, float] = {
    2021: 0.08,
    2022: 0.15,
    2023: 0.21,
    2024: 0.26,
    2025: 0.30,
}
SKILL_POSITIONS = ("QB", "RB", "WR", "TE")
_ROW_PATTERN = re.compile(
    r'\{"id":(?P<expert_id>\d+),"rank":(?P<overall>\d+),'
    r'"expert":(?P<expert>\{.*?\}|"(?:\\.|[^"\\])+")'
    r',"qb":(?P<qb>null|\d+),"rb":(?P<rb>null|\d+),'
    r'"wr":(?P<wr>null|\d+),"te":(?P<te>null|\d+),'
)


@dataclass(frozen=True, slots=True)
class InSeasonAccuracy:
    year: int
    expert_id: str
    expert_name: str
    source_name: str
    overall_rank: int
    qb_rank: int | None
    rb_rank: int | None
    wr_rank: int | None
    te_rank: int | None
    field_size: int
    overall_percentile: float
    source_url: str
    retrieved_at: str


@dataclass(frozen=True, slots=True)
class CurrentExpert:
    expert_id: str
    name: str
    source_name: str
    position_updates: tuple[tuple[str, str], ...]
    latest_weekly_accuracy: tuple[tuple[str, int], ...]
    prior_weekly_accuracy: tuple[tuple[str, int], ...]

    def update_for(self, position: str) -> str | None:
        return dict(self.position_updates).get(position.upper())


@dataclass(frozen=True, slots=True)
class ExpertScore:
    expert_id: str
    expert_name: str
    source_name: str
    score: float
    weighted_percentile: float
    coverage: float
    seasons: int
    annual_ranks: tuple[tuple[int, int], ...]


@dataclass(frozen=True, slots=True)
class SelectedExpert:
    expert_id: str
    expert_name: str
    source_name: str
    weight: float
    historical_score: float
    seasons: int
    annual_ranks: tuple[tuple[int, int], ...]
    position_updates: tuple[tuple[str, str], ...]


def _rank(value: str) -> int | None:
    return None if value == "null" else int(value)


def _expert_label(value: str) -> tuple[str, str]:
    decoded = json.loads(value)
    label = str(decoded.get("label") if isinstance(decoded, dict) else decoded)
    name, separator, source = label.partition(" - ")
    return name.strip(), source.strip() if separator else "Unknown"


def parse_inseason_accuracy_page(
    html: str,
    year: int,
    *,
    retrieved_at: str,
    source_url: str | None = None,
) -> tuple[InSeasonAccuracy, ...]:
    parsed: list[dict[str, Any]] = []
    for match in _ROW_PATTERN.finditer(html):
        name, source = _expert_label(match.group("expert"))
        parsed.append(
            {
                "expert_id": match.group("expert_id"),
                "expert_name": name,
                "source_name": source,
                "overall_rank": int(match.group("overall")),
                "qb_rank": _rank(match.group("qb")),
                "rb_rank": _rank(match.group("rb")),
                "wr_rank": _rank(match.group("wr")),
                "te_rank": _rank(match.group("te")),
            }
        )
    if not parsed:
        raise ValueError(f"FantasyPros {year} weekly in-season page contained no rows")
    ranks = [row["overall_rank"] for row in parsed]
    if ranks != list(range(1, len(parsed) + 1)):
        raise ValueError(
            f"FantasyPros {year} weekly in-season ranks were incomplete or out of order"
        )
    field_size = len(parsed)
    url = source_url or INSEASON_ACCURACY_URL.format(year=year)
    return tuple(
        InSeasonAccuracy(
            year=year,
            field_size=field_size,
            overall_percentile=(
                1.0 - (row["overall_rank"] - 1.0) / (field_size - 1.0)
                if field_size > 1
                else 1.0
            ),
            source_url=url,
            retrieved_at=retrieved_at,
            **row,
        )
        for row in parsed
    )


def fetch_inseason_accuracy(
    years: Iterable[int] = DEFAULT_YEARS,
    *,
    minimum_interval_seconds: float = 1.0,
    timeout_seconds: float = 20.0,
    retrieved_at: str | None = None,
) -> tuple[InSeasonAccuracy, ...]:
    captured = retrieved_at or datetime.now(timezone.utc).isoformat()
    result: list[InSeasonAccuracy] = []
    last_request = 0.0
    for year in years:
        elapsed = time.monotonic() - last_request
        if last_request and elapsed < minimum_interval_seconds:
            time.sleep(minimum_interval_seconds - elapsed)
        url = INSEASON_ACCURACY_URL.format(year=year)
        request = Request(
            url,
            headers={"Accept": "text/html", "User-Agent": "RosterTheory/0.1"},
        )
        try:
            with urlopen(request, timeout=timeout_seconds) as response:
                html = response.read().decode("utf-8", errors="replace")
        except (HTTPError, URLError, TimeoutError) as exc:
            raise RuntimeError(
                f"Unable to load FantasyPros {year} weekly in-season accuracy: {exc}"
            ) from exc
        last_request = time.monotonic()
        result.extend(
            parse_inseason_accuracy_page(
                html, year, retrieved_at=captured, source_url=url
            )
        )
    return tuple(result)


_ACCURACY_FIELDS = (
    "year",
    "expert_id",
    "expert_name",
    "source_name",
    "overall_rank",
    "qb_rank",
    "rb_rank",
    "wr_rank",
    "te_rank",
    "field_size",
    "overall_percentile",
    "source_url",
    "retrieved_at",
)


def write_inseason_accuracy(
    rows: Iterable[InSeasonAccuracy], path: str | Path
) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=_ACCURACY_FIELDS)
        writer.writeheader()
        for row in rows:
            values = {field: getattr(row, field) for field in _ACCURACY_FIELDS}
            values["overall_percentile"] = f"{row.overall_percentile:.6f}"
            writer.writerow(values)
    return target


def load_inseason_accuracy(path: str | Path) -> tuple[InSeasonAccuracy, ...]:
    with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
        rows = tuple(csv.DictReader(handle))
    return tuple(
        InSeasonAccuracy(
            year=int(row["year"]),
            expert_id=str(row["expert_id"]),
            expert_name=str(row["expert_name"]),
            source_name=str(row["source_name"]),
            overall_rank=int(row["overall_rank"]),
            qb_rank=int(row["qb_rank"]) if row["qb_rank"] else None,
            rb_rank=int(row["rb_rank"]) if row["rb_rank"] else None,
            wr_rank=int(row["wr_rank"]) if row["wr_rank"] else None,
            te_rank=int(row["te_rank"]) if row["te_rank"] else None,
            field_size=int(row["field_size"]),
            overall_percentile=float(row["overall_percentile"]),
            source_url=str(row["source_url"]),
            retrieved_at=str(row["retrieved_at"]),
        )
        for row in rows
    )


def normalize_current_experts(value: Mapping[str, Any]) -> tuple[CurrentExpert, ...]:
    result: list[CurrentExpert] = []
    for raw in value.get("experts") or ():
        if not isinstance(raw, Mapping) or raw.get("expert_id") is None:
            continue
        position_updates = raw.get("positions") or {}
        weekly = raw.get("accuracy_weekly") or {}
        prior = raw.get("accuracy_weekly_last_season") or {}
        result.append(
            CurrentExpert(
                expert_id=str(raw["expert_id"]),
                name=str(raw.get("name") or raw["expert_id"]).strip(),
                source_name=str(raw.get("source") or "Unknown").strip(),
                position_updates=tuple(
                    sorted((str(key).upper(), str(item)) for key, item in position_updates.items())
                ),
                latest_weekly_accuracy=tuple(
                    sorted((str(key).upper(), int(item)) for key, item in weekly.items())
                ),
                prior_weekly_accuracy=tuple(
                    sorted((str(key).upper(), int(item)) for key, item in prior.items())
                ),
            )
        )
    return tuple(sorted(result, key=lambda item: int(item.expert_id)))


def accuracy_from_expert_directory(
    value: Mapping[str, Any],
    *,
    retrieved_at: str,
    source_url: str,
    year: int | None = None,
) -> tuple[InSeasonAccuracy, ...]:
    """Extract one full annual weekly-accuracy table from expert metadata.

    FantasyPros exposes the latest season under ``accuracy_weekly`` and the
    immediately preceding season under ``accuracy_weekly_last_season``. Rows
    without an overall result did not qualify for that annual competition.
    """
    current_year = int(value.get("accuracy_weekly_season") or 0)
    prior_year = int(value.get("accuracy_weekly_last_season") or 0)
    target_year = year or current_year
    if target_year == current_year:
        field = "accuracy_weekly"
    elif target_year == prior_year:
        field = "accuracy_weekly_last_season"
    else:
        raise ValueError(
            f"Expert directory does not contain weekly accuracy for {target_year}"
        )
    parsed: list[dict[str, Any]] = []
    for raw in value.get("experts") or ():
        if not isinstance(raw, Mapping) or raw.get("expert_id") is None:
            continue
        ranks = raw.get(field)
        if not isinstance(ranks, Mapping) or ranks.get("ALL") is None:
            continue
        parsed.append(
            {
                "expert_id": str(raw["expert_id"]),
                "expert_name": str(raw.get("name") or raw["expert_id"]).strip(),
                "source_name": str(raw.get("source") or "Unknown").strip(),
                "overall_rank": int(ranks["ALL"]),
                "qb_rank": int(ranks["QB"]) if ranks.get("QB") is not None else None,
                "rb_rank": int(ranks["RB"]) if ranks.get("RB") is not None else None,
                "wr_rank": int(ranks["WR"]) if ranks.get("WR") is not None else None,
                "te_rank": int(ranks["TE"]) if ranks.get("TE") is not None else None,
            }
        )
    if not parsed:
        raise ValueError(f"FantasyPros expert directory has no {target_year} weekly accuracy")
    field_size = max(row["overall_rank"] for row in parsed)
    ranks = [row["overall_rank"] for row in parsed]
    if len(ranks) != len(set(ranks)):
        raise ValueError(
            f"FantasyPros {target_year} weekly accuracy contains duplicate ranks"
        )
    return tuple(
        InSeasonAccuracy(
            year=target_year,
            field_size=field_size,
            overall_percentile=(
                1.0 - (row["overall_rank"] - 1.0) / (field_size - 1.0)
                if field_size > 1
                else 1.0
            ),
            source_url=source_url,
            retrieved_at=retrieved_at,
            **row,
        )
        for row in sorted(parsed, key=lambda item: item["overall_rank"])
    )


def score_experts(
    rows: Iterable[InSeasonAccuracy],
    *,
    weights: Mapping[int, float] = DEFAULT_RECENCY_WEIGHTS,
    coverage_floor: float = 0.80,
    minimum_seasons: int = 2,
) -> tuple[ExpertScore, ...]:
    if not 0.0 <= coverage_floor <= 1.0:
        raise ValueError("coverage_floor must be between zero and one")
    grouped: dict[str, list[InSeasonAccuracy]] = {}
    for row in rows:
        if row.year in weights:
            grouped.setdefault(row.expert_id, []).append(row)
    scored: list[ExpertScore] = []
    available_years = len(weights)
    for expert_id, observations in grouped.items():
        observations.sort(key=lambda row: row.year)
        if len(observations) < minimum_seasons:
            continue
        denominator = sum(float(weights[row.year]) for row in observations)
        percentile = sum(
            float(weights[row.year]) * row.overall_percentile for row in observations
        ) / denominator
        coverage = coverage_floor + (1.0 - coverage_floor) * (
            len(observations) / available_years
        )
        latest = observations[-1]
        scored.append(
            ExpertScore(
                expert_id=expert_id,
                expert_name=latest.expert_name,
                source_name=latest.source_name,
                score=percentile * coverage,
                weighted_percentile=percentile,
                coverage=coverage,
                seasons=len(observations),
                annual_ranks=tuple(
                    (row.year, row.overall_rank) for row in observations
                ),
            )
        )
    return tuple(sorted(scored, key=lambda row: (-row.score, row.expert_id)))


def _parse_provider_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def select_current_experts(
    scores: Sequence[ExpertScore],
    current: Sequence[CurrentExpert],
    *,
    now: datetime,
    pool_size: int = 5,
    maximum_source_count: int = 2,
    freshness_hours: float = 48.0,
    required_positions: Sequence[str] = SKILL_POSITIONS,
) -> tuple[SelectedExpert, ...]:
    current_by_id = {item.expert_id: item for item in current}
    selected: list[tuple[ExpertScore, CurrentExpert]] = []
    sources: dict[str, int] = {}
    normalized_now = now.astimezone(timezone.utc)
    for score in scores:
        active = current_by_id.get(score.expert_id)
        if active is None:
            continue
        updates = dict(active.position_updates)
        if any(position not in updates for position in required_positions):
            continue
        if any(
            (normalized_now - _parse_provider_time(updates[position])).total_seconds()
            > freshness_hours * 3600
            for position in required_positions
        ):
            continue
        source = active.source_name.casefold()
        if sources.get(source, 0) >= maximum_source_count:
            continue
        selected.append((score, active))
        sources[source] = sources.get(source, 0) + 1
        if len(selected) == pool_size:
            break
    if len(selected) < pool_size:
        raise ValueError(
            f"Only {len(selected)} historically eligible, fresh experts satisfy a pool of {pool_size}"
        )
    score_total = sum(item.score for item, _ in selected)
    return tuple(
        SelectedExpert(
            expert_id=score.expert_id,
            expert_name=active.name,
            source_name=active.source_name,
            weight=score.score / score_total,
            historical_score=score.score,
            seasons=score.seasons,
            annual_ranks=score.annual_ranks,
            position_updates=active.position_updates,
        )
        for score, active in selected
    )


def selection_holdout_score(
    rows: Sequence[InSeasonAccuracy],
    *,
    weight_style: str,
    pool_size: int,
    coverage_floor: float,
) -> tuple[float, int]:
    outcomes: list[float] = []
    for target_year in sorted({row.year for row in rows})[2:]:
        training_years = tuple(range(min(row.year for row in rows), target_year))
        if weight_style == "equal":
            weights = {year: 1.0 for year in training_years}
        elif weight_style == "linear":
            weights = {year: index + 1.0 for index, year in enumerate(training_years)}
        elif weight_style == "recent":
            weights = {
                year: DEFAULT_RECENCY_WEIGHTS.get(year, index + 1.0)
                for index, year in enumerate(training_years)
            }
        else:
            raise ValueError(f"Unknown weight style: {weight_style}")
        scores = score_experts(
            (row for row in rows if row.year < target_year),
            weights=weights,
            coverage_floor=coverage_floor,
        )
        target = {row.expert_id: row for row in rows if row.year == target_year}
        eligible = [score for score in scores if score.expert_id in target][:pool_size]
        if len(eligible) < pool_size:
            continue
        outcomes.append(
            sum(target[score.expert_id].overall_percentile for score in eligible)
            / pool_size
        )
    return (sum(outcomes) / len(outcomes), len(outcomes)) if outcomes else (0.0, 0)
