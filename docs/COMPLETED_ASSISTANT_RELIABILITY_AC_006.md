# AC-006 — Supported scoring formats and season portability

Implemented September 25, 2026 for issue #12 in
[PR #21](https://github.com/jaretjb/RosterTheory/pull/21); GitHub records its merge state.
AC-007 and AC-008 remain open. This is not closure of the full reliability audit.

## Verified provider capability

Primary references checked September 25, 2026:

- [FantasyPros API reference](https://api.fantasypros.com/v2/docs): NFL consensus
  rankings and projections document STD, HALF and PPR; rankings include weekly,
  ROS and WW horizons. Direct retrieval returned HTTP 403, so the indexed primary
  documentation was inspected. No paid endpoint was called for this work.
- [FantasyPros scoring settings](https://www.fantasypros.com/scoring-settings/)
  supplies the baseline scoring values used for mismatch disclosure.
- [Sleeper reception-bonus rules](https://support.sleeper.com/en/articles/3652730-how-are-reception-bonuses-calculated)
  establishes that positional reception bonuses stack with base reception points
  and follow primary position, not the lineup slot.

Provider UI support for custom formats is not evidence that the ranking API
offers a league-exact custom-scoring or superflex parameter. No such parameter,
synthetic expert ballot, or league-exact premium ranking is invented here.

## Changes

The league reception multiplier maps explicitly: 0 -> STD, 0.5 -> HALF, 1 -> PPR.
Other multipliers are visibly unsupported for ranking authority rather than
rounded to the nearest provider format. Nonfinite scoring is rejected. Existing
unknown-stat-category checks remain before paid board retrieval.

Weekly/ROS requests and cache parameters use that mapping. Provider responses
must declare matching season and scoring; cached responses receive the same
validation. WW configuration must match the league before paid retrieval, and
WW responses are independently checked. A response cannot be relabeled to make
the requested format or next season appear covered.

Custom QB scoring, positional RB/WR/TE reception bonuses, and actual roster slots
are applied through ordinary scoring/lineup code. Raw projections stay attached
to player identity regardless of expert order. Expert rankings remain baseline
authority; deviations, two-QB and superflex limitations are disclosed in board
metadata and player warnings. Missing primary position or required reception
stats marks premium projection coverage incomplete, not complete zero evidence.
Specialist performance uses the same primary-position scoring semantics.

Runtime Trade and Waiver board cache defaults follow the snapshot season.
Trade evaluate/search/target services and their CLI defaults no longer pin 2026.
Waiver shares the factual provider cache with its stricter freshness windows.
Default identity-override and draft-anchor paths follow the snapshot season;
manual expert pools require an explicit path instead of an implicit 2026 file.
The global request-budget file intentionally remains shared across seasons.

Week-one draft anchors require matching league key, league ID, season metadata
and declared scoring in the selected STD/HALF/PPR scope. An explicit timestamp
cannot bypass season checks in the live path. A missing current-season anchor
stays unavailable; it does not fall back to last year's file. ROS-ready refreshes
do not require any unused draft anchor. Configured league keys are not special-cased.
Historical diagnostic probes and explicit Draft tooling are not redefined by
this in-season change; their dated defaults do not supply live assistant authority.

## Verification and limits

Regression coverage was added before implementation. Tests exercise all three
formats, response/cache scope, custom and unknown formats, premium stats and
missing coverage, custom QB scoring, two-QB/superflex/flex lineups, expert-order
invariance, renamed leagues, current/next-season paths, stale anchors, and WW
configuration checks before paid retrieval. Existing missing-player, retention,
cross-position and claim-plan safeguards remain in the full suite.

The tracking summary and detailed AC-006 status have a consistency regression.
Verification: 776 tests pass (12 new format/season tests and one tracking
consistency regression); Ruff and diff checks pass. Focused provider, board,
snapshot and WW validation: 67 tests pass.
No live report, paid data refresh, Sleeper mutation or historical calibration ran.
League-exact custom expert rankings remain unavailable where the provider does
not document them; correct raw-stat projections do not change that limitation.
