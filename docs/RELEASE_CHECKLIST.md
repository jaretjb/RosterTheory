# Public-release quality and security checklist

This checklist describes the blocking OS-006 gates. Passing it makes a commit
eligible for release-candidate review; it does not publish a package, create a
tag, make the repository public, or prove that league-specific recommendation
policy is calibrated.

## Required automated checks

The `release gates` GitHub Actions workflow must pass without skipped or
allowed-failure jobs:

1. **Unit tests** — the complete `unittest` suite and bytecode compilation run
   on Linux and Windows with Python 3.11, 3.12, and 3.13. A Python 3.13 macOS
   job provides the practical third-platform check.
2. **CLI contracts** — focused tests separately gate guided help, offline
   Doctor, banner suppression, narrow/plain rendering, redirected output, and
   exactly one JSON value on machine-oriented stdout.
3. **Repository contents** — `python scripts/release_gate.py repository`
   rejects tracked `.env` variants, `leagues.json`, credential/key files, and
   anything beneath `data/cache`, `data/exports`, or `data/manual`.
4. **Secret scan** — Gitleaks scans the complete fetched Git history and the
   working tree. A finding blocks the workflow; do not add an allowlist merely
   to silence an unexplained result.
5. **Static checks** — Ruff 0.16.7 runs the declared release-critical
   syntax/name rule set against `src`, `tests`, and `scripts`.
6. **Dependency audit** — pip-audit 2.10.1 audits the local project declared by
   `pyproject.toml`. The application currently has no runtime dependencies;
   the audit remains required so adding one cannot bypass review.
7. **Package build and inspection** — build 1.6.1 creates exactly one wheel and
   one source distribution. The distribution gate checks required entry-point,
   source, test, and release-script files and rejects private/generated/cache,
   traversal, compiled, Git, or nested build content.
8. **Clean install** — the wheel is installed without dependencies into a new
   virtual environment outside the checkout. Guided help, offline Doctor JSON,
   example configuration, and a redirected season-preparation JSON dry-run are
   exercised from a path containing spaces.

Local equivalents are:

```powershell
python -m pip install -e '.[dev]'
python scripts/release_gate.py repository
python -m unittest discover -s tests
python -m ruff check src tests scripts
python -m pip_audit --cache-dir build/pip-audit-cache .
python -m build --outdir build/release-dist
python scripts/release_gate.py distributions build/release-dist
python scripts/clean_install_smoke.py build/release-dist/roster_theory-0.1.0-py3-none-any.whl
```

The same commands work in a POSIX shell; quote paths containing spaces.

## Manual release-candidate review

These judgments are intentionally not automated and remain required in OS-007:

- review the final diff and release notes for accurate alpha claims;
- confirm third-party notices and redistribution decisions still match every
  shipped example and fixture;
- resolve and approve the private-history disposition, then repeat the full
  history secret scan against the rewritten candidate;
- confirm no real league, manager, player-choice, provider payload, or local
  absolute path appears in the candidate artifacts; and
- obtain explicit user approval before tagging, publishing a release, making a
  repository public, or pushing rewritten history.

## OS-007 candidate procedure

The 0.1.0 alpha candidate uses a new single-root Git history built from the
reviewed tree. The existing repository and ignored local evidence remain the
private backup. In a separate temporary clone of the candidate:

1. verify that only the sanitized root commit is reachable;
2. repeat the repository-content and identity-pattern reviews;
3. run Gitleaks against the complete candidate history and working tree;
4. run the complete unit, static, dependency, build, distribution, and clean
   install checks above; and
5. compare the candidate tree to the reviewed OS-007 preparation tree and
   require no difference.

Record the exact candidate branch, commit, tree comparison, command results,
and manual-review outcome in the OS-007 completion handoff. Do not push the
candidate or perform any publication step during OS-007.

Repository-wide automatic formatting is not a release gate yet. Ruff's version
and static rule set are pinned; adopting `ruff format --check` requires a
separate intentional baseline change so OS-006 does not mechanically rewrite
unrelated historical code.
