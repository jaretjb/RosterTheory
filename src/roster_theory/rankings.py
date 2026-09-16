from __future__ import annotations

import csv
import math
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from roster_theory.core.scoring import STAT_ALIASES, score_stats


SKILL_POSITIONS = ("QB", "RB", "WR", "TE")
ACCURACY_POSITIONS = (*SKILL_POSITIONS, "K", "DST", "IDP")


def normalize_name(value: str) -> str:
    value = value.split(" - ", 1)[0]
    return re.sub(r"[^a-z0-9]", "", value.lower())


def _as_float(value: Any) -> float | None:
    if value in (None, "", "-"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True, slots=True)
class AccuracyRecord:
    expert_name: str
    overall_rank: float
    position_ranks: Mapping[str, float]
    overall_percentile: float | None = None
    position_percentiles: Mapping[str, float] | None = None
    years_by_position: Mapping[str, int] | None = None

    def weight(self, position: str, field_size: int = 160) -> float:
        """Convert historical rank to a smooth, position-aware reliability weight."""
        normalized_position = position.upper()
        position_rank = self.position_ranks.get(normalized_position, self.overall_rank)
        overall_percentile = self.overall_percentile
        if overall_percentile is None:
            overall_percentile = max(0.0, 1.0 - ((self.overall_rank - 1.0) / max(1, field_size - 1)))
        position_percentile = (self.position_percentiles or {}).get(normalized_position)
        if position_percentile is None:
            position_percentile = max(0.0, 1.0 - ((position_rank - 1.0) / max(1, field_size - 1)))
        skill = 0.30 * overall_percentile + 0.70 * position_percentile
        years = (self.years_by_position or {}).get(normalized_position)
        if years is not None:
            # Five-year coverage is preferred, but strong two- to four-year
            # records remain usable. The formula gives two-year records the
            # requested 88% factor and reaches 100% with five years.
            skill *= 0.80 + 0.20 * min(5, max(0, years)) / 5
        return max(0.05, skill * skill)


def load_accuracy(path: str | Path = "data/manual/fantasypros/expert_accuracy_2021_2025.csv") -> dict[str, AccuracyRecord]:
    records: dict[str, AccuracyRecord] = {}
    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(
            f"Expert accuracy input not found: {source}. Supply an authorized "
            "file with --accuracy PATH; run roster-theory doctor to inspect "
            "local setup. No expert data is bundled."
        )
    with source.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            name = str(row["expert_name"]).strip()
            overall = _as_float(row.get("overall_rank"))
            if overall is None:
                continue
            positions = {
                position: rank
                for position in ACCURACY_POSITIONS
                if (rank := _as_float(row.get(position))) is not None
            }
            overall_percentile = _as_float(row.get("overall_percentile"))
            percentiles = {
                position: percentile
                for position in ACCURACY_POSITIONS
                if (percentile := _as_float(row.get(f"{position}_percentile"))) is not None
            }
            years = {
                position: int(value)
                for position in ACCURACY_POSITIONS
                if (value := _as_float(row.get(f"{position}_years"))) is not None
            }
            records[normalize_name(name)] = AccuracyRecord(
                name,
                overall,
                positions,
                overall_percentile,
                percentiles,
                years,
            )
    return records


def load_expert_pool(
    path: str | Path,
    accuracy: Mapping[str, AccuracyRecord],
) -> dict[str, AccuracyRecord]:
    """Load the current export pool without changing the historical master list."""
    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(
            f"Expert pool input not found: {source}. Supply an authorized "
            "file with --expert-pool PATH; run roster-theory doctor to inspect "
            "local setup. No selected pool is bundled."
        )
    with source.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows or "expert_name" not in rows[0]:
        raise ValueError(f"{path} is missing an expert_name column")
    selected: dict[str, AccuracyRecord] = {}
    missing: list[str] = []
    for row in rows:
        active = str(row.get("selected_for_export", "true")).strip().lower()
        if active in {"false", "0", "no", "n"}:
            continue
        name = str(row.get("expert_name") or "").strip()
        key = normalize_name(name)
        record = accuracy.get(key)
        if record is None:
            missing.append(name)
        else:
            selected[key] = record
    if missing:
        raise ValueError(
            "Current expert pool contains names missing from the historical master list: "
            + ", ".join(sorted(missing))
        )
    return selected


def load_long_rankings_csv(path: str | Path) -> list[dict[str, Any]]:
    """Load one row per expert/player ranking from a CSV export or pasted table."""
    with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    required = {"expert_name", "player_name", "position", "expert_rank"}
    missing = required - set(rows[0] if rows else {})
    if missing:
        raise ValueError(f"Rankings CSV is missing columns: {', '.join(sorted(missing))}")
    return rows


def _player_key(row: Mapping[str, Any]) -> str:
    for field in ("sleeper_id", "fantasypros_id", "player_id"):
        if row.get(field):
            return f"{field}:{row[field]}"
    return "name:" + normalize_name(str(row.get("player_name", "")))


