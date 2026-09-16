from __future__ import annotations

import csv
import json
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from roster_theory.expert_accuracy_history import (
    RECENCY_WEIGHTS,
    load_accuracy_history,
    recency_accuracy_scores,
)
from roster_theory.fantasypros import FantasyProsClient
from roster_theory.rankings import normalize_name


SKILL_POSITIONS = ("QB", "RB", "WR", "TE")
COHORT_SIZE = 5
EXPERT_PICKER_URLS = {
    "STD": "https://www.fantasypros.com/nfl/cheatsheets/top-players.php?week=draft",
    "HALF": "https://www.fantasypros.com/nfl/cheatsheets/top-half-ppr-players.php?week=draft",
}


def _consensus_params(position: str, scoring: str, **extra: Any) -> dict[str, Any]:
    """Build ranking parameters without confusing ALL Draft with OP."""
    params: dict[str, Any] = {"position": position, "scoring": scoring, **extra}
    if position == "ALL":
        params["type"] = "DRAFT"
    return params


@dataclass(frozen=True, slots=True)
class HistoricalExpert:
    name: str
    master_rank: int
    category_rank: int
    category: str
    accuracy_score: float
    years: int
    score_method: str = "coverage_adjusted_2021_2025"
    annual_ranks: tuple[tuple[int, int], ...] = ()


@dataclass(frozen=True, slots=True)
class SelectedExpert:
    historical: HistoricalExpert
    expert_id: int
    api_name: str
    last_updated: str
    cohort: int = 0
    cohort_weight: float = 0.0
    weight_multiplier: float = 1.0


@dataclass(frozen=True, slots=True)
class GroupedRankingExport:
    output_dir: Path
    request_count: int
    selected_counts: Mapping[str, int]
    ranking_counts: Mapping[str, int]
    issue_count: int


