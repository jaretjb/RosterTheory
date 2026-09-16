from __future__ import annotations

import json
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Mapping

from roster_theory.core.errors import IdentityIncomplete, RosterIllegal, StaleData
from roster_theory.core.models import FantasyTeam, LeagueRules, Player
from roster_theory.core.provenance import AnalysisManifest, DataStamp, stable_hash
from roster_theory.providers.cache import atomic_write_json, is_fresh
from roster_theory.providers.sleeper import SleeperBundle, SleeperTransaction


SUPPORTED_POSITIONS = frozenset({"QB", "RB", "WR", "TE", "K", "DST", "DEF"})
DEFAULT_FRESHNESS_WINDOW = timedelta(minutes=5)


class AcquisitionState(str, Enum):
    FREE_AGENT = "FREE_AGENT"
    WAIVERS = "WAIVERS"
    UNROSTERED = "UNROSTERED"
    LOCKED = "LOCKED"
    PENDING = "PENDING"
    UNKNOWN = "UNKNOWN"


ACQUIRABLE_STATES = frozenset(
    {
        AcquisitionState.FREE_AGENT.value,
        AcquisitionState.WAIVERS.value,
        AcquisitionState.UNROSTERED.value,
        AcquisitionState.PENDING.value,
    }
)


@dataclass(frozen=True, slots=True)
class PlayerAcquisition:
    player_id: str
    state: str
    owner_roster_id: str | None
    transaction_ids: tuple[str, ...]
    evidence: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RosterCapacity:
    roster_id: str
    active_limit: int
    active_count: int
    open_active_slots: int
    reserve_limit: int | None
    reserve_count: int
    capacity_legal: bool
    reserve_legality_known: bool
    reserve_legal: bool


@dataclass(frozen=True, slots=True)
class WaiverCompleteness:
    league_complete: bool
    rosters_complete: bool
    user_resolved: bool
    ownership_complete: bool
    identity_complete: bool
    roster_capacity_complete: bool
    reserve_legality_complete: bool
    acquisition_state_complete: bool
    freshness_complete: bool

    @property
    def snapshot_complete(self) -> bool:
        return all(asdict(self).values())

    @property
    def roster_snapshot_complete(self) -> bool:
        return all(
            (
                self.league_complete,
                self.rosters_complete,
                self.user_resolved,
                self.ownership_complete,
                self.identity_complete,
                self.roster_capacity_complete,
                self.reserve_legality_complete,
                self.freshness_complete,
            )
        )


@dataclass(frozen=True, slots=True)
class WaiverSnapshot:
    schema_version: int
    product: str
    league_key: str
    captured_at: datetime
    freshness_window_seconds: int
    current: bool
    nfl_state: tuple[tuple[str, Any], ...]
    league: LeagueRules
    user_roster_id: str
    teams: tuple[FantasyTeam, ...]
    players: tuple[Player, ...]
    owner_by_player: tuple[tuple[str, str], ...]
    roster_capacity: tuple[RosterCapacity, ...]
    acquisitions: tuple[PlayerAcquisition, ...]
    transactions: tuple[SleeperTransaction, ...]
    stamps: tuple[DataStamp, ...]
    capabilities: tuple[tuple[str, bool], ...]
    completeness: WaiverCompleteness
    warnings: tuple[str, ...]
    manifest: AnalysisManifest
    recommendation_generated: bool
    sleeper_write_performed: bool


