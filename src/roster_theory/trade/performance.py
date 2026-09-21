from __future__ import annotations

import math
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta
from typing import Sequence

from roster_theory.core.errors import CoverageIncomplete
from roster_theory.core.provenance import stable_hash
from roster_theory.trade.targets import TargetPerformanceContext


AVAILABILITY = frozenset({"PLAYED", "BYE", "INACTIVE", "PARTIAL", "UNKNOWN"})


@dataclass(frozen=True, slots=True)
class PregameExpectation:
    league_key: str
    season: int
    player_id: str
    week: int
    position: str
    captured_at: datetime
    projected_points: float | None
    projected_position_rank: float | None
    scoring_fingerprint: str
    source: str


@dataclass(frozen=True, slots=True)
class CompletedPerformanceOutcome:
    league_key: str
    season: int
    player_id: str
    week: int
    position: str
    game_started_at: datetime | None
    game_completed_at: datetime | None
    captured_at: datetime
    actual_points: float | None
    actual_position_rank: float | None
    availability: str
    scoring_fingerprint: str
    source: str


@dataclass(frozen=True, slots=True)
class PerformancePolicy:
    policy_id: str
    window_weeks: int
    prior_games: float
    minimum_games: int
    signal_threshold: float
    maximum_age_days: float
    point_scales: tuple[tuple[str, float], ...]
    rank_scales: tuple[tuple[str, float], ...]

    def __post_init__(self) -> None:
        if not self.policy_id.strip():
            raise ValueError("Performance policy_id is required")
        if (
            self.window_weeks <= 0 or self.minimum_games <= 0
            or self.minimum_games > self.window_weeks
        ):
            raise ValueError("Performance window and minimum games must be positive")
        if (
            any(not math.isfinite(value) for value in (
                self.prior_games, self.signal_threshold, self.maximum_age_days
            ))
            or self.prior_games < 0
            or self.signal_threshold <= 0
            or self.maximum_age_days <= 0
        ):
            raise ValueError("Performance shrinkage, signal, or freshness limit is invalid")
        for name, rows in (("point", self.point_scales), ("rank", self.rank_scales)):
            if not rows or len({position for position, _ in rows}) != len(rows):
                raise ValueError(f"{name} scales must have unique positions")
            if any(
                not position or position != position.upper()
                or not math.isfinite(scale) or scale <= 0
                for position, scale in rows
            ):
                raise ValueError(f"{name} scales must be finite and positive")


@dataclass(frozen=True, slots=True)
class PerformanceResidual:
    player_id: str
    week: int
    position: str
    expected_points: float | None
    actual_points: float | None
    point_residual: float | None
    expected_position_rank: float | None
    actual_position_rank: float | None
    rank_residual: float | None
    expectation_captured_at: datetime | None
    point_expectation_captured_at: datetime | None
    rank_expectation_captured_at: datetime | None
    game_started_at: datetime | None
    game_completed_at: datetime | None
    outcome_captured_at: datetime
    expectation_source: str | None
    point_expectation_source: str | None
    rank_expectation_source: str | None
    outcome_source: str
    availability: str
    included: bool
    exclusion_reason: str | None


@dataclass(frozen=True, slots=True)
class PerformanceEvidence:
    schema_version: int
    league_key: str
    season: int
    through_week: int
    as_of: datetime
    policy: PerformancePolicy
    residuals: tuple[PerformanceResidual, ...]
    contexts: tuple[TargetPerformanceContext, ...]
    warnings: tuple[str, ...]
    evidence_hash: str


def _aware(value: datetime | None, field: str) -> None:
    if value is not None and (value.tzinfo is None or value.utcoffset() is None):
        raise ValueError(f"{field} must include a timezone")


def _finite(value: float | None, field: str) -> None:
    if value is not None and not math.isfinite(value):
        raise ValueError(f"{field} must be finite")


