# Modular migration handoff

Updated: September 26, 2026 (America/Los_Angeles)

PR #37 merged scoring contracts and decision-scoped coverage. Independent
Trade/Waiver comparisons remain available despite irrelevant missing players;
unknown assets stay protected. Evidence:
`docs/MODULAR_DECISION_COVERAGE.md` and `docs/MODULAR_PROVIDER_SCORING.md`.

PR #38 merged roster membership and reserve eligibility. Old normalized files
require refreshing or original-build replay. The schema-only golden migration
retains original MA-001 evidence and unchanged reference decisions.
Evidence: `docs/MODULAR_ROSTER_MEMBERSHIP.md`.

MA-002e adds scoped capability records and Draft position-limit admission at the
recommend command and watcher, including cached recommendations. Unknown rules
cannot enter room-backed decisions. Both reference Draft profiles remain LIMITED
until cap evidence is verified. Pure offline calculations and all existing
goldens remain unchanged; 888 tests pass. Evidence: `docs/MODULAR_DRAFT_RULE_ADMISSION.md`.
Required CI/review remain the merge gate; stop at the tested PR handoff.

Read `docs/MODULAR_BASELINE.md` only for baseline evidence; implementation loads
the active milestone and `IMPLEMENTATION_POLICY.md`. Requirements/architecture
questions load only the requested sections of the modular documents.

Both current rule maps were captured read-only; public evidence is redacted and
all player/manager fixtures are synthetic. Source-rule observation is not proof
of provider coverage, feature readiness or calibration. Trade still has an
explicit skill-player evaluation boundary. The 12-format matrix remains future
validation, not an existing support claim.

Open: #30 scoring/provider completeness, #31 positional-cap source mapping,
operation-specific capacity and full admission, #32 provider limits, #33 Draft cap/season
assumptions. Both reference maps remain LIMITED (`fum_rec`); actual provider
coverage is unverified. Historical-stat/Draft scoring and remaining MA-002
contracts need separate slices. #30, #31 and MA-002 remain open.
