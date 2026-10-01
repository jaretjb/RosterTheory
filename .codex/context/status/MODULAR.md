# Modular migration handoff

Updated: September 30, 2026 (America/Los_Angeles)

MA-002u fixes position-aware forecasts across Draft, Trade and
Waiver. Optional off-role/rare omissions no longer block; supplied stats
still count and core/invalid failures remain. Trade discovery/search agrees
with entered evaluation. Permanent rule and evidence:
`docs/POSITION_FORECAST_COVERAGE.md`. All 971 tests pass. Live Trade rerun:
zero excluded rosters, 24 targets, 81 evaluations, one provisional offer.

MA-003 merged in PRs #51-#52; #32 closed. MA-004a-e moved Draft ownership
in PRs #54-#58.

MA-004f corrected #33 in PR #59. Legal capacity and bye-aware evidence are
separate from Draft preferences. Evidence: `docs/MODULAR_DRAFT_ISSUE_33.md`.

MA-005a/b tested 12 synthetic half-PPR shapes and Trade/Waiver evaluations
in PRs #60-#61; no support promotion. Evidence: `docs/MODULAR_HALF_PPR_MATRIX.md`
and `docs/MODULAR_INSEASON_MATRIX.md`.

MA-002q checked Draft limits in PR #62. Reference A omits enforcement; B
declares `1`. Positional maxima remain unmapped; both scopes stay LIMITED:
`docs/MODULAR_POSITION_LIMIT_SOURCE.md`.

PRs #63-#64 closed #30. MA-002u corrects forecast requirements.

MA-002t checked saved Draft membership before board preparation in PR #65. Missing
roles or taxi capacity require refresh. Positional maxima remain unmapped; both
reference Draft scopes stay LIMITED. Evidence:
`docs/MODULAR_MEMBERSHIP_ISSUE_31.md`.

#31 closed after PR #65. PR #66 clarified trust in user-confirmed state.

MA-004g moved Draft preferences in PR #67. MA-005c full Waiver search evidence
merged in PR #68. Six full/open/missing-add cases passed with separate fixture
policies. Evidence: `docs/MODULAR_WAIVER_SEARCH_MATRIX.md`.

Trade/Waiver share neutral preparation and a provider budget ledger while
keeping decisions separate. Evidence: `docs/MODULAR_SHARED_PREPARATION.md`.

Baseline: `docs/MODULAR_BASELINE.md`. Implementation loads the active milestone
and `IMPLEMENTATION_POLICY.md`. Position-cap source mapping, actual provider
coverage, and wider format support remain unverified as separate validation.
