# Modular migration handoff

Updated: September 27, 2026 (America/Los_Angeles)

MA-003 merged in PR #51. Active MA-003b (#32) on
`codex/ma-003-provider-budget` brings older Draft, diagnostic and accuracy
commands into the shared FantasyPros budget. No live paid calls.

Trade and Waiver use shared neutral value preparation; Waiver adapts its own
snapshot. Provider retrieval, cache interpretation, identity, league scoring,
horizon evidence and value calculations moved out of Trade. Feature decisions
remain separate. A process-safe ledger coordinates FantasyPros budget and
pacing for main board, Waiver Wire, backtest and expert refresh paths. Synthetic
tests cover dependency direction, snapshot reuse, concurrent reservations,
pacing and retries. MA-002 evidence remains open; no new calibration claim.
Evidence: `docs/MODULAR_SHARED_PREPARATION.md`.

MA-002p restored conditional Trade/Waiver forecasts from 12,861 retained rows;
weekly `fumbles` means fumbles lost. Trade estimate decisions remain conditional;
Waiver cannot affirmatively add/claim. Draft scoring is unchanged. Earlier
PRs #37–#40 covered decision-scoped missing players, membership, Draft position
admission and capacity. Evidence: `docs/MODULAR_WORKFLOW_RECONCILIATION.md`,
`docs/MODULAR_DECISION_COVERAGE.md`, `docs/MODULAR_ROSTER_MEMBERSHIP.md`,
`docs/MODULAR_DRAFT_RULE_ADMISSION.md`, `docs/MODULAR_OPERATION_CAPACITY.md`.

Baseline evidence: `docs/MODULAR_BASELINE.md`. Implementation loads the active
milestone and `IMPLEMENTATION_POLICY.md`.

Sleeper documents `fum_rec` under Team Defense. Missing projection fields still
prevent exact coverage. All public fixtures are synthetic. Trade retains its
skill-player boundary; the 12-format matrix remains future validation.

Open: #30 provider field/actual-source evidence, #31 position caps, #32 provider
limits pending MA-003b merge, #33 Draft cap/season assumptions. Actual provider coverage is unverified;
MA-002 remains open.
