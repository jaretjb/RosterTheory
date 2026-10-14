# Waiver Assistant current status

Updated: October 13, 2026 (America/Los_Angeles)

WA-032 is implemented and validated in [PR #85](https://github.com/jaretjb/RosterTheory/pull/85) on
`codex/waiver-weekly-roster-plans`, stacked on the unmerged WA-031 dependency.
Default search now returns ordered IR preparations, exact additions/drops and
independent specialist swaps. Bounded combinations compare actual owned-player
coverage, points, expert ROS value, depth and risk; successful prefixes and
failed-claim repair plans are revalidated. Marginal extra QBs must have useful
starts or incremental insurance. Injury retention distinguishes the replacement
cutoff. Expiring availability scenarios remain conditional with platform-status
fallbacks. `--objective ros` preserves the season-oriented view.

All 1,087 tests, Ruff, context/privacy/package gates and isolated installation
pass. The verified update is installed locally. Saved and fresh evidence was
audited independently in both requested leagues; fresh publication revalidation
passed. Unchanged-build offline replay verified both exact result hashes.
Plans reflect current ownership and disclose bounded search, close calls,
reactivation cost and coverage limitations. Detailed evidence:
`docs/COMPLETED_WAIVER_ASSISTANT_WA_032.md`.

WA-031 historical expert selection remains horizon/position-specific, with
coverage penalties and contributor audits. Older annual populations remain
partial/DEGRADED; ROS uses weekly accuracy as a declared proxy. WA-030/029
freshness, dependency readiness and caching remain. No empirical cross-league
calibration or global-optimum claim is made.

Separate issues track specialist parity (#78), provider forecasts (#79), and
weekly-only evaluation (#80). Draft 2026 remains closed; product policies stay
separate. No Sleeper write or tracked private calibration occurred.
