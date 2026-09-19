# Trade TA-1201 completion

Completed September 18, 2026 (America/Los_Angeles).

## Football outcome

The larger 12-team, two-FLEX Trade search now completes in about 63 seconds
instead of about 225 seconds without searching fewer packages or changing the
recommendation. The smaller league remains about 31 seconds. Both searches
still return no qualifying target under their separate league policies.

## Measured cause and repair

The shared lineup optimizer counted an empty branch for every fixed starter
slot when deciding whether to use its position-allocation fast path. A normal
two-FLEX lineup therefore appeared to have 4,096 shapes even though it has only
nine full-lineup position allocations. That sent tens of thousands of ordinary
lineups through the general player-by-player bitmask solver.

The optimizer now sizes the same full-allocation space its cached helper tries
first. If a full lineup is impossible, the existing helper can still consider
empty slots or fall back to the general solver. It also precomputes the selected
players and score for each `(position, count)` once per lineup rather than
sorting and summing the same prefix for every allocation shape.

## Equivalence and safety

- League Alpha retained 5,094 enumerated packages and 27 exact evaluations.
- League Beta retained 6,226 enumerated packages and 33 exact evaluations.
- Opportunity counts, rejection counts, policy versions, and no-target results
  are unchanged; evidence hashes differ only because live manifests changed.
- Controlled brute-force, flexible-lineup, Trade, Waiver, and full regression
  tests pass.
- Release, privacy, distribution, clean-install, and external-repository checks
  pass.
- No provider authority, league calibration, recommendation threshold, search
  bound, or Sleeper state changed.
