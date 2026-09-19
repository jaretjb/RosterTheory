from __future__ import annotations

import csv
import json
import time
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from roster_theory.core.errors import (
    CoverageIncomplete,
    IdentityIncomplete,
    ScheduleIncomplete,
    UnsupportedScoring,
)
from roster_theory.core.identity import reconcile_identities
from roster_theory.core.models import Projection, RankObservation
from roster_theory.core.replacement import positional_waiver_baselines
from roster_theory.core.scoring import STAT_ALIASES, score_stats
from roster_theory.fantasypros import FantasyProsClient
from roster_theory.providers.cache import (
    DailyRequestBudget,
    atomic_write_json,
    cache_key,
    is_fresh,
)
from roster_theory.providers.fantasypros import (
    FantasyProsIdentity,
    NewsRecord,
    ProjectionDataset,
    RankingDataset,
    normalize_news,
    normalize_projections,
    normalize_rankings,
)
from roster_theory.trade.boards import (
    SelectedRank,
    ValueBoard,
    ValuationGap,
    aggregate_selected_ranks,
    build_projection_curves,
    build_value_board,
    export_board_evidence,
    valuation_gaps,
)
from roster_theory.trade.call_plan import CallPlan, PlannedCall, build_call_plan
from roster_theory.trade.horizons import (
    EARLY_SEASON_DRAFT_ANCHOR,
    BallotExclusion,
    DualHorizonPlayer,
    LongTermPlayer,
    SeasonStageDecision,
    SnapshotDatum,
    WeeklyPlayerSignal,
    choose_season_stage,
    compose_horizon_views,
    capture_prospective_snapshot,
    filter_ros_ballots,
    load_draft_anchor,
)
from roster_theory.trade.experts import CurrentExpert, normalize_current_experts
from roster_theory.trade.schedule import load_schedule
from roster_theory.trade.service import RefreshResult, refresh_trade_snapshot
from roster_theory.trade.snapshot import retag_trade_snapshot, save_trade_snapshot


POSITION_MINIMUMS: Mapping[str, int] = {"QB": 25, "RB": 60, "WR": 60, "TE": 20}
SPECIAL_TEAM_POSITIONS = ("K", "DST")
_NFL_TEAM_ALIASES: Mapping[str, str] = {
    "JAC": "JAX",
    "OAK": "LV",
    "SD": "LAC",
    "STL": "LAR",
    "WSH": "WAS",
}
OUT_OF_SCOPE_SCORING_SETTINGS: Mapping[str, str] = {
    "blk_kick": "DEF blocked-kick scoring",
    "def_st_ff": "DEF/special-teams forced-fumble scoring",
    "def_st_fum_rec": "DEF/special-teams fumble-recovery scoring",
    "def_st_td": "DEF/special-teams touchdown scoring",
    "def_td": "DEF touchdown scoring",
    "ff": "DEF/IDP forced-fumble scoring",
    "fgm_0_19": "K field-goal scoring",
    "fgm_20_29": "K field-goal scoring",
    "fgm_30_39": "K field-goal scoring",
    "fgm_40_49": "K field-goal scoring",
    "fgm_50_59": "K field-goal scoring",
    "fgm_50p": "K field-goal scoring",
    "fgm_60p": "K field-goal scoring",
    "fgmiss": "K missed-field-goal scoring",
    "int": "DEF/IDP interception scoring",
    "pts_allow_0": "DEF points-allowed scoring",
    "pts_allow_1_6": "DEF points-allowed scoring",
    "pts_allow_7_13": "DEF points-allowed scoring",
    "pts_allow_14_20": "DEF points-allowed scoring",
    "pts_allow_21_27": "DEF points-allowed scoring",
    "pts_allow_28_34": "DEF points-allowed scoring",
    "pts_allow_35p": "DEF points-allowed scoring",
    "sack": "DEF/IDP sack scoring",
    "safe": "DEF safety scoring",
    "st_ff": "special-teams forced-fumble scoring",
    "st_fum_rec": "special-teams fumble-recovery scoring",
    "xpm": "K extra-point scoring",
    "xpmiss": "K missed-extra-point scoring",
}
PROJECTION_LIMITED_SCORING_SETTINGS: Mapping[str, str] = {
    "fum_rec": "rare fumble recovery is not supplied in the skill-player forecast schema",
    "fum_rec_td": "rare fumble-recovery touchdown is not supplied in the skill-player forecast schema",
}


@dataclass(frozen=True, slots=True)
class TradeScoringCapability:
    supported_skill_settings: tuple[str, ...]
    out_of_scope_settings: tuple[tuple[str, str], ...]
    projection_limited_settings: tuple[tuple[str, str], ...]
    unsupported_settings: tuple[str, ...]


def classify_trade_scoring(
    scoring: Mapping[str, Any] | Sequence[tuple[str, float]],
) -> TradeScoringCapability:
    values = dict(scoring)
    nonzero = {
        str(setting)
        for setting, multiplier in values.items()
        if float(multiplier or 0.0) != 0.0
    }
    out_of_scope = tuple(
        (setting, OUT_OF_SCOPE_SCORING_SETTINGS[setting])
        for setting in sorted(nonzero.intersection(OUT_OF_SCOPE_SCORING_SETTINGS))
    )
    projection_limited = tuple(
        (setting, PROJECTION_LIMITED_SCORING_SETTINGS[setting])
        for setting in sorted(
            nonzero.intersection(PROJECTION_LIMITED_SCORING_SETTINGS)
        )
    )
    classified = {
        setting for setting, _ in (*out_of_scope, *projection_limited)
    }
    supported = tuple(sorted(nonzero.intersection(STAT_ALIASES) - classified))
    unsupported = tuple(sorted(nonzero - set(STAT_ALIASES) - classified))
    return TradeScoringCapability(
        supported_skill_settings=supported,
        out_of_scope_settings=out_of_scope,
        projection_limited_settings=projection_limited,
        unsupported_settings=unsupported,
    )


def validate_trade_scoring(
    scoring: Mapping[str, Any] | Sequence[tuple[str, float]],
) -> TradeScoringCapability:
    capability = classify_trade_scoring(scoring)
    if capability.unsupported_settings:
        raise UnsupportedScoring(
            "League scoring has unsupported skill projection categories: "
            + ", ".join(capability.unsupported_settings)
        )
    return capability


@dataclass(frozen=True, slots=True)
class ExpertPoolMember:
    expert_id: str
    expert_name: str
    source_name: str
    weight: float


