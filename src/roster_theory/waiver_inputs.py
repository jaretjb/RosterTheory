from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from dataclasses import asdict
from pathlib import Path
from typing import Any, Mapping, Sequence

from roster_theory.core.models import Projection
from roster_theory.core.errors import CoverageIncomplete
from roster_theory.core.projections import projection_is_complete
from roster_theory.core.scoring import score_stats
from roster_theory.providers.formats import ranking_format
from roster_theory.sleeper import SleeperClient, resolve_league_policy_path
from roster_theory.waiver.evaluation import (
    ContingencyScenarioInput,
    PlayerValueInput,
    save_waiver_evaluation_inputs,
)
from roster_theory.waiver.expert_panel import WaiverRosPanelSelector
from roster_theory.trade.board_service import refresh_value_boards
from roster_theory.waiver.policy import load_waiver_policy
from roster_theory.waiver.legality import DropLegality, assess_drop_legality, sleeper_drop_rules
from roster_theory.waiver.snapshot import WaiverSnapshot
from roster_theory.trade.schedule import ScheduleConfig, load_schedule
from roster_theory.waiver.service import refresh_waiver_snapshot
from roster_theory.waiver.ww_evidence import (
    load_waiver_wire_config,
    refresh_waiver_wire_evidence,
)


SUPPORTED_POSITIONS = frozenset({"QB", "RB", "WR", "TE", "K", "DST", "DEF"})
SPECIAL_TEAM_POSITIONS = frozenset({"K", "DST", "DEF"})


def build_drop_legality_evidence(
    snapshot: WaiverSnapshot, schedule: ScheduleConfig,
    matchups: Sequence[Mapping[str, Any]], player_ids: set[str], *, now: datetime,
) -> dict[str, DropLegality]:
    matchup = next((row for row in matchups if str(row.get("roster_id")) == snapshot.user_roster_id), {})
    starters = {str(pid) for pid in matchup.get("starters") or ()}
    players = {row.player_id: row for row in snapshot.players}
    rules = sleeper_drop_rules(dict(snapshot.league.platform_settings))
    games = schedule.games
    if schedule.source == "nflverse nflverse-data schedules release":
        # Compatibility with audited schedule artifacts created before zone metadata.
        games = tuple({"gametime_zone": "US/Eastern", **game} for game in games)
    return {
        pid: assess_drop_legality(
            nfl_team=players[pid].nfl_team,
            starter=pid in starters if "starters" in matchup else None,
            week=snapshot.manifest.current_week, games=games,
            bye_week=dict(schedule.bye_weeks).get(str(players[pid].nfl_team)),
            now=now, **rules,
        ) if pid in players else DropLegality(None, "PLAYER_IDENTITY_UNAVAILABLE")
        for pid in sorted(player_ids)
    }


def _waiver_position(player: object) -> str | None:
    positions = {
        "DST" if str(item).upper() == "DEF" else str(item).upper()
        for item in getattr(player, "positions", ())
    }
    return next(
        (item for item in ("QB", "RB", "WR", "TE", "K", "DST") if item in positions),
        None,
    )


def _stat_number(row: dict[str, object], *names: str) -> float:
    for name in names:
        raw = row.get(name)
        if raw not in (None, "", "-"):
            try:
                return float(raw)
            except (TypeError, ValueError):
                continue
    return 0.0


def _opportunities(row: dict[str, object], position: str) -> float | None:
    if position == "QB":
        return _stat_number(row, "pass_att") + _stat_number(row, "rush_att")
    if position == "RB":
        return _stat_number(row, "rush_att") + _stat_number(row, "rec_tgt")
    if position in {"WR", "TE"}:
        return _stat_number(row, "rec_tgt") + _stat_number(row, "rush_att")
    if position == "K":
        return (
            _stat_number(row, "fgm")
            + _stat_number(row, "fgmiss")
            + _stat_number(row, "xpm")
            + _stat_number(row, "xpmiss")
        )
    return None


