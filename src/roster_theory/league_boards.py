from __future__ import annotations

import csv
import json
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from roster_theory.fantasypros import FantasyProsClient
from roster_theory.rankings import FLEX_ELIGIBILITY, add_vbd, normalize_name, starter_baselines


BOARD_POSITIONS = ("QB", "RB", "WR", "TE", "K", "DST")
SKILL_POSITIONS = ("QB", "RB", "WR", "TE")
SCOPES_BY_SCORING = {
    "STD": {"skills_standard", "k", "dst"},
    "HALF": {"skills_half_ppr", "k", "dst"},
}
MINIMUM_COMPLETE_RANKING_COUNTS = {
    # The ten-expert skill consensus is intentionally narrower in the fringe
    # than the former twenty-expert union. These floors still cover far more
    # than any legal 10- or 12-team draft can select at one position; the
    # separate top-180 coverage and join gates protect the draftable board.
    "QB": 60, "RB": 120, "WR": 150, "TE": 80, "K": 40, "DST": 32
}
EXPECTED_ROSTER_POSITION = {"DEF": "DST"}
PLAYER_NAME_ALIASES = {"hollywoodbrown": "marquisebrown"}


@dataclass(slots=True)
class LeagueBoard:
    players: list[dict[str, Any]]
    metadata: dict[str, Any]
    matches: list[dict[str, Any]]
    issues: list[dict[str, Any]]


def ranking_counts_complete(counts: Mapping[str, int]) -> bool:
    return all(
        counts.get(position, 0) >= minimum
        for position, minimum in MINIMUM_COMPLETE_RANKING_COUNTS.items()
    )


def maximum_rosterable_skill_counts(
    roster_positions: Iterable[str], team_count: int
) -> dict[str, int]:
    """Return conservative per-position depth for every legal drafted roster.

    Every bench slot can hold any skill position. Flex slots count for each
    eligible position because this is a source-completeness ceiling, not a
    prediction of how managers will allocate those slots.
    """

    normalized = [
        EXPECTED_ROSTER_POSITION.get(str(position), str(position))
        for position in roster_positions
    ]
    slot_counts = Counter(normalized)
    bench_slots = slot_counts.get("BN", 0)
    return {
        position: team_count
        * (
            slot_counts.get(position, 0)
            + bench_slots
            + sum(
                slot_counts.get(flex_position, 0)
                for flex_position, eligible in FLEX_ELIGIBILITY.items()
                if position in eligible
            )
        )
        for position in SKILL_POSITIONS
    }


def projection_counts_complete(
    counts: Mapping[str, int], requirements: Mapping[str, int]
) -> bool:
    return all(
        counts.get(position, 0) >= requirements.get(position, 0)
        for position in SKILL_POSITIONS
    )


def ranked_skill_projection_coverage(
    rows: Iterable[Mapping[str, Any]], limit: int = 180
) -> tuple[int, float]:
    """Measure projections before missing values can distort VBD board order."""

    ranked = sorted(
        (
            row
            for row in rows
            if row.get("position") in SKILL_POSITIONS
            and row.get("overall_rank_score") is not None
        ),
        key=lambda row: float(row["overall_rank_score"]),
    )[:limit]
    coverage = (
        sum(row.get("projected_points") is not None for row in ranked) / len(ranked)
        if ranked
        else 0.0
    )
    return len(ranked), round(coverage, 4)


class PacedCalls:
    def __init__(self, minimum_interval: float = 1.0) -> None:
        self.minimum_interval = minimum_interval
        self.last_call: float | None = None
        self.request_count = 0

    def call(self, callback: Callable[[], dict[str, Any]]) -> dict[str, Any]:
        if self.last_call is not None:
            remaining = self.minimum_interval - (time.monotonic() - self.last_call)
            if remaining > 0:
                time.sleep(remaining)
        value = callback()
        self.last_call = time.monotonic()
        self.request_count += 1
        return value