def _validate_inputs(
    league_key: str,
    season: int,
    expectations: Sequence[PregameExpectation],
    outcomes: Sequence[CompletedPerformanceOutcome],
) -> None:
    seen_expectations: dict[tuple[str, int, datetime, str], PregameExpectation] = {}
    for row in expectations:
        if row.league_key != league_key or row.season != season:
            raise CoverageIncomplete("Pregame expectation belongs to another league or season")
        _aware(row.captured_at, "Expectation captured_at")
        _finite(row.projected_points, "Projected points")
        _finite(row.projected_position_rank, "Projected rank")
        if row.projected_position_rank is not None and row.projected_position_rank <= 0:
            raise ValueError("Projected rank must be positive")
        if (
            not row.player_id or row.week <= 0 or not row.position
            or not row.source or not row.scoring_fingerprint
        ):
            raise ValueError("Pregame expectation has incomplete identity or provenance")
        key = (row.player_id, row.week, row.captured_at, row.source)
        if key in seen_expectations and row != seen_expectations[key]:
            raise CoverageIncomplete("Conflicting pregame captures share identity and timestamp")
        seen_expectations[key] = row
    seen_outcomes: dict[tuple[str, int, datetime, str], CompletedPerformanceOutcome] = {}
    for row in outcomes:
        if row.league_key != league_key or row.season != season:
            raise CoverageIncomplete("Completed outcome belongs to another league or season")
        for field in ("game_started_at", "game_completed_at", "captured_at"):
            _aware(getattr(row, field), f"Outcome {field}")
        _finite(row.actual_points, "Actual points")
        _finite(row.actual_position_rank, "Actual rank")
        if row.actual_position_rank is not None and row.actual_position_rank <= 0:
            raise ValueError("Actual rank must be positive")
        if row.availability not in AVAILABILITY:
            raise ValueError(f"Unsupported availability: {row.availability}")
        if (
            not row.player_id or row.week <= 0 or not row.position
            or not row.source or not row.scoring_fingerprint
        ):
            raise ValueError("Completed outcome has incomplete identity or provenance")
        if (
            row.game_started_at is not None and row.game_completed_at is not None
            and row.game_completed_at < row.game_started_at
        ):
            raise ValueError("Game completion precedes its start")
        key = (row.player_id, row.week, row.captured_at, row.source)
        if key in seen_outcomes and row != seen_outcomes[key]:
            raise CoverageIncomplete("Conflicting completed outcomes share identity and timestamp")
        seen_outcomes[key] = row


def _latest_capture(
    rows: Sequence[PregameExpectation], metric: str
) -> PregameExpectation | None:
    if not rows:
        return None
    latest_at = max(row.captured_at for row in rows)
    latest = tuple(row for row in rows if row.captured_at == latest_at)
    if len({getattr(row, metric) for row in latest}) > 1:
        raise CoverageIncomplete(
            f"Ambiguous simultaneous pregame {metric} captures require a source choice"
        )
    return max(latest, key=lambda row: row.source)


