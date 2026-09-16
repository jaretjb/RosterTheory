from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from roster_theory.core.errors import CoverageIncomplete
from roster_theory.core.models import RankObservation
from roster_theory.core.provenance import stable_hash
from roster_theory.providers.cache import atomic_write_json
from roster_theory.providers.fantasypros import NewsRecord


EARLY_SEASON_DRAFT_ANCHOR = "EARLY_SEASON_DRAFT_ANCHOR"
LONG_TERM = "LONG_TERM"
CURRENT_SIGNAL = "CURRENT_SIGNAL"
ROS = "ROS"
STOP_REVIEW = "STOP_REVIEW"
MATERIAL_NEWS_CATEGORIES = frozenset(
    {"injury", "suspension", "transaction", "depth_chart", "depth-chart"}
)


def parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


@dataclass(frozen=True, slots=True)
class BallotExclusion:
    expert_id: str
    position: str
    player_id: str | None
    reason: str
    ballot_updated_at: str | None
    evidence_at: str | None = None


@dataclass(frozen=True, slots=True)
class BallotFreshnessResult:
    eligible: tuple[RankObservation, ...]
    exclusions: tuple[BallotExclusion, ...]

    @property
    def excluded_expert_positions(self) -> tuple[tuple[str, str], ...]:
        return tuple(
            sorted(
                {
                    (row.expert_id, row.position)
                    for row in self.exclusions
                    if row.player_id is None
                }
            )
        )


def filter_ros_ballots(
    ballots: Sequence[RankObservation],
    position_updates: Mapping[tuple[str, str], str],
    news: Sequence[NewsRecord] = (),
    *,
    now: datetime,
    maximum_age: timedelta = timedelta(days=14),
    material_categories: Iterable[str] = MATERIAL_NEWS_CATEGORIES,
) -> BallotFreshnessResult:
    """Apply freshness to contributor ballots, never to the response capture.

    An old or missing expert-position revision excludes that complete ballot.
    Material news excludes only affected player rows and leaves the conflict in
    the audit result. Provider IDs must be reconciled before mixing sources.
    """
    normalized_now = now.astimezone(timezone.utc)
    material = {str(item).casefold() for item in material_categories}
    parsed_news: dict[str, list[tuple[datetime, NewsRecord]]] = {}
    for item in news:
        if (
            item.player_id is None
            or item.published_at is None
            or str(item.category or "").casefold() not in material
        ):
            continue
        try:
            published = parse_utc(item.published_at)
        except ValueError:
            continue
        if published <= normalized_now:
            parsed_news.setdefault(item.player_id, []).append((published, item))

    eligible: list[RankObservation] = []
    exclusions: list[BallotExclusion] = []
    position_status: dict[tuple[str, str], tuple[datetime | None, str | None]] = {}
    for ballot in ballots:
        if ballot.horizon.upper() != ROS:
            raise ValueError("Ballot freshness applies only to ROS observations")
        expert_id = str(ballot.expert_id or "")
        if not expert_id:
            raise ValueError("Contributor ballots require an expert ID")
        key = (expert_id, ballot.position.upper())
        if key not in position_status:
            raw_update = position_updates.get(key)
            if raw_update is None:
                position_status[key] = (None, "missing_position_revision")
            else:
                try:
                    updated = parse_utc(raw_update)
                except ValueError:
                    position_status[key] = (None, "invalid_position_revision")
                else:
                    age = normalized_now - updated
                    if age < timedelta(0):
                        position_status[key] = (updated, "future_position_revision")
                    elif age > maximum_age:
                        position_status[key] = (updated, "stale_position_ballot")
                    else:
                        position_status[key] = (updated, None)

    for (expert_id, position), (updated, reason) in sorted(position_status.items()):
        if reason is not None:
            exclusions.append(
                BallotExclusion(
                    expert_id=expert_id,
                    position=position,
                    player_id=None,
                    reason=reason,
                    ballot_updated_at=updated.isoformat() if updated else None,
                )
            )

    for ballot in ballots:
        key = (str(ballot.expert_id), ballot.position.upper())
        updated, reason = position_status[key]
        if reason is not None:
            continue
        conflicts = [
            (published, item)
            for published, item in parsed_news.get(ballot.player_id, ())
            if updated is not None and published > updated
        ]
        if conflicts:
            published, _ = max(conflicts, key=lambda item: item[0])
            exclusions.append(
                BallotExclusion(
                    expert_id=key[0],
                    position=key[1],
                    player_id=ballot.player_id,
                    reason="material_news_after_ballot",
                    ballot_updated_at=updated.isoformat() if updated else None,
                    evidence_at=published.isoformat(),
                )
            )
            continue
        eligible.append(ballot)
    return BallotFreshnessResult(
        eligible=tuple(eligible),
        exclusions=tuple(
            sorted(
                exclusions,
                key=lambda row: (
                    row.expert_id,
                    row.position,
                    row.player_id or "",
                    row.reason,
                ),
            )
        ),
    )


