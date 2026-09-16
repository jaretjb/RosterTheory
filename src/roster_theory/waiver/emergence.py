from __future__ import annotations

import json
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from roster_theory.core.provenance import stable_hash
from roster_theory.providers.cache import atomic_write_json


EMERGENCE_CLASSIFIER_VERSION = "wa-013-role-volume-v1"
CLASSIFICATIONS = frozenset(
    {
        "ROLE_EXPANSION",
        "SUPPORTED_TREND",
        "EFFICIENCY_ONLY",
        "INJURY_CONDITIONAL",
        "CONFLICTING",
        "UNKNOWN",
    }
)
IDENTITY_STATUSES = frozenset({"MATCHED", "UNMATCHED", "AMBIGUOUS"})
COVERAGE_STATUSES = frozenset({"COMPLETE", "PARTIAL", "UNAVAILABLE"})
GAME_STATUSES = frozenset({"PLAYED", "INACTIVE", "BYE", "INCOMPLETE"})
INJURY_CONTEXTS = frozenset(
    {"NONE", "INJURY_FILL_IN", "RETURN_PENDING", "UNKNOWN"}
)
ROLE_DURABILITIES = frozenset(
    {"DURABLE", "TEMPORARY", "UNCONFIRMED", "NONE"}
)


@dataclass(frozen=True, slots=True)
class UsageMeasure:
    """One named usage measure without substituting another measure for it."""

    numerator: float | None = None
    team_denominator: float | None = None
    reported_share: float | None = None

    def __post_init__(self) -> None:
        for name, value in (
            ("numerator", self.numerator),
            ("team_denominator", self.team_denominator),
            ("reported_share", self.reported_share),
        ):
            if value is not None and value < 0:
                raise ValueError(f"Usage {name} cannot be negative")
        if self.team_denominator == 0:
            raise ValueError("Usage team denominator must be positive")
        if self.reported_share is not None and self.reported_share > 1:
            raise ValueError("Usage reported share must be between zero and one")


@dataclass(frozen=True, slots=True)
class FantasyResultComponents:
    """Non-overlapping point components supplied under the league's scoring."""

    total_points: float
    opportunity_points: float
    touchdown_points: float
    long_play_points: float
    other_efficiency_points: float
    touchdowns: int = 0
    long_plays: int = 0

    def __post_init__(self) -> None:
        if self.touchdowns < 0 or self.long_plays < 0:
            raise ValueError("Fantasy result event counts cannot be negative")
        component_total = (
            self.opportunity_points
            + self.touchdown_points
            + self.long_play_points
            + self.other_efficiency_points
        )
        if abs(component_total - self.total_points) > 0.01:
            raise ValueError("Fantasy result components must sum to total points")


@dataclass(frozen=True, slots=True)
class GameUsageObservation:
    player_id: str
    player_name: str
    team: str
    position: str
    season: int
    week: int
    game_id: str
    source: str
    captured_at: datetime
    source_updated_at: datetime
    identity_status: str
    coverage_status: str
    game_status: str
    overtime: bool
    offensive_snap_share: UsageMeasure = UsageMeasure()
    route_participation: UsageMeasure = UsageMeasure()
    target_share: UsageMeasure = UsageMeasure()
    targets: UsageMeasure = UsageMeasure()
    carries: UsageMeasure = UsageMeasure()
    total_opportunities: UsageMeasure = UsageMeasure()
    goal_line_work: UsageMeasure = UsageMeasure()
    red_zone_work: UsageMeasure = UsageMeasure()
    two_minute_usage: UsageMeasure = UsageMeasure()
    designed_touches: UsageMeasure = UsageMeasure()
    fantasy_result: FantasyResultComponents | None = None
    teammate_injury_context: str = "UNKNOWN"
    role_durability: str = "UNCONFIRMED"
    role_news: str | None = None
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not all(
            (
                self.player_id.strip(),
                self.player_name.strip(),
                self.team.strip(),
                self.position.strip(),
                self.game_id.strip(),
                self.source.strip(),
            )
        ):
            raise ValueError("Usage observations require player, game, and source identity")
        if self.season <= 0 or self.week <= 0:
            raise ValueError("Usage observations require positive season and week")
        if self.captured_at.tzinfo is None or self.source_updated_at.tzinfo is None:
            raise ValueError("Usage observation timestamps must be timezone-aware")
        if self.identity_status not in IDENTITY_STATUSES:
            raise ValueError("Unsupported usage identity status")
        if self.coverage_status not in COVERAGE_STATUSES:
            raise ValueError("Unsupported usage coverage status")
        if self.game_status not in GAME_STATUSES:
            raise ValueError("Unsupported usage game status")
        if self.teammate_injury_context not in INJURY_CONTEXTS:
            raise ValueError("Unsupported teammate injury context")
        if self.role_durability not in ROLE_DURABILITIES:
            raise ValueError("Unsupported role durability")


