# Modular migration handoff

Updated: September 27, 2026 (America/Los_Angeles)

MA-003 merged in PR #51; its provider-limit follow-up merged in PR #52 and
closed #32. MA-004a moved Draft analysis into a Draft package in merged PR #54.
Active MA-004b moves simulation into that package behind a compatibility import.
Decision behavior stays unchanged.

MA-004b is prepared on `codex/ma-004b-draft-simulation`. Both synthetic
reference profiles retain their Draft semantic hashes, and old/new simulation
imports resolve to one module. Focused tests (149), the full suite (937), Ruff,
package/install smoke and context routing pass locally. Five-repeat fixed-seed
Draft turn and strategy medians changed by -3.4% to +0.4%; allocation peaks are
unchanged. No provider or Sleeper operation occurred. Watcher and policy changes
require later slices.

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
