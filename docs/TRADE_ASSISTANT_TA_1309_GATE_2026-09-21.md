# TA-1309 read-only gate checkpoint — September 21, 2026

Historical checkpoint: the coverage failure below was fixed and both leagues
were rerun. See `COMPLETED_TRADE_ASSISTANT_TA_1309.md` for the final gate.

Status: **incomplete gate**, not a trade recommendation. This public record
contains aggregate results only. League-local source data, policies, feedback
templates, and search evidence remain in ignored paths.

## Fresh league-isolated search

Each configured league used its own provisional TA-1308 target policy, fresh
Sleeper roster state, and refreshed Trade inputs. No trade, lineup, waiver, or
other Sleeper write was requested.

| Result | League A | League B |
| --- | ---: | ---: |
| Pricing mode | ECR-PROXY | ECR-PROXY |
| BUY_LOW WATCH cards | 0 | 2 |
| SELL_HIGH WATCH cards | 0 | 0 |
| CONSOLIDATE WATCH cards | 8 | 8 |
| NEED_FIT WATCH cards | 7 | 8 |
| Exact package decisions evaluated | 49 | 70 |
| Intrinsic WIN decisions | 8 | 2 |
| Accepted offers | 0 | 0 |
| Completed outcomes in performance history | 0 | 0 |

All target cards remained WATCH. A selected-expert intrinsic WIN is not proof
that the package is market-fair or partner-credible. Every evaluated package's
market axis was explicitly labeled `ECR-PROXY`; there was no direct-chart FAIR
claim. The two BUY_LOW cards in League B are ranking/value-gap signals, not
verified recent-underperformance bargains. There was no supported SELL_HIGH
calculation in these runs. The 5% consolidation premium and 0/5/10% sensitivity
cannot be tested against live chart prices in proxy mode.

## Direct-chart coverage finding

The Stats Guy Fantasy response reached the normalization gate, but its direct
chart did not cover 610 IDs in the required player universe. Of these, 609
for League A and 607 for League B were free agents; 1 and 3 respectively were
rostered. No retained target or evaluated package asset was among the missing
IDs. The current rule intentionally downgrades the *whole run* when any
required player lacks a direct price, avoiding mixed chart/proxy claims. The
rule currently treats the broad valuation universe as required, including
free agents, and the downstream target gate also requires every fully valued
rostered player. Narrowing either gate needs an explicit coverage policy and
per-offer evidence check, not a silent exclusion.

The runs also emitted over 6,900 warnings each, overwhelmingly repeated
missing-projection notices for the broad player universe. This obscures the
actionable limitations and needs aggregation before a human-readable live
report is practical.

## Verification and remaining gate

- Full suite: 643 tests passed; focused Trade/market/evaluation suite: 72
  tests passed; Ruff passed.
- Both saved search hashes verified on offline replay, which correctly labels
  replay as `OFFLINE/NON-CURRENT`. The saved manifests matched their current
  league snapshots; all 44 snapshot source stamps per league were fresh.
- Tests cover the chart-free entered evaluator, direct-chart/proxy fallback,
  deterministic target/offer replay, and GET-only provider probing. The live
  searches exercised the proxy fallback. A fully disconnected finder was not
  run because current Sleeper roster reads remain required.
- The `.env` file, provisional league policies, and generated evidence are
  ignored by Git. No raw provider payload, player row, API key, or private
  league identifier is included in this record.

TA-1309 remains active. Before calling the finder chart-validated, decide how
to require direct prices for only assets that can enter a target or exact
package, visibly exclude unsupported assets, preserve a single honest pricing
mode, and aggregate missing-projection warnings. Then repeat both fresh runs
and reconcile actual chart fairness and consolidation sensitivity. TA-1310
still owns empirical, league-local calibration after completed outcomes and
dated decisions accumulate.
