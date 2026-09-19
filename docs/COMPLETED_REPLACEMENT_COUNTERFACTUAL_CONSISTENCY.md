# Replacement Counterfactual Consistency — completed

Completed: September 18, 2026 (America/Los_Angeles)

## Outcome

Bye and known-inactive value is no longer measured against an empty lineup
slot. The shared in-season evaluator now:

1. optimizes the roster's active bench;
2. measures starting capacity lost specifically to known unavailable players;
3. fills only that lost capacity with the best legal waiver alternatives; and
4. exposes the selected replacement IDs for audit.

The limited-player lineup optimizer preserves FLEX and SUPER_FLEX legality and
caps waiver use at unavailable-player capacity. A structural hole caused by an
imbalanced roster, trade, or add/drop does not imply permission for another
transaction.

Trade uses the shared counterfactual directly. General Waiver and K/DST
evaluation also use it, but exclude the evaluated add so its baseline is the
next alternative. Waiver candidates must have an acquirable snapshot state;
locked unowned players are not replacement options. The existing one-QB
streamer policy remains independently governed. Trade evaluation evidence is
schema version 4 and Waiver evaluation evidence is schema version 12.

Draft's legacy bye sensitivity retains its synthetic post-draft waiver pool,
but `bye_coverage_points` now means reserve production above that floor.
`bye_replacement_floor_points` and `bye_filled_points` separately disclose the
counterfactual and total production. The primary no-bye weekly-use Draft model
and all acquisition policy are unchanged.

## Verification

- Focused regressions cover active-bench-first behavior, exclusion of the
  evaluated add, acquisition-state filtering, FLEX selection, multiple byes,
  K/DST, Trade, Waiver, and Draft reporting.
- `python -m unittest discover -s tests`: 575 tests passed.
- Ruff passed on every changed Python source and test file.
- `git diff --check` passed; line-ending notices are repository-local Windows
  normalization warnings, not whitespace errors.

No live provider request, league calibration transfer, transaction submission,
or Sleeper write occurred.