class _ExpertPickerParser(HTMLParser):
    """Read the expert IDs and names shown by FantasyPros' Pick Experts modal."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.experts: dict[int, dict[str, str]] = {}
        self._expert_id: int | None = None
        self._name_parts: list[str] = []
        self._capture_name = False
        self._updated_timestamp = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "tr":
            self._expert_id = None
            self._name_parts = []
            self._capture_name = False
            self._updated_timestamp = ""
        elif tag == "input" and attributes.get("name") == "expert[]":
            value = str(attributes.get("value") or "")
            if value.isdigit():
                self._expert_id = int(value)
        elif (
            tag == "a"
            and self._expert_id is not None
            and str(attributes.get("href") or "").startswith("/experts/")
        ):
            self._capture_name = True
        elif tag == "td" and self._expert_id is not None and attributes.get("data-sort"):
            self._updated_timestamp = str(attributes["data-sort"])

    def handle_data(self, data: str) -> None:
        if self._capture_name:
            self._name_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a":
            self._capture_name = False
        elif tag == "tr" and self._expert_id is not None:
            name = " ".join("".join(self._name_parts).split())
            if not name:
                return
            last_updated = ""
            if self._updated_timestamp.isdigit():
                last_updated = datetime.fromtimestamp(
                    int(self._updated_timestamp), tz=UTC
                ).isoformat()
            prior = self.experts.get(self._expert_id)
            current = {"name": name, "last_updated": last_updated}
            if prior is not None and prior != current:
                raise ValueError(
                    f"FantasyPros picker repeated expert ID {self._expert_id} with conflicting data"
                )
            self.experts[self._expert_id] = current


def parse_fantasypros_expert_picker(html: str) -> dict[int, dict[str, str]]:
    parser = _ExpertPickerParser()
    parser.feed(html)
    if not parser.experts:
        raise ValueError("FantasyPros Pick Experts page did not contain any selectable experts")
    return parser.experts


def load_fantasypros_expert_picker(
    scoring: str,
    *,
    timeout_seconds: float = 20.0,
) -> dict[int, dict[str, str]]:
    normalized_scoring = scoring.upper()
    try:
        url = EXPERT_PICKER_URLS[normalized_scoring]
    except KeyError as exc:
        raise ValueError(f"No FantasyPros expert-picker URL for scoring {scoring!r}") from exc
    request = Request(
        url,
        headers={"Accept": "text/html", "User-Agent": "RosterTheory/0.1"},
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            html = response.read().decode("utf-8", errors="replace")
    except (HTTPError, URLError, TimeoutError) as exc:
        raise RuntimeError(f"Unable to load FantasyPros Pick Experts page: {exc}") from exc
    return parse_fantasypros_expert_picker(html)


def coverage_factor(years: int) -> float:
    return 0.80 + 0.20 * min(5, max(0, years)) / 5


def load_historical_experts(
    path: str | Path,
    category: str,
) -> list[HistoricalExpert]:
    normalized_category = category.upper()
    with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))

    candidates: list[tuple[dict[str, str], float, int]] = []
    for row in rows:
        if normalized_category == "OVERALL":
            score_value = row.get("master_score")
            years_value = row.get("overall_years")
        else:
            percentile_value = row.get(f"{normalized_category}_percentile")
            years_value = row.get(f"{normalized_category}_years")
            if not percentile_value or not years_value:
                continue
            score_value = str(float(percentile_value) * coverage_factor(int(float(years_value))))
        if not score_value or not years_value or int(float(years_value)) < 2:
            continue
        candidates.append((row, float(score_value), int(float(years_value))))

    candidates.sort(key=lambda item: (-item[1], item[0]["expert_name"]))
    result: list[HistoricalExpert] = []
    for category_rank, (row, score, years) in enumerate(candidates, start=1):
        result.append(
            HistoricalExpert(
                name=row["expert_name"],
                master_rank=int(row["master_rank"]),
                category_rank=category_rank,
                category=normalized_category,
                accuracy_score=score,
                years=years,
            )
        )
    return result


def load_recency_historical_experts(
    master_path: str | Path,
    annual_path: str | Path,
) -> list[HistoricalExpert]:
    """Rank overall experts by the agreed recency score and eligibility gate."""
    master = load_historical_experts(master_path, "OVERALL")
    scores = recency_accuracy_scores(load_accuracy_history(annual_path))
    candidates: list[tuple[HistoricalExpert, Any]] = []
    for expert in master:
        score = scores.get(normalize_name(expert.name))
        if score is None or not score.eligible:
            continue
        candidates.append((expert, score))
    candidates.sort(key=lambda item: (-item[1].score, item[0].name))
    return [
        HistoricalExpert(
            name=expert.name,
            master_rank=expert.master_rank,
            category_rank=selection_rank,
            category="OVERALL",
            accuracy_score=score.score,
            years=score.years,
            score_method="recency_8_15_21_26_30",
            annual_ranks=score.annual_ranks,
        )
        for selection_rank, (expert, score) in enumerate(candidates, start=1)
    ]


def _available_experts(
    responses: Iterable[Mapping[str, Any]],
    *,
    require_all: bool = False,
) -> tuple[dict[int, dict[str, str]], list[dict[str, str]]]:
    response_list = list(responses)
    if not response_list:
        return {}, []
    id_sets = [set(map(int, response.get("expert_names", {}).keys())) for response in response_list]
    selected_ids = (
        set.intersection(*id_sets) if require_all and id_sets else set.union(*id_sets) if id_sets else set()
    )
    available: dict[int, dict[str, str]] = {}
    issues: list[dict[str, str]] = []
    for expert_id in selected_ids:
        observed_names: list[str] = []
        observed_updates: list[str] = []
        for response in response_list:
            names = response.get("expert_names", {})
            updates = response.get("expert_pub", {})
            name = str(names.get(str(expert_id), "")).strip()
            if name:
                observed_names.append(name)
            updated = str(updates.get(str(expert_id), "")).strip()
            if updated:
                observed_updates.append(updated)
        normalized_names = {normalize_name(name) for name in observed_names}
        if len(normalized_names) != 1:
            issues.append(
                {
                    "status": "ambiguous_api_identity",
                    "api_expert_id": str(expert_id),
                    "api_name": " | ".join(sorted(set(observed_names))),
                    "detail": "API returned different names for this expert across ranking tables",
                }
            )
            continue
        available[expert_id] = {
            "name": observed_names[0],
            "last_updated": max(observed_updates, default=""),
        }
    if require_all:
        return available, issues
    for response_index, response in enumerate(response_list, start=1):
        names = response.get("expert_names", {})
        missing_count = len(selected_ids - set(map(int, names.keys())))
        if missing_count:
            issues.append(
                {
                    "status": "position_availability_varies",
                    "api_expert_id": "",
                    "api_name": "",
                    "detail": f"Availability response {response_index} omits {missing_count} experts present in another table",
                }
            )
    return available, issues


def _scope_available_experts(
    category: str,
    picker_experts: Mapping[int, Mapping[str, str]] | None,
    availability_responses: Iterable[Mapping[str, Any]],
) -> tuple[dict[int, dict[str, str]], list[dict[str, str]]]:
    """Use the UI's one overall picker for skills, not default ECR contributors."""
    if category == "OVERALL":
        if picker_experts is None:
            raise ValueError("Overall skill rankings require the FantasyPros expert picker")
        return (
            {
                int(expert_id): {
                    "name": str(expert.get("name") or "").strip(),
                    "last_updated": str(expert.get("last_updated") or "").strip(),
                }
                for expert_id, expert in picker_experts.items()
                if str(expert.get("name") or "").strip()
            },
            [],
        )
    return _available_experts(availability_responses, require_all=True)


