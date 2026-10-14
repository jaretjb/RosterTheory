# Waiver Assistant current status

Updated: October 13, 2026 (America/Los_Angeles)

WA-031 restores five-season expert selection to the live weekly and ROS Waiver
path, weighted newest-to-oldest 30/26/21/15/8 with historical coverage adjustment
and source concentration limits. Panels are independent by position/horizon;
their historical weights survive ballot aggregation. Unfiltered ECR stays
separate and cannot fill missing selected votes. ROS selection explicitly uses
weekly accuracy as a proxy. Contributor audits explain missing identities,
history, dates, ballots, unhonored filters and selection cutoffs.

Archived history was restored locally, but older annual populations remain
partial and are reported DEGRADED. Misdated historical API responses and
individual ROS responses that ignore requested experts are rejected. Separate
live input preparation succeeded for both leagues. Acquisition, QB holding,
injury retention and league-local calibration are unchanged. Detailed evidence:
`docs/COMPLETED_WAIVER_ASSISTANT_WA_031.md`.

WA-030 (PR #81) weekly skill streamers, specialist comparisons, dependency-based
readiness, calendar-date freshness and machine audits remain. Shared-slot or
unknown-roster cases still require ordinary validation. WA-029 caching remains.

All 1,069 tests, Ruff, context/privacy/package checks and isolated installation
pass. Separate issues track specialist parity (#78), provider forecasts (#79),
and weekly-only evaluation (#80). Draft 2026 remains closed; product policies
stay separate. No Sleeper write or tracked private calibration occurred.
