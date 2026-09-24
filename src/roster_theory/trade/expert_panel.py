from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Protocol, Sequence

from roster_theory.core.errors import CoverageIncomplete


class CurrentExpertLike(Protocol):
    expert_id: str
    name: str
    source_name: str
    position_updates: tuple[tuple[str, str], ...]
    latest_weekly_accuracy: tuple[tuple[str, int], ...]
    prior_weekly_accuracy: tuple[tuple[str, int], ...]


class ValueInputsLike(Protocol):
    ros_rankings: tuple[Any, ...]
    current_experts: tuple[CurrentExpertLike, ...]


@dataclass(frozen=True, slots=True)
class TradeExpertPoolMember:
    expert_id: str
    expert_name: str
    source_name: str
    weight: float


@dataclass(frozen=True, slots=True)
class TradeExpertPoolResolution:
    members: tuple[TradeExpertPoolMember, ...]
    evidence: Mapping[str, Any]


SKILL_POSITIONS = ("QB", "RB", "WR", "TE")
PREFERRED_PANEL_SIZE = 3
MINIMUM_PANEL_SIZE = 2
MAXIMUM_UPDATE_AGE = timedelta(hours=48)
LATEST_ACCURACY_WEIGHT = 0.70
PRIOR_ACCURACY_WEIGHT = 0.30


def _parse_provider_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _all_accuracy_rank(rows: Sequence[tuple[str, int]]) -> int | None:
    return dict(rows).get("ALL")


def _accuracy_score(
    expert: CurrentExpertLike,
) -> tuple[float, int | None, int | None] | None:
    latest = _all_accuracy_rank(expert.latest_weekly_accuracy)
    prior = _all_accuracy_rank(expert.prior_weekly_accuracy)
    if latest is None and prior is None:
        return None
    if latest is None:
        return float(prior), latest, prior
    if prior is None:
        return float(latest), latest, prior
    return (
        round(LATEST_ACCURACY_WEIGHT * latest + PRIOR_ACCURACY_WEIGHT * prior, 6),
        latest,
        prior,
    )


def _contributor_positions(inputs: ValueInputsLike) -> dict[str, set[str]]:
    positions: dict[str, set[str]] = {}
    for dataset in inputs.ros_rankings:
        dataset_positions = {
            row.position
            for row in dataset.observations
            if row.position in SKILL_POSITIONS
        }
        for contributor_id in dataset.contributor_ids:
            positions.setdefault(str(contributor_id), set()).update(dataset_positions)
    return positions


