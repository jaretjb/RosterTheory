# Waiver Assistant current status

Updated: September 25, 2026 (America/Los_Angeles)

AC-001/#7 through AC-005/#11 merged in PRs #15–#19.
PR #20 reconciled #11's completion records; issue #11 is closed.
AC-006/#12 merged in PR #21 with all 20 checks passing; issue #12 is closed.
AC-007/#13 implements freshness, readiness and replay contracts on its own branch.
Evidence: `docs/COMPLETED_ASSISTANT_RELIABILITY_AC_007.md`.

Source observations retain their original times, including cache hits. News uses
a one-hour refresh interval and remains a finite global feed, never complete
per-player coverage. Publication rechecks ownership, lineup/settings, player status,
transactions and matchup starters, and checks source expiry and kickoff boundaries.
Immutable as-of evaluation and wall-clock publication checks are separate.
Input gaps, bounded search, candidate confidence and informational warnings are
separate; empty exhaustive searches can be ready. Hashed sidecar manifests record
build, policy, scoring, sources and replay inputs. Offline replay reproduces hashes
without provider calls and is never current/actionable.

AC-005 weekly caps (RB/WR50, QB/TE24, K/DST16), sampled specialist production,
truthful decision paths and tie preservation remain. AC-002 candidate/retention
safety and AC-003 cross-position, exhaustive search, budget disclosure and
conditional-claim safeguards remain unchanged.

Historical specialist calibration and league-exact custom expert rankings remain
unproven/unavailable. No live report, paid refresh or Sleeper mutation ran.
Verification: 792 tests, Ruff and diff checks pass on the AC-007 branch.

The audit is NOT closed. AC-008 remains planned in
`docs/ASSISTANT_RELIABILITY_TASKS.md`. No next milestone is authorized.
The assistant remains read-only.
