# WA-033 — Required coverage and conditional claim alternatives

Authorized October 20, 2026, after repairing CI and merging PR #86. That PR's
checks failed because final status text exceeded its context budget and updated
decision wording had not been captured in the synthetic reference. Reviewed
reference differences changed wording, hashes and byte counts only. All checks
passed at the corrected head before the GitHub merge.

## Decision behavior

`waiver.coverage` recognizes a confirmed QB or kicker vacancy separately from
optional depth. It does not credit an assumed waiver acquisition as owned.
QB evidence records the actual owned-lineup gain, and preserves the old
replacement-floor and expert-value comparisons as separate tradeoffs.

A QB coverage exception requires a safe drop: no current or next-two-week
starter sacrifice, no additional near-term vacancy, and no top starting-quality
ROS holding. The original evidence, freshness, depth, downside and contingent
upside rules remain required. The exception applies only to that coverage move's
negative ROS cost, preventing an unrelated optional move from borrowing it.

A kicker's confirmed bye does not require inventing its missing weekly rank.
The target still needs a usable current weekly rank, fresh league-scored season
production, activity and news evidence. Replacement ranking uses the selected
league's existing season-production weight and sample prior. Complete missing
point forecasts remain unavailable, and this limitation is reported explicitly.

Conditional failure branches now include specialists. Failed targets become
unavailable for acquisition and replacement baselines; successful prerequisites
remain owned. The branch is re-evaluated through the same exact safety checks.
No named real player, league-specific threshold adjustment or forced backup
order is embedded in implementation or synthetic fixtures.

## Verification

Synthetic regressions cover required QB coverage with an expert-value tradeoff,
starter and elite-bye retention, optional depth, missing news, missing kicker
forecasts/ranks during a known bye, stale production and failed-target exclusion
from both acquisition and replacement pools. Existing reference candidate
decisions remain identical; reviewed hashes/sizes change for the additional
coverage evidence field. Full-suite, release and current-run evidence are
recorded with the PR handoff.

All 1,098 tests pass. Ruff, repository privacy, distribution checks and isolated
clean installation pass. A fresh read-only search with ownership/publication
revalidation selects the QB coverage repair plus independent defense and kicker
replacements. Its failed-claim branches preserve prior successes and provide
validated alternatives for all three requests. Historical synthetic reference
candidate decisions are unchanged; reference hashes and sizes include the new
coverage evidence field. The verified build is installed locally.

The reported frozen league case changes from an empty owned QB slot to complete
owned offense coverage. The required QB gains 17.559 actual owned points rather
than only 1.274 points over an assumed alternative acquisition. Both reviewed
kicker replacements become evaluable without an invented incumbent rank.
An offline audit is not a current recommendation. Fresh runs retain ordinary
publication and ownership revalidation. No Sleeper writes or private evidence
are committed; Draft/Trade policy remains unchanged.
