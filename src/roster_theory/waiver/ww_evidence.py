from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from roster_theory.core.call_plan import CallPlan, PlannedCall, build_call_plan
from roster_theory.core.errors import CoverageIncomplete
from roster_theory.core.models import Player, RankObservation
from roster_theory.core.provenance import DataStamp, stable_hash
from roster_theory.fantasypros import FantasyProsClient
from roster_theory.providers.cache import (
    DailyRequestBudget,
    atomic_write_json,
    cache_key,
    is_fresh,
)
from roster_theory.providers.fantasypros import (
    FantasyProsIdentity,
    RankingDataset,
    normalize_rankings,
)


DEFAULT_WAIVER_CONFIG_DIR = Path("config/waiver")
_SAFE_LEAGUE_KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*")


@dataclass(frozen=True, slots=True)
class WaiverWireConfig:
    league_key: str
    scoring: str
    position: str
    maximum_age_hours: float
    trusted_expert_ids: tuple[str, ...]
    config_hash: str


@dataclass(frozen=True, slots=True)
class WaiverWireExpertRank:
    expert_id: str
    overall_rank: float | None
    position_rank: float | None
    updated_at: str | None


@dataclass(frozen=True, slots=True)
class WaiverWirePlayerEvidence:
    player_id: str
    fantasypros_id: str
    match_status: str
    position: str
    market_overall_rank: float | None
    market_position_rank: float | None
    market_rank_min: float | None
    market_rank_max: float | None
    market_rank_std: float | None
    selected_expert_ranks: tuple[WaiverWireExpertRank, ...]


@dataclass(frozen=True, slots=True)
class WaiverWireEvidence:
    schema_version: int
    product: str
    league_key: str
    horizon: str
    raw_market_horizon: str
    scoring: str
    week: int | None
    captured_at: datetime
    provider_updated_at: str | None
    maximum_age_hours: float
    market_complete: bool
    selected_experts_complete: bool
    complete: bool
    trusted_expert_ids: tuple[str, ...]
    contributor_ids: tuple[str, ...]
    players: tuple[WaiverWirePlayerEvidence, ...]
    unmatched_fantasypros_ids: tuple[str, ...]
    ambiguous_fantasypros_ids: tuple[str, ...]
    missing_trusted_expert_ids: tuple[str, ...]
    stamps: tuple[DataStamp, ...]
    warnings: tuple[str, ...]
    config_hash: str
    evidence_hash: str


@dataclass(frozen=True, slots=True)
class WaiverWireRefreshResult:
    evidence: WaiverWireEvidence
    call_plan: CallPlan
    output_path: Path


def _stamp_from_json(value: Mapping[str, Any]) -> DataStamp:
    return DataStamp(
        source=str(value["source"]),
        endpoint=str(value["endpoint"]),
        captured_at=datetime.fromisoformat(str(value["captured_at"])),
        season=int(value["season"]) if value.get("season") is not None else None,
        week=int(value["week"]) if value.get("week") is not None else None,
        horizon_start=(
            int(value["horizon_start"])
            if value.get("horizon_start") is not None
            else None
        ),
        horizon_end=(
            int(value["horizon_end"])
            if value.get("horizon_end") is not None
            else None
        ),
        scoring_label=(
            str(value["scoring_label"])
            if value.get("scoring_label") is not None
            else None
        ),
        scoring_hash=(
            str(value["scoring_hash"])
            if value.get("scoring_hash") is not None
            else None
        ),
        parameter_hash=(
            str(value["parameter_hash"])
            if value.get("parameter_hash") is not None
            else None
        ),
        payload_hash=(
            str(value["payload_hash"])
            if value.get("payload_hash") is not None
            else None
        ),
        cache_status=str(value.get("cache_status") or "miss"),
        freshness_seconds=(
            int(value["freshness_seconds"])
            if value.get("freshness_seconds") is not None
            else None
        ),
        fresh=value.get("fresh") if isinstance(value.get("fresh"), bool) else None,
        export_restriction=(
            str(value["export_restriction"])
            if value.get("export_restriction") is not None
            else None
        ),
        warnings=tuple(str(item) for item in value.get("warnings") or ()),
    )


