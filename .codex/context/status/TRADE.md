# Trade Assistant current status

Updated: October 8, 2026 (America/Los_Angeles)

TA-1316 is implemented and validated on
`codex/trade-finder-roster-plausibility`; separate PR handoff is pending.
The wheel is installed locally. The finder protects starter coverage before
waiver additions, rejects increased excess depth, measures conditional
incoming use, and scores QB bundles jointly. Counteroffers pass user/roster
checks and existing partner policy. Strict verdicts, expert weights and
numerical thresholds are unchanged. JSON/CSV preserve pruning counts, samples
and completed incoming-use checks. Detail:
`docs/COMPLETED_TRADE_ASSISTANT_TA_1316.md`.

All 1,051 tests pass. The requested saved league case returns four supported
ideas in 120.036 seconds (one strict, three negotiation), excludes both invalid
two-QB packages, and records 21 exact evaluations and 11,031 roster rejections.
This offline case is non-actionable; coverage remains time-limited. Configured
football thresholds match its source. Ruff, compilation, distribution privacy,
clean installation, installed-command, context and staged-tree privacy checks
pass.

Prior TA-1315's timed finder is merged in
[PR #82](https://github.com/jaretjb/RosterTheory/pull/82). League search defaults
to 120 seconds; an opponent ID or unambiguous team name selects 300 seconds.
All nine shapes, up to ten supported ideas, strict verdicts, bounded repairs,
deadline accounting and historical replay remain supported. Original evidence:
`docs/COMPLETED_TRADE_ASSISTANT_TA_1315.md`.

TA-1314 connects preparation to completed league-scored outcomes with source
and pregame timing. Detail:
`docs/COMPLETED_TRADE_ASSISTANT_TA_1314.md`. Empirical calibration remains
unpromoted until its dated sample requirements pass. No league's policy or
result may be transferred to another league. Trade remains read-only.