@dataclass(frozen=True, slots=True)
class BoardRefreshResult:
    refresh: RefreshResult
    selected_raw: ValueBoard
    selected_final: ValueBoard
    market: ValueBoard
    selected_ranks: tuple[SelectedRank, ...]
    gaps: tuple[ValuationGap, ...]
    call_plan: CallPlan
    output_path: Path
    identity_matches: int
    required_players: int
    stage: SeasonStageDecision
    horizon_views: tuple[DualHorizonPlayer, ...]
    prospective_snapshot_path: Path
    weekly_projections: tuple[Projection, ...]
    weekly_rankings: tuple[RankObservation, ...] = ()
    ros_rankings: tuple[RankObservation, ...] = ()
    expert_pool: tuple[ExpertPoolMember, ...] = ()


@dataclass(frozen=True, slots=True)
class ValueInputs:
    weekly_rankings: tuple[RankingDataset, ...]
    ros_rankings: tuple[RankingDataset, ...]
    projection_sets: tuple[ProjectionDataset, ...]
    current_experts: tuple[CurrentExpert, ...]
    news: tuple[NewsRecord, ...]
    call_plan: CallPlan


def _ros_market_is_complete(datasets: Sequence[RankingDataset]) -> bool:
    return len(datasets) >= len(POSITION_MINIMUMS) and all(
        any(
            dataset.complete_horizon
            and dataset.horizon == "ROS"
            and sum(
                row.position == position and row.position_rank is not None
                for row in dataset.observations
            )
            >= minimum
            for dataset in datasets
        )
        for position, minimum in POSITION_MINIMUMS.items()
    )


def load_expert_pool(
    path: str | Path = "data/manual/fantasypros/inseason_expert_pool_2026.csv",
) -> tuple[ExpertPoolMember, ...]:
    with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
        rows = tuple(csv.DictReader(handle))
    members = tuple(
        ExpertPoolMember(
            expert_id=str(row["expert_id"]),
            expert_name=str(row["expert_name"]),
            source_name=str(row["source_name"]),
            weight=float(row["weight"]),
        )
        for row in rows
    )
    if not members or abs(sum(member.weight for member in members) - 1.0) > 1e-6:
        raise ValueError("In-season expert pool weights must sum to one")
    return members


def default_inseason_expert_pool_path(league_key: str, season: int) -> Path:
    return (
        Path("data")
        / "manual"
        / "policies"
        / league_key
        / str(season)
        / "inseason_experts.csv"
    )


def _read_budget(path: Path) -> DailyRequestBudget:
    if not path.exists():
        return DailyRequestBudget()
    return DailyRequestBudget.from_json(json.loads(path.read_text(encoding="utf-8")))


def _cache_record(path: Path, maximum_age: timedelta, now: datetime) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        captured = datetime.fromisoformat(str(value["captured_at"]))
        if is_fresh(captured, maximum_age, now=now) and isinstance(value.get("payload"), dict):
            return value
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None
    return None


def resolve_draft_anchor(
    league_key: str,
    league_id: str,
    *,
    path: str | Path | None = None,
    updated_at: str | None = None,
) -> tuple[Path, str]:
    target = Path(
        path or Path("data/exports/league_boards_2026") / f"{league_key}_board.csv"
    )
    if not target.exists():
        raise CoverageIncomplete(
            f"Week 1 Draft anchor is missing for league {league_key}: {target}"
        )
    if path is not None and updated_at is not None:
        return target, updated_at

    metadata_path = target.with_name(f"{league_key}_metadata.json")
    if not metadata_path.exists():
        raise CoverageIncomplete(
            f"Week 1 Draft anchor metadata is missing for league {league_key}: {metadata_path}"
        )
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CoverageIncomplete(
            f"Week 1 Draft anchor metadata is unreadable for league {league_key}"
        ) from exc
    if str(metadata.get("league_key") or "") != league_key:
        raise CoverageIncomplete("Week 1 Draft anchor metadata has the wrong league key")
    if str(metadata.get("league_id") or "") != league_id:
        raise CoverageIncomplete("Week 1 Draft anchor metadata has the wrong league ID")
    source_time = updated_at or str(metadata.get("generated_at") or "")
    if not source_time:
        raise CoverageIncomplete("Week 1 Draft anchor metadata has no generated timestamp")
    try:
        datetime.fromisoformat(source_time)
    except ValueError as exc:
        raise CoverageIncomplete(
            "Week 1 Draft anchor metadata has an invalid generated timestamp"
        ) from exc
    return target, source_time


def _input_calls(
    season: int,
    week: int,
    weeks: Sequence[int],
    cache_dir: Path,
    now: datetime,
    budget: DailyRequestBudget,
    ranking_positions: Sequence[str] = tuple(POSITION_MINIMUMS),
    weekly_ranking_max_age: timedelta = timedelta(hours=12),
    ros_ranking_max_age: timedelta = timedelta(hours=24),
    ros_experts_max_age: timedelta = timedelta(hours=12),
) -> tuple[CallPlan, dict[str, Path], dict[str, dict[str, Any]]]:
    calls: list[PlannedCall] = []
    paths: dict[str, Path] = {}
    cached: dict[str, dict[str, Any]] = {}
    definitions: list[tuple[str, str, dict[str, Any], timedelta]] = []
    for position in ranking_positions:
        definitions.append(
            (
                f"rankings_{position.lower()}",
                f"/nfl/{season}/consensus-rankings",
                {"position": position, "scoring": "HALF", "week": week, "experts": "show"},
                weekly_ranking_max_age,
            )
        )
    ros_positions = (
        tuple(ranking_positions)
        if week >= 2
        else tuple(position for position in ranking_positions if position == "DST")
    )
    if ros_positions:
        for position in ros_positions:
            definitions.append(
                (
                    f"ros_rankings_{position.lower()}",
                    f"/nfl/{season}/consensus-rankings",
                    {
                        "position": position,
                        "scoring": "HALF",
                        "type": "ROS",
                        "experts": "show",
                    },
                    ros_ranking_max_age,
                )
            )
        if week >= 2:
            definitions.append(
                (
                    "ros_experts",
                    f"/nfl/{season}/rankings/experts",
                    {"type": "ROS", "include_overall": "true"},
                    ros_experts_max_age,
                )
            )
    definitions.append(
        (
            "material_news",
            "/nfl/news",
            {"limit": 100},
            timedelta(hours=2),
        )
    )
    for projection_week in weeks:
        definitions.append(
            (
                f"projections_{projection_week}",
                f"/nfl/{season}/projections",
                {"position": "ALL", "scoring": "HALF", "week": projection_week},
                timedelta(hours=12),
            )
        )
    for name, endpoint, parameters, maximum_age in definitions:
        path = cache_dir / f"{cache_key(endpoint, parameters)}.json"
        record = _cache_record(path, maximum_age, now)
        paths[name] = path
        if record is not None:
            cached[name] = record
        calls.append(
            PlannedCall(
                name=name,
                provider="FantasyPros",
                endpoint=endpoint,
                parameters=tuple(sorted(parameters.items())),
                fresh_cache_hit=record is not None,
            )
        )
    return build_call_plan(calls, budget), paths, cached


