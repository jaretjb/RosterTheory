# TA-1314: automatic completed-result inputs

## Cause and repair

The finder automatically appended prospective weekly expectations, but its
completed-outcome path required a separate manual JSON import. Normal targets
and package-search commands never fetched completed results. Empty result
ledgers therefore kept recent-performance support unavailable indefinitely.

Normal live Trade commands now collect prior results for captured weeks within
that league's configured performance window. The adapter combines:

- Sleeper league matchup `players_points`, including bench players, for actual
  points under the league's scoring. Generic PPR/half-PPR totals are not used.
- Sleeper weekly `gp` for verified participation. Missing participation is not
  treated as a played zero-point game.
- nflverse regular-season schedule rows with observed final scores, an explicit
  Eastern kickoff, and source capture times. The final-score observation time
  is a conservative completion bound, not a fabricated final-whistle time.
- Player-team identity retained with new pregame captures. Legacy captures can
  recover identity only from their exact saved snapshot, matched by league,
  season, scoring and capture time. Today's team is never used for an old game.

No sparse raw-stat field is silently zero-filled. No actual position rank is
invented from a league's incomplete roster universe. The adapter uses no
FantasyPros requests and makes no Sleeper writes. League/scoring-scoped cached
results and hashed source evidence live in ignored local storage, with a 24-hour
refresh interval. Corrections append new observations; unchanged data does not
duplicate outcomes. Provider failures remain visible optional-context failures.

Sources: [Sleeper matchups](https://docs.sleeper.com/#getting-matchups-in-a-league)
and [nflverse schedule fields](https://nflreadr.nflverse.com/articles/dictionary_schedules.html).
The live response additionally verifies the `players_points` and participation
fields used by this adapter; they are not all documented in Sleeper's examples.
Raw provider rows and private league identities remain untracked.

## What this does not establish

Historical pregame expectations cannot be reconstructed from today's forecast.
Late captures still fail, and each league's existing minimum-games requirement
remains unchanged. A loaded result is not automatically a compatible signal.
Known manual partial/inactive annotations are preserved. The public sources
verify participation but cannot universally identify injury-shortened games;
this limitation is displayed and manual partial-game evidence takes precedence
over automatic collection. Players not rostered in that historical league
matchup may lack league-scored results and are explicitly excluded.

Performance context remains supporting evidence for the existing target
ranking. It cannot change ROS expert order or independently authorize a trade.
Saved historical replay uses its stored context without fetching current data.
Waiver's unchanged kickoff conversion was extracted to a neutral shared helper;
no Waiver policy or scoring behavior changed.

## Verification

Synthetic regressions exercise exact league totals, usable pregame joins,
late-capture rejection, idempotency, corrections, cross-league cache isolation,
legacy team recovery, team aliases, final-score/participation/point failures,
manual partial-game preservation, offline behavior, and provider failures.
The existing Trade history, signal and replay tests also pass. Two separate
live league checks loaded 243 and 289 completed player-week observations. Each
produced seven compatible contexts. One illustrated player had a valid Week 3
shortfall, but a late Week 2 capture left only one eligible game; the two-game
requirement correctly kept that signal incompatible. Unavailable league player
totals and unverified participation remain explicit. These results do not
promote league-wide coverage or calibration.

Ruff, focused/context tests, wheel/sdist build and distribution checks, and a
clean wheel installation passed. The full 978-test regression run passed;
the final eight-test outcome suite also passed after the team-alias regression
was added. Context routing and staged repository privacy checks passed.

Delivery depends on PR #70's position-aware forecast coverage; it does not
promote the provisional Trade calibration policies.
