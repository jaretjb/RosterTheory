# Waiver Assistant current status

Updated: September 25, 2026 (America/Los_Angeles)

AC-001/#7 through AC-004/#10 merged in PRs #15–#18; PR #18 passed all 20 checks.
AC-005/#11 is implemented; tested PR handoff pending.
Evidence: `docs/COMPLETED_ASSISTANT_RELIABILITY_AC_005.md`.

Universal weekly evidence caps: RB/WR50, QB/TE24, K/DST16. Fixed weekly
normalization is independent of the provider tail; ownership still determines
replacement and retention protection. Equal production/panel ranks preserve ties.
Specialists use league-scored season totals with explicit normalized weights
(K0.75, DST0.40) and played-game sample shrinkage. Production conflicts cannot
be bypassed through the projection branch. Projection and rank/performance paths
have distinct, truthful reasons. Missing samples remain unknown and disclosed;
they do not stop the report. Inputs preserve counts/timestamps (schema9), and
exact/search evidence identifies evaluation schema17.
The ignored local raw-weight policy was migrated; both local league policies
load universal defaults. No league calibration/result was transferred.

AC-002 candidate/retention safety and AC-003 cross-position/exhaustive search,
budget disclosure and conditional-claim safeguards remain. Historical specialist
calibration is unproven. No live report, provider refresh or Sleeper write ran.
Verification: 762 tests, Ruff and diff checks pass.

The audit is NOT closed. AC-006–AC-008 in
`docs/ASSISTANT_RELIABILITY_TASKS.md` remain planned; no next milestone is authorized.
Historical WA-025–WA-027 evidence is not a current recommendation or proof of
historical calibration. The assistant remains read-only.