@dataclass(frozen=True, slots=True)
class TrustedEditorialObservation:
    player_id: str
    player_name: str
    author: str
    source: str
    source_url: str | None
    artifact_id: str | None
    published_at: datetime
    captured_at: datetime
    identity_status: str
    explicit_labels: tuple[str, ...] = ()
    explicit_rank: int | None = None
    explicit_tier: str | None = None
    explicit_role_claim: str | None = None
    explicit_faab_min_percent: float | None = None
    explicit_faab_max_percent: float | None = None
    excerpt: str | None = None
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not all(
            (
                self.player_id.strip(),
                self.player_name.strip(),
                self.author.strip(),
                self.source.strip(),
            )
        ):
            raise ValueError("Editorial observations require player, author, and source")
        if not (self.source_url or self.artifact_id):
            raise ValueError("Editorial evidence requires a source URL or artifact ID")
        if self.published_at.tzinfo is None or self.captured_at.tzinfo is None:
            raise ValueError("Editorial timestamps must be timezone-aware")
        if self.identity_status not in IDENTITY_STATUSES:
            raise ValueError("Unsupported editorial identity status")
        if self.explicit_rank is not None and self.explicit_rank <= 0:
            raise ValueError("An explicit editorial rank must be positive")
        low = self.explicit_faab_min_percent
        high = self.explicit_faab_max_percent
        if low is not None and not 0 <= low <= 100:
            raise ValueError("Editorial FAAB minimum must be between zero and 100")
        if high is not None and not 0 <= high <= 100:
            raise ValueError("Editorial FAAB maximum must be between zero and 100")
        if low is not None and high is not None and low > high:
            raise ValueError("Editorial FAAB range is inverted")


@dataclass(frozen=True, slots=True)
class MetricComparison:
    metric: str
    basis: str
    latest: float | None
    rolling_average: float | None
    baseline_average: float | None
    rolling_sample_size: int
    baseline_sample_size: int
    delta_from_baseline: float | None


@dataclass(frozen=True, slots=True)
class PlayerEmergenceEvidence:
    player_id: str
    player_name: str
    team: str
    position: str
    identity_status: str
    coverage_status: str
    latest_week: int | None
    latest_game_id: str | None
    rolling_window_weeks: tuple[int, ...]
    baseline_weeks: tuple[int, ...]
    excluded_games: tuple[tuple[int, str], ...]
    observations: tuple[GameUsageObservation, ...]
    comparisons: tuple[MetricComparison, ...]
    triggering_result: FantasyResultComponents | None
    editorials: tuple[TrustedEditorialObservation, ...]
    classification: str
    affirmative_eligible: bool
    classification_reasons: tuple[str, ...]
    warnings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class EmergenceEvidence:
    schema_version: int
    classifier_version: str
    product: str
    league_key: str
    captured_at: datetime
    usage_maximum_age_hours: float
    editorial_maximum_age_hours: float
    players: tuple[PlayerEmergenceEvidence, ...]
    unmatched_player_ids: tuple[str, ...]
    ambiguous_player_ids: tuple[str, ...]
    complete: bool
    warnings: tuple[str, ...]
    evidence_hash: str