def _yards(row: dict[str, object], position: str) -> float | None:
    if position not in {"QB", "RB", "WR", "TE"}:
        return None
    return (
        _stat_number(row, "pass_yd")
        if position == "QB"
        else _stat_number(row, "rush_yd") + _stat_number(row, "rec_yd")
    )


def _rank_by_position(
    metric: dict[str, float], players: dict[str, object]
) -> dict[str, int]:
    grouped: dict[str, list[tuple[str, float]]] = {}
    for player_id, value in metric.items():
        player = players.get(player_id)
        position = _waiver_position(player) if player is not None else None
        if position is not None:
            grouped.setdefault(position, []).append((player_id, value))
    result = {}
    for rows in grouped.values():
        previous = None
        rank = 0
        for index, (player_id, value) in enumerate(sorted(rows, key=lambda item: -item[1]), 1):
            if value != previous:
                rank = index
            result[player_id] = rank
            previous = value
    return result


def _performance_evidence(
    *,
    client: SleeperClient,
    season: int,
    current_week: int,
    players: dict[str, object],
    scoring: dict[str, float],
    as_of: datetime | None = None,
) -> tuple[dict[str, dict[str, object]], tuple[int, ...]]:
    as_of = as_of or datetime.now(timezone.utc)
    completed_weeks = tuple(
        range(max(1, current_week - 2), current_week)
    )
    season_rows = client.season_stats(season)
    weekly_rows = {
        week: client.weekly_stats(season, week) for week in completed_weeks
    }
    season_points = {
        player_id: score_stats(row, scoring, position=next(iter(players[player_id].positions), None)).points
        for player_id, row in season_rows.items()
        if player_id in players
    }
    recent_points: dict[str, float] = {}
    recent_opportunities: dict[str, float] = {}
    recent_yards: dict[str, float] = {}
    recent_samples: dict[str, int | None] = {}
    for player_id, player in players.items():
        position = _waiver_position(player)
        if position is None:
            continue
        rows = tuple(
            weekly_rows[week][player_id]
            for week in completed_weeks
            if player_id in weekly_rows[week]
            and weekly_rows[week][player_id].get("gp") != 0
        )
        if not rows:
            continue
        recent_samples[player_id] = (len(rows) if all(_game_count(row.get("gp")) == 1 for row in rows)
                                     else None)
        recent_points[player_id] = round(
            sum(score_stats(row, scoring, position=player.positions[0]).points for row in rows) / len(rows), 3
        )
        opportunity_values = tuple(
            value for row in rows if (value := _opportunities(row, position)) is not None
        )
        yard_values = tuple(
            value for row in rows if (value := _yards(row, position)) is not None
        )
        if opportunity_values:
            recent_opportunities[player_id] = round(
                sum(opportunity_values) / len(opportunity_values), 3
            )
        if yard_values:
            recent_yards[player_id] = round(sum(yard_values) / len(yard_values), 3)
    season_ranks = _rank_by_position(season_points, players)
    recent_ranks = _rank_by_position(recent_points, players)
    opportunity_ranks = _rank_by_position(recent_opportunities, players)
    yard_ranks = _rank_by_position(recent_yards, players)
    return (
        {
            player_id: {
                "season_points": season_points.get(player_id),
                "season_position_rank": season_ranks.get(player_id),
                "season_sample_size": _game_count(season_rows.get(player_id, {}).get("gp")),
                "performance_as_of": as_of,
                "recent_points_per_game": recent_points.get(player_id),
                "recent_position_rank": recent_ranks.get(player_id),
                "recent_opportunities_per_game": recent_opportunities.get(player_id),
                "recent_opportunity_rank": opportunity_ranks.get(player_id),
                "recent_yards_per_game": recent_yards.get(player_id),
                "recent_yards_rank": yard_ranks.get(player_id),
                "recent_sample_size": recent_samples.get(player_id, 0),
            }
            for player_id in players
        },
        completed_weeks,
    )


def _game_count(value: object) -> int | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0 and value < 100 and int(value) == value:
        return int(value)
    return None


