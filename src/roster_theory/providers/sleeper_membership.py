"""Sleeper roster field and IR rule translation, without source-default guesses."""
from roster_theory.core.roster import assess_reserve_eligibility
from roster_theory.core.errors import RosterIllegal


def capacity_setting(settings, key):
    value = settings.get(key)
    if value is not None and (type(value) is not int or value < 0):
        raise ValueError(f"Sleeper {key} must be a nonnegative integer or unavailable")
    return value


def require_draft_membership_settings(settings):
    """A draft-only payload cannot prove all league rules; reject known taxi modes."""
    for key in ("taxi_slots", "slots_taxi"):
        if key in settings and (type(settings[key]) is not int or settings[key] != 0):
            raise RosterIllegal(f"Draft roster membership unsupported or unknown: {key}={settings[key]!r}")


def require_draft_snapshot_membership(snapshot):
    current = snapshot.get("current", {})
    require_draft_membership_settings(current.get("league", {}).get("settings") or {})
    for roster in current.get("rosters") or ():
        if roster.get("taxi"):
            raise RosterIllegal("Draft roster membership unsupported: TAXI_UNSUPPORTED")


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
