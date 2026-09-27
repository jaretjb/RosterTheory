# Modular migration handoff

Updated: September 27, 2026 (America/Los_Angeles)

MA-003 merged in PR #51; its provider-limit follow-up merged in PR #52 and
closed #32. Active MA-004a establishes a Draft package by moving only Draft
analysis behind a compatibility import. Decision behavior stays unchanged.

MA-004a's Draft analysis extraction is prepared on
`codex/ma-004a-draft-analysis`. Both synthetic reference profiles retain their
Draft semantic hashes and old/new analysis imports share callable objects.
The focused 125-test set, full 936-test suite, Ruff, package/install smoke,
context and privacy checks pass. Same-machine, five-repeat fixed-seed Draft
turn and strategy medians changed by +0.7% to +2.0%; Python allocation peaks
changed by at most 59 bytes. No provider or Sleeper operation was performed.
Further Draft simulation, watcher and policy changes require a later slice.

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

Open: #30 provider field/actual-source evidence, #31 position caps, and #33
Draft cap/season assumptions. Actual provider coverage is unverified; MA-002
remains open. MA-004a is structural; no new league support is claimed.
