"""Convert explicitly zoned NFL schedule times without system tzdata."""
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping


def kickoff_time(game: Mapping[str, Any]) -> datetime | None:
    try:
        if game.get("kickoff_at"):
            value = datetime.fromisoformat(str(game["kickoff_at"]).replace("Z", "+00:00"))
            return value if value.tzinfo is not None else None
        if game.get("gametime_zone") != "US/Eastern":
            return None
        value = datetime.fromisoformat(f"{game['gameday']}T{game['gametime']}")
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
