"""Conservative account-wide FantasyPros budget and request pacing."""

from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Iterator

from roster_theory.providers.cache import DailyRequestBudget, atomic_write_json


@contextmanager
def _process_lock(path: Path, *, timeout_seconds: float = 30.0) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        if handle.seek(0, os.SEEK_END) == 0:
            handle.write(b"\0")
            handle.flush()
        start = time.monotonic()
        while True:
            try:
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() - start >= timeout_seconds:
                    raise TimeoutError(f"Timed out waiting for provider ledger lock: {path}")
                time.sleep(0.05)
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def reserve_requests(path: Path, count: int, *, today: date | None = None) -> int:
    """Charge a complete planned batch before any paid request starts."""

    with _process_lock(path.with_suffix(".lock")):
        budget = (
            DailyRequestBudget.from_json(json.loads(path.read_text(encoding="utf-8")))
            if path.exists() else DailyRequestBudget()
        )
        remaining = budget.reserve(count, today=today)
        atomic_write_json(path, budget.to_json())
        return remaining


def pace_request(path: Path, *, minimum_spacing_seconds: float = 1.05) -> None:
    """Space starts across processes; a crashed request remains charged."""

    pacing_path = path.with_name("request_pacing.json")
    with _process_lock(path.with_suffix(".lock")):
        if pacing_path.exists():
            try:
                previous = datetime.fromisoformat(
                    str(json.loads(pacing_path.read_text(encoding="utf-8"))["started_at"])
                )
                elapsed = max(0.0, (datetime.now(timezone.utc) - previous).total_seconds())
                if elapsed < minimum_spacing_seconds:
                    time.sleep(minimum_spacing_seconds - elapsed)
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                raise ValueError(f"Provider pacing ledger is invalid: {pacing_path}") from exc
        atomic_write_json(pacing_path, {"started_at": datetime.now(timezone.utc).isoformat()})