def classify_acquisition_state(
    player_id: str,
    *,
    owner_by_player: Mapping[str, str],
    transactions: tuple[SleeperTransaction, ...] = (),
    explicit_status: str | None = None,
) -> PlayerAcquisition:
    owner = owner_by_player.get(player_id)
    if owner is not None:
        return PlayerAcquisition(
            player_id=player_id,
            state=AcquisitionState.LOCKED.value,
            owner_roster_id=owner,
            transaction_ids=(),
            evidence=("current_roster_ownership",),
        )

    pending_ids = tuple(
        sorted(
            transaction.transaction_id
            for transaction in transactions
            if transaction.status == "pending"
            and transaction.transaction_type == "waiver"
            and player_id in dict(transaction.adds)
            and transaction.transaction_id
        )
    )
    if pending_ids:
        return PlayerAcquisition(
            player_id=player_id,
            state=AcquisitionState.PENDING.value,
            owner_roster_id=None,
            transaction_ids=pending_ids,
            evidence=("observed_pending_waiver_add",),
        )

    normalized = str(explicit_status or "").strip().upper().replace("-", "_")
    aliases = {
        "FREE_AGENT": AcquisitionState.FREE_AGENT,
        "FREEAGENT": AcquisitionState.FREE_AGENT,
        "FA": AcquisitionState.FREE_AGENT,
        "WAIVER": AcquisitionState.WAIVERS,
        "WAIVERS": AcquisitionState.WAIVERS,
        "LOCKED": AcquisitionState.LOCKED,
        "PENDING": AcquisitionState.PENDING,
    }
    state = aliases.get(normalized)
    if state is not None:
        return PlayerAcquisition(
            player_id=player_id,
            state=state.value,
            owner_roster_id=None,
            transaction_ids=(),
            evidence=("explicit_platform_availability",),
        )
    return PlayerAcquisition(
        player_id=player_id,
        state=AcquisitionState.UNROSTERED.value,
        owner_roster_id=None,
        transaction_ids=(),
        evidence=("current_roster_delta",),
    )


def _capacity(league: LeagueRules, team: FantasyTeam) -> RosterCapacity:
    player_ids = set(team.player_ids)
    starter_ids = {player_id for player_id in team.starter_ids if player_id != "0"}
    reserve_ids = set(team.reserve_ids)
    if not starter_ids.issubset(player_ids):
        raise RosterIllegal(f"Roster {team.roster_id} has a starter outside its player list")
    if not reserve_ids.issubset(player_ids):
        raise RosterIllegal(f"Roster {team.roster_id} has a reserve outside its player list")
    active_limit = len(league.roster_positions)
    active_count = len(player_ids - reserve_ids)
    reserve_limit = league.reserve_slots
    reserve_known = reserve_limit is not None
    reserve_legal = reserve_known and len(reserve_ids) <= int(reserve_limit)
    capacity_legal = active_count <= active_limit and (
        not reserve_known or len(player_ids) <= active_limit + int(reserve_limit)
    )
    if not capacity_legal:
        raise RosterIllegal(f"Roster {team.roster_id} exceeds its configured capacity")
    if reserve_known and not reserve_legal:
        raise RosterIllegal(f"Roster {team.roster_id} exceeds its reserve capacity")
    return RosterCapacity(
        roster_id=team.roster_id,
        active_limit=active_limit,
        active_count=active_count,
        open_active_slots=max(0, active_limit - active_count),
        reserve_limit=reserve_limit,
        reserve_count=len(reserve_ids),
        capacity_legal=capacity_legal,
        reserve_legality_known=reserve_known,
        reserve_legal=reserve_legal,
    )


