# OS-018 — Unified season preparation and runtime refresh

Completed: September 16, 2026 (America/Los_Angeles)

## Outcome

`roster-theory inputs prepare` is now the ordinary season/session preparation
entry point. It targets Draft, Trade, Waiver, or all assistants for one league
or every configured league. `inputs status` performs the same readiness
inspection offline.

Preparation validates existing artifacts before planning work, refreshes only
missing, invalid, or stale provider facts in `auto` mode, and supports an
explicit `force` mode. Its result contains the complete provider-call and
local-write preflight, dry-run and offline behavior, artifact authority,
horizon, scope, readiness, and an exact next command for every unresolved
input. It never presents refreshed data as a recommendation or as proof of
league-policy calibration.

## Safety, isolation, and recovery

- Historical Draft accuracy retains its preseason horizon; Trade and Waiver
  pools retain weekly in-season accuracy and the ROS horizon.
- The existing FantasyPros request budget, evidence payload hashes, source
  metadata, and one-request-per-second behavior remain in the underlying
  refresh command.
- Schedule evidence is shared by season. FantasyPros source evidence can be
  fetched once and replayed to derive separately audited league pools.
- League policy, scoring, private inputs, readiness, and result paths are never
  borrowed between leagues.
- Completed operations remain on disk when a later provider call fails. A
  rerun re-inspects them and resumes only remaining work.
- `--dry-run` performs no provider call or local write. `--offline` forbids
  network calls and reports the live command required to continue.
- Every result reports `recommendation_generated: false` and
  `sleeper_write_performed: false`.

The installed package now exposes `roster-theory waiver inputs LEAGUE`, so the
fresh league-scored Waiver bundle no longer depends on manually created files
or a repository-only script. Draft rankings/boards and all private shapes also
have explicit installed commands; only documented league calibration and
override decisions remain human-governed.

## Validation

- Synthetic coverage verifies targeted modes, zero-side-effect dry runs,
  offline recovery commands, fresh-cache reuse, API failure continuation,
  two-league shared-evidence reuse with league-local derived pools, paths with
  spaces, and the installed Waiver command.
- Complete suite: 560 tests pass.
- Wheel and source distribution built successfully with no build isolation.
- The wheel was installed into a fresh Windows virtual environment beneath a
  path containing spaces. PowerShell command discovery passed.
- Git Bash invoked the installed wheel, redirected `inputs status --help`, and
  produced/parsed a redirected `inputs prepare --dry-run --json` result from a
  path containing spaces.
- Tracked-path and secret-pattern checks found no `.env`, provider cache/manual
  payload, or credential-shaped value in Git. Distribution manifests exclude
  `.env` and `data/`.

No live provider request, private production input, recommendation, or Sleeper
write was used during validation.