_MEASURE_SPECS = (
    ("offensive_snap_share", "SHARE"),
    ("route_participation", "SHARE"),
    ("target_share", "SHARE"),
    ("targets", "COUNT"),
    ("carries", "COUNT"),
    ("total_opportunities", "COUNT"),
    ("goal_line_work", "COUNT"),
    ("red_zone_work", "COUNT"),
    ("two_minute_usage", "COUNT"),
    ("designed_touches", "COUNT"),
)
_EXPANSION_DELTAS = {
    "offensive_snap_share": 0.15,
    "route_participation": 0.15,
    "target_share": 0.05,
    "targets": 3.0,
    "carries": 4.0,
    "total_opportunities": 5.0,
    "designed_touches": 3.0,
}


def _utc(value: datetime) -> datetime:
    return value.astimezone(timezone.utc)


def _measure_value(measure: UsageMeasure, basis: str) -> float | None:
    if basis == "COUNT":
        return float(measure.numerator) if measure.numerator is not None else None
    if measure.numerator is None or measure.team_denominator is None:
        return None
    computed = float(measure.numerator) / float(measure.team_denominator)
    return float(measure.reported_share) if measure.reported_share is not None else computed


def _share_problem(metric: str, measure: UsageMeasure) -> str | None:
    supplied = any(
        value is not None
        for value in (measure.numerator, measure.team_denominator, measure.reported_share)
    )
    if not supplied:
        return None
    if measure.numerator is None or measure.team_denominator is None:
        return f"{metric} is missing its player numerator or team denominator"
    computed = float(measure.numerator) / float(measure.team_denominator)
    if measure.reported_share is not None and abs(computed - measure.reported_share) > 0.02:
        return f"{metric} reported share conflicts with its numerator and denominator"
    return None


def _average(values: Sequence[float | None]) -> tuple[float | None, int]:
    present = tuple(value for value in values if value is not None)
    if not present:
        return None, 0
    return round(sum(present) / len(present), 6), len(present)


def _comparisons(
    latest: GameUsageObservation,
    rolling: Sequence[GameUsageObservation],
    baseline: Sequence[GameUsageObservation],
) -> tuple[MetricComparison, ...]:
    rows: list[MetricComparison] = []
    for metric, basis in _MEASURE_SPECS:
        latest_value = _measure_value(getattr(latest, metric), basis)
        rolling_value, rolling_n = _average(
            [_measure_value(getattr(row, metric), basis) for row in rolling]
        )
        baseline_value, baseline_n = _average(
            [_measure_value(getattr(row, metric), basis) for row in baseline]
        )
        delta = (
            round(rolling_value - baseline_value, 6)
            if rolling_value is not None and baseline_value is not None
            else None
        )
        rows.append(
            MetricComparison(
                metric=metric,
                basis=basis,
                latest=latest_value,
                rolling_average=rolling_value,
                baseline_average=baseline_value,
                rolling_sample_size=rolling_n,
                baseline_sample_size=baseline_n,
                delta_from_baseline=delta,
            )
        )
    return tuple(rows)


def _semantic_signature(observation: GameUsageObservation) -> dict[str, Any]:
    value = asdict(observation)
    for key in ("source", "captured_at", "source_updated_at", "warnings"):
        value.pop(key, None)
    return value


def _is_high_participation(observation: GameUsageObservation) -> bool:
    values = {
        metric: _measure_value(getattr(observation, metric), basis)
        for metric, basis in _MEASURE_SPECS
    }
    participation = (
        (values["offensive_snap_share"] or 0) >= 0.55
        or (values["route_participation"] or 0) >= 0.60
    )
    volume = (
        (values["target_share"] or 0) >= 0.15
        or (values["targets"] or 0) >= 6
        or (values["carries"] or 0) >= 8
        or (values["total_opportunities"] or 0) >= 10
        or (values["designed_touches"] or 0) >= 6
    )
    return participation and volume


