from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from roster_theory.providers.cache import DailyRequestBudget, is_fresh
from roster_theory.providers.sleeper import SleeperAdapter
from roster_theory.schedule_inputs import default_schedule_path
from roster_theory.sleeper import SleeperClient, find_league_config, load_owner_config
from roster_theory.trade.call_plan import CallPlan, PlannedCall, build_call_plan
from roster_theory.trade.schedule import load_schedule
from roster_theory.trade.snapshot import TradeSnapshot, build_trade_snapshot, save_trade_snapshot


@dataclass(frozen=True, slots=True)
class RefreshResult:
    snapshot: TradeSnapshot
    call_plan: CallPlan
    output_path: Path
    schedule_path: Path | None = None
    schedule_captured_at: str | None = None
    schedule_fresh: bool | None = None
    schedule_age_seconds: int | None = None


def _player_cache_fresh(path: Path, now: datetime) -> bool:
    if not path.exists():
        return False
    try:
        import json

        value = json.loads(path.read_text(encoding="utf-8"))
        captured_at = datetime.fromisoformat(str(value["captured_at"]))
        return is_fresh(captured_at, timedelta(hours=24), now=now)
    except (KeyError, TypeError, ValueError):
        return False


def sleeper_refresh_plan(
    league_id: str,
    weeks: tuple[int, ...],
    *,
    player_cache_hit: bool,
    budget: DailyRequestBudget | None = None,
) -> CallPlan:
    calls = [
        PlannedCall("nfl_state", "Sleeper", "/state/nfl"),
        PlannedCall("league", "Sleeper", f"/league/{league_id}"),
        PlannedCall("users", "Sleeper", f"/league/{league_id}/users"),
        PlannedCall("rosters", "Sleeper", f"/league/{league_id}/rosters"),
        PlannedCall("winners_bracket", "Sleeper", f"/league/{league_id}/winners_bracket"),
        PlannedCall("losers_bracket", "Sleeper", f"/league/{league_id}/losers_bracket"),
        PlannedCall(
            "players",
            "Sleeper",
            "/players/nfl",
            fresh_cache_hit=player_cache_hit,
        ),
    ]
    for week in weeks:
        calls.extend(
            (
                PlannedCall(
                    f"matchups_{week}",
                    "Sleeper",
                    f"/league/{league_id}/matchups/{week}",
                ),
                PlannedCall(
                    f"transactions_{week}",
                    "Sleeper",
                    f"/league/{league_id}/transactions/{week}",
                ),
            )
        )
    return build_call_plan(calls, budget or DailyRequestBudget())


def refresh_trade_snapshot(
    league_key: str,
    *,
    config_path: str | Path | None = None,
    ranking_horizon: str = "WEEKLY-PROXY",
    schedule_path: str | Path | None = None,
    player_cache_path: str | Path = "data/cache/trade/sleeper/players_nfl.json",
    output_path: str | Path | None = None,
    client: SleeperClient | None = None,
    include_special_team_identities: bool = False,
) -> RefreshResult:
    league_config = find_league_config(league_key, config_path)
    owner = load_owner_config(config_path)
    league_id = str(league_config["league_id"])
    season = int(league_config["season"])
    user_id = str(owner.get("sleeper_user_id") or "")
    if not user_id:
        raise ValueError("Configured Sleeper user ID is required")
    resolved_schedule_path = (
        Path(schedule_path) if schedule_path else default_schedule_path(season)
    )
    schedule = load_schedule(resolved_schedule_path, expected_season=season)
    now = datetime.now(timezone.utc)
    schedule_captured_at = datetime.fromisoformat(
        (schedule.captured_at or schedule.verified_at).replace("Z", "+00:00")
    )
    if schedule_captured_at.tzinfo is None:
        schedule_captured_at = schedule_captured_at.replace(tzinfo=timezone.utc)
    schedule_age_seconds = max(0, int((now - schedule_captured_at).total_seconds()))
    cache_path = Path(player_cache_path)
    plan = sleeper_refresh_plan(
        league_id,
        schedule.weeks,
        player_cache_hit=_player_cache_fresh(cache_path, now),
    )
    bundle = SleeperAdapter(
        client or SleeperClient(), player_cache_path=cache_path
    ).fetch(league_id, list(schedule.weeks))
    snapshot = build_trade_snapshot(
        league_key=league_key,
        user_id=user_id,
        ranking_horizon=ranking_horizon,
        sleeper=bundle,
        schedule=schedule,
        valuation_inputs_complete=False,
        warnings=(),
        include_special_team_identities=include_special_team_identities,
    )
    target = Path(
        output_path
        or Path("data/exports/trade")
        / league_key
        / snapshot.manifest.analysis_id
        / "snapshot.json"
    )
    save_trade_snapshot(snapshot, target)
    return RefreshResult(
        snapshot=snapshot,
        call_plan=plan,
        output_path=target,
        schedule_path=resolved_schedule_path,
        schedule_captured_at=schedule.captured_at or schedule.verified_at,
        schedule_fresh=schedule_age_seconds <= int(timedelta(hours=24).total_seconds()),
        schedule_age_seconds=schedule_age_seconds,
    )


def refresh_report(result: RefreshResult) -> dict[str, Any]:
    snapshot = result.snapshot
    return {
        "product": snapshot.product,
        "operation": "DATA-ONLY REFRESH",
        "league": snapshot.league_key,
        "season": snapshot.league.season,
        "current_week": snapshot.manifest.current_week,
        "evaluation_horizon": [
            snapshot.manifest.horizon_start,
            snapshot.manifest.horizon_end,
        ],
        "ranking_horizon": snapshot.ranking_horizon,
        "current": snapshot.current,
        "snapshot_complete": snapshot.completeness.snapshot_complete,
        "valuation_inputs_complete": snapshot.completeness.valuation_inputs_complete,
        "teams": len(snapshot.teams),
        "owned_players": len(snapshot.owner_by_player),
        "rostered_tradeable_players": len(
            set(snapshot.tradeable_player_ids).intersection(dict(snapshot.owner_by_player))
        ),
        "tradeable_players": len(snapshot.tradeable_player_ids),
        "free_agents": len(snapshot.free_agent_ids),
        "weeks": len(snapshot.weeks),
        "user_roster_id": snapshot.user_roster_id,
        "manifest_id": snapshot.manifest.analysis_id,
        "call_plan": {
            "total": len(result.call_plan.calls),
            "required": result.call_plan.required_calls,
            "optional": result.call_plan.optional_calls,
            "cache_hits": result.call_plan.cache_hits,
            "fantasypros_calls": result.call_plan.fantasypros_calls,
            "fantasypros_remaining_after_plan": result.call_plan.fantasypros_remaining_after_plan,
        },
        "warnings": list(snapshot.warnings),
        "snapshot_path": str(result.output_path),
        "schedule": {
            "path": str(result.schedule_path) if result.schedule_path else None,
            "captured_at": result.schedule_captured_at,
            "fresh": result.schedule_fresh,
            "age_seconds": result.schedule_age_seconds,
            "refresh_command": f"roster-theory inputs schedule refresh {snapshot.league_key}",
        },
        "recommendation_generated": False,
        "sleeper_write_performed": False,
    }
