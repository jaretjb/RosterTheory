# TA-1315 — Timed Trade finder with opponent scope

Authorized October 8, 2026. The former target-first search could omit ordinary
upgrades, label useful strict counters as no offers, and stop after four exact
evaluations per lane/shape. The new baseline generation uses the existing
expert boards, projections, scoring, price bands and decision thresholds.

## Behavior

`trade search home_league` spends up to 120 seconds on discovery, construction
and exact evaluation. `--opponent 3` or an exact, unambiguous displayed team
name selects a 300-second deeper search. `--time-budget-seconds` overrides that
execution budget; preparation has a separate timer. Self, unknown and ambiguous
opponents are rejected with valid choices before discovery or diagnosis.

All nine shapes with one to three players on either side are constructed.
One-for-one generation considers every eligible rostered skill player; larger
league shapes use the existing configured pools. Opponent mode uses full
eligible rosters. Price-indexed bundles reject out-of-band pairs before lineup
evaluation. Baseline upgrades do not depend on buy/sell/consolidation labels or
the target-card display cap. Queues rotate across opponents and shapes, with
fair, estimated mutual gains evaluated first within a queue. Unique packages
share one exact decision, including repairs. Explicit exact-evaluation caps
also constrain repair work.

Up to ten ideas retain the original strict verdict and full decision gates:

- Recommended offers pass the existing exact and search gates.
- Negotiation candidates improve both lineups, pass user value, risk, depth,
  evidence, legality, chart fairness and partner usefulness checks, and fail
  only the opponent's consensus-value floor. Their strict verdict is COUNTER.
- Counteroffer ideas retain a strict COUNTER and positive user lineup gain;
  failed checks remain visible. At most three one-edit repairs add, remove or
  substitute one asset, stay within three players per side, and use the same
  evaluator. Repairs do not expand recursively.

Missing, illegal and declined cases remain diagnostics. Results are ordered by
verdict tier, user gain, opponent gain, downside, chart distance, asset count
and stable IDs. League presentation selects an opponent representative before
filling remaining slots. Fewer than ten supported ideas is reported honestly.
JSON and CSV preserve scope, raw gates, selected ideas and completed repairs;
human output shows player names, both gains, specific failed checks, required
moves and concise evidence notes.

Three-for-one consolidation retains the existing single-target premium once,
audits both adds and both drops, and checks all three incoming assets against
the opponent's final roster. Two-for-one fields remain compatible.

## Evidence and execution

`execution_profile` is optional and independent of the football policy:

```json
{
  "version": "trade-finder-execution-v1",
  "league_seconds": 120.0,
  "opponent_seconds": 300.0,
  "max_ideas": 10,
  "repairs_per_counter": 3
}
```

Only the requested local league file was migrated, adding that section while
retaining all prior football settings. Legacy policies load with execution
defaults. Legacy saved reports retain their verified offline loader. New timed
manifests verify and replay recorded completed results without rerunning a wall
clock. They are non-current and non-actionable.

Deadlines checkpoint discovery, bundle construction, exact evaluations and
secondary combinations. An interrupted package is not published as evaluated.
Per-opponent/shape counts distinguish price pruning, constructed eligible,
attempted, completed, unevaluated, unconstructed, explicit caps and pool limits.
Secondary search retains its existing bounded pool and combination rules.

Run-local Trade caches bind snapshot, projections, scoring, horizon, boards and
policy. Neutral matrix caches reuse identical exact lineup problems and waiver
representatives. Players with identical eligible slots cannot occupy more
slots than that signature allows; inferior additional players cannot improve
the exact solution. Solver reuse preserves the full unused-player list and all
coverage checks. Other assistants receive the same neutral results without any
Trade policy.

`scripts/benchmark_trade_finder.py MANIFEST EVIDENCE --output PATH` restores
verified saved inputs and evaluates at the original evidence time, explicitly
as OFFLINE / NON-ACTIONABLE. Use `--opponent ID` for the deep profile. It never
refreshes providers or submits a transaction.

## Validation

Validation includes exhaustive small-roster coverage of all nine shapes without
target cards; same-candidate scope equivalence; exclusion of unrelated roster
diagnoses; deadline rotation and unfinished-evaluation exclusion; consensus
floor-only negotiation classification; unique bounded repairs with shared
evaluation; tier/opponent ranking; cache isolation; safe price-index bounds;
300 deterministic mixed-position/overlapping-slot exact-solver comparisons;
and persisted JSON/CSV/offline replay contracts.

All 1,040 unit tests pass. Ruff, compilation, context routing, repository/index
privacy, distribution validation and an isolated wheel installation pass.
The parser compatibility fixture changes only the two new flags on the shared
Trade targets/search parser.

The requested saved-input league case constructs 94,020 pairs, prunes 71,134
by price and retains 22,886 eligible pairs. Its 120.025-second run finishes
22 unique exact evaluations including one repair, returning ten ideas: one
strict recommendation, two negotiation candidates and seven counters. The
previous saved result had zero passing offers. One protected roster coverage
gap and existing asset-price exclusions remain explicit; this benchmark is
offline and not a current recommendation.

The selected-opponent case constructs 112,346 pairs, prunes 82,647 by price and
retains 29,699 eligible pairs. Its 300.017-second run completes 27 unique exact
evaluations, including 13 completed repair checks with shared-cache reuse.
All nine shapes receive exact evaluations. Its ten ideas comprise one strict
recommendation, six negotiation candidates and three counters. Coverage keeps
29,684 constructed primary packages unevaluated. Both profiles stop at their
time budget rather than claiming exhaustive search.

The known mutually useful single-player swap appears as a negotiation candidate
with user lineup gain +6.485 and opponent gain +6.434; its strict COUNTER still
fails only the opponent consensus-value floor (-10.482 versus -5). The active
optimizer record exactly matches the original saved record. The human preview
is 92 lines / 5,055 characters, with detailed repeated warnings retained in JSON.
