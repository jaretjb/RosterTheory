from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from roster_theory.core.scoring_contract import ScoringScope, assess_scoring_rules
from roster_theory.fantasypros import FantasyProsClient
from roster_theory.providers.projection_scoring import (
    DRAFT_SCORING_CONTRACT_VERSION,
    WEEKLY_RULES,
    score_draft_projection_row,
    scoring_coverage,
)
from roster_theory.rankings import (
    AccuracyRecord,
    add_vbd,
    normalize_name,
    starter_baselines,
    weighted_consensus,
)


@dataclass(slots=True)
class FantasyProsBoard:
    players: list[dict[str, Any]]
    metadata: dict[str, Any]


def _api_accuracy(expert: Mapping[str, Any]) -> AccuracyRecord | None:
    ranks = expert.get("accuracy_draft") or {}
    overall = ranks.get("ALL")
    if overall in (None, ""):
        return None
    positions = {
        position: float(ranks[position])
        for position in ("QB", "RB", "WR", "TE")
        if ranks.get(position) not in (None, "")
    }
    return AccuracyRecord(str(expert.get("name") or expert.get("expert_id")), float(overall), positions)


def select_experts(
    api_experts: Iterable[Mapping[str, Any]],
    historical_accuracy: Mapping[str, AccuracyRecord],
    limit: int = 10,
    minimum_historical_matches: int = 5,
) -> tuple[list[tuple[int, AccuracyRecord]], str]:
    """Prefer the multi-year table; use API single-season accuracy only for sample validation."""
    available = list(api_experts)
    historical: list[tuple[int, AccuracyRecord]] = []
    for expert in available:
        record = historical_accuracy.get(normalize_name(str(expert.get("name") or "")))
        if record is not None and expert.get("expert_id") is not None:
            historical.append((int(expert["expert_id"]), record))
    historical.sort(key=lambda item: item[1].overall_rank)
    if len(historical) >= minimum_historical_matches:
        return historical[:limit], "multi_year_2021_2025"

    fallback: list[tuple[int, AccuracyRecord]] = []
    for expert in available:
        record = _api_accuracy(expert)
        if record is not None and expert.get("expert_id") is not None:
            fallback.append((int(expert["expert_id"]), record))
    fallback.sort(key=lambda item: item[1].overall_rank)
    return fallback[:limit], "api_latest_year_sample_fallback"


def _single_expert_filter(expert_id: int) -> str:
    # The API treats a lone ID as an empty filter; repeating it produces a
    # one-expert consensus and still reports total_experts=1.
    return f"{expert_id}:{expert_id}"


def _adp_field(receptions: float) -> str:
    if receptions >= 0.75:
        return "rank_adp_ppr"
    if receptions >= 0.25:
        return "rank_adp_half"
    return "rank_adp"


def _sleeper_name_index(players: Mapping[str, Mapping[str, Any]] | None) -> dict[str, str]:
    if not players:
        return {}
    index: dict[str, str] = {}
    ambiguous: set[str] = set()
    for sleeper_id, player in players.items():
        full_name = str(player.get("full_name") or "").strip()
        if not full_name:
            full_name = f"{player.get('first_name', '')} {player.get('last_name', '')}".strip()
        key = normalize_name(full_name)
        if not key:
            continue
        if key in index and index[key] != str(sleeper_id):
            ambiguous.add(key)
        else:
            index[key] = str(sleeper_id)
    for key in ambiguous:
        index.pop(key, None)
    return index


def _projection_response_scope_issues(response: Mapping[str, Any], season: int) -> list[str]:
    issues = []
    for field in ("season", "year"):
        if response.get(field) not in (None, "") and str(response[field]) != str(season):
            issues.append(f"{field}_mismatch={response[field]}")
    if response.get("week") not in (None, "", 0, "0"):
        issues.append(f"weekly_response={response['week']}")
    return issues