def build_waiver_snapshot(
    *,
    league_key: str,
    user_id: str,
    sleeper: SleeperBundle,
    expected_user_roster_id: str | None = None,
    availability_by_player: Mapping[str, str] | None = None,
    freshness_window: timedelta = DEFAULT_FRESHNESS_WINDOW,
    now: datetime | None = None,
) -> WaiverSnapshot:
    current_time = now or datetime.now(timezone.utc)
    if not is_fresh(sleeper.captured_at, freshness_window, now=current_time):
        raise StaleData("Sleeper waiver inputs exceed the current-run freshness gate")
    state = dict(sleeper.state)
    current_week = int(state.get("week") or 0)
    state_season = int(state.get("season") or 0)
    league = sleeper.league
    if current_week < 1 or state_season != league.season:
        raise IdentityIncomplete("Sleeper state and league season must agree")
    if len(sleeper.teams) != league.team_count:
        raise IdentityIncomplete("Sleeper roster count does not match league team count")
    user_teams = [team for team in sleeper.teams if team.owner_id == user_id]
    if len(user_teams) != 1:
        raise IdentityIncomplete("Configured Sleeper user must resolve to exactly one roster")
    user_team = user_teams[0]
    if expected_user_roster_id is not None and user_team.roster_id != expected_user_roster_id:
        raise IdentityIncomplete("Configured user roster ID does not match Sleeper ownership")

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
    supported_rostered_ids = {
        player_id
        for player_id in owner_by_player
        if SUPPORTED_POSITIONS.intersection(player_by_id[player_id].positions)
    }
    universe = tuple(
        player
        for player in sleeper.players
        if player.player_id in supported_rostered_ids
        or (player.active is True and SUPPORTED_POSITIONS.intersection(player.positions))
    )
    capacities = tuple(_capacity(league, team) for team in sleeper.teams)
    explicit = availability_by_player or {}
    acquisitions = tuple(
        classify_acquisition_state(
            player.player_id,
            owner_by_player=owner_by_player,
            transactions=sleeper.transactions,
            explicit_status=explicit.get(player.player_id),
        )
        for player in universe
    )
    unclassified_count = sum(
        acquisition.state == AcquisitionState.UNKNOWN.value
        for acquisition in acquisitions
    )
    reserve_complete = all(item.reserve_legality_known for item in capacities)
    acquisition_complete = unclassified_count == 0
    warnings: list[str] = []
    if not reserve_complete:
        warnings.append("Reserve-slot limits are unavailable for one or more rosters")
    if not acquisition_complete:
        warnings.append(
            "Current ownership could not classify "
            f"{unclassified_count} supported players"
        )
    warnings.append(
        "Exact FREE_AGENT versus WAIVERS mechanism and competing pending claims are "
        "informational; claim success cannot be predicted"
    )
    completeness = WaiverCompleteness(
        league_complete=True,
        rosters_complete=True,
        user_resolved=True,
        ownership_complete=True,
        identity_complete=True,
        roster_capacity_complete=all(item.capacity_legal for item in capacities),
        reserve_legality_complete=reserve_complete,
        acquisition_state_complete=acquisition_complete,
        freshness_complete=True,
    )
    capabilities = (
        ("sleeper_get_only", True),
        ("current_sleeper_ownership", True),
        ("current_unrostered_delta", True),
        ("current_roster_capacity", True),
        ("current_reserve_membership", reserve_complete),
        ("explicit_player_availability", bool(availability_by_player)),
        ("competing_pending_claims_complete", False),
        ("fantasypros_called", False),
        ("sleeper_write_surface_present", False),
    )
    normalized_inputs = {
        "nfl_state": sleeper.state,
        "league": league,
        "teams": sleeper.teams,
        "players": universe,
        "owner_by_player": owner_by_player,
        "roster_capacity": capacities,
        "acquisitions": acquisitions,
        "transactions": sleeper.transactions,
    }
    input_hashes = (
        ("league", stable_hash(league)),
        ("teams", stable_hash(sleeper.teams)),
        ("players", stable_hash(universe)),
        ("transactions", stable_hash(sleeper.transactions)),
        ("acquisitions", stable_hash(acquisitions)),
    )
    manifest = AnalysisManifest.build(
        league_id=league.league_id,
        user_id=user_id,
        current_week=current_week,
        horizon_start=current_week,
        horizon_end=current_week,
        configuration={
            "league_key": league_key,
            "freshness_window_seconds": int(freshness_window.total_seconds()),
            "availability_source": (
                "explicit_platform_availability"
                if availability_by_player
                else "sleeper_public_get_only"
            ),
        },
        normalized_inputs=normalized_inputs,
        data_stamps=sleeper.stamps,
        coverage_checks=tuple(asdict(completeness).items()),
        warnings=tuple(warnings),
        input_hashes=input_hashes,
    )
    return WaiverSnapshot(
        schema_version=1,
        product="WAIVER ASSISTANT",
        league_key=league_key,
        captured_at=sleeper.captured_at,
        freshness_window_seconds=int(freshness_window.total_seconds()),
        current=True,
        nfl_state=sleeper.state,
        league=league,
        user_roster_id=user_team.roster_id,
        teams=sleeper.teams,
        players=universe,
        owner_by_player=tuple(sorted(owner_by_player.items())),
        roster_capacity=capacities,
        acquisitions=acquisitions,
        transactions=sleeper.transactions,
        stamps=sleeper.stamps,
        capabilities=capabilities,
        completeness=completeness,
        warnings=tuple(warnings),
        manifest=manifest,
        recommendation_generated=False,
        sleeper_write_performed=False,
    )


