# Modular migration handoff

Updated: September 29, 2026 (America/Los_Angeles)

MA-003 merged in PRs #51-#52; #32 closed. MA-004a-e moved Draft ownership
in PRs #54-#58.

MA-004f corrected #33 in PR #59. Legal capacity and bye-aware evidence are
separate from Draft preferences. Evidence: `docs/MODULAR_DRAFT_ISSUE_33.md`.

MA-005a/b tested 12 synthetic half-PPR shapes and Trade/Waiver evaluations
in PRs #60-#61; no support promotion. Evidence: `docs/MODULAR_HALF_PPR_MATRIX.md`
and `docs/MODULAR_INSEASON_MATRIX.md`.

MA-002q checked Draft position-limit source semantics in PR #62. Reference A
omits enforcement; B declares `1`. Neither source inventory nor API docs maps
positional maxima. Both scopes remain LIMITED. Evidence and recovery:
`docs/MODULAR_POSITION_LIMIT_SOURCE.md`.

PRs #63-#64 closed #30. Missing statistics remain visible; provider coverage
is unverified. Evidence: `docs/MODULAR_SCORING_ISSUE_30.md`.

MA-002t checked saved Draft membership before board preparation in PR #65. Missing
roles or taxi capacity require refresh. Positional maxima remain unmapped; both
reference Draft scopes stay LIMITED. Evidence:
`docs/MODULAR_MEMBERSHIP_ISSUE_31.md`.

#31 closed after PR #65. PR #66 clarified that user-confirmed merges and closures
do not need rechecking. Closure does not promote provider or league support.

Active MA-004g moves Draft preference ownership into the Draft package while
preserving CSV loading, decisions, output, and old import paths. This is a
source-ownership change with no provider operation or support validation.

Trade/Waiver share neutral preparation and a provider budget ledger while
keeping decisions separate. Evidence: `docs/MODULAR_SHARED_PREPARATION.md`.

Baseline: `docs/MODULAR_BASELINE.md`. Implementation loads the active milestone
and `IMPLEMENTATION_POLICY.md`. Position-cap source mapping, actual provider
coverage, and wider format support remain unverified as separate validation.
