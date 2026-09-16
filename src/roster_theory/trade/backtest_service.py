from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from roster_theory.fantasypros import FantasyProsClient
from roster_theory.providers.cache import (
    DailyRequestBudget,
    atomic_write_json,
    cache_key,
)
from roster_theory.trade.backtest import (
    DraftProxyBacktest,
    DraftProxyForecast,
    run_draft_proxy_backtest,
    write_draft_proxy_backtest,
)
from roster_theory.trade.call_plan import CallPlan, PlannedCall, build_call_plan


BACKTEST_LIMITS: Mapping[str, int] = {"QB": 30, "RB": 70, "WR": 90, "TE": 35}


@dataclass(frozen=True, slots=True)
class HistoricalBacktestResult:
    rows: tuple[DraftProxyForecast, ...]
    backtest: DraftProxyBacktest
    call_plan: CallPlan
    output_path: Path
    date_precision_warning: bool


def _budget(path: Path) -> DailyRequestBudget:
    if not path.exists():
        return DailyRequestBudget()
    return DailyRequestBudget.from_json(json.loads(path.read_text(encoding="utf-8")))


def _cache_payload(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    payload = value.get("payload")
    return value if isinstance(payload, dict) else None


def historical_backtest_plan(
    seasons: Sequence[int],
    weeks: Sequence[int],
    *,
    cache_dir: Path,
    budget: DailyRequestBudget,
) -> tuple[CallPlan, dict[str, Path], dict[str, dict[str, Any]]]:
    definitions: list[tuple[str, str, dict[str, Any]]] = []
    for season in seasons:
        for position in BACKTEST_LIMITS:
            definitions.append(
                (
                    f"draft_{season}_{position}",
                    f"/nfl/{season}/consensus-rankings",
                    {
                        "position": position,
                        "scoring": "HALF",
                        "type": "DRAFT",
                        "experts": "show",
                    },
                )
            )
            definitions.append(
                (
                    f"points_{season}_{position}",
                    f"/nfl/{season}/player-points",
                    {
                        "start": min(weeks),
                        "end": max(weeks),
                        "position": position,
                        "scoring": "HALF",
                    },
                )
            )
            for week in weeks:
                definitions.append(
                    (
                        f"weekly_{season}_{week}_{position}",
                        f"/nfl/{season}/consensus-rankings",
                        {
                            "position": position,
                            "scoring": "HALF",
                            "week": week,
                            "experts": "show",
                        },
                    )
                )
    calls: list[PlannedCall] = []
    paths: dict[str, Path] = {}
    cached: dict[str, dict[str, Any]] = {}
    for name, endpoint, parameters in definitions:
        path = cache_dir / f"{cache_key(endpoint, parameters)}.json"
        record = _cache_payload(path)
        paths[name] = path
        if record is not None:
            cached[name] = record
        calls.append(
            PlannedCall(
                name=name,
                provider="FantasyPros",
                endpoint=endpoint,
                parameters=tuple(sorted(parameters.items())),
                fresh_cache_hit=record is not None,
            )
        )
    return build_call_plan(calls, budget), paths, cached


def _position_rank(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        match = re.search(r"(\d+(?:\.\d+)?)$", str(value or ""))
        return float(match.group(1)) if match else None


def _dated(year: int, value: Any, *, end_of_day: bool = False) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError("Historical ranking response lacks last_updated")
    if re.fullmatch(r"\d{1,2}/\d{1,2}", text):
        month, day = (int(item) for item in text.split("/"))
        calendar_year = year + 1 if month <= 2 else year
        hour, minute, second = (23, 59, 59) if end_of_day else (0, 0, 0)
        return datetime(
            calendar_year, month, day, hour, minute, second, tzinfo=timezone.utc
        ).isoformat()
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def _ranks(payload: Mapping[str, Any]) -> dict[str, float]:
    result: dict[str, float] = {}
    for row in payload.get("players") or ():
        if not isinstance(row, Mapping) or row.get("player_id") is None:
            continue
        rank = _position_rank(row.get("pos_rank"))
        if rank is not None:
            result[str(row["player_id"])] = rank
    return result


def _teams(payload: Mapping[str, Any]) -> dict[str, str]:
    return {
        str(row["player_id"]): str(row.get("player_team_id") or "").upper()
        for row in payload.get("players") or ()
        if isinstance(row, Mapping) and row.get("player_id") is not None
    }


def load_historical_byes(
    path: str | Path = "data/manual/nfl/nfl_byes_2024_2025.json",
) -> dict[int, dict[str, int]]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    result = {
        int(season): {str(team): int(week) for team, week in teams.items()}
        for season, teams in (value.get("seasons") or {}).items()
    }
    for season, teams in result.items():
        if len(teams) != 32 or any(week < 5 or week > 14 for week in teams.values()):
            raise ValueError(f"Historical bye schedule is incomplete for {season}")
    return result


def _weekly_points(payload: Mapping[str, Any]) -> dict[str, dict[int, float]]:
    result: dict[str, dict[int, float]] = {}
    for row in payload.get("players") or ():
        if not isinstance(row, Mapping) or row.get("player_id") is None:
            continue
        weeks = row.get("weeks") or {}
        if isinstance(weeks, Mapping):
            result[str(row["player_id"])] = {
                int(week): float(points)
                for week, points in weeks.items()
                if points not in (None, "")
            }
    return result


def _collect_rows(
    values: Mapping[str, Mapping[str, Any]],
    seasons: Sequence[int],
    weeks: Sequence[int],
    bye_by_season: Mapping[int, Mapping[str, int]],
) -> tuple[DraftProxyForecast, ...]:
    provisional: list[dict[str, Any]] = []
    for season in seasons:
        outcome_at = datetime(season + 1, 2, 1, tzinfo=timezone.utc).isoformat()
        for position, limit in BACKTEST_LIMITS.items():
            draft_payload = values[f"draft_{season}_{position}"]["payload"]
            draft = _ranks(draft_payload)
            draft_teams = _teams(draft_payload)
            points = _weekly_points(values[f"points_{season}_{position}"]["payload"])
            draft_published = _dated(season, draft_payload.get("last_updated"))
            for week in weeks:
                weekly_payload = values[f"weekly_{season}_{week}_{position}"]["payload"]
                weekly = _ranks(weekly_payload)
                weekly_published = _dated(season, weekly_payload.get("last_updated"))
                cutoff = _dated(season, weekly_payload.get("last_updated"), end_of_day=True)
                worst_weekly = max(weekly.values(), default=float(limit)) + 1.0
                candidates = sorted(
                    (
                        (player_id, draft_rank)
                        for player_id, draft_rank in draft.items()
                        if draft_rank <= limit and player_id in points
                    ),
                    key=lambda item: (item[1], item[0]),
                )
                for player_id, draft_rank in candidates:
                    remaining = sum(
                        value
                        for outcome_week, value in points[player_id].items()
                        if week <= outcome_week <= max(weeks)
                    )
                    raw_weekly = weekly.get(player_id, worst_weekly)
                    # Archived weekly ECR commonly omits bye players. The
                    # adjusted control restores an omitted player to the
                    # long-term order rather than interpreting absence as a
                    # collapse in ownership value.
                    on_bye = (
                        bye_by_season.get(season, {}).get(draft_teams.get(player_id, ""))
                        == week
                    )
                    adjusted = (
                        draft_rank
                        if on_bye and player_id not in weekly
                        else weekly.get(player_id, worst_weekly)
                    )
                    provisional.append(
                        {
                            "season": season,
                            "week": week,
                            "player_id": player_id,
                            "position": position,
                            "draft_rank": draft_rank,
                            "weekly_rank": raw_weekly,
                            "adjusted_weekly_rank": adjusted,
                            "actual_points": remaining,
                            "forecast_cutoff": cutoff,
                            "draft_published_at": draft_published,
                            "weekly_published_at": weekly_published,
                            "outcome_available_at": outcome_at,
                        }
                    )
    replacement: dict[tuple[int, int, str], float] = {}
    for key in sorted(
        {(row["season"], row["week"], row["position"]) for row in provisional}
    ):
        values_at_key = sorted(
            (
                float(row["actual_points"])
                for row in provisional
                if (row["season"], row["week"], row["position"]) == key
            ),
            reverse=True,
        )
        index = min(len(values_at_key), max(1, int(round(len(values_at_key) * 0.60)))) - 1
        replacement[key] = values_at_key[index]
    return tuple(
        DraftProxyForecast(
            actual_lineup_value=max(
                0.0,
                float(row["actual_points"])
                - replacement[(row["season"], row["week"], row["position"])],
            ),
            **row,
        )
        for row in provisional
    )


def run_historical_draft_proxy_study(
    *,
    seasons: Sequence[int] = (2024, 2025),
    weeks: Sequence[int] = tuple(range(1, 18)),
    cache_dir: str | Path = "data/cache/trade/fantasypros/historical_draft_proxy",
    budget_path: str | Path = "data/cache/trade/fantasypros/daily_budget.json",
    output_path: str | Path = "data/exports/trade/draft_proxy_backtest_2024_2025.json",
    bye_path: str | Path = "data/manual/nfl/nfl_byes_2024_2025.json",
    client: FantasyProsClient | None = None,
) -> HistoricalBacktestResult:
    target_cache = Path(cache_dir)
    target_budget = Path(budget_path)
    budget = _budget(target_budget)
    plan, paths, cached = historical_backtest_plan(
        seasons, weeks, cache_dir=target_cache, budget=budget
    )
    if plan.fantasypros_calls:
        budget.reserve(plan.fantasypros_calls)
        atomic_write_json(target_budget, budget.to_json())
    values: dict[str, dict[str, Any]] = dict(cached)
    provider = client or FantasyProsClient()
    last_request = 0.0
    for call in plan.calls:
        if call.fresh_cache_hit:
            continue
        elapsed = time.monotonic() - last_request
        if last_request and elapsed < 1.05:
            time.sleep(1.05 - elapsed)
        params = dict(call.parameters)
        season = int(call.name.split("_")[1])
        if call.name.startswith("points_"):
            payload = provider.player_points(season, **params)
        else:
            payload = provider.consensus_rankings(season, **params)
        record = {
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "payload": payload,
        }
        atomic_write_json(paths[call.name], record)
        values[call.name] = record
        last_request = time.monotonic()
    rows = _collect_rows(values, seasons, weeks, load_historical_byes(bye_path))
    backtest = run_draft_proxy_backtest(rows)
    output = write_draft_proxy_backtest(output_path, backtest)
    return HistoricalBacktestResult(
        rows=rows,
        backtest=backtest,
        call_plan=plan,
        output_path=output,
        date_precision_warning=True,
    )