def waiver_wire_evidence_from_json(value: Mapping[str, Any]) -> WaiverWireEvidence:
    if int(value.get("schema_version") or 0) != 1:
        raise ValueError("Unsupported Waiver Wire evidence schema")
    if str(value.get("product") or "") != "WAIVER ASSISTANT":
        raise ValueError("Waiver Wire evidence must be Waiver-scoped")
    expected = str(value.get("evidence_hash") or "")
    unsigned = dict(value)
    unsigned["evidence_hash"] = ""
    if not expected or stable_hash(unsigned) != expected:
        raise ValueError("Waiver Wire evidence failed hash verification")
    captured_at = datetime.fromisoformat(str(value["captured_at"]))
    if captured_at.tzinfo is None:
        raise ValueError("Waiver Wire evidence timestamp must be timezone-aware")
    players = tuple(
        WaiverWirePlayerEvidence(
            player_id=str(row["player_id"]),
            fantasypros_id=str(row["fantasypros_id"]),
            match_status=str(row.get("match_status") or "UNKNOWN"),
            position=str(row.get("position") or ""),
            market_overall_rank=(
                float(row["market_overall_rank"])
                if row.get("market_overall_rank") is not None
                else None
            ),
            market_position_rank=(
                float(row["market_position_rank"])
                if row.get("market_position_rank") is not None
                else None
            ),
            market_rank_min=(
                float(row["market_rank_min"])
                if row.get("market_rank_min") is not None
                else None
            ),
            market_rank_max=(
                float(row["market_rank_max"])
                if row.get("market_rank_max") is not None
                else None
            ),
            market_rank_std=(
                float(row["market_rank_std"])
                if row.get("market_rank_std") is not None
                else None
            ),
            selected_expert_ranks=tuple(
                WaiverWireExpertRank(
                    expert_id=str(expert["expert_id"]),
                    overall_rank=(
                        float(expert["overall_rank"])
                        if expert.get("overall_rank") is not None
                        else None
                    ),
                    position_rank=(
                        float(expert["position_rank"])
                        if expert.get("position_rank") is not None
                        else None
                    ),
                    updated_at=(
                        str(expert["updated_at"])
                        if expert.get("updated_at") is not None
                        else None
                    ),
                )
                for expert in row.get("selected_expert_ranks") or ()
            ),
        )
        for row in value.get("players") or ()
    )
    return WaiverWireEvidence(
        schema_version=1,
        product="WAIVER ASSISTANT",
        league_key=str(value["league_key"]),
        horizon=str(value["horizon"]),
        raw_market_horizon=str(value.get("raw_market_horizon") or ""),
        scoring=str(value.get("scoring") or ""),
        week=int(value["week"]) if value.get("week") is not None else None,
        captured_at=captured_at.astimezone(timezone.utc),
        provider_updated_at=(
            str(value["provider_updated_at"])
            if value.get("provider_updated_at") is not None
            else None
        ),
        maximum_age_hours=float(value["maximum_age_hours"]),
        market_complete=bool(value.get("market_complete")),
        selected_experts_complete=bool(value.get("selected_experts_complete")),
        complete=bool(value.get("complete")),
        trusted_expert_ids=tuple(
            str(item) for item in value.get("trusted_expert_ids") or ()
        ),
        contributor_ids=tuple(
            str(item) for item in value.get("contributor_ids") or ()
        ),
        players=players,
        unmatched_fantasypros_ids=tuple(
            str(item) for item in value.get("unmatched_fantasypros_ids") or ()
        ),
        ambiguous_fantasypros_ids=tuple(
            str(item) for item in value.get("ambiguous_fantasypros_ids") or ()
        ),
        missing_trusted_expert_ids=tuple(
            str(item) for item in value.get("missing_trusted_expert_ids") or ()
        ),
        stamps=tuple(_stamp_from_json(row) for row in value.get("stamps") or ()),
        warnings=tuple(str(item) for item in value.get("warnings") or ()),
        config_hash=str(value.get("config_hash") or ""),
        evidence_hash=expected,
    )


def load_waiver_wire_evidence(path: str | Path) -> WaiverWireEvidence:
    return waiver_wire_evidence_from_json(
        json.loads(Path(path).read_text(encoding="utf-8"))
    )


def default_waiver_wire_config_path(
    league_key: str,
    *,
    config_dir: str | Path = DEFAULT_WAIVER_CONFIG_DIR,
) -> Path:
    if not _SAFE_LEAGUE_KEY.fullmatch(league_key):
        raise ValueError(f"Invalid Waiver league key: {league_key!r}")
    return Path(config_dir) / f"{league_key}.ww-evidence.json"