def load_contingency_inputs(
    path: str | Path | None,
    *,
    league_key: str,
    snapshot: object,
    projections: tuple,
) -> tuple[ContingencyScenarioInput, ...]:
    if path is None:
        return ()
    current_week = getattr(getattr(snapshot, "manifest", None), "current_week", None)
    if current_week is None:
        current_week = min((week.week for week in snapshot.weeks), default=None)
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if int(value.get("schema_version") or 0) != 1:
        raise ValueError("Unsupported Waiver contingency-audit schema")
    if str(value.get("product") or "") != "WAIVER ASSISTANT":
        raise ValueError("Contingency audit must be Waiver-scoped")
    if str(value.get("league_key") or "") != league_key:
        raise ValueError("Contingency audit is for a different league")
    players_by_name: dict[str, list] = {}
    for player in snapshot.players:
        players_by_name.setdefault(player.name.casefold(), []).append(player)
    projection_by_key = {
        (row.player_id, row.week): row
        for row in projections
        if row.horizon == "WEEKLY" and row.week is not None
    }
    result: list[ContingencyScenarioInput] = []
    for relationship in value.get("relationships") or ():
        beneficiary_name = str(relationship.get("beneficiary") or "").strip()
        teammate_name = str(relationship.get("unavailable_teammate") or "").strip()
        beneficiary_matches = players_by_name.get(beneficiary_name.casefold(), [])
        teammate_matches = players_by_name.get(teammate_name.casefold(), [])
        if len(beneficiary_matches) != 1 or len(teammate_matches) != 1:
            raise ValueError(
                "Contingency audit player names must resolve exactly: "
                f"{beneficiary_name} / {teammate_name}"
            )
        beneficiary = beneficiary_matches[0]
        teammate = teammate_matches[0]
        if str(relationship.get("scenario_model") or "") != "TEAMMATE_PROJECTION_CEILING":
            raise ValueError(
                "Contingency audit requires TEAMMATE_PROJECTION_CEILING"
            )
        scenario_rows: list[Projection] = []
        for week in snapshot.weeks:
            beneficiary_projection = projection_by_key.get(
                (beneficiary.player_id, week.week)
            )
            teammate_projection = projection_by_key.get((teammate.player_id, week.week))
            if beneficiary_projection is None or teammate_projection is None:
                raise ValueError(
                    "Contingency audit misses a beneficiary or teammate weekly projection: "
                    f"{beneficiary_name} / {teammate_name} / W{week.week}"
                )
            scenario_rows.append(
                Projection(
                    player_id=beneficiary.player_id,
                    horizon="WEEKLY",
                    week=week.week,
                    raw_stats=(),
                    league_points=max(
                        beneficiary_projection.league_points,
                        teammate_projection.league_points,
                    ),
                    source=(
                        "Named teammate-projection ceiling from league-scored FantasyPros inputs; "
                        + str(relationship.get("evidence_source") or "")
                    ),
                    coverage_status=(
                        "complete"
                        if projection_is_complete(
                            beneficiary_projection, current_week=current_week
                        )
                        and projection_is_complete(
                            teammate_projection, current_week=current_week
                        )
                        else "partial"
                    ),
                )
            )
        result.append(
            ContingencyScenarioInput(
                beneficiary_player_id=beneficiary.player_id,
                unavailable_teammate_player_id=teammate.player_id,
                relationship=str(relationship.get("relationship") or ""),
                evidence_source=str(relationship.get("evidence_source") or ""),
                evidence_captured_at=datetime.fromisoformat(
                    str(relationship["evidence_captured_at"])
                ),
                relationship_status=str(
                    relationship.get("relationship_status") or "MISSING"
                ),
                projections=tuple(scenario_rows),
                strongest_uncertainty=str(
                    relationship.get("strongest_uncertainty") or ""
                ),
            )
        )
    return tuple(result)


