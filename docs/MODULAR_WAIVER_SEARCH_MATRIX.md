# MA-005c: exact-reference Waiver full-search evidence

September 29, 2026. This slice runs complete candidate search on the two
synthetic reference profiles. Each uses its own existing controlled-fixture
Waiver policy and invented three-week points. It makes no provider request
and does not change any recommendation code.

## Checked cases

| Profile | User roster | Eligible adds | Capacity result |
| --- | --- | ---: | --- |
| Reference A | Full | 6 | Exact evaluations select a drop |
| Reference A | One open active place | 7 | Exact evaluations need no drop |
| Reference B | Full | 6 | Exact evaluations select a drop |
| Reference B | One open active place | 7 | Exact evaluations need no drop |

Opening a place releases the removed synthetic player into the available
pool, accounting for the seventh candidate. Every eligible add receives an
exact evaluation, with no candidate budget exclusion. Search evidence is
bound to the matching league and policy; outputs report no Sleeper write.
Removing the free RB's projection excludes that add with
`INCOMPLETE_PROJECTION_COVERAGE` in each profile while other adds remain
independently evaluated. The focused six-search test took 130 seconds total
on this Windows host, so each case finished within the existing ten-minute
completion gate; this is not a portable timing assertion.

## Remaining readiness work

These are controlled fixtures, not current league observations. A Waiver
recommendation for tonight still needs a current Sleeper snapshot, complete
league-scored provider inputs, fresh availability and news evidence, the
selected league's own policy, and publication revalidation. MA-005's wider
roster-shape, ancillary-mode, live-source and policy gates remain open.
Neither reference profile nor the 12-shape family is promoted to live support
by this test. No league calibration is transferred.