def load_waiver_wire_config(path: str | Path, *, league_key: str) -> WaiverWireConfig:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if int(value.get("schema_version") or 0) != 1:
        raise ValueError("Unsupported Waiver Wire evidence config schema")
    if str(value.get("product") or "") != "WAIVER ASSISTANT":
        raise ValueError("Waiver Wire evidence config must be Waiver-scoped")
    configured_league = str(value.get("league_key") or "")
    if configured_league != league_key:
        raise ValueError(
            f"Waiver Wire evidence config is for {configured_league or 'no league'}, "
            f"not {league_key}"
        )
    scoring = str(value.get("scoring") or "").upper()
    if scoring not in {"STD", "HALF", "PPR"}:
        raise ValueError("Waiver Wire evidence scoring must be STD, HALF, or PPR")
    position = str(value.get("position") or "ALL").upper()
    maximum_age_hours = float(value.get("maximum_age_hours") or 0.0)
    if maximum_age_hours <= 0:
        raise ValueError("Waiver Wire evidence maximum age must be positive")
    trusted = tuple(str(item).strip() for item in value.get("trusted_expert_ids") or ())
    if any(not item for item in trusted) or len(set(trusted)) != len(trusted):
        raise ValueError("Waiver Wire trusted expert IDs must be non-empty and unique")
    return WaiverWireConfig(
        league_key=league_key,
        scoring=scoring,
        position=position,
        maximum_age_hours=maximum_age_hours,
        trusted_expert_ids=trusted,
        config_hash=stable_hash(value),
    )


def _provider_updated_at(value: str | None, captured_at: datetime) -> datetime | None:
    if not value:
        return None
    raw = value.strip()
    normalized = raw.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        parsed = None
    if parsed is None:
        for pattern in (
            "%Y-%m-%d %H:%M:%S",
            "%m/%d/%Y %H:%M:%S",
            "%m/%d/%Y",
            "%m/%d/%y",
            "%m/%d",
        ):
            try:
                parsed = datetime.strptime(raw, pattern)
                if pattern == "%m/%d":
                    parsed = parsed.replace(year=captured_at.year)
                break
            except ValueError:
                continue
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _identity_map(
    players: Sequence[Player],
    identities: Sequence[FantasyProsIdentity],
) -> tuple[dict[str, str], set[str]]:
    result: dict[str, str] = {}
    ambiguous: set[str] = set()
    players_by_external: dict[tuple[str, str], set[str]] = {}
    players_by_name: dict[str, list[Player]] = {}
    for player in players:
        players_by_name.setdefault(player.name.strip().casefold(), []).append(player)
        for key, value in player.external_ids:
            players_by_external.setdefault((key.casefold(), str(value)), set()).add(
                player.player_id
            )
        if not player.fantasypros_id:
            continue
        fantasypros_id = str(player.fantasypros_id).removeprefix("fp:")
        existing = result.get(fantasypros_id)
        if existing is not None and existing != player.player_id:
            raise CoverageIncomplete(
                f"FantasyPros identity maps to multiple players: {fantasypros_id}"
            )
        result[fantasypros_id] = player.player_id
    for identity in identities:
        fantasypros_id = identity.fantasypros_id
        if fantasypros_id in result:
            continue
        external_candidates: set[str] = set()
        for key, value in identity.external_ids:
            external_candidates.update(
                players_by_external.get((key.casefold(), str(value)), set())
            )
        if len(external_candidates) == 1:
            result[fantasypros_id] = next(iter(external_candidates))
            continue
        if len(external_candidates) > 1:
            ambiguous.add(fantasypros_id)
            continue
        name_candidates = [
            player
            for player in players_by_name.get(identity.name.strip().casefold(), ())
            if (not identity.nfl_team or player.nfl_team == identity.nfl_team)
            and identity.position in player.positions
        ]
        if len(name_candidates) == 1:
            result[fantasypros_id] = name_candidates[0].player_id
        elif len(name_candidates) > 1:
            ambiguous.add(fantasypros_id)
    if len(set(result.values())) != len(result):
        duplicates = {
            player_id
            for player_id in result.values()
            if sum(value == player_id for value in result.values()) > 1
        }
        for fantasypros_id, player_id in tuple(result.items()):
            if player_id in duplicates:
                ambiguous.add(fantasypros_id)
                del result[fantasypros_id]
    return result, ambiguous