def _as_float(value: Any) -> float | None:
    if value in (None, "", "-"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _value(stats: Mapping[str, Any], *names: str) -> float | None:
    for name in names:
        result = _as_float(stats.get(name))
        if result is not None:
            return result
    return None


SKILL_STATS: dict[str, tuple[str, ...]] = {
    "pass_yd": ("pass_yds",),
    "pass_td": ("pass_tds",),
    "pass_int": ("pass_ints",),
    "rush_yd": ("rush_yds",),
    "rush_td": ("rush_tds",),
    "rec": ("rec_rec",),
    "rec_yd": ("rec_yds",),
    "rec_td": ("rec_tds",),
    "fum_lost": ("fumbles",),
    "st_td": ("ret_tds",),
}

DST_STATS: dict[str, tuple[str, ...]] = {
    "def_st_ff": ("def_ff",),
    "def_st_fum_rec": ("def_fr",),
    "int": ("def_int",),
    "sack": ("def_sack",),
    "safe": ("def_safety",),
    "def_td": ("def_td",),
    "def_st_td": ("def_retd",),
    "pts_allow_0": ("def_pa_a",),
    "pts_allow_1_6": ("def_pa_b",),
    "pts_allow_7_13": ("def_pa_c",),
    "pts_allow_14_20": ("def_pa_d",),
    "pts_allow_21_27": ("def_pa_e",),
    "pts_allow_28_34": ("def_pa_f",),
    "pts_allow_35p": ("def_pa_g",),
}


def score_api_projection(
    position: str, stats: Mapping[str, Any], scoring: Mapping[str, Any]
) -> tuple[float | None, str, list[str]]:
    """Score only stat categories explicitly supplied by FantasyPros.

    Returns points, complete/partial/unavailable, and unsupported non-zero Sleeper settings.
    """
    position = position.upper()
    total = 0.0
    unsupported: list[str] = []
    if position in SKILL_POSITIONS:
        for setting, aliases in SKILL_STATS.items():
            stat = _value(stats, *aliases)
            if stat is not None:
                total += stat * float(_as_float(scoring.get(setting)) or 0.0)
        two_point_rates = {
            float(_as_float(scoring.get(name)) or 0.0) for name in ("pass_2pt", "rush_2pt", "rec_2pt")
        }
        two_point_tds = _value(stats, "2pt_tds")
        if two_point_tds is not None and len(two_point_rates) == 1:
            total += two_point_tds * next(iter(two_point_rates))
        elif two_point_tds is not None and any(two_point_rates):
            unsupported.append("nonuniform_2pt_conversion_scoring")
        return round(total, 3), "partial" if unsupported else "complete", unsupported

    if position == "DST":
        for setting, aliases in DST_STATS.items():
            stat = _value(stats, *aliases)
            if stat is not None:
                total += stat * float(_as_float(scoring.get(setting)) or 0.0)
        for setting in ("blk_kick",):
            if _as_float(scoring.get(setting)):
                unsupported.append(setting)
        return round(total, 3), "partial" if unsupported else "complete", unsupported

    if position == "K":
        made = _value(stats, "fg")
        attempts = _value(stats, "fga")
        extra_points = _value(stats, "xpt")
        if extra_points is not None:
            total += extra_points * float(_as_float(scoring.get("xpm")) or 0.0)
        if made is not None and attempts is not None:
            total += max(0.0, attempts - made) * float(_as_float(scoring.get("fgmiss")) or 0.0)
        distance_settings = tuple(
            name for name in ("fgm_0_19", "fgm_20_29", "fgm_30_39", "fgm_40_49", "fgm_50_59", "fgm_50p", "fgm_60p")
            if _as_float(scoring.get(name))
        )
        unsupported.extend(distance_settings)
        if _as_float(scoring.get("xpmiss")):
            unsupported.append("xpmiss")
        # Partial kicker points would distort both the position order and its replacement baseline.
        return (None if unsupported else round(total, 3)), ("unavailable" if unsupported else "complete"), unsupported

    return None, "unavailable", [f"unsupported_position:{position}"]


def _read_csv(path: str | Path) -> list[dict[str, str]]:
    with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _ranking_rows(path: str | Path, scoring: str) -> list[dict[str, Any]]:
    scopes = SCOPES_BY_SCORING[scoring]
    rows = [row for row in _read_csv(path) if row.get("scope") in scopes]
    for row in rows:
        row["position"] = str(row.get("position") or "").upper()
        row["fantasypros_id"] = str(row.get("fantasypros_id") or "")
        row["rank_score"] = _as_float(row.get("rank_score"))
        row["weighted_position_rank"] = int(float(row.get("weighted_position_rank") or 0))
        row["overall_rank_score"] = _as_float(row.get("overall_rank_score"))
        row["weighted_overall_rank"] = (
            int(float(row["weighted_overall_rank"]))
            if row.get("weighted_overall_rank") not in (None, "", "0")
            else None
        )
    return rows


def _sleeper_candidates(players: Mapping[str, Mapping[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for sleeper_id, player in players.items():
        positions = {str(value).upper() for value in (player.get("fantasy_positions") or [])}
        positions.add(str(player.get("position") or "").upper())
        if "DEF" in positions:
            positions.add("DST")
        names = {
            str(player.get("full_name") or "").strip(),
            str(player.get("search_full_name") or "").strip(),
            f"{player.get('first_name', '')} {player.get('last_name', '')}".strip(),
        }
        candidate = {
            "sleeper_id": str(sleeper_id),
            "player_name": str(player.get("full_name") or "").strip(),
            "team": str(player.get("team") or "").upper().replace("JAC", "JAX"),
            "positions": positions,
        }
        for name in names:
            for key in _identity_keys(name):
                result[key].append(candidate)
    return result


def _identity_keys(name: str) -> set[str]:
    key = normalize_name(name)
    keys = {key} if key else set()
    # FantasyPros commonly includes generational suffixes while Sleeper omits them.
    for suffix in ("jr", "sr", "ii", "iii", "iv", "v"):
        if key.endswith(suffix) and len(key) > len(suffix):
            keys.add(key[: -len(suffix)])
    alias = PLAYER_NAME_ALIASES.get(key)
    if alias:
        keys.add(alias)
    return keys


def _match_sleeper(
    player_name: str, position: str, team: str, candidates: Mapping[str, list[dict[str, Any]]]
) -> tuple[str | None, str, list[dict[str, Any]]]:
    matches = [
        candidate
        for key in _identity_keys(player_name)
        for candidate in candidates.get(key, [])
        if position in candidate["positions"]
    ]
    matches = list({candidate["sleeper_id"]: candidate for candidate in matches}.values())
    if len(matches) == 1:
        return matches[0]["sleeper_id"], "matched", matches
    normalized_team = team.upper().replace("JAC", "JAX")
    team_matches = [candidate for candidate in matches if candidate["team"] == normalized_team]
    if normalized_team and len(team_matches) == 1:
        return team_matches[0]["sleeper_id"], "matched_team", matches
    return None, "ambiguous" if matches else "unmatched", matches


def fetch_board_sources(
    client: FantasyProsClient, season: int = 2026, minimum_interval: float = 1.0
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, list[dict[str, Any]]], dict[str, Any]]:
    calls = PacedCalls(minimum_interval)
    projections: dict[str, list[dict[str, Any]]] = {}
    projection_meta: dict[str, Any] = {}
    for position in SKILL_POSITIONS:
        response = calls.call(lambda position=position: client.projections(season, position=position))
        projections[position] = list(response.get("players", []))
        projection_meta[position] = {
            "count": len(projections[position]),
            "tier": response.get("tier"),
            "public_api_limited_flag": bool(response.get("public_api_limited")),
        }
    adp: dict[str, list[dict[str, Any]]] = {}
    adp_meta: dict[str, Any] = {}
    for scoring in ("STD", "HALF"):
        response = calls.call(
            lambda scoring=scoring: client.consensus_rankings(
                season, position="ALL", scoring=scoring, type="ADP"
            )
        )
        adp[scoring] = list(response.get("players", []))
        adp_meta[scoring] = {
            "count": len(adp[scoring]),
            "tier": response.get("tier"),
            "ranking_type": response.get("ranking_type_name"),
            "total_sources": response.get("total_experts"),
        }
    return projections, adp, {
        "season": season,
        "request_count": calls.request_count,
        "projections": projection_meta,
        "adp": adp_meta,
    }


def _issue(
    source: str, status: str, row: Mapping[str, Any], detail: str, severity: str = "info"
) -> dict[str, Any]:
    return {
        "source": source,
        "status": status,
        "severity": severity,
        "fantasypros_id": row.get("fantasypros_id") or row.get("fpid") or row.get("player_id") or row.get("id") or "",
        "player_name": row.get("player_name") or row.get("name") or "",
        "position": row.get("position") or row.get("position_id") or row.get("player_position_id") or "",
        "detail": detail,
    }


def build_league_board(
    *,
    league_key: str,
    snapshot: Mapping[str, Any],
    ranking_path: str | Path,
    projections: Mapping[str, list[dict[str, Any]]],
    adp_rows: Mapping[str, list[dict[str, Any]]],
    sleeper_players: Mapping[str, Mapping[str, Any]],
    source_metadata: Mapping[str, Any],
    scoring_settings_override: Mapping[str, Any] | None = None,
    approved_scoring_override: bool = False,
) -> LeagueBoard:
    league = snapshot["current"]["league"]
    scoring_settings = dict(league.get("scoring_settings", {}))
    scoring_settings.update(scoring_settings_override or {})
    scoring = "HALF" if float(scoring_settings.get("rec") or 0.0) >= 0.25 else "STD"
    rankings = _ranking_rows(ranking_path, scoring)
    projection_by_id: dict[str, dict[str, Any]] = {}
    issues: list[dict[str, Any]] = []
    scoring_limitations: dict[str, list[str]] = {}
    for position, rows in projections.items():
        for row in rows:
            fpid = str(row.get("fpid") or "")
            if not fpid:
                issues.append(_issue("projection", "missing_fantasypros_id", row, "Projection row has no fpid"))
                continue
            points, status, unsupported = score_api_projection(position, row.get("stats") or {}, scoring_settings)
            projection_by_id[fpid] = {
                "projected_points": points,
                "projection_status": status,
                "unsupported_scoring": "|".join(unsupported),
            }
            if unsupported:
                scoring_limitations[position] = sorted(set(scoring_limitations.get(position, []) + unsupported))

    adp_by_id = {
        str(row.get("player_id")): _as_float(row.get("rank_ecr") or row.get("rank_ave"))
        for row in adp_rows[scoring]
        if row.get("player_id") is not None
    }
    candidates = _sleeper_candidates(sleeper_players)
    board: list[dict[str, Any]] = []
    matches: list[dict[str, Any]] = []
    ranking_ids: set[str] = set()
    for row in rankings:
        fpid = row["fantasypros_id"]
        ranking_ids.add(fpid)
        position = row["position"]
        rank_only = position in {"K", "DST"}
        projection = projection_by_id.get(fpid) if not rank_only else None
        sleeper_id, match_status, match_candidates = _match_sleeper(
            str(row.get("player_name") or ""), position, str(row.get("team") or ""), candidates
        )
        player = dict(row)
        player.update(
            projection
            or {
                "projected_points": None,
                "projection_status": "rank_only" if rank_only else "unavailable",
                "unsupported_scoring": "",
            }
        )
        player["value_method"] = (
            "specialist_expert_rank"
            if rank_only
            else "selected_expert_overall_rank_plus_league_scored_consensus_projection"
        )
        player["projection_source"] = (
            "not_used" if rank_only else "fantasypros_unfiltered_projection_consensus"
        )
        player["adp"] = adp_by_id.get(fpid)
        player["sleeper_id"] = sleeper_id
        player["match_status"] = match_status
        board.append(player)
        matches.append({
            "fantasypros_id": fpid,
            "player_name": row.get("player_name"),
            "team": row.get("team"),
            "position": position,
            "weighted_position_rank": row.get("weighted_position_rank"),
            "match_status": match_status,
            "sleeper_id": sleeper_id,
            "candidate_sleeper_ids": "|".join(candidate["sleeper_id"] for candidate in match_candidates),
        })
        if projection is None and not rank_only:
            issues.append(_issue("join", "ranking_without_projection", row, "No same-ID projection row", "warning"))
        elif projection is not None and projection["projection_status"] != "complete":
            issues.append(_issue("scoring", projection["projection_status"], row, projection["unsupported_scoring"], "warning"))
        if player["adp"] is None:
            issues.append(_issue("join", "ranking_without_adp", row, f"No {scoring} ADP row"))
        if sleeper_id is None:
            issues.append(_issue("sleeper", match_status, row, "No unique Sleeper player match", "warning"))

    for position, rows in projections.items():
        for row in rows:
            if str(row.get("fpid") or "") not in ranking_ids:
                issues.append(_issue("projection", "projection_without_ranking", row, "Projection is outside the grouped ranking board"))
    for row in adp_rows[scoring]:
        position = str(row.get("player_position_id") or "").upper()
        if position in BOARD_POSITIONS and str(row.get("player_id") or "") not in ranking_ids:
            issues.append(_issue("adp", "adp_without_ranking", row, "ADP row is outside the grouped ranking board"))

    team_count = int(league.get("total_rosters") or league.get("settings", {}).get("num_teams") or 0)
    roster_positions = [EXPECTED_ROSTER_POSITION.get(str(value), str(value)) for value in league.get("roster_positions", [])]
    projected = [player for player in board if player.get("projected_points") is not None]
    baselines = starter_baselines(projected, roster_positions, team_count)
    board = add_vbd(board, baselines)
    for overall_rank, player in enumerate(board, start=1):
        player["board_order"] = overall_rank

    evaluation = board[: min(180, len(board))]
    ranked_skill_count, ranked_skill_coverage = ranked_skill_projection_coverage(board)
    count = len(evaluation)
    coverage = {
        "evaluated_players": count,
        "projection": round(sum(row.get("projected_points") is not None for row in evaluation) / count, 4) if count else 0.0,
        "adp": round(sum(row.get("adp") is not None for row in evaluation) / count, 4) if count else 0.0,
        "sleeper_match": round(sum(row.get("sleeper_id") is not None for row in evaluation) / count, 4) if count else 0.0,
        "overall_expert_rank": round(
            sum(
                row.get("overall_rank_score") is not None
                for row in evaluation
                if row.get("position") in SKILL_POSITIONS
            )
            / max(
                1,
                sum(row.get("position") in SKILL_POSITIONS for row in evaluation),
            ),
            4,
        ),
        "ranked_skill_projection": ranked_skill_coverage,
    }
    ranking_counts = dict(sorted(Counter(row["position"] for row in rankings).items()))
    projection_counts = {
        position: len(projections.get(position, []))
        for position in SKILL_POSITIONS
    }
    projection_count_requirements = maximum_rosterable_skill_counts(
        roster_positions,
        team_count,
    )
    required_baselines = {position for position in roster_positions if position in SKILL_POSITIONS}
    top_ids = {row["fantasypros_id"] for row in evaluation}
    severe_top_join_issues = [
        issue for issue in issues
        if issue["severity"] == "warning" and str(issue["fantasypros_id"]) in top_ids
        and issue["status"] not in {"partial", "unavailable"}
    ]
    checks = {
        "grouped_rankings_complete": ranking_counts_complete(ranking_counts),
        "league_roster_capacity_projection_counts_complete": projection_counts_complete(
            projection_counts,
            projection_count_requirements,
        ),
        "scoring_specific_adp_available": source_metadata["adp"][scoring]["count"] >= 300,
        "all_skill_position_replacement_baselines": required_baselines.issubset(baselines),
        "top_180_projection_coverage_at_least_90_percent": coverage["projection"] >= 0.90,
        "top_180_ranked_skill_projection_coverage_100_percent": (
            ranked_skill_count == 180
            and coverage["ranked_skill_projection"] == 1.0
        ),
        "top_180_adp_coverage_at_least_90_percent": coverage["adp"] >= 0.90,
        "top_180_sleeper_match_coverage_100_percent": coverage["sleeper_match"] == 1.0,
        "top_180_skill_overall_expert_rank_coverage_at_least_90_percent": (
            coverage["overall_expert_rank"] >= 0.90
        ),
        "no_partial_or_unavailable_skill_scoring": not scoring_limitations,
        "no_top_180_severe_join_issues": not severe_top_join_issues,
    }
    source_complete = all(checks.values())
    hypothetical = bool(scoring_settings_override)
    metadata = {
        "generated_at": datetime.now().astimezone().isoformat(),
        "source": "fantasypros_hof_premium_grouped_league_board",
        "league_key": league_key,
        "league_id": league.get("league_id"),
        "league_name": league.get("name"),
        "season": int(league.get("season") or source_metadata["season"]),
        "scoring": scoring,
        "hypothetical": hypothetical,
        "approved_scoring_assumption": bool(
            hypothetical and approved_scoring_override
        ),
        "scoring_settings_override": dict(scoring_settings_override or {}),
        "sleeper_snapshot_captured_at": snapshot.get("captured_at"),
        "player_count": len(board),
        "ranking_counts": ranking_counts,
        "projection_counts": projection_counts,
        "projection_count_requirements": projection_count_requirements,
        "projection_count_policy": "maximum_legal_roster_capacity_by_position",
        "adp_count": len(adp_rows[scoring]),
        "replacement_baselines": baselines,
        "scoring_limitations": scoring_limitations,
        "rank_only_positions": ["K", "DST"],
        "skill_projection_source": "fantasypros_unfiltered_projection_consensus",
        "skill_ranking_source": "weighted_selected_expert_position_and_all_draft_consensus",
        "coverage": coverage,
        "match_status_counts": dict(sorted(Counter(row["match_status"] for row in matches).items())),
        "issue_count": len(issues),
        "checks": checks,
        "simulation_ready": source_complete,
        "draft_ready": source_complete and (
            not hypothetical or approved_scoring_override
        ),
    }
    return LeagueBoard(board, metadata, matches, issues)


def write_csv(rows: Iterable[Mapping[str, Any]], path: str | Path) -> Path:
    rows = [dict(row) for row in rows]
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fields: list[str] = []
    for row in rows:
        for field in row:
            if field not in fields:
                fields.append(field)
    with target.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows({field: row.get(field) for field in fields} for row in rows)
    return target


def write_board(result: LeagueBoard, output_dir: str | Path, league_key: str) -> list[Path]:
    destination = Path(output_dir)
    paths = [
        write_csv(result.players, destination / f"{league_key}_board.csv"),
        write_csv(result.matches, destination / f"{league_key}_matches.csv"),
        write_csv(result.issues, destination / f"{league_key}_issues.csv"),
    ]
    metadata_path = destination / f"{league_key}_metadata.json"
    metadata_path.write_text(json.dumps(result.metadata, indent=2, sort_keys=True), encoding="utf-8")
    paths.append(metadata_path)
    return paths
