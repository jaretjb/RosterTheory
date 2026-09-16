from __future__ import annotations

import csv
import math
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from roster_theory.fantasypros import FantasyProsClient
from roster_theory.grouped_rankings import _consensus_params
from roster_theory.rankings import normalize_name


SKILL_POSITIONS = ("QB", "RB", "WR", "TE")
RANK_DISPERSION_FIELDS = (
    "overall_rank_stddev",
    "overall_rank_min",
    "overall_rank_max",
    "overall_rank_experts",
    "overall_rank_weight_coverage",
    "position_rank_stddev",
    "position_rank_min",
    "position_rank_max",
    "position_rank_experts",
    "position_rank_weight_coverage",
)


def _single_expert_filter(expert_id: int) -> str:
    # FantasyPros ignores a lone ID; repeating it requests a one-expert consensus.
    return f"{expert_id}:{expert_id}"


def load_selected_experts(
    path: str | Path, scope: str
) -> list[dict[str, Any]]:
    with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
        rows = [row for row in csv.DictReader(handle) if row.get("scope") == scope]
    selected: dict[int, dict[str, Any]] = {}
    for row in rows:
        expert_id = int(row["expert_id"])
        selected.setdefault(
            expert_id,
            {
                "expert_id": expert_id,
                "expert_name": str(row.get("expert_name") or ""),
                "selection_rank": int(row.get("selection_rank") or 0),
                "last_updated": str(row.get("last_updated") or ""),
                "expert_weight": float(row.get("effective_expert_weight") or 0.0),
            },
        )
    return sorted(selected.values(), key=lambda row: row["selection_rank"])


