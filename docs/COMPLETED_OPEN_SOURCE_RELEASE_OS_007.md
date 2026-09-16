# OS-007 — Public alpha release candidate

Completed: September 16, 2026 (America/Los_Angeles)

## Outcome

RosterTheory 0.1.0 is prepared as a reviewable, source-only public alpha
candidate. The README, changelog, and dedicated release notes distinguish
repeatable software and safety contracts from recommendation policy that still
requires fresh, league- and season-local evidence and calibration. The normal
workflow is command-driven through `inputs prepare`, `inputs status`, and
`doctor`; missing, stale, partial, ambiguous, or uncalibrated authority remains
visible and blocking.

The release-history disposition is a new single-root history created from the
reviewed candidate tree. This avoids making retired private identifiers and
personal commit metadata in the existing graph reachable. The existing private
repository and ignored runtime evidence remain intact as the backup. The local
candidate branch is `codex/0.1.0-alpha-candidate`; its exact commit is reported
in the handoff because a commit cannot embed its own identifier.

No tag, GitHub release, visibility change, remote candidate push, provider
request, Sleeper write, or package-registry upload occurred.

## Manual review

- The tracked tree contains no real league configuration, provider payload,
  generated recommendation evidence, private filesystem path, or known live
  credential.
- The only long Sleeper-style ID detected by the broad pattern review is the
  documented synthetic draft ID used by `tests/test_mock_watcher.py`.
- The author name in `LICENSE` and package metadata is the explicitly approved
  copyright identity. The sanitized root uses project release metadata rather
  than the private commit author's email.
- `docs/THIRD_PARTY_NOTICES.md` still accounts for every shipped configuration,
  example, and provider fixture. Provider rankings, projections, API responses,
  schedules, expert pools, and league records remain excluded or regenerated
  locally under ignored paths.
- The candidate tree exactly matches the reviewed OS-007 preparation tree; only
  its reachable Git history differs.

## Validation

Validation was repeated in a separate clean clone of the single-root candidate:

- exactly one commit is reachable and it has no parent;
- Gitleaks 8.30.1 reports no leaks across the complete candidate history and
  working tree;
- the repository-content gate passes;
- all 564 unit tests pass;
- Ruff 0.16.7 passes the declared release-critical checks;
- pip-audit 2.10.1 reports no known runtime dependency vulnerabilities;
- wheel and source distribution creation and content inspection pass;
- the isolated clean-wheel installation smoke test passes; and
- `git diff --check`, the identity-pattern review, and the candidate-tree
  comparison pass.

GitHub's multi-platform release-gate workflow remains a publication-time check.
OS-013 must re-confirm its passing state and the exact local candidate before
any explicit publication authorization is acted upon.
