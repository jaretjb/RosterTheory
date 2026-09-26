# MA-002c: decision-scoped missing player evidence

Implements [MR-02 section 3.1](MODULAR_REQUIREMENTS.md#31-missing-evidence-must-have-decision-specific-consequences)
on PR #37. Source scoring remains strict; unknown data is never filled with zero.
No provider requests, live simulations, calibration transfers or league actions.

## Decision behavior

An incomplete unchanged player no longer rejects an entire Trade roster or its
opponents. Missing identities and forecasts remain visible, owned and protected
from package construction and automatic add/drop selection. Required cuts still
count those occupied slots. Known K/DST identities outside Trade's existing skill
universe retain that established feature boundary; this is not a K/DST expansion.

The feature compares its known-player subset and classifies the actual move:

| Evidence relation | Trade | Waiver |
| --- | --- | --- |
| Independent lineup, depth and bounded risk effect | Existing verdict with scoped confidence and incomplete whole-roster forecast disclosure | Existing policy gates may pass; source incompleteness stays visible |
| Missing player could affect the move | CONDITIONAL comparison; no accepted offer or proved best package | WATCH with CONDITIONAL_ROSTER_EVIDENCE; no affirmative claim/add |
| Actual asset evidence or required legality unavailable | Default exact evaluation blocks that package | Blocks that add/drop; other candidates may continue |

The existing explicit Trade partial-schedule option remains exploratory. It
cannot turn missing actual-asset evidence into a complete recommendation.
Rank-only comparisons likewise retain their existing non-lineup scope.

## Dependency proof and conservative limits

Neutral mechanics close actual changed-player eligibility over the league's
lineup slots and all multi-position bridges. Ordinary FLEX connects RB/WR/TE;
SUPER_FLEX also connects QB. This safety test does not advertise superflex support.
A missing future week remains missing even if the player is injured now. No rank,
bench label, projected return date or materiality cutoff proves irrelevance.

Feature policies add dependencies beyond shared slots. Required Trade secondary
moves remain conditional because unknown players can affect the choice of cut or
replacement. Waiver QB holding decisions include bench opportunity cost. Both
features conservatively retain a dependency when an available player could fill
the omitted component: depth calculations compare replacement floors across
open slots. Unresolved player identity cannot establish position independence.

For genuinely separate components, lineup and depth differences cancel. Absolute
roster totals, exposure shares and risk scenarios remain subset estimates. The
offense-downside gate uses an upper bound instead of treating subset risk as full
roster risk. For unchanged unknown contributions C_i:

`max(A_i + C_i) - max(B_i + C_i) <= max_i(A_i - B_i)`.

The bound includes zero and a 0.004-point numerical allowance for four loss
calculations derived from scores rounded to 0.001. This is rounding protection,
not a football materiality threshold. If the bound cannot establish the risk
gate, the comparison stays conditional. Unknown projections are never estimated.

## Search and evidence

Trade discovery, ordinary search and target-package search continue over known
assets on affected rosters. Partial risk estimates cannot dominate complete
comparisons or earn a lowest-risk objective tag. Conditional comparisons cannot
count as accepted, establish OFFER_FOUND or pass consolidation approval.
Reports label conditional fit and incomplete whole-roster metrics. Existing
`roster_exclusions` fields now inventory protected evidence gaps; they no longer
mean every decision on that roster was rejected.

Waiver protects unknown incumbents while evaluating other legal drops. Conditional
results retain WATCH and explicit uncertainty through text reports and manifests.
Source completeness, candidate confidence and search-budget completeness remain
separate. No unconditional best-overall claim follows from a conditional result.

Full-data schemas and semantic baselines remain unchanged. Partial-result hashes
and verdicts intentionally change; regenerate old reports before using this
behavior. No previously saved evidence is rewritten. Rollback is a PR revert of
this slice; it restores the overbroad veto and should not be called a data fix.

## Validation

The local suite passed 860 tests, including all 24 unchanged MA-001 semantic
workloads, existing provider coverage tests and snapshot-clock regressions.
Thirteen new tests cover slot graphs, multi-position bridges, independent
projection sweeps, conservative risk maxima, future-week gaps, replacement and
secondary dependencies, protected identity/capacity, candidate searches and
conditional reports. Existing tests that required a whole-roster veto now assert
protected assets and conditional comparisons instead. No golden was regenerated.

Run `python -m unittest discover -s tests` with `PYTHONPATH=src;.` on Windows.
`scripts/ma002_decision_benchmark.py` measures the frozen MA-001 Trade/Waiver
searches, one warm-up and five repetitions, verifying every result against its
existing golden. `--source-root` allows a read-only archive of the previous commit
to run the same workload. Local measurements are not production latency promises.

Five-repetition medians on this Windows workspace, comparing a read-only archive
of `d986d13` with this slice (seconds):

| Frozen scope | Before | After |
| --- | ---: | ---: |
| Reference A / Trade bounded search | 1.241529 | 1.237384 |
| Reference A / Waiver six-candidate search | 4.334307 | 4.077171 |
| Reference B / Trade bounded search | 3.134673 | 3.223389 |
| Reference B / Waiver six-candidate search | 20.510208 | 18.161459 |

After-run repetitions were A Trade 1.237384/1.226897/1.245254/1.257989/1.235787;
A Waiver 4.050796/4.045599/4.124732/4.077171/4.151743;
B Trade 3.223389/3.295569/3.276778/3.165315/3.166614;
B Waiver 19.288105/17.951645/18.161459/19.294617/17.146993.
Before-run repetitions were A Trade 1.234444/1.242259/1.241989/1.236835/1.241529;
A Waiver 4.287076/4.297584/4.632841/4.334307/4.974945;
B Trade 3.208036/3.171779/3.117429/3.123905/3.134673;
B Waiver 19.215677/20.617725/20.554918/20.344533/20.510208.

The largest median increase was 2.8% (about 89 ms) for B Trade. Other medians
fell; no optimization or speedup is claimed from these background-sensitive
local runs. Every measured result matched its existing golden. Partial searches
can do more useful work than the previous immediate rejection, so equal latency
for missing-data searches is not promised. Existing search budgets still apply.
Ruff, context routing and repository privacy gates pass; required remote CI
remains the merge gate.

Provider `fum_rec` applicability and omitted-field semantics remain unresolved;
neither reference league becomes production-ready from this change. Issue #30,
the broader MA-002 milestone and separate roster-membership work remain open.
