# RosterTheory Waiver Assistant design

Status: Initial design for the approved League Alpha vertical slice
Updated: September 9, 2026 (America/Los_Angeles)

## Architecture

The Waiver Assistant is a separate product adapter over feature-neutral
in-season inputs and roster-delta calculations:

1. `providers` normalizes read-only Sleeper and FantasyPros responses.
2. `core` owns identities, league scoring, legal lineup optimization,
   replacement calculation, cache, and provenance.
3. A feature-neutral in-season layer will own weekly projection matrices,
   before/after single-roster impact, depth, and reusable risk calculations
   extracted from Trade with regression coverage.
4. `waiver` owns acquisition state, add/drop legality, candidate generation,
   decision gates, evidence, and presentation.
5. `trade` retains two-roster package, partner, fairness, and package-search
   policy. `draft` retains acquisition-timing and draft-room policy.

Waiver code must not import Draft policy. Direct imports from `trade` are
temporary only inside an explicitly bounded extraction milestone and may not
remain in the promoted Waiver interface.

## Data flow

`Sleeper GET -> normalized league/rosters/transactions -> immutable waiver
snapshot -> horizon-matched value inputs -> add/drop candidates -> exact
single-roster evaluation -> Waiver gates -> compact report + evidence`

Provider caches may be shared when request parameters and normalized semantics
are identical. Waiver exports live under `data/exports/waiver/`; configuration
lives under `config/waiver/`.

## Initial interfaces

- `waiver refresh <league>`: data-only snapshot and completeness report.
- `waiver evaluate <league> --add PLAYER [--drop PLAYER]`: one entered
  acquisition, with automatic drop search when required.
- `waiver search <league>`: later milestone after entered evaluation passes.

All commands are read-only. No provider adapter exposes a transaction-write
method.

## Fail-closed boundaries

- Sleeper ownership must be current inside the configured waiver freshness
  window at both candidate resolution and final report construction.
- Acquisition status is `FREE_AGENT`, `WAIVERS`, `UNROSTERED`, `LOCKED`,
  `PENDING`, or `UNKNOWN`. Current non-ownership plus supported-position
  eligibility is sufficient for evaluation; exact transaction mechanism and
  pending-claim visibility are informational.
- Unknown roster capacity or reserve legality blocks automatic drop selection.
- Missing relevant ranks, projections, identity, or material-news freshness
  blocks final decision labels unless a later approved degraded mode specifies
  otherwise.
- Candidate and value-input hashes are included in deterministic evidence.
- Ownership inputs preserve their actual long-term horizon. Search protects a
  candidate from ownership-floor pruning when a same-position legal drop is
  strictly dominated by fresh weekly rank, ROS consensus, and remaining
  league-scored projection while both ownership values still use the same
  non-ROS horizon. The exact evaluator rechecks the proof and all ordinary
  safety gates before producing an affirmative label.

## Current extraction seams

The existing Trade implementation already contains the target algorithms but
mixes them with Trade orchestration. The reusable seams are the weekly
projection matrix, lineup scoring, bounded secondary add/drop choice, depth
above waivers, team impact, and risk profile. They will be extracted in small
steps while existing Trade tests pin behavior.
