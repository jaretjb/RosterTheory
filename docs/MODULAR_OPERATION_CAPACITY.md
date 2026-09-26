# MA-002f operation-specific roster capacity

September 26, 2026. Bounded #31 follow-up from merged PR #39; MA-002 and #31
remain open.

## Rule and decision boundary

Sleeper [allows a draft or trade to leave a team over its roster limit](https://support.sleeper.com/en/articles/3956140-can-a-team-go-over-the-roster-limit).
The team cannot add free agents or edit its starting lineup until the overage
is resolved. Sleeper [also permits temporary positional-limit overages through
trades and waivers](https://support.sleeper.com/en/articles/5379935-how-do-i-set-positional-limits),
but their source settings and exact admission remain separate #31 work.
An ineligible [IR occupant can lock additions and other roster adjustments](https://support.sleeper.com/en/articles/1983643-how-does-injured-reserve-ir-work).
These are different constraints; a single league-wide membership veto cannot
correctly represent all three actions.

Core membership now reports active/reserve overages as `OVER_LIMIT` observations.
Strict `require_membership` retains its original rejection by default. Snapshot
callers explicitly allow these two observations, while all duplicate identity,
ownership, starter/reserve overlap, unsupported taxi and malformed-capacity
errors still stop them. Source membership is never altered to make a team fit.

Trade refresh and current-data validation admit overfull rosters and record
their warnings. A trade involving one is modeled with `DECISION-CONDITIONAL`:
the trade can be discussed, but lineup and secondary-move effects depend on
resolving the overage. Reserve overage also requires a manual legality check;
the public IR rule does not guarantee every such trade. An unrelated overfull
roster does not receive those modes for the evaluated package. Existing
reserve-player and unknown-rule manual checks remain in force. The result is
read-only advice, not a claim that a package has been submitted or accepted.

Waiver refresh records capacity and reserve legality for every roster and can
show an incomplete whole-league snapshot. A user add still requires that user's
capacity and reserve evidence to be legal and known. Search checks those same
user-specific prerequisites instead of treating an opponent's overage as a
league-wide veto. Warnings and snapshot completeness continue to expose the
opponent's state. No claim success or future roster repair is assumed.

## Validation and remaining limits

Before the change, synthetic overfull Trade current checks and Waiver refreshes
raised `ACTIVE_CAPACITY_EXCEEDED` before evaluation. Focused regressions now
cover Trade refresh/comparison, opponent and user Waiver overages, independent
Waiver search, reserve overage, and structural-defect rejection. The full suite
passes 896 tests, including unchanged MA-001 parser/output goldens. Ruff passes;
no provider calls, calibration transfers or league writes occurred.

The rule about temporarily exceeded positional limits does not establish a
provider field mapping or authorize broad positional-cap support. The app does
not yet model every claim sequence, commissioner override, or exact Sleeper
transaction outcome. #31 retains full feature admission and source mapping;
the support matrix remains future validation.
