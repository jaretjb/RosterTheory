from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from roster_theory.fantasypros import FantasyProsClient, FantasyProsError
from roster_theory.sleeper import SleeperClient


def describe_schema(value: Any, depth: int = 0) -> Any:
    """Describe container fields without retaining provider data rows."""
    if depth >= 3:
        return type(value).__name__
    if isinstance(value, list):
        sample = next((item for item in value if item is not None), None)
        return {
            "type": "list",
            "count": len(value),
            "item": describe_schema(sample, depth + 1) if sample is not None else None,
        }
    if isinstance(value, dict):
        identifier_map = bool(value) and all(
            str(key).isdigit()
            or (
                2 <= len(str(key)) <= 4
                and str(key).isalpha()
                and str(key).isupper()
            )
            for key in value
        )
        if value and (
            identifier_map
            or (
                len(value) > 50
                and all(isinstance(item, dict) for item in value.values())
            )
        ):
            sample = next(iter(value.values()))
            return {
                "type": "object_map",
                "count": len(value),
                "item": describe_schema(sample, depth + 1),
            }
        return {
            "type": "object",
            "fields": {
                str(key): describe_schema(child, depth + 1)
                for key, child in sorted(value.items())
            },
        }
    return type(value).__name__


def _dataset(endpoint: str, value: Any) -> dict[str, Any]:
    count = len(value) if isinstance(value, (dict, list)) else None
    return {
        "method": "GET",
        "endpoint": endpoint,
        "count": count,
        "schema": describe_schema(value),
    }


def probe_sleeper(
    client: SleeperClient,
    league_id: str,
    *,
    user_id: str | None = None,
    weeks: list[int],
    include_players: bool = True,
    include_trends: bool = False,
    captured_at: datetime | None = None,
) -> dict[str, Any]:
    """Fetch documented read-only surfaces and retain schema evidence only."""
    captured = captured_at or datetime.now(timezone.utc)
    calls: list[tuple[str, str, Callable[[], Any]]] = [
        ("nfl_state", "/state/nfl", lambda: client.state("nfl")),
        ("league", f"/league/{league_id}", lambda: client.league(league_id)),
        ("users", f"/league/{league_id}/users", lambda: client.league_users(league_id)),
        ("rosters", f"/league/{league_id}/rosters", lambda: client.league_rosters(league_id)),
        (
            "winners_bracket",
            f"/league/{league_id}/winners_bracket",
            lambda: client.league_winners_bracket(league_id),
        ),
        (
            "losers_bracket",
            f"/league/{league_id}/losers_bracket",
            lambda: client.league_losers_bracket(league_id),
        ),
    ]
    for week in sorted(set(weeks)):
        calls.extend(
            [
                (
                    f"matchups_week_{week}",
                    f"/league/{league_id}/matchups/{week}",
                    lambda week=week: client.league_matchups(league_id, week),
                ),
                (
                    f"transactions_week_{week}",
                    f"/league/{league_id}/transactions/{week}",
                    lambda week=week: client.league_transactions(league_id, week),
                ),
            ]
        )
    if include_players:
        calls.append(("players", "/players/nfl", lambda: client.players("nfl")))
    if include_trends:
        calls.extend(
            [
                (
                    "trending_adds",
                    "/players/nfl/trending/add?lookback_hours=24&limit=25",
                    lambda: client.trending_players("nfl", "add"),
                ),
                (
                    "trending_drops",
                    "/players/nfl/trending/drop?lookback_hours=24&limit=25",
                    lambda: client.trending_players("nfl", "drop"),
                ),
            ]
        )

    values: dict[str, Any] = {}
    datasets: dict[str, Any] = {}
    for name, endpoint, fetch in calls:
        values[name] = fetch()
        datasets[name] = _dataset(endpoint, values[name])

    league = values["league"]
    state = values["nfl_state"]
    rosters = values["rosters"]
    settings = league.get("settings", {}) if isinstance(league, dict) else {}
    roster_players = [
        str(player_id)
        for roster in rosters
        for player_id in (roster.get("players") or [])
    ]
    user_rosters = (
        [
            roster
            for roster in rosters
            if str(roster.get("owner_id")) == str(user_id)
        ]
        if user_id
        else []
    )
    user_roster = user_rosters[0] if len(user_rosters) == 1 else None
    winners = values["winners_bracket"]
    bracket_rounds = [
        int(row["r"])
        for row in winners
        if isinstance(row, dict) and row.get("r")
    ]
    playoff_start = settings.get("playoff_week_start")
    championship_week = (
        int(playoff_start) + max(bracket_rounds) - 1
        if playoff_start and bracket_rounds
        else None
    )
    matchup_coverage = {
        str(week): {
            "team_rows": len(values[f"matchups_week_{week}"]),
            "rows_with_matchup_id": sum(
                1
                for row in values[f"matchups_week_{week}"]
                if row.get("matchup_id") is not None
            ),
        }
        for week in sorted(set(weeks))
    }
    league_audit = {
        "season": league.get("season"),
        "status": league.get("status"),
        "nfl_state_season": state.get("season"),
        "nfl_state_week": state.get("week"),
        "total_rosters_declared": league.get("total_rosters"),
        "rosters_returned": len(rosters),
        "unique_owner_ids": len(
            {
                str(roster.get("owner_id"))
                for roster in rosters
                if roster.get("owner_id")
            }
        ),
        "roster_positions": list(league.get("roster_positions") or []),
        "roster_size": len(league.get("roster_positions") or []),
        "reserve_slots": settings.get("reserve_slots"),
        "trade_deadline_raw": settings.get("trade_deadline"),
        "trades_disabled": settings.get("disable_trades"),
        "playoff_week_start": playoff_start,
        "playoff_teams": settings.get("playoff_teams"),
        "playoff_bracket_rounds": max(bracket_rounds) if bracket_rounds else None,
        "derived_championship_week": championship_week,
        "user_id_configured": user_id is not None,
        "user_roster_matches": len(user_rosters),
        "user_roster_id": user_roster.get("roster_id") if user_roster else None,
        "user_player_count": (
            len(user_roster.get("players") or []) if user_roster else None
        ),
        "user_starter_count": (
            len(user_roster.get("starters") or []) if user_roster else None
        ),
        "user_reserve_count": (
            len(user_roster.get("reserve") or []) if user_roster else None
        ),
        "rostered_player_slots": len(roster_players),
        "unique_rostered_players": len(set(roster_players)),
        "duplicate_player_ownership_count": (
            len(roster_players) - len(set(roster_players))
        ),
        "matchup_coverage": matchup_coverage,
    }
    return {
        "schema_version": 1,
        "product": "TRADE ASSISTANT",
        "provider": "Sleeper",
        "captured_at": captured.isoformat(),
        "league_id": league_id,
        "read_only": True,
        "authentication": "none",
        "raw_rows_saved": False,
        "league_audit": league_audit,
        "datasets": datasets,
    }


