# AC-003 — Joint cross-position optimization and claim plans

Issue: [#9](https://github.com/jaretjb/RosterTheory/issues/9).
Status: implemented; [PR #17](https://github.com/jaretjb/RosterTheory/pull/17)
awaits review/merge. Prerequisite AC-002 merged in
[PR #16](https://github.com/jaretjb/RosterTheory/pull/16).

## Decision behavior

- Exact evaluation considers all supported, proved-legal drops across QB, RB,
  WR, TE, K and DST. No blanket same-position tie-break or claim-plan filter
  remains. Open slots do not require unnecessary drops.
- Specialist cross-position moves require full-roster projection improvement and
  ownership, depth, downside, contingent-upside and injured-retention protection.
  Same-position K/DST streaming policy and weights are unchanged; positional
  ranks/season points cannot justify a cross-position sacrifice.
- Incomplete roster projection evidence is explicitly quarantined in named and
  search evaluations. Affected skill/FLEX dependencies, or K/DST dependencies,
  remain blocked; unrelated missing positions do not veto an independent move.
- Best-move identity, exact results, claim priorities and specialist display use
  the same evaluated-pair order. All affirmative selected pairs appear in plans;
  affirmative specialists cannot disappear behind a display limit.

## Search coverage

The old acquisition-score cutoff, rank/ownership pruning and lineup-only bound
did not prove dominance under the joint multi-objective policy. They are removed.
Default search is exhaustive over eligible adds and supported, evidenced legal
drops. Eligibility omissions remain visible; this is not a claim of complete
provider coverage.

`waiver search <league> --exact-candidate-budget N` optionally limits initial add
evaluations. Unevaluated IDs, counts and unknown move quality are recorded. The
operation is `BUDGET-LIMITED WAIVER SEARCH`; a global optimum/no-action conclusion
is expressly unproved. The legacy `enable_pruning` API argument is accepted but
does not enable unsafe pruning. Legacy policy exact-count configuration no longer
silently truncates search. Diagnostic lineup bounds only determine search order.

## Conditional claims

Plan rows are single-move alternatives, not independent approvals to execute
together. A deterministic canonical branch re-evaluates each later original pair
against the hypothetical changed roster. Accepted prefixes also pass cumulative
original-to-final lineup, current-week, depth and downside checks. Shared drops
and consumed open slots are rejected. Failed attempts include explicit reasons.

Hypothetical ownership, acquisitions and capacity are updated consistently;
dropped players are locked, not assumed instantly available as free agents.
Nothing is sent to Sleeper. Only the listed successful prefixes are validated;
different claim outcomes or other combinations require a fresh report. This is
not exhaustive multi-claim optimization, a FAAB optimizer or a success estimate.
Branch rechecks are additional work beyond the initial add-candidate budget.

## Verification

New regressions in `tests/test_waiver_joint_plans.py` cover cross-position best
pairs, specialist/skill drops, injured retention and depth, complete and missing
projection named/search equivalence, approved plan identity/order, specialist
visibility, explicit/invalid budgets, adversarial budget omission of the actual
best move, shared slots, hypothetical ownership/capacity, changed-roster rejection
and cumulative depth loss. The cumulative-depth unit fixture injects controlled
impact values to isolate the total-loss guard; other search/evaluation fixtures
run the actual lineup/policy calculations.

Search evidence schema is 11; exact evaluation schema is 16. Saved evidence
includes conditional branch checks in its verified hash. Older evidence remains
offline replay only.

Validation: all 737 unit tests pass; Ruff and `git diff --check` pass.
No live league report, paid
provider refresh, trade, lineup change or waiver submission was performed.
AC-004 through AC-008 remain open; this does not close the overall audit.
