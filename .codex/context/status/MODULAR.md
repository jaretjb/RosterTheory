# Modular migration handoff

Updated: September 26, 2026 (America/Los_Angeles)

Planning PR #27 is merged. MA-001 PR #34 remains open, with 811 tests and all
20 CI checks passed. Its baseline is the base for the dependent MA-002a branch.

MA-002 is authorized on September 26; its first slice MA-002a is implementation-complete: versioned
scoring-rule and statistic-evidence contracts, independent tests and an explicit
reference-rule inventory. Existing feature/provider paths remain unchanged.
All 828 tests, Ruff and context checks pass; awaiting dependent PR review/CI.
Evidence and next integration slice: `docs/MODULAR_SCORING_CONTRACT.md`.

Read `docs/MODULAR_BASELINE.md` only for baseline evidence; implementation loads
the active milestone and `IMPLEMENTATION_POLICY.md`. Requirements/architecture
questions load only the requested sections of the modular documents.

Both current rule maps were captured read-only; public evidence is redacted and
all player/manager fixtures are synthetic. Source-rule observation is not proof
of provider coverage, feature readiness or calibration. Trade still has an
explicit skill-player evaluation boundary. The 12-format matrix remains future
validation, not an existing support claim.

Known behavior issues: #30 scoring completeness, #31 roster membership, #32
process-safe provider limits, #33 Draft cap/season assumptions. MA-002a prepares
#30 but does not close it; adapter/feature integration and the other issues stay
outside this slice. Stop at a tested dependent PR; overall MA-002 remains open.
