# Trade Assistant current status

Updated: September 26, 2026 (America/Los_Angeles)

Snapshot-clock repair: schedule provenance age now uses the recorded snapshot
capture time, preserving IDs/seeds across rebuilds. Regression tests cover a
second boundary, the 24-hour schedule cutoff, and stale ownership rejection.
All 813 tests, Ruff, and privacy gates pass; the formerly flaky test passed 100
repeats. PR delivery is pending. No provider calls or decision-policy change.

TA-1313 implementation is complete; delivery is through PR #25. Trade
weekly projections now retain the provider's declared STD/HALF/PPR label while
rescoring usable raw stats under the league's Sleeper settings. Rank scope
remains exact; rows without required raw stats remain unavailable. The affected
league's ignored provisional target policy loads with obsolete fields removed,
without changing active thresholds or claiming calibration. The prior read-only
League Beta search passed the former projection-format stop, evaluated 52
packages, and found no offers. Readiness remains INCOMPLETE because two rosters
each lack one Week 3 player projection. Revalidation against PR #26 passed all
802 tests, Ruff, and tracked-tree/index privacy gates. No additional provider
refresh or Sleeper write. Do not treat the live result as a ready recommendation.

AC-001–AC-008/#7–#14 are merged through PR #23. Their shared exact gates,
ranking caps, scoring formats, freshness contracts and bounded-search proofs
remain in force. Completed evidence is in the matching
`docs/COMPLETED_ASSISTANT_RELIABILITY_AC_*.md` records. The audit remains open;
No other Trade implementation milestone is active. TA-1310 empirical
calibration remains unpromoted pending sufficient dated evidence. Trade is
read-only.