def _has_expansion(comparisons: Sequence[MetricComparison]) -> bool:
    return any(
        row.metric in _EXPANSION_DELTAS
        and row.delta_from_baseline is not None
        and row.delta_from_baseline >= _EXPANSION_DELTAS[row.metric]
        for row in comparisons
    )


def _variance_driven(result: FantasyResultComponents | None) -> bool:
    if result is None:
        return False
    variance_points = result.touchdown_points + result.long_play_points
    share = variance_points / result.total_points if result.total_points > 0 else 0.0
    return result.touchdowns >= 2 or result.long_plays >= 1 or share >= 0.40


def _observation_from_json(value: Mapping[str, Any]) -> GameUsageObservation:
    def measure(name: str) -> UsageMeasure:
        raw = value.get(name) or {}
        return UsageMeasure(
            numerator=float(raw["numerator"]) if raw.get("numerator") is not None else None,
            team_denominator=(
                float(raw["team_denominator"])
                if raw.get("team_denominator") is not None
                else None
            ),
            reported_share=(
                float(raw["reported_share"])
                if raw.get("reported_share") is not None
                else None
            ),
        )

    result_raw = value.get("fantasy_result")
    result = (
        FantasyResultComponents(
            total_points=float(result_raw["total_points"]),
            opportunity_points=float(result_raw["opportunity_points"]),
            touchdown_points=float(result_raw["touchdown_points"]),
            long_play_points=float(result_raw["long_play_points"]),
            other_efficiency_points=float(result_raw["other_efficiency_points"]),
            touchdowns=int(result_raw.get("touchdowns") or 0),
            long_plays=int(result_raw.get("long_plays") or 0),
        )
        if result_raw is not None
        else None
    )
    return GameUsageObservation(
        player_id=str(value["player_id"]),
        player_name=str(value["player_name"]),
        team=str(value["team"]),
        position=str(value["position"]),
        season=int(value["season"]),
        week=int(value["week"]),
        game_id=str(value["game_id"]),
        source=str(value["source"]),
        captured_at=datetime.fromisoformat(str(value["captured_at"])),
        source_updated_at=datetime.fromisoformat(str(value["source_updated_at"])),
        identity_status=str(value["identity_status"]),
        coverage_status=str(value["coverage_status"]),
        game_status=str(value["game_status"]),
        overtime=bool(value.get("overtime")),
        offensive_snap_share=measure("offensive_snap_share"),
        route_participation=measure("route_participation"),
        target_share=measure("target_share"),
        targets=measure("targets"),
        carries=measure("carries"),
        total_opportunities=measure("total_opportunities"),
        goal_line_work=measure("goal_line_work"),
        red_zone_work=measure("red_zone_work"),
        two_minute_usage=measure("two_minute_usage"),
        designed_touches=measure("designed_touches"),
        fantasy_result=result,
        teammate_injury_context=str(value.get("teammate_injury_context") or "UNKNOWN"),
        role_durability=str(value.get("role_durability") or "UNCONFIRMED"),
        role_news=str(value["role_news"]) if value.get("role_news") is not None else None,
        warnings=tuple(str(item) for item in value.get("warnings") or ()),
    )