def _residual(
    outcome: CompletedPerformanceOutcome,
    captures: Sequence[PregameExpectation],
    *,
    as_of: datetime,
    through_week: int,
    first_week: int,
    positions: set[str],
) -> PerformanceResidual:
    reason: str | None = None
    point_capture: PregameExpectation | None = None
    rank_capture: PregameExpectation | None = None
    if outcome.week > through_week:
        reason = "FUTURE_WEEK"
    elif outcome.week < first_week:
        reason = "OUTSIDE_WINDOW"
    elif outcome.captured_at > as_of:
        reason = "FUTURE_OUTCOME_CAPTURE"
    elif outcome.game_completed_at is None or outcome.game_completed_at > as_of:
        reason = "GAME_NOT_COMPLETE"
    elif outcome.captured_at < outcome.game_completed_at:
        reason = "OUTCOME_CAPTURED_BEFORE_GAME_END"
    elif outcome.availability != "PLAYED":
        reason = outcome.availability
    elif outcome.game_started_at is None:
        reason = "MISSING_GAME_START"
    elif outcome.position.upper() not in positions:
        reason = "UNSUPPORTED_POSITION"
    else:
        eligible = tuple(
            row for row in captures
            if row.captured_at < outcome.game_started_at and row.captured_at <= as_of
        )
        if not eligible:
            reason = "NO_PREGAME_CAPTURE" if not captures else "POSTGAME_OR_FUTURE_CAPTURE"
        else:
            same_position = tuple(
                row for row in eligible if row.position.upper() == outcome.position.upper()
            )
            same_scoring = tuple(
                row for row in same_position
                if row.scoring_fingerprint == outcome.scoring_fingerprint
            )
            if not same_position:
                reason = "POSITION_MISMATCH"
            elif not same_scoring:
                reason = "SCORING_MISMATCH"
            else:
                point_rows = tuple(
                    row for row in same_scoring
                    if row.projected_points is not None and outcome.actual_points is not None
                )
                rank_rows = tuple(
                    row for row in same_scoring
                    if row.projected_position_rank is not None
                    and outcome.actual_position_rank is not None
                )
                point_capture = _latest_capture(point_rows, "projected_points")
                rank_capture = _latest_capture(rank_rows, "projected_position_rank")
                if point_capture is None and rank_capture is None:
                    reason = "NO_COMPARABLE_METRIC"
    expectation = max(
        (row for row in (point_capture, rank_capture) if row is not None),
        key=lambda row: (row.captured_at, row.source), default=None,
    )
    point = (
        round(outcome.actual_points - point_capture.projected_points, 6)
        if reason is None and point_capture is not None
        and point_capture.projected_points is not None and outcome.actual_points is not None
        else None
    )
    rank = (
        round(rank_capture.projected_position_rank - outcome.actual_position_rank, 6)
        if reason is None and rank_capture is not None
        and rank_capture.projected_position_rank is not None
        and outcome.actual_position_rank is not None
        else None
    )
    future_or_incomplete = reason in {
        "FUTURE_WEEK", "FUTURE_OUTCOME_CAPTURE", "GAME_NOT_COMPLETE",
        "OUTCOME_CAPTURED_BEFORE_GAME_END",
    }
    return PerformanceResidual(
        player_id=outcome.player_id,
        week=outcome.week,
        position=outcome.position.upper(),
        expected_points=point_capture.projected_points if point_capture else None,
        actual_points=None if future_or_incomplete else outcome.actual_points,
        point_residual=point,
        expected_position_rank=rank_capture.projected_position_rank if rank_capture else None,
        actual_position_rank=(
            None if future_or_incomplete else outcome.actual_position_rank
        ),
        rank_residual=rank,
        expectation_captured_at=expectation.captured_at if expectation else None,
        point_expectation_captured_at=(
            point_capture.captured_at if point_capture else None
        ),
        rank_expectation_captured_at=(
            rank_capture.captured_at if rank_capture else None
        ),
        game_started_at=outcome.game_started_at,
        game_completed_at=None if future_or_incomplete else outcome.game_completed_at,
        outcome_captured_at=outcome.captured_at,
        expectation_source=expectation.source if expectation else None,
        point_expectation_source=point_capture.source if point_capture else None,
        rank_expectation_source=rank_capture.source if rank_capture else None,
        outcome_source=outcome.source,
        availability=outcome.availability,
        included=reason is None,
        exclusion_reason=reason,
    )