def build_fantasypros_board(
    client: FantasyProsClient,
    *,
    season: int,
    league_id: str,
    scoring_settings: Mapping[str, Any],
    roster_positions: Iterable[str],
    team_count: int,
    historical_accuracy: Mapping[str, AccuracyRecord],
    expert_limit: int = 10,
    sleeper_players: Mapping[str, Mapping[str, Any]] | None = None,
    shrink_to_ecr: float = 0.25,
    max_expert_share: float = 0.20,
) -> FantasyProsBoard:
    receptions = float(scoring_settings.get("rec") or 0.0)
    scoring = "PPR" if receptions >= 0.75 else "HALF" if receptions >= 0.25 else "STD"
    # Filtering this directory by ranking type suppresses accuracy data in the
    # public sample tier, so request the full expert records and filter locally.
    expert_response = client.ranking_experts(season, include_overall="true")
    selected, weight_source = select_experts(
        expert_response.get("experts", []), historical_accuracy, limit=expert_limit
    )
    if not selected:
        raise ValueError("FantasyPros did not return any experts with usable draft-accuracy data")

    player_response = client.players("nfl")
    adp_name = _adp_field(receptions)
    adp_by_id = {
        str(player.get("player_id")): player.get(adp_name)
        for player in player_response.get("players", [])
        if player.get("player_id") is not None
    }
    scope = ScoringScope(league_id, season, "DRAFT-API-IMPORT", "SEASON", None)
    assessment = assess_scoring_rules(
        scoring_settings, scope=scope, catalogue=WEEKLY_RULES,
        catalogue_version=DRAFT_SCORING_CONTRACT_VERSION,
    )
    projections_by_id: dict[str, float] = {}
    projection_issues: list[dict[str, str]] = []
    projection_sources: list[dict[str, Any]] = []
    seen_projection_ids: set[str] = set()
    for position in ("QB", "RB", "WR", "TE"):
        projection_response = client.projections(season, position=position)
        scope_issues = _projection_response_scope_issues(projection_response, season)
        projection_sources.append({
            "position": position,
            "declared_season": projection_response.get("season"),
            "declared_year": projection_response.get("year"),
            "declared_week": projection_response.get("week"),
            "declared_scoring": projection_response.get("scoring"),
            "scope_issues": scope_issues,
        })
        if "players" not in projection_response:
            projection_issues.append({"position": position, "reason": "missing_players_field"})
            continue
        players = projection_response.get("players", [])
        if not isinstance(players, list):
            projection_issues.append({"position": position, "reason": "invalid_players_shape"})
            continue
        for index, player in enumerate(players):
            if not isinstance(player, Mapping):
                projection_issues.append({
                    "position": position, "row": str(index), "reason": "invalid_player_shape",
                })
                continue
            raw_id = player.get("fpid")
            if raw_id in (None, ""):
                projection_issues.append({
                    "position": position, "row": str(index), "reason": "missing_fpid",
                })
                continue
            player_id = str(raw_id)
            if player_id in seen_projection_ids:
                projections_by_id.pop(player_id, None)
                projection_issues.append({
                    "position": position, "fpid": player_id, "reason": "duplicate_fpid",
                })
                continue
            seen_projection_ids.add(player_id)
            if scope_issues:
                projection_issues.append({
                    "position": position, "fpid": player_id,
                    "reason": "source_scope_mismatch:" + ";".join(scope_issues),
                })
                continue
            declared_position = player.get("position_id") or player.get("player_position_id")
            if declared_position and str(declared_position).upper() != position:
                projection_issues.append({
                    "position": position, "fpid": player_id,
                    "reason": f"position_mismatch={declared_position}",
                })
                continue
            if not isinstance(player.get("stats"), Mapping):
                projection_issues.append({
                    "position": position, "fpid": player_id, "reason": "invalid_stats_shape",
                })
                continue
            scored = score_draft_projection_row(
                {"position_id": position, "stats": player["stats"]}, assessment,
            )
            if scored.complete:
                projections_by_id[player_id] = scored.require_points()
            else:
                projection_issues.append({
                    "position": position, "fpid": player_id,
                    "reason": scoring_coverage(scored),
                })
    sleeper_by_name = _sleeper_name_index(sleeper_players)

    rows: list[dict[str, Any]] = []
    accuracy_for_board: dict[str, AccuracyRecord] = {}
    returned_counts = {expert_id: 0 for expert_id, _ in selected}
    for expert_id, record in selected:
        accuracy_for_board[normalize_name(record.expert_name)] = record
    for position in ("QB", "RB", "WR", "TE"):
        ecr_response = client.consensus_rankings(season, position=position, scoring=scoring)
        ecr_by_id = {
            str(player.get("player_id")): player.get("rank_ecr")
            for player in ecr_response.get("players", [])
            if player.get("player_id") is not None
        }
        for expert_id, record in selected:
            response = client.consensus_rankings(
                season,
                position=position,
                scoring=scoring,
                filters=_single_expert_filter(expert_id),
            )
            returned_counts[expert_id] += len(response.get("players", []))
            for player in response.get("players", []):
                player_id = str(player.get("player_id"))
                player_name = str(player.get("player_name") or "")
                rows.append(
                    {
                        "expert_name": record.expert_name,
                        "player_name": player_name,
                        "team": player.get("player_team_id"),
                        "position": player.get("player_position_id"),
                        "expert_rank": player.get("rank_ecr"),
                        "ecr": ecr_by_id.get(player_id),
                        "adp": adp_by_id.get(player_id),
                        "projected_points": projections_by_id.get(player_id),
                        "fantasypros_id": player_id,
                        "sleeper_id": sleeper_by_name.get(normalize_name(player_name)),
                        "bye_week": player.get("player_bye_week"),
                    }
                )

    selected_metadata = [
        {
            "expert_id": expert_id,
            "expert_name": record.expert_name,
            "overall_accuracy_rank": record.overall_rank,
            "returned_players": returned_counts[expert_id],
        }
        for expert_id, record in selected
    ]

    board = weighted_consensus(
        rows,
        accuracy_for_board,
        shrink_to_ecr=shrink_to_ecr,
        max_expert_share=max_expert_share,
    )
    ranked_ids = {str(player["fantasypros_id"]) for player in board if player.get("fantasypros_id")}
    for player_id in sorted(projections_by_id.keys() - ranked_ids):
        projection_issues.append({"fpid": player_id, "reason": "unmatched_projection_id"})
    for player_id in sorted(ranked_ids - seen_projection_ids):
        projection_issues.append({"fpid": player_id, "reason": "missing_projection_row"})
    top_players = board[:180]
    projection_coverage = (
        sum(player.get("projected_points") is not None for player in top_players) / len(top_players)
        if top_players else 0.0
    )
    projected_board = [player for player in board if player.get("projected_points") is not None]
    baselines = starter_baselines(projected_board, roster_positions, team_count)
    board = add_vbd(board, baselines) if baselines else board
    checks = {
        "premium_api": expert_response.get("public_api_limited") is False,
        "multi_year_accuracy": weight_source == "multi_year_2021_2025",
        "at_least_five_current_experts": sum(count > 0 for count in returned_counts.values()) >= 5,
        "at_least_150_ranked_skill_players": len(board) >= 150,
        "all_replacement_baselines": set(("QB", "RB", "WR", "TE")).issubset(baselines),
        "top_180_projection_coverage_at_least_90_percent": projection_coverage >= 0.90,
    }
    return FantasyProsBoard(
        players=board,
        metadata={
            "league_id": league_id,
            "season": season,
            "scoring": scoring,
            "weight_source": weight_source,
            "public_api_limited": bool(expert_response.get("public_api_limited")),
            "api_tier": expert_response.get("tier"),
            "selected_experts": selected_metadata,
            "selected_expert_count": len(selected_metadata),
            "player_count": len(board),
            "players_with_projections": len(projected_board),
            "replacement_baselines": baselines,
            "draft_ready": all(checks.values()),
            "checks": checks,
            "top_180_projection_coverage": round(projection_coverage, 4),
            "projection_scoring_contract": DRAFT_SCORING_CONTRACT_VERSION,
            "projection_scoring_hash": assessment.scoring_hash,
            "projection_rules_hash": assessment.rules_hash,
            "projection_rule_support": assessment.support,
            "projection_sources": projection_sources,
            "projection_issues": projection_issues,
        },
    )
