from __future__ import annotations

import json
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

from roster_theory.core.errors import IdentityIncomplete, StaleData
from roster_theory.core.models import FantasyTeam, LeagueRules, Player
from roster_theory.core.provenance import AnalysisManifest, DataStamp, stable_hash
from roster_theory.providers.cache import atomic_write_json, is_fresh
from roster_theory.providers.sleeper import SleeperBundle
from roster_theory.trade.schedule import EvaluationWeek, ScheduleConfig, build_evaluation_weeks


SKILL_POSITIONS = frozenset({"QB", "RB", "WR", "TE"})


@dataclass(frozen=True, slots=True)
class SnapshotCompleteness:
    league_complete: bool
    ownership_complete: bool
    user_resolved: bool
    identity_complete: bool
    schedule_complete: bool
    valuation_inputs_complete: bool

    @property
    def snapshot_complete(self) -> bool:
        return all(
            (
                self.league_complete,
                self.ownership_complete,
                self.user_resolved,
                self.identity_complete,
                self.schedule_complete,
            )
        )


@dataclass(frozen=True, slots=True)
class TradeSnapshot:
    schema_version: int
    product: str
    league_key: str
    captured_at: datetime
    ranking_horizon: str
    current: bool
    league: LeagueRules
    user_roster_id: str
    teams: tuple[FantasyTeam, ...]
    players: tuple[Player, ...]
    weeks: tuple[EvaluationWeek, ...]
    owner_by_player: tuple[tuple[str, str], ...]
    free_agent_ids: tuple[str, ...]
    tradeable_player_ids: tuple[str, ...]
    transaction_ids: tuple[str, ...]
    stamps: tuple[DataStamp, ...]
    capabilities: tuple[tuple[str, bool], ...]
    completeness: SnapshotCompleteness
    warnings: tuple[str, ...]
    manifest: AnalysisManifest


def retag_trade_snapshot(snapshot: TradeSnapshot, ranking_horizon: str) -> TradeSnapshot:
    """Rebuild manifest identity after the joint horizon gate resolves."""
    if ranking_horizon not in {
        "WEEKLY-PROXY",
        "ROS",
        "EARLY_SEASON_DRAFT_ANCHOR",
    }:
        raise ValueError("Unsupported Trade ranking horizon")
    if ranking_horizon == snapshot.ranking_horizon:
        return snapshot
    normalized_inputs = {
        "league": snapshot.league,
        "teams": snapshot.teams,
        "players": snapshot.players,
        "weeks": snapshot.weeks,
        "owner_by_player": snapshot.owner_by_player,
        "ranking_horizon": ranking_horizon,
    }
    manifest = AnalysisManifest.build(
        league_id=snapshot.manifest.league_id,
        user_id=snapshot.manifest.user_id,
        current_week=snapshot.manifest.current_week,
        horizon_start=snapshot.manifest.horizon_start,
        horizon_end=snapshot.manifest.horizon_end,
        configuration={
            "prior_configuration_hash": snapshot.manifest.configuration_hash,
            "ranking_horizon": ranking_horizon,
        },
        normalized_inputs=normalized_inputs,
        data_stamps=snapshot.manifest.data_stamps,
        coverage_checks=snapshot.manifest.coverage_checks,
        warnings=snapshot.manifest.warnings,
        input_hashes=snapshot.manifest.input_hashes,
    )
    return replace(snapshot, ranking_horizon=ranking_horizon, manifest=manifest)


def _state(bundle: SleeperBundle) -> dict[str, Any]:
    return dict(bundle.state)


