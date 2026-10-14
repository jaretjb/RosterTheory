"""Historical weekly-accuracy facts, independent of any assistant's policy."""

from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence
from urllib.parse import urlparse

from roster_theory.core.errors import CoverageIncomplete
from roster_theory.core.provenance import stable_hash


@dataclass(frozen=True, slots=True)
class AnnualExpertAccuracy:
    year: int
    expert_id: str
    expert_name: str
    source_name: str
    overall_rank: int
    field_size: int
    source_url: str
    qb_rank: int | None = None
    rb_rank: int | None = None
    wr_rank: int | None = None
    te_rank: int | None = None
    retrieved_at: str = ""


def load_weekly_accuracy_history(path: str | Path, years: Sequence[int], *, evidence_dir=None):
    """Read published annual facts without importing another feature's selector."""
    target = Path(path)
    if not target.is_file():
        raise CoverageIncomplete(f"Five-season weekly expert accuracy is unavailable: {target}")
    with target.open(encoding="utf-8-sig", newline="") as handle:
        raw = tuple(csv.DictReader(handle))
    rows = []
    seen = set()
    for row in raw:
        year = int(row["year"])
        if year not in years:
            continue
        expert_id = str(row["expert_id"])
        rank, size = int(row["overall_rank"]), int(row["field_size"])
        if not expert_id.isdigit() or rank < 1 or size < rank or size < 2:
            raise CoverageIncomplete("Historical expert accuracy contains invalid rank/field evidence")
        if (year, expert_id) in seen:
            raise CoverageIncomplete("Historical expert accuracy contains duplicate expert/year facts")
        seen.add((year, expert_id))
        url = urlparse(row["source_url"])
        if (url.hostname not in {"www.fantasypros.com", "fantasypros.com", "api.fantasypros.com"}
                or not ("/nfl/accuracy/" in url.path or "/rankings/experts" in url.path)
                or "draft" in url.path):
            raise CoverageIncomplete("Waiver expert history must declare weekly in-season accuracy")
        rows.append(AnnualExpertAccuracy(year, expert_id, row["expert_name"],
                    row["source_name"], rank, size, row["source_url"],
                    *(int(row.get(f"{p}_rank")) if row.get(f"{p}_rank") else None
                      for p in ("qb", "rb", "wr", "te")), row.get("retrieved_at", "")))
    if {row.year for row in rows} != set(years):
        raise CoverageIncomplete("Waiver expert history must cover all five completed seasons")
    sizes = {year: {row.field_size for row in rows if row.year == year} for year in years}
    if any(len(values) != 1 for values in sizes.values()):
        raise CoverageIncomplete("Historical expert field sizes conflict within a season")
    for year in years:
        field_size = next(iter(sizes[year]))
        ranks = [row.overall_rank for row in rows if row.year == year]
        if len(ranks) != len(set(ranks)):
            raise CoverageIncomplete(f"Historical weekly accuracy for {year} contains duplicate rank slots")
        if evidence_dir is not None:
            source = Path(evidence_dir) / f"inseason_accuracy_{year}.json"
            if source.is_file():
                record = json.loads(source.read_text(encoding="utf-8"))
                population = re.search(r"over\s+(\d+)\s+fantasy analysts", str(record.get("payload", "")), re.I)
                if population and field_size <= int(population.group(1)):
                    raise CoverageIncomplete(f"Historical weekly accuracy for {year} contains only "
                        f"{field_size} experts, but its source describes over {population.group(1)}; "
                        "provide the full annual accuracy export instead of the public top-ten table")
    evidence = {"path": str(target), "payload_hash": stable_hash(rows),
                "years": list(years), "rows": len(rows),
                "field_sizes": {str(year): next(iter(values)) for year, values in sizes.items()},
                "authority": "published_weekly_accuracy",
                "population_scope": "recorded_annual_expert_facts",
                "annual_population_coverage": {str(year): {
                    "recorded": sum(row.year == year for row in rows),
                    "field_size": next(iter(sizes[year])),
                } for year in years},
                "population_complete": all(sum(row.year == year for row in rows) == next(iter(sizes[year]))
                                           for year in years)}
    return tuple(rows), evidence


def annual_accuracy_from_directory(payload, year, *, source_url, public_evidence=None):
    """Require the declared accuracy year; endpoint season alone is insufficient."""
    if str(payload.get("accuracy_weekly_season")) == str(year):
        field = "accuracy_weekly"
    elif str(payload.get("accuracy_weekly_last_season")) == str(year):
        field = "accuracy_weekly_last_season"
    else:
        raise CoverageIncomplete(f"FantasyPros historical expert request for {year} returned accuracy "
            f"for {payload.get('accuracy_weekly_season')} / {payload.get('accuracy_weekly_last_season')}; "
            "the API response cannot replace the full completed-year accuracy export")
    facts = []
    seen = set()
    for expert in payload.get("experts", ()):
        rank = (expert.get(field) or {}).get("ALL")
        if rank is None:
            continue
        if isinstance(rank, bool) or not isinstance(rank, int) or rank <= 0:
            raise CoverageIncomplete("Historical expert directory contains invalid accuracy ranks")
        expert_id = str(expert["expert_id"])
        if expert_id in seen:
            raise CoverageIncomplete("Historical expert directory contains duplicate identities")
        seen.add(expert_id)
        facts.append((expert_id, expert["name"], expert.get("source", "Unknown"), rank,
                      tuple((expert.get(field) or {}).get(p) for p in ("QB", "RB", "WR", "TE"))))
    size = max((row[3] for row in facts), default=0)
    if sorted(row[3] for row in facts) != list(range(1, size + 1)) or size < 2:
        raise CoverageIncomplete(f"FantasyPros {year} accuracy directory omits annual rank slots; "
                                 "a current contributor directory is not the full annual population")
    if public_evidence is not None and Path(public_evidence).is_file():
        record = json.loads(Path(public_evidence).read_text(encoding="utf-8"))
        html = str(record.get("payload", ""))
        public = {m.group(1): int(m.group(2)) for m in re.finditer(
            r'\{"id":(\d+),"rank":(\d+),"expert":', html)}
        if any(public.get(expert_id, rank) != rank for expert_id, _, _, rank, _ in facts):
            raise CoverageIncomplete(f"FantasyPros directory accuracy labeled {year} conflicts "
                                     "with the published annual leaderboard; raw evidence retained")
    return tuple(AnnualExpertAccuracy(year, expert_id, name, source, rank, size, source_url, *positions)
                 for expert_id, name, source, rank, positions in facts)


def write_weekly_accuracy_history(path, rows):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fields = (*AnnualExpertAccuracy.__dataclass_fields__, "overall_percentile")
    from dataclasses import asdict
    # Only a fully validated five-season refresh may replace the original.
    temporary = target.with_suffix(target.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows({**asdict(row), "overall_percentile":
                          1 - (row.overall_rank - 1) / (row.field_size - 1)} for row in rows)
    temporary.replace(target)