def select_available_experts(
    historical: Iterable[HistoricalExpert],
    available: Mapping[int, Mapping[str, str]],
    *,
    limit: int = 20,
) -> tuple[list[SelectedExpert], list[dict[str, str]]]:
    history_by_name: dict[str, list[HistoricalExpert]] = {}
    for expert in historical:
        history_by_name.setdefault(normalize_name(expert.name), []).append(expert)

    matched: dict[str, tuple[int, Mapping[str, str]]] = {}
    issues: list[dict[str, str]] = []
    for expert_id, api in available.items():
        api_name = str(api.get("name") or "").strip()
        key = normalize_name(api_name)
        candidates = history_by_name.get(key, [])
        if len(candidates) == 1:
            if key in matched:
                issues.append(
                    {
                        "status": "ambiguous_api_identity",
                        "api_expert_id": str(expert_id),
                        "api_name": api_name,
                        "detail": "More than one current API expert normalized to this historical name",
                    }
                )
            else:
                matched[key] = (expert_id, api)
        elif len(candidates) > 1:
            issues.append(
                {
                    "status": "ambiguous_historical_match",
                    "api_expert_id": str(expert_id),
                    "api_name": api_name,
                    "detail": "Multiple historical experts share this normalized name",
                }
            )

    selected: list[SelectedExpert] = []
    for expert in historical:
        match = matched.get(normalize_name(expert.name))
        if match is None:
            continue
        expert_id, api = match
        selected.append(
            SelectedExpert(
                historical=expert,
                expert_id=expert_id,
                api_name=str(api.get("name") or expert.name),
                last_updated=str(api.get("last_updated") or ""),
            )
        )
        if len(selected) == limit:
            break

    if len(selected) < limit:
        issues.append(
            {
                "status": "insufficient_available_experts",
                "api_expert_id": "",
                "api_name": "",
                "detail": f"Selected {len(selected)} of requested {limit} experts",
            }
        )
    selected_keys = {normalize_name(expert.historical.name) for expert in selected}
    for expert in list(historical)[:limit]:
        if normalize_name(expert.name) not in selected_keys:
            issues.append(
                {
                    "status": "historical_leader_unavailable",
                    "api_expert_id": "",
                    "api_name": expert.name,
                    "detail": f"Historical {expert.category} rank {expert.category_rank} is not currently available",
                }
            )
    return selected, issues


def load_expert_pool_overrides(
    path: str | Path | None,
) -> dict[str, dict[str, Any]]:
    """Load dated availability and anchor-weight decisions for skill pools."""

    if path is None:
        return {}
    source = Path(path)
    if not source.exists():
        raise FileNotFoundError(f"Expert-pool override file not found: {source}")
    result: dict[str, dict[str, Any]] = {}
    with source.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"scope", "expert_name", "action", "value", "reason"}
        if not required.issubset(reader.fieldnames or []):
            missing = sorted(required - set(reader.fieldnames or []))
            raise ValueError(
                "Expert-pool override file is missing columns: " + ", ".join(missing)
            )
        for row in reader:
            scope = str(row.get("scope") or "").strip()
            expert_name = str(row.get("expert_name") or "").strip()
            action = str(row.get("action") or "").strip().lower()
            if not scope or not expert_name or not action:
                continue
            scope_result = result.setdefault(
                scope,
                {
                    "excluded_experts": [],
                    "last_updated_overrides": [],
                    "anchor": None,
                },
            )
            if action == "exclude":
                scope_result["excluded_experts"].append(
                    {
                        "expert_name": expert_name,
                        "reason": str(row.get("reason") or "").strip(),
                    }
                )
            elif action == "anchor_equivalent":
                if scope_result["anchor"] is not None:
                    raise ValueError(f"More than one anchor expert configured for {scope}")
                try:
                    equivalent_weight = float(row.get("value") or 0)
                except ValueError as error:
                    raise ValueError(
                        f"Invalid anchor equivalent weight for {expert_name}: {row.get('value')}"
                    ) from error
                if equivalent_weight < 1.0:
                    raise ValueError("Anchor equivalent weight must be at least one")
                scope_result["anchor"] = {
                    "expert_name": expert_name,
                    "equivalent_weight": equivalent_weight,
                    "reason": str(row.get("reason") or "").strip(),
                }
            elif action == "last_updated_override":
                updated_at = str(row.get("value") or "").strip()
                try:
                    datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
                except ValueError as error:
                    raise ValueError(
                        f"Invalid last-updated override for {expert_name}: {updated_at}"
                    ) from error
                scope_result["last_updated_overrides"].append(
                    {
                        "expert_name": expert_name,
                        "last_updated": updated_at,
                        "reason": str(row.get("reason") or "").strip(),
                    }
                )
            else:
                raise ValueError(f"Unsupported expert-pool override action: {action}")
    return result


