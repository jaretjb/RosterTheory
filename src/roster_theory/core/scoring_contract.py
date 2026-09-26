"""Versioned, provider-neutral scoring evidence; not feature readiness or policy.

Adapters must supply canonical statistic names and an explicit rule catalogue.
This contract never infers zero from absence, aliases a provider field, derives
threshold events from average yards, or approves a recommendation.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Literal, Mapping

from roster_theory.core.errors import CoverageIncomplete
from roster_theory.core.provenance import stable_hash


Horizon = Literal['WEEKLY', 'ROS', 'SEASON']
Support = Literal['SUPPORTED', 'LIMITED', 'UNSUPPORTED']
POSITIONS = ('QB', 'RB', 'WR', 'TE', 'K', 'DST')


def _text(value: str, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'{name} must be a nonempty string')


def _number(value: object) -> float | None:
    # Canonical inputs are numbers. String parsing and alias conversion belong
    # to the adapter; booleans are never numerical statistical observations.
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        result = float(value)
    except OverflowError:
        return None
    return result if math.isfinite(result) else None


def _scope(season: int, horizon: str, week: int | None) -> None:
    if type(season) is not int or season < 1:
        raise ValueError('season must be a positive integer')
    if horizon not in ('WEEKLY', 'ROS', 'SEASON'):
        raise ValueError('horizon must be WEEKLY, ROS or SEASON')
    if horizon in ('WEEKLY', 'ROS'):
        if type(week) is not int or week < 1:
            raise ValueError('weekly/ROS evidence requires a positive start week')
    elif week is not None:
        raise ValueError('season evidence must not declare a week')


@dataclass(frozen=True, slots=True)
class ScoringScope:
    league_id: str
    season: int
    operation: str
    horizon: Horizon
    week: int | None

    def __post_init__(self) -> None:
        _text(self.league_id, 'league_id')
        _text(self.operation, 'operation')
        _scope(self.season, self.horizon, self.week)


@dataclass(frozen=True, slots=True)
class LinearScoringRule:
    setting: str
    statistic: str
    # None means applicability is unverified, never "all positions".
    positions: tuple[str, ...] | None
    evidence: str

    def __post_init__(self) -> None:
        for name in ('setting', 'statistic', 'evidence'):
            _text(getattr(self, name), name)
        if self.positions is not None:
            if not isinstance(self.positions, tuple) or not self.positions:
                raise ValueError('positions must be a nonempty tuple or None')
            if len(set(self.positions)) != len(self.positions):
                raise ValueError('positions must be unique')
            for position in self.positions:
                if position not in POSITIONS:
                    raise ValueError('Rule positions must use canonical position names')


@dataclass(frozen=True, slots=True)
class ScoringIssue:
    category: str
    setting: str
    reason: str

    def __post_init__(self) -> None:
        _text(self.category, 'issue category')
        _text(self.reason, 'issue reason')
        if not isinstance(self.setting, str):
            raise ValueError('issue setting must be a string')


@dataclass(frozen=True, slots=True)
class RuleAssessment:
    schema_version: int
    scope: ScoringScope
    catalogue_version: str
    scoring_hash: str
    rules_hash: str
    support: Support
    active_rules: tuple[tuple[LinearScoringRule, float], ...]
    disabled_settings: tuple[str, ...]
    issues: tuple[ScoringIssue, ...]

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise ValueError('Unsupported scoring-assessment schema')
        if self.support not in ('SUPPORTED', 'LIMITED', 'UNSUPPORTED'):
            raise ValueError('Unknown scoring support status')
        if not isinstance(self.scope, ScoringScope):
            raise ValueError('Scoring assessment requires an explicit scope')
        _text(self.catalogue_version, 'catalogue_version')
        for name in ('active_rules', 'disabled_settings', 'issues'):
            if not isinstance(getattr(self, name), tuple):
                raise ValueError(f'{name} must be an immutable tuple')
        for rule, multiplier in self.active_rules:
            if not isinstance(rule, LinearScoringRule) or _number(multiplier) is None or multiplier == 0:
                raise ValueError('Active rules require an explicit rule and finite nonzero multiplier')


def assess_scoring_rules(
    scoring: Mapping[str, object], *, scope: ScoringScope,
    catalogue: tuple[LinearScoringRule, ...], catalogue_version: str,
) -> RuleAssessment:
    """Classify every supplied setting before examining any player statistics."""
    _text(catalogue_version, 'catalogue_version')
    by_setting = {rule.setting: rule for rule in catalogue}
    if len(by_setting) != len(catalogue):
        raise ValueError('Duplicate scoring-rule definitions')
    active, disabled, issues, normalized = [], [], [], []
    for setting in scoring:
        _text(setting, 'setting')
    for setting in sorted(scoring):
        _text(setting, 'setting')
        raw = scoring[setting]
        multiplier = _number(raw)
        # Invalid inputs stay distinguishable and hashable, including NaN/Inf.
        if multiplier is None:
            if not isinstance(raw, (str, int, float, bool, type(None))):
                raise ValueError(f'{setting}: scoring multiplier must be a scalar')
            normalized.append((setting, type(raw).__name__, str(raw)))
            issues.append(ScoringIssue('invalid_multiplier', setting, 'A finite numeric multiplier is required'))
            continue
        normalized.append((setting, 'number', multiplier))
        if multiplier == 0:
            disabled.append(setting)
            continue
        rule = by_setting.get(setting)
        if rule is None:
            issues.append(ScoringIssue('unsupported_rule', setting, 'No explicit calculation rule is declared'))
            continue
        active.append((rule, multiplier))
        if rule.positions is None:
            issues.append(ScoringIssue('unknown_applicability', setting, 'Position applicability has not been established'))
    support: Support = ('UNSUPPORTED' if any(i.category != 'unknown_applicability' for i in issues)
                        else 'LIMITED' if issues else 'SUPPORTED')
    return RuleAssessment(1, scope, catalogue_version, stable_hash(normalized),
        stable_hash({'scope': scope, 'version': catalogue_version,
                     'catalogue': sorted(catalogue, key=lambda r: r.setting), 'scoring': normalized}),
        support, tuple(active), tuple(disabled), tuple(issues))


@dataclass(frozen=True, slots=True)
class StatObservation:
    statistic: str
    value: float | None
    kind: Literal['OBSERVED', 'STRUCTURAL_ZERO', 'INVALID']
    evidence: str = ''

    def __post_init__(self) -> None:
        _text(self.statistic, 'statistic')
        if self.kind not in ('OBSERVED', 'STRUCTURAL_ZERO', 'INVALID'):
            raise ValueError('Unknown statistical observation kind')
        if self.kind == 'INVALID':
            if self.value is not None:
                raise ValueError('Invalid statistics must not carry usable values')
            _text(self.evidence, 'invalid-stat evidence')
        elif _number(self.value) is None:
            raise ValueError('Observed statistics must be finite numbers')
        if self.kind == 'STRUCTURAL_ZERO':
            if self.value != 0:
                raise ValueError('Structural zero must be zero')
            _text(self.evidence, 'source-schema zero rule')


@dataclass(frozen=True, slots=True)
class StatEvidence:
    schema_version: int
    source: str
    source_schema: str
    season: int
    horizon: Horizon
    week: int | None
    position: str | None
    observations: tuple[StatObservation, ...]

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise ValueError('Unsupported stat-evidence schema')
        _text(self.source, 'source')
        _text(self.source_schema, 'source_schema')
        _scope(self.season, self.horizon, self.week)
        if self.position is not None:
            if self.position not in POSITIONS:
                raise ValueError('Evidence position must be canonical or explicitly unknown (None)')
        if not isinstance(self.observations, tuple):
            raise ValueError('observations must be an immutable tuple')
        if any(not isinstance(o, StatObservation) for o in self.observations):
            raise ValueError('observations must contain explicit StatObservation records')
        names = [o.statistic for o in self.observations]
        if len(set(names)) != len(names):
            raise ValueError('Duplicate or conflicting statistical observations')


def observed_statistics(
    stats: Mapping[str, object], *, source: str, source_schema: str, season: int,
    horizon: Horizon, week: int | None, position: str | None,
    structural_zeros: Mapping[str, str] | None = None,
) -> StatEvidence:
    """Preserve invalid scalar observations; zero declarations require provenance.

    A structural-zero declaration is a caller-supplied source-schema fact, not
    permission to fill arbitrary absent fields. Production adapters must cite
    their verified schema rule; this contract supplies no provider defaults.
    """
    observations = []
    for statistic in stats:
        _text(statistic, 'statistic')
    for statistic in structural_zeros or {}:
        _text(statistic, 'statistic')
    for statistic, raw in sorted(stats.items()):
        value = _number(raw)
        if value is None and not isinstance(raw, (str, int, float, bool, type(None))):
            raise ValueError(f'{statistic}: statistic must be a scalar')
        observations.append(StatObservation(statistic, value,
            'OBSERVED' if value is not None else 'INVALID',
            '' if value is not None else f'{type(raw).__name__}: {raw}'))
    for statistic, schema_rule in sorted((structural_zeros or {}).items()):
        observations.append(StatObservation(statistic, 0.0, 'STRUCTURAL_ZERO', schema_rule))
    return StatEvidence(1, source, source_schema, season, horizon, week, position, tuple(observations))


@dataclass(frozen=True, slots=True)
class ScoredEvidence:
    schema_version: int
    assessment: RuleAssessment
    source_evidence: StatEvidence
    diagnostic_points: float
    used_settings: tuple[str, ...]
    inapplicable_settings: tuple[str, ...]
    structural_zero_settings: tuple[str, ...]
    issues: tuple[ScoringIssue, ...]

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise ValueError('Unsupported scored-evidence schema')
        if _number(self.diagnostic_points) is None:
            raise ValueError('Diagnostic points must be finite')
        if not isinstance(self.assessment, RuleAssessment) or not isinstance(self.source_evidence, StatEvidence):
            raise ValueError('Scored evidence requires explicit rule and source records')
        for name in ('used_settings', 'inapplicable_settings', 'structural_zero_settings', 'issues'):
            if not isinstance(getattr(self, name), tuple):
                raise ValueError(f'{name} must be an immutable tuple')

    @property
    def complete(self) -> bool:
        return self.assessment.support == 'SUPPORTED' and not self.issues

    def require_points(self) -> float:
        """A caller cannot accidentally obtain usable partial points."""
        if not self.complete:
            reasons = '; '.join(f'{i.setting or "source"}: {i.category}' for i in self.issues)
            raise CoverageIncomplete(f'Scoring evidence is incomplete: {reasons}')
        return self.diagnostic_points


def score_evidence(assessment: RuleAssessment, evidence: StatEvidence) -> ScoredEvidence:
    """Apply declared linear rules to explicitly scoped canonical observations."""
    if assessment.schema_version != 1:
        raise ValueError('Unsupported scoring-assessment schema')
    scope = assessment.scope
    issues = list(assessment.issues)
    if (scope.season, scope.horizon, scope.week) != (evidence.season, evidence.horizon, evidence.week):
        issues.append(ScoringIssue('source_scope_mismatch', '', 'Season, horizon and week must match the requested scope'))
    observed = {o.statistic: o for o in evidence.observations}
    total, used, inapplicable, zeros = 0.0, [], [], []
    for rule, multiplier in assessment.active_rules:
        if rule.positions is None:
            continue
        if evidence.position is None:
            issues.append(ScoringIssue('missing_position', rule.setting, 'Position is required to resolve applicability'))
            continue
        if evidence.position not in rule.positions:
            inapplicable.append(rule.setting)
            continue
        observation = observed.get(rule.statistic)
        if observation is None:
            issues.append(ScoringIssue('missing_statistic', rule.setting, f'Missing canonical statistic: {rule.statistic}'))
            continue
        if observation.kind == 'INVALID':
            issues.append(ScoringIssue('invalid_statistic', rule.setting, f'{rule.statistic}: {observation.evidence}'))
            continue
        contribution = observation.value * multiplier
        if not math.isfinite(contribution) or not math.isfinite(total + contribution):
            issues.append(ScoringIssue('nonfinite_result', rule.setting, 'The contribution or accumulated total is nonfinite'))
            continue
        total += contribution
        used.append(rule.setting)
        if observation.kind == 'STRUCTURAL_ZERO':
            zeros.append(rule.setting)
    return ScoredEvidence(1, assessment, evidence, round(total, 3), tuple(used),
                          tuple(inapplicable), tuple(zeros), tuple(issues))
