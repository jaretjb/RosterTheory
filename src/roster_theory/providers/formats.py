"""Documented FantasyPros baseline formats, independent of league policy.

See https://api.fantasypros.com/v2/docs (NFL consensus rankings/projections).
Custom scoring projections do not manufacture custom expert rankings.
"""

from dataclasses import dataclass
from math import isfinite
from typing import Mapping, Any

from roster_theory.core.errors import CoverageIncomplete, UnsupportedScoring


@dataclass(frozen=True, slots=True)
class RankingFormat:
    scoring: str
    league_exact: bool
    warnings: tuple[str, ...]


def ranking_format(scoring: Mapping[str, Any], roster_positions=()) -> RankingFormat:
    try:
        values = {str(key): float(value) for key, value in scoring.items()}
    except (TypeError, ValueError) as exc:
        raise UnsupportedScoring("League scoring multipliers must be numeric and finite") from exc
    if any(not isfinite(value) for value in values.values()):
        raise UnsupportedScoring("League scoring multipliers must be finite")
    reception = values.get("rec", 0.0)
    formats = {0.0: "STD", 0.5: "HALF", 1.0: "PPR"}
    if reception not in formats:
        raise UnsupportedScoring(
            "No documented FantasyPros ranking format for reception multiplier "
            f"{reception}; supported baseline formats are STD/HALF/PPR"
        )
    baseline = {
        "pass_td": 4,
        "pass_yd": 0.04,
        "pass_int": -1,
        "rush_td": 6,
        "rush_yd": 0.1,
        "rec_td": 6,
        "rec_yd": 0.1,
        "fum_lost": -2,
        "pass_2pt": 2,
        "rush_2pt": 2,
        "rec_2pt": 2,
        "fgm_0_19": 3,
        "fgm_20_29": 3,
        "fgm_30_39": 3,
        "fgm_40_49": 4,
        "fgm_50p": 5,
        "fgmiss": -1,
        "xpm": 1,
        "xpmiss": -1,
        "int": 2,
        "sack": 1,
        "safe": 2,
        "blk_kick": 2,
        "pts_allow_0": 10,
        "pts_allow_1_6": 7,
        "pts_allow_7_13": 4,
        "pts_allow_14_20": 1,
        "pts_allow_21_27": 0,
        "pts_allow_28_34": -1,
        "pts_allow_35p": -4,
        "def_td": 6,
        "def_st_td": 6,
        "st_td": 6,
    }
    custom = sorted(
        {key for key, default in baseline.items() if values.get(key, 0) != default}
        | {
            key
            for key, value in values.items()
            if key != "rec" and key not in baseline and value != 0
        }
    )
    warnings = (
        ()
        if not custom
        else (
            f"Expert rankings use baseline {formats[reception]}, not custom authority for {', '.join(custom)}; "
            "raw projections are scored separately under league rules",
        )
    )
    multi_qb = tuple(roster_positions).count("QB") > 1 or "SUPER_FLEX" in roster_positions
    if multi_qb:
        warnings += (
            "Expert positional ranks retain their baseline format; overall/WW ranks are not "
            "league-exact superflex/two-QB authority. Lineup and replacement use actual roster slots",
        )
    return RankingFormat(formats[reception], not custom and not multi_qb, warnings)


def validate_provider_scope(payload: Mapping[str, Any], *, season: int, scoring: str) -> None:
    declared = tuple(payload[key] for key in ("year", "season") if key in payload)
    if not declared or any(str(value) != str(season) for value in declared):
        raise CoverageIncomplete(
            f"FantasyPros response season {declared!r} does not match requested {season}"
        )
    if str(payload.get("scoring") or "").upper() != scoring:
        raise CoverageIncomplete("FantasyPros response scoring does not match requested " + scoring)
