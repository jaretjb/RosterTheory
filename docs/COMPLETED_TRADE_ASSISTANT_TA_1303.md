# TA-1303 — Leakage-safe recent-performance context

Completed September 21, 2026 (America/Los_Angeles) on
`codex/ta-1303-performance-context`. This is an optional evidence boundary for
Trade target discovery, not a new expert ranking or recommendation policy.

`trade/performance.py` joins completed, league-scored player outcomes to only
the latest compatible projection and position-rank captures made before each
game. Point and rank captures may have different pregame timestamps. The
rolling-origin decision timestamp and completed-week boundary exclude future
results; their actual values are masked in historical evidence. Conflicting
simultaneous captures fail explicitly, and league/season or scoring-fingerprint
mismatches cannot be transferred. Every residual retains expected and actual
values where eligible, metric-specific capture times and sources, the completed
game/capture times, availability, inclusion status, and exclusion reason.

Bye, inactive, partial, unsupported position/scoring, missing comparable
metric, and postgame-only cases are excluded with visible reasons. A versioned
`PerformancePolicy` supplies the lookback window, position-specific point and
rank scales, minimum sample, shrinkage prior, signal boundary, and freshness
limit; it has no production numerical defaults. Short samples shrink toward
zero and cannot support a target until the minimum is met. Stale or mixed-
position context is also claim-disabled. Conflicting point/rank directions
neutralize the signal.

The resulting `TargetPerformanceContext` plugs into existing deterministic
`discover_trade_targets`. It can explain or order target cards but cannot
alter the selected-expert board, independently create an intrinsic/market
edge, or block discovery when absent. A stale context no longer contributes
ranking support. Six focused rolling-origin fixtures verify future/postgame
exclusion, independent captures, availability, rank-only evidence, shrinkage,
position scaling, league isolation, stale/small samples, deterministic hash,
and unchanged expert order. All 630 tests and Ruff pass. No live provider
request, private history evidence, calibration, Sleeper write, or secret was
used.

TA-1308 is now the next dependency-ready task. It must provide the separately
authorized, league-local historical study, choose its performance windows and
other decision thresholds with holdouts, and wire validated context into the
live target workflow. Until then, CLI searches retain explicit
`UNAVAILABLE` performance context; no fixture parameters are promoted.
