"""Conservative FantasyPros weekly-stat translation into the scoring contract.

This catalogue declares arithmetic, not provider coverage. Missing fields are
never zero. See docs/MODULAR_PROVIDER_SCORING.md for sources and limitations.
"""
from __future__ import annotations

from math import isfinite
from typing import Mapping

from roster_theory.core.scoring_contract import (
    LinearScoringRule, RuleAssessment, ScoredEvidence, StatEvidence,
    StatObservation, score_evidence,
)


SCORING_CONTRACT_VERSION = "fantasypros-weekly-v1"
INDIVIDUALS = ("QB", "RB", "WR", "TE", "K")
_RULE_EVIDENCE = "Sleeper scoring categories; docs/MODULAR_PROVIDER_SCORING.md"

# Passing/receiving are not restricted to the player's usual football role.
# In particular, a missing WR passing forecast is not a documented zero.
_INDIVIDUAL_SETTINGS = (
    "pass_yd", "pass_td", "pass_int", "pass_2pt", "rush_yd", "rush_td",
    "rush_2pt", "rec", "rec_yd", "rec_td", "rec_2pt", "fum_lost",
    "fum_rec_td", "st_td", "st_ff", "st_fum_rec",
)
_DEFENSE_SETTINGS = (
    "int", "sack", "safe", "blk_kick", "ff", "def_td",
    "def_st_td", "def_st_ff", "def_st_fum_rec", "pts_allow_0",
    "pts_allow_1_6", "pts_allow_7_13", "pts_allow_14_20", "pts_allow_21_27",
    "pts_allow_28_34", "pts_allow_35p",
)
_KICKING_SETTINGS = (
    "fgm", "fgm_0_19", "fgm_20_29", "fgm_30_39", "fgm_40_49",
    "fgm_50_59", "fgm_50p", "fgm_60p", "fgmiss", "fgmiss_0_19",
    "fgmiss_20_29", "fgmiss_30_39", "fgmiss_40_49", "fgmiss_50_59",
    "fgmiss_50p", "fgmiss_60p", "xpm", "xpmiss",
)
WEEKLY_RULES = tuple(
    LinearScoringRule(setting, setting, positions, _RULE_EVIDENCE)
    for settings, positions in (
        (_INDIVIDUAL_SETTINGS, INDIVIDUALS),
        (_DEFENSE_SETTINGS, ("DST",)),
        (_KICKING_SETTINGS, ("K",)),
    ) for setting in settings
) + tuple(
    LinearScoringRule(f"bonus_rec_{position.lower()}", "rec", (position,), _RULE_EVIDENCE)
    for position in ("RB", "WR", "TE")
) + (
    # The existing skill projection path classifies this as limited. Do not
    # guess a position boundary while migrating that unresolved mapping.
    LinearScoringRule("fum_rec", "fum_rec", None, "Unresolved applicability; issue #30"),
)

# Explicit aliases retained from the existing NFL adapter where category
# identity is unambiguous. Canonical event keys are also accepted. This does
# not assert that FantasyPros supplies every key for every position/week.
_ALIASES = {
    "pass_yd": ("pass_yds", "passing_yards"),
    "pass_td": ("pass_tds", "passing_touchdowns"),
    "pass_int": ("pass_ints", "interceptions"),
    "pass_2pt": ("passing_2pt",),
    "rush_yd": ("rush_yds", "rushing_yards"),
    "rush_td": ("rush_tds", "rushing_touchdowns"),
    "rush_2pt": ("rushing_2pt",),
    "rec": ("rec_rec", "receptions"),
    "rec_yd": ("rec_yds", "receiving_yards"),
    "rec_td": ("rec_tds", "receiving_touchdowns"),
    "rec_2pt": ("receiving_2pt",),
    "fum_lost": ("fumbles_lost",),
    "st_td": ("ret_tds",),
    "int": ("def_int",),
    "sack": ("def_sack",),
    "safe": ("def_safety",),
}


def statistic_number(raw: object) -> float | None:
    """Numeric strings are valid provider values; booleans/NaN/Inf are not."""
    if isinstance(raw, bool) or not isinstance(raw, (int, float, str)):
        return None
    try:
        value = float(raw)
    except (ValueError, OverflowError):
        return None
    return value if isfinite(value) else None


def score_projection_row(row: Mapping[str, object], assessment: RuleAssessment) -> ScoredEvidence:
    stats = row.get("stats")
    stats = stats if isinstance(stats, Mapping) else {}
    position = str(row.get("position_id") or "").upper()
    if position == "DEF":
        position = "DST"
    if position not in (*INDIVIDUALS, "DST"):
        position = None
    observations = []
    for statistic in sorted({rule.statistic for rule, _ in assessment.active_rules}):
        aliases = (statistic, *_ALIASES.get(statistic, ()))
        present = [(key, statistic_number(stats[key])) for key in aliases if key in stats]
        if not present:
            continue
        if any(value is None for _, value in present):
            observations.append(StatObservation(statistic, None, "INVALID",
                "Non-numeric/nonfinite provider statistic: " + ", ".join(key for key, _ in present)))
        elif len({value for _, value in present}) != 1:
            observations.append(StatObservation(statistic, None, "INVALID",
                "Conflicting provider aliases: " + ", ".join(key for key, _ in present)))
        else:
            observations.append(StatObservation(statistic, present[0][1], "OBSERVED",
                "Provider field: " + ", ".join(key for key, _ in present)))
    scope = assessment.scope
    evidence = StatEvidence(1, "FantasyPros", SCORING_CONTRACT_VERSION, scope.season,
                            scope.horizon, scope.week, position, tuple(observations))
    return score_evidence(assessment, evidence)


def scoring_coverage(result: ScoredEvidence) -> str:
    """Versioned failure vocabulary, preserved by existing projection readers."""
    if result.complete:
        return "complete"
    issues = sorted({(issue.category, issue.setting or "source") for issue in result.issues})
    return "scoring_incomplete_v1:" + ";".join(f"{category}={setting}" for category, setting in issues)
