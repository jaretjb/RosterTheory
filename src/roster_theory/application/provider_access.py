"""Compose account-wide request accounting for direct FantasyPros commands."""

from __future__ import annotations

from pathlib import Path
from typing import Callable, TypeVar

from roster_theory.storage.request_gate import pace_request, reserve_requests


DEFAULT_BUDGET_PATH = Path("data/cache/trade/fantasypros/daily_budget.json")
_Client = TypeVar("_Client")


def charge_fantasypros_request(
    budget_path: str | Path = DEFAULT_BUDGET_PATH,
    *,
    minimum_spacing_seconds: float = 1.05,
) -> None:
    """Reserve durably, then pace the attempt; interruptions remain charged."""
    path = Path(budget_path)
    reserve_requests(path, 1)
    pace_request(path, minimum_spacing_seconds=minimum_spacing_seconds)


def charged_fantasypros_client(
    client_factory: Callable[..., _Client],
    budget_path: str | Path = DEFAULT_BUDGET_PATH,
    *,
    minimum_spacing_seconds: float = 1.05,
) -> _Client:
    """Charge every API attempt, including retries, from the shared ledger."""
    return client_factory(before_attempt=lambda: charge_fantasypros_request(
        budget_path, minimum_spacing_seconds=minimum_spacing_seconds,
    ))