def _context(
    player_id: str,
    rows: Sequence[PerformanceResidual],
    *,
    as_of: datetime,
    policy: PerformancePolicy,
) -> TargetPerformanceContext:
    included = tuple(row for row in rows if row.included)
    points = tuple(row.point_residual for row in included if row.point_residual is not None)
    ranks = tuple(row.rank_residual for row in included if row.rank_residual is not None)
    point_shrink = len(points) / (len(points) + policy.prior_games) if points else 0.0
    rank_shrink = len(ranks) / (len(ranks) + policy.prior_games) if ranks else 0.0
    shrunk_points = round(sum(points) / len(points) * point_shrink, 6) if points else None
    shrunk_rank = round(sum(ranks) / len(ranks) * rank_shrink, 6) if ranks else None
    last_capture = max((row.outcome_captured_at for row in included), default=None)
    fresh = bool(last_capture and as_of - last_capture <= timedelta(days=policy.maximum_age_days))
    enough = len(included) >= policy.minimum_games
    mixed_positions = len({row.position for row in included}) > 1
    position = included[-1].position if included else rows[-1].position
    point_scale = dict(policy.point_scales).get(position)
    rank_scale = dict(policy.rank_scales).get(position)
    components = tuple(
        value for value in (
            shrunk_points / point_scale if shrunk_points is not None and point_scale else None,
            shrunk_rank / rank_scale if shrunk_rank is not None and rank_scale else None,
        ) if value is not None
    )
    score = sum(components) / len(components) if components else 0.0
    conflict = len(components) == 2 and components[0] * components[1] < 0.0
    signal = (
        "NEUTRAL" if conflict or mixed_positions or abs(score) < policy.signal_threshold
        else "OUTPERFORMING" if score > 0 else "UNDERPERFORMING"
    )
    warnings = []
    if not enough:
        warnings.append("Performance sample is too small to support a target signal")
    if not fresh:
        warnings.append("Performance context is stale or has no compatible recent outcome")
    if conflict:
        warnings.append("Point and rank surprises disagree; signal was neutralized")
    if mixed_positions:
        warnings.append("Multiple evaluation positions were observed; signal was neutralized")
    return TargetPerformanceContext(
        player_id=player_id,
        signal=signal,
        sample_size=len(included),
        as_of=as_of,
        compatible=enough and fresh and bool(components) and not mixed_positions,
        shrunk_point_residual=shrunk_points,
        shrunk_rank_residual=shrunk_rank,
        fresh=fresh,
        source=f"pregame-vs-completed:{policy.policy_id}",
        exclusions=tuple(
            f"W{row.week}:{row.exclusion_reason}" for row in rows if not row.included
        ),
        warnings=tuple(warnings),
    )


def build_performance_evidence(
    league_key: str,
    season: int,
    through_week: int,
    as_of: datetime,
    *,
    expectations: Sequence[PregameExpectation],
    outcomes: Sequence[CompletedPerformanceOutcome],
    policy: PerformancePolicy,
) -> PerformanceEvidence:
    """Join only information available at the historical decision timestamp."""

    _aware(as_of, "Decision as_of")
    if not league_key or season <= 0 or through_week <= 0:
        raise ValueError("Performance decision scope is incomplete")
    _validate_inputs(league_key, season, expectations, outcomes)
    captures_by_key: dict[tuple[str, int], list[PregameExpectation]] = {}
    for row in expectations:
        captures_by_key.setdefault((row.player_id, row.week), []).append(row)
    outcomes_by_key: dict[tuple[str, int], list[CompletedPerformanceOutcome]] = {}
    for row in outcomes:
        outcomes_by_key.setdefault((row.player_id, row.week), []).append(row)
    first_week = max(1, through_week - policy.window_weeks + 1)
    positions = set(dict(policy.point_scales)) | set(dict(policy.rank_scales))
    residuals = []
    for key in sorted(outcomes_by_key):
        available = [row for row in outcomes_by_key[key] if row.captured_at <= as_of]
        source_rows = available if available else outcomes_by_key[key]
        outcome = max(source_rows, key=lambda row: (row.captured_at, row.source))
        residuals.append(_residual(
            outcome,
            captures_by_key.get(key, ()),
            as_of=as_of,
            through_week=through_week,
            first_week=first_week,
            positions=positions,
        ))
    by_player: dict[str, list[PerformanceResidual]] = {}
    for row in residuals:
        by_player.setdefault(row.player_id, []).append(row)
    contexts = tuple(
        _context(player_id, rows, as_of=as_of, policy=policy)
        for player_id, rows in sorted(by_player.items())
    )
    warnings = tuple(dict.fromkeys(
        f"{row.player_id} W{row.week}: {row.exclusion_reason}"
        for row in residuals if not row.included
    ))
    result = PerformanceEvidence(
        schema_version=1,
        league_key=league_key,
        season=season,
        through_week=through_week,
        as_of=as_of,
        policy=policy,
        residuals=tuple(residuals),
        contexts=contexts,
        warnings=warnings,
        evidence_hash="",
    )
    return replace(result, evidence_hash=stable_hash(asdict(result)))
