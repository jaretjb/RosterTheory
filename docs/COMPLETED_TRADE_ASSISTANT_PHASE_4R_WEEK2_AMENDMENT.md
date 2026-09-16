# Completed Trade Assistant amendment: Week 2 ROS transition

Completed September 5, 2026 (America/Los_Angeles). This record closes TA-417,
the user-directed amendment to Phase 4R's season-stage policy.

## Decision

- Use final Draft selected and market ranking evidence during Week 1 only.
- Beginning in Week 2, transition both ownership boards together when selected
  ROS ballots and market ROS ECR are fresh and complete.
- If that gate fails in Week 2, retain both explicitly labeled Draft boards for
  review. From Week 3 onward, stop before extending the Draft anchor unless the
  extension is explicitly approved.
- Keep ROS ownership value, weekly ranks, and weekly projections separate.
  `BLENDED` remains disabled.

This is a product judgment informed—but not dictated—by the proxy backtest:
Draft-only narrowly led Week 1, while weekly-only led Weeks 2 and 3. The
historical data cannot determine a true ROS/weekly combination because it lacks
point-in-time ROS boards.

## Live-learning contract

Every `trade values` refresh writes cutoff-safe, unblended long-term rank/value
and current weekly rank/projection evidence. Once outcomes become available,
the rolling-origin harness can compare ROS-only, weekly-only, projection-only,
and candidate combinations. No weight is tuned from the current roster, one
interesting player, or information published after the forecast cutoff.

The Week 2 retrieval plan now includes genuine ROS selected/market ranks,
expert-position revision times, unfiltered material news, and the current
weekly signal. Empty ROS or a provider Draft fallback fails the joint gate
instead of being accepted or crashing before the Week 2 review fallback.

## Validation

Fifteen focused fixtures cover the revised timing, joint transition, fallback,
post-Week-2 stop, market completeness, future-data rejection, and separate
horizon behavior. The repository-root regression suite passes 235 tests in
3.726 seconds. No live provider call or Sleeper write was made for this
amendment.

Phase 5 remains inactive and requires separate user approval.