def _fetch_value_inputs(
    snapshot_result: RefreshResult,
    *,
    client: FantasyProsClient,
    cache_dir: Path,
    budget_path: Path,
    ranking_positions: Sequence[str] = tuple(POSITION_MINIMUMS),
    weekly_ranking_max_age: timedelta = timedelta(hours=12),
    ros_ranking_max_age: timedelta = timedelta(hours=24),
    ros_experts_max_age: timedelta = timedelta(hours=12),
) -> ValueInputs:
    snapshot = snapshot_result.snapshot
    now = datetime.now(timezone.utc)
    budget = _read_budget(budget_path)
    weeks = tuple(week.week for week in snapshot.weeks)
    plan, cache_paths, cached = _input_calls(
        snapshot.league.season,
        snapshot.manifest.current_week,
        weeks,
        cache_dir,
        now,
        budget,
        ranking_positions,
        weekly_ranking_max_age,
        ros_ranking_max_age,
        ros_experts_max_age,
    )
    if plan.fantasypros_calls:
        budget.reserve(plan.fantasypros_calls)
        atomic_write_json(budget_path, budget.to_json())
    values: dict[str, dict[str, Any]] = dict(cached)
    last_request = 0.0
    for call in plan.calls:
        if call.fresh_cache_hit:
            continue
        elapsed = time.monotonic() - last_request
        if last_request and elapsed < 1.05:
            time.sleep(1.05 - elapsed)
        parameters = dict(call.parameters)
        if call.name.startswith("rankings_") or call.name.startswith("ros_rankings_"):
            payload = client.consensus_rankings(snapshot.league.season, **parameters)
        elif call.name == "ros_experts":
            payload = client.ranking_experts(snapshot.league.season, **parameters)
        elif call.name == "material_news":
            payload = client.news(**parameters)
        else:
            payload = client.projections(snapshot.league.season, **parameters)
        captured_at = datetime.now(timezone.utc).isoformat()
        record = {"captured_at": captured_at, "payload": payload}
        atomic_write_json(cache_paths[call.name], record)
        values[call.name] = record
        last_request = time.monotonic()

    ranking_datasets: list[RankingDataset] = []
    for position in ranking_positions:
        name = f"rankings_{position.lower()}"
        record = values[name]
        dataset = normalize_rankings(
            record["payload"],
            requested_horizon="WEEKLY",
            board_source="market",
            captured_at=datetime.fromisoformat(record["captured_at"]),
            endpoint=f"/nfl/{snapshot.league.season}/consensus-rankings",
            parameters={"position": position, "scoring": "HALF", "week": snapshot.manifest.current_week, "experts": "show"},
        )
        if dataset.horizon != "WEEKLY" or dataset.week != snapshot.manifest.current_week:
            raise CoverageIncomplete("FantasyPros rankings did not return the active weekly horizon")
        status = "hit" if name in cached else "miss"
        ranking_datasets.append(replace(dataset, stamp=replace(dataset.stamp, cache_status=status)))

    ros_datasets: list[RankingDataset] = []
    current_experts: tuple[CurrentExpert, ...] = ()
    news = normalize_news(values["material_news"]["payload"])
    ros_positions = (
        tuple(ranking_positions)
        if snapshot.manifest.current_week >= 2
        else tuple(position for position in ranking_positions if position == "DST")
    )
    if ros_positions:
        for position in ros_positions:
            name = f"ros_rankings_{position.lower()}"
            record = values[name]
            dataset = normalize_rankings(
                record["payload"],
                requested_horizon="ROS",
                board_source="market",
                captured_at=datetime.fromisoformat(record["captured_at"]),
                endpoint=f"/nfl/{snapshot.league.season}/consensus-rankings",
                parameters={
                    "position": position,
                    "scoring": "HALF",
                    "type": "ROS",
                    "experts": "show",
                },
            )
            status = "hit" if name in cached else "miss"
            ros_datasets.append(
                replace(dataset, stamp=replace(dataset.stamp, cache_status=status))
            )
        if snapshot.manifest.current_week >= 2:
            current_experts = normalize_current_experts(values["ros_experts"]["payload"])

    scoring = dict(snapshot.league.scoring)
    projection_datasets: list[ProjectionDataset] = []
    for week in weeks:
        name = f"projections_{week}"
        record = values[name]
        payload = record["payload"]
        points: dict[str, float] = {}
        for row in payload.get("players") or ():
            if not isinstance(row, Mapping) or row.get("fpid") is None:
                continue
            scored = score_stats(row.get("stats") or {}, scoring)
            points[str(row["fpid"])] = scored.points
        dataset = normalize_projections(
            payload,
            horizon="WEEKLY",
            league_points=points,
            captured_at=datetime.fromisoformat(record["captured_at"]),
            endpoint=f"/nfl/{snapshot.league.season}/projections",
            parameters={"position": "ALL", "scoring": "HALF", "week": week},
        )
        if dataset.week != week:
            raise CoverageIncomplete(f"FantasyPros projection response did not match Week {week}")
        status = "hit" if name in cached else "miss"
        projection_datasets.append(replace(dataset, stamp=replace(dataset.stamp, cache_status=status)))
    return ValueInputs(
        weekly_rankings=tuple(ranking_datasets),
        ros_rankings=tuple(ros_datasets),
        projection_sets=tuple(projection_datasets),
        current_experts=current_experts,
        news=news,
        call_plan=plan,
    )


