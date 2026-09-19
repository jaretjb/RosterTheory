from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from roster_theory.core.models import Projection
from roster_theory.sleeper import SleeperClient, resolve_league_policy_path
from roster_theory.waiver.evaluation import (
    ContingencyScenarioInput,
    PlayerValueInput,
    projection_coverage_is_complete,
    save_waiver_evaluation_inputs,
)
from roster_theory.trade.board_service import refresh_value_boards
from roster_theory.waiver.policy import load_waiver_policy
from roster_theory.waiver.service import refresh_waiver_snapshot
from roster_theory.waiver.ww_evidence import (
    load_waiver_wire_config,
    refresh_waiver_wire_evidence,
)


SUPPORTED_POSITIONS = frozenset({"QB", "RB", "WR", "TE", "K", "DST", "DEF"})
SPECIAL_TEAM_POSITIONS = frozenset({"K", "DST", "DEF"})


def load_contingency_inputs(
    path: str | Path | None,
    *,
    league_key: str,
    snapshot: object,
    projections: tuple,
) -> tuple[ContingencyScenarioInput, ...]:
    if path is None:
        return ()
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
                        if projection_coverage_is_complete(
                            beneficiary_projection.coverage_status
                        )
                        and projection_coverage_is_complete(
                            teammate_projection.coverage_status
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
    board = refresh_value_boards(
        league_key,
        config_path=config,
        cache_dir="data/cache/waiver/fantasypros/2026",
        budget_path="data/cache/trade/fantasypros/daily_budget.json",
        include_special_teams=True,
        weekly_ranking_max_age=timedelta(hours=2),
        ros_ranking_max_age=timedelta(hours=2),
        ros_experts_max_age=timedelta(hours=2),
    )
    snapshot = board.refresh.snapshot
    waiver_state = refresh_waiver_snapshot(
        league_key, config_path=config
    ).snapshot
    waiver_wire_refresh = refresh_waiver_wire_evidence(
        config=load_waiver_wire_config(
            resolve_league_policy_path(
                league_key,
                "waiver_wire",
                config_path=config,
                explicit_path=waiver_wire_policy_path,
            ),
            league_key=league_key,
        ),
        season=waiver_state.league.season,
        week=waiver_state.manifest.current_week,
        players=board.refresh.snapshot.players,
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
            coverage_status=(
                "complete"
                if player_id in (skill_ids | special_ids)
                else "incomplete"
            ),
            normalization_basis="LEAGUE_POSITIONAL_VORP",
            long_term_value_horizon=board.stage.mode,
            warnings=tuple(
                sorted(
                    {
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
        row for row in board.weekly_projections if row.player_id in covered_ids
    )
    contingencies = load_contingency_inputs(
        contingency_file,
        league_key=league_key,
        snapshot=snapshot,
        projections=projections,
    )
    matchups = SleeperClient().league_matchups(
        waiver_state.league.league_id, waiver_state.manifest.current_week
    )
    user_matchup = next(
        row
        for row in matchups
        if str(row.get("roster_id")) == waiver_state.user_roster_id
    )
    starters = {str(player_id) for player_id in user_matchup.get("starters") or ()}
    points = {
        str(player_id): float(value or 0.0)
        for player_id, value in (user_matchup.get("players_points") or {}).items()
    }
    proved_locked = {
        player_id
        for player_id in active_supported_ids.intersection(starters)
        if points.get(player_id, 0.0) != 0.0
    }
    captured_at = datetime.now(timezone.utc)
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
            player_id: player_id not in proved_locked
            for player_id in sorted(active_supported_ids)
        },
        weeks=snapshot.weeks,
        projections=projections,
        values=values,
        news_fresh={player_id: True for player_id in sorted(covered_ids)},
        contingencies=contingencies,
        waiver_wire_evidence=waiver_wire_refresh.evidence,
    )
    return {
        "operation": "WAIVER LIVE INPUT BUILD",
        "league": league_key,
        "policy_version": policy.version,
        "policy_hash": policy.policy_hash,
        "captured_at": captured_at.isoformat(),
        "covered_value_players": len(values),
        "weekly_projection_rows": len(projections),
        "contingency_relationships": len(contingencies),
        "user_drop_legality_rows": len(active_supported_ids),
        "user_players_missing_value_inputs": sorted(active_supported_ids - covered_ids),
        "proved_locked_user_players": sorted(proved_locked),
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
        "waiver_wire_warnings": list(waiver_wire_refresh.evidence.warnings),
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



