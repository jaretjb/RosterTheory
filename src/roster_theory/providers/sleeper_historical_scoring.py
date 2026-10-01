"""Sleeper historical-stat translation for Waiver evidence.

For a player row with a valid played-game count, interpret omitted applicable
counting fields as explicit zeros. This sparse-field rule was checked against
league-scored Sleeper matchup points; an absent row or game count remains
incomplete.
"""
from __future__ import annotations

from math import isfinite
from typing import Mapping

from roster_theory.core.scoring_contract import (
    POSITIONS, RuleAssessment, ScoredEvidence, ScoringScope, StatEvidence,
    StatObservation, assess_scoring_rules, score_evidence,
)
from roster_theory.providers.sleeper_scoring_rules import SLEEPER_LINEAR_RULES


HISTORICAL_RULES_VERSION = "sleeper-historical-sparse-zero-v2"


def assess_historical_rules(scoring: Mapping[str, object], *, league_id: str,
                            season: int, week: int | None) -> RuleAssessment:
    scope = ScoringScope(league_id, season, "WAIVER-HISTORICAL-PERFORMANCE",
                         "WEEKLY" if week is not None else "SEASON", week)
    return assess_scoring_rules(scoring, scope=scope, catalogue=SLEEPER_LINEAR_RULES,
                                catalogue_version=HISTORICAL_RULES_VERSION)


def _number(raw: object) -> float | None:
    if isinstance(raw, bool) or not isinstance(raw, (int, float, str)):
        return None
    try:
        value = float(raw)
    except (ValueError, OverflowError):
        return None
    return value if isfinite(value) else None


def score_historical_stats(stats: Mapping[str, object], assessment: RuleAssessment,
                           *, position: str | None) -> ScoredEvidence:
    canonical_position = (position or "").upper()
    if canonical_position == "DEF":
        canonical_position = "DST"
    if canonical_position not in POSITIONS:
        canonical_position = None
    observations = []
    games = _number(stats.get("gp"))
    played = games is not None and games > 0 and games == int(games)
    applicable = {
        rule.statistic for rule, _ in assessment.active_rules
        if rule.positions is not None and canonical_position in rule.positions
    }
    for statistic in sorted({rule.statistic for rule, _ in assessment.active_rules}):
        if statistic not in stats:
            if played and statistic in applicable:
                observations.append(StatObservation(
                    statistic, 0.0, "STRUCTURAL_ZERO",
                    "Sleeper omitted this counting field from a played-game stat row",
                ))
            continue
        raw = stats[statistic]
        number = _number(raw)
        observations.append(StatObservation(
            statistic, number, "OBSERVED" if number is not None else "INVALID",
            f"Sleeper field {statistic}" if number is not None
            else f"Invalid Sleeper field {statistic} ({type(raw).__name__})",
        ))
    scope = assessment.scope
    evidence = StatEvidence(1, "Sleeper", HISTORICAL_RULES_VERSION, scope.season,
                            scope.horizon, scope.week, canonical_position, tuple(observations))
    return score_evidence(assessment, evidence)
