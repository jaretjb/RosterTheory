from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping

from roster_theory.core.errors import SourceUnavailable
from roster_theory.providers.cache import DailyRequestBudget, cache_key


@dataclass(frozen=True, slots=True)
class PlannedCall:
    name: str
    provider: str
    endpoint: str
    parameters: tuple[tuple[str, Any], ...] = ()
    required: bool = True
    fresh_cache_hit: bool = False

    @property
    def key(self) -> str:
        return cache_key(self.endpoint, dict(self.parameters))


@dataclass(frozen=True, slots=True)
class CallPlan:
    calls: tuple[PlannedCall, ...]
    fantasypros_calls: int
    required_calls: int
    optional_calls: int
    cache_hits: int
    duplicate_calls_removed: int
    fantasypros_remaining_after_plan: int


def build_call_plan(
    calls: list[PlannedCall], budget: DailyRequestBudget
) -> CallPlan:
    unique: list[PlannedCall] = []
    seen: set[tuple[str, str]] = set()
    for call in calls:
        identity = (call.provider.lower(), call.key)
        if identity in seen:
            continue
        seen.add(identity)
        unique.append(call)
    paid = sum(
        call.provider.lower() == "fantasypros" and not call.fresh_cache_hit
        for call in unique
    )
    remaining = budget.limit - budget.used
    if paid > remaining:
        budget.reserve(paid)
    return CallPlan(
        calls=tuple(unique),
        fantasypros_calls=paid,
        required_calls=sum(call.required for call in unique),
        optional_calls=sum(not call.required for call in unique),
        cache_hits=sum(call.fresh_cache_hit for call in unique),
        duplicate_calls_removed=len(calls) - len(unique),
        fantasypros_remaining_after_plan=remaining - paid,
    )


def execute_call_plan(
    plan: CallPlan,
    fetchers: Mapping[str, Callable[[], Any]],
    budget: DailyRequestBudget,
) -> dict[str, Any]:
    if plan.fantasypros_calls:
        budget.reserve(plan.fantasypros_calls)
    results: dict[str, Any] = {}
    for call in plan.calls:
        if call.fresh_cache_hit:
            continue
        fetch = fetchers.get(call.name)
        if fetch is None:
            if call.required:
                raise SourceUnavailable(f"Missing required fetcher: {call.name}")
            continue
        try:
            results[call.name] = fetch()
        except Exception as exc:
            if call.required:
                raise SourceUnavailable(f"Required call failed: {call.name}") from exc
    return results
