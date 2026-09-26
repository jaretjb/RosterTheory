"""Scoped rule support, independent of data readiness and policy calibration."""
from dataclasses import dataclass
from typing import Literal


RuleClassification = Literal['SUPPORTED', 'IRRELEVANT', 'UNKNOWN', 'UNSUPPORTED']


@dataclass(frozen=True, slots=True)
class RuleCapability:
    rule: str
    classification: RuleClassification
    reason: str
    evidence: tuple[str, ...] = ()

    def __post_init__(self):
        if self.classification not in ('SUPPORTED', 'IRRELEVANT', 'UNKNOWN', 'UNSUPPORTED'):
            raise ValueError('Unrecognized rule classification')
        if not self.rule or not self.reason:
            raise ValueError('Rule capabilities require a rule name and reason')


@dataclass(frozen=True, slots=True)
class CapabilityAssessment:
    feature: str
    operation: str
    scope: str
    checks: tuple[RuleCapability, ...]
    schema_version: int = 1

    def __post_init__(self):
        if not self.feature or not self.operation or not self.scope:
            raise ValueError('Capabilities require an explicit feature, operation and scope')
        if self.schema_version != 1:
            raise ValueError('Unsupported capability schema')
        if len({row.rule for row in self.checks}) != len(self.checks):
            raise ValueError('Duplicate capability rule')

    @property
    def status(self) -> str:
        if any(row.classification == 'UNSUPPORTED' for row in self.checks):
            return 'UNSUPPORTED'
        if not self.checks or any(row.classification == 'UNKNOWN' for row in self.checks):
            return 'LIMITED'
        return 'SUPPORTED'

    @property
    def scope_admitted(self) -> bool:
        """Only this named scope; never a whole-feature readiness declaration."""
        return self.status == 'SUPPORTED'

    @property
    def blockers(self) -> tuple[RuleCapability, ...]:
        return tuple(row for row in self.checks if row.classification in ('UNKNOWN', 'UNSUPPORTED'))
