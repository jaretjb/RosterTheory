# Modular migration handoff

Updated: September 26, 2026 (America/Los_Angeles)

PR #45 merged Draft ranking-source checks. MA-002l checks preseason projection
scope. Absent or conflicting season/week/position declarations cannot supply
league-scored Draft points; valid positions remain independent. Evidence:
`docs/MODULAR_DRAFT_PROJECTION_SCOPE.md`; CI/review remain the gate.
All 915 local tests pass with unchanged reference goldens.

MA-002k excluded wrong-horizon or unknown ranks/ECR while retaining valid
sources. Evidence: `docs/MODULAR_DRAFT_RANKING_SCOPE.md`; 913 tests passed.

MA-002j admitted only complete league-scored Draft points and checked top-board
coverage. Evidence: `docs/MODULAR_DRAFT_API_SCORING.md`.

PRs #37–#40 merged scoring/decision coverage, membership, Draft position-limit
admission and operation capacity. Missing independent players no longer veto Trade/Waiver comparisons;
unknown assets remain protected. Old normalized membership artifacts require
refresh or original-build replay. Draft unknown rules still block room-backed
recommendations. Evidence: `docs/MODULAR_DECISION_COVERAGE.md`,
`docs/MODULAR_ROSTER_MEMBERSHIP.md`, `docs/MODULAR_DRAFT_RULE_ADMISSION.md`,
`docs/MODULAR_OPERATION_CAPACITY.md`.

Read `docs/MODULAR_BASELINE.md` only for baseline evidence; implementation loads
the active milestone and `IMPLEMENTATION_POLICY.md`. Requirements/architecture
questions load only the requested sections of the modular documents.

Both reference rule maps were captured read-only and remain LIMITED (`fum_rec`).
Source observation is not proof of provider coverage, readiness or calibration.
All public fixtures are synthetic. Trade retains its skill-player boundary; the
12-format matrix remains future validation.

Open: #30 provider field and actual-source evidence; #31 positional-cap source mapping
and full admission, #32 provider limits, #33 Draft cap/season
assumptions. Actual provider coverage is unverified. Remaining MA-002
contracts need separate slices. #30, #31 and MA-002 remain open.