def _editorial_from_json(value: Mapping[str, Any]) -> TrustedEditorialObservation:
    return TrustedEditorialObservation(
        player_id=str(value["player_id"]),
        player_name=str(value["player_name"]),
        author=str(value["author"]),
        source=str(value["source"]),
        source_url=str(value["source_url"]) if value.get("source_url") else None,
        artifact_id=str(value["artifact_id"]) if value.get("artifact_id") else None,
        published_at=datetime.fromisoformat(str(value["published_at"])),
        captured_at=datetime.fromisoformat(str(value["captured_at"])),
        identity_status=str(value["identity_status"]),
        explicit_labels=tuple(str(item) for item in value.get("explicit_labels") or ()),
        explicit_rank=int(value["explicit_rank"]) if value.get("explicit_rank") is not None else None,
        explicit_tier=str(value["explicit_tier"]) if value.get("explicit_tier") is not None else None,
        explicit_role_claim=(
            str(value["explicit_role_claim"])
            if value.get("explicit_role_claim") is not None
            else None
        ),
        explicit_faab_min_percent=(
            float(value["explicit_faab_min_percent"])
            if value.get("explicit_faab_min_percent") is not None
            else None
        ),
        explicit_faab_max_percent=(
            float(value["explicit_faab_max_percent"])
            if value.get("explicit_faab_max_percent") is not None
            else None
        ),
        excerpt=str(value["excerpt"]) if value.get("excerpt") is not None else None,
        warnings=tuple(str(item) for item in value.get("warnings") or ()),
    )


