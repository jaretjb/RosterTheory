# Trade Assistant TA-1305 completion

Completed: September 20, 2026 (America/Los_Angeles)

## Football outcome

Package search can now start with an identified player opportunity instead of
hoping a small generic pool discovers the strategy accidentally. Each target
lane receives its own package-shape budget, so a useful 2-for-1 is not crowded
out by cheaper 1-for-1 evaluations. Passing offers must improve the user's
exact team while also clearing separate market, partner-roster, legality,
depth, and downside gates.

## Delivered optimizer

`src/roster_theory/trade/target_optimizer.py` adds a bounded deterministic
optimizer around the TA-1304 target evidence:

- `BUY_LOW`, `SELL_HIGH`, `CONSOLIDATE`, and `NEED_FIT` are searched as
  independent lanes;
- 1-for-1, 2-for-1, 1-for-2, and 2-for-2 each receive an explicit exact-
  evaluation budget inside every lane;
- outgoing seeds expose usable surplus, exact standalone marginal lineup cost,
  partner positional need, market price, selected value, and distance from the
  target's price;
- bounded incoming pools prefer actual user lineup gain and diagnosed need;
- a broad construction band prunes implausible packages cheaply, while the
  narrower final market band remains an independent exact decision gate;
- direct trade-market values produce `FAIR`, `USER_UNDERPAY`, or
  `USER_OVERPAY`; fallback construction stays labeled `ECR-PROXY` and never
  claims chart fairness;
- exact decisions preserve intrinsic outcome, market fairness, selected and
  market-ECR deltas, team impacts, partner plausibility, depth, downside,
  add/drop consequences, and rejection reason separately; and
- Pareto frontiers are formed within each lane. Asset-count simplicity cannot
  suppress the consolidation lane.

The optimizer verifies that the selected, market-ECR, and direct trade-market
boards are exactly the evidence used for target discovery. It reports
enumerated, prefiltered, deduplicated, eligible, attempted, evaluated, accepted,
and runtime-pruned counts for all 16 lane/package-size groups.

Targets remain `WATCH` when no passing package exists. A passing construction
is labeled `OFFER_FOUND`, but `obtainable` remains false and no manager
preference or acceptance probability is inferred.

All numerical thresholds and all 16 budgets are required through an explicit
`TargetOptimizerConfig`. They are test policy, not calibrated production
defaults; separate league calibration remains TA-1308.

## Verification

Six focused synthetic tests prove:

- a one-evaluation budget in every lane/package-size retains the same best
  intrinsic result as controlled exhaustive evaluation in all 16 groups;
- the consolidation 2-for-1 budget survives independently alongside the
  buy-low 1-for-1 budget;
- exact decisions distinguish a market-unfair intrinsic win from a market-fair
  intrinsic loss;
- `ECR-PROXY` constrains search without making chart-fairness claims;
- zero-budget and no-passing-offer targets remain deterministic `WATCH` items;
  and
- mismatched target/value evidence fails closed.

`python -m unittest discover -s tests` passes all 618 tests. `python -m ruff
check .` passes, and the affected source/tests pass Ruff format checking. No
provider request, live league operation, calibration transfer, recommendation,
or Sleeper write occurred.

## Handoff

TA-1306 is the next P0 task. It must strengthen the `CONSOLIDATE` 2-for-1 lane
with an explicit premium, the user's resulting add, the partner's forced drop,
and proof that both outgoing assets provide partner lineup or depth use. TA-1307
will then connect target discovery and package optimization to the shared CLI
and evidence reports.