def _identity_map(
    sleeper_players: Sequence[Any],
    identities: Sequence[FantasyProsIdentity],
    overrides: Mapping[str, str] | None = None,
) -> tuple[dict[str, str], int]:
    unique_identities: dict[str, FantasyProsIdentity] = {}
    for identity in identities:
        existing = unique_identities.get(identity.fantasypros_id)
        if existing is None or len(identity.external_ids) > len(existing.external_ids):
            unique_identities[identity.fantasypros_id] = identity
    source_rows = []
    for identity in unique_identities.values():
        # Provider-local numeric IDs are different namespaces. Prefix the
        # FantasyPros value so coincidentally equal Sleeper IDs cannot become
        # false exact matches; only shared external IDs may bridge providers.
        row = {"fantasypros_id": f"fp:{identity.fantasypros_id}"}
        row.update(dict(identity.external_ids))
        source_rows.append(row)
    target_rows = []
    for player in sleeper_players:
        row = {"sleeper_id": player.player_id}
        row.update(dict(player.external_ids))
        target_rows.append(row)
    report = reconcile_identities(
        source_rows,
        target_rows,
        source_id_field="fantasypros_id",
        target_id_field="sleeper_id",
        shared_id_fields=("yahoo", "sportradar"),
    )
    if report.ambiguous:
        raise IdentityIncomplete("FantasyPros identities contain ambiguous exact-ID matches")
    resolved = {
        match.source_id.removeprefix("fp:"): match.target_id
        for match in report.matches
    }
    sleeper_by_id = {player.player_id: player for player in sleeper_players}
    claimed_sleeper_ids = set(resolved.values())
    for fantasypros_id, sleeper_id in tuple(sorted(resolved.items())):
        identity = unique_identities[fantasypros_id]
        if identity.position.upper().replace("DEF", "DST") != "DST":
            continue
        player = sleeper_by_id[sleeper_id]
        source_team = _normalize_nfl_team(identity.nfl_team)
        target_team = _normalize_nfl_team(player.nfl_team)
        target_positions = {
            str(position).upper().replace("DEF", "DST")
            for position in player.positions
        }
        if not source_team or source_team != target_team or "DST" not in target_positions:
            raise IdentityIncomplete(
                "FantasyPros DST exact-ID match has mismatched team identity: "
                f"{fantasypros_id}/{sleeper_id}"
            )
    for fantasypros_id, identity in sorted(unique_identities.items()):
        if fantasypros_id in resolved:
            continue
        if identity.position.upper().replace("DEF", "DST") != "DST":
            continue
        source_team = _normalize_nfl_team(identity.nfl_team)
        if not source_team:
            continue
        candidates = tuple(
            sorted(
                player.player_id
                for player in sleeper_players
                if "DST"
                in {
                    str(position).upper().replace("DEF", "DST")
                    for position in player.positions
                }
                and _normalize_nfl_team(player.nfl_team) == source_team
            )
        )
        if len(candidates) > 1:
            raise IdentityIncomplete(
                "FantasyPros DST team identity is ambiguous: "
                f"{fantasypros_id}/{source_team}/" + ",".join(candidates)
            )
        if not candidates:
            continue
        sleeper_id = candidates[0]
        if sleeper_id in claimed_sleeper_ids:
            raise IdentityIncomplete(
                "FantasyPros DST team identity conflicts with an existing match: "
                f"{fantasypros_id}/{sleeper_id}"
            )
        resolved[fantasypros_id] = sleeper_id
        claimed_sleeper_ids.add(sleeper_id)
    for fantasypros_id, sleeper_id in sorted((overrides or {}).items()):
        identity = unique_identities.get(fantasypros_id)
        player = sleeper_by_id.get(sleeper_id)
        if identity is None and player is None:
            continue
        if identity is None or player is None:
            raise IdentityIncomplete(
                f"In-season identity override is only present on one provider: "
                f"{fantasypros_id}/{sleeper_id}"
            )
        existing = resolved.get(fantasypros_id)
        if existing is not None and existing != sleeper_id:
            raise IdentityIncomplete(
                f"In-season identity override conflicts with exact-ID match: "
                f"{fantasypros_id}/{existing}/{sleeper_id}"
            )
        resolved[fantasypros_id] = sleeper_id
    return resolved, len(resolved)


def _normalize_nfl_team(value: str | None) -> str:
    team = str(value or "").strip().upper()
    return _NFL_TEAM_ALIASES.get(team, team)


def load_inseason_identity_overrides(
    path: str | Path = "config/inseason_identity_overrides_2026.csv",
) -> dict[str, str]:
    target = Path(path)
    if not target.exists():
        return {}
    with target.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = tuple(csv.DictReader(handle))
    required = {"fantasypros_id", "sleeper_id", "player_name", "team", "position", "evidence"}
    if rows and not required.issubset(rows[0]):
        raise ValueError("In-season identity override CSV has incomplete columns")
    result: dict[str, str] = {}
    for row in rows:
        fantasypros_id = str(row.get("fantasypros_id") or "").strip()
        sleeper_id = str(row.get("sleeper_id") or "").strip()
        if not fantasypros_id or not sleeper_id or not str(row.get("evidence") or "").strip():
            raise ValueError("In-season identity overrides require both IDs and evidence")
        if fantasypros_id in result and result[fantasypros_id] != sleeper_id:
            raise ValueError(f"Conflicting in-season identity override: {fantasypros_id}")
        result[fantasypros_id] = sleeper_id
    return result


def _canonical_rank(
    observation: RankObservation,
    identity_map: Mapping[str, str],
    *,
    retain_unmatched_slot: bool = False,
    horizon: str = "WEEKLY-PROXY",
) -> RankObservation | None:
    player_id = identity_map.get(observation.player_id)
    if player_id is None and retain_unmatched_slot:
        player_id = f"fp:{observation.player_id}"
    elif player_id is None:
        return None
    return replace(
        observation,
        player_id=player_id,
        horizon=horizon,
        overall_rank=None,
    )


