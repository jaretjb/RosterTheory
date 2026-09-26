# Modular migration handoff

Updated: September 26, 2026 (America/Los_Angeles)

PRs #27/#34 are merged to main. PR #35 merged into its former MA-001 base;
PR #37 carries that approved contract forward with PR #36's snapshot-clock repair.

MA-002 is authorized on September 26. Active slice MA-002b integrates explicit
scoring coverage into shared FantasyPros weekly projection preparation for Trade
and Waiver. Missing/invalid statistics and unsupported/unresolved rules block
completeness. All 847 tests and 20 CI checks passed at `ae07d4e`.
PR #37 is held as a draft after the user's clarification: irrelevant missing
players must not disable independent decisions. MR-02 section 3.1 now defines
candidate relevance, protected unknown assets and conditional results. Runtime
decision scoping remains the next implementation step before promotion.
Evidence: `docs/MODULAR_PROVIDER_SCORING.md`; pure contract history:
`docs/MODULAR_SCORING_CONTRACT.md`.

Read `docs/MODULAR_BASELINE.md` only for baseline evidence; implementation loads
the active milestone and `IMPLEMENTATION_POLICY.md`. Requirements/architecture
questions load only the requested sections of the modular documents.

Both current rule maps were captured read-only; public evidence is redacted and
all player/manager fixtures are synthetic. Source-rule observation is not proof
of provider coverage, feature readiness or calibration. Trade still has an
explicit skill-player evaluation boundary. The 12-format matrix remains future
validation, not an existing support claim.

Known behavior issues: #30 scoring completeness, #31 roster membership, #32
process-safe provider limits, #33 Draft cap/season assumptions. Both reference
maps remain LIMITED (`fum_rec` applicability); actual provider coverage is not
verified. Historical-stat/Draft scoring and remaining MA-002 contracts need
separate slices. Stop at a tested PR against main; #30 and MA-002 remain open.