def filter_recent_experts(
    available: Mapping[int, Mapping[str, str]],
    max_age_days: int | None,
    *,
    as_of: datetime | None = None,
) -> tuple[dict[int, Mapping[str, str]], list[dict[str, str]]]:
    """Keep only experts with a provable picker update inside the age window."""

    if max_age_days is None:
        return dict(available), []
    if max_age_days < 0:
        raise ValueError("Maximum expert ranking age cannot be negative")
    current = as_of or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    cutoff = current.astimezone(UTC) - timedelta(days=max_age_days)
    retained: dict[int, Mapping[str, str]] = {}
    issues: list[dict[str, str]] = []
    for expert_id, expert in available.items():
        updated_text = str(expert.get("last_updated") or "").strip()
        try:
            updated_at = datetime.fromisoformat(
                updated_text.replace("Z", "+00:00")
            )
            if updated_at.tzinfo is None:
                updated_at = updated_at.replace(tzinfo=UTC)
        except ValueError:
            updated_at = None
        if updated_at is not None and updated_at.astimezone(UTC) >= cutoff:
            retained[expert_id] = expert
            continue
        issues.append(
            {
                "status": "stale_or_undated_skill_expert",
                "api_expert_id": str(expert_id),
                "api_name": str(expert.get("name") or ""),
                "detail": (
                    f"Last update {updated_text or 'unavailable'} is older than "
                    f"the {max_age_days}-day cutoff {cutoff.date().isoformat()}"
                ),
            }
        )
    return retained, issues


