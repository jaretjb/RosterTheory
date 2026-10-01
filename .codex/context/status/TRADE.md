# Trade Assistant current status

Updated: September 30, 2026 (America/Los_Angeles)

TA-1314 connects normal live Trade runs to completed league-scored outcomes.
The former path captured expectations but required manual outcome import.
Collection retains source evidence, historical team identity, pregame timing
and sample requirements. Missing results remain explicit; early-exit detection
is limited. Detail: `docs/COMPLETED_TRADE_ASSISTANT_TA_1314.md`.
Depends on unmerged PR #70. Separate live checks loaded 243/289 outcomes,
with seven compatible contexts each. All 978 full-suite tests and eight final
outcome tests pass, plus Ruff, context, package and clean-install checks.

TA-1313 shipped through PR #25. Trade
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
TA-1314 is active. TA-1310 empirical
calibration remains unpromoted pending sufficient dated evidence. Trade is
read-only.