def _required_market_universe(
    snapshot_result: RefreshResult,
    market_rows: Sequence[RankObservation],
) -> tuple[
    tuple[RankObservation, ...], dict[str, str], dict[str, str], dict[str, int]
]:
    snapshot = snapshot_result.snapshot
    by_id = {row.player_id: row for row in market_rows}
    players = {player.player_id: player for player in snapshot.players}
    owned = dict(snapshot.owner_by_player)
    missing_rostered = sorted(
        player_id
        for player_id in owned
        if player_id in set(snapshot.tradeable_player_ids) and player_id not in by_id
    )
    if missing_rostered:
        raise CoverageIncomplete(
            "Active ownership board does not cover rostered skill players: "
            + ", ".join(missing_rostered)
        )
    required_counts: dict[str, int] = {}
    for position, minimum in POSITION_MINIMUMS.items():
        rostered_ranks = [
            int(by_id[player_id].position_rank or 0)
            for player_id in owned
            if player_id in by_id and by_id[player_id].position == position
        ]
        required_counts[position] = max([minimum, *rostered_ranks])
    required_rows: list[RankObservation] = []
    curve_positions: dict[str, str] = {}
    for position, cutoff in required_counts.items():
        rows = sorted(
            (
                row
                for row in market_rows
                if row.position == position
                and row.position_rank is not None
                and row.position_rank <= cutoff
            ),
            key=lambda row: float(row.position_rank or 0),
        )
        ranks = [int(row.position_rank or 0) for row in rows]
        if ranks != list(range(1, cutoff + 1)):
            raise CoverageIncomplete(
                f"Mapped {position} ECR is not contiguous through rank {cutoff}"
            )
        required_rows.extend(rows)
        curve_positions.update((row.player_id, position) for row in rows)
    board_positions = {
        player_id: position
        for player_id, position in curve_positions.items()
        if not player_id.startswith("fp:")
    }
    if any(player_id not in players for player_id in board_positions):
        raise IdentityIncomplete("Required ranking universe is absent from Sleeper players")
    return tuple(required_rows), board_positions, curve_positions, required_counts


def _canonical_projections(
    datasets: Sequence[ProjectionDataset],
    identity_map: Mapping[str, str],
    required_positions: Mapping[str, str],
    bye_by_team: Mapping[str, int],
    sleeper_players: Mapping[str, Any],
    allowed_positions: Sequence[str] = tuple(POSITION_MINIMUMS),
) -> tuple[tuple[Projection, ...], dict[str, str], dict[str, tuple[str, ...]]]:
    by_player_week: dict[tuple[str, int], Projection] = {}
    candidate_positions: dict[str, str] = {}
    weeks = tuple(int(dataset.week or 0) for dataset in datasets)
    for dataset in datasets:
        identity_by_id = {
            identity.fantasypros_id: identity for identity in dataset.identities
        }
        for projection in dataset.projections:
            player_id = identity_map.get(projection.player_id, f"fp:{projection.player_id}")
            identity = identity_by_id.get(projection.player_id)
            position = identity.position if identity is not None else ""
            position = "DST" if position == "DEF" else position
            if position in set(allowed_positions) and dataset.week is not None:
                candidate_positions[player_id] = position
                by_player_week[(player_id, dataset.week)] = replace(
                    projection, player_id=player_id
                )
    result: list[Projection] = []
    complete_positions: dict[str, str] = {}
    warning_map: dict[str, tuple[str, ...]] = {}
    for player_id, position in sorted(candidate_positions.items()):
        team = (
            sleeper_players[player_id].nfl_team
            if player_id in sleeper_players
            else None
        )
        rows: list[Projection] = []
        missing_weeks: list[int] = []
        for week in weeks:
            projection = by_player_week.get((player_id, week))
            if projection is not None:
                rows.append(projection)
            elif bye_by_team.get(str(team)) == week:
                rows.append(
                    Projection(
                        player_id=player_id,
                        horizon="WEEKLY",
                        week=week,
                        raw_stats=(),
                        league_points=0.0,
                        source="Audited NFL bye",
                        coverage_status="verified_bye_zero",
                    )
                )
            else:
                missing_weeks.append(week)
        if missing_weeks and player_id not in required_positions:
            continue
        if missing_weeks:
            warning_map[player_id] = tuple(
                f"FantasyPros omitted non-bye Week {week}; explicit zero retained"
                for week in missing_weeks
            )
            rows.extend(
                Projection(
                    player_id=player_id,
                    horizon="WEEKLY",
                    week=week,
                    raw_stats=(),
                    league_points=0.0,
                    source="FantasyPros source omission",
                    coverage_status="source_omission_zero",
                )
                for week in missing_weeks
            )
        result.extend(rows)
        complete_positions[player_id] = position
    absent_required = sorted(set(required_positions) - set(complete_positions))
    known_inactive = {"IR", "PUP", "SUSP", "OUT"}
    for player_id in tuple(absent_required):
        player = sleeper_players.get(player_id)
        if player is None or str(player.injury_status or "").upper() not in known_inactive:
            continue
        position = required_positions[player_id]
        result.extend(
            Projection(
                player_id=player_id,
                horizon="WEEKLY",
                week=week,
                raw_stats=(),
                league_points=0.0,
                source=f"Sleeper {player.injury_status} status",
                coverage_status="known_inactive_zero",
            )
            for week in weeks
        )
        complete_positions[player_id] = position
        warning_map[player_id] = (
            f"No weekly projection; explicit zero retained for Sleeper {player.injury_status} status",
        )
    absent_required = sorted(set(required_positions) - set(complete_positions))
    if absent_required:
        raise CoverageIncomplete(
            "Required ranked players have no FantasyPros projection identity: "
            + ", ".join(absent_required)
        )
    return tuple(result), complete_positions, warning_map


def _build_provider_projection_curves(
    canonical_projections: Sequence[Projection],
    distribution_positions: Mapping[str, str],
    *,
    required_counts: Mapping[str, int],
    expected_weeks: Sequence[int],
):
    """Build rank-slot curves from the provider distribution, not board identities.

    Provider-only identifiers intentionally remain here: they supply an
    authoritative projection slot even when the current Sleeper directory cannot
    map them to a roster/value-board player. Board construction applies the
    separate mapped-player boundary later.
    """

    return build_projection_curves(
        canonical_projections,
        distribution_positions,
        required_counts=required_counts,
        expected_weeks=expected_weeks,
    )


def _raw_rank_ordinals(selected: Sequence[SelectedRank]) -> dict[str, int]:
    result: dict[str, int] = {}
    for position in sorted({row.position for row in selected}):
        rows = sorted(
            (row for row in selected if row.position == position),
            key=lambda row: (
                row.raw_position_rank if row.raw_position_rank is not None else float("inf"),
                row.market_position_rank,
                row.player_id,
            ),
        )
        result.update((row.player_id, rank) for rank, row in enumerate(rows, 1))
    return result