def resolve_player_acquisition(
    snapshot: WaiverSnapshot, name: str
) -> PlayerAcquisition:
    normalized = name.strip().casefold()
    matches = [player for player in snapshot.players if player.name.casefold() == normalized]
    if not matches:
        raise IdentityIncomplete(f"Waiver target did not resolve exactly: {name}")
    if len(matches) != 1:
        raise IdentityIncomplete(f"Waiver target is ambiguous: {name}")
    acquisition_by_id = {
        acquisition.player_id: acquisition for acquisition in snapshot.acquisitions
    }
    return acquisition_by_id[matches[0].player_id]


def save_waiver_snapshot(snapshot: WaiverSnapshot, path: str | Path) -> Path:
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


def load_waiver_snapshot(path: str | Path) -> WaiverSnapshot:
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
    transactions = tuple(
        SleeperTransaction(
            transaction_id=str(item["transaction_id"]),
            week=int(item["week"]),
            transaction_type=str(item["transaction_type"]),
            status=item.get("status"),
            roster_ids=tuple(item.get("roster_ids") or ()),
            adds=tuple(tuple(pair) for pair in item.get("adds") or ()),
            drops=tuple(tuple(pair) for pair in item.get("drops") or ()),
            created_at_ms=item.get("created_at_ms"),
            status_updated_at_ms=item.get("status_updated_at_ms"),
            creator_id=item.get("creator_id"),
            waiver_bid=item.get("waiver_bid"),
            metadata=tuple(tuple(pair) for pair in item.get("metadata") or ()),
        )
        for item in value["transactions"]
    )
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
        coverage_checks=tuple(
            tuple(item) for item in manifest_value.get("coverage_checks") or ()
        ),
        warnings=tuple(manifest_value.get("warnings") or ()),
        input_hashes=tuple(
            tuple(item) for item in manifest_value.get("input_hashes") or ()
        ),
    )
    snapshot = WaiverSnapshot(
        schema_version=int(value["schema_version"]),
        product=str(value["product"]),
        league_key=str(value["league_key"]),
        captured_at=datetime.fromisoformat(str(value["captured_at"])),
        freshness_window_seconds=int(value["freshness_window_seconds"]),
        current=False,
        nfl_state=tuple(tuple(pair) for pair in value["nfl_state"]),
        league=league,
        user_roster_id=str(value["user_roster_id"]),
        teams=teams,
        players=players,
        owner_by_player=tuple(tuple(pair) for pair in value["owner_by_player"]),
        roster_capacity=tuple(RosterCapacity(**item) for item in value["roster_capacity"]),
        acquisitions=tuple(
            PlayerAcquisition(
                player_id=str(item["player_id"]),
                state=str(item["state"]),
                owner_roster_id=item.get("owner_roster_id"),
                transaction_ids=tuple(item.get("transaction_ids") or ()),
                evidence=tuple(item.get("evidence") or ()),
            )
            for item in value["acquisitions"]
        ),
        transactions=transactions,
        stamps=stamps,
        capabilities=tuple(tuple(pair) for pair in value["capabilities"]),
        completeness=WaiverCompleteness(**value["completeness"]),
        warnings=tuple(value.get("warnings") or ()),
        manifest=manifest,
        recommendation_generated=bool(value["recommendation_generated"]),
        sleeper_write_performed=bool(value["sleeper_write_performed"]),
    )
    return replace(
        snapshot,
        warnings=(*snapshot.warnings, "OFFLINE/NON-CURRENT Waiver snapshot"),
    )


def assert_current(
    snapshot: WaiverSnapshot,
    *,
    now: datetime | None = None,
) -> None:
    if not snapshot.current:
        raise StaleData("Offline Waiver snapshot is non-current")
    maximum_age = timedelta(seconds=snapshot.freshness_window_seconds)
    if not is_fresh(snapshot.captured_at, maximum_age, now=now or datetime.now(timezone.utc)):
        raise StaleData("Sleeper waiver inputs exceed the current-run freshness gate")