def _unique_observations(
    observations: Sequence[RankObservation], *, label: str
) -> dict[str, RankObservation]:
    result: dict[str, RankObservation] = {}
    for observation in observations:
        if observation.player_id in result:
            raise CoverageIncomplete(
                f"Duplicate {label} Waiver observation: {observation.player_id}"
            )
        result[observation.player_id] = observation
    return result


def build_waiver_wire_evidence(
    *,
    config: WaiverWireConfig,
    players: Sequence[Player],
    market: RankingDataset,
    selected: Mapping[str, RankingDataset],
    now: datetime | None = None,
) -> WaiverWireEvidence:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("Waiver Wire evidence time must be timezone-aware")
    if market.horizon != "WAIVER" or not market.complete_horizon:
        raise CoverageIncomplete(
            f"FantasyPros market Waiver horizon is incomplete: {market.raw_horizon or 'missing'}"
        )
    unexpected = tuple(sorted(set(selected) - set(config.trusted_expert_ids)))
    if unexpected:
        raise CoverageIncomplete(
            "Unconfigured Waiver expert evidence supplied: " + ", ".join(unexpected)
        )
    identity_map, ambiguous = _identity_map(players, market.identities)
    market_by_fp = _unique_observations(market.observations, label="market")
    selected_by_expert: dict[str, dict[str, RankObservation]] = {}
    for expert_id, dataset in selected.items():
        if dataset.horizon != "WAIVER" or not dataset.complete_horizon:
            raise CoverageIncomplete(
                f"FantasyPros selected expert {expert_id} Waiver horizon is incomplete: "
                f"{dataset.raw_horizon or 'missing'}"
            )
        selected_by_expert[expert_id] = _unique_observations(
            dataset.observations, label=f"expert {expert_id}"
        )

    missing_experts = tuple(
        expert_id
        for expert_id in config.trusted_expert_ids
        if expert_id not in selected_by_expert
    )
    captured_fresh = is_fresh(
        market.stamp.captured_at,
        timedelta(hours=config.maximum_age_hours),
        now=current,
    )
    provider_time = _provider_updated_at(market.updated_at, market.stamp.captured_at)
    provider_fresh = provider_time is not None and is_fresh(
        provider_time,
        timedelta(hours=config.maximum_age_hours),
        now=current,
    )
    scoring_matches = str(market.scoring or "").upper() == config.scoring
    selected_fresh_by_expert = {
        expert_id: (
            is_fresh(
                dataset.stamp.captured_at,
                timedelta(hours=config.maximum_age_hours),
                now=current,
            )
            and (
                (
                    updated := _provider_updated_at(
                        dataset.updated_at, dataset.stamp.captured_at
                    )
                )
                is not None
                and is_fresh(
                    updated,
                    timedelta(hours=config.maximum_age_hours),
                    now=current,
                )
            )
            and str(dataset.scoring or "").upper() == config.scoring
            and bool(dataset.observations)
        )
        for expert_id, dataset in selected.items()
    }
    selected_fresh = all(selected_fresh_by_expert.values())

    evidence_rows: list[WaiverWirePlayerEvidence] = []
    unmatched: list[str] = []
    for fantasypros_id, observation in market_by_fp.items():
        player_id = identity_map.get(fantasypros_id)
        if player_id is None and fantasypros_id not in ambiguous:
            unmatched.append(fantasypros_id)
            player_id = f"fp:{fantasypros_id}"
        elif player_id is None:
            player_id = f"fp:{fantasypros_id}"
        expert_rows = tuple(
            WaiverWireExpertRank(
                expert_id=expert_id,
                overall_rank=expert_observation.overall_rank,
                position_rank=expert_observation.position_rank,
                updated_at=expert_observation.updated_at,
            )
            for expert_id in config.trusted_expert_ids
            if (
                expert_observation := selected_by_expert.get(expert_id, {}).get(
                    fantasypros_id
                )
            )
            is not None
        )
        evidence_rows.append(
            WaiverWirePlayerEvidence(
                player_id=player_id,
                fantasypros_id=fantasypros_id,
                match_status=(
                    "MATCHED"
                    if fantasypros_id in identity_map
                    else "AMBIGUOUS"
                    if fantasypros_id in ambiguous
                    else "UNMATCHED"
                ),
                position=observation.position,
                market_overall_rank=observation.overall_rank,
                market_position_rank=observation.position_rank,
                market_rank_min=observation.rank_min,
                market_rank_max=observation.rank_max,
                market_rank_std=observation.rank_std,
                selected_expert_ranks=expert_rows,
            )
        )

    selected_complete = not missing_experts and selected_fresh
    warnings: list[str] = []
    if not captured_fresh:
        warnings.append("FantasyPros Waiver market capture is stale")
    if not market.observations:
        warnings.append("FantasyPros Waiver market returned no ranked players")
    if not scoring_matches:
        warnings.append(
            "FantasyPros Waiver market scoring does not match Waiver configuration"
        )
    if provider_time is None:
        warnings.append("FantasyPros Waiver market update time is missing or unparseable")
    elif not provider_fresh:
        warnings.append("FantasyPros Waiver market update is stale")
    if missing_experts:
        warnings.append(
            "Configured Waiver experts are missing: " + ", ".join(missing_experts)
        )
    if selected and not selected_fresh:
        warnings.append(
            "One or more selected-expert Waiver datasets are stale, empty, or use the wrong scoring"
        )
    if unmatched:
        warnings.append(
            f"{len(unmatched)} FantasyPros Waiver player(s) are unmatched"
        )
    if ambiguous:
        warnings.append(
            f"{len(ambiguous)} FantasyPros Waiver player identity match(es) are ambiguous"
        )
    complete = (
        captured_fresh
        and provider_fresh
        and scoring_matches
        and bool(market.observations)
        and selected_complete
        and not unmatched
        and not ambiguous
    )
    market_stamp_fresh = captured_fresh and provider_fresh
    stamps = (
        replace(
            market.stamp,
            freshness_seconds=max(
                0,
                int(
                    (
                        current
                        - min(
                            market.stamp.captured_at.astimezone(timezone.utc),
                            provider_time or market.stamp.captured_at.astimezone(timezone.utc),
                        )
                    ).total_seconds()
                ),
            ),
            fresh=market_stamp_fresh,
        ),
    ) + tuple(
        replace(
            selected[expert_id].stamp,
            freshness_seconds=max(
                0,
                int(
                    (
                        current
                        - min(
                            selected[expert_id].stamp.captured_at.astimezone(timezone.utc),
                            _provider_updated_at(
                                selected[expert_id].updated_at,
                                selected[expert_id].stamp.captured_at,
                            )
                            or selected[expert_id].stamp.captured_at.astimezone(timezone.utc),
                        )
                    ).total_seconds()
                ),
            ),
            fresh=selected_fresh_by_expert.get(expert_id, False),
        )
        for expert_id in config.trusted_expert_ids
        if expert_id in selected
    )
    base = WaiverWireEvidence(
        schema_version=1,
        product="WAIVER ASSISTANT",
        league_key=config.league_key,
        horizon="WAIVER",
        raw_market_horizon=market.raw_horizon,
        scoring=market.scoring or config.scoring,
        week=market.week,
        captured_at=market.stamp.captured_at.astimezone(timezone.utc),
        provider_updated_at=market.updated_at,
        maximum_age_hours=config.maximum_age_hours,
        market_complete=(
            captured_fresh
            and provider_fresh
            and scoring_matches
            and bool(market.observations)
        ),
        selected_experts_complete=selected_complete,
        complete=complete,
        trusted_expert_ids=config.trusted_expert_ids,
        contributor_ids=market.contributor_ids,
        players=tuple(sorted(evidence_rows, key=lambda row: (row.player_id, row.fantasypros_id))),
        unmatched_fantasypros_ids=tuple(sorted(unmatched)),
        ambiguous_fantasypros_ids=tuple(sorted(ambiguous)),
        missing_trusted_expert_ids=missing_experts,
        stamps=stamps,
        warnings=tuple(warnings),
        config_hash=config.config_hash,
        evidence_hash="",
    )
    return replace(base, evidence_hash=stable_hash(asdict(base)))


