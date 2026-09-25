# AC-002 — Candidate-scoped safety and transaction legality

Issue: [#8](https://github.com/jaretjb/RosterTheory/issues/8). Implemented September
25, 2026; tested handoff in [PR #16](https://github.com/jaretjb/RosterTheory/pull/16), pending review/merge.
Findings: W3, W5, T3, D1. AC-001/#7 and prerequisite PR #6 are merged.

## Behavior

- Production Waiver Value now requires complete relevant values/projections and
  QB streamer evidence, bounded current-week loss, depth/downside, QB holding
  support, and protected-option retention. It retains the existing scoring policy;
  a composite score cannot override these safeguards.
- WATCH requires a plausible bounded move and identifies its failed gate. Severe
  lineup losses, missing decision-critical numerical evidence, and protected
  retention failures are PASS, not near-threshold opportunities.
- Unknown/locked drops and missing alternative-drop values are explicitly excluded.
  Other legal moves still run. A search with no legal replacement returns visible
  omissions and no action, rather than aborting the report.
- Trade snapshots preserve ownership and explicitly record missing directory/team
  evidence. Missing rankings/projections and unavailable rank slots/baselines produce
  scoped board exclusions. No expert position ranks are renumbered to fill a hole;
  no omitted player receives an invented value or complete zero projection.
- Target and legacy package searches isolate affected rosters. Missing user-roster
  evidence prevents unsafe offers but returns a report with exclusions/counts.
  Exact trades reject unresolved evidence only when it affects their participants.
  Automatic secondary drops require value evidence.
- JSON and text outputs expose partial coverage. `ValueBoard.complete` describes
  the included rows; reports separately declare excluded/requested coverage, and
  never report the whole board complete when exclusions exist.

## Legality evidence

Fantasy points are no longer a lock detector. Current matchup starters, aware
kickoff timestamps, audited byes, and actual league settings determine drop locks.
A zero-point started starter is locked. `bench_lock` controls started bench drops;
`disable_adds` controls league-wide moves, including an open-slot acquisition.
Missing/ambiguous game evidence or relevant settings remain UNKNOWN, never legal.
An unavailable league-wide move setting blocks automatic input generation because
it affects every transaction; a missing individual player does not.

The setting mappings were verified against [Sleeper's published web client](https://sleepercdn.com/js/bundle-ffb5642d54c3137a49e6ebf5ece9dd82.js?vsn=d)
(SHA-256 `230bc19fb8c9dcbb061f47c23af0f479f8da2d0a0c5fe9117b9535ffa3ce5330`).
Sleeper also documents the [league-wide lock](https://support.sleeper.com/en/articles/4037431-why-can-t-i-drop-players)
and the [pre-kickoff pending-claim exception](https://support.sleeper.com/en/articles/3473234-why-was-someone-able-to-drop-their-starter-after-they-have-played).
These recommendations concern new moves; they do not assume an earlier claim.
[nflverse's dictionary](https://nflreadr.nflverse.com/articles/dictionary_schedules.html)
establishes Eastern kickoff wall time. Conversion handles modern US DST without
requiring a Windows timezone package; ambiguous transition times are unavailable.

## Verification and remaining work

722 unit tests and Ruff pass. Regressions cover production-priority safety,
severe-loss WATCH, reversible news blockers, protected retention, unknown/locked
drops, open slots, zero-point kickoff, league/bench settings, unknown identity,
unrelated versus decision-critical roster omissions, partial curves/baselines,
empty value scopes, and visible partial reports. Pre-fix regressions reproduced
unsafe affirmative labels and whole-report coverage exceptions.

No paid provider refresh, live recommendation run, or Sleeper write was performed.
Malformed structural evidence (duplicate ownership/ranks, mismatched horizons)
still stops processing. AC-003–AC-008 remain planned, including cross-position
optimization, Trade verdict/secondary-move strategy, specialist calibration,
freshness/provenance, and end-to-end measurement. The overall audit remains open.
