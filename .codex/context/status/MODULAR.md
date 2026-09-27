# Modular migration handoff

Updated: September 27, 2026 (America/Los_Angeles)

MA-003 merged in PR #51; its provider-limit follow-up merged in PR #52 and
closed #32. Active MA-004a moves Draft analysis into a Draft package behind a
compatibility import. Decision behavior stays unchanged.

MA-004a is prepared on `codex/ma-004a-draft-analysis`. Both synthetic reference
profiles retain their Draft semantic hashes, and old/new imports share callable
objects. Focused tests (125), the full suite (936), Ruff, package/install smoke,
context and privacy checks passed locally. Five-repeat fixed-seed Draft turn
and strategy medians changed by +0.7% to +2.0%; allocation peaks changed by at
most 59 bytes. No provider or Sleeper operation occurred. Simulation, watcher
and policy changes require later slices.

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
