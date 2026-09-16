from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

from roster_theory.core.models import FantasyTeam, LeagueRules, Player, frozen_pairs
from roster_theory.core.provenance import DataStamp, stable_hash
from roster_theory.providers.cache import atomic_write_json, is_fresh
from roster_theory.sleeper import SleeperClient


@dataclass(frozen=True, slots=True)
class SleeperMatchupWeek:
    week: int
    team_rows: int
    roster_matchups: tuple[tuple[str, str | None], ...]


@dataclass(frozen=True, slots=True)
class SleeperTransaction:
    transaction_id: str
    week: int
    transaction_type: str
    status: str | None
    roster_ids: tuple[str, ...]
    adds: tuple[tuple[str, str], ...]
    drops: tuple[tuple[str, str], ...]
    created_at_ms: int | None = None
    status_updated_at_ms: int | None = None
    creator_id: str | None = None
    waiver_bid: int | None = None
    metadata: tuple[tuple[str, Any], ...] = ()


@dataclass(frozen=True, slots=True)
class SleeperBundle:
    captured_at: datetime
    state: tuple[tuple[str, Any], ...]
    league: LeagueRules
    teams: tuple[FantasyTeam, ...]
    players: tuple[Player, ...]
    matchups: tuple[SleeperMatchupWeek, ...]
    transactions: tuple[SleeperTransaction, ...]
    winner_bracket_rounds: int | None
    loser_bracket_rows: int
    stamps: tuple[DataStamp, ...]
    player_directory_cache_status: str