def _draft_selected_ranks(
    selected_rows: Sequence[RankObservation],
    market_rows: Sequence[RankObservation],
) -> tuple[SelectedRank, ...]:
    selected_by_id = {row.player_id: row for row in selected_rows}
    if set(selected_by_id) != {row.player_id for row in market_rows}:
        raise CoverageIncomplete("Final Draft selected and market anchors differ")
    position_rank: dict[str, int] = {}
    for position in POSITION_MINIMUMS:
        rows = sorted(
            (row for row in selected_rows if row.position == position),
            key=lambda row: (float(row.position_rank or float("inf")), row.player_id),
        )
        position_rank.update((row.player_id, rank) for rank, row in enumerate(rows, 1))
    overall_rank = {
        row.player_id: rank
        for rank, row in enumerate(
            sorted(
                (row for row in selected_rows if row.overall_rank is not None),
                key=lambda row: (float(row.overall_rank or float("inf")), row.player_id),
            ),
            1,
        )
    }
    return tuple(
        SelectedRank(
            player_id=market.player_id,
            position=market.position,
            raw_position_rank=selected_by_id[market.player_id].position_rank,
            raw_overall_rank=selected_by_id[market.player_id].overall_rank,
            final_position_rank=position_rank[market.player_id],
            final_overall_rank=overall_rank.get(market.player_id),
            market_position_rank=int(market.position_rank or 0),
            market_overall_rank=(
                int(market.overall_rank) if market.overall_rank is not None else None
            ),
            dispersion=None,
            contributor_weight=1.0,
            contributions=(),
            omissions=(),
            shrinkage_to_ecr=0.0,
        )
        for market in sorted(market_rows, key=lambda row: row.player_id)
    )


