# AC-007 — Freshness, readiness, provenance, and handoff contracts

Merged for issue #13, September 25, 2026, in
[PR #22](https://github.com/jaretjb/RosterTheory/pull/22) (commit `35c76ba9ff105b196ba8e04b4eb09dce460e1b0d`); all 20 checks passed and issue #13 is closed.
AC-008 merged in PR #23; the reliability audit remains open.

## Behavior and boundaries

- Sleeper stamps preserve per-endpoint observation times and payload hashes.
  A cached player directory keeps its original observation time. FantasyPros
  provenance includes original observation time, fetch completion time when known,
  cache status, parameters, payload hash and source-specific maximum age.
- News is explicitly a finite global feed (100 records), not complete per-player
  news. A missing mention is not an all-clear. Per the user's direction, a feed is
  reused for one hour; final league revalidation never fetches FantasyPros news.
  Legacy `material_news_fresh` means freshness of the available news evidence,
  not proof that all relevant news about that player was collected. The saved
  `news_coverage` declaration and report warning make that distinction explicit.
- Trade exact/comparison/search/target computations use an immutable admitted
  as-of scope, so a long search does not age individual candidates differently.
  Waiver uses its explicit evaluation time; its wall-clock publication clock is
  independently injectable for tests. Offline replay cannot freeze the live clock.
- Before actionable files are written, GET-only revalidation compares ownership,
  lineup/reserve membership, league rules, player availability/eligibility and
  transactions. Waiver also rechecks matchup starters and kickoff boundaries.
  Changed facts or expired contributing sources require a refresh/rerun, not a
  stale recommendation. Missing inputs remain separately disclosed.
- Input completeness, search coverage, candidate confidence and informational
  warnings are distinct axes. Known ownership/out-of-scope exclusions are not
  missing data. An empty exhaustive search can be ready; a bounded search cannot
  establish a global best move or no-action conclusion.

## Reproducibility

Each actionable workflow saves a sibling `*.manifest.json` with schema version,
source-build hash, policy/scoring hashes, source stamps, evaluation/publication
times, volatile-fact verification and normalized snapshot/input/policy evidence.
The whole manifest and replay payload are hashed. Machine reports expose compact
provenance summaries without duplicating all replay data. Waiver input schema is
10; older input schemas remain readable with legacy provenance visibly unknown.

Use `roster_theory.waiver.replay.replay_waiver_manifest(path)` or
`roster_theory.trade.replay.replay_trade_manifest(path)` with a saved manifest.
These verify the manifest and source build, reconstruct only code-selected record
types, rerun the pure decision computation at the recorded time, and require the
original decision hash. They make no provider calls. Returned evidence is explicitly
`OFFLINE / NON-ACTIONABLE`, even when the reproduced historical verdict was positive.

## Verification

Regressions preceded implementation. Focused acceptance covers original cache
age, per-source expiry, hourly news reuse, finite-feed scope, fake-clock long runs,
ownership/status changes, revalidation expiry, matchup changes, kickoff, empty
exhaustive results, bounded searches, harmless warnings and tamper rejection.
Production-service fixture tests reproduce Waiver exact/search and Trade
exact/comparison/legacy-search/targets/target-search hashes from manifests,
including provisional performance context and ECR-proxy pricing.

Final verification: 792 unit tests passed on Python 3.13; Ruff and
`git diff --check` passed. Tests used synthetic fixtures and fake clocks.
No live league report, paid provider request or Sleeper mutation was performed.

## Remaining limits

GET revalidation is not an atomic platform transaction; users must recheck before
acting. News coverage is limited and hourly, not continuous. Policy scores are not
calibrated probabilities; no new league calibration or historical-performance
claim is made. AC-008 still owns integrated release gates and measured optimization.
AC-006 was reconciled as merged in PR #21, with issue #12 closed, in the tracker,
affected status files, active handoff and its completed record.
