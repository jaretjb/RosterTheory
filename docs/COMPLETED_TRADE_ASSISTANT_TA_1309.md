# TA-1309 — Trade Finder live read-only gate complete

Completed September 21, 2026 (America/Los_Angeles). This public record uses
aggregate labels only; local league/player evidence and normalized trade charts
remain in ignored `data/` paths. The finder remains decision support, not a
trade submission or an opponent-acceptance prediction.

## Coverage and prior-chart behavior

The Stats Guy Fantasy chart was not empty. The old all-or-nothing gate required
prices for the broad valuation universe, including hundreds of free agents.
Current chart pricing now applies to targets and exact packages whose actual
assets all have current prices. Missing current prices are reported explicitly.
If a compatible league-local chart from the preceding eight days covers a
missing candidate, all assets in that candidate's package use that one prior
chart. Its market status is `PRIOR_WEEK_MARKET`, indicative only; it cannot
yield a current `FAIR` verdict, a consolidation premium claim, or an accepted
offer. No package blends chart dates. Assets missing from both charts are
excluded with a count and individual exclusion evidence in the private report.

The normal source-resolution ladder is current API, authorized current import,
still-current cached chart if the source fails, dated prior chart (up to eight
days old), then explicit `ECR-PROXY`. Archives are partitioned by league,
season, and redraft format under ignored `data/cache/trade/market/`. Tampered,
wrong-season, wrong-format, future, or expired charts are not usable. Detailed
missing-projection cells remain in the evaluation matrix while the finder
report aggregates the thousands of repeated universe warnings into a count.

## Fresh separate league validation

| Result | League A | League B |
| --- | ---: | ---: |
| Price mode | Current Stats Guy Fantasy chart | Current Stats Guy Fantasy chart |
| Retained target cards | 23 | 22 |
| Rostered assets excluded for missing current price | 1 | 3 |
| Exact packages evaluated | 121 | 82 |
| Accepted modeled offers | 4 | 0 |
| Consolidation 2-for-1 calculations with 0/5/10% sensitivity | 10 | 10 |
| Aggregated warnings | 10 | 10 |

The four retained League A offers were intrinsic `WIN` and current-chart
`FAIR`; two came from buy-low targets and two from need-fit targets. No
consolidation package was retained. League B honestly produced no accepted
offer. A WATCH target is not called obtainable, and a modeled fair offer does
not imply its owner will accept it. Both runs had insufficient completed-game
performance history. The 5% consolidation premium is still an uncalibrated
provisional setting; TA-1310 owns empirical promotion.

## Verification

- Both fresh search artifacts passed hash-verified offline replay and matched
  current league-local manifests. Their chart fairness statuses remained
  separate from intrinsic outcomes. The previous ECR-proxy run is preserved as
  historical gate evidence, not treated as the latest run.
- 649 full-suite tests and Ruff pass. Focused fixtures cover partial-current
  chart coverage, per-package prior-chart pricing, stale-status refusal to
  accept an offer, format/age isolation, chart-free entered evaluation, and
  deterministic replay. A live prior-week fallback could not be exercised yet
  because no earlier chart was archived; the source path was tested with dated
  fixtures.
- `.env`, league policies, generated search evidence, and normalized chart
  archives are ignored by Git. Provider access and Sleeper reads are GET-only;
  no Sleeper trade or roster action was sent. No API key, raw licensed payload,
  private player row, or league identifier appears in this public record.