def build_trade_snapshot(
    *,
    league_key: str,
    user_id: str,
    ranking_horizon: str,
    sleeper: SleeperBundle,
    schedule: ScheduleConfig,
    valuation_inputs_complete: bool = False,
    warnings: tuple[str, ...] = (),
    include_special_team_identities: bool = False,
) -> TradeSnapshot:
    if ranking_horizon not in {
        "WEEKLY-PROXY",
        "ROS",
        "EARLY_SEASON_DRAFT_ANCHOR",
    }:
        raise ValueError(
            "ranking_horizon must be WEEKLY-PROXY, ROS, or "
            "EARLY_SEASON_DRAFT_ANCHOR"
        )
    state = _state(sleeper)
    current_week = int(state.get("week") or 0)
    state_season = int(state.get("season") or 0)
    league = sleeper.league
    if not current_week or state_season != league.season or schedule.season != league.season:
        raise IdentityIncomplete("Sleeper state, league, and schedule season must agree")
    if len(sleeper.teams) != league.team_count:
        raise IdentityIncomplete("Sleeper roster count does not match league team count")
    user_teams = [team for team in sleeper.teams if team.owner_id == user_id]
    if len(user_teams) != 1:
        raise IdentityIncomplete("Configured Sleeper user must resolve to exactly one roster")

    owner_by_player: dict[str, str] = {}
    duplicates: set[str] = set()
    for team in sleeper.teams:
        for player_id in team.player_ids:
            if player_id in owner_by_player:
                duplicates.add(player_id)
            owner_by_player[player_id] = team.roster_id
    if duplicates:
        raise IdentityIncomplete(
            "Duplicate Sleeper ownership: " + ", ".join(sorted(duplicates))
        )
    player_by_id = {player.player_id: player for player in sleeper.players}
    missing = sorted(player_id for player_id in owner_by_player if player_id not in player_by_id)
    if missing:
        raise IdentityIncomplete(
            "Rostered players missing from Sleeper directory: " + ", ".join(missing)
        )

    rostered_skill_ids = {
        player_id
        for player_id in owner_by_player
        if SKILL_POSITIONS.intersection(player_by_id[player_id].positions)
    }
    missing_teams = sorted(
        player_id
        for player_id in rostered_skill_ids
        if player_by_id[player_id].nfl_team not in schedule.teams
    )
    if missing_teams:
        raise IdentityIncomplete(
            "Rostered skill players lack a scheduled NFL team: "
            + ", ".join(missing_teams)
        )

    valuation_universe = tuple(
        player
        for player in sleeper.players
        if player.player_id in rostered_skill_ids
        or (
            player.active is True
            and bool(SKILL_POSITIONS.intersection(player.positions))
            and player.nfl_team in schedule.teams
        )
    )
    identity_universe = tuple(
        sorted(
            (
                *valuation_universe,
                *(
                    player
                    for player in sleeper.players
                    if include_special_team_identities
                    and player.player_id
                    not in {row.player_id for row in valuation_universe}
                    and player.active is True
                    and bool({"K", "DST"}.intersection(player.positions))
                    and player.nfl_team in schedule.teams
                ),
            ),
            key=lambda player: player.player_id,
        )
    )
    tradeable_ids = tuple(sorted(player.player_id for player in valuation_universe))
    free_agents = tuple(
        player_id for player_id in tradeable_ids if player_id not in owner_by_player
    )
    weeks = build_evaluation_weeks(
        current_week=current_week,
        championship_week=league.championship_week,
        playoff_start_week=league.playoff_start_week,
        team_count=league.team_count,
        matchups=sleeper.matchups,
        schedule=schedule,
    )
    if not all(week.fantasy_matchups_complete for week in weeks):
        from roster_theory.core.errors import ScheduleIncomplete

        raise ScheduleIncomplete("Sleeper fantasy matchups are incomplete in the evaluation horizon")

    schedule_captured_at = datetime.fromisoformat(
        (schedule.captured_at or schedule.verified_at).replace("Z", "+00:00")
    )
    if schedule_captured_at.tzinfo is None:
        schedule_captured_at = schedule_captured_at.replace(tzinfo=timezone.utc)
    schedule_age_seconds = max(
        0, int((datetime.now(timezone.utc) - schedule_captured_at).total_seconds())
    )
    schedule_stamp = DataStamp(
        source=schedule.source,
        endpoint=schedule.endpoint or schedule.source_url,
        captured_at=schedule_captured_at,
        season=schedule.season,
        horizon_start=weeks[0].week,
        horizon_end=weeks[-1].week,
        payload_hash=schedule.payload_hash,
        cache_status="local_normalized_schedule",
        freshness_seconds=schedule_age_seconds,
        fresh=schedule_age_seconds <= 24 * 60 * 60,
        export_restriction=schedule.use_restriction or None,
    )
    stamps = (*sleeper.stamps, schedule_stamp)
    completeness = SnapshotCompleteness(
        league_complete=True,
        ownership_complete=True,
        user_resolved=True,
        identity_complete=True,
        schedule_complete=True,
        valuation_inputs_complete=valuation_inputs_complete,
    )
    capabilities = (
        ("current_sleeper_ownership", True),
        ("nfl_schedule_and_byes", True),
        ("fantasy_matchup_horizon", True),
        ("market_rank_normalizer", True),
        ("projection_normalizer", True),
        ("valuation_inputs_loaded", valuation_inputs_complete),
    )
    normalized_inputs = {
        "league": league,
        "teams": sleeper.teams,
        "players": identity_universe,
        "weeks": weeks,
        "owner_by_player": owner_by_player,
        "ranking_horizon": ranking_horizon,
    }
    input_hashes = (
        ("league", stable_hash(league)),
        ("teams", stable_hash(sleeper.teams)),
        ("players", stable_hash(identity_universe)),
        ("weeks", stable_hash(weeks)),
    )
    manifest = AnalysisManifest.build(
        league_id=league.league_id,
        user_id=user_id,
        current_week=current_week,
        horizon_start=weeks[0].week,
        horizon_end=weeks[-1].week,
        configuration={
            "league_key": league_key,
            "ranking_horizon": ranking_horizon,
            "schedule_hash": schedule.payload_hash,
            **(
                {"include_special_team_identities": True}
                if include_special_team_identities
                else {}
            ),
        },
        normalized_inputs=normalized_inputs,
        data_stamps=tuple(stamps),
        coverage_checks=tuple(
            (name, value)
            for name, value in asdict(completeness).items()
            if name != "valuation_inputs_complete"
        ),
        warnings=warnings,
        input_hashes=input_hashes,
    )
    return TradeSnapshot(
        schema_version=1,
        product="TRADE ASSISTANT",
        league_key=league_key,
        captured_at=sleeper.captured_at,
        ranking_horizon=ranking_horizon,
        current=True,
        league=league,
        user_roster_id=user_teams[0].roster_id,
        teams=sleeper.teams,
        players=identity_universe,
        weeks=weeks,
        owner_by_player=tuple(sorted(owner_by_player.items())),
        free_agent_ids=free_agents,
        tradeable_player_ids=tradeable_ids,
        transaction_ids=tuple(
            item.transaction_id for item in sleeper.transactions if item.transaction_id
        ),
        stamps=tuple(stamps),
        capabilities=capabilities,
        completeness=completeness,
        warnings=warnings,
        manifest=manifest,
    )


