# OS-006 — Automated public-release quality and security gates

Completed: September 16, 2026 (America/Los_Angeles)

## Outcome

`.github/workflows/release-gates.yml` now makes the public-release checks
blocking on pushes, pull requests, and manual dispatches:

- the complete suite and bytecode compilation run on Python 3.11, 3.12, and
  3.13 on Linux and Windows, plus Python 3.13 on macOS;
- focused tests explicitly gate guided help, offline Doctor, banner
  suppression, narrow/plain rendering, redirected output, and single-value
  JSON output;
- a standard-library repository gate rejects tracked private configuration,
  environment files, credentials, keys, and runtime cache/export/manual data;
- Gitleaks v3 scans the full fetched Git history and working tree;
- pinned Ruff 0.16.7 release-critical static checks and pip-audit 2.10.1
  vulnerability checks run before packaging;
- pinned build 1.6.1 creates the wheel and source distribution, whose contents
  are validated by a fail-closed archive inspector; and
- the wheel is installed without dependencies into a fresh environment outside
  the checkout, then exercised through help, Doctor JSON, example config, and
  season-preparation dry-run flows using paths with spaces.

The development tools are declared and pinned in `pyproject.toml`. The public
release checklist distinguishes these automated blockers from OS-007's manual
claim, licensing, final-diff, and history-disposition review. Automatic
repository-wide formatting remains explicitly deferred until an intentional
format baseline is approved; it is not silently introduced as a release gate.

## Validation

- Complete suite: 564 tests pass.
- Focused CLI/output gate: 33 tests pass.
- Ruff: all declared checks pass.
- pip-audit: no known vulnerabilities in the declared runtime dependency set.
- Repository path gate: pass.
- Current tracked-file high-confidence credential pattern scan: no finding.
- Wheel and source distribution: build and content inspection pass.
- Isolated wheel installation and CLI smoke test: pass.
- `git diff --check`: pass; line-ending notices are informational.

The remote multi-platform and full-history Gitleaks jobs are configured but
cannot execute until this working tree is pushed or opened as a pull request.
OS-006 does not publish, tag, push, rewrite history, or make the repository
public.