def _load_budget(path: Path) -> DailyRequestBudget:
    if not path.exists():
        return DailyRequestBudget()
    return DailyRequestBudget.from_json(json.loads(path.read_text(encoding="utf-8")))


def _cache_record(path: Path, *, maximum_age: timedelta, now: datetime):
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        captured_at = datetime.fromisoformat(str(value["captured_at"]))
        if not is_fresh(captured_at, maximum_age, now=now):
            return None
        if not isinstance(value.get("payload"), dict):
            return None
        return value
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


def refresh_waiver_wire_evidence(
    *,
    config: WaiverWireConfig,
    season: int,
    week: int,
    players: Sequence[Player],
    client: FantasyProsClient | None = None,
    cache_dir: str | Path = "data/cache/waiver/fantasypros/ww",
    budget_path: str | Path = "data/cache/trade/fantasypros/daily_budget.json",
    output_path: str | Path | None = None,
    now: datetime | None = None,
    minimum_interval: float = 1.05,
) -> WaiverWireRefreshResult:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("Waiver Wire refresh time must be timezone-aware")
    provider = client or FantasyProsClient()
    root = Path(cache_dir)
    maximum_age = timedelta(hours=config.maximum_age_hours)
    definitions = [("market", None)] + [
        (f"expert_{expert_id}", expert_id)
        for expert_id in config.trusted_expert_ids
    ]
    records: dict[str, dict] = {}
    cache_paths: dict[str, Path] = {}
    calls: list[PlannedCall] = []
    parameters_by_name: dict[str, dict[str, object]] = {}
    for name, expert_id in definitions:
        parameters: dict[str, object] = {
            "position": config.position,
            "scoring": config.scoring,
            "type": "WW",
            "week": week,
        }
        if expert_id is None:
            parameters["experts"] = "show"
        else:
            parameters["filters"] = f"{expert_id}:{expert_id}"
        parameters_by_name[name] = parameters
        cache_path = root / (
            f"{name}_{cache_key(f'/nfl/{season}/consensus-rankings', parameters)}.json"
        )
        cache_paths[name] = cache_path
        cached = _cache_record(cache_path, maximum_age=maximum_age, now=current)
        if cached is not None:
            records[name] = cached
        calls.append(
            PlannedCall(
                name=f"waiver_wire_{name}",
                provider="FantasyPros",
                endpoint=f"/nfl/{season}/consensus-rankings",
                parameters=tuple(sorted(parameters.items())),
                fresh_cache_hit=cached is not None,
            )
        )

    budget_target = Path(budget_path)
    budget = _load_budget(budget_target)
    plan = build_call_plan(calls, budget)
    if plan.fantasypros_calls:
        budget.reserve(plan.fantasypros_calls)
        atomic_write_json(budget_target, budget.to_json())
    last_request = time.monotonic()
    for name, _expert_id in definitions:
        if name in records:
            continue
        elapsed = time.monotonic() - last_request
        if elapsed < minimum_interval:
            time.sleep(minimum_interval - elapsed)
        payload = provider.consensus_rankings(season, **parameters_by_name[name])
        captured_at = current.astimezone(timezone.utc)
        record = {"captured_at": captured_at.isoformat(), "payload": payload}
        atomic_write_json(cache_paths[name], record)
        records[name] = record
        last_request = time.monotonic()

    datasets: dict[str, RankingDataset] = {}
    for name, expert_id in definitions:
        record = records[name]
        dataset = normalize_rankings(
            record["payload"],
            requested_horizon="WAIVER",
            board_source="market" if expert_id is None else "selected",
            expert_id=expert_id,
            captured_at=datetime.fromisoformat(str(record["captured_at"])),
            endpoint=f"/nfl/{season}/consensus-rankings",
            parameters=parameters_by_name[name],
        )
        if not dataset.complete_horizon:
            raise CoverageIncomplete(
                f"FantasyPros returned {dataset.raw_horizon or 'no horizon'} for "
                f"Waiver request {name}; fallback={dataset.fallback_for or 'none'}"
            )
        cache_status = "hit" if any(
            call.name == f"waiver_wire_{name}" and call.fresh_cache_hit
            for call in plan.calls
        ) else "miss"
        datasets[name] = replace(
            dataset,
            stamp=replace(dataset.stamp, cache_status=cache_status),
        )

    evidence = build_waiver_wire_evidence(
        config=config,
        players=players,
        market=datasets["market"],
        selected={
            expert_id: datasets[f"expert_{expert_id}"]
            for expert_id in config.trusted_expert_ids
        },
        now=current,
    )
    target = Path(
        output_path
        or root / f"{config.league_key}_waiver_wire_evidence.json"
    )
    atomic_write_json(target, evidence)
    return WaiverWireRefreshResult(evidence=evidence, call_plan=plan, output_path=target)
