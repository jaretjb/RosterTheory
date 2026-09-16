from __future__ import annotations

from typing import Any, Mapping, Protocol, runtime_checkable


@runtime_checkable
class LeagueStateSource(Protocol):
    def state(self, sport: str = "nfl") -> Mapping[str, Any]: ...

    def league(self, league_id: str) -> Mapping[str, Any]: ...

    def league_users(self, league_id: str) -> list[Mapping[str, Any]]: ...

    def league_rosters(self, league_id: str) -> list[Mapping[str, Any]]: ...

    def league_matchups(
        self, league_id: str, week: int
    ) -> list[Mapping[str, Any]]: ...

    def league_transactions(
        self, league_id: str, week: int
    ) -> list[Mapping[str, Any]]: ...


@runtime_checkable
class PlayerDirectorySource(Protocol):
    def players(self, sport: str = "nfl") -> Mapping[str, Any]: ...


@runtime_checkable
class RankingSource(Protocol):
    def consensus_rankings(
        self, season: int, **params: Any
    ) -> Mapping[str, Any]: ...

    def ranking_experts(self, season: int, **params: Any) -> Mapping[str, Any]: ...


@runtime_checkable
class ProjectionSource(Protocol):
    def projections(self, season: int, **params: Any) -> Mapping[str, Any]: ...


@runtime_checkable
class AvailabilitySource(Protocol):
    def news(self, sport: str = "nfl", **params: Any) -> Mapping[str, Any]: ...


@runtime_checkable
class PlayerPointsSource(Protocol):
    def player_points(self, season: int, **params: Any) -> Mapping[str, Any]: ...

