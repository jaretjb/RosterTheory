"""Trade-only execution controls; these never alter football decision policy."""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field, is_dataclass
from functools import wraps
from math import isfinite
from time import perf_counter
from typing import Callable, Iterator


class SearchDeadline(Exception):
    """An unfinished calculation must not be published as evaluated."""


@dataclass(frozen=True, slots=True)
class FinderExecutionPolicy:
    version: str = "trade-finder-execution-v1"
    league_seconds: float = 120.0
    opponent_seconds: float = 300.0
    max_ideas: int = 10
    repairs_per_counter: int = 3

    def __post_init__(self) -> None:
        if self.version != "trade-finder-execution-v1":
            raise ValueError("Unsupported Trade finder execution version")
        if any(not isfinite(v) or v <= 0 for v in (self.league_seconds, self.opponent_seconds)):
            raise ValueError("Trade search time budgets must be finite and positive")
        if not 1 <= self.max_ideas <= 10 or not 0 <= self.repairs_per_counter <= 3:
            raise ValueError("Trade finder allows 1-10 ideas and 0-3 one-edit repairs")


@dataclass
class SearchExecution:
    seconds: float
    binding: str
    clock: Callable[[], float] = perf_counter
    started: float = field(init=False)
    cache: dict = field(default_factory=dict)
    references: dict = field(default_factory=dict)
    hits: int = 0
    misses: int = 0

    def __post_init__(self) -> None:
        if not isfinite(self.seconds) or self.seconds <= 0:
            raise ValueError("--time-budget-seconds must be finite and positive")
        self.started = self.clock()

    @property
    def elapsed(self) -> float:
        return self.clock() - self.started

    def check(self) -> None:
        if self.elapsed >= self.seconds:
            raise SearchDeadline()

    def key(self, value):
        if isinstance(value, (set, frozenset)):
            return tuple(sorted(value))
        if isinstance(value, (tuple, list)):
            return tuple(self.key(v) for v in value)
        if isinstance(value, dict):
            return tuple(sorted((k, self.key(v)) for k, v in value.items()))
        if is_dataclass(value):
            # Immutable inputs live only in this bound run. Strong references
            # prevent ID reuse; different matrices/options cannot collide.
            self.references[id(value)] = value
            return (type(value), id(value))
        return value


_execution: ContextVar[SearchExecution | None] = ContextVar("trade_search_execution", default=None)


@contextmanager
def search_execution(execution: SearchExecution) -> Iterator[SearchExecution]:
    token = _execution.set(execution)
    try:
        yield execution
    finally:
        _execution.reset(token)


def checkpoint() -> None:
    execution = _execution.get()
    if execution is not None:
        execution.check()


def cached(function):
    """Reuse exact calculations only within one snapshot/policy-bound run."""
    @wraps(function)
    def wrapped(*args, **kwargs):
        execution = _execution.get()
        if execution is None:
            return function(*args, **kwargs)
        execution.check()
        key = (execution.binding, function, execution.key(args), execution.key(kwargs))
        if key in execution.cache:
            execution.hits += 1
            return execution.cache[key]
        result = function(*args, **kwargs)
        execution.check()
        execution.misses += 1
        execution.cache[key] = result
        return result
    return wrapped