def snapshot_to_dict(snapshot: TradeSnapshot) -> dict[str, Any]:
    return json.loads(json.dumps(asdict(snapshot), default=lambda value: value.isoformat()))


def save_trade_snapshot(snapshot: TradeSnapshot, path: str | Path) -> Path:
    return atomic_write_json(path, snapshot)


def _stamp(value: Mapping[str, Any]) -> DataStamp:
    return DataStamp(
        source=str(value["source"]),
        endpoint=str(value["endpoint"]),
        captured_at=datetime.fromisoformat(str(value["captured_at"])),
        season=value.get("season"),
        week=value.get("week"),
        horizon_start=value.get("horizon_start"),
        horizon_end=value.get("horizon_end"),
        scoring_label=value.get("scoring_label"),
        scoring_hash=value.get("scoring_hash"),
        parameter_hash=value.get("parameter_hash"),
        payload_hash=value.get("payload_hash"),
        cache_status=str(value.get("cache_status") or "miss"),
        freshness_seconds=value.get("freshness_seconds"),
        fresh=value.get("fresh"),
        export_restriction=value.get("export_restriction"),
        warnings=tuple(value.get("warnings") or ()),
    )


def load_trade_snapshot(path: str | Path) -> TradeSnapshot:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    league_value = value["league"]
    league = LeagueRules(
        league_id=str(league_value["league_id"]),
        season=int(league_value["season"]),
        team_count=int(league_value["team_count"]),
        roster_positions=tuple(league_value["roster_positions"]),
        scoring=tuple((str(key), float(raw)) for key, raw in league_value["scoring"]),
        playoff_start_week=league_value.get("playoff_start_week"),
        championship_week=league_value.get("championship_week"),
        reserve_slots=league_value.get("reserve_slots"),
        trade_deadline_raw=league_value.get("trade_deadline_raw"),
        platform_settings=tuple(
            tuple(pair) for pair in league_value.get("platform_settings") or ()
        ),
    )
    teams = tuple(
        FantasyTeam(
            roster_id=str(item["roster_id"]),
            owner_id=item.get("owner_id"),
            display_name=str(item["display_name"]),
            player_ids=tuple(item["player_ids"]),
            starter_ids=tuple(item.get("starter_ids") or ()),
            reserve_ids=tuple(item.get("reserve_ids") or ()),
            waiver_position=item.get("waiver_position"),
            waiver_budget_used=item.get("waiver_budget_used"),
            platform_settings=tuple(
                tuple(pair) for pair in item.get("platform_settings") or ()
            ),
        )
        for item in value["teams"]
    )
    players = tuple(
        Player(
            player_id=str(item["player_id"]),
            name=str(item["name"]),
            positions=tuple(item["positions"]),
            sleeper_id=item.get("sleeper_id"),
            fantasypros_id=item.get("fantasypros_id"),
            nfl_team=item.get("nfl_team"),
            active=item.get("active"),
            injury_status=item.get("injury_status"),
            external_ids=tuple(tuple(pair) for pair in item.get("external_ids") or ()),
            identity_confidence=str(item.get("identity_confidence") or "unverified"),
        )
        for item in value["players"]
    )
    weeks = tuple(EvaluationWeek(**item) for item in value["weeks"])
    completeness = SnapshotCompleteness(**value["completeness"])
    stamps = tuple(_stamp(item) for item in value["stamps"])
    manifest_value = value["manifest"]
    manifest = AnalysisManifest(
        analysis_id=str(manifest_value["analysis_id"]),
        league_id=str(manifest_value["league_id"]),
        user_id=str(manifest_value["user_id"]),
        current_week=int(manifest_value["current_week"]),
        horizon_start=int(manifest_value["horizon_start"]),
        horizon_end=int(manifest_value["horizon_end"]),
        configuration_hash=str(manifest_value["configuration_hash"]),
        scenario_seed=str(manifest_value["scenario_seed"]),
        data_stamps=tuple(_stamp(item) for item in manifest_value["data_stamps"]),
        coverage_checks=tuple(tuple(item) for item in manifest_value.get("coverage_checks") or ()),
        warnings=tuple(manifest_value.get("warnings") or ()),
        input_hashes=tuple(tuple(item) for item in manifest_value.get("input_hashes") or ()),
    )
    snapshot = TradeSnapshot(
        schema_version=int(value["schema_version"]),
        product=str(value["product"]),
        league_key=str(value["league_key"]),
        captured_at=datetime.fromisoformat(str(value["captured_at"])),
        ranking_horizon=str(value["ranking_horizon"]),
        current=False,
        league=league,
        user_roster_id=str(value["user_roster_id"]),
        teams=teams,
        players=players,
        weeks=weeks,
        owner_by_player=tuple(tuple(item) for item in value["owner_by_player"]),
        free_agent_ids=tuple(value["free_agent_ids"]),
        tradeable_player_ids=tuple(value["tradeable_player_ids"]),
        transaction_ids=tuple(value["transaction_ids"]),
        stamps=stamps,
        capabilities=tuple(tuple(item) for item in value["capabilities"]),
        completeness=completeness,
        warnings=tuple(value.get("warnings") or ()),
        manifest=manifest,
    )
    return replace(snapshot, warnings=(*snapshot.warnings, "OFFLINE/NON-CURRENT snapshot"))


def assert_current(
    snapshot: TradeSnapshot,
    *,
    maximum_age: timedelta = timedelta(minutes=5),
    now: datetime | None = None,
) -> None:
    if not snapshot.current:
        raise StaleData("Offline Trade snapshot is non-current")
    if not is_fresh(snapshot.captured_at, maximum_age, now=now or datetime.now(timezone.utc)):
        raise StaleData("Sleeper ownership exceeds the current-run freshness gate")
