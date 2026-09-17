# OS-013 completion — GitHub publication and verification

Completed: September 16, 2026 (America/Los_Angeles)

## Outcome

RosterTheory's reviewed source-only `0.1.0` alpha repository is public at
<https://github.com/jaret81/RosterTheory>.

With explicit user approval, the published history starts from the sanitized
single-root candidate:

- branch: `main`
- approved root: `76801ee2a3efeced464381cb471cb3e19eaabb86`
- root subject: `RosterTheory 0.1.0 public alpha candidate`
- root identity: `RosterTheory Release <release@roster-theory.invalid>`

The original graph remains available in a verified ignored local backup and in
the separate private `jaret81/RosterTheory-private-archive` repository. The
working repository now uses `Jaret Brown` and GitHub's account-associated
no-reply address for future commits, so the contributor name remains visible
without publishing a personal contact address.

## Remote cleanup

The first publication attempt force-updated the original repository's visible
refs to the sanitized root. Fifty-four Actions runs associated with the retired
private history were deleted. A post-publication anonymous check nevertheless
found that GitHub still served an unreachable retired commit when addressed by
its exact SHA. The repository was immediately returned to private visibility.

To avoid relying on eventual object garbage collection, the contained
repository was renamed `RosterTheory-private-archive` and retained privately.
A distinct empty private `RosterTheory` repository was created, then populated
with only the sanitized history. Before its visibility change it had one
branch, no tags, no pull requests, no releases, and no copy of the tested
retired commit object.

The replacement also exposed a Gitleaks Action range bug for root histories and
a container ownership mismatch. The gate now runs the pinned official Gitleaks
container directly, grants Git trust only to the container's checked-out
workspace through process-scoped configuration, scans all reachable history,
and preserves its SARIF report. The corrected complete release workflow passed.

No tag or GitHub release was created, and no distribution was uploaded to PyPI.

## Verification

- The local repository gate passed against the candidate tree.
- All 564 unit tests passed.
- The replacement history starts at the approved sanitized root and contains no
  known personal email or private absolute-path pattern.
- The replacement's complete GitHub Actions release-gate run, including the
  full-history Gitleaks scan, completed successfully.
- Anonymous requests to the repository, README, and MIT license returned HTTP
  200.
- A credential-free clone resolved to the replacement repository's public
  `main`, whose ancestry terminates at the approved root.
- Installing `roster-theory==0.1.0` from that public clone succeeded.
- The installed package ran `doctor home_league --json` against the synthetic
  example configuration with exit code 0, zero provider calls, and zero Sleeper
  writes.

## Remaining boundaries

This is a source-only alpha. Recommendation readiness still requires fresh,
authorized provider evidence and separately reviewed league- and season-local
policy. No league calibration or result transfers to another league. RosterTheory
does not submit drafts, trades, waiver claims, or lineup changes.
