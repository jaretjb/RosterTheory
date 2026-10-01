"""Position-aware FantasyPros projection translation into the scoring contract.

Missing required fields block coverage; optional omissions remain recorded.
See docs/POSITION_FORECAST_COVERAGE.md for the shared forecast contract.
"""
from __future__ import annotations

from math import isfinite
from typing import Mapping

from roster_theory.core.projections import ESTIMATED_PROJECTION_PREFIX
from roster_theory.core.forecast_scoring import score_forecast_evidence
from roster_theory.core.scoring_contract import (
    RuleAssessment, ScoredEvidence, StatEvidence,
    StatObservation,
)
from roster_theory.providers.sleeper_scoring_rules import INDIVIDUALS, SLEEPER_LINEAR_RULES


SCORING_CONTRACT_VERSION = "fantasypros-weekly-v3"
DRAFT_SCORING_CONTRACT_VERSION = "fantasypros-draft-season-v3"
WEEKLY_ESTIMATE_POLICY_VERSION = "core-stats-conditional-v1"
WEEKLY_RULES = SLEEPER_LINEAR_RULES
_CORE_SKILL_STATS = {
    "QB": frozenset({"pass_yd", "pass_td", "pass_int", "rush_yd", "rush_td"}),
    "RB": frozenset({"rush_yd", "rush_td", "rec", "rec_yd", "rec_td"}),
    "WR": frozenset({"rec", "rec_yd", "rec_td"}),
    "TE": frozenset({"rec", "rec_yd", "rec_td"}),
}

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


def _score_projection_row(
    row: Mapping[str, object], assessment: RuleAssessment, source_schema: str,
) -> ScoredEvidence:
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
        if statistic == "fum_lost" and source_schema in (
            SCORING_CONTRACT_VERSION, DRAFT_SCORING_CONTRACT_VERSION,
        ):
            # FantasyPros labels the preseason projection column FL (Fumbles
            # Lost); its week-zero API example scores `fumbles` as lost fumbles.
            aliases = (*aliases, "fumbles")
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
    evidence = StatEvidence(1, "FantasyPros", source_schema, scope.season,
                            scope.horizon, scope.week, position, tuple(observations))
    return score_forecast_evidence(assessment, evidence)


def score_projection_row(row: Mapping[str, object], assessment: RuleAssessment) -> ScoredEvidence:
    """Score existing weekly/ROS projections without changing their source schema."""
    return _score_projection_row(row, assessment, SCORING_CONTRACT_VERSION)


def score_draft_projection_row(row: Mapping[str, object], assessment: RuleAssessment) -> ScoredEvidence:
    """Score season projections with an explicitly preseason Draft source schema."""
    if assessment.scope.horizon != "SEASON":
        raise ValueError("Draft projection scoring requires a season scope")
    return _score_projection_row(row, assessment, DRAFT_SCORING_CONTRACT_VERSION)


def scoring_coverage(result: ScoredEvidence) -> str:
    """Versioned failure vocabulary, preserved by existing projection readers."""
    if result.complete:
        return "complete"
    issues = sorted({(issue.category, issue.setting or "source") for issue in result.issues})
    return "scoring_incomplete_v1:" + ";".join(f"{category}={setting}" for category, setting in issues)


def weekly_estimate_coverage(result: ScoredEvidence) -> str | None:
    """Admit a labeled skill estimate only when core stats and rules are sound."""
    if result.assessment.scope.horizon != "WEEKLY" or result.assessment.support != "SUPPORTED":
        return None
    position = result.source_evidence.position
    if position not in _CORE_SKILL_STATS or not result.used_settings:
        return None
    if not result.issues or any(issue.category != "missing_statistic" for issue in result.issues):
        return None
    observed = {
        item.statistic for item in result.source_evidence.observations
        if item.kind == "OBSERVED"
    }
    required_core = {
        rule.statistic for rule, _ in result.assessment.active_rules
        if rule.statistic in _CORE_SKILL_STATS[position] and position in (rule.positions or ())
    }
    if not required_core.issubset(observed):
        return None
    missing = sorted({issue.setting for issue in result.issues})
    return ESTIMATED_PROJECTION_PREFIX + ";".join(
        f"missing_statistic={setting}" for setting in missing
    )
