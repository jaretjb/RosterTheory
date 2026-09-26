"""Inventory observed reference rules without claiming verified provider support.

Run from the repository root with PYTHONPATH=src;. (src:. on POSIX).
This is offline migration tooling; it does not supply a production catalogue.
"""
import json

from roster_theory.core.provenance import stable_hash
from roster_theory.core.scoring import POSITION_RECEPTION_BONUSES, STAT_ALIASES
from roster_theory.core.scoring_contract import LinearScoringRule, ScoringScope, assess_scoring_rules
from tests.ma001_fixtures import PROFILES, rules


def inventory():
    # Prior alias recognition is an inventory lead, not proof of applicability,
    # projection availability, or a structural-zero convention for any provider.
    catalogue = tuple(LinearScoringRule(key, key, None,
        'Legacy calculation recognition only; source/applicability unverified')
        for key in sorted(STAT_ALIASES))
    profiles = {}
    for profile in PROFILES:
        observed = rules(profile)
        scoring = observed['scoring_settings']
        scope = ScoringScope(profile, 2026, 'scoring-inventory', 'WEEKLY', 1)
        assessed = assess_scoring_rules(scoring, scope=scope, catalogue=catalogue,
                                        catalogue_version='legacy-calculation-inventory-v1')
        categories = {i.setting: i.category for i in assessed.issues}
        profiles[profile] = {
            'observed_at': observed['observed_at'], 'reference_rules_hash': stable_hash(observed),
            'scoring_hash': assessed.scoring_hash, 'support': assessed.support,
            'disabled_settings': list(assessed.disabled_settings),
            'nonzero_settings': [{
                'setting': setting, 'multiplier': value,
                'contract_issue': categories[setting],
                'candidate_canonical_statistic': setting if setting in STAT_ALIASES else None,
                'legacy_alias_candidates': list(STAT_ALIASES.get(setting, ())),
                'legacy_position_bonus': POSITION_RECEPTION_BONUSES.get(setting),
                'applicable_positions': None,
                'verified_provider_fields': None,
                'calculation': 'multiplier * explicit canonical statistic' if setting in STAT_ALIASES else None,
                'missing_data_behavior': 'BLOCK: no zero inference',
            } for setting, value in sorted(scoring.items()) if value != 0],
        }
    return {'schema_version': 1, 'scope': 'MA-002a inventory, not production admission',
            'provider_coverage': 'UNVERIFIED; no live retrieval or provider zero rules', 'profiles': profiles}


if __name__ == '__main__':
    print(json.dumps(inventory(), indent=2))
