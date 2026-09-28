# Modular migration handoff

Updated: September 27, 2026 (America/Los_Angeles)

MA-003 merged in PR #51; its provider-limit follow-up merged in PR #52 and
closed #32. MA-004a and MA-004b moved Draft analysis and simulation into a
Draft package in merged PRs #54-#55. Active MA-004c moves Draft advice behind
a compatibility import; decisions and output remain unchanged.

MA-004c is prepared on `codex/ma-004c-draft-assistant`. Old/new advice imports
resolve to one module, and the moved implementation AST is identical. Both
synthetic profiles retain their Draft semantic hashes. Focused tests (141), the
full suite (938), Ruff and context routing pass locally. Five-repeat fixed-seed
Draft turn and strategy medians changed by -0.6% to +2.6%; allocation peaks
are unchanged. No provider or Sleeper operation occurred. Watcher and policy
changes require later slices.

Trade and Waiver use shared neutral preparation while keeping separate decisions.
Waiver adapts its own snapshot. A process-safe ledger coordinates FantasyPros
budget and pacing across current entry points. Synthetic tests cover dependency
direction, snapshot reuse, concurrent reservations, pacing and retries. Evidence:
`docs/MODULAR_SHARED_PREPARATION.md`.

MA-002p restored conditional Trade/Waiver forecasts. Trade decisions using
estimates remain conditional; Waiver cannot affirmatively add/claim. Draft
scoring is unchanged. Evidence: `docs/MODULAR_WORKFLOW_RECONCILIATION.md`.

Baseline: `docs/MODULAR_BASELINE.md`. Implementation loads the active milestone
and `IMPLEMENTATION_POLICY.md`. Open: #30 provider evidence, #31 position caps,
and #33 Draft cap/season assumptions. Actual provider coverage and wider format
support remain unverified.
