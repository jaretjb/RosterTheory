# Trade Assistant Phase 6 decision calibration

Date: September 5, 2026 (America/Los_Angeles)
Policy: `phase6-scenario-fallback-v1`

## Objective

The entered-package label is a transparent summary of independent football
components, not an acceptance prediction or composite trade grade. Expected
points remain primary. Reducing Cincinnati exposure cannot rescue a package
that gives away material selected-model value or usable depth.

## Version 1 gates

Every `ACCEPTABLE` package must have complete current evidence, nonnegative
user expected-lineup change, nonnegative user selected-value change after
secondary moves, and partner market value of at least -5.0 after secondary
moves. A partner below that boundary lacks a credible market-value rationale
and produces `COUNTER` unless a harder user failure produces `DECLINE`.

Risk posture changes only these tolerances:

| Posture | Maximum usable-depth loss | Maximum added offense-downside loss |
| --- | ---: | ---: |
| Conservative | 10.0 | 0.0 |
| Balanced | 25.0 | 5.0 |
| Ceiling | 40.0 | 10.0 |

All values are printed with the result. Projections, expert ranks, ownership
values, and scenario calculations are identical across postures.

## Label boundaries

- `ACCEPTABLE`: every gate passes.
- `COUNTER`: the trade concept has a positive component but misses an adjacent,
  potentially repairable value, depth, risk, or partner boundary.
- `DECLINE`: evidence/legality is incomplete; both user expected points and
  selected value are negative; selected value misses by more than 10.0; or
  depth loss is more than twice the posture limit.
- `TARGET` remains reserved for Phase 7 search results that also solve a
  diagnosed need or exploit a material selected-versus-market gap.

## Golden and live checks

The controlled three-Bengals fixture keeps Chase Brown, Ja'Marr Chase, and Tee
Higgins as distinct players and shared Cincinnati exposure. An equal-value
replacement for Higgins reduces concentration and is `ACCEPTABLE`. A discounted
replacement also reduces concentration but loses expected points and selected
value, so it is `DECLINE`.

The initial live FantasyPros example—Brown, Javonte Williams, and Higgins for
James Cook and CeeDee Lamb—correctly includes Juwan Johnson as the user's waiver
addition and Roschon Johnson as the partner's drop. Under Balanced v1 it is
`DECLINE`: expected starter value is +1.758, but selected value is -26.648 and
usable depth is -54.584. Concentration/downside improves, which demonstrates
that risk is not being applied as a forced diversification bonus.

These thresholds are the first live-testable version. Future results may justify
a new policy version; they must not silently mutate this evidence.
