# Modular migration handoff

Updated: September 27, 2026 (America/Los_Angeles)

MA-003 merged in PR #51; its provider-limit follow-up merged in PR #52 and
closed #32. MA-004a through MA-004d moved Draft analysis, simulation, advice
and watcher decisions into a Draft package in merged PRs #54-#57. Active
MA-004e completes the watcher application and presentation boundaries.

MA-004d merged in PR #57. MA-004e is prepared on
`codex/ma-004e-watcher-boundaries`: application owns read-only polling,
presentation owns human watcher reports, and `mock_watcher.py` remains an
import-only compatibility path. The synthetic one-poll report and rendered
text retain their complete 16,401-byte semantic hash. All 10 moved definitions
have identical ASTs. Focused tests (86), the full suite (942), Ruff, context
routing, wheel build and clean-install smoke pass locally. Five-repeat watcher
median changed +1.4%; Python allocation peak is unchanged. CI/review remain
the merge gate. Ranking policy and #33 remain separate. No provider call or
Sleeper write occurred.

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
