# Completed Trade Assistant milestone: Phase 4 value boards

Completed September 4, 2026 (America/Los_Angeles).

## Football outcome

RosterTheory can now show where its selected in-season experts and the public
market disagree on player value using the same point scale. These are discovery
signals only: Phase 4 does not infer an opponent's preference, evaluate a trade
package, apply final risk labels, or write to Sleeper.

## Expert selection

The dated selection study is retained as private local evidence because it
contains FantasyPros-derived accuracy rows and expert identifiers. It selected
a bounded pool using equal-year, field-normalized weekly in-season accuracy,
coverage adjustment, current availability, and a per-site concentration cap.
Unavailable seasons remain explicit missing evidence rather than being treated
as poor finishes. No preseason accuracy enters the selector, and the evidence
is never labeled ROS accuracy.

The API itself was authenticated and operational. The only unavailable
authentication was a separate browser session for the subscriber website; it
did not prevent rank, projection, or current expert API retrieval.

## Board model

- Current selected-expert ballots are aggregated independently from untouched
  market ECR. Raw contributions, omissions, dispersion, pre-shrink rank, and
  final rank remain auditable.
- Adaptive ECR shrinkage supplies only missing selected-expert weight. Complete
  ballots receive zero shrinkage; a fixed preseason blend or named anchor was
  rejected.
- Until direct ROS ranks publish, both boards use the same `WEEKLY-PROXY`
  horizon. Weeks 1-17 consensus projections are scored under live Sleeper rules
  to form one positional distribution.
- Each board assigns that distribution by its own positional rank order. Missing
  slots are retained, not collapsed. The controlled RB10 test assigns 150 points
  to the RB10 on either board.
- Both boards use the same current free-agent replacement zero. Board-specific
  PAVA curves are monotone and cannot invert positional order.
- The signed common-scale gap is `market VORP - selected VORP`: positive is a
  sell-high signal and negative is a buy-low signal.

## Live read-only validation

`python -m roster_theory trade values league_alpha` completed with:

- 234 selected, selected-raw, market, and valuation-gap rows;
- 239 selected-rank evidence rows, including five non-tradeable placeholders
  that preserve rank slots;
- 202 rows with all selected experts contributing and 37 partial rows;
- projection curves covering QB 25, RB 102, WR 76, and TE 36;
- common remaining-week baselines of QB 264.893, RB 139.206, WR 127.902, and
  TE 131.458;
- 21 FantasyPros cache hits, zero new calls on the confirmation run, and 428 of
  the 500 daily requests remaining after all Phase 4 exploration;
- manifest `eef47c6e968c11ee457aedae8d278b11ccad0f51c2bd0a008f9cca67b775b812`
  and evidence hash
  `3ec694871d1acf64cf4128a33959b2f13cdfa0d14b856527385d0132e7ede8f6`.

The ignored local artifact is
`data/exports/trade/league_alpha/eef47c6e968c11ee457aedae8d278b11ccad0f51c2bd0a008f9cca67b775b812/value_boards.json`.
It warns that weekly ranks are not ROS ranks and that valuation gaps are not
trade recommendations or opponent preferences.

## Verification and stopping point

The full regression suite passes 220 tests, including annual accuracy parsing,
expert selection, contributor normalization, provider identity isolation,
horizon matching, weekly coverage, rank-slot transfer, monotone curves, common
replacement value, gap direction, deterministic exports, and Draft regressions.

TA-401 through TA-410 are complete. Phase 5 (TA-501 through TA-508) is the next
candidate milestone: it will evaluate user-entered packages and team-level
lineup/depth effects without yet applying final risk labels. It is not active.
