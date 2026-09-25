# Trade Assistant current status

Updated: September 25, 2026 (America/Los_Angeles)

Current handoff: AC-001 audit cleanup is implemented and tested, pending PR
review. Current injury status no longer erases future supplied projections, and
source omissions remain missing evidence rather than complete active zeroes.
Provider normalization and rank-slot curves use the same provenance contract.
All 696 tests and Ruff pass; no live provider call or Sleeper write occurred.
Evidence: `docs/COMPLETED_ASSISTANT_RELIABILITY_AC_001.md`.

The audit remains open. AC-002–AC-008 in `docs/ASSISTANT_RELIABILITY_TASKS.md`
track scoped missing-player recovery, verdict/secondary-move consistency,
format/freshness/provenance support, and integration/performance work. AC-002
(issue #8) is next; no further implementation milestone is active.
TA-1312 ROS-panel resilience was previously completed on September 23, as
recorded in `ACTIVE_MILESTONE.md`; the older status below is historical.

Stopping point: TA-1309 Phase 13 read-only gate is complete. TA-1301–TA-1309
are complete; TA-1310 retains empirical rolling-origin calibration after
sufficient evidence exists. No Trade implementation is active.

TA-1309 now keeps current chart pricing for covered targets and packages,
excludes missing assets explicitly, and supports a league-local archived
prior-week chart for whole-package indicative analysis without current FAIR
or accepted-offer claims. Fresh separate league runs used the current chart:
one found four offers, the other none. No completed-performance history
exists yet and the 5% premium remains provisional. All 649 tests and Ruff pass.
Details: `docs/COMPLETED_TRADE_ASSISTANT_TA_1309.md`.

TA-1308 connects prospective pregame-versus-completed performance context to
the normal finder, labels separate league-local policies
`PROVISIONAL_HEURISTIC`, shows direct-chart 0/5/10% consolidation fairness
sensitivity, and writes non-overwriting feedback templates. Its separate-axis
rolling-origin study harness remains unpromoted because local history is
insufficient. At the TA-1308 handoff, 643 tests and Ruff passed and no live
finder had run. Details:
`docs/COMPLETED_TRADE_ASSISTANT_TA_1308.md`.

TA-1303 joins completed results only to compatible pregame point/rank captures
at a rolling-origin decision time. It retains exclusion/provenance rows,
position-aware shrinkage, and claim-disabled small/stale samples. Expert order
is unchanged. Six focused tests, all 630 tests, and Ruff pass. No live history
or private evidence was read. Details:
`docs/COMPLETED_TRADE_ASSISTANT_TA_1303.md`.

TA-1307 adds target-first CLI cards/offers and separate intrinsic/market
verdicts. Fresh read-only league validation remains TA-1309. Details:
`docs/COMPLETED_TRADE_ASSISTANT_TA_1307.md`.

TA-1306 adds exact 2-for-1 consolidation with visible premium, add/drop, and
partner-use evidence. TA-1310 owns empirical calibration. Details:
`docs/COMPLETED_TRADE_ASSISTANT_TA_1306.md`.

Earlier ingestion, discovery, and optimizer details:
`docs/COMPLETED_TRADE_ASSISTANT_TA_1302.md`,
`docs/COMPLETED_TRADE_ASSISTANT_TA_1304.md`, and
`docs/COMPLETED_TRADE_ASSISTANT_TA_1305.md`.
