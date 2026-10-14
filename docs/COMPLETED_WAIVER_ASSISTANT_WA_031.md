# WA-031 — Historical expert weighting and contributor reconciliation

Implemented October 13, 2026. Scope is the user's approved recommendations 1–2.

The live Waiver path previously used unfiltered weekly consensus and a ROS
selector based on two accuracy fields with equal final contributor weights.
It now selects independent panels for each horizon and position from five
completed seasons of published weekly accuracy. Newest-to-oldest year weights
are 30/26/21/15/8. Weekly accuracy is explicitly a proxy for ROS selection;
the app does not claim measured ROS accuracy.

## Selection and authority

- Convert each annual overall rank to its percentile in that annual field.
  Normalize year weights over available observations, then multiply by
  `0.80 + 0.20 * observed_seasons / 5`. Require at least two seasons.
- Prefer three usable experts per position, require two, and allow at most two
  from the same source. Preserve historical scores in normalized ballot weights.
- Require current identities, position publication dates, current-horizon votes,
  and actual requested contributor IDs. Advertised membership is not a ballot.
- Fetch missing individual ballots in historical-score order within the shared
  cache, pacing and request budget. Never fill missing selected votes with ECR.
- Retain unfiltered market evidence separately. Per-player selected ranks require
  at least two selected votes and retain omissions and dispersion.
- Audit every discovered contributor's selection or exclusion, including missing
  history, identity, dates, ballots, unhonored filters and concentration/cutoff.
  Preserve freshness and material-news ballot exclusions.

Shared preparation adds optional callbacks with unchanged defaults for other
assistants. Historical accuracy parsing is neutral provider code; Waiver owns
selection and aggregation. The legacy selector remains for compatibility and
historical tests, but the live command no longer invokes it.

## Historical evidence and provider limitations

An ignored archived CSV contained 308 annual expert records. Its annual field
sizes agree with the published population rather than treating a top-ten table
as the whole field. All 50 locally saved public top-ten anchors match that CSV.
The earlier clipped CSV was preserved locally before restoring the archive.

The archive remains incomplete, especially in older seasons. The audit records
each year's recorded count and field size, and reports DEGRADED coverage.
Missing years receive the coverage adjustment; the app does not describe the
history as a complete annual population.

Budgeted API probes for completed years returned different accuracy years or
facts inconsistent with the annual leaderboard. Those responses were retained
locally and rejected. New API history replacement requires explicit matching
years, complete annual rank slots and agreement with available public anchors.
No misdated response replaced historical evidence.

Some individual ROS requests return other contributors despite the requested
expert filter. Those ballots are rejected and the reason is recorded. Missing
ROS directory identities may be reconciled from the current weekly directory,
but only identity/source facts are reused; ROS dates and votes require their
own verified response. Public website availability alone is not API authority.

## Validation

Focused fixtures cover weighted history, coverage penalties, source caps,
independent positions, missing and stale ballots, calendar-date precision,
unhonored filters, ROS identity reconciliation, missing player votes, duplicate
conflicts, API year/population checks, shared WEEKLY-PROXY integration and CSV
compatibility with existing consumers.

Live read-only input preparation succeeded separately for both configured
leagues. Weekly and ROS skill panels differ, and historical weights are
preserved. No search or Sleeper write was performed during these checks.
Private evidence remains in ignored runtime directories.

All 1,069 repository tests pass. Ruff, staged repository privacy checks,
wheel/sdist privacy checks and isolated installation pass. The existing
local command is updated from the verified wheel. These checks establish
implementation correctness and provider authority; they do not establish a
measured improvement in fantasy outcomes.

Acquisition thresholds, QB holding, injury retention, scoring, league-local
numeric calibration and Draft/Trade decision policies are unchanged. Further
waiver-policy recalibration remains separate work.
