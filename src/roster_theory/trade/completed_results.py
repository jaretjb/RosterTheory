"""Read-only, league-scoped actuals for the prospective Trade capture ledger.

Sleeper matchup player totals are already scored by that league. Raw stats are
used only to verify participation, never to fill missing scoring fields with
zero. nflverse final scores verify completion; its observation time is a
conservative completion bound, not an invented final-whistle timestamp.
"""
from __future__ import annotations

import csv
import io
import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from math import isfinite
from pathlib import Path

from roster_theory.core.errors import SourceUnavailable
from roster_theory.core.provenance import stable_hash
from roster_theory.core.schedule_time import kickoff_time
from roster_theory.providers.cache import atomic_write_json
from roster_theory.providers.nflverse import (
    fetch_nflverse_schedule, load_schedule_evidence, save_schedule_evidence,
)
from roster_theory.sleeper import SleeperClient, SleeperError
from roster_theory.trade.performance import CompletedPerformanceOutcome


SOURCE = "Sleeper league players_points + nflverse observed final/v1"
TEAM_ALIASES = {"LA": "LAR", "JAC": "JAX", "WSH": "WAS", "OAK": "LV", "SD": "LAC"}


def _time(value):
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("Outcome source timestamp must be timezone-aware")
    return result


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if isfinite(value) else None


def capture_teams(snapshot, expectations, archive_root):
    """Recover team identity only from the exact original capture snapshot."""
    wanted = {row.captured_at.isoformat() for row in expectations}
    found = {}
    warnings = []
    for path in sorted(Path(archive_root).glob("*/snapshot.json")):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            if value.get("captured_at") not in wanted:
                continue
            if (value.get("league_key") != snapshot.league_key
                    or value["league"]["league_id"] != snapshot.league.league_id
                    or value["league"]["season"] != snapshot.league.season
                    or stable_hash(value["league"]["scoring"]) != stable_hash(snapshot.league.scoring)):
                continue
            for player in value["players"]:
                key = (player["player_id"], value["captured_at"])
                found.setdefault(key, set()).add(player.get("nfl_team"))
        except (OSError, ValueError, KeyError, TypeError):
            warnings.append(f"Could not verify archived capture {path.name}")
    # New captures carry their own immutable team; never use today's team for
    # an older capture. A conflict is unavailable rather than arbitrarily won.
    for row in expectations:
        if row.nfl_team:
            found.setdefault((row.player_id, row.captured_at.isoformat()), set()).add(row.nfl_team)
    return {key: next(iter(values)) for key, values in found.items()
            if len(values) == 1 and None not in values}, warnings


