"""Drop game-lock evidence for a new move, never a pre-kickoff pending claim.

Sleeper documents the pre-kickoff-claim exception separately:
https://support.sleeper.com/en/articles/3473234
Setting mappings were verified in Sleeper's published web client (September 2026).
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Sequence


@dataclass(frozen=True, slots=True)
class DropLegality:
    legal: bool | None
    reason: str
    kickoff_at: str | None = None


def sleeper_drop_rules(settings: Mapping[str, Any]) -> dict[str, bool | None]:
    """Do not coerce missing, string, or unrecognized platform settings to false."""
    def flag(key: str) -> bool | None:
        value = settings.get(key)
        return bool(value) if isinstance(value, (int, bool)) and value in (0, 1) else None

    return {"league_moves_locked": flag("disable_adds"),
            "prevent_started_bench_drop": flag("bench_lock")}


def _kickoff(game: Mapping[str, Any]) -> datetime | None:
    try:
        if game.get("kickoff_at"):
            value = datetime.fromisoformat(str(game["kickoff_at"]).replace("Z", "+00:00"))
            return value if value.tzinfo is not None else None
        if game.get("gametime_zone") != "US/Eastern":
            return None
        value = datetime.fromisoformat(f"{game['gameday']}T{game['gametime']}")
        # nflverse declares Eastern wall time. Modern US DST (2007 onward),
        # implemented explicitly because Windows need not have IANA tzdata.
        # Ambiguous/nonexistent transition-hour inputs remain unavailable.
        if value.year < 2007 or value.tzinfo is not None:
            return None
        march = datetime(value.year, 3, 1)
        november = datetime(value.year, 11, 1)
        start = march + timedelta(days=(6 - march.weekday()) % 7 + 7, hours=2)
        end = november + timedelta(days=(6 - november.weekday()) % 7, hours=2)
        if start <= value < start + timedelta(hours=1) or end - timedelta(hours=1) <= value < end:
            return None
        offset = -4 if start <= value < end else -5
        return value.replace(tzinfo=timezone(timedelta(hours=offset)))
    except (KeyError, TypeError, ValueError):
        return None


def assess_drop_legality(
    *, nfl_team: str | None, starter: bool | None, week: int,
    games: Sequence[Mapping[str, Any]], bye_week: int | None, now: datetime,
    prevent_started_bench_drop: bool | None = None,
    league_moves_locked: bool | None = None,
) -> DropLegality:
    if now.tzinfo is None:
        raise ValueError("Drop legality requires an aware evaluation timestamp")
    if league_moves_locked is True:
        return DropLegality(False, "LEAGUE_MOVES_LOCKED")
    if league_moves_locked is None:
        return DropLegality(None, "LEAGUE_MOVE_RULE_UNVERIFIED")
    matching = [game for game in games if str(game.get("week")) == str(week)
                and nfl_team and nfl_team in (game.get("away_team"), game.get("home_team"))]
    if bye_week == week and not matching:
        return DropLegality(True, "AUDITED_BYE_NO_GAME_LOCK")
    if len(matching) != 1 or bye_week == week:
        return DropLegality(None, "GAME_STATE_UNAVAILABLE_OR_CONFLICTING")
    if str(matching[0].get("status", "")).upper() in {"POSTPONED", "CANCELLED", "CANCELED", "SUSPENDED"}:
        return DropLegality(None, "GAME_STATE_UNAVAILABLE_OR_CONFLICTING")
    kickoff = _kickoff(matching[0])
    if kickoff is None:
        return DropLegality(None, "KICKOFF_UNAVAILABLE")
    stamp = kickoff.astimezone(timezone.utc).isoformat()
    if now < kickoff:
        return DropLegality(True, "BEFORE_KICKOFF", stamp)
    if starter is True:
        return DropLegality(False, "STARTER_GAME_STARTED", stamp)
    if starter is None or prevent_started_bench_drop is None:
        return DropLegality(None, "STARTED_GAME_RULE_OR_STARTER_STATUS_UNVERIFIED", stamp)
    return DropLegality(not prevent_started_bench_drop, "VERIFIED_STARTED_BENCH_RULE", stamp)