@dataclass(frozen=True, slots=True)
class SeasonStageDecision:
    mode: str
    selected_source: str
    market_source: str
    usable: bool
    review_required: bool
    reasons: tuple[str, ...]


def choose_season_stage(
    current_week: int,
    *,
    selected_ros_fresh: bool = False,
    selected_ros_complete: bool = False,
    market_ros_fresh: bool = False,
    market_ros_complete: bool = False,
    failed_transition_extension_approved: bool = False,
) -> SeasonStageDecision:
    if current_week < 1:
        raise ValueError("current_week must be positive")
    if current_week == 1:
        return SeasonStageDecision(
            mode=EARLY_SEASON_DRAFT_ANCHOR,
            selected_source="final Draft selected board",
            market_source="final Draft market ECR",
            usable=True,
            review_required=False,
            reasons=("Draft anchor is mandatory during Week 1",),
        )
    gates = {
        "selected_ros_fresh": selected_ros_fresh,
        "selected_ros_complete": selected_ros_complete,
        "market_ros_fresh": market_ros_fresh,
        "market_ros_complete": market_ros_complete,
    }
    failures = tuple(name for name, passed in gates.items() if not passed)
    if not failures:
        return SeasonStageDecision(
            mode=ROS,
            selected_source="fresh selected-expert ROS",
            market_source="fresh complete market ROS ECR",
            usable=True,
            review_required=False,
            reasons=("Both ROS ownership boards passed the joint transition gate",),
        )
    if current_week == 2 or failed_transition_extension_approved:
        return SeasonStageDecision(
            mode=EARLY_SEASON_DRAFT_ANCHOR,
            selected_source="final Draft selected board",
            market_source="final Draft market ECR",
            usable=True,
            review_required=True,
            reasons=("ROS transition failed: " + ", ".join(failures),),
        )
    return SeasonStageDecision(
        mode=STOP_REVIEW,
        selected_source="none",
        market_source="none",
        usable=False,
        review_required=True,
        reasons=(
            "Draft-anchor extension beyond Week 2 requires explicit review",
            "ROS transition failed: " + ", ".join(failures),
        ),
    )


@dataclass(frozen=True, slots=True)
class LongTermPlayer:
    player_id: str
    position: str
    position_rank: int
    value: float
    source: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class WeeklyPlayerSignal:
    player_id: str
    position: str
    week: int
    position_rank: int | None
    projected_points: float | None
    matchup_adjustment: float
    source: str
    updated_at: str
    bye: bool = False
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class DualHorizonPlayer:
    player_id: str
    position: str
    long_term_rank: int
    long_term_value: float
    long_term_source: str
    long_term_updated_at: str
    current_week: int | None
    current_rank: int | None
    current_projected_points: float | None
    current_adjusted_points: float | None
    current_availability: str
    current_source: str | None
    current_updated_at: str | None
    warnings: tuple[str, ...]