def refresh_value_boards(
    league_key: str,
    *,
    config_path: str | Path | None = None,
    expert_pool_path: str | Path | None = None,
    cache_dir: str | Path = "data/cache/trade/fantasypros/2026",
    budget_path: str | Path = "data/cache/trade/fantasypros/daily_budget.json",
    output_path: str | Path | None = None,
    fantasypros_client: FantasyProsClient | None = None,
    draft_anchor_path: str | Path | None = None,
    draft_anchor_updated_at: str | None = None,
    identity_override_path: str | Path = "config/inseason_identity_overrides_2026.csv",
    include_special_teams: bool = False,
    weekly_ranking_max_age: timedelta = timedelta(hours=12),
    ros_ranking_max_age: timedelta = timedelta(hours=24),
    ros_experts_max_age: timedelta = timedelta(hours=12),
) -> BoardRefreshResult:
    # During Week 1 the final Draft boards own long-term value. The current
    # weekly feed is still fetched below, but only as a separate signal.
    refresh = refresh_trade_snapshot(
        league_key,
        config_path=config_path,
        ranking_horizon=EARLY_SEASON_DRAFT_ANCHOR,
        include_special_team_identities=include_special_teams,
    )
    snapshot = refresh.snapshot
    scoring_capability = validate_trade_scoring(snapshot.league.scoring)
    ranking_positions = (
        (*POSITION_MINIMUMS, *SPECIAL_TEAM_POSITIONS)
        if include_special_teams
        else tuple(POSITION_MINIMUMS)
    )
    inputs = _fetch_value_inputs(
        refresh,
        client=fantasypros_client or FantasyProsClient(),
        cache_dir=Path(cache_dir),
        budget_path=Path(budget_path),
        ranking_positions=ranking_positions,
        weekly_ranking_max_age=weekly_ranking_max_age,
        ros_ranking_max_age=ros_ranking_max_age,
        ros_experts_max_age=ros_experts_max_age,
    )
    all_identities = tuple(
        identity
        for dataset in (
            *inputs.weekly_rankings,
            *inputs.ros_rankings,
            *inputs.projection_sets,
        )
        for identity in dataset.identities
    )
    identity_map, identity_matches = _identity_map(
        snapshot.players,
        all_identities,
        load_inseason_identity_overrides(identity_override_path),
    )
    weekly_market_rows = tuple(
        mapped
        for dataset in inputs.weekly_rankings
        for row in dataset.observations
        if (mapped := _canonical_rank(row, identity_map, retain_unmatched_slot=True)) is not None
    )
    pool = load_expert_pool(
        expert_pool_path
        or default_inseason_expert_pool_path(league_key, snapshot.league.season)
    )
    weights = {member.expert_id: member.weight for member in pool}
    fresh_ros_ballots: tuple[RankObservation, ...] = ()
    selected_ros_complete = False
    market_ros_complete = False
    freshness_exclusions: tuple[BallotExclusion, ...] = ()
    if snapshot.manifest.current_week >= 2:
        updates = {
            (expert.expert_id, position): updated_at
            for expert in inputs.current_experts
            for position, updated_at in expert.position_updates
            if expert.expert_id in weights
        }
        raw_ballots = tuple(
            row
            for dataset in inputs.ros_rankings
            for row in dataset.contributor_observations
            if row.expert_id in weights and row.horizon.upper() == "ROS"
        )
        freshness = filter_ros_ballots(
            raw_ballots,
            updates,
            inputs.news,
            now=datetime.now(timezone.utc),
        )
        fresh_ros_ballots = freshness.eligible
        freshness_exclusions = freshness.exclusions
        contributor_counts = {
            position: len(
                {
                    str(row.expert_id)
                    for row in fresh_ros_ballots
                    if row.position == position
                }
            )
            for position in POSITION_MINIMUMS
        }
        selected_ros_complete = all(count >= 2 for count in contributor_counts.values())
        market_ros_complete = _ros_market_is_complete(inputs.ros_rankings)
    stage = choose_season_stage(
        snapshot.manifest.current_week,
        selected_ros_fresh=selected_ros_complete,
        selected_ros_complete=selected_ros_complete,
        market_ros_fresh=market_ros_complete,
        market_ros_complete=market_ros_complete,
    )
    if not stage.usable:
        raise CoverageIncomplete("; ".join(stage.reasons))

    resolved_anchor_path, resolved_anchor_updated_at = resolve_draft_anchor(
        league_key,
        snapshot.league.league_id,
        path=draft_anchor_path,
        updated_at=draft_anchor_updated_at,
    )
    draft_selected, draft_market = load_draft_anchor(
        resolved_anchor_path, updated_at=resolved_anchor_updated_at
    )
    known_ids = {player.player_id for player in snapshot.players}
    draft_selected = tuple(
        row
        if row.player_id in known_ids or row.player_id.startswith("fp:")
        else replace(row, player_id=f"fp:draft-sleeper-{row.player_id}")
        for row in draft_selected
    )
    draft_market = tuple(
        row
        if row.player_id in known_ids or row.player_id.startswith("fp:")
        else replace(row, player_id=f"fp:draft-sleeper-{row.player_id}")
        for row in draft_market
    )
    if stage.mode == "ROS":
        canonical_ros_rows = tuple(
            mapped
            for dataset in inputs.ros_rankings
            for row in dataset.observations
            if (
                mapped := _canonical_rank(
                    row,
                    identity_map,
                    retain_unmatched_slot=True,
                    horizon="ROS",
                )
            )
            is not None
        )
        market_rows = canonical_ros_rows
    else:
        canonical_ros_rows = tuple(
            mapped
            for dataset in inputs.ros_rankings
            for row in dataset.observations
            if (
                mapped := _canonical_rank(
                    row,
                    identity_map,
                    retain_unmatched_slot=True,
                    horizon="ROS",
                )
            )
            is not None
        )
        market_rows = draft_market
    required_market, positions, curve_positions, required_counts = _required_market_universe(
        refresh, market_rows
    )
    required_ids = set(curve_positions)
    if stage.mode == "ROS":
        contributor_rows = tuple(
            mapped
            for row in fresh_ros_ballots
            if (
                mapped := _canonical_rank(
                    row,
                    identity_map,
                    retain_unmatched_slot=True,
                    horizon="ROS",
                )
            )
            is not None
            and mapped.player_id in required_ids
        )
        selected_ranks = aggregate_selected_ranks(
            required_market,
            contributor_rows,
            weights,
            horizon="ROS",
        )
    else:
        selected_anchor_rows = tuple(
            row for row in draft_selected if row.player_id in required_ids
        )
        selected_ranks = _draft_selected_ranks(selected_anchor_rows, required_market)

    if snapshot.ranking_horizon != stage.mode:
        snapshot = retag_trade_snapshot(snapshot, stage.mode)
        snapshot_path = (
            Path("data/exports/trade")
            / league_key
            / snapshot.manifest.analysis_id
            / "snapshot.json"
        )
        save_trade_snapshot(snapshot, snapshot_path)
        refresh = RefreshResult(
            snapshot=snapshot,
            call_plan=refresh.call_plan,
            output_path=snapshot_path,
            schedule_path=refresh.schedule_path,
            schedule_captured_at=refresh.schedule_captured_at,
            schedule_fresh=refresh.schedule_fresh,
            schedule_age_seconds=refresh.schedule_age_seconds,
        )
    if refresh.schedule_path is None:
        raise ScheduleIncomplete("Trade refresh did not record the schedule artifact path")
    schedule = load_schedule(
        refresh.schedule_path, expected_season=snapshot.league.season
    )
    player_by_id = {player.player_id: player for player in snapshot.players}
    canonical_projections, distribution_positions, projection_warnings = _canonical_projections(
        inputs.projection_sets,
        identity_map,
        positions,
        dict(schedule.bye_weeks),
        player_by_id,
        ranking_positions,
    )
    weeks = tuple(week.week for week in snapshot.weeks)
    curves = _build_provider_projection_curves(
        canonical_projections,
        distribution_positions,
        required_counts=required_counts,
        expected_weeks=weeks,
    )
    raw_points = {
        player_id: sum(
            projection.league_points
            for projection in canonical_projections
            if projection.player_id == player_id
        )
        for player_id in positions
    }
    baselines = positional_waiver_baselines(
        (player_by_id[player_id] for player_id in positions),
        dict(snapshot.owner_by_player),
        raw_points,
        positions=POSITION_MINIMUMS,
        depth=1,
    )
    if set(baselines) != set(POSITION_MINIMUMS):
        raise CoverageIncomplete("Required universe lacks a free-agent replacement baseline")
    replacement = {position: baseline.points for position, baseline in baselines.items()}
    selected_final = build_value_board(
        board_id="selected_final",
        horizon=stage.mode,
        position_ranks={
            row.player_id: row.final_position_rank
            for row in selected_ranks
            if row.player_id in positions
        },
        positions=positions,
        curves=curves,
        replacement_baselines=replacement,
        player_warnings=projection_warnings,
        stamps=tuple(
            dataset.stamp
            for dataset in (
                *inputs.weekly_rankings,
                *inputs.ros_rankings,
                *inputs.projection_sets,
            )
        ),
    )
    selected_raw = build_value_board(
        board_id="selected_raw",
        horizon=stage.mode,
        position_ranks={
            player_id: rank
            for player_id, rank in _raw_rank_ordinals(selected_ranks).items()
            if player_id in positions
        },
        positions=positions,
        curves=curves,
        replacement_baselines=replacement,
        player_warnings=projection_warnings,
        stamps=tuple(
            dataset.stamp
            for dataset in (
                *inputs.weekly_rankings,
                *inputs.ros_rankings,
                *inputs.projection_sets,
            )
        ),
    )
    market = build_value_board(
        board_id="market",
        horizon=stage.mode,
        position_ranks={
            row.player_id: int(row.position_rank or 0)
            for row in required_market
            if row.player_id in positions
        },
        positions=positions,
        curves=curves,
        replacement_baselines=replacement,
        player_warnings=projection_warnings,
        stamps=tuple(
            dataset.stamp
            for dataset in (
                *inputs.weekly_rankings,
                *inputs.ros_rankings,
                *inputs.projection_sets,
            )
        ),
    )
    gaps = valuation_gaps(selected_final, market)
    weekly_by_id = {
        row.player_id: row
        for row in weekly_market_rows
        if row.player_id in positions
    }
    current_projection = {
        row.player_id: row
        for row in canonical_projections
        if row.week == snapshot.manifest.current_week and row.player_id in positions
    }
    bye_by_team = dict(schedule.bye_weeks)
    long_term_updated_at = (
        max(dataset.stamp.captured_at for dataset in inputs.ros_rankings).isoformat()
        if stage.mode == "ROS" and inputs.ros_rankings
        else resolved_anchor_updated_at
    )
    freshness_warnings: dict[str, tuple[str, ...]] = {}
    for player_id in sorted(
        {
            row.player_id
            for row in freshness_exclusions
            if row.player_id is not None
        }
    ):
        conflicts = tuple(
            sorted(
                f"Selected ROS ballot {row.expert_id}/{row.position} invalidated: newer material news"
                for row in freshness_exclusions
                if row.player_id == player_id
            )
        )
        freshness_warnings[player_id] = conflicts
    horizon_views = compose_horizon_views(
        tuple(
            LongTermPlayer(
                player_id=row.player_id,
                position=row.position,
                position_rank=row.position_rank,
                value=row.reconciled_vorp,
                source=stage.selected_source,
                updated_at=long_term_updated_at,
            )
            for row in selected_final.players
        ),
        tuple(
            WeeklyPlayerSignal(
                player_id=player_id,
                position=position,
                week=snapshot.manifest.current_week,
                position_rank=(
                    int(weekly_by_id[player_id].position_rank or 0)
                    if player_id in weekly_by_id
                    else None
                ),
                projected_points=(
                    current_projection[player_id].league_points
                    if player_id in current_projection
                    else None
                ),
                matchup_adjustment=0.0,
                source="FantasyPros current-week ECR and league-scored projection",
                updated_at=max(
                    (
                        dataset.stamp.captured_at.isoformat()
                        for dataset in (
                            *inputs.weekly_rankings,
                            *(
                                dataset
                                for dataset in inputs.projection_sets
                                if dataset.week == snapshot.manifest.current_week
                            ),
                        )
                    ),
                    default=snapshot.captured_at.isoformat(),
                ),
                bye=bye_by_team.get(str(player_by_id[player_id].nfl_team))
                == snapshot.manifest.current_week,
                warnings=(
                    *projection_warnings.get(player_id, ()),
                    *freshness_warnings.get(player_id, ()),
                ),
            )
            for player_id, position in positions.items()
        ),
    )
    target = Path(
        output_path
        or Path("data/exports/trade")
        / league_key
        / snapshot.manifest.analysis_id
        / "value_boards.json"
    )
    prospective_target = target.with_name("prospective_horizon_snapshot.json")
    prospective_data: list[SnapshotDatum] = []
    for row in horizon_views:
        prospective_data.extend(
            (
                SnapshotDatum(
                    kind="long_term_rank",
                    player_id=row.player_id,
                    position=row.position,
                    value=row.long_term_rank,
                    source=row.long_term_source,
                    published_at=row.long_term_updated_at,
                ),
                SnapshotDatum(
                    kind="long_term_value",
                    player_id=row.player_id,
                    position=row.position,
                    value=row.long_term_value,
                    source=row.long_term_source,
                    published_at=row.long_term_updated_at,
                ),
            )
        )
        if row.current_updated_at is not None:
            prospective_data.extend(
                (
                    SnapshotDatum(
                        kind="current_rank",
                        player_id=row.player_id,
                        position=row.position,
                        value=row.current_rank,
                        source=row.current_source or "CURRENT_SIGNAL",
                        published_at=row.current_updated_at,
                    ),
                    SnapshotDatum(
                        kind="current_adjusted_points",
                        player_id=row.player_id,
                        position=row.position,
                        value=row.current_adjusted_points,
                        source=row.current_source or "CURRENT_SIGNAL",
                        published_at=row.current_updated_at,
                    ),
                )
            )
    capture_prospective_snapshot(
        prospective_target,
        season=snapshot.league.season,
        week=snapshot.manifest.current_week,
        cutoff=datetime.now(timezone.utc),
        mode=stage.mode,
        data=tuple(prospective_data),
    )
    export_board_evidence(
        target,
        selected_ranks=selected_ranks,
        selected_raw=selected_raw,
        selected=selected_final,
        market=market,
        gaps=gaps,
        manifest_id=snapshot.manifest.analysis_id,
        warnings=(
            f"{stage.mode} owns long-term value; CURRENT_SIGNAL remains separate",
            "CURRENT_SIGNAL weekly ranks/projections remain separate and do not change ownership value",
            "Valuation gaps are signals, not trade recommendations or opponent preferences",
        ),
        additional_evidence={
            "season_stage": asdict(stage),
            "horizon_views": [asdict(row) for row in horizon_views],
            "ballot_freshness_exclusions": [
                asdict(row) for row in freshness_exclusions
            ],
            "scoring_capability": asdict(scoring_capability),
            "draft_anchor": {
                "league_key": league_key,
                "league_id": snapshot.league.league_id,
                "path": str(resolved_anchor_path),
                "updated_at": resolved_anchor_updated_at,
            },
            "blend_enabled": False,
        },
    )
    return BoardRefreshResult(
        refresh=refresh,
        selected_raw=selected_raw,
        selected_final=selected_final,
        market=market,
        selected_ranks=selected_ranks,
        gaps=gaps,
        call_plan=inputs.call_plan,
        output_path=target,
        identity_matches=identity_matches,
        required_players=len(positions),
        stage=stage,
        horizon_views=horizon_views,
        prospective_snapshot_path=prospective_target,
        weekly_projections=canonical_projections,
        weekly_rankings=weekly_market_rows,
        ros_rankings=canonical_ros_rows,
        expert_pool=pool,
    )