def build_waiver_inputs(
    league_key: str,
    *,
    output: str | Path | None = None,
    config: str | Path | None = None,
    policy_path: str | Path | None = None,
    waiver_wire_policy_path: str | Path | None = None,
    contingency_file: str | Path | None = None,
) -> dict[str, object]:
    """Build a fresh league-local input bundle and return its audit summary."""

    output_path = Path(
        output or f"data/cache/waiver/{league_key}_live_inputs.json"
    )
    policy = load_waiver_policy(
        resolve_league_policy_path(
            league_key,
            "waiver_decision",
            config_path=config,
            explicit_path=policy_path,
        )
    )
    waiver_state = refresh_waiver_snapshot(league_key, config_path=config).snapshot
    format_evidence = ranking_format(dict(waiver_state.league.scoring), getattr(waiver_state.league, "roster_positions", ()))
    ww_config = load_waiver_wire_config(
        resolve_league_policy_path(league_key, "waiver_wire", config_path=config,
                                  explicit_path=waiver_wire_policy_path), league_key=league_key,
    )
    if ww_config.scoring != format_evidence.scoring:
        raise ValueError("Waiver Wire configuration scoring does not match league format " + format_evidence.scoring)
    board = refresh_value_boards(
        league_key,
        config_path=config,
        budget_path="data/cache/trade/fantasypros/daily_budget.json",
        include_special_teams=True,
        weekly_ranking_max_age=timedelta(hours=2),
        ros_ranking_max_age=timedelta(hours=2),
        ros_experts_max_age=timedelta(hours=2),
        expert_pool_resolver=WaiverRosPanelSelector(league_key),
        require_all_rostered_market_coverage=False,
    )
    snapshot = board.refresh.snapshot
    if (snapshot.league.season != waiver_state.league.season
            or snapshot.league.scoring != waiver_state.league.scoring):
        raise CoverageIncomplete("Waiver snapshot and value-board league season/scoring differ")
    waiver_wire_refresh = refresh_waiver_wire_evidence(
        config=ww_config,
        season=waiver_state.league.season,
        week=waiver_state.manifest.current_week,
        players=board.refresh.snapshot.players,
        current_experts=board.current_experts,
    )
    selected = {row.player_id: row for row in board.selected_final.players}
    market = {row.player_id: row for row in board.market.players}
    current_position_rank = {
        row.player_id: int(row.position_rank)
        for row in board.weekly_rankings
        if row.position_rank is not None
    }
    ros_position_rank = {
        row.player_id: int(row.position_rank)
        for row in board.ros_rankings
        if row.position_rank is not None
    }
    players = {
        **{row.player_id: row for row in snapshot.players},
        **{row.player_id: row for row in waiver_state.players},
    }
    user_team = next(
        row
        for row in waiver_state.teams
        if row.roster_id == waiver_state.user_roster_id
    )
    active_supported_ids = {
        player_id
        for player_id in set(user_team.player_ids) - set(user_team.reserve_ids)
        if player_id in players
        and SUPPORTED_POSITIONS.intersection(players[player_id].positions)
    }
    roster_special_ids = {
        player_id
        for player_id in active_supported_ids
        if SPECIAL_TEAM_POSITIONS.intersection(players[player_id].positions)
    }
    special_ids = {
        player_id
        for player_id in current_position_rank
        if player_id in players
        and SPECIAL_TEAM_POSITIONS.intersection(players[player_id].positions)
    } | roster_special_ids
    skill_ids = set(selected).intersection(market)
    notable_visibility_ids = {
        row.player_id
        for row in waiver_wire_refresh.evidence.players
        if row.match_status == "MATCHED"
        and row.market_overall_rank is not None
        and row.market_overall_rank <= 10
        and row.player_id in players
    } - skill_ids - special_ids
    covered_ids = skill_ids | special_ids | notable_visibility_ids
    sleeper = SleeperClient()
    performance, completed_weeks = _performance_evidence(
        client=sleeper,
        season=waiver_state.league.season,
        current_week=waiver_state.manifest.current_week,
        players=players,
        scoring=dict(waiver_state.league.scoring),
    )
    raw_projection = {
        player_id: sum(
            row.league_points
            for row in board.weekly_projections
            if row.player_id == player_id
        )
        for player_id in special_ids | notable_visibility_ids
    }
    values = tuple(
        PlayerValueInput(
            player_id=player_id,
            selected_value=(selected[player_id].reconciled_vorp if player_id in skill_ids else 0.0),
            market_value=(market[player_id].reconciled_vorp if player_id in skill_ids else 0.0),
            raw_projection=(selected[player_id].raw_projection if player_id in skill_ids else raw_projection[player_id]),
            current_week_position_rank=current_position_rank.get(player_id),
            rest_of_season_position_rank=ros_position_rank.get(player_id),
            selected_rest_of_season_position_rank=(
                selected[player_id].position_rank
                if player_id in skill_ids
                else None
            ),
            coverage_status=(
                "complete"
                if player_id in (skill_ids | special_ids)
                else "incomplete"
            ),
            normalization_basis="LEAGUE_POSITIONAL_VORP",
            long_term_value_horizon=board.stage.mode,
            season_points=performance[player_id]["season_points"],
            season_sample_size=performance[player_id]["season_sample_size"],
            recent_sample_size=performance[player_id]["recent_sample_size"],
            performance_as_of=performance[player_id]["performance_as_of"],
            season_position_rank=performance[player_id]["season_position_rank"],
            recent_points_per_game=performance[player_id]["recent_points_per_game"],
            recent_position_rank=performance[player_id]["recent_position_rank"],
            recent_opportunities_per_game=performance[player_id][
                "recent_opportunities_per_game"
            ],
            recent_opportunity_rank=performance[player_id][
                "recent_opportunity_rank"
            ],
            recent_yards_per_game=performance[player_id]["recent_yards_per_game"],
            recent_yards_rank=performance[player_id]["recent_yards_rank"],
            recent_completed_weeks=completed_weeks,
            performance_source=(
                "Sleeper public season and weekly stats scored under this league's rules"
            ),
            warnings=tuple(
                sorted(
                    {
                        *format_evidence.warnings,
                        *(selected[player_id].warnings if player_id in skill_ids else ()),
                        *(market[player_id].warnings if player_id in skill_ids else ()),
                        *(
                            (
                                "Ranked Waiver candidate is outside complete selected/market value-board coverage; retained for visibility only",
                            )
                            if player_id in notable_visibility_ids
                            else ()
                        ),
                        *(
                            (
                                "K/DST ownership value is intentionally neutral; weekly streaming policy applies",
                            )
                            if player_id in special_ids
                            else ()
                        ),
                        *(
                            (
                                "Current-week position rank is unavailable for this roster incumbent; retained for complete drop comparison",
                            )
                            if player_id in roster_special_ids
                            and player_id not in current_position_rank
                            else ()
                        ),
                    }
                )
            ),
        )
        for player_id in sorted(covered_ids)
    )
    projections = tuple(
        row
        for row in board.weekly_projections
        if row.player_id in covered_ids | active_supported_ids
    )
    contingencies = load_contingency_inputs(
        contingency_file,
        league_key=league_key,
        snapshot=snapshot,
        projections=projections,
    )
    matchups = sleeper.league_matchups(
        waiver_state.league.league_id, waiver_state.manifest.current_week
    )
    schedule = load_schedule(board.refresh.schedule_path, expected_season=waiver_state.league.season)
    captured_at = datetime.now(timezone.utc)
    drop_rules = sleeper_drop_rules(dict(waiver_state.league.platform_settings))
    if drop_rules["league_moves_locked"] is None:
        raise CoverageIncomplete("League move-lock setting unavailable; transaction legality is unproved")
    legality_evidence = build_drop_legality_evidence(
        waiver_state, schedule, matchups, active_supported_ids, now=captured_at,
    )
    proved_locked = {pid for pid, row in legality_evidence.items() if row.legal is False}
    ros_panel_evidence = {
        **dict(board.expert_pool_evidence or {}),
        "missing_rostered_player_ids": list(board.missing_rostered_player_ids),
    }
    save_waiver_evaluation_inputs(
        output_path,
        league_key=league_key,
        captured_at=captured_at,
        availability_source=(
            "current Sleeper roster and matchup delta with supported-position eligibility; "
            "fresh FantasyPros rankings, projections, and material-news feed; exact "
            "free-agent/waivers mechanism and pending claims informational"
        ),
        availability_by_player={},
        drop_legality={
            player_id: legality_evidence[player_id].legal
            for player_id in sorted(active_supported_ids)
        },
        weeks=snapshot.weeks,
        projections=projections,
        values=values,
        news_fresh={player_id: True for player_id in sorted(covered_ids)},
        contingencies=contingencies,
        waiver_wire_evidence=waiver_wire_refresh.evidence,
        ros_panel_evidence=ros_panel_evidence,
        drop_legality_evidence={pid: asdict(row) for pid, row in legality_evidence.items()},
    )
    return {
        "operation": "WAIVER LIVE INPUT BUILD",
        "league": league_key,
        "policy_version": policy.version,
        "policy_hash": policy.policy_hash,
        "captured_at": captured_at.isoformat(),
        "covered_value_players": len(values),
        "weekly_projection_rows": len(projections),
        "performance_completed_weeks": list(completed_weeks),
        "performance_players": sum(
            1 for row in performance.values() if row["season_points"] is not None
        ),
        "contingency_relationships": len(contingencies),
        "user_drop_legality_rows": len(active_supported_ids),
        "user_players_missing_value_inputs": sorted(active_supported_ids - covered_ids),
        "league_rostered_players_missing_value_board": list(
            board.missing_rostered_player_ids
        ),
        "proved_locked_user_players": sorted(proved_locked),
        "unknown_drop_legality_players": [pid for pid, row in legality_evidence.items() if row.legal is None],
        "drop_legality_evidence": {pid: asdict(row) for pid, row in legality_evidence.items()},
        "drop_rules": drop_rules,
        "fantasypros_calls": (
            board.call_plan.fantasypros_calls
            + waiver_wire_refresh.call_plan.fantasypros_calls
        ),
        "fantasypros_cache_hits": (
            board.call_plan.cache_hits
            + waiver_wire_refresh.call_plan.cache_hits
        ),
        "waiver_wire_complete": waiver_wire_refresh.evidence.complete,
        "waiver_wire_market_complete": waiver_wire_refresh.evidence.market_complete,
        "waiver_wire_selected_experts_complete": (
            waiver_wire_refresh.evidence.selected_experts_complete
        ),
        "waiver_wire_ranking_source": waiver_wire_refresh.evidence.ranking_source,
        "waiver_wire_trusted_expert_ids": list(
            waiver_wire_refresh.evidence.trusted_expert_ids
        ),
        "waiver_wire_expert_selection": [
            {
                "expert_id": row.expert_id,
                "expert_name": row.expert_name,
                "latest_accuracy_rank": row.latest_accuracy_rank,
                "prior_accuracy_rank": row.prior_accuracy_rank,
                "status": row.status,
                "reason": row.reason,
            }
            for row in waiver_wire_refresh.evidence.expert_selection
        ],
        "waiver_wire_warnings": list(waiver_wire_refresh.evidence.warnings),
        "ros_panel": ros_panel_evidence,
        "fantasypros_remaining_after_plan": (
            board.call_plan.fantasypros_remaining_after_plan
        ),
        "output_path": str(output_path),
        "sleeper_write_performed": False,
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Build fresh read-only Waiver Assistant inputs for a configured league"
    )
    parser.add_argument(
        "league", help="Configured league key with league-local Waiver policy files"
    )
    parser.add_argument("--output")
    parser.add_argument("--config", help="League configuration JSON")
    parser.add_argument("--policy", help="Waiver decision policy override")
    parser.add_argument(
        "--waiver-wire-policy", help="Waiver Wire evidence policy override"
    )
    parser.add_argument(
        "--contingency-file",
        help="Optional league-scoped named-role evidence for counterfactual audit",
    )
    args = parser.parse_args(argv)
    result = build_waiver_inputs(
        args.league,
        output=args.output,
        config=args.config,
        policy_path=args.policy,
        waiver_wire_policy_path=args.waiver_wire_policy,
        contingency_file=args.contingency_file,
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()