def select_trade_ros_panel(
    inputs: ValueInputsLike,
    now: datetime,
    *,
    league_key: str,
    preferred_size: int = PREFERRED_PANEL_SIZE,
    minimum_size: int = MINIMUM_PANEL_SIZE,
    maximum_update_age: timedelta = MAXIMUM_UPDATE_AGE,
) -> TradeExpertPoolResolution:
    """Choose accurate, fresh experts who actually contributed current ROS ballots."""

    if now.tzinfo is None:
        raise ValueError("Trade ROS panel selection time must be timezone-aware")
    if preferred_size < minimum_size or minimum_size < 2:
        raise ValueError("Trade ROS panel requires at least two preferred experts")

    normalized_now = now.astimezone(timezone.utc)
    current_by_id = {expert.expert_id: expert for expert in inputs.current_experts}
    contributor_positions = _contributor_positions(inputs)
    required_positions = set(SKILL_POSITIONS)
    audit: list[dict[str, Any]] = []
    eligible: list[tuple[float, CurrentExpertLike, dict[str, Any]]] = []

    for expert_id in sorted(
        contributor_positions,
        key=lambda value: (int(value) if value.isdigit() else 10**12, value),
    ):
        covered_positions = contributor_positions[expert_id]
        expert = current_by_id.get(expert_id)
        row: dict[str, Any] = {
            "expert_id": expert_id,
            "expert_name": expert.name if expert else None,
            "source_name": expert.source_name if expert else None,
            "contributor_positions": sorted(covered_positions),
            "latest_weekly_accuracy_rank": None,
            "prior_weekly_accuracy_rank": None,
            "accuracy_score": None,
            "weight": None,
            "status": "excluded",
            "reason": "",
        }
        if covered_positions != required_positions:
            row["reason"] = "missing_ros_position_contribution"
        elif expert is None:
            row["reason"] = "missing_current_expert_directory_identity"
        else:
            score = _accuracy_score(expert)
            updates = dict(expert.position_updates)
            if score is None:
                row["reason"] = "missing_weekly_accuracy_evidence"
            elif (
                score[1] is not None
                and score[2] is not None
                and score[1] >= 100
                and score[2] >= 100
            ):
                row["reason"] = "poor_accuracy_both_seasons"
            elif any(position not in updates for position in SKILL_POSITIONS):
                row["reason"] = "missing_position_update"
            else:
                try:
                    ages = tuple(
                        normalized_now - _parse_provider_time(updates[position])
                        for position in SKILL_POSITIONS
                    )
                except ValueError:
                    row["reason"] = "invalid_position_update"
                else:
                    if any(age < timedelta(0) for age in ages):
                        row["reason"] = "future_position_update"
                    elif any(age > maximum_update_age for age in ages):
                        row["reason"] = "stale_position_update"
                    else:
                        accuracy, latest, prior = score
                        row.update(
                            {
                                "latest_weekly_accuracy_rank": latest,
                                "prior_weekly_accuracy_rank": prior,
                                "accuracy_score": accuracy,
                                "status": "eligible",
                                "reason": "eligible",
                            }
                        )
                        eligible.append((accuracy, expert, row))
        audit.append(row)

    selected = sorted(
        eligible,
        key=lambda item: (
            item[0],
            _all_accuracy_rank(item[1].latest_weekly_accuracy) or 10**9,
            _all_accuracy_rank(item[1].prior_weekly_accuracy) or 10**9,
            item[1].expert_id,
        ),
    )[:preferred_size]
    if len(selected) < minimum_size:
        reasons: dict[str, int] = {}
        for row in audit:
            reason = str(row["reason"])
            reasons[reason] = reasons.get(reason, 0) + 1
        summary = ", ".join(f"{key}={value}" for key, value in sorted(reasons.items()))
        raise CoverageIncomplete(
            f"Trade ROS panel found {len(selected)} eligible contributor(s); "
            f"at least {minimum_size} are required ({summary or 'no contributors'})"
        )

    weight = 1.0 / len(selected)
    selected_ids = {expert.expert_id for _, expert, _ in selected}
    members = tuple(
        TradeExpertPoolMember(
            expert_id=expert.expert_id,
            expert_name=expert.name,
            source_name=expert.source_name,
            weight=weight,
        )
        for _, expert, _ in selected
    )
    for row in audit:
        if row["expert_id"] in selected_ids:
            row["status"] = "selected"
            row["reason"] = "top_available_weekly_accuracy"
            row["weight"] = weight
        elif row["status"] == "eligible":
            row["status"] = "excluded"
            row["reason"] = "below_selection_cutoff"

    evidence: Mapping[str, Any] = {
        "schema_version": "roster-theory.trade-ros-panel/v1",
        "product": "TRADE ASSISTANT",
        "league_key": league_key,
        "selected_at": normalized_now.isoformat(),
        "status": "READY" if len(members) == preferred_size else "DEGRADED",
        "selection_method": "actual_ros_contributors_by_weighted_weekly_accuracy_rank",
        "preferred_size": preferred_size,
        "minimum_size": minimum_size,
        "maximum_update_age_hours": maximum_update_age.total_seconds() / 3600.0,
        "accuracy_weights": {
            "latest_weekly_accuracy": LATEST_ACCURACY_WEIGHT,
            "prior_weekly_accuracy": PRIOR_ACCURACY_WEIGHT,
        },
        "required_positions": list(SKILL_POSITIONS),
        "weighting_method": "equal_after_accuracy_selection",
        "members": [asdict(member) for member in members],
        "candidates": audit,
        "market_ecr_remains_independent": True,
        "sleeper_write_performed": False,
    }
    return TradeExpertPoolResolution(members=members, evidence=evidence)
