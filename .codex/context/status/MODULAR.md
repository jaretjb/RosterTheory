# Modular migration handoff

Updated: September 26, 2026 (America/Los_Angeles)

MA-002f is at tested handoff: temporary active/reserve overages are observed in
Trade/Waiver snapshots. Trades involving an overfull roster remain conditional
because lineup edits and secondary additions may be locked. Waiver search is
scoped to the user's own capacity/reserve legality; an opponent's overage remains
visible but does not veto an independent claim. Structural membership defects
still block. 896 tests pass with unchanged reference goldens; Ruff passes.
Evidence: `docs/MODULAR_OPERATION_CAPACITY.md`. Required CI/review remain the
merge gate.

PRs #37–#39 merged scoring/decision coverage, membership and Draft position-limit
admission. Missing independent players no longer veto Trade/Waiver comparisons;
unknown assets remain protected. Old normalized membership artifacts require
refresh or original-build replay. Draft unknown rules still block room-backed
recommendations. Evidence: `docs/MODULAR_DECISION_COVERAGE.md`,
`docs/MODULAR_ROSTER_MEMBERSHIP.md`, `docs/MODULAR_DRAFT_RULE_ADMISSION.md`.

Read `docs/MODULAR_BASELINE.md` only for baseline evidence; implementation loads
the active milestone and `IMPLEMENTATION_POLICY.md`. Requirements/architecture
questions load only the requested sections of the modular documents.

Both reference rule maps were captured read-only and remain LIMITED (`fum_rec`).
Source observation is not proof of provider coverage, readiness or calibration.
All public fixtures are synthetic. Trade retains its skill-player boundary; the
12-format matrix remains future validation.

Open: #30 scoring/provider completeness, #31 positional-cap source mapping
and full admission, #32 provider limits, #33 Draft cap/season
assumptions. Actual provider coverage is unverified. Historical-stat/Draft scoring and remaining MA-002
contracts need separate slices. #30, #31 and MA-002 remain open.