def save_probe(report: dict[str, Any], path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return target


def _response_metadata(value: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "accuracy_draft_season",
        "accuracy_weekly_last_season",
        "accuracy_weekly_season",
        "count",
        "fallback_for",
        "last_updated",
        "last_updated_ts",
        "position_id",
        "positions",
        "public_api_limited",
        "ranking_type_name",
        "scoring",
        "season",
        "sport",
        "tier",
        "total_experts",
        "type",
        "week",
        "year",
    }
    return {key: value.get(key) for key in sorted(allowed) if key in value}


def _response_coverage(value: dict[str, Any]) -> dict[str, Any]:
    players = value.get("players")
    if not isinstance(players, list):
        players = value.get("items")
    rows = players if isinstance(players, list) else []
    fields = sorted(
        {str(key) for row in rows if isinstance(row, dict) for key in row}
    )
    stats = sorted(
        {
            str(key)
            for row in rows
            if isinstance(row, dict) and isinstance(row.get("stats"), dict)
            for key in row["stats"]
        }
    )
    expert_ids = sorted(
        str(key)
        for key in (value.get("expert_names") or {})
    )
    return {
        "row_count": len(rows),
        "row_fields": fields,
        "stat_fields": stats,
        "expert_ids": expert_ids,
    }


def probe_fantasypros(
    client: FantasyProsClient,
    *,
    season: int,
    week: int,
    historical_season: int,
    sleep: Callable[[float], None],
    captured_at: datetime | None = None,
) -> dict[str, Any]:
    """Run a bounded authenticated capability probe and save no player rows."""
    captured = captured_at or datetime.now(timezone.utc)
    datasets: dict[str, Any] = {}

    def run(
        name: str,
        endpoint: str,
        params: dict[str, Any],
        fetch: Callable[[], dict[str, Any]],
    ) -> dict[str, Any] | None:
        if datasets:
            sleep(1.05)
        try:
            value = fetch()
        except FantasyProsError as exc:
            datasets[name] = {
                "method": "GET",
                "endpoint": endpoint,
                "parameters": params,
                "available": False,
                "error_type": type(exc).__name__,
                "http_status": client.last_get_metadata.get("http_status"),
            }
            return None
        datasets[name] = {
            "method": "GET",
            "endpoint": endpoint,
            "parameters": params,
            "available": True,
            "metadata": _response_metadata(value),
            "coverage": _response_coverage(value),
            "schema": describe_schema(value),
            "rate_limit_headers": client.last_get_metadata.get(
                "rate_limit_headers", {}
            ),
        }
        return value

    ros_params = {
        "position": "RB",
        "scoring": "HALF",
        "type": "ROS",
        "experts": "show",
    }
    ros = run(
        "ros_ecr",
        f"/nfl/{season}/consensus-rankings",
        ros_params,
        lambda: client.consensus_rankings(season, **ros_params),
    )
    expert_ids = sorted(str(key) for key in ((ros or {}).get("expert_names") or {}))
    selected_expert = expert_ids[0] if expert_ids else None
    if selected_expert:
        individual_params = {
            "position": "RB",
            "scoring": "HALF",
            "type": "ROS",
            # FantasyPros ignores a one-ID filter; duplicating the ID is the
            # existing, verified way to request one contributor.
            "filters": f"{selected_expert}:{selected_expert}",
        }
        run(
            "individual_ros_rank",
            f"/nfl/{season}/consensus-rankings",
            individual_params,
            lambda: client.consensus_rankings(season, **individual_params),
        )

    expert_params = {"type": "ROS", "include_overall": "true"}
    run(
        "ranking_experts",
        f"/nfl/{season}/rankings/experts",
        expert_params,
        lambda: client.ranking_experts(season, **expert_params),
    )
    weekly_rank_params = {"position": "RB", "scoring": "HALF", "week": week}
    weekly_rank = run(
        "weekly_ecr",
        f"/nfl/{season}/consensus-rankings",
        weekly_rank_params,
        lambda: client.consensus_rankings(season, **weekly_rank_params),
    )
    weekly_projection_params = {"position": "RB", "scoring": "HALF", "week": week}
    run(
        "weekly_projections",
        f"/nfl/{season}/projections",
        weekly_projection_params,
        lambda: client.projections(season, **weekly_projection_params),
    )
    ros_projection_params = {"position": "RB", "scoring": "HALF", "week": "ROS"}
    run(
        "ros_projection_attempt",
        f"/nfl/{season}/projections",
        ros_projection_params,
        lambda: client.projections(season, **ros_projection_params),
    )
    news_params = {"category": "injury", "limit": 5}
    run("injury_news", "/nfl/news", news_params, lambda: client.news(**news_params))
    run("players", "/nfl/players", {}, lambda: client.players())
    points_params = {"start": 1, "end": 17, "position": "RB", "scoring": "PPR"}
    run(
        "historical_player_points",
        f"/nfl/{historical_season}/player-points",
        points_params,
        lambda: client.player_points(historical_season, **points_params),
    )
    if ros and weekly_rank:
        player_ids = [
            str(row.get("player_id"))
            for row in ros.get("players", [])[:2]
            if row.get("player_id") is not None
        ]
        if len(player_ids) == 2:
            compare_params = {
                "players": ":".join(player_ids),
                "position": "RB",
                "ranking_type": "ros",
                "details": "experts",
            }
            run(
                "compare_players_ros",
                "/nfl/compare-players",
                compare_params,
                lambda: client.compare_players(**compare_params),
            )

    def metadata(name: str) -> dict[str, Any]:
        return datasets.get(name, {}).get("metadata", {})

    ros_metadata = metadata("ros_ecr")
    individual_metadata = metadata("individual_ros_rank")
    weekly_rank_metadata = metadata("weekly_ecr")
    weekly_projection_metadata = metadata("weekly_projections")
    ros_projection_metadata = metadata("ros_projection_attempt")
    capability_assessment = {
        "current_ros_ecr": (
            str(ros_metadata.get("ranking_type_name", "")).lower() == "ros"
            and not ros_metadata.get("fallback_for")
        ),
        "current_individual_ros_ranks": (
            str(individual_metadata.get("ranking_type_name", "")).lower()
            == "ros"
            and not individual_metadata.get("fallback_for")
        ),
        "weekly_ecr": (
            str(weekly_rank_metadata.get("ranking_type_name", "")).lower()
            == "weekly"
            and str(weekly_rank_metadata.get("week")) == str(week)
        ),
        "weekly_stat_projections": (
            str(weekly_projection_metadata.get("week")) == str(week)
            and datasets.get("weekly_projections", {}).get("coverage", {}).get(
                "row_count", 0
            )
            > 0
        ),
        "ros_stat_projections": (
            str(ros_projection_metadata.get("week", "")).upper() == "ROS"
            or str(ros_projection_metadata.get("type", "")).lower() == "ros"
        ),
        "structured_injuries": False,
        "injury_news": datasets.get("injury_news", {}).get("available", False),
        "historical_player_points": datasets.get(
            "historical_player_points", {}
        ).get("available", False),
        "direct_sleeper_player_id": "sleeper_id"
        in datasets.get("players", {}).get("coverage", {}).get("row_fields", []),
        "rate_limit_reported_by_server": any(
            dataset.get("rate_limit_headers")
            for dataset in datasets.values()
            if isinstance(dataset, dict)
        ),
    }
    return {
        "schema_version": 1,
        "product": "TRADE ASSISTANT",
        "provider": "FantasyPros HOF Premium",
        "captured_at": captured.isoformat(),
        "authenticated": True,
        "raw_rows_saved": False,
        "minimum_spacing_seconds": 1.05,
        "requests_attempted": client.request_count,
        "capability_assessment": capability_assessment,
        "datasets": datasets,
    }
