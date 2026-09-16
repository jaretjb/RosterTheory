# Completed Trade Assistant milestone: Phase 5 entered-package evaluation

Completed September 5, 2026 (America/Los_Angeles).

## Football outcome

RosterTheory can evaluate a user-entered player-only trade against both current
rosters. It shows the weekly starters displaced or added, total and playoff
projected-point changes, usable depth above plausible waivers, selected-expert
and market ownership value exchanged, raw projection value, and any add/drop
needed to make unequal packages roster-neutral.

The evaluator does not call a trade good or bad. `decision_label` remains null
and terminal output leads with `NO FINAL DECISION LABEL`; correlation risk,
roster diagnosis, and calibrated `ACCEPTABLE/TARGET/COUNTER/DECLINE` gates
remain Phase 6 work.

## Delivered contracts

- `PlayerAsset` and two-roster `TradePackage` accept only exact provider IDs or
  unique normalized names. Ownership, duplicate assets, self-trades, unknown
  players, three-team receives, and unsupported sizes stop visibly.
- Supported packages are 1-for-1, 2-for-1, 1-for-2, and 2-for-2, applied to
  both rosters simultaneously.
- The indexed weekly matrix uses league-scored projections, explicit bye and
  known-inactive zeroes, missing-row warnings, and configurable playoff weight.
- Each roster is optimized before and after by week. Results retain starting
  entrants/exits, best/worst week, full-horizon and playoff delta, and
  absence-based depth above plausible waiver replacements.
- Unequal packages enumerate the required add or drop, retain the chosen and
  next-best result, and accept explicit user overrides.
- Selected, market, and raw-projection ownership views remain separate for both
  teams. No opaque combined score is introduced.
- Provisional reversal conditions name missing coverage, traded-player
  availability, add/drop dependence, selected-versus-market sign disagreement,
  and playoff sign sensitivity.
- `trade evaluate` provides compact terminal or canonical JSON output and saves
  manifest-linked, hash-checked evidence. Offline replay is explicitly labeled
  `OFFLINE/NON-CURRENT`.
- Incomplete selected evidence becomes `ECR-ONLY`; rank-only,
  schedule-partial, and reserve-rule cases are explicitly labeled and cannot
  claim a complete projected result or proven automatic legality.

## Controlled hand audits

The three-week 2-for-1 fixture sends an 8-point WR and 1-point WR for a
12-point WR. With the best 7-point waiver WR added, the user's optimized lineup
changes from 23 to 29 points per week: +18 over the horizon. The partner drops
the incoming 1-point WR and changes from 22 to 18: -12. Forcing a 3-point RB add
and a different partner drop changes the totals to +12 and -18.

A separate sensitivity reduces the acquired WR to 6 points and raises the best
waiver WR to 9. Automatic waiver selection makes the user's horizon result +6;
forcing the inferior add makes it -6. This proves the secondary transaction can
reverse the football result and must remain visible.

Perspective reversal preserves each exact team result while negating the
sent/received market package delta. Cross-position and playoff-weight fixtures
also match their hand totals.

## Verification and stopping point

`python -m compileall -q src tests` passes. The required full regression suite
passes 254 tests in 3.549 seconds, including all Draft Assistant regressions and
19 Phase 5 package, projection, lineup, add/drop, degraded-mode, evidence, and
CLI tests. Tests use fixtures and make no live provider calls.

No real trade package was evaluated because the user did not enter one. No
Sleeper write, recommendation label, opponent-preference claim, or new paid
provider call occurred.

TA-501 through TA-508 are complete. Phase 6 is the next candidate milestone and
requires separate user approval.
