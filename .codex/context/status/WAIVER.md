# Waiver Assistant current status

Updated: September 25, 2026 (America/Los_Angeles)

AC-001/#7 through AC-005/#11 merged in PRs #15–#19.
PR #20 reconciled #11's completion records; issue #11 is closed.
AC-006/#12 merged in PR #21 with all 20 checks passing; issue #12 is closed.
AC-007/#13 merged in PR #22 with all 20 checks passing; issue #13 is closed.
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

Specialist calibration and league-exact expert ranks remain unproven.
No live report, paid refresh or Sleeper mutation ran.
AC-008/#14 is implemented on `codex/ac-008-release-gates`, pending PR/merge.
Stage timing, exact coverage, and cache sizes are exposed outside hashed Waiver
evidence. Independent alpha/beta policy fixtures and offline replay remain
decision-stable. Evidence: `docs/COMPLETED_ASSISTANT_RELIABILITY_AC_008.md`.
Verification: 797 tests, Ruff and diff checks pass on the AC-008 branch.

Audit open; AC-008 unmerged. No next milestone authorized. Read-only.
