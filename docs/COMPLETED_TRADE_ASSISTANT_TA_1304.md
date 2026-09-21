# Trade Assistant TA-1304 completion

Completed: September 20, 2026 (America/Los_Angeles)

## Football outcome

Trade discovery can now identify whom to acquire, whom to shop, and which
opponent player could support a consolidation before it constructs an offer.
The result keeps the manager's intrinsic football view separate from community
exchange price and retains every target as `WATCH` until later package search
proves a legal, partner-credible offer.

## Delivered contract

`src/roster_theory/trade/targets.py` adds deterministic discovery for:

- `BUY_LOW`: a material negative
  `market_price_percentile - intrinsic_percentile` plus real user lineup or
  depth fit;
- `SELL_HIGH`: a material positive premium plus contained exact user-roster
  marginal cost;
- `CONSOLIDATE`: an opponent player who clears the explicit weighted-horizon
  starter-upgrade threshold, while clearly deferring outgoing-pair, drop, and
  partner-use proof; and
- `NEED_FIT`: the bilateral roster-fit fallback when market price is aligned.

Each target card independently preserves selected-expert value, full market
ECR, direct trade-market price or explicit `ECR-PROXY`, normalized premium,
exact-roster lineup/depth fit, modeled owner disposability, optional compatible
performance context, ownership/source timestamps, warnings, and the ordered
lexicographic ranking factors. There is no combined target score.

Owner disposability is explicitly modeled evidence, never a claim about a
manager's preference. Every card has `partner_credible_offer_found=false` and
`obtainable=false`. Partial, stale, incompatible, or unconfirmed direct chart
coverage disables direct pricing for the complete run and reports the reason;
it never mixes chart and proxy prices silently.

Thresholds are required through an explicit `TargetDiscoveryConfig`. They are
not treated as calibrated defaults; league-specific calibration remains
TA-1308 work.

## Verification

Seven focused synthetic tests prove:

- the intended player and authoritative owner in all four target lanes;
- separate intrinsic, market-ECR, trade-price, team-fit, and freshness fields;
- identical valid targets without recent-performance context;
- `WATCH` status with no preference or obtainability claim;
- deterministic lexicographic ordering and visible lane-limit exclusions;
- complete-run `ECR-PROXY` behavior when the chart is unavailable; and
- named fallback evidence when one required rostered player lacks a chart row.

`python -m unittest discover -s tests` passes all 612 tests. `python -m ruff
check .` passes, and the new source/tests pass Ruff format checking. No provider
request, live league operation, calibration transfer, recommendation, or
Sleeper write occurred.

## Handoff

TA-1305 is the next P0 task. It must construct packages around these target
lanes and apply separate intrinsic, market-fairness, partner, legality, and
downside gates. TA-1306 will prove full consolidation mechanics, and TA-1307
will expose the shared target evidence through the CLI and search report.