def _player_evidence(
    *,
    player_id: str,
    observations: Sequence[GameUsageObservation],
    editorials: Sequence[TrustedEditorialObservation],
    now: datetime,
    usage_maximum_age_hours: float,
    editorial_maximum_age_hours: float,
) -> PlayerEmergenceEvidence:
    ordered = tuple(
        sorted(observations, key=lambda row: (row.season, row.week, row.game_id, row.source))
    )
    ordered_editorials = tuple(
        sorted(
            editorials,
            key=lambda row: (
                row.published_at,
                row.author.casefold(),
                row.source,
                row.source_url or "",
                row.artifact_id or "",
            ),
        )
    )
    representative = ordered[-1] if ordered else None
    player_name = representative.player_name if representative else ordered_editorials[-1].player_name
    team = representative.team if representative else "UNKNOWN"
    position = representative.position if representative else "UNKNOWN"
    identity_values = {
        row.identity_status for row in (*ordered, *ordered_editorials)
    }
    identity_status = (
        "AMBIGUOUS"
        if "AMBIGUOUS" in identity_values
        else "UNMATCHED"
        if "UNMATCHED" in identity_values or not identity_values
        else "MATCHED"
    )
    warnings = [warning for row in ordered for warning in row.warnings]
    warnings.extend(warning for row in ordered_editorials for warning in row.warnings)
    reasons: list[str] = []
    blocking: list[str] = []

    if len({(row.player_name, row.team, row.position) for row in ordered}) > 1:
        blocking.append("Player name, team, or position conflicts across usage sources")

    by_game: dict[tuple[int, int, str], list[GameUsageObservation]] = {}
    for row in ordered:
        by_game.setdefault((row.season, row.week, row.game_id), []).append(row)
    conflicts = tuple(
        key
        for key, rows in sorted(by_game.items())
        if len({stable_hash(_semantic_signature(row)) for row in rows}) > 1
    )
    if conflicts:
        blocking.append(
            "Usage sources conflict for "
            + ", ".join(f"{season}-W{week}-{game}" for season, week, game in conflicts)
        )

    canonical = tuple(rows[0] for _, rows in sorted(by_game.items()))
    played = tuple(row for row in canonical if row.game_status == "PLAYED")
    excluded = tuple(
        (row.week, row.game_status) for row in canonical if row.game_status != "PLAYED"
    )
    latest_calendar = canonical[-1] if canonical else None
    latest = played[-1] if played else None
    if latest is None:
        blocking.append("No completed played game is available")
    elif latest_calendar is not latest:
        blocking.append(
            f"Latest game status is {latest_calendar.game_status}, not a completed played game"
        )

    rolling = played[-2:]
    baseline = played[:-2]
    comparisons = _comparisons(latest, rolling, baseline) if latest else ()

    if identity_status != "MATCHED":
        blocking.append(f"Player identity is {identity_status}")
    latest_source_rows = (
        tuple(by_game[(latest.season, latest.week, latest.game_id)]) if latest else ()
    )
    for source_row in latest_source_rows:
        if source_row.coverage_status != "COMPLETE":
            blocking.append(
                f"Latest usage coverage from {source_row.source} is "
                f"{source_row.coverage_status}"
            )
        if now - _utc(source_row.source_updated_at) > timedelta(
            hours=usage_maximum_age_hours
        ):
            blocking.append(
                f"Latest role and usage evidence from {source_row.source} is stale"
            )
    for editorial in ordered_editorials:
        if now - _utc(editorial.published_at) > timedelta(hours=editorial_maximum_age_hours):
            blocking.append(
                f"Trusted editorial evidence from {editorial.author} is stale"
            )
        if editorial.identity_status != "MATCHED":
            blocking.append(
                f"Trusted editorial identity from {editorial.author} is {editorial.identity_status}"
            )
    if latest:
        for source_row in latest_source_rows:
            for metric, basis in _MEASURE_SPECS:
                if basis == "SHARE":
                    problem = _share_problem(metric, getattr(source_row, metric))
                    if problem:
                        blocking.append(f"{source_row.source}: {problem}")
        if latest.fantasy_result is None:
            blocking.append("Triggering fantasy-result decomposition is unavailable")
        if latest.teammate_injury_context == "UNKNOWN":
            blocking.append("Current teammate-injury context is unknown")
        if latest.role_durability == "UNCONFIRMED":
            blocking.append("Current depth-chart or coaching role is unconfirmed")
        if latest.overtime:
            warnings.append("Latest game included overtime; raw counts may be inflated")

    classification = "UNKNOWN"
    high_latest = bool(latest and _is_high_participation(latest))
    expansion = _has_expansion(comparisons)
    supported = (
        len(rolling) >= 2
        and bool(baseline)
        and all(_is_high_participation(row) for row in rolling)
        and expansion
    )
    injury_conditional = bool(
        latest
        and (
            latest.teammate_injury_context in {"INJURY_FILL_IN", "RETURN_PENDING"}
            or latest.role_durability == "TEMPORARY"
        )
    )
    if conflicts:
        classification = "CONFLICTING"
        reasons.append("Equivalent game keys contain materially different source observations")
    elif blocking:
        reasons.extend(blocking)
    elif injury_conditional:
        classification = "INJURY_CONDITIONAL"
        reasons.append("The observed workload is explicitly tied to a teammate absence or temporary role")
    elif supported:
        classification = "SUPPORTED_TREND"
        reasons.append("At least two high-participation games sustain an increase over the earlier baseline")
    elif high_latest and expansion:
        classification = "ROLE_EXPANSION"
        reasons.append("The latest high-participation game materially exceeds the earlier baseline")
    elif latest and _variance_driven(latest.fantasy_result) and not high_latest:
        classification = "EFFICIENCY_ONLY"
        reasons.append("Touchdown or long-play production drove the result without high participation and volume")
    else:
        reasons.append("The available observations do not prove role expansion or an efficiency-only spike")

    warnings.extend(blocking)
    unavailable = tuple(
        row.metric for row in comparisons if row.latest is None
    )
    if unavailable:
        warnings.append("Latest metrics unavailable: " + ", ".join(unavailable))
    coverage_status = (
        "UNAVAILABLE"
        if not ordered
        else "PARTIAL"
        if blocking or any(row.coverage_status != "COMPLETE" for row in ordered)
        else "COMPLETE"
    )
    affirmative = classification in {"ROLE_EXPANSION", "SUPPORTED_TREND"}
    return PlayerEmergenceEvidence(
        player_id=player_id,
        player_name=player_name,
        team=team,
        position=position,
        identity_status=identity_status,
        coverage_status=coverage_status,
        latest_week=latest.week if latest else None,
        latest_game_id=latest.game_id if latest else None,
        rolling_window_weeks=tuple(row.week for row in rolling),
        baseline_weeks=tuple(row.week for row in baseline),
        excluded_games=excluded,
        observations=ordered,
        comparisons=comparisons,
        triggering_result=latest.fantasy_result if latest else None,
        editorials=ordered_editorials,
        classification=classification,
        affirmative_eligible=affirmative,
        classification_reasons=tuple(sorted(set(reasons))),
        warnings=tuple(sorted(set(warnings))),
    )


