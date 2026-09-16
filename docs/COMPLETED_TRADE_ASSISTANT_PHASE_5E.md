# Completed Trade Assistant milestone: Phase 5E larger entered packages

Completed September 5, 2026 (America/Los_Angeles).

## Football outcome

`trade evaluate` now supports player packages with one through four players on
either side. This includes the common 3-for-3 and 4-for-4 cases as well as
unequal packages such as 2-for-3 and 1-for-4.

For an unequal trade, the roster sending more players than it receives fills
every resulting open active-roster slot from the current waiver pool. The other
roster includes every required drop. Those secondary moves are included in
weekly lineup, depth, selected-expert, market, and raw-projection results for
both teams.

## Delivered behavior

- Exact ID/name, ownership, uniqueness, two-team, and simultaneous-exchange
  checks now accept one through four players per side.
- Secondary moves are represented as sets while retaining the convenient
  singular view for existing 2-for-1 callers.
- Up to three additions or drops are evaluated jointly. The solver does not
  assume that choosing one player at a time produces the best final roster.
- The chosen and next-best move sets, eligible and evaluated pool sizes,
  combinations considered, and any bounded-search warning are preserved in
  terminal and JSON evidence.
- Automatic search considers at most 18 individually screened secondary
  players and 1,000 combinations per roster. A bounded result is visibly
  labeled `BOUNDED-SECONDARY-SEARCH` rather than presented as exhaustive.
- Repeating `--add` or `--drop` supplies partial or complete move-set overrides.
  Rank-only unequal packages require an explicit player for every necessary
  addition and drop because lineup projections cannot choose them safely.
- Evaluation evidence schema 2 records plural move sets and remains
  deterministic and hash-checked. No final decision label was added.

## Controlled evidence

- Hand-audited 3-for-3 and 4-for-4 cases produce -3 horizon points for one
  roster and +3 for the other, with no secondary transaction.
- The 2-for-3 fixture proves the team sending three players receives the best
  roster-relevant waiver addition, while the other team includes its required
  drop. The waiver player's market value is included in the result.
- The 4-for-1 fixture jointly selects three waiver additions and three drops,
  supports three explicit overrides on each side, and preserves exact results
  when team perspective is reversed.
- A multi-week fixture makes the best individual waiver player a greedy trap:
  the jointly selected two-player waiver set has the higher final weekly-lineup
  total.
- A forced one-combination fixture proves the hard search bound and visible
  degraded-mode label.

## Verification and stopping point

`python -m compileall -q src tests` passes. The required full regression suite
passes 261 tests in 3.709 seconds, including 26 entered-package tests and all
Draft Assistant regressions. Tests use fixtures and make no live provider
calls.

The larger-package evaluator is ready for initial testing with an actual trade
idea. No real package was evaluated during implementation, and no Sleeper
write, final recommendation label, or new paid provider call occurred.

TA-509 is complete. Phase 6 remains a separately approved milestone.
