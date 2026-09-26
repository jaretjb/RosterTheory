# Modular migration handoff

Updated: September 26, 2026 (America/Los_Angeles)

PR #37 is merged to main, carrying MA-002a/b scoring contracts, MA-002c decision
coverage and the snapshot-clock repair. Independent Trade/Waiver comparisons
remain available despite irrelevant missing players. Unknown assets stay
protected; connected dependencies remain conditional. Evidence:
`docs/MODULAR_DECISION_COVERAGE.md` and `docs/MODULAR_PROVIDER_SCORING.md`.

MA-002d implements the membership slice of #31: preserve taxi roles, reconcile
ownership/capacity, check reserve eligibility and reject known taxi formats.
Normalized snapshots now require explicit taxi evidence; old files request a
refresh or original-build replay. The reviewed schema-only golden migration
retains the original MA-001 evidence and unchanged reference decisions.
All 877 local tests pass. Contract and validation: `docs/MODULAR_ROSTER_MEMBERSHIP.md`.
Required CI and review remain the merge gate; stop at this tested PR handoff.

Read `docs/MODULAR_BASELINE.md` only for baseline evidence; implementation loads
the active milestone and `IMPLEMENTATION_POLICY.md`. Requirements/architecture
questions load only the requested sections of the modular documents.

Both current rule maps were captured read-only; public evidence is redacted and
all player/manager fixtures are synthetic. Source-rule observation is not proof
of provider coverage, feature readiness or calibration. Trade still has an
explicit skill-player evaluation boundary. The 12-format matrix remains future
validation, not an existing support claim.

Open: #30 scoring/provider completeness, #31 Draft position-limit semantics and
full capability admission, #32 process-safe provider limits, #33 Draft cap/season
assumptions. Both reference maps remain LIMITED (`fum_rec`); actual provider
coverage is unverified. Historical-stat/Draft scoring and remaining MA-002
contracts need separate slices. #30, #31 and MA-002 remain open.