def compose_horizon_views(
    long_term: Sequence[LongTermPlayer],
    current: Sequence[WeeklyPlayerSignal],
) -> tuple[DualHorizonPlayer, ...]:
    current_by_id = {row.player_id: row for row in current}
    if len(current_by_id) != len(current):
        raise CoverageIncomplete("CURRENT_SIGNAL contains duplicate players")
    result: list[DualHorizonPlayer] = []
    for owned in long_term:
        signal = current_by_id.get(owned.player_id)
        if signal is None:
            result.append(
                DualHorizonPlayer(
                    player_id=owned.player_id,
                    position=owned.position,
                    long_term_rank=owned.position_rank,
                    long_term_value=owned.value,
                    long_term_source=owned.source,
                    long_term_updated_at=owned.updated_at,
                    current_week=None,
                    current_rank=None,
                    current_projected_points=None,
                    current_adjusted_points=None,
                    current_availability="MISSING",
                    current_source=None,
                    current_updated_at=None,
                    warnings=("CURRENT_SIGNAL missing",),
                )
            )
            continue
        if signal.position != owned.position:
            raise CoverageIncomplete(
                f"Horizon positions differ for {owned.player_id}"
            )
        adjusted = (
            None
            if signal.projected_points is None
            else 0.0
            if signal.bye
            else max(0.0, signal.projected_points + signal.matchup_adjustment)
        )
        warnings = list(signal.warnings)
        if signal.bye:
            warnings.append("Bye affects current-week use, not long-term ownership value")
        result.append(
            DualHorizonPlayer(
                player_id=owned.player_id,
                position=owned.position,
                long_term_rank=owned.position_rank,
                long_term_value=owned.value,
                long_term_source=owned.source,
                long_term_updated_at=owned.updated_at,
                current_week=signal.week,
                current_rank=signal.position_rank,
                current_projected_points=signal.projected_points,
                current_adjusted_points=adjusted,
                current_availability="BYE" if signal.bye else "ACTIVE",
                current_source=signal.source,
                current_updated_at=signal.updated_at,
                warnings=tuple(warnings),
            )
        )
    return tuple(sorted(result, key=lambda row: (row.position, row.long_term_rank, row.player_id)))


def load_draft_anchor(
    path: str | Path,
    *,
    updated_at: str,
    scope: str = "skills_half_ppr",
) -> tuple[tuple[RankObservation, ...], tuple[RankObservation, ...]]:
    def optional_float(value: str | None) -> float | None:
        return float(value) if value not in (None, "") else None

    with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
        rows = tuple(row for row in csv.DictReader(handle) if row.get("scope") == scope)
    selected: list[RankObservation] = []
    market: list[RankObservation] = []
    for row in rows:
        sleeper_id = str(row.get("sleeper_id") or "").strip()
        fantasypros_id = str(row.get("fantasypros_id") or "").strip()
        player_id = sleeper_id or (f"fp:{fantasypros_id}" if fantasypros_id else "")
        position = str(row.get("position") or "").strip().upper()
        if (
            not player_id
            or position not in {"QB", "RB", "WR", "TE"}
            or row.get("weighted_position_rank") in (None, "")
            or row.get("ecr") in (None, "")
        ):
            continue
        selected.append(
            RankObservation(
                player_id=player_id,
                horizon=EARLY_SEASON_DRAFT_ANCHOR,
                board_source="final_draft_selected",
                expert_id=None,
                position=position,
                position_rank=float(row["weighted_position_rank"]),
                overall_rank=optional_float(row.get("weighted_overall_rank")),
                scoring=str(row.get("scoring") or "HALF"),
                updated_at=updated_at,
            )
        )
        market.append(
            RankObservation(
                player_id=player_id,
                horizon=EARLY_SEASON_DRAFT_ANCHOR,
                board_source="final_draft_market",
                expert_id=None,
                position=position,
                position_rank=float(row["ecr"]),
                overall_rank=optional_float(row.get("overall_ecr")),
                scoring=str(row.get("scoring") or "HALF"),
                updated_at=updated_at,
            )
        )
    if not selected or len(selected) != len(market):
        raise CoverageIncomplete("Final Draft anchor is empty or asymmetric")
    return tuple(selected), tuple(market)


@dataclass(frozen=True, slots=True)
class SnapshotDatum:
    kind: str
    player_id: str
    position: str
    value: float | str | None
    source: str
    published_at: str


def capture_prospective_snapshot(
    path: str | Path,
    *,
    season: int,
    week: int,
    cutoff: datetime,
    mode: str,
    data: Sequence[SnapshotDatum],
) -> Path:
    normalized_cutoff = cutoff.astimezone(timezone.utc)
    future = [row for row in data if parse_utc(row.published_at) > normalized_cutoff]
    if future:
        raise ValueError("Prospective snapshot contains information after its cutoff")
    ordered = tuple(
        sorted(data, key=lambda row: (row.kind, row.position, row.player_id, row.source))
    )
    payload = {
        "schema_version": 1,
        "product": "TRADE ASSISTANT",
        "purpose": "PROSPECTIVE_HORIZON_VALIDATION",
        "season": season,
        "week": week,
        "cutoff": normalized_cutoff.isoformat(),
        "mode": mode,
        "data": [asdict(row) for row in ordered],
    }
    payload["snapshot_hash"] = stable_hash(payload)
    return atomic_write_json(path, payload)