def build_emergence_evidence(
    *,
    league_key: str,
    observations: Sequence[GameUsageObservation],
    editorials: Sequence[TrustedEditorialObservation] = (),
    captured_at: datetime,
    usage_maximum_age_hours: float = 48.0,
    editorial_maximum_age_hours: float = 72.0,
) -> EmergenceEvidence:
    if not league_key.strip():
        raise ValueError("Emergence evidence requires a league key")
    if captured_at.tzinfo is None:
        raise ValueError("Emergence evidence timestamp must be timezone-aware")
    if usage_maximum_age_hours <= 0 or editorial_maximum_age_hours <= 0:
        raise ValueError("Emergence evidence freshness windows must be positive")
    now = _utc(captured_at)
    player_ids = tuple(
        sorted({row.player_id for row in observations} | {row.player_id for row in editorials})
    )
    players = tuple(
        _player_evidence(
            player_id=player_id,
            observations=tuple(row for row in observations if row.player_id == player_id),
            editorials=tuple(row for row in editorials if row.player_id == player_id),
            now=now,
            usage_maximum_age_hours=usage_maximum_age_hours,
            editorial_maximum_age_hours=editorial_maximum_age_hours,
        )
        for player_id in player_ids
    )
    unmatched = tuple(row.player_id for row in players if row.identity_status == "UNMATCHED")
    ambiguous = tuple(row.player_id for row in players if row.identity_status == "AMBIGUOUS")
    warnings = tuple(
        sorted(
            {
                f"{row.player_id}: {warning}"
                for row in players
                for warning in row.warnings
            }
        )
    )
    base = EmergenceEvidence(
        schema_version=1,
        classifier_version=EMERGENCE_CLASSIFIER_VERSION,
        product="WAIVER ASSISTANT",
        league_key=league_key,
        captured_at=now,
        usage_maximum_age_hours=float(usage_maximum_age_hours),
        editorial_maximum_age_hours=float(editorial_maximum_age_hours),
        players=players,
        unmatched_player_ids=unmatched,
        ambiguous_player_ids=ambiguous,
        complete=bool(players)
        and all(row.coverage_status == "COMPLETE" for row in players),
        warnings=warnings,
        evidence_hash="",
    )
    return replace(base, evidence_hash=stable_hash(asdict(base)))


