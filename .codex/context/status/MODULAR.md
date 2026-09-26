# Modular migration handoff

Updated: September 26, 2026 (America/Los_Angeles)

PR #41 merged Waiver historical scoring evidence into main. MA-002h addresses
Waiver breakout scenarios: their six modeled statistics must cover every
applicable active league scoring rule before a scenario value is used. Missing
categories explain an unavailable scenario; the base Waiver comparison and
unrelated candidates remain independent. Evidence:
`docs/MODULAR_EMERGING_SCORING.md`; CI/review remain the merge gate.
All 905 local tests, including unchanged reference goldens, pass.

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

Open: #30 scoring/provider completeness and Draft legacy consumers; #31 positional-cap source mapping
and full admission, #32 provider limits, #33 Draft cap/season
assumptions. Actual provider coverage is unverified. Draft scoring and remaining MA-002
contracts need separate slices. #30, #31 and MA-002 remain open.