def board_refresh_report(result: BoardRefreshResult) -> dict[str, Any]:
    largest = sorted(result.gaps, key=lambda row: (-abs(row.value_gap), row.player_id))[:10]
    player_by_id = {
        player.player_id: player for player in result.refresh.snapshot.players
    }
    owner_by_player = dict(result.refresh.snapshot.owner_by_player)
    return {
        "product": "TRADE ASSISTANT",
        "operation": "VALUE BOARD REFRESH",
        "league": result.refresh.snapshot.league_key,
        "horizon": result.selected_final.horizon,
        "season_stage": asdict(result.stage),
        "current_signal_players": len(result.horizon_views),
        "blend_enabled": False,
        "prospective_snapshot_path": str(result.prospective_snapshot_path),
        "selected_board": result.selected_final.board_id,
        "market_board": result.market.board_id,
        "boards_complete": result.selected_final.complete and result.market.complete,
        "required_players": result.required_players,
        "identity_matches": result.identity_matches,
        "selected_experts": [
            {"expert_id": member.expert_id, "name": member.expert_name, "weight": member.weight}
            for member in getattr(result, "expert_pool", ())
        ],
        "call_plan": {
            "total": len(result.call_plan.calls),
            "fantasypros_calls": result.call_plan.fantasypros_calls,
            "cache_hits": result.call_plan.cache_hits,
            "fantasypros_remaining_after_plan": result.call_plan.fantasypros_remaining_after_plan,
        },
        "largest_absolute_gaps": [
            {
                "player_id": row.player_id,
                "player_name": player_by_id[row.player_id].name,
                "nfl_team": player_by_id[row.player_id].nfl_team,
                "fantasy_roster_id": owner_by_player.get(row.player_id),
                "signal": row.signal,
                "value_gap": round(row.value_gap, 3),
                "rank_gap": row.rank_gap,
            }
            for row in largest
        ],
        "sign_convention": "positive value_gap = market above selected (possible sell-high); negative = selected above market (possible buy-low)",
        "recommendation_generated": False,
        "opponent_preference_claimed": False,
        "sleeper_write_performed": False,
        "output_path": str(result.output_path),
    }
