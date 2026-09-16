# Completed milestone — Trade Assistant Phase 6

Completed: September 5, 2026 (America/Los_Angeles)

## Football outcome

Entered trades now receive transparent `ACCEPTABLE`, `COUNTER`, or `DECLINE`
labels. The label cannot hide its inputs: both managers' expected starter
points, usable depth, playoffs, selected/market/raw value, concentration,
independent absence, offense-wide downside/upside, waiver additions, required
drops, and every decision threshold remain separate.

Reducing a stack is not automatically beneficial. The controlled Cincinnati
audits identify Chase Brown, Ja'Marr Chase, and Tee Higgins separately and as a
shared offense. Equal-value diversification is `ACCEPTABLE`; discounted
diversification is `DECLINE` despite lower concentration.

## Delivered

- `RiskProfile` records NFL-team roster/starter membership, projected point
  share, byes, typed same-offense pairs, individual-absence tests, and broad
  downside/upside scenarios.
- `phase6-scenario-fallback-v1` configures scenario multipliers and
  conservative/balanced/ceiling thresholds without changing projections or
  rankings.
- The evidence study rejects player-pair correlation fitting because available
  history is only one PPR RB season, not multi-year all-position half-PPR data.
- `trade diagnose` reports weekly optimal points, waiver-relative positional
  needs, true usable surplus, bye gaps, concentration, and the smallest useful
  roster change.
- `trade evaluate` prints the decision, all gates, both teams' risk changes,
  compact source freshness, and saved canonical evidence.
- Secondary add/drop VORP is floored at zero so below-replacement players cannot
  create phantom trade value; raw projection and lineup consequences remain.
- Missing projections are grouped by relevance. The terminal names affected
  package/roster/secondary players but reduces 5,270 irrelevant fringe
  player-week messages to one auditable coverage line.

## Live validation

The supplied Brown/Javonte Williams/Higgins for James Cook/CeeDee Lamb package
was evaluated against current read-only League Alpha ownership. Juwan Johnson fills
the user's open slot and Roschon Johnson is the partner drop. All named players
have complete weekly projection coverage.

Balanced v1 returns `DECLINE`: user expected starter points are +1.758, selected
value is -26.648, usable depth is -54.584, and playoff impact is -0.932. The
Cincinnati downside sensitivity improves materially, proving that
diversification does not override expected-value and depth gates.

The live roster diagnosis identifies Week 13 as the smallest current coverage
gap and Cincinnati as 40.5% of projected starter points. These are current
snapshot findings, not cross-league calibration.

Saved ignored evidence:

- `data/exports/trade/league_alpha/c5309c474528ddf668ace59da19f8c937ebaf2d7c2be0c5b7cb88210fa26015d/trade_evaluation_92fbf69f21c6d6b4.json`
- `data/exports/trade/league_alpha/2b2849e0eb1abe6a97419296d3ca493e3d566f25f0effca052235fb9be7a7959/roster_diagnosis_bf433a41ae730e69.json`

## Verification

The required repository suite passes 268 tests in 4.038 seconds. Focused Trade
evaluation tests cover warnings, risk scenarios, pair types, diagnosis,
postures, decision gates, opposite Cincinnati outcomes, below-replacement
secondary moves, deterministic evidence, and CLI parsing. A later focused CLI
run also passed after replacing a Windows-incompatible arrow glyph.

## Handoff

Phase 6 is complete. No implementation milestone is active. Phase 7 is the
next candidate: league-wide need diagnosis and bounded opportunity discovery,
including the separately recorded three- and four-player package extension.
Phase 7 requires separate user approval.
