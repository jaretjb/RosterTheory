"""Typed domain failures shared by RosterTheory product tracks."""


class RosterTheoryError(Exception):
    """Base class for expected, user-reportable domain failures."""


class SourceUnavailable(RosterTheoryError):
    pass


class StaleData(RosterTheoryError):
    pass


class IdentityIncomplete(RosterTheoryError):
    pass


class CoverageIncomplete(RosterTheoryError):
    pass


class Uncalibrated(RosterTheoryError):
    """A league has no proved, league-scoped policy for a decision workflow."""


class UnsupportedScoring(RosterTheoryError):
    pass


class RosterIllegal(RosterTheoryError):
    pass


class ScheduleIncomplete(RosterTheoryError):
    pass


class ProviderCapabilityMissing(RosterTheoryError):
    pass


class RequestBudgetExceeded(RosterTheoryError):
    pass