def weighted_consensus(
    rows: Iterable[Mapping[str, Any]],
    accuracy: Mapping[str, AccuracyRecord],
    shrink_to_ecr: float = 0.25,
    max_expert_share: float = 0.20,
) -> list[dict[str, Any]]:
    """Build a position-aware weighted expert consensus with conservative ECR shrinkage."""
    if not 0.0 <= shrink_to_ecr <= 1.0:
        raise ValueError("shrink_to_ecr must be between zero and one")
    if not 0.0 < max_expert_share <= 1.0:
        raise ValueError("max_expert_share must be between zero and one")

    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        if _as_float(row.get("expert_rank")) is not None:
            grouped[_player_key(row)].append(row)

    result: list[dict[str, Any]] = []
    for player_key, player_rows in grouped.items():
        first = player_rows[0]
        position = str(first.get("position", "")).upper()
        observations: list[tuple[float, float, str]] = []
        for row in player_rows:
            expert = str(row.get("expert_name", ""))
            record = accuracy.get(normalize_name(expert))
            if record is None:
                continue
            rank = _as_float(row.get("expert_rank"))
            if rank is not None:
                observations.append((rank, record.weight(position), record.expert_name))
        if not observations:
            continue

        raw_total = sum(weight for _, weight, _ in observations)
        # A 20% cap is impossible with fewer than five experts. In that case,
        # retain the reliability weights instead of flattening a small test set.
        effective_cap = max_expert_share if len(observations) * max_expert_share >= 1.0 else 1.0
        shares = [min(weight / raw_total, effective_cap) for _, weight, _ in observations]
        share_total = sum(shares)
        weighted_rank = sum(
            rank * share / share_total for (rank, _, _), share in zip(observations, shares, strict=True)
        )

        ecr_values = [value for row in player_rows if (value := _as_float(row.get("ecr"))) is not None]
        ecr = sum(ecr_values) / len(ecr_values) if ecr_values else None
        final_rank = weighted_rank if ecr is None else (1.0 - shrink_to_ecr) * weighted_rank + shrink_to_ecr * ecr
        adp_values = [value for row in player_rows if (value := _as_float(row.get("adp"))) is not None]
        projection_values = [
            value for row in player_rows if (value := _as_float(row.get("projected_points"))) is not None
        ]
        player = {
                "player_key": player_key,
                "player_name": first.get("player_name"),
                "team": first.get("team"),
                "position": position,
                "weighted_expert_rank": round(weighted_rank, 3),
                "ecr": round(ecr, 3) if ecr is not None else None,
                "rank_score": round(final_rank, 3),
                "adp": round(sum(adp_values) / len(adp_values), 3) if adp_values else None,
                "projected_points": (
                    round(sum(projection_values) / len(projection_values), 3) if projection_values else None
                ),
                "expert_count": len(observations),
                "experts": [expert for _, _, expert in observations],
            }
        for field in ("fantasypros_id", "sleeper_id", "bye_week"):
            if first.get(field) not in (None, ""):
                player[field] = first.get(field)
        result.append(player)

    by_position: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for player in result:
        by_position[player["position"]].append(player)
    for players in by_position.values():
        players.sort(key=lambda player: (player["rank_score"], str(player["player_name"])))
        for index, player in enumerate(players, start=1):
            player["weighted_position_rank"] = index
    return sorted(result, key=lambda player: (player["rank_score"], str(player["player_name"])))


def score_projection(stats: Mapping[str, Any], scoring: Mapping[str, Any]) -> float:
    """Compatibility wrapper around feature-neutral Sleeper scoring."""
    return score_stats(stats, scoring).points


FLEX_ELIGIBILITY: dict[str, tuple[str, ...]] = {
    "FLEX": ("RB", "WR", "TE"),
    "WRRB_FLEX": ("RB", "WR"),
    "REC_FLEX": ("WR", "TE"),
    "SUPER_FLEX": ("QB", "RB", "WR", "TE"),
}


def starter_baselines(
    players: Iterable[Mapping[str, Any]], roster_positions: Iterable[str], team_count: int
) -> dict[str, float]:
    """Estimate last-starter baselines, assigning flex slots to the strongest remaining players."""
    baseline_positions = (*SKILL_POSITIONS, "K", "DST")
    player_list = [dict(player) for player in players if player.get("position") in baseline_positions]
    normalized_roster = ["DST" if position == "DEF" else position for position in roster_positions]
    dedicated = CounterLike(normalized_roster)
    selected: dict[str, int] = {
        position: dedicated.get(position, 0) * team_count for position in baseline_positions
    }

    flex_slots: list[tuple[str, ...]] = []
    for roster_position in normalized_roster:
        eligible = FLEX_ELIGIBILITY.get(roster_position)
        if eligible:
            flex_slots.extend([eligible] * team_count)

    by_position: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for player in player_list:
        by_position[str(player["position"])].append(player)
    for values in by_position.values():
        values.sort(key=lambda player: -float(player.get("projected_points") or -math.inf))

    for eligible in flex_slots:
        candidates = []
        for position in eligible:
            index = selected.get(position, 0)
            values = by_position.get(position, [])
            if index < len(values):
                candidates.append((float(values[index].get("projected_points") or -math.inf), position))
        if candidates:
            _, position = max(candidates)
            selected[position] = selected.get(position, 0) + 1

    baselines: dict[str, float] = {}
    for position, count in selected.items():
        values = by_position.get(position, [])
        if count > 0 and len(values) >= count:
            baselines[position] = float(values[count - 1].get("projected_points") or 0.0)
    return baselines


def CounterLike(values: Iterable[str]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for value in values:
        counts[str(value)] += 1
    return counts


def add_vbd(players: Iterable[Mapping[str, Any]], baselines: Mapping[str, float]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for source in players:
        player = dict(source)
        projection = _as_float(player.get("projected_points"))
        baseline = baselines.get(str(player.get("position")))
        player["vbd"] = round(projection - baseline, 3) if projection is not None and baseline is not None else None
        result.append(player)
    return sorted(
        result,
        key=lambda player: (
            -(float(player["vbd"]) if player.get("vbd") is not None else -math.inf),
            float(player.get("rank_score") or math.inf),
        ),
    )
