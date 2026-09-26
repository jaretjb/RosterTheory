# AC-008 — End-to-end release gates and measured optimization

Status: implemented on `codex/ac-008-release-gates`; merge pending. Issue #14.
The reliability audit remains open pending merge and any future dated calibration.
No live provider refresh, league action, or Sleeper mutation was run.

## Decision and release gates

- A regression failed before the cache change: one controlled Trade run invoked
  exact evaluation 180 times for 126 distinct packages (54 cross-lane repeats).
  It now calls exact evaluation once per distinct package, while retaining all
  180 lane decisions and applying market/strategy screens separately per lane.
- A valid construction market rejection now occurs before expensive lineup
  calculations. It still records the same rejection and candidate coverage;
  no new recommendation pruning or budget is introduced.
- Waiver, broad Trade, and target Trade expose stage timing, coverage, and cache
  counts through run diagnostics outside hashed decision evidence. Waiver and
  target production reports also show saved evidence size. Timing cannot alter
  deterministic replay hashes.
- Duplicate exact evaluations in the Trade display report link to the first
  full occurrence by evidence hash. The saved, hash-verified evidence remains
  complete, and every opportunity retains its decision and lane metadata.
- Separate alpha/beta Waiver fixtures exercise distinct league policies.
  Existing supported-format, bounded/exhaustive, offline replay, provider
  freshness, and output-path regressions ran in the full suite. No league's
  decision result is transferred to another league.

## Measurements

Windows, Python 3.13, three runs per case with `tracemalloc`; numbers are
within-process medians, not a production speed guarantee. The controlled
fixtures are synthetic. Current runs can be repeated with
`PYTHONPATH=src;. python scripts/benchmark_ac008.py --repeat 3` in PowerShell.
Baseline values were captured before source changes using the same fixture
constructors and measurement method. Fixture timestamps differ between
baseline and changed runs, so their evidence hashes are not compared directly;
coverage counts and repeat-run hashes are checked separately.
As an additional same-snapshot check, the merged-main evaluator and this branch
produced byte-for-byte equal result payloads and evidence hashes for permissive
and strict target search, broad Trade search, and exhaustive Waiver search.

| Fixture | Before | After | Peak memory before → after | Evidence bytes | Coverage |
| --- | ---: | ---: | ---: | ---: | --- |
| Trade target, permissive market | 7.303 s | 6.334 s | 13.37 → 12.92 MB | 1,722,651 both | 180 evaluated, 151 accepted; 54 cached repeats |
| Trade target, strict market | 1.190 s | 0.777 s | 2.30 → 1.73 MB | 237,315 both | 180 enumerated, 169 rejected, 11 evaluated |
| Broad Trade search | 0.211 s | 0.213 s | 0.49 → 0.49 MB | 22,783 both | 225 enumerated, 3 attempted, 1 accepted |
| Waiver search | 0.620 s | 0.599 s | 1.00 → 1.02 MB | 171,498 both | 4/4 eligible adds exact; 0 pruned |

Only the target optimization has a meaningful measured improvement in these
fixtures. Broad Trade and Waiver differences are noise-level; no speedup is
claimed for them. A separate full Trade report fixture containing 66 offers and
11 repeated exact-evaluation proofs went from 1,722,690 to 1,546,684 JSON
bytes (176,006 fewer, about 10.2%) in the display representation; its saved
evidence file is unchanged.

## Verification and limitations

Focused tests: Trade target optimizer, Trade target workflow, Waiver search,
and broad Trade search passed. Full suite: 797 tests passed. Ruff and
`git diff --check` passed. Saved evidence replay remains offline/non-current.
Synthetic fixtures and local timing do not prove live league calibration or
all possible Trade package dominance. Existing candidate pools and exact budgets
remain disclosed; no hidden pruning is authorized by this milestone.