def collect_completed_results(snapshot, expectations, existing, *, window_weeks,
                              client=None, cache_root=None, archive_root=None, now=None):
    """Collect prior-week outcomes; failures remain optional and visible."""
    now = now or datetime.now(timezone.utc)
    first = max(1, snapshot.manifest.current_week - window_weeks)
    relevant = [row for row in expectations if first <= row.week < snapshot.manifest.current_week]
    summary = {"status": "NO_PRIOR_CAPTURES", "added_outcomes": 0,
               "exclusions": [], "sources": [], "warnings": []}
    if not snapshot.current or not relevant:
        return (), summary
    manual = {(row.player_id, row.week) for row in existing if row.source != SOURCE}
    relevant = [row for row in relevant if (row.player_id, row.week) not in manual]
    if not relevant:
        summary["status"] = "PRESERVED_IMPORTS"
        return (), summary
    client = client or SleeperClient()
    root = Path(cache_root or "data/cache/trade/performance/sources")
    root.mkdir(parents=True, exist_ok=True)
    teams, warnings = capture_teams(snapshot, relevant,
        archive_root or Path("data/exports/trade") / snapshot.league_key)
    summary["warnings"].extend(warnings)
    if not teams:
        summary["status"] = "UNAVAILABLE"
        summary["warnings"].append("No verified historical team identities for prior captures")
        return (), summary
    schedule_path = root / "nflverse-final-scores.json"
    try:
        schedule = load_schedule_evidence(schedule_path) if schedule_path.exists() else None
        if schedule is None or not timedelta(0) <= now - _time(schedule.captured_at) <= timedelta(hours=24):
            schedule = fetch_nflverse_schedule()
            save_schedule_evidence(schedule, schedule_path)
        observed_final = _time(schedule.captured_at)
        games = {}
        for game in csv.DictReader(io.StringIO(schedule.content)):
            if int(game["season"]) != snapshot.league.season or game["game_type"] != "REG":
                continue
            for team in (game["home_team"], game["away_team"]):
                games.setdefault((int(game["week"]), TEAM_ALIASES.get(team, team)), []).append(game)
        summary["sources"].append({"source": schedule.source, "captured_at": schedule.captured_at,
                                   "payload_hash": schedule.response_hash})
    except (OSError, ValueError, KeyError, TypeError, SourceUnavailable) as exc:
        summary.update(status="UNAVAILABLE", warnings=[*warnings, f"Completed schedule unavailable: {exc}"])
        return (), summary

    scoring = stable_hash(snapshot.league.scoring)
    prior = {(row.player_id, row.week): row for row in sorted(existing, key=lambda x: x.captured_at)}
    results = []
    failures = 0
    for week in sorted({row.week for row in relevant}):
        scope = (snapshot.league.league_id, snapshot.league.season, week, scoring)
        path = root / f"{stable_hash(scope)[:24]}.json"
        try:
            cached = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
            if (cached is None or cached.get("scope") != list(scope)
                    or cached.get("payload_hash") != stable_hash(cached["payload"])
                    or _time(cached["captured_at"]) < observed_final
                    or not timedelta(0) <= now - _time(cached["captured_at"]) <= timedelta(hours=24)):
                payload = {"matchups": client.league_matchups(snapshot.league.league_id, week),
                           "participation": client.weekly_stats(snapshot.league.season, week)}
                cached = {"scope": scope, "captured_at": datetime.now(timezone.utc).isoformat(),
                          "payload": payload, "payload_hash": stable_hash(payload)}
                atomic_write_json(path, cached)
            captured = _time(cached["captured_at"])
            if captured < observed_final:
                raise ValueError("Results precede the verified final-score observation")
            summary["sources"].append({"source": SOURCE, "week": week,
                "captured_at": cached["captured_at"], "payload_hash": cached["payload_hash"]})
            points = {}
            if not isinstance(cached["payload"]["matchups"], list):
                raise ValueError("Matchup results must be a list")
            for matchup in cached["payload"]["matchups"]:
                if not isinstance(matchup, dict) or not isinstance(matchup.get("players_points", {}), dict):
                    raise ValueError("Malformed matchup player results")
                for pid, value in (matchup.get("players_points") or {}).items():
                    if pid in (matchup.get("players") or []):
                        points.setdefault(pid, set()).add(_number(value))
            rows = cached["payload"]["participation"]
            if not isinstance(rows, dict) or any(not isinstance(row, dict) for row in rows.values()):
                raise ValueError("Malformed participation results")
        except (OSError, ValueError, KeyError, TypeError, SleeperError) as exc:
            summary["warnings"].append(f"Week {week} results unavailable: {exc}")
            failures += 1
            continue
        for pid in sorted({row.player_id for row in relevant if row.week == week}):
            key = (pid, week)
            if key in prior and prior[key].source != SOURCE:
                continue  # Preserve verified manual availability/partial-game annotations.
            captures = [row for row in relevant if row.week == week and row.player_id == pid]
            identities = {(row.position, teams.get((pid, row.captured_at.isoformat()))) for row in captures}
            reason = None
            if len(identities) != 1 or next(iter(identities))[1] is None:
                reason = "HISTORICAL_TEAM_UNAVAILABLE_OR_AMBIGUOUS"
            else:
                position, team = next(iter(identities))
                matched = games.get((week, TEAM_ALIASES.get(team, team)), [])
                if len(matched) != 1:
                    reason = "BYE_OR_GAME_UNAVAILABLE"
                else:
                    game = matched[0]
                    start = kickoff_time({**game, "gametime_zone": "US/Eastern"})
                    # nflverse scores are final results. Nonempty finite scores
                    # and a later observation are required; elapsed time alone
                    # never proves a game finished.
                    try:
                        final = all(isfinite(float(game[name])) and float(game[name]) >= 0
                                    for name in ("home_score", "away_score"))
                    except (KeyError, TypeError, ValueError):
                        final = False
                    if not final or start is None or start >= observed_final:
                        reason = "GAME_NOT_VERIFIED_COMPLETE"
                    elif pid not in points or len(points[pid]) != 1 or None in points[pid]:
                        reason = "LEAGUE_PLAYER_POINTS_UNAVAILABLE_OR_AMBIGUOUS"
                    elif _number(rows.get(pid, {}).get("gp")) != 1:
                        reason = "PARTICIPATION_UNVERIFIED"
            if reason:
                summary["exclusions"].append({"player_id": pid, "week": week, "reason": reason})
                continue
            outcome = CompletedPerformanceOutcome(snapshot.league_key, snapshot.league.season,
                pid, week, position, start, observed_final, captured, next(iter(points[pid])),
                None, "PLAYED", scoring, SOURCE)
            old = prior.get(key)
            if old and (old.actual_points, old.position, old.game_started_at, old.availability) == (
                    outcome.actual_points, outcome.position, outcome.game_started_at, outcome.availability):
                continue
            results.append(outcome)
    summary["added_outcomes"] = len(results)
    summary["status"] = "PARTIAL" if failures or summary["exclusions"] else "COMPLETE"
    summary["exclusion_counts"] = dict(Counter(row["reason"] for row in summary["exclusions"]))
    summary["warnings"].append("Played means verified participation; automated early-exit injury detection is unavailable. Manual partial-game annotations take precedence.")
    return tuple(results), summary
