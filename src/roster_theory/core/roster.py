"""Pure roster facts and admission checks; no recommendations or provider I/O."""
from dataclasses import dataclass
from collections import Counter
from typing import Mapping, Sequence

from roster_theory.core.errors import RosterIllegal
from roster_theory.core.lineup import NON_STARTERS
from roster_theory.core.models import FantasyTeam, LeagueRules, Player

CAPACITY_OVERAGE_CODES = frozenset({"ACTIVE_CAPACITY_EXCEEDED", "RESERVE_CAPACITY_EXCEEDED"})


@dataclass(frozen=True, slots=True)
class MembershipIssue:
    code: str
    status: str
    roster_id: str | None = None
    player_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RosterState:
    roster_id: str
    owned_ids: tuple[str, ...]
    active_ids: tuple[str, ...] | None
    starter_ids: tuple[str, ...]
    reserve_ids: tuple[str, ...]
    taxi_ids: tuple[str, ...] | None
    active_limit: int
    open_active_slots: int | None


@dataclass(frozen=True, slots=True)
class MembershipAssessment:
    rosters: tuple[RosterState, ...]
    issues: tuple[MembershipIssue, ...]

    @property
    def complete(self) -> bool:
        return not self.issues


def assess_membership(league: LeagueRules, teams: Sequence[FantasyTeam]) -> MembershipAssessment:
    issues = []
    states = []
    taxi_limit = league.taxi_slots
    if taxi_limit is not None and (type(taxi_limit) is not int or taxi_limit < 0):
        issues.append(MembershipIssue("INVALID_TAXI_CAPACITY", "INVALID"))
    elif taxi_limit:
        issues.append(MembershipIssue("TAXI_UNSUPPORTED", "UNSUPPORTED"))
    for roster_id, count in Counter(team.roster_id for team in teams).items():
        if count > 1:
            issues.append(MembershipIssue("DUPLICATE_ROSTER_ID", "INVALID", roster_id))
    owners = {}
    active_limit = sum(position.upper() not in {"IR", "RESERVE", "TAXI"} for position in league.roster_positions)
    starter_limit = sum(position.upper() not in NON_STARTERS for position in league.roster_positions)
    for team in teams:
        def issue(code, status="INVALID", players=()):
            issues.append(MembershipIssue(code, status, team.roster_id, tuple(sorted(players, key=str))))
        owned, reserves = set(team.player_ids), set(team.reserve_ids)
        starters = tuple(pid for pid in team.starter_ids if pid != "0")
        taxis = team.taxi_ids
        if taxis is None and taxi_limit == 0:
            taxis = ()  # Explicit league capacity proves no legal taxi membership.
        for name, ids in (("OWNED", team.player_ids), ("STARTER", starters),
                          ("RESERVE", team.reserve_ids), ("TAXI", taxis or ())):
            duplicates = {pid for pid, count in Counter(ids).items() if count > 1}
            if duplicates:
                issue("DUPLICATE_" + name, players=duplicates)
            if any(not isinstance(pid, str) or not pid or pid == "0" for pid in ids):
                issue("INVALID_" + name + "_IDENTITY")
        for pid in owned:
            if pid in owners:
                issue("DUPLICATE_OWNERSHIP", players=(pid,))
            owners[pid] = team.roster_id
        if not reserves <= owned:
            issue("RESERVE_NOT_OWNED", players=reserves - owned)
        if not set(starters) <= owned:
            issue("STARTER_NOT_OWNED", players=set(starters) - owned)
        if set(starters) & reserves:
            issue("STARTER_IN_RESERVE", players=set(starters) & reserves)
        if len(team.starter_ids) > starter_limit:
            issue("STARTER_CAPACITY_EXCEEDED")
        if taxis is None:
            issue("TAXI_MEMBERSHIP_UNKNOWN", "UNKNOWN")
        elif taxis:
            issue("TAXI_UNSUPPORTED", "UNSUPPORTED", taxis)
            if not set(taxis) <= owned:
                issue("TAXI_NOT_OWNED", players=set(taxis) - owned)
            if set(taxis) & (reserves | set(starters)):
                issue("TAXI_MEMBERSHIP_OVERLAP", players=set(taxis) & (reserves | set(starters)))
        active = None if taxis is None else owned - reserves - set(taxis)
        if active is not None and len(active) > active_limit:
            issue("ACTIVE_CAPACITY_EXCEEDED", "OVER_LIMIT")
        limit = league.reserve_slots
        if limit is None:
            if reserves:
                issue("RESERVE_CAPACITY_UNKNOWN", "UNKNOWN")
        elif type(limit) is not int or limit < 0:
            issue("INVALID_RESERVE_CAPACITY")
        elif len(reserves) > limit:
            issue("RESERVE_CAPACITY_EXCEEDED", "OVER_LIMIT")
        states.append(RosterState(team.roster_id, tuple(sorted(owned, key=str)),
            tuple(sorted(active, key=str)) if active is not None else None, starters, tuple(sorted(reserves, key=str)),
            tuple(taxis) if taxis is not None else None, active_limit,
            max(0, active_limit - len(active)) if active is not None else None))
    return MembershipAssessment(tuple(states), tuple(issues))


def require_membership(league: LeagueRules, teams: Sequence[FantasyTeam], *,
                       allow_capacity_overage: bool = False) -> MembershipAssessment:
    """Admit trustworthy membership; snapshots may observe temporary overages."""
    assessment = assess_membership(league, teams)
    blockers = [row for row in assessment.issues
                if row.code != "RESERVE_CAPACITY_UNKNOWN"
                and not (allow_capacity_overage and row.code in CAPACITY_OVERAGE_CODES)]
    if blockers:
        raise RosterIllegal("Roster membership unavailable: " + "; ".join(
            f"{row.status}: {row.code} (roster {row.roster_id or 'league'})" for row in blockers))
    return assessment


def assess_reserve_eligibility(team: FantasyTeam, players: Sequence[Player],
                              allowed_statuses: Mapping[str, bool | None]) -> tuple[MembershipIssue, ...]:
    """Check declared status eligibility; None means the rule is unknown."""
    by_id = {row.player_id: row for row in players}
    issues = []
    for pid in team.reserve_ids:
        player = by_id.get(pid)
        if player is None:
            issues.append(MembershipIssue("RESERVE_IDENTITY_UNKNOWN", "UNKNOWN", team.roster_id, (pid,)))
            continue
        status = (player.injury_status or "").upper()
        allowed = allowed_statuses.get(status)
        if allowed is True:
            continue
        unknown = allowed is None
        issues.append(MembershipIssue("RESERVE_ELIGIBILITY_UNKNOWN" if unknown else "RESERVE_INELIGIBLE",
                                      "UNKNOWN" if unknown else "INVALID", team.roster_id, (pid,)))
    return tuple(issues)


def require_membership_artifact(teams) -> None:
    if any("taxi_ids" not in team for team in teams):
        raise ValueError("Legacy roster snapshot lacks taxi membership evidence; refresh from Sleeper or replay with its original build")
    for team in teams:
        taxis = team["taxi_ids"]
        if taxis is not None and (not isinstance(taxis, list) or any(not isinstance(pid, str) for pid in taxis)):
            raise ValueError("Invalid taxi membership in saved snapshot; refresh source evidence")