def emergence_evidence_from_json(value: Mapping[str, Any]) -> EmergenceEvidence:
    if int(value.get("schema_version") or 0) != 1:
        raise ValueError("Unsupported emergence-evidence schema")
    if str(value.get("product") or "") != "WAIVER ASSISTANT":
        raise ValueError("Emergence evidence must be Waiver-scoped")
    if str(value.get("classifier_version") or "") != EMERGENCE_CLASSIFIER_VERSION:
        raise ValueError("Unsupported emergence classifier version")
    expected = str(value.get("evidence_hash") or "")
    unsigned = dict(value)
    unsigned["evidence_hash"] = ""
    if not expected or stable_hash(unsigned) != expected:
        raise ValueError("Emergence evidence failed hash verification")

    players: list[PlayerEmergenceEvidence] = []
    for row in value.get("players") or ():
        observations = tuple(
            _observation_from_json(raw) for raw in row.get("observations") or ()
        )
        editorials = tuple(
            _editorial_from_json(raw) for raw in row.get("editorials") or ()
        )
        result_raw = row.get("triggering_result")
        result = (
            FantasyResultComponents(
                total_points=float(result_raw["total_points"]),
                opportunity_points=float(result_raw["opportunity_points"]),
                touchdown_points=float(result_raw["touchdown_points"]),
                long_play_points=float(result_raw["long_play_points"]),
                other_efficiency_points=float(result_raw["other_efficiency_points"]),
                touchdowns=int(result_raw.get("touchdowns") or 0),
                long_plays=int(result_raw.get("long_plays") or 0),
            )
            if result_raw is not None
            else None
        )
        classification = str(row["classification"])
        if classification not in CLASSIFICATIONS:
            raise ValueError("Unsupported emergence classification")
        players.append(
            PlayerEmergenceEvidence(
                player_id=str(row["player_id"]),
                player_name=str(row["player_name"]),
                team=str(row["team"]),
                position=str(row["position"]),
                identity_status=str(row["identity_status"]),
                coverage_status=str(row["coverage_status"]),
                latest_week=int(row["latest_week"]) if row.get("latest_week") is not None else None,
                latest_game_id=str(row["latest_game_id"]) if row.get("latest_game_id") is not None else None,
                rolling_window_weeks=tuple(int(item) for item in row.get("rolling_window_weeks") or ()),
                baseline_weeks=tuple(int(item) for item in row.get("baseline_weeks") or ()),
                excluded_games=tuple(
                    (int(item[0]), str(item[1])) for item in row.get("excluded_games") or ()
                ),
                observations=observations,
                comparisons=tuple(
                    MetricComparison(
                        metric=str(item["metric"]),
                        basis=str(item["basis"]),
                        latest=float(item["latest"]) if item.get("latest") is not None else None,
                        rolling_average=(
                            float(item["rolling_average"])
                            if item.get("rolling_average") is not None
                            else None
                        ),
                        baseline_average=(
                            float(item["baseline_average"])
                            if item.get("baseline_average") is not None
                            else None
                        ),
                        rolling_sample_size=int(item["rolling_sample_size"]),
                        baseline_sample_size=int(item["baseline_sample_size"]),
                        delta_from_baseline=(
                            float(item["delta_from_baseline"])
                            if item.get("delta_from_baseline") is not None
                            else None
                        ),
                    )
                    for item in row.get("comparisons") or ()
                ),
                triggering_result=result,
                editorials=editorials,
                classification=classification,
                affirmative_eligible=bool(row.get("affirmative_eligible")),
                classification_reasons=tuple(str(item) for item in row.get("classification_reasons") or ()),
                warnings=tuple(str(item) for item in row.get("warnings") or ()),
            )
        )
    captured_at = datetime.fromisoformat(str(value["captured_at"]))
    if captured_at.tzinfo is None:
        raise ValueError("Emergence evidence timestamp must be timezone-aware")
    return EmergenceEvidence(
        schema_version=1,
        classifier_version=EMERGENCE_CLASSIFIER_VERSION,
        product="WAIVER ASSISTANT",
        league_key=str(value["league_key"]),
        captured_at=_utc(captured_at),
        usage_maximum_age_hours=float(value["usage_maximum_age_hours"]),
        editorial_maximum_age_hours=float(value["editorial_maximum_age_hours"]),
        players=tuple(players),
        unmatched_player_ids=tuple(str(item) for item in value.get("unmatched_player_ids") or ()),
        ambiguous_player_ids=tuple(str(item) for item in value.get("ambiguous_player_ids") or ()),
        complete=bool(value.get("complete")),
        warnings=tuple(str(item) for item in value.get("warnings") or ()),
        evidence_hash=expected,
    )


def save_emergence_evidence(evidence: EmergenceEvidence, path: str | Path) -> Path:
    return atomic_write_json(path, evidence)


def load_emergence_evidence(path: str | Path) -> EmergenceEvidence:
    return emergence_evidence_from_json(
        json.loads(Path(path).read_text(encoding="utf-8"))
    )
