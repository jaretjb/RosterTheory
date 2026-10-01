"""Position requirements for forecasts, distinct from historical event scoring.

Optional omissions are recorded, never manufactured as observed zeroes. Any
supplied optional statistic is still scored and must be valid. Unknown rules,
unknown positions and missing required statistics retain the strict contract.
"""
from dataclasses import replace

from roster_theory.core.scoring_contract import RuleAssessment, ScoredEvidence, StatEvidence, score_evidence


FORECAST_COVERAGE_VERSION = "position-forecast-v1"
_PASSING = frozenset({"pass_yd", "pass_td", "pass_int"})
_RUSHING = frozenset({"rush_yd", "rush_td"})
_RECEIVING = frozenset({"rec", "rec_yd", "rec_td"})
_RARE = frozenset({"pass_2pt", "rush_2pt", "rec_2pt", "fum_rec_td", "st_td", "st_ff", "st_fum_rec"})
OPTIONAL_FORECAST_STATS = {
    "QB": _RECEIVING | _RARE,
    "RB": _PASSING | _RARE,
    "WR": _PASSING | _RUSHING | _RARE,
    "TE": _PASSING | _RUSHING | _RARE,
    "K": _PASSING | _RUSHING | _RECEIVING | _RARE | {"fum_lost"},
    "DST": frozenset(),
}


def score_forecast_evidence(assessment: RuleAssessment, evidence: StatEvidence) -> ScoredEvidence:
    """Score every supplied value, requiring only position-relevant forecasts."""
    result = score_evidence(assessment, evidence)
    optional = OPTIONAL_FORECAST_STATS.get(evidence.position, frozenset())
    optional_settings = {rule.setting for rule, _ in assessment.active_rules
                         if rule.statistic in optional}
    omitted = tuple(sorted(issue.setting for issue in result.issues
                           if issue.category == "missing_statistic"
                           and issue.setting in optional_settings))
    return replace(result, optional_missing_settings=omitted,
                   coverage_policy=FORECAST_COVERAGE_VERSION,
                   issues=tuple(issue for issue in result.issues
                                if not (issue.category == "missing_statistic"
                                        and issue.setting in optional_settings)))
