# Trade Assistant current status

Updated: September 25, 2026 (America/Los_Angeles)

TA-1313 is implemented on a separate branch and awaiting PR review. Trade
weekly projections now retain the provider's declared STD/HALF/PPR label while
rescoring usable raw stats under the league's Sleeper settings. Rank scope
remains exact; rows without required raw stats remain unavailable. The affected
league's ignored provisional target policy loads with obsolete fields removed,
without changing active thresholds or claiming calibration. A fresh read-only
League Beta search passed the former projection-format stop, evaluated 52
packages, and found no offers. Readiness remains INCOMPLETE because two rosters
each lack one Week 3 player projection. All 799 tests and Ruff pass; no Sleeper
write. Do not treat the live result as a ready trade recommendation.

AC-001–AC-008/#7–#14 are merged through PR #23. Their shared exact gates,
ranking caps, scoring formats, freshness contracts and bounded-search proofs
remain in force. Completed evidence is in the matching
`docs/COMPLETED_ASSISTANT_RELIABILITY_AC_*.md` records. The audit remains open;
TA-1313 is the only current implementation milestone. TA-1310 empirical
calibration remains unpromoted pending sufficient dated evidence. Trade is
read-only.
