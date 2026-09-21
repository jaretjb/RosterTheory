# Completed Trade Assistant TA-1302

Completed: September 20, 2026 (America/Los_Angeles)

Branch: `codex/ta-1302-trade-market-board`

Scope: Weekly redraft trade-market ingestion and normalization boundary

## Football result

RosterTheory can now load a current community exchange-price board without
mixing those prices into football projections or exact team value. The board is
ready for later finder work to construct market-plausible offers; existing
entered-package evaluation remains fully operational without it.

The normalized result preserves two separate facts:

- whether the league needs the independently calculated 1QB or superflex/2QB
  redraft market; and
- that the provider's reception and tight-end-premium market blends are not
  exact Sleeper league scoring.

## Implementation

- Added a standard-library, unauthenticated, GET-only Stats Guy Fantasy client
  using the documented bulk `/players` endpoint.
- Added immutable `TradeMarketBoard`, `TradeMarketPrice`, and
  `TradeMarketEvidence` contracts.
- Joined provider rows directly by canonical Sleeper player ID and rejected
  missing, duplicate, nonnumeric, negative, unsupported-position, partial, or
  required-player-incomplete data.
- Selected `non_sf_redraft` or `sf_redraft` from actual league starter slots.
- Preserved provider calculation time, retrieval time, raw price, ranks, 7-day
  and 30-day changes, and change from a verified prior complete board.
- Added visible source attribution, scoring-blend warnings, freshness metadata,
  payload provenance, and a deterministic evidence hash.
- Added provenance-checked authorized JSON import and tamper-detecting replay.
- Added fail-closed resolution from API to authorized import to `ECR-PROXY`.
  Proxy mode emits no fabricated board and disables chart price, change,
  fairness, and consolidation-premium claims.
- Kept normalized provider evidence in caller-selected ignored storage; no live
  provider row is present in source control.

## Live contract check

One implemented-client bulk GET normalized the current response without saving
or printing a player row:

- provider timestamp: `2026-09-20T13:01:05.336Z`;
- source rows: 396;
- normalized 1QB redraft prices: 211;
- complete: yes;
- league-scoring exact: no; and
- attribution and both scoring-blend warnings: present.

The full TA-1301/TA-1302 provider audit totals twelve successful, documented,
unauthenticated Stats Guy Fantasy GETs. No FantasyPros request, secret, article
scrape, recommendation, or Sleeper write occurred.

## Verification

- Fourteen dedicated synthetic tests cover API and import format selection,
  identity, coverage, freshness, numeric validation, value changes, attribution,
  scoring limitations, replay integrity, cache output, and all fallback modes.
- Ninety focused Trade market/evaluation/snapshot/value-board tests pass,
  confirming that intrinsic entered-trade evaluation remains chart-optional.
- All 605 repository tests pass.
- Full Ruff checks pass.
- `git diff --check` passes; line-ending notices are informational only.

## Remaining boundary

TA-1302 supplies evidence but deliberately does not change target discovery,
candidate construction, fairness thresholds, or recommendation labels. TA-1304
is the next P0 finder task and may now consume this board. TA-1303 remains
optional P1 performance context and does not block the core finder. No later
Trade task is authorized by this completion record.
