# Modular migration handoff

Updated: September 27, 2026 (America/Los_Angeles)

MA-003 merged in PR #51; its provider-limit follow-up merged in PR #52 and
closed #32. MA-004a through MA-004c moved Draft analysis, simulation and
advice into a Draft package in merged PRs #54-#56. Active MA-004d moves Draft
watcher state and recommendations into the package; decisions and output stay
unchanged.

MA-004c's behavior-preserving advice extraction merged in PR #56. MA-004d is
prepared on `codex/ma-004d-draft-watcher`: `mock_watcher.py` retains polling
and report formatting while Draft state and recommendations live in
`draft/watcher.py`. Old and new imports share the moved callables. All 940 tests,
Ruff, context routing, wheel build and clean-install smoke pass locally. Both
synthetic profiles retain their complete Draft turn and strategy hashes.
Five-repeat medians changed by -21.5% to +3.8%; Python allocation peaks are
unchanged. CI/review remain the merge gate. Ranking policy and #33 remain
separate. No provider call or Sleeper write occurred.

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
