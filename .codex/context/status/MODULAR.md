# Modular migration handoff

Updated: September 26, 2026 (America/Los_Angeles)

PRs #27/#34 are merged to main. PR #35 merged into its former MA-001 base;
PR #37 carries that approved contract forward with PR #36's snapshot-clock repair.

MA-002c implements decision-scoped Trade/Waiver coverage on PR #37. Unknown
players remain owned and protected from automatic trades/drops. Independent
moves continue; connected lineup, replacement, holding or secondary dependencies
produce conditional comparisons. Conditional results cannot become accepted
offers or affirmative claims. Full-roster forecasts stay incomplete.
All 860 local tests pass, including unchanged MA-001 goldens. Required PR CI
and review remain the merge gate. Evidence: `docs/MODULAR_DECISION_COVERAGE.md`.
Strict source scoring from MA-002b remains: missing/invalid statistics and
unsupported/unresolved rules block completeness. Source evidence:
`docs/MODULAR_PROVIDER_SCORING.md`; contract: `docs/MODULAR_SCORING_CONTRACT.md`.

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
