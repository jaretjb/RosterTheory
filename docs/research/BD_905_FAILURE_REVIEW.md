# BD-905 failed-validation review

Reviewed September 15, 2026 (America/Los_Angeles). This is a bounded,
read-only diagnostic of the completed 2026 League Beta shadow validation. It
does not recalibrate another league, change Draft policy, or authorize a live
rollout. The public BD-905 row in docs/OPEN_TASKS.md records the failed gate.
The detailed result used here is an ignored local BD-905 artifact. The former completed
validation document named in the task row is absent from the current public
tree, so this review preserves only aggregate findings and method limits.

## Paired outcome

Both selection and confirmation have 24 complete pick-72/pick-96 decisions
across six acquisition environments. Selection used room seeds 905100 and
905101; disjoint confirmation used 905200 and 905201. Recomputed primary
rollout-minus-primary means match the saved summaries.

| Block | Decisions changed | Primary mean delta | Full-rank mean delta | Primary loss / gain / tie |
| --- | ---: | ---: | ---: | ---: |
| Selection | 19/24 (79.2%) | -0.302 | -0.905 | 3 / 1 / 20 |
| Confirmation | 15/24 (62.5%) | +0.079 | -0.541 | 3 / 1 / 20 |

Of the changed decisions, 15/19 in selection and 11/15 in confirmation had
zero measured primary utility change. The selection middle-QB/TE environment
lost 1.771 primary mean and 3.972 at the primary P10. One paired pick-72 room
there lost 7.083 primary utility and 15.504 full-rank utility. Full-rank mean
regressed in both blocks; confirmation had four full-rank losses and no
full-rank gain. The aggregate primary mean changes sign between blocks, and
the environment-level unblended middle-QB/TE mean also changes sign. This is
frequent decision churn without stable measured benefit, with a material
local downside.

The saved mean-regret delta equals the negative mean-utility delta because
regret is calculated against the better of only these two compared paths.
That metric is useful as a paired comparison, but does not provide an
independent promotion check. A future validation should declare a separate
regret benchmark and inspect the lower tail of paired utility deltas alongside
the absolute-score P10 gate.

## Recorded package feasibility

All nine FantasyPros packages pass feasibility in the fixed realized roster.
None has three of three complete opponent-redraft comparisons. Only five of
27 paired redraft scenarios complete; 22 are infeasible. The forced recorded
actual branch completes in seven scenarios and the forced alternative in
15; both complete in five. Failures occur when a forced target is no longer
available at the relevant pick after opponents redraft. A scenario with only
one feasible branch cannot supply a paired alternative value. The fixed-roster
scores therefore cannot rescue the failed validation gate or establish that
a recorded package survives changing opponent acquisition.

## Decision and next gate

The current rollout candidate remains rejected for promotion and offline
shadow-only. The saved pairing, block completeness, and mean calculations
check out; this review did not identify a data or seed-pairing defect that
reverses the loss. The small room count and missing original detailed public
record limit any claim about general rollout performance.

A future Draft research milestone may define a less volatile candidate policy,
an independent regret benchmark, and a prospectively feasible two-branch
package test. It must acquire new comparable evidence, predeclare the
offline selection and confirmation gate, and pass it for this league and format
before any future live-shadow work begins. That shadow would need normal-clock
latency, no stale or missed turns, deterministic evidence, and the immediate
unchanged primary recommendation whenever it is unavailable. Promotion would
need forward evidence, a predeclared materiality threshold, no meaningful
mean/P10 regression, a read-only smoke check, and separate user approval.
No 2026 live Draft operation or cross-league calibration follows from this
review.
