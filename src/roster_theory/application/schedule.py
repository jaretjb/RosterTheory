from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from roster_theory.core.errors import ScheduleIncomplete
from roster_theory.providers.sleeper import SleeperMatchupWeek
from roster_theory.schedule_inputs import validate_schedule_document


@dataclass(frozen=True, slots=True)
class ScheduleConfig:
    season: int
    weeks: tuple[int, ...]
    teams: tuple[str, ...]
    bye_weeks: tuple[tuple[str, int], ...]
    source: str
    source_url: str
    verified_at: str
    payload_hash: str
    endpoint: str = ""
    captured_at: str = ""
    response_hash: str = ""
    license: str = ""
    use_restriction: str = ""
    games: tuple[Mapping[str, Any], ...] = ()


@dataclass(frozen=True, slots=True)
class EvaluationWeek:
    week: int
    playoff: bool
    fantasy_matchup_rows: int
    fantasy_matchups_complete: bool
    bye_teams: tuple[str, ...]
    nfl_schedule_complete: bool


def load_schedule(
    path: str | Path,
    *,
    expected_season: int | None = None,
) -> ScheduleConfig:
    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(
            f"NFL schedule not found: {source}. Run roster-theory inputs schedule "
            "refresh LEAGUE, or pass --schedule PATH. No real schedule is bundled."
        )
    value = json.loads(source.read_text(encoding="utf-8"))
    validation = validate_schedule_document(value, expected_season=expected_season)
    teams = tuple(sorted(str(item).upper() for item in value.get("teams") or ()))
    weeks = tuple(sorted(int(item) for item in value.get("weeks") or ()))
    byes = tuple(
        sorted((str(team).upper(), int(week)) for team, week in (value.get("bye_weeks") or {}).items())
    )
    return ScheduleConfig(
        season=int(value["season"]),
        weeks=weeks,
        teams=teams,
        bye_weeks=byes,
        source=str(value.get("source") or ""),
        source_url=str(value["source_url"]),
        verified_at=str(value.get("verified_at") or value["captured_at"]),
        payload_hash=str(value.get("payload_hash") or validation["payload_hash"]),
        endpoint=str(value["endpoint"]),
        captured_at=str(value["captured_at"]),
        response_hash=str(value["response_hash"]),
        license=str(value["license"]),
        use_restriction=str(value["use_restriction"]),
        games=tuple(value["games"]),
    )


def build_evaluation_weeks(
    *,
    current_week: int,
    championship_week: int | None,
    playoff_start_week: int | None,
    team_count: int,
    matchups: tuple[SleeperMatchupWeek, ...],
    schedule: ScheduleConfig,
) -> tuple[EvaluationWeek, ...]:
    if championship_week is None or championship_week < current_week:
        raise ScheduleIncomplete("League championship week is missing or before current week")
    required = tuple(range(current_week, championship_week + 1))
    if any(week not in schedule.weeks for week in required):
        raise ScheduleIncomplete("Audited NFL schedule does not cover the full evaluation horizon")
    matchup_by_week = {item.week: item for item in matchups}
    byes = dict(schedule.bye_weeks)
    result: list[EvaluationWeek] = []
    for week in required:
        matchup = matchup_by_week.get(week)
        complete_matchups = bool(
            matchup
            and matchup.team_rows == team_count
            and all(matchup_id is not None for _, matchup_id in matchup.roster_matchups)
        )
        result.append(
            EvaluationWeek(
                week=week,
                playoff=playoff_start_week is not None and week >= playoff_start_week,
                fantasy_matchup_rows=matchup.team_rows if matchup else 0,
                fantasy_matchups_complete=complete_matchups,
                bye_teams=tuple(sorted(team for team, bye in byes.items() if bye == week)),
                nfl_schedule_complete=True,
            )
        )
    return tuple(result)
