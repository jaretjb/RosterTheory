"""Sleeper roster field and IR rule translation, without source-default guesses."""
from collections.abc import Mapping

from roster_theory.core.roster import assess_reserve_eligibility, require_membership, require_no_taxi_settings
from roster_theory.core.errors import RosterIllegal


def capacity_setting(settings, key):
    value = settings.get(key)
    if value is not None and (type(value) is not int or value < 0):
        raise ValueError(f"Sleeper {key} must be a nonnegative integer or unavailable")
    return value


def require_draft_membership_settings(settings):
    """A draft-only payload cannot prove all league rules; reject known taxi modes."""
    require_no_taxi_settings(settings, context="Draft roster membership")


def require_draft_snapshot_membership(snapshot):
    """Admit a saved Draft source only when current roster roles are established."""
    from roster_theory.providers.sleeper import normalize_league, normalize_teams

    if isinstance(snapshot, Mapping) and "schema_version" in snapshot:
        version = snapshot["schema_version"]
        if type(version) is not int or version != 1:
            raise RosterIllegal("Unsupported Draft snapshot schema; refresh from Sleeper")
    current = snapshot.get("current") if isinstance(snapshot, Mapping) else None
    if not isinstance(current, Mapping):
        raise RosterIllegal("Draft snapshot lacks current membership; refresh from Sleeper")
    raw_league, raw_rosters = current.get("league"), current.get("rosters")
    if not isinstance(raw_league, Mapping) or not isinstance(raw_rosters, list):
        raise RosterIllegal("Draft snapshot lacks league or roster evidence; refresh from Sleeper")
    settings = raw_league.get("settings")
    if not isinstance(settings, Mapping):
        raise RosterIllegal("Draft snapshot lacks league settings; refresh from Sleeper")
    require_draft_membership_settings(settings)
    try:
        league = normalize_league(raw_league)
        teams = normalize_teams([], raw_rosters)
    except (TypeError, ValueError, AttributeError) as exc:
        raise RosterIllegal("Draft snapshot has invalid membership; refresh from Sleeper") from exc
    if league.taxi_slots is None:
        raise RosterIllegal("Draft taxi capacity is unavailable; refresh from Sleeper")
    if len(teams) != league.team_count:
        raise RosterIllegal("Draft snapshot roster count does not match league rules; refresh from Sleeper")
    assessment = require_membership(league, teams, allow_capacity_overage=True)
    if any(row.code == "RESERVE_CAPACITY_UNKNOWN" for row in assessment.issues):
        raise RosterIllegal("Draft reserve capacity is unavailable; refresh from Sleeper")
    return assessment


def roster_ids(roster, field, *, optional=False):
    if field not in roster:
        if optional:
            return None
        raise ValueError(f"Sleeper roster is missing {field} membership")
    values = roster[field]
    if values is None:
        return None if optional else ()
    if not isinstance(values, list) or any(not isinstance(pid, str) or not pid for pid in values):
        raise ValueError(f"Sleeper roster {field} must be a list of player IDs")
    return tuple(values)


def reserve_eligibility(league, team, players):
    # Sleeper documents IR/PUP eligibility and commissioner-controlled extensions:
    # https://support.sleeper.com/en/articles/1983643-how-does-injured-reserve-ir-work
    settings = dict(league.platform_settings)
    flags = {"OUT": "reserve_allow_out", "O": "reserve_allow_out",
             "DOUBTFUL": "reserve_allow_doubtful", "D": "reserve_allow_doubtful",
             "SUSP": "reserve_allow_sus", "SUSPENDED": "reserve_allow_sus",
             "NA": "reserve_allow_na", "DNR": "reserve_allow_dnr", "COVID": "reserve_allow_cov"}
    statuses = {"IR": True, "PUP": True, "HEALTHY": False,
                "Q": False, "QUESTIONABLE": False, "": None}
    for status, key in flags.items():
        value = settings.get(key)
        statuses[status] = bool(value) if type(value) is int and value in (0, 1) else None
    return assess_reserve_eligibility(team, players, statuses)