def _integer(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def normalize_league(value: Mapping[str, Any]) -> LeagueRules:
    league_id = str(value.get("league_id") or "")
    season = _integer(value.get("season"))
    team_count = _integer(value.get("total_rosters"))
    positions = tuple(str(item) for item in (value.get("roster_positions") or ()))
    scoring = value.get("scoring_settings") or {}
    settings = value.get("settings") or {}
    if not league_id or season is None or not team_count or not positions:
        raise ValueError("Sleeper league response is missing required identity/rules")
    if not isinstance(scoring, Mapping) or not isinstance(settings, Mapping):
        raise ValueError("Sleeper league scoring/settings must be objects")
    return LeagueRules(
        league_id=league_id,
        season=season,
        team_count=team_count,
        roster_positions=positions,
        scoring=tuple(
            sorted((str(key), float(raw)) for key, raw in scoring.items())
        ),
        playoff_start_week=_integer(settings.get("playoff_week_start")),
        championship_week=None,
        reserve_slots=_integer(settings.get("reserve_slots")),
        trade_deadline_raw=settings.get("trade_deadline"),
        platform_settings=frozen_pairs(settings),
    )


def normalize_teams(
    users: list[Mapping[str, Any]], rosters: list[Mapping[str, Any]]
) -> tuple[FantasyTeam, ...]:
    user_names: dict[str, str] = {}
    for user in users:
        user_id = str(user.get("user_id") or "")
        metadata = user.get("metadata") or {}
        if not isinstance(metadata, Mapping):
            metadata = {}
        user_names[user_id] = str(
            metadata.get("team_name")
            or user.get("display_name")
            or user.get("username")
            or user_id
        )
    teams: list[FantasyTeam] = []
    for roster in rosters:
        roster_id = str(roster.get("roster_id") or "")
        if not roster_id:
            raise ValueError("Sleeper roster is missing roster_id")
        owner_id = str(roster.get("owner_id") or "") or None
        roster_settings = roster.get("settings") or {}
        if not isinstance(roster_settings, Mapping):
            raise ValueError("Sleeper roster settings must be an object")
        teams.append(
            FantasyTeam(
                roster_id=roster_id,
                owner_id=owner_id,
                display_name=user_names.get(owner_id or "", owner_id or roster_id),
                player_ids=tuple(str(item) for item in (roster.get("players") or ())),
                starter_ids=tuple(str(item) for item in (roster.get("starters") or ())),
                reserve_ids=tuple(str(item) for item in (roster.get("reserve") or ())),
                waiver_position=_integer(roster_settings.get("waiver_position")),
                waiver_budget_used=_integer(roster_settings.get("waiver_budget_used")),
                platform_settings=frozen_pairs(roster_settings),
            )
        )
    return tuple(sorted(teams, key=lambda team: int(team.roster_id)))


def normalize_players(value: Mapping[str, Mapping[str, Any]]) -> tuple[Player, ...]:
    players: list[Player] = []
    external_fields = {
        "yahoo": "yahoo_id",
        "espn": "espn_id",
        "fantasy_data": "fantasy_data_id",
        "sportradar": "sportradar_id",
        "rotowire": "rotowire_id",
    }
    for raw_id, row in value.items():
        sleeper_id = str(row.get("player_id") or raw_id)
        raw_positions = row.get("fantasy_positions") or [row.get("position")]
        positions = tuple(
            sorted(
                {
                    "DST" if str(item).upper() == "DEF" else str(item).upper()
                    for item in raw_positions
                    if item
                }
            )
        )
        name = str(
            row.get("full_name")
            or row.get("first_name")
            or row.get("last_name")
            or sleeper_id
        )
        external_ids = tuple(
            sorted(
                (canonical, str(row[field]))
                for canonical, field in external_fields.items()
                if row.get(field) not in (None, "")
            )
        )
        players.append(
            Player(
                player_id=sleeper_id,
                sleeper_id=sleeper_id,
                fantasypros_id=None,
                name=name,
                positions=positions,
                nfl_team=str(row.get("team") or "") or None,
                active=row.get("active") if isinstance(row.get("active"), bool) else None,
                injury_status=str(row.get("injury_status") or "") or None,
                external_ids=external_ids,
                identity_confidence="sleeper_authoritative",
            )
        )
    return tuple(sorted(players, key=lambda player: player.player_id))


def normalize_matchups(
    week: int, rows: list[Mapping[str, Any]]
) -> SleeperMatchupWeek:
    return SleeperMatchupWeek(
        week=week,
        team_rows=len(rows),
        roster_matchups=tuple(
            sorted(
                (
                    str(row.get("roster_id") or ""),
                    str(row.get("matchup_id"))
                    if row.get("matchup_id") is not None
                    else None,
                )
                for row in rows
            )
        ),
    )


def normalize_transactions(
    week: int, rows: list[Mapping[str, Any]]
) -> tuple[SleeperTransaction, ...]:
    result: list[SleeperTransaction] = []
    for row in rows:
        adds = row.get("adds") or {}
        drops = row.get("drops") or {}
        settings = row.get("settings") or {}
        metadata = row.get("metadata") or {}
        if not isinstance(adds, Mapping) or not isinstance(drops, Mapping):
            raise ValueError("Sleeper transaction adds/drops must be objects")
        if not isinstance(settings, Mapping) or not isinstance(metadata, Mapping):
            raise ValueError("Sleeper transaction settings/metadata must be objects")
        result.append(
            SleeperTransaction(
                transaction_id=str(row.get("transaction_id") or ""),
                week=week,
                transaction_type=str(row.get("type") or "unknown"),
                status=str(row.get("status") or "") or None,
                roster_ids=tuple(str(item) for item in (row.get("roster_ids") or ())),
                adds=tuple(sorted((str(key), str(value)) for key, value in adds.items())),
                drops=tuple(sorted((str(key), str(value)) for key, value in drops.items())),
                created_at_ms=_integer(row.get("created")),
                status_updated_at_ms=_integer(row.get("status_updated")),
                creator_id=str(row.get("creator") or "") or None,
                waiver_bid=_integer(settings.get("waiver_bid")),
                metadata=frozen_pairs(metadata),
            )
        )
    return tuple(sorted(result, key=lambda item: item.transaction_id))


class SleeperAdapter:
    def __init__(
        self,
        client: SleeperClient,
        *,
        player_cache_path: str | Path = "data/cache/trade/sleeper/players_nfl.json",
    ) -> None:
        self.client = client
        self.player_cache_path = Path(player_cache_path)

    def _player_directory(
        self, captured_at: datetime, *, maximum_age: timedelta = timedelta(hours=24)
    ) -> tuple[Mapping[str, Any], str]:
        if self.player_cache_path.exists():
            cached = json.loads(self.player_cache_path.read_text(encoding="utf-8"))
            cache_time = datetime.fromisoformat(str(cached["captured_at"]))
            if is_fresh(cache_time, maximum_age, now=captured_at):
                return cached["players"], "hit"
        players = self.client.players("nfl")
        atomic_write_json(
            self.player_cache_path,
            {"captured_at": captured_at.isoformat(), "players": players},
        )
        return players, "miss"

    def fetch(self, league_id: str, weeks: list[int]) -> SleeperBundle:
        captured_at = datetime.now(timezone.utc)
        state = self.client.state("nfl")
        raw_league = self.client.league(league_id)
        users = self.client.league_users(league_id)
        rosters = self.client.league_rosters(league_id)
        winners = self.client.league_winners_bracket(league_id)
        losers = self.client.league_losers_bracket(league_id)
        player_rows, player_cache_status = self._player_directory(captured_at)
        matchup_values = {
            week: self.client.league_matchups(league_id, week)
            for week in sorted(set(weeks))
        }
        transaction_values = {
            week: self.client.league_transactions(league_id, week)
            for week in sorted(set(weeks))
        }
        league = normalize_league(raw_league)
        rounds = [
            int(row["r"])
            for row in winners
            if isinstance(row, Mapping) and row.get("r") is not None
        ]
        championship = (
            league.playoff_start_week + max(rounds) - 1
            if league.playoff_start_week is not None and rounds
            else None
        )
        league = LeagueRules(
            league_id=league.league_id,
            season=league.season,
            team_count=league.team_count,
            roster_positions=league.roster_positions,
            scoring=league.scoring,
            playoff_start_week=league.playoff_start_week,
            championship_week=championship,
            reserve_slots=league.reserve_slots,
            trade_deadline_raw=league.trade_deadline_raw,
            platform_settings=league.platform_settings,
        )
        stamps = tuple(
            DataStamp(
                source="Sleeper",
                endpoint=endpoint,
                captured_at=captured_at,
                season=league.season,
                week=week,
                parameter_hash=stable_hash({"league_id": league_id, "week": week}),
                cache_status=cache,
                fresh=True,
            )
            for endpoint, week, cache in (
                ("/state/nfl", None, "miss"),
                (f"/league/{league_id}", None, "miss"),
                (f"/league/{league_id}/users", None, "miss"),
                (f"/league/{league_id}/rosters", None, "miss"),
                (f"/league/{league_id}/winners_bracket", None, "miss"),
                (f"/league/{league_id}/losers_bracket", None, "miss"),
                ("/players/nfl", None, player_cache_status),
                *(
                    (f"/league/{league_id}/matchups/{week}", week, "miss")
                    for week in sorted(set(weeks))
                ),
                *(
                    (f"/league/{league_id}/transactions/{week}", week, "miss")
                    for week in sorted(set(weeks))
                ),
            )
        )
        return SleeperBundle(
            captured_at=captured_at,
            state=frozen_pairs(state),
            league=league,
            teams=normalize_teams(users, rosters),
            players=normalize_players(player_rows),
            matchups=tuple(
                normalize_matchups(week, matchup_values[week])
                for week in sorted(matchup_values)
            ),
            transactions=tuple(
                transaction
                for week in sorted(transaction_values)
                for transaction in normalize_transactions(week, transaction_values[week])
            ),
            winner_bracket_rounds=max(rounds) if rounds else None,
            loser_bracket_rows=len(losers),
            stamps=stamps,
            player_directory_cache_status=player_cache_status,
        )

    def fetch_waiver(self, league_id: str) -> SleeperBundle:
        """Fetch the bounded GET-only inputs needed by a Waiver refresh."""
        captured_at = datetime.now(timezone.utc)
        state = self.client.state("nfl")
        current_week = _integer(state.get("week"))
        if current_week is None or current_week < 1:
            raise ValueError("Sleeper NFL state is missing the current week")
        raw_league = self.client.league(league_id)
        users = self.client.league_users(league_id)
        rosters = self.client.league_rosters(league_id)
        player_rows, player_cache_status = self._player_directory(
            captured_at, maximum_age=timedelta(minutes=5)
        )
        transaction_rows = self.client.league_transactions(league_id, current_week)
        league = normalize_league(raw_league)
        stamps = tuple(
            DataStamp(
                source="Sleeper",
                endpoint=endpoint,
                captured_at=captured_at,
                season=league.season,
                week=week,
                parameter_hash=stable_hash({"league_id": league_id, "week": week}),
                cache_status=cache,
                fresh=True,
            )
            for endpoint, week, cache in (
                ("/state/nfl", None, "miss"),
                (f"/league/{league_id}", None, "miss"),
                (f"/league/{league_id}/users", None, "miss"),
                (f"/league/{league_id}/rosters", None, "miss"),
                ("/players/nfl", None, player_cache_status),
                (
                    f"/league/{league_id}/transactions/{current_week}",
                    current_week,
                    "miss",
                ),
            )
        )
        return SleeperBundle(
            captured_at=captured_at,
            state=frozen_pairs(state),
            league=league,
            teams=normalize_teams(users, rosters),
            players=normalize_players(player_rows),
            matchups=(),
            transactions=normalize_transactions(current_week, transaction_rows),
            winner_bracket_rounds=None,
            loser_bracket_rows=0,
            stamps=stamps,
            player_directory_cache_status=player_cache_status,
        )
