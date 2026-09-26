from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
import re
from typing import Any, Mapping

from roster_theory.core.models import Projection, RankObservation
from roster_theory.core.errors import CoverageIncomplete, ProviderCapabilityMissing
from roster_theory.core.provenance import DataStamp, stable_hash
from roster_theory.core.scoring_contract import ScoringScope, assess_scoring_rules
from roster_theory.providers.formats import ranking_format, validate_provider_scope
from roster_theory.providers.projection_scoring import (
    SCORING_CONTRACT_VERSION, WEEKLY_RULES, score_projection_row, scoring_coverage,
    statistic_number,
)
from roster_theory.fantasypros import FantasyProsClient


def _number(value: Any) -> float | None:
    if value in (None, "", "-"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _integer(value: Any) -> int | None:
    parsed = _number(value)
    return int(parsed) if parsed is not None else None


def _position_rank(value: Any) -> float | None:
    parsed = _number(value)
    if parsed is not None:
        return parsed
    match = re.search(r"(\d+(?:\.\d+)?)$", str(value or ""))
    return float(match.group(1)) if match else None


@dataclass(frozen=True, slots=True)
class FantasyProsIdentity:
    fantasypros_id: str
    name: str
    position: str
    nfl_team: str | None
    external_ids: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class RankingDataset:
    horizon: str
    raw_horizon: str
    scoring: str | None
    week: int | None
    updated_at: str | None
    contributor_ids: tuple[str, ...]
    identities: tuple[FantasyProsIdentity, ...]
    observations: tuple[RankObservation, ...]
    contributor_observations: tuple[RankObservation, ...]
    fallback_for: str | None
    complete_horizon: bool
    stamp: DataStamp


@dataclass(frozen=True, slots=True)
class ProjectionDataset:
    horizon: str
    scoring: str | None
    week: int | None
    contributor_ids: tuple[str, ...]
    identities: tuple[FantasyProsIdentity, ...]
    projections: tuple[Projection, ...]
    stamp: DataStamp


@dataclass(frozen=True, slots=True)
class NewsRecord:
    player_id: str | None
    published_at: str | None
    title: str
    category: str | None


@dataclass(frozen=True, slots=True)
class PlayerPointRecord:
    player_id: str
    position: str
    total_points: float
    weekly_points: tuple[tuple[int, float], ...]


def _identity(row: Mapping[str, Any], *, projection: bool = False) -> FantasyProsIdentity:
    raw_player_id = row.get("fpid") if projection else row.get("player_id")
    player_id = str(raw_player_id) if raw_player_id not in (None, "") else ""
    if not player_id:
        raise ValueError("FantasyPros row is missing player ID")
    raw_position = row.get("position_id") if projection else row.get("player_position_id")
    position = str(raw_position or "").upper()
    external = {
        "yahoo": row.get("player_yahoo_id"),
        # FantasyPros' legacy field name carries Sportradar UUIDs in the NFL
        # responses; Sleeper exposes the same value as ``sportradar_id``.
        "sportradar": row.get("sportsdata_id") or row.get("sportsdata_player_id"),
        "cbs": row.get("cbs_player_id"),
    }
    return FantasyProsIdentity(
        fantasypros_id=player_id,
        name=str((row.get("name") if projection else row.get("player_name")) or player_id),
        position=position,
        nfl_team=str((row.get("team_id") if projection else row.get("player_team_id")) or "") or None,
        external_ids=tuple(
            sorted((key, str(value)) for key, value in external.items() if value not in (None, ""))
        ),
    )


def normalize_rankings(
    value: Mapping[str, Any],
    *,
    requested_horizon: str,
    board_source: str,
    expert_id: str | None = None,
    captured_at: datetime | None = None,
    endpoint: str = "/consensus-rankings",
    parameters: Mapping[str, Any] | None = None,
) -> RankingDataset:
    captured = captured_at or datetime.now(timezone.utc)
    raw_ranking_type = str(value.get("ranking_type_name") or "").strip()
    ranking_type = _canonical_ranking_horizon(raw_ranking_type)
    fallback = str(value.get("fallback_for") or "") or None
    requested = _canonical_ranking_horizon(requested_horizon)
    complete_horizon = bool(raw_ranking_type) and ranking_type == requested and fallback is None
    week = _integer(value.get("week"))
    rows = value.get("players") or []
    if not isinstance(rows, list):
        raise ValueError("FantasyPros ranking players must be a list")
    identities: list[FantasyProsIdentity] = []
    observations: list[RankObservation] = []
    contributor_observations: list[RankObservation] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        identity = _identity(row)
        identities.append(identity)
        position_rank = _position_rank(row.get("pos_rank"))
        observations.append(
            RankObservation(
                player_id=identity.fantasypros_id,
                horizon=ranking_type or requested,
                board_source=board_source,
                expert_id=expert_id,
                position=identity.position,
                position_rank=position_rank,
                overall_rank=_number(row.get("rank_ecr") or row.get("rank_ave")),
                tier=_integer(row.get("tier")),
                scoring=str(value.get("scoring") or "") or None,
                updated_at=str(value.get("last_updated") or "") or None,
                rank_min=_number(row.get("rank_min")),
                rank_max=_number(row.get("rank_max")),
                rank_std=_number(row.get("rank_std")),
            )
        )
        expert_ranks = row.get("experts") or {}
        if isinstance(expert_ranks, Mapping):
            for contributor_id, contributor_rank in expert_ranks.items():
                rank = _position_rank(contributor_rank)
                if rank is None:
                    continue
                contributor_observations.append(
                    RankObservation(
                        player_id=identity.fantasypros_id,
                        horizon=ranking_type or requested,
                        board_source="expert_ballot",
                        expert_id=str(contributor_id),
                        position=identity.position,
                        position_rank=rank,
                        overall_rank=None,
                        tier=None,
                        scoring=str(value.get("scoring") or "") or None,
                        updated_at=str(value.get("last_updated") or "") or None,
                    )
                )
    contributor_ids = tuple(
        sorted(str(key) for key in (value.get("expert_names") or {}))
    )
    return RankingDataset(
        horizon=ranking_type or requested,
        raw_horizon=raw_ranking_type,
        scoring=str(value.get("scoring") or "") or None,
        week=week,
        updated_at=str(value.get("last_updated") or "") or None,
        contributor_ids=contributor_ids,
        identities=tuple(identities),
        observations=tuple(observations),
        contributor_observations=tuple(contributor_observations),
        fallback_for=fallback,
        complete_horizon=complete_horizon,
        stamp=DataStamp(
            source="FantasyPros",
            endpoint=endpoint,
            captured_at=captured,
            season=_integer(value.get("year")),
            week=week,
            scoring_label=str(value.get("scoring") or "") or None,
            parameter_hash=stable_hash(parameters or {}),
            payload_hash=stable_hash(value),
            cache_status="miss",
            fresh=True,
            export_restriction="personal HOF Premium data",
            warnings=(f"fallback_for:{fallback}",) if fallback else (),
        ),
    )


def _canonical_ranking_horizon(value: str) -> str:
    normalized = re.sub(r"[\s_-]+", " ", str(value or "").strip().upper())
    aliases = {
        "REST OF SEASON": "ROS",
        "ROS": "ROS",
        "WEEK": "WEEKLY",
        "WEEKLY": "WEEKLY",
        "WW": "WAIVER",
        "WAIVER": "WAIVER",
        "WAIVER WIRE": "WAIVER",
    }
    return aliases.get(normalized, normalized)


def normalize_projections(
    value: Mapping[str, Any],
    *,
    horizon: str,
    league_points: Mapping[str, float] | None = None,
    coverage_by_player: Mapping[str, str] | None = None,
    captured_at: datetime | None = None,
    endpoint: str = "/projections",
    parameters: Mapping[str, Any] | None = None,
) -> ProjectionDataset:
    captured = captured_at or datetime.now(timezone.utc)
    rows = value.get("players") or []
    if not isinstance(rows, list):
        raise ValueError("FantasyPros projection players must be a list")
    week = _integer(value.get("week"))
    identities: list[FantasyProsIdentity] = []
    projections: list[Projection] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        identity = _identity(row, projection=True)
        identities.append(identity)
        stats = row.get("stats") or {}
        if not isinstance(stats, Mapping):
            stats = {}
        numeric_stats = tuple(
            sorted(
                (str(key), parsed)
                for key, raw in stats.items()
                if (parsed := statistic_number(raw)) is not None
            )
        )
        projections.append(
            Projection(
                player_id=identity.fantasypros_id,
                horizon=horizon.upper(),
                week=week,
                raw_stats=numeric_stats,
                league_points=float((league_points or {}).get(identity.fantasypros_id, 0.0)),
                source="FantasyPros consensus",
                coverage_status=(coverage_by_player or {}).get(identity.fantasypros_id,
                                  "unverified_scoring_v1"),
            )
        )
    return ProjectionDataset(
        horizon=horizon.upper(),
        scoring=str(value.get("scoring") or "") or None,
        week=week,
        contributor_ids=tuple(sorted(str(item) for item in (value.get("experts") or ()))),
        identities=tuple(identities),
        projections=tuple(projections),
        stamp=DataStamp(
            source="FantasyPros",
            endpoint=endpoint,
            captured_at=captured,
            season=_integer(value.get("season")),
            week=week,
            scoring_label=str(value.get("scoring") or "") or None,
            parameter_hash=stable_hash(parameters or {}),
            payload_hash=stable_hash(value),
            cache_status="miss",
            fresh=True,
            export_restriction="personal HOF Premium data",
        ),
    )


def normalize_scored_projections(
    value: Mapping[str, Any], *, scoring_settings: Mapping[str, Any],
    season: int, week: int, league_id: str = "unbound",
    captured_at: datetime | None = None, endpoint: str = "/projections",
    parameters: Mapping[str, Any] | None = None,
) -> ProjectionDataset:
    """One strict weekly scoring path for direct and cached provider inputs."""
    declared_scoring = str(value.get("scoring") or "").upper()
    if declared_scoring not in {"STD", "HALF", "PPR"}:
        raise CoverageIncomplete("FantasyPros projection has unknown scoring scope")
    validate_provider_scope(value, season=season, scoring=declared_scoring)
    if str(value.get("week")) != str(week):
        raise CoverageIncomplete(f"FantasyPros projection response did not match Week {week}")
    rows = value.get("players")
    if not isinstance(rows, list):
        raise CoverageIncomplete("FantasyPros projection players must be a list")
    assessment = assess_scoring_rules(scoring_settings,
        scope=ScoringScope(league_id, season, "weekly_projection", "WEEKLY", week),
        catalogue=WEEKLY_RULES, catalogue_version=SCORING_CONTRACT_VERSION)
    scored = {}
    for row in rows:
        if not isinstance(row, Mapping) or row.get("fpid") in (None, ""):
            raise CoverageIncomplete("FantasyPros projection row has no player identity")
        player_id = str(row["fpid"])
        if player_id in scored:
            raise CoverageIncomplete("Duplicate FantasyPros projection player identity")
        scored[player_id] = score_projection_row(row, assessment)
    try:
        dataset = normalize_projections(value, horizon="WEEKLY",
            league_points={pid: result.diagnostic_points for pid, result in scored.items()},
            coverage_by_player={pid: scoring_coverage(result) for pid, result in scored.items()},
            captured_at=captured_at, endpoint=endpoint, parameters=parameters)
    except ValueError as exc:
        # Raw NaN/Inf cannot be hashed into a reproducible payload. Keep this a
        # visible failed preparation; never sanitize its provenance into success.
        raise CoverageIncomplete(f"Invalid FantasyPros projection payload: {exc}") from exc
    return replace(dataset, stamp=replace(dataset.stamp, scoring_hash=assessment.scoring_hash,
        parameter_hash=stable_hash({"provider_parameters": parameters or {},
                                   "scoring_contract": SCORING_CONTRACT_VERSION,
                                   "rules_hash": assessment.rules_hash})))


def normalize_news(value: Mapping[str, Any]) -> tuple[NewsRecord, ...]:
    rows = value.get("items") or []
    return tuple(
        NewsRecord(
            player_id=str(row.get("player_id")) if row.get("player_id") is not None else None,
            published_at=str(row.get("published") or row.get("published_at") or "") or None,
            title=str(row.get("title") or ""),
            category=str(row.get("category") or "") or None,
        )
        for row in rows
        if isinstance(row, Mapping)
    )


def normalize_player_points(value: Mapping[str, Any]) -> tuple[PlayerPointRecord, ...]:
    result: list[PlayerPointRecord] = []
    for row in value.get("players") or []:
        if not isinstance(row, Mapping) or row.get("player_id") is None:
            continue
        weeks = row.get("weeks") or {}
        result.append(
            PlayerPointRecord(
                player_id=str(row["player_id"]),
                position=str(row.get("position_id") or "").upper(),
                total_points=float(_number(row.get("points")) or 0.0),
                weekly_points=tuple(
                    sorted(
                        (int(week), float(parsed))
                        for week, raw in weeks.items()
                        if (parsed := _number(raw)) is not None
                    )
                ),
            )
        )
    return tuple(result)


class FantasyProsAdapter:
    """Normalize only Phase-1-proven FantasyPros GET capabilities."""

    def __init__(self, client: FantasyProsClient) -> None:
        self.client = client

    def rankings(
        self,
        season: int,
        position: str,
        *,
        horizon: str,
        scoring: str = "HALF",
        week: int | None = None,
        expert_id: str | None = None,
    ) -> RankingDataset:
        normalized_horizon = _canonical_ranking_horizon(horizon)
        params: dict[str, Any] = {"position": position, "scoring": scoring}
        if scoring not in {"STD", "HALF", "PPR"}:
            raise ProviderCapabilityMissing("Unsupported FantasyPros ranking format: " + scoring)
        if normalized_horizon == "ROS":
            params["type"] = "ROS"
        elif normalized_horizon == "WEEKLY":
            if week is None:
                raise ValueError("Weekly rankings require a week")
            params["week"] = week
        elif normalized_horizon == "WAIVER":
            params["type"] = "WW"
            if week is not None:
                params["week"] = week
        else:
            raise ValueError("Ranking horizon must be ROS, WEEKLY, or WAIVER")
        if expert_id:
            params["filters"] = f"{expert_id}:{expert_id}"
        else:
            params["experts"] = "show"
        value = self.client.consensus_rankings(season, **params)
        validate_provider_scope(value, season=season, scoring=scoring)
        dataset = normalize_rankings(
            value,
            requested_horizon=normalized_horizon,
            board_source="selected" if expert_id else "market",
            expert_id=expert_id,
            endpoint=f"/nfl/{season}/consensus-rankings",
            parameters=params,
        )
        if not dataset.complete_horizon:
            raise ProviderCapabilityMissing(
                f"FantasyPros returned {dataset.horizon} for requested "
                f"{normalized_horizon}; fallback={dataset.fallback_for or 'none'}"
            )
        return dataset

    def weekly_projections(
        self,
        season: int,
        week: int,
        position: str,
        scoring_settings: Mapping[str, Any],
        *,
        league_id: str = "unbound",
    ) -> ProjectionDataset:
        scoring_code = ranking_format(scoring_settings).scoring
        params = {"position": position, "scoring": scoring_code, "week": week}
        value = self.client.projections(season, **params)
        validate_provider_scope(value, season=season, scoring=scoring_code)
        if str(value.get("week")) != str(week):
            raise ProviderCapabilityMissing(f"FantasyPros projection response did not match Week {week}")
        return normalize_scored_projections(
            value,
            scoring_settings=scoring_settings, season=season, week=week, league_id=league_id,
            endpoint=f"/nfl/{season}/projections",
            parameters=params,
        )

    def injury_news(self, *, limit: int = 25) -> tuple[NewsRecord, ...]:
        return normalize_news(self.client.news(category="injury", limit=limit))

    def historical_player_points(
        self, season: int, start: int, end: int, position: str
    ) -> tuple[PlayerPointRecord, ...]:
        value = self.client.player_points(
            season, start=start, end=end, position=position, scoring="PPR"
        )
        return normalize_player_points(value)
