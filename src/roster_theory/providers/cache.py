from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, TypeVar

from roster_theory.core.errors import RequestBudgetExceeded
from roster_theory.core.provenance import canonical_json, stable_hash


T = TypeVar("T")


def cache_key(endpoint: str, parameters: Mapping[str, Any] | None = None) -> str:
    return stable_hash({"endpoint": endpoint, "parameters": parameters or {}})


def atomic_write_json(path: str | Path, value: Any) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(
        dir=target.parent, prefix=f".{target.name}.", suffix=".tmp"
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(canonical_json(value))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()
    return target


def is_fresh(
    captured_at: datetime,
    maximum_age: timedelta,
    *,
    now: datetime | None = None,
) -> bool:
    current = now or datetime.now(timezone.utc)
    if captured_at.tzinfo is None or current.tzinfo is None:
        raise ValueError("Freshness timestamps must be timezone-aware")
    return timedelta(0) <= current - captured_at <= maximum_age


class RequestDeduplicator:
    def __init__(self) -> None:
        self._values: dict[str, Any] = {}

    def get_or_call(
        self,
        endpoint: str,
        parameters: Mapping[str, Any] | None,
        fetch: Callable[[], T],
    ) -> tuple[T, bool]:
        key = cache_key(endpoint, parameters)
        if key in self._values:
            return self._values[key], True
        value = fetch()
        self._values[key] = value
        return value, False


@dataclass(slots=True)
class DailyRequestBudget:
    limit: int = 500
    used: int = 0
    budget_date: date | None = None

    def _rollover(self, today: date) -> None:
        if self.budget_date != today:
            self.used = 0
            self.budget_date = today

    def reserve(self, count: int = 1, *, today: date | None = None) -> int:
        if count < 0:
            raise ValueError("Request count cannot be negative")
        current_date = today or datetime.now(timezone.utc).date()
        self._rollover(current_date)
        if self.used + count > self.limit:
            raise RequestBudgetExceeded(
                f"FantasyPros request plan needs {count} calls with "
                f"{self.limit - self.used} remaining"
            )
        self.used += count
        return self.limit - self.used

    def to_json(self) -> dict[str, Any]:
        return {
            "limit": self.limit,
            "used": self.used,
            "budget_date": self.budget_date.isoformat() if self.budget_date else None,
        }

    @classmethod
    def from_json(cls, value: Mapping[str, Any]) -> "DailyRequestBudget":
        raw_date = value.get("budget_date")
        return cls(
            limit=int(value.get("limit", 500)),
            used=int(value.get("used", 0)),
            budget_date=date.fromisoformat(str(raw_date)) if raw_date else None,
        )

