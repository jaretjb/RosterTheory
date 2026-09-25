# Waiver Assistant current status

Updated: September 25, 2026 (America/Los_Angeles)

AC-001/#7 and prerequisite PR #6 are merged. AC-002/#8 merged in PR #16.
AC-003/#9 is implemented; PR #17 awaits review/merge.
Evidence: `docs/COMPLETED_ASSISTANT_RELIABILITY_AC_003.md`.
All supported legal cross-position drops compete without same-position preference.
Default search is exhaustive over eligible adds; an explicit budget reports
unevaluated IDs and cannot prove a global best/no-action result. Approved moves
stay in canonical plan/display order, including specialists. Conditional claim
branches recheck the changed roster and cumulative losses; other combinations
remain unvalidated. Missing evidence is visible and quarantined locally, with
affected position dependencies blocked. AC-002 retention/safety gates remain.
Verification: 737 tests, Ruff and diff checks pass. No live report, provider
refresh or Sleeper write occurred.

The audit is NOT closed. AC-004–AC-008 in `docs/ASSISTANT_RELIABILITY_TASKS.md`
track Trade decisions, ranking caps, specialist scoring, formats, freshness and performance.
No next milestone is authorized.

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
