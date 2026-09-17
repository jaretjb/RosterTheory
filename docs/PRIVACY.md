# Privacy and public repository boundary

Updated: September 14, 2026 (America/Los_Angeles)

RosterTheory's source, tests, configuration examples, and public documentation
must not contain a manager's identity, private league or draft identifiers,
credentials, private filesystem paths, or generated provider evidence. The
copyright holder's legal name, Jaret Brown, is an intentional exception in
the MIT license and its release handoff, approved September 15, 2026.

## Public and local files

`config/leagues.example.json` is the public template and contains synthetic
values only. Copy it to the per-user path documented in `README.md`, or select
a private path with `ROSTER_THEORY_CONFIG`/`--config`, and replace every owner,
league, draft, season, team, and roster value locally. `.env` is also ignored;
`.env.example` contains only an empty key field.

Provider caches, exports, manual imports, release-audit originals, and other
generated evidence belong under these ignored directories:

- `data/cache/`
- `data/exports/`
- `data/manual/`

Local identity overrides, waiver policy/evidence files, and generated release
evidence are covered by the additional generic patterns in `.gitignore`.
Unmatched, ambiguous, partial, or unavailable provider data must still be
reported rather than omitted.

Professional NFL player names and published expert/source names are intentional
real-world references, not private manager identities. OS-003 separately owns
the redistribution decision for any third-party data files; this privacy audit
does not grant redistribution rights.

## Audit result

The September 14 working-tree audit covered source, tests, configuration,
documentation, package metadata, tracked-path candidates, ignored local paths,
and all 66 commits reachable from the local refs. The reviewed public tree uses
synthetic league aliases (`league_alpha` and `league_beta`) for isolated legacy
calibrations and synthetic owner, team, league, and draft identifiers. No
private filesystem path or live credential was found in the public tree. The
FantasyPros key example is an empty or clearly synthetic placeholder.

The ignored local files were not deleted, moved, or inspected for publication.
No provider request or Sleeper write occurred.

OS-007 repeated the public-tree review and prepared the reviewed tree on a
local, single-root candidate branch. A fresh clone of that candidate contained
one reachable commit, passed the repository path and identity-pattern reviews,
and had no Gitleaks finding. OS-013 published that reviewed root as remote
`main`; the original private history and ignored evidence remain in a verified
private local backup rather than the public Git graph.

## Git history decision

Do not publish the existing Git graph as-is. Reachable history still contains a
retired real league configuration, former private league and organization
labels, live identifiers in historical documents, and individual author
identity in commit metadata.

The completed release disposition is a new single-root history created from
the reviewed tree, not publication of or in-place filtering of the private
graph. Before publication, OS-013 preserved the original repository in a
verified private backup, re-confirmed the candidate commit and tree, replaced
the private remote history, removed obsolete Actions runs tied to the retired
graph, and verified the public repository anonymously.

If any version of the repository has already been shared, rewriting remote
history cannot revoke existing clones, forks, caches, or downloaded archives.
Treat any credential ever committed as compromised and rotate it at its
provider even after the commit is removed. The current audit found only the
documented FantasyPros placeholder pattern, not a live key, but automated
release secret scanning remains required by OS-006.
