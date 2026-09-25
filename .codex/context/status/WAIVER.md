# Waiver Assistant current status

Updated: September 25, 2026 (America/Los_Angeles)

AC-001/#7 and prerequisite PR #6 are merged. AC-002/#8 is implemented, pending
PR review/merge. PR link: `docs/ASSISTANT_RELIABILITY_TASKS.md`.
Evidence: `docs/COMPLETED_ASSISTANT_RELIABILITY_AC_002.md`.
Production Waiver Value enforces evidence, weekly/depth/downside, QB holding,
and retention gates. WATCH needs a plausible bounded move and specific blocker.
Unknown/locked drops are excluded locally. Drop locks use actual league settings,
matchup starters, kickoff, and byes, never scored points.
Verification: 722 tests and Ruff pass; no live report or Sleeper write occurred.

The audit is NOT closed. AC-003–AC-008 in `docs/ASSISTANT_RELIABILITY_TASKS.md`
track safety gates, cross-position optimization, pruning/report consistency,
ranking caps, specialist scoring, formats, freshness, and performance.
No further implementation milestone is authorized.

Historical evidence remains in `docs/WAIVER_ASSISTANT_TASKS.md`:

- WA-026 introduced generic retention-safe value defaults and isolated league
  overrides. Its pruning tests do not prove general cross-position equivalence.
- WA-027 exposed league-scored specialist production with local K/DST weight
  adjustments. These are not historically validated universal calibration.
- Missing roster value evidence is visible and excluded from automatic drops.
- WA-025 separated acquisition and retention evidence. WA-017–WA-024 covered
  input resilience, identity, reporting, rank evidence, and streaming.

WA-006 audits recur; WA-016 remains optional research. The assistant is read-only;
historical results are not current claims or proof that outstanding audit findings
are resolved.