def assign_cohort_weights(
    experts: Iterable[SelectedExpert],
    cohort_size: int = COHORT_SIZE,
    *,
    anchor_expert_name: str | None = None,
    anchor_equivalent_weight: float = 1.0,
) -> list[SelectedExpert]:
    selected = list(experts)
    if not selected:
        return []
    if anchor_equivalent_weight < 1.0:
        raise ValueError("Anchor equivalent weight must be at least one")

    anchor_key = normalize_name(anchor_expert_name or "")
    anchor = next(
        (
            expert
            for expert in selected
            if anchor_key and normalize_name(expert.historical.name) == anchor_key
        ),
        None,
    )
    cohort_numbers: list[int]
    multipliers = [1.0] * len(selected)
    if anchor is not None:
        ordinary = [expert for expert in selected if expert is not anchor]
        selected = [anchor, *ordinary]
        cohort_numbers = [1] + [
            2 + index // cohort_size for index in range(len(ordinary))
        ]
        ordinary_mean_square = (
            sum(expert.historical.accuracy_score**2 for expert in ordinary)
            / len(ordinary)
            if ordinary
            else anchor.historical.accuracy_score**2
        )
        multipliers = [
            (
                anchor_equivalent_weight
                * ordinary_mean_square
                / (anchor.historical.accuracy_score**2)
            ),
            *([1.0] * len(ordinary)),
        ]
    else:
        cohort_numbers = [index // cohort_size + 1 for index in range(len(selected))]

    cohort_raw: dict[int, float] = {}
    for expert, cohort, multiplier in zip(selected, cohort_numbers, multipliers):
        cohort_raw[cohort] = cohort_raw.get(cohort, 0.0) + (
            expert.historical.accuracy_score**2 * multiplier
        )
    total = sum(cohort_raw.values())
    if total <= 0:
        raise ValueError("Historical expert scores did not produce usable cohort weights")
    return [
        SelectedExpert(
            historical=expert.historical,
            expert_id=expert.expert_id,
            api_name=expert.api_name,
            last_updated=expert.last_updated,
            cohort=cohort,
            cohort_weight=cohort_raw[cohort] / total,
            weight_multiplier=multiplier,
        )
        for expert, cohort, multiplier in zip(selected, cohort_numbers, multipliers)
    ]


class _RateLimitedCalls:
    def __init__(self, minimum_interval_seconds: float, progress: Callable[[str], None]) -> None:
        self.minimum_interval_seconds = minimum_interval_seconds
        self.progress = progress
        self.request_count = 0
        self._last_call = 0.0

    def call(self, label: str, function: Callable[[], dict[str, Any]]) -> dict[str, Any]:
        elapsed = time.monotonic() - self._last_call
        if self._last_call and elapsed < self.minimum_interval_seconds:
            time.sleep(self.minimum_interval_seconds - elapsed)
        response = function()
        self._last_call = time.monotonic()
        self.request_count += 1
        self.progress(f"FantasyPros request {self.request_count}: {label}")
        if response.get("tier") != "premium":
            raise ValueError(f"FantasyPros {label} did not return Premium-tier data")
        players = response.get("players")
        if isinstance(players, list) and response.get("limit") is not None:
            raise ValueError(f"FantasyPros {label} returned a limited response")
        return response


def _write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def export_grouped_rankings(
    client: FantasyProsClient,
    *,
    season: int = 2026,
    accuracy_path: str | Path = "data/manual/fantasypros/expert_accuracy_2021_2025.csv",
    annual_accuracy_path: str | Path = "data/manual/fantasypros/expert_accuracy_annual_2021_2025.csv",
    output_dir: str | Path = "data/exports/fantasypros_2026",
    expert_limit: int = 10,
    specialist_expert_limit: int = 20,
    cohort_size: int = COHORT_SIZE,
    ecr_shrinkage: float = 0.15,
    specialist_ecr_shrinkage: float = 0.25,
    expert_overrides_path: str | Path | None = "data/manual/fantasypros/expert_pool_overrides_2026.csv",
    max_skill_ranking_age_days: int | None = 14,
    minimum_interval_seconds: float = 1.05,
    progress: Callable[[str], None] = print,
    expert_picker_loader: Callable[[str], Mapping[int, Mapping[str, str]]] = (
        load_fantasypros_expert_picker
    ),
) -> GroupedRankingExport:
    if expert_limit < 1 or specialist_expert_limit < 1 or cohort_size < 1:
        raise ValueError("Expert limit and cohort size must be positive")
    if not 0 <= ecr_shrinkage <= 1 or not 0 <= specialist_ecr_shrinkage <= 1:
        raise ValueError("ECR shrinkage must be between zero and one")

    destination = Path(output_dir)
    calls = _RateLimitedCalls(minimum_interval_seconds, progress)
    issues: list[dict[str, str]] = []
    scope_specs = {
        "skills_standard": ("OVERALL", "STD", SKILL_POSITIONS),
        "skills_half_ppr": ("OVERALL", "HALF", SKILL_POSITIONS),
        "k": ("K", "STD", ("K",)),
        "dst": ("DST", "STD", ("DST",)),
    }
    base_responses: dict[tuple[str, str], dict[str, Any]] = {}
    pools: dict[str, list[SelectedExpert]] = {}
    pool_overrides = load_expert_pool_overrides(expert_overrides_path)
    skill_picker_experts = {
        scope: expert_picker_loader(scoring)
        for scope, (category, scoring, _) in scope_specs.items()
        if category == "OVERALL"
    }
    picker_counts = {
        scope: len(experts) for scope, experts in skill_picker_experts.items()
    }

    for scope, (category, scoring, positions) in scope_specs.items():
        availability_responses = []
        for position in positions:
            response_role = (
                "default ECR anchor" if category == "OVERALL" else "availability/ECR"
            )
            response = calls.call(
                f"{scope} {position} {response_role}",
                lambda position=position, scoring=scoring: client.consensus_rankings(
                    season, position=position, scoring=scoring, experts="show"
                ),
            )
            base_responses[(scope, position)] = response
            availability_responses.append(response)
        if category == "OVERALL":
            # FantasyPros only accepts the documented ALL position when the
            # draft ranking type is explicit. This is the selected experts'
            # cross-position cheat sheet; OP is a fantasy-points list and is
            # not suitable for one-QB draft ordering.
            base_responses[(scope, "ALL")] = calls.call(
                f"{scope} ALL draft ECR",
                lambda scoring=scoring: client.consensus_rankings(
                    season,
                    **_consensus_params("ALL", scoring, experts="show"),
                ),
            )
            picker_experts = skill_picker_experts[scope]
        else:
            picker_experts = None
        available, availability_issues = _scope_available_experts(
            category, picker_experts, availability_responses
        )
        scope_overrides = pool_overrides.get(scope, {})
        update_overrides = {
            normalize_name(str(row.get("expert_name") or "")): row
            for row in scope_overrides.get("last_updated_overrides", [])
        }
        updated_available: dict[int, Mapping[str, str]] = {}
        for expert_id, expert in available.items():
            override = update_overrides.get(
                normalize_name(str(expert.get("name") or ""))
            )
            if override is None:
                updated_available[expert_id] = expert
                continue
            updated_available[expert_id] = {
                **expert,
                "last_updated": str(override.get("last_updated") or ""),
            }
            issues.append(
                {
                    "scope": scope,
                    "status": "configured_last_updated_override",
                    "api_expert_id": str(expert_id),
                    "api_name": str(expert.get("name") or ""),
                    "detail": str(override.get("reason") or "Configured correction"),
                }
            )
        available = updated_available
        excluded = {
            normalize_name(str(row.get("expert_name") or "")): row
            for row in scope_overrides.get("excluded_experts", [])
        }
        retained_available: dict[int, Mapping[str, str]] = {}
        for expert_id, expert in available.items():
            exclusion = excluded.get(normalize_name(str(expert.get("name") or "")))
            if exclusion is None:
                retained_available[expert_id] = expert
                continue
            issues.append(
                {
                    "scope": scope,
                    "status": "configured_expert_exclusion",
                    "api_expert_id": str(expert_id),
                    "api_name": str(expert.get("name") or ""),
                    "detail": str(exclusion.get("reason") or "Configured exclusion"),
                }
            )
        available = retained_available
        if category == "OVERALL":
            available, freshness_issues = filter_recent_experts(
                available,
                max_skill_ranking_age_days,
            )
            for issue in freshness_issues:
                issues.append({"scope": scope, **issue})
        historical = (
            load_recency_historical_experts(accuracy_path, annual_accuracy_path)
            if category == "OVERALL"
            else load_historical_experts(accuracy_path, category)
        )
        scope_limit = expert_limit if category == "OVERALL" else specialist_expert_limit
        selected, selection_issues = select_available_experts(
            historical, available, limit=scope_limit
        )
        anchor = scope_overrides.get("anchor")
        anchor_name = str((anchor or {}).get("expert_name") or "") or None
        if anchor_name and not any(
            normalize_name(expert.historical.name) == normalize_name(anchor_name)
            for expert in selected
        ):
            issues.append(
                {
                    "scope": scope,
                    "status": "configured_anchor_unavailable",
                    "api_expert_id": "",
                    "api_name": anchor_name,
                    "detail": "Configured anchor was not selected; ordinary cohort weighting remains active",
                }
            )
        pools[scope] = assign_cohort_weights(
            selected,
            cohort_size,
            anchor_expert_name=anchor_name,
            anchor_equivalent_weight=float(
                (anchor or {}).get("equivalent_weight") or 1.0
            ),
        )
        for issue in (*availability_issues, *selection_issues):
            issues.append({"scope": scope, **issue})

    pool_rows: list[dict[str, Any]] = []
    for scope, experts in pools.items():
        cohort_member_counts: dict[int, int] = {}
        for expert in experts:
            cohort_member_counts[expert.cohort] = (
                cohort_member_counts.get(expert.cohort, 0) + 1
            )
        for selection_rank, expert in enumerate(experts, start=1):
            pool_rows.append(
                {
                    "scope": scope,
                    "selection_rank": selection_rank,
                    "expert_name": expert.historical.name,
                    "expert_id": expert.expert_id,
                    "historical_category": expert.historical.category,
                    "historical_category_rank": expert.historical.category_rank,
                    "historical_master_rank": expert.historical.master_rank,
                    "historical_score": f"{expert.historical.accuracy_score:.4f}",
                    "historical_years": expert.historical.years,
                    "score_method": expert.historical.score_method,
                    "annual_overall_ranks": " | ".join(
                        f"{year}:{rank}" for year, rank in expert.historical.annual_ranks
                    ),
                    "cohort": expert.cohort,
                    "cohort_weight": f"{expert.cohort_weight:.6f}",
                    "cohort_member_count": cohort_member_counts[expert.cohort],
                    "weight_multiplier": f"{expert.weight_multiplier:.6f}",
                    "effective_expert_weight": (
                        f"{expert.cohort_weight / cohort_member_counts[expert.cohort]:.6f}"
                    ),
                    "last_updated": expert.last_updated,
                }
            )
    _write_csv(
        destination / "expert_pools.csv",
        pool_rows,
        [
            "scope", "selection_rank", "expert_name", "expert_id", "historical_category",
            "historical_category_rank", "historical_master_rank", "historical_score",
            "historical_years", "score_method", "annual_overall_ranks", "cohort",
            "cohort_weight", "cohort_member_count", "weight_multiplier",
            "effective_expert_weight", "last_updated",
        ],
    )

    cohort_rows: list[dict[str, Any]] = []
    weighted_rows: list[dict[str, Any]] = []
    ranking_counts: dict[str, int] = {}
    for scope, (category, scoring, positions) in scope_specs.items():
        experts = pools[scope]
        cohorts: dict[int, list[SelectedExpert]] = {}
        for expert in experts:
            cohorts.setdefault(expert.cohort, []).append(expert)
        ranking_positions = (*positions, "ALL") if category == "OVERALL" else positions
        for position in ranking_positions:
            base = base_responses[(scope, position)]
            base_by_id = {
                str(player.get("player_id")): player
                for player in base.get("players", [])
                if player.get("player_id") is not None
            }
            player_cohorts: dict[str, list[tuple[float, float]]] = {}
            player_details: dict[str, dict[str, Any]] = {}
            cohort_responses: list[tuple[int, list[SelectedExpert], dict[str, Any], float]] = []
            for cohort_number, cohort in cohorts.items():
                filter_ids = [str(expert.expert_id) for expert in cohort]
                if len(filter_ids) == 1:
                    filter_ids.append(filter_ids[0])
                expert_filter = ":".join(filter_ids)
                response = calls.call(
                    f"{scope} {position} cohort {cohort_number}",
                    lambda position=position, scoring=scoring, expert_filter=expert_filter: (
                        client.consensus_rankings(
                            season,
                            **_consensus_params(
                                position,
                                scoring,
                                filters=expert_filter,
                                experts="show",
                            ),
                        )
                    ),
                )
                returned_ids = set(map(int, response.get("expert_names", {}).keys()))
                requested_ids = {expert.expert_id for expert in cohort}
                active_cohort = [
                    expert for expert in cohort if expert.expert_id in returned_ids
                ]
                returned_experts = int(response.get("total_experts") or 0)
                if len(active_cohort) < len(cohort):
                    issues.append(
                        {
                            "scope": scope,
                            "status": (
                                "selected_expert_rankings_unavailable"
                                if position == "ALL"
                                else "partial_cohort_availability"
                            ),
                            "api_expert_id": ":".join(
                                str(expert.expert_id) for expert in cohort
                            ),
                            "api_name": "",
                            "detail": (
                                f"{position} cohort {cohort_number} returned {len(active_cohort)} of "
                                f"{len(cohort)} experts selected from the FantasyPros picker"
                            ),
                        }
                    )
                if (
                    not returned_ids.issubset(requested_ids)
                    or returned_experts != len(returned_ids)
                ):
                    issues.append(
                        {
                            "scope": scope,
                            "status": "expert_filter_mismatch",
                            "api_expert_id": expert_filter,
                            "api_name": "",
                            "detail": (
                                f"{position} cohort {cohort_number} requested {len(cohort)} experts "
                                f"but FantasyPros used {returned_experts}"
                            ),
                        }
                    )
                if not active_cohort:
                    issues.append(
                        {
                            "scope": scope,
                            "status": "empty_cohort",
                            "api_expert_id": "",
                            "api_name": "",
                            "detail": f"{position} cohort {cohort_number} has no current rankings",
                        }
                    )
                    continue
                raw_weight = sum(
                    expert.historical.accuracy_score**2 * expert.weight_multiplier
                    for expert in active_cohort
                )
                cohort_responses.append((cohort_number, active_cohort, response, raw_weight))
            position_weight_total = sum(raw_weight for _, _, _, raw_weight in cohort_responses)
            if position_weight_total <= 0:
                issues.append(
                    {
                        "scope": scope,
                        "status": "empty_position_consensus",
                        "api_expert_id": "",
                        "api_name": "",
                        "detail": f"No selected cohort returned {position} rankings",
                    }
                )
                continue
            for cohort_number, cohort, response, raw_weight in cohort_responses:
                cohort_weight = raw_weight / position_weight_total
                cohort_names = " | ".join(
                    expert.historical.name for expert in cohort
                )
                returned_experts = int(response.get("total_experts") or 0)
                for player in response.get("players", []):
                    player_id = str(player.get("player_id") or "")
                    rank = player.get("rank_ecr")
                    if not player_id or rank in (None, ""):
                        continue
                    player_cohorts.setdefault(player_id, []).append((float(rank), cohort_weight))
                    player_details[player_id] = player
                    cohort_rows.append(
                        {
                            "scope": scope,
                            "scoring": scoring,
                            "position": position,
                            "cohort": cohort_number,
                            "cohort_weight": f"{cohort_weight:.6f}",
                            "expert_count": returned_experts,
                            "experts": cohort_names,
                            "fantasypros_id": player_id,
                            "player_name": player.get("player_name"),
                            "team": player.get("player_team_id"),
                            "cohort_consensus_rank": rank,
                        }
                    )
            position_results: list[dict[str, Any]] = []
            for player_id, observations in player_cohorts.items():
                used_weight = sum(weight for _, weight in observations)
                grouped_rank = sum(rank * weight for rank, weight in observations) / used_weight
                base_player = base_by_id.get(player_id, {})
                ecr = base_player.get("rank_ecr")
                active_ecr_shrinkage = (
                    ecr_shrinkage if category == "OVERALL" else specialist_ecr_shrinkage
                )
                final_rank = (
                    grouped_rank
                    if ecr in (None, "")
                    else (1 - active_ecr_shrinkage) * grouped_rank
                    + active_ecr_shrinkage * float(ecr)
                )
                details = player_details[player_id]
                position_results.append(
                    {
                        "scope": scope,
                        "scoring": scoring,
                        "position": position,
                        "fantasypros_id": player_id,
                        "player_name": details.get("player_name"),
                        "team": details.get("player_team_id"),
                        "weighted_cohort_rank": round(grouped_rank, 3),
                        "ecr": float(ecr) if ecr not in (None, "") else "",
                        "rank_score": round(final_rank, 3),
                        "cohorts_reporting": len(observations),
                        "cohort_weight_coverage": round(used_weight, 6),
                    }
                )
            position_results.sort(key=lambda row: (row["rank_score"], str(row["player_name"])))
            for position_rank, row in enumerate(position_results, start=1):
                row["weighted_position_rank"] = position_rank
            if position == "ALL":
                overall_by_id = {
                    row["fantasypros_id"]: row for row in position_results
                }
                for row in weighted_rows:
                    if row["scope"] != scope:
                        continue
                    overall = overall_by_id.get(row["fantasypros_id"])
                    row.update(
                        {
                            "weighted_overall_rank": (
                                overall.get("weighted_position_rank") if overall else ""
                            ),
                            "overall_weighted_cohort_rank": (
                                overall.get("weighted_cohort_rank") if overall else ""
                            ),
                            "overall_ecr": overall.get("ecr") if overall else "",
                            "overall_rank_score": (
                                overall.get("rank_score") if overall else ""
                            ),
                            "overall_cohorts_reporting": (
                                overall.get("cohorts_reporting") if overall else 0
                            ),
                            "overall_cohort_weight_coverage": (
                                overall.get("cohort_weight_coverage") if overall else 0
                            ),
                        }
                    )
            else:
                weighted_rows.extend(position_results)
        ranking_counts[scope] = sum(1 for row in weighted_rows if row["scope"] == scope)

    _write_csv(
        destination / "expert_cohort_rankings.csv",
        cohort_rows,
        [
            "scope", "scoring", "position", "cohort", "cohort_weight", "expert_count",
            "experts", "fantasypros_id", "player_name", "team", "cohort_consensus_rank",
        ],
    )
    _write_csv(
        destination / "weighted_rankings.csv",
        weighted_rows,
        [
            "scope", "scoring", "position", "weighted_position_rank", "fantasypros_id",
            "player_name", "team", "weighted_cohort_rank", "ecr", "rank_score",
            "cohorts_reporting", "cohort_weight_coverage", "weighted_overall_rank",
            "overall_weighted_cohort_rank", "overall_ecr", "overall_rank_score",
            "overall_cohorts_reporting", "overall_cohort_weight_coverage",
        ],
    )
    _write_csv(
        destination / "issues.csv",
        issues,
        ["scope", "status", "api_expert_id", "api_name", "detail"],
    )
    metadata = {
        "generated_at": datetime.now().astimezone().isoformat(),
        "season": season,
        "api_tier": "premium",
        "request_count": calls.request_count,
        "skill_expert_limit": expert_limit,
        "specialist_expert_limit": specialist_expert_limit,
        "cohort_size": cohort_size,
        "skill_ecr_shrinkage": ecr_shrinkage,
        "specialist_ecr_shrinkage": specialist_ecr_shrinkage,
        "maximum_skill_ranking_age_days": max_skill_ranking_age_days,
        "expert_overrides_path": str(expert_overrides_path or ""),
        "expert_pool_overrides": pool_overrides,
        "overall_selection": {
            "method": "field_normalized_recency_weighted_percentile",
            "annual_accuracy_path": str(annual_accuracy_path),
            "weights": {str(year): weight for year, weight in RECENCY_WEIGHTS.items()},
            "minimum_years": 2,
            "one_year_eligible": False,
            "two_year_gate": "consecutive seasons and top-10 overall in both",
            "coverage_factors": {"2": 0.88, "3": 0.92, "4": 0.96, "5": 1.0},
        },
        "expert_picker_counts": picker_counts,
        "expert_picker_urls": {
            scope: EXPERT_PICKER_URLS[scoring]
            for scope, (_, scoring, _) in scope_specs.items()
            if scope in picker_counts
        },
        "selected_counts": {scope: len(experts) for scope, experts in pools.items()},
        "ranking_counts": ranking_counts,
        "issue_count": len(issues),
        "complete": all(
            len(experts)
            == (expert_limit if scope.startswith("skills_") else specialist_expert_limit)
            for scope, experts in pools.items()
        )
        and not any(
            issue["status"]
            in {
                "insufficient_available_experts", "expert_filter_mismatch",
                "empty_cohort", "empty_position_consensus",
                "selected_expert_rankings_unavailable",
            }
            for issue in issues
        ),
    }
    (destination / "metadata.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True), encoding="utf-8"
    )
    return GroupedRankingExport(
        output_dir=destination,
        request_count=calls.request_count,
        selected_counts=metadata["selected_counts"],
        ranking_counts=ranking_counts,
        issue_count=len(issues),
    )