def _ranking_rows(response: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    rows = {}
    for player in response.get("players") or []:
        player_id = str(player.get("player_id") or "")
        rank = player.get("rank_ecr")
        if not player_id or rank in (None, ""):
            continue
        rows[player_id] = {
            "player_id": player_id,
            "player_name": str(player.get("player_name") or ""),
            "position": str(player.get("player_position_id") or "").upper(),
            "rank": float(rank),
        }
    return rows


def _response_filter_issue(
    response: Mapping[str, Any], expert: Mapping[str, Any], position: str
) -> dict[str, Any] | None:
    expected = int(expert["expert_id"])
    returned_ids = {
        int(value) for value in (response.get("expert_names") or {}).keys()
    }
    total = int(response.get("total_experts") or 0)
    if returned_ids == {expected} and total == 1:
        return None
    return {
        "expert_id": expected,
        "expert_name": expert["expert_name"],
        "expert_weight": float(expert.get("expert_weight") or 0.0),
        "position": position,
        "status": "expert_filter_mismatch",
        "returned_expert_ids": sorted(returned_ids),
        "returned_expert_count": total,
    }


def _pairwise_audit(
    expert: Mapping[str, Any],
    position: str,
    overall: Mapping[str, Mapping[str, Any]],
    positional: Mapping[str, Mapping[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    overall_at_position = {
        player_id: row
        for player_id, row in overall.items()
        if row.get("position") == position
    }
    shared = sorted(set(overall_at_position) & set(positional))
    inversions = []
    comparable_pairs = 0
    tied_pairs = 0
    for left_index, left_id in enumerate(shared):
        for right_id in shared[left_index + 1 :]:
            left_all = float(overall_at_position[left_id]["rank"])
            right_all = float(overall_at_position[right_id]["rank"])
            left_pos = float(positional[left_id]["rank"])
            right_pos = float(positional[right_id]["rank"])
            all_order = (left_all > right_all) - (left_all < right_all)
            position_order = (left_pos > right_pos) - (left_pos < right_pos)
            if not all_order or not position_order:
                tied_pairs += 1
                continue
            comparable_pairs += 1
            if all_order != position_order:
                inversions.append(
                    {
                        "expert_id": int(expert["expert_id"]),
                        "expert_name": expert["expert_name"],
                        "position": position,
                        "left_player_id": left_id,
                        "left_player_name": overall_at_position[left_id]["player_name"],
                        "left_all_rank": left_all,
                        "left_position_rank": left_pos,
                        "right_player_id": right_id,
                        "right_player_name": overall_at_position[right_id]["player_name"],
                        "right_all_rank": right_all,
                        "right_position_rank": right_pos,
                    }
                )
    summary = {
        "expert_id": int(expert["expert_id"]),
        "expert_name": expert["expert_name"],
        "position": position,
        "all_player_count": len(overall_at_position),
        "position_player_count": len(positional),
        "shared_player_count": len(shared),
        "join_coverage": (
            round(len(shared) / min(len(overall_at_position), len(positional)), 6)
            if overall_at_position and positional
            else 0.0
        ),
        "comparable_pairs": comparable_pairs,
        "tied_pairs": tied_pairs,
        "inversion_count": len(inversions),
        "inversion_rate": (
            round(len(inversions) / comparable_pairs, 6) if comparable_pairs else None
        ),
    }
    return summary, inversions


def _named_pair_comparison(
    expert: Mapping[str, Any],
    overall: Mapping[str, Mapping[str, Any]],
    positional: Mapping[str, Mapping[str, Any]],
    left_name: str,
    right_name: str,
) -> dict[str, Any]:
    overall_by_name = {normalize_name(row["player_name"]): row for row in overall.values()}
    position_by_name = {
        normalize_name(row["player_name"]): row for row in positional.values()
    }
    left_key = normalize_name(left_name)
    right_key = normalize_name(right_name)
    left_all = overall_by_name.get(left_key)
    right_all = overall_by_name.get(right_key)
    left_pos = position_by_name.get(left_key)
    right_pos = position_by_name.get(right_key)
    complete = all((left_all, right_all, left_pos, right_pos))
    return {
        "expert_id": int(expert["expert_id"]),
        "expert_name": expert["expert_name"],
        "expert_weight": float(expert.get("expert_weight") or 0.0),
        "complete": complete,
        "left_player": left_name,
        "right_player": right_name,
        "all_order": (
            left_name if float(left_all["rank"]) < float(right_all["rank"]) else right_name
        )
        if complete
        else None,
        "position_order": (
            left_name if float(left_pos["rank"]) < float(right_pos["rank"]) else right_name
        )
        if complete
        else None,
        "left_all_rank": left_all.get("rank") if left_all else None,
        "right_all_rank": right_all.get("rank") if right_all else None,
        "left_position_rank": left_pos.get("rank") if left_pos else None,
        "right_position_rank": right_pos.get("rank") if right_pos else None,
    }


def audit_weighted_export_consistency(
    path: str | Path, scope: str
) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
        rows = [
            row
            for row in csv.DictReader(handle)
            if row.get("scope") == scope and row.get("position") in SKILL_POSITIONS
        ]
    by_position: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row.get("rank_score") in (None, "") or row.get("overall_rank_score") in (
            None,
            "",
        ):
            continue
        by_position[str(row["position"])].append(row)
    inversions = []
    comparable_pairs = 0
    tied_pairs = 0
    position_summaries = {}
    for position, position_rows in sorted(by_position.items()):
        position_pairs = 0
        position_inversions = 0
        ordered = sorted(position_rows, key=lambda row: str(row.get("fantasypros_id") or ""))
        for left_index, left in enumerate(ordered):
            for right in ordered[left_index + 1 :]:
                left_all = float(left["overall_rank_score"])
                right_all = float(right["overall_rank_score"])
                left_pos = float(left["rank_score"])
                right_pos = float(right["rank_score"])
                all_order = (left_all > right_all) - (left_all < right_all)
                position_order = (left_pos > right_pos) - (left_pos < right_pos)
                if not all_order or not position_order:
                    tied_pairs += 1
                    continue
                comparable_pairs += 1
                position_pairs += 1
                if all_order == position_order:
                    continue
                position_inversions += 1
                inversions.append(
                    {
                        "position": position,
                        "left_player_id": left.get("fantasypros_id"),
                        "left_player_name": left.get("player_name"),
                        "left_all_rank_score": left_all,
                        "left_position_rank_score": left_pos,
                        "right_player_id": right.get("fantasypros_id"),
                        "right_player_name": right.get("player_name"),
                        "right_all_rank_score": right_all,
                        "right_position_rank_score": right_pos,
                    }
                )
        position_summaries[position] = {
            "player_count": len(position_rows),
            "comparable_pairs": position_pairs,
            "inversion_count": position_inversions,
            "inversion_rate": (
                round(position_inversions / position_pairs, 6)
                if position_pairs
                else None
            ),
        }
    return {
        "path": str(path),
        "scope": scope,
        "player_count": len(rows),
        "comparable_pairs": comparable_pairs,
        "tied_pairs": tied_pairs,
        "inversion_count": len(inversions),
        "inversion_rate": (
            round(len(inversions) / comparable_pairs, 6)
            if comparable_pairs
            else None
        ),
        "by_position": position_summaries,
        "inversions": inversions,
    }


def rank_dispersion_by_player(
    individual_rankings: Iterable[Mapping[str, Any]],
) -> dict[tuple[str, str], dict[str, Any]]:
    """Summarize accuracy-weighted expert rank dispersion by player and feed."""

    grouped: dict[tuple[str, str], list[tuple[float, float]]] = defaultdict(list)
    for row in individual_rankings:
        player_id = str(row.get("player_id") or "")
        feed = str(row.get("ranking_feed") or "").upper()
        try:
            rank = float(row.get("rank"))
            weight = float(row.get("expert_weight"))
        except (TypeError, ValueError):
            continue
        if not player_id or feed not in ("ALL", *SKILL_POSITIONS):
            continue
        if rank <= 0.0 or weight <= 0.0:
            continue
        grouped[(player_id, feed)].append((rank, weight))

    result: dict[tuple[str, str], dict[str, Any]] = {}
    for key, observations in grouped.items():
        total_weight = sum(weight for _rank, weight in observations)
        mean = sum(rank * weight for rank, weight in observations) / total_weight
        variance = (
            sum(weight * ((rank - mean) ** 2) for rank, weight in observations)
            / total_weight
        )
        ranks = [rank for rank, _weight in observations]
        result[key] = {
            "rank_stddev": round(math.sqrt(variance), 6),
            "rank_min": min(ranks),
            "rank_max": max(ranks),
            "expert_count": len(observations),
            "expert_weight_coverage": round(total_weight, 6),
        }
    return result


def enrich_ranked_csv_with_dispersion(
    path: str | Path,
    individual_rankings: Iterable[Mapping[str, Any]],
    *,
    scope: str,
) -> dict[str, Any]:
    """Attach individual-ballot dispersion to a weighted export or league board."""

    csv_path = Path(path)
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)
    for field in RANK_DISPERSION_FIELDS:
        if field not in fieldnames:
            fieldnames.append(field)

    dispersion = rank_dispersion_by_player(individual_rankings)
    enriched = 0
    for row in rows:
        if row.get("scope") != scope:
            continue
        position = str(row.get("position") or "").upper()
        player_id = str(row.get("fantasypros_id") or "")
        if not player_id or position not in SKILL_POSITIONS:
            continue
        overall = dispersion.get((player_id, "ALL"))
        positional = dispersion.get((player_id, position))
        if overall is None and positional is None:
            continue
        for prefix, summary in (("overall", overall), ("position", positional)):
            if summary is None:
                continue
            row[f"{prefix}_rank_stddev"] = summary["rank_stddev"]
            row[f"{prefix}_rank_min"] = summary["rank_min"]
            row[f"{prefix}_rank_max"] = summary["rank_max"]
            row[f"{prefix}_rank_experts"] = summary["expert_count"]
            row[f"{prefix}_rank_weight_coverage"] = summary[
                "expert_weight_coverage"
            ]
        enriched += 1

    temporary = csv_path.with_suffix(csv_path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(csv_path)
    return {
        "path": str(csv_path),
        "scope": scope,
        "row_count": len(rows),
        "enriched_player_count": enriched,
    }


def build_weighted_ballot_preferences(
    individual_rankings: Iterable[Mapping[str, Any]],
    board: Iterable[Mapping[str, Any]],
) -> tuple[dict[tuple[str, str], float], dict[str, Any]]:
    """Build direct pairwise preferences from individual positional ballots."""
    board_by_fantasypros_id = {
        str(row.get("fantasypros_id")): {
            "player_key": str(
                row.get("player_key")
                or row.get("sleeper_id")
                or row.get("player_name")
            ),
            "player_name": str(row.get("player_name") or ""),
            "position": str(row.get("position") or "").upper(),
        }
        for row in board
        if row.get("fantasypros_id") not in (None, "")
        and str(row.get("position") or "").upper() in SKILL_POSITIONS
    }
    ballots: dict[str, dict[int, dict[str, float]]] = defaultdict(
        lambda: defaultdict(dict)
    )
    expert_weights: dict[int, float] = {}
    for row in individual_rankings:
        feed = str(row.get("ranking_feed") or "").upper()
        if feed not in SKILL_POSITIONS:
            continue
        board_player = board_by_fantasypros_id.get(str(row.get("player_id") or ""))
        if board_player is None or board_player["position"] != feed:
            continue
        expert_id = int(row["expert_id"])
        expert_weights[expert_id] = float(row.get("expert_weight") or 0.0)
        ballots[feed][expert_id][board_player["player_key"]] = float(row["rank"])

    preferences: dict[tuple[str, str], float] = {}
    pair_count = 0
    zero_coverage_pairs = 0
    by_position = {}
    for position, expert_ballots in sorted(ballots.items()):
        player_keys = sorted(
            {
                player_key
                for expert_ballot in expert_ballots.values()
                for player_key in expert_ballot
            }
        )
        position_pairs = 0
        position_zero_coverage = 0
        for left_index, left_key in enumerate(player_keys):
            for right_key in player_keys[left_index + 1 :]:
                left_weight = 0.0
                right_weight = 0.0
                for expert_id, expert_ballot in expert_ballots.items():
                    if left_key not in expert_ballot or right_key not in expert_ballot:
                        continue
                    weight = expert_weights.get(expert_id, 0.0)
                    if expert_ballot[left_key] < expert_ballot[right_key]:
                        left_weight += weight
                    elif expert_ballot[right_key] < expert_ballot[left_key]:
                        right_weight += weight
                total_weight = left_weight + right_weight
                if total_weight <= 0.0:
                    zero_coverage_pairs += 1
                    position_zero_coverage += 1
                    continue
                preferences[(left_key, right_key)] = left_weight / total_weight
                preferences[(right_key, left_key)] = right_weight / total_weight
                pair_count += 1
                position_pairs += 1
        by_position[position] = {
            "player_count": len(player_keys),
            "covered_pairs": position_pairs,
            "zero_coverage_pairs": position_zero_coverage,
        }
    return preferences, {
        "method": "direct_accuracy_weighted_pairwise_position_ballots",
        "expert_count": len(expert_weights),
        "covered_pairs": pair_count,
        "zero_coverage_pairs": zero_coverage_pairs,
        "by_position": by_position,
    }


def audit_expert_rank_consistency(
    client: FantasyProsClient,
    *,
    season: int,
    expert_pool_path: str | Path,
    scope: str = "skills_half_ppr",
    scoring: str = "HALF",
    positions: Iterable[str] = SKILL_POSITIONS,
    minimum_interval: float = 1.0,
    weighted_rankings_path: str | Path | None = None,
    clock: Callable[[], float] = time.monotonic,
    sleeper: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    experts = load_selected_experts(expert_pool_path, scope)
    requested_positions = tuple(str(position).upper() for position in positions)
    issues = []
    summaries = []
    inversions = []
    individual_rankings = []
    target_comparisons = []
    request_count = 0
    last_call_at: float | None = None

    def fetch(expert: Mapping[str, Any], position: str) -> dict[str, Any]:
        nonlocal last_call_at, request_count
        if last_call_at is not None:
            delay = minimum_interval - (clock() - last_call_at)
            if delay > 0:
                sleeper(delay)
        response = client.consensus_rankings(
            season,
            **_consensus_params(
                position,
                scoring,
                filters=_single_expert_filter(int(expert["expert_id"])),
                experts="show",
            ),
        )
        last_call_at = clock()
        request_count += 1
        issue = _response_filter_issue(response, expert, position)
        if issue:
            issues.append(issue)
        return response

    for expert in experts:
        overall = _ranking_rows(fetch(expert, "ALL"))
        individual_rankings.extend(
            {
                "expert_id": int(expert["expert_id"]),
                "expert_name": expert["expert_name"],
                "expert_weight": float(expert.get("expert_weight") or 0.0),
                "last_updated": expert["last_updated"],
                "ranking_feed": "ALL",
                **row,
            }
            for row in overall.values()
        )
        for position in requested_positions:
            positional = _ranking_rows(fetch(expert, position))
            individual_rankings.extend(
                {
                    "expert_id": int(expert["expert_id"]),
                    "expert_name": expert["expert_name"],
                    "expert_weight": float(expert.get("expert_weight") or 0.0),
                    "last_updated": expert["last_updated"],
                    "ranking_feed": position,
                    **row,
                }
                for row in positional.values()
            )
            summary, position_inversions = _pairwise_audit(
                expert, position, overall, positional
            )
            summary["last_updated"] = expert["last_updated"]
            summaries.append(summary)
            inversions.extend(position_inversions)
            if position == "RB":
                target_comparisons.append(
                    _named_pair_comparison(
                        expert,
                        overall,
                        positional,
                        "Kenneth Walker III",
                        "Derrick Henry",
                    )
                )

    by_position = {}
    for position in requested_positions:
        rows = [row for row in summaries if row["position"] == position]
        comparable = sum(int(row["comparable_pairs"]) for row in rows)
        inversion_count = sum(int(row["inversion_count"]) for row in rows)
        by_position[position] = {
            "experts": len(rows),
            "comparable_pairs": comparable,
            "inversion_count": inversion_count,
            "inversion_rate": (
                round(inversion_count / comparable, 6) if comparable else None
            ),
        }
    total_pairs = sum(row["comparable_pairs"] for row in summaries)
    target_weighted_votes: dict[str, float] = defaultdict(float)
    for comparison in target_comparisons:
        if comparison["complete"] and comparison["all_order"]:
            target_weighted_votes[str(comparison["all_order"])] += float(
                comparison.get("expert_weight") or 0.0
            )
    result = {
        "season": season,
        "scope": scope,
        "scoring": scoring,
        "expert_pool_path": str(expert_pool_path),
        "expert_count": len(experts),
        "request_count": request_count,
        "positions": list(requested_positions),
        "issues": issues,
        "summary": {
            "comparable_pairs": total_pairs,
            "inversion_count": len(inversions),
            "inversion_rate": (
                round(len(inversions) / total_pairs, 6) if total_pairs else None
            ),
            "by_position": by_position,
        },
        "expert_position_summaries": summaries,
        "target_comparisons": target_comparisons,
        "target_weighted_votes": {
            player: round(weight, 6)
            for player, weight in sorted(target_weighted_votes.items())
        },
        "inversions": inversions,
        "individual_rankings": individual_rankings,
    }
    if weighted_rankings_path is not None:
        result["weighted_export"] = audit_weighted_export_consistency(
            weighted_rankings_path, scope
        )
    return result
