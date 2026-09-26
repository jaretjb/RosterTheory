"""Sleeper Draft position-limit evidence; no inferred caps or setting defaults."""
import json
from collections.abc import Mapping

from roster_theory.core.capabilities import CapabilityAssessment, RuleCapability
from roster_theory.core.errors import CoverageIncomplete


POSITION_LIMIT_SOURCE = 'https://support.sleeper.com/en/articles/5379935-how-do-i-set-positional-limits'
API_SOURCE = 'https://docs.sleeper.com/#get-a-specific-draft'


def assess_draft_position_limits(draft: Mapping) -> CapabilityAssessment:
    settings = draft.get('settings')
    settings_valid = isinstance(settings, Mapping)
    present = settings_valid and 'enforce_position_limits' in settings
    value = settings.get('enforce_position_limits') if present else None
    observed = json.dumps(value, sort_keys=True) if present else '(absent)'
    evidence = (f'settings.enforce_position_limits={observed}', POSITION_LIMIT_SOURCE, API_SOURCE)
    valid = type(value) is int and value in (0, 1)
    enforcement = RuleCapability('draft.position_limit_enforcement',
        'SUPPORTED' if valid else 'UNKNOWN',
        ('Draft enforcement is explicitly enabled.' if value == 1 else 'Draft enforcement is explicitly disabled.')
        if valid else 'Draft position-limit enforcement is missing or malformed; its default is not assumed.',
        evidence)
    limits = RuleCapability('draft.position_limit_maxima',
        'IRRELEVANT' if valid and value == 0 else 'UNKNOWN',
        'Position maxima do not constrain draft picks when enforcement is explicitly disabled.'
        if valid and value == 0 else
        'Actual position maxima have no verified provider mapping; roster slots and app acquisition preferences are not league caps.',
        (POSITION_LIMIT_SOURCE, API_SOURCE))
    return CapabilityAssessment('draft', 'room_recommendation', 'position_limits', (enforcement, limits))


def require_draft_position_limits(draft: Mapping) -> CapabilityAssessment:
    assessment = assess_draft_position_limits(draft)
    if not assessment.scope_admitted:
        reasons = '; '.join(f'{row.rule}: {row.reason}' for row in assessment.blockers)
        raise CoverageIncomplete('Draft position-limit rules unresolved: ' + reasons +
            ' Obtain verified source rules before room recommendations; do not substitute app caps or change league settings to bypass this check.')
    return assessment
