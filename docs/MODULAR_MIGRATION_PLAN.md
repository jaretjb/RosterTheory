# Modular RosterTheory: migration and validation plan

Status: MA-004a through MA-004e merged in PRs #54-#58; MA-004f Draft legality/season correction active; MA-002 evidence follow-ups remain open

Updated: September 27, 2026 (America/Los_Angeles)

References: [requirements](MODULAR_REQUIREMENTS.md), [architecture](MODULAR_ARCHITECTURE.md)

## 1. Delivery contract

Approve the planning package before activating implementation. Keep one bounded
product milestone active; use separate branches and PRs for every change, never
commit or push directly to main. A roadmap row or GitHub issue is not execution
authorization. The current Draft closure and feature promotion gates remain.

This document is the canonical requirement-to-work mapping. GitHub issues track
delivery discussion and PR links; maintain IDs/status consistently here when
issues are opened or closed. Do not create a second competing full backlog.
The active MA-004f slice has a detailed contract below; MA-001's baseline
contract remains as a completed reference.

MA-000 delivers the three planning documents, reconciliation links and issue
sequence. It does not run providers, alter private settings or product code,
change recommendation policy, activate later work, or merge itself.

## 2. Sequence and traceability

MA-001 froze the reference behavior. MA-002 established scoring, membership and
capability contracts, with #30 and #31 still open for source and rule evidence.
MA-003 extracted shared Trade/Waiver preparation in PR #51; its shared provider
limit follow-up merged in PR #52 and closed #32. MA-004a through MA-004e established
Draft analysis, simulation, advice and watcher ownership in PRs #54-#58.
The active MA-004f slice corrects issue #33's Draft legality and season evidence;
support promotion remains a separate decision.

MA-001 evidence: [reference and migration baseline](MODULAR_BASELINE.md).
Tracking: [#29](https://github.com/jaretjb/RosterTheory/issues/29). Verified
open follow-ups are #30/#31 (MA-002) and #33 (MA-004). Creating an issue does
not activate its implementation.

MA-002a's [scoring contract](MODULAR_SCORING_CONTRACT.md) defines the additive
scope, independent expectations and later behavior integration for #30. This
slice does not replace the broad MA-002 exit conditions below.
MA-002b's [provider integration](MODULAR_PROVIDER_SCORING.md) exposes incomplete
weekly projection scoring in shared Trade/Waiver preparation. It leaves #30
open for unresolved provider evidence and the other scoring consumers.

MA-002c's [decision coverage](MODULAR_DECISION_COVERAGE.md), merged in PR #37,
satisfies the user's correction that irrelevant missing players must not block
independent trade/waiver comparisons. Preserve unknown assets and explicit
conditional results without disabling scoring checks or globally enabling
partial schedules. Provider-definition work remains under #30.

MA-002d's [membership contract and evidence](MODULAR_ROSTER_MEMBERSHIP.md) preserves
taxi membership, validates ownership/capacity and reserve eligibility, rejects
known taxi formats, and versions normalized snapshot evidence. Its reviewed
schema-only baseline migration retains the original MA-001 golden. Draft
position-limit semantics and full feature capability admission remain open under
#31; this slice does not establish the future support matrix.

MA-002e's [Draft rule admission](MODULAR_DRAFT_RULE_ADMISSION.md) establishes a
scoped capability contract and guards room-backed recommendations against
unresolved position-limit evidence, including cached recommendations. Both
reference Draft profiles remain LIMITED for this scope. Provider cap mapping,
other draft modes and operation-specific in-season capacity remain under #31.

MA-002f's [operation capacity](MODULAR_OPERATION_CAPACITY.md) observes temporary
over-limit rosters without hiding them. It permits conditional Trade comparisons
and independent Waiver searches while user acquisitions still require legal
capacity and reserve state. Positional-cap source mapping and full admission
remain under #31.

MA-002g's [historical scoring evidence](MODULAR_HISTORICAL_SCORING.md) keeps
partial Sleeper season/recent-week point totals out of Waiver rankings while
preserving independent candidates and per-player warnings. Other legacy
scoring consumers and provider field semantics remain under #30.

MA-002h's [emerging-scenario scoring evidence](MODULAR_EMERGING_SCORING.md)
requires complete applicable statistics before a Waiver breakout scenario is
valued. The main Waiver comparison stays independent. Draft imports and
provider field semantics remain under #30.

MA-002i's [Draft manual scoring evidence](MODULAR_DRAFT_MANUAL_SCORING.md)
preserves missing-versus-zero evidence in preseason CSV exports and excludes
incomplete point totals from replacement baselines and readiness. Expert ranks
remain available; the live API import remains separate under #30.

MA-002j's [Draft API scoring evidence](MODULAR_DRAFT_API_SCORING.md) routes the
remaining production Draft scorer through complete, season-scoped evidence and
checks top-board coverage before reporting import readiness. Provider field
semantics and ranking-horizon authority remain unresolved under #30.

MA-002k's [Draft ranking-scope evidence](MODULAR_DRAFT_RANKING_SCOPE.md)
requests preseason rankings explicitly and admits only responses that declare
the requested season, week, position, scoring and Draft horizon. Unknown and
mismatched ranking sources remain incomplete; provider field semantics and
actual-source coverage still require evidence under #30.

MA-002l's [Draft projection-scope evidence](MODULAR_DRAFT_PROJECTION_SCOPE.md)
requests week-zero projections and requires provider-declared season, week and
position before raw statistics become Draft points. Rejected sources cannot
invalidate independent position responses through duplicate IDs. Provider field
semantics and actual-source coverage remain open under #30.

MA-002m's [projection-source tier evidence](MODULAR_PROJECTION_SOURCE_TIER.md)
observes aggregate sample-tier preseason responses without publishing player
data. It prevents a sample or unverified projection source from making an API
Draft board ready even when the expert directory looks premium. Actual premium
field coverage and unresolved source semantics remain under #30.

MA-002n's [ranking-source tier evidence](MODULAR_RANKING_SOURCE_TIER.md)
observes limited consensus and individual Draft ranking responses despite a
`premium` tier label. It prevents sample or unverified ranking responses from
making a Draft board ready while preserving inspectable diagnostic ranks.
Actual premium source coverage remains under #30.

MA-002o's [working-workflow reconciliation](MODULAR_WORKFLOW_RECONCILIATION.md)
compares the accepted pre-MA-002 paths with preserved aggregate evidence. The
successful grouped Draft path is distinct from the direct API import probes.
The new room gate stops both reference Draft configurations, and strict weekly
scoring makes cached forecasts unusable for Trade/Waiver value preparation.
The slice corrects proven misclassification and records remaining behavior
choices without calling incomplete scores complete.

MA-002p restores the prior usable in-season forecast path as an explicitly
conditional estimate when core position statistics are present. It preserves
strict exclusion for missing core or invalid evidence, exposes incomplete
scoring on value boards, and limits Trade/Waiver decision labels while source
fields remain unverified.

| ID | Milestone / proposed issue title | Depends on | Requirements | Exit evidence |
| --- | --- | --- | --- | --- |
| MA-000 | Review bounded league support and modular migration design | None | MR-01 through MR-14 | Planning PR reviewed; authority/conflicts resolved; no product changes |
| MA-001 | Freeze reference profiles, compatibility cases and migration baseline | MA-000 | MR-01, MR-02, MR-06, MR-09, MR-10, MR-13, MR-14 | Exact redacted rule inventory; synthetic fixtures; current tests; known-defect ledger; measured baseline |
| MA-002 | Establish league-rule and scoring coverage contracts | MA-001 | MR-01 through MR-07 | Shared contracts and capability assessment; explicit stat completeness and roster membership; separate bug-fix PRs |
| MA-003 | Extract neutral preparation and coordinate provider infrastructure | MA-002 | MR-06 through MR-12 | Waiver no longer imports Trade workflows; pure core; snapshot consistency; process-safe budget/pacing tests |
| MA-004 | Modularize Draft and complete application/presentation boundaries | MA-003 | MR-05 through MR-10, MR-12, MR-13 | Draft package and compatibility adapters; reviewed shared-mechanics equivalence; dependency gates across all features |
| MA-005 | Validate and publish the bounded half-PPR support matrix | MA-004 | MR-01 through MR-14 | Both exact profiles and 12 base combinations; command limits, ancillary modes and performance gates documented |
| MA-006 | Validate standard and PPR through the same contracts | MA-005 | MR-01, MR-02, MR-04, MR-06, MR-08 through MR-14 | 36 total base combinations; format-correct provider/rank/cache paths; no inherited calibration claims |

MA-002 through MA-004 can contain several sequential PRs. Do not turn their row
titles into permission for a single large rewrite. Each activation identifies
the next small issue/PR slice, allowed paths and stopping condition.

### MA-004a: Draft analysis package foundation

After merged PR #52, move the existing `draft_analysis.py` implementation into
`draft/analysis.py` and add a `draft` package. Keep `draft_analysis.py` as a
thin compatibility import so existing scripts, tests and users can still use
the old path. Change internal imports to the new owner only where doing so
does not create a cycle. The affected product files are the new package, the
old analysis module and direct import sites; tests and this handoff may change.
Do not move `simulation.py`, the watcher or the ranking stack in this PR.

This is a source-ownership change, not a behavior correction. Preserve all
public analysis names and signatures, Draft command spelling and output,
serialized fields, decisions, reasons, numeric results, deterministic ties,
policy caps, 2026 season assumptions and replay/build-hash checks. Do not
auto-rewrite old artifacts or suppress an unexplained difference. A source
hash may change because files move; compare declared semantic fields and keep
exact-build replay enforcement. Issue #33's legal-versus-preference cap and
season-evidence fixes require a separate, reviewed behavior PR. #30/#31 do
not become proof of wider format support through this extraction.

Acceptance: both synthetic reference leagues retain the reviewed Draft
analysis and recommendation evidence; old and new analysis import paths expose
the same callable objects; CLI parser and result contracts remain stable; the
new `draft` module has no provider, storage, CLI or other-feature dependency.
Focused `test_draft_analysis`, `test_simulation`, `test_mock_watcher`,
`test_cli_discovery` and `test_modular_baseline` checks precede the full suite.
Run Ruff, package/install smoke, context routing, staged privacy gate and CI.
Review MA-001's fixed-seed Draft turn and strategy timing on the same machine
against its proposed 20% runtime and 25% allocation review thresholds. Use
synthetic fixtures and no paid calls or Sleeper writes. Stop at a tested PR;
reverting that PR restores the old module layout without changing user data.

### MA-004b: Draft simulation package extraction

After merged PR #54, move the existing `simulation.py` implementation to
`draft/simulation.py`. Keep `simulation.py` as a compatibility import so existing
users, tests and scripts can still import every public and currently used private
name. Change production import sites to the new owner only when no cycle results.
The affected product files are the new module, compatibility adapter and direct
import sites; tests and the Modular handoff may change. Do not move watcher,
ranking or preference implementations in this PR.

This is a source-ownership change. Preserve all Draft decisions, reasons,
numerical outputs, deterministic ties, commands, result fields, policy caps,
2026 season assumptions, schemas and exact-build replay checks. A source hash
may change with the move; compare complete semantic evidence without suppressing
an unexplained difference. Issue #33's cap and season fixes require a separate
behavior PR. Do not claim wider league support or new calibration.

Acceptance: old and new simulation imports expose the same objects; both
synthetic reference leagues retain reviewed Draft turn and strategy evidence;
CLI parser and result contracts stay stable. Run focused simulation, watcher,
Draft, CLI and modular baseline tests, then the full suite, Ruff, package/install
smoke, context routing, staged privacy gate and CI. Compare MA-001's fixed-seed
Draft turn and two-trial strategy timing and Python allocation on the same machine
with five measured repetitions after warm-up against the 20% and 25% review
thresholds. No paid provider calls or Sleeper writes. Stop at a tested PR;
reverting it restores the prior module layout without changing user data.

### MA-004c: Draft advice package extraction

After merged PR #55, move the existing `assistant.py` implementation to
`draft/assistant.py`. Keep `assistant.py` as a compatibility import for public
and currently imported private names. Change internal imports to the new owner
only where no cycle results. The affected product files are the new module,
compatibility adapter and direct import sites; focused tests and the Modular
handoff may change. Do not move watcher or ranking implementations in this PR.

This is a source-ownership change. Preserve `recommend_available` and its
sorting, scores and output fields; preserve signatures, Draft commands, result
fields, decisions, reasons, deterministic ties, policy caps, season assumptions,
schemas and exact-build replay checks. A source hash may change with the move;
compare complete semantic evidence without suppressing unexplained differences.
Issue #33's cap and season fixes require a separate behavior PR. No wider
league support or new calibration follows from this extraction.

Acceptance: old and new assistant imports expose the same callable objects;
both synthetic reference leagues retain reviewed Draft turn and strategy
evidence; CLI parser and result contracts stay stable. Run focused assistant,
simulation, watcher, CLI and modular baseline tests, then the full suite, Ruff,
package/install smoke, context routing, staged privacy gate and CI. Compare
MA-001's fixed-seed Draft turn and two-trial strategy timing and Python
allocation on the same machine with five measured repetitions after warm-up
against the 20% and 25% review thresholds. Use synthetic inputs only. Open one
tested PR with before-and-after evidence, then stop without merging it. No new
issue is needed; reverting the PR restores the prior layout without user data
changes.

### MA-004d: Draft watcher state and recommendation extraction

After merged PR #56, move the watcher's Draft state transitions, room timing and
recommendation logic into `draft/watcher.py`. Keep `mock_watcher.py` as the
compatibility entry point for old imports, current Sleeper polling and human
report formatting; move those effects to application and presentation in later
reviewed slices. Change safe internal imports to the Draft owner. Do not move
ranking implementations or change issue #33's cap and season rules. Move the
existing taxi membership admission check to a neutral core helper while keeping
its provider entry point and exact rejection behavior.

This is a source-ownership change. Preserve watcher recommendations, transitions,
warnings, report fields, polling cadence, command spelling, output and replay
checks. Compare complete semantic evidence without suppressing differences; a
source hash may change with the move. No provider calls, Sleeper writes, wider
league support or new calibration follows from this extraction.

Acceptance: old and new paths expose the same moved callables; the Draft module
does not import Sleeper polling, providers, storage, CLI or other assistants.
Focused watcher, Draft, CLI and modular baseline tests precede the full suite.
Run Ruff, package/install smoke, context routing, staged privacy gate and CI.
Compare MA-001's fixed-seed Draft turn and two-trial strategy timing and Python
allocation on the same machine with five measured repetitions after warm-up
against the 20% and 25% review thresholds. Use synthetic inputs only. Open one
tested PR with before-and-after evidence, then stop without merging. No new
issue is needed; reverting the PR restores the old source layout without user
data changes.

### MA-004e: Draft watcher application and presentation boundaries

After merged PR #57, move `MockDraftWatcher` polling into
`application/draft_watcher.py` and the human report formatter and its private
helpers into `presentation/draft_watcher.py`. Keep `mock_watcher.py` as an
import-only compatibility path for old public and currently used private names.
The CLI imports each new owner directly; Draft decisions remain in
`draft/watcher.py`. Do not change ranking policy, issue #33's cap and season
rules, or any provider behavior.

Preserve GET-only polling, duplicate and changed-turn handling, caching,
warnings, report schema, human text and color output, JSON collection and exit
codes. Compare equivalent synthetic watcher reports and rendered text before
and after. Source relocation may change build hashes; retain exact-build replay
enforcement. No paid provider calls, Sleeper writes, wider league support or
new calibration follow from this extraction.

Acceptance: old and new imports expose the same moved class and formatter;
application imports Draft/provider infrastructure but no presentation, while
presentation imports no provider, application or evaluation module. Focused
watcher, CLI, admission, reference and boundary tests precede the full suite.
Run Ruff, package/install smoke, context routing, staged privacy gate and CI.
Use synthetic five-repeat watcher timing and allocation evidence on the same
machine, with complete semantic report and text hashes equal. Open one tested
PR with before-and-after evidence, then stop without merging. No new issue is
needed; reverting it restores the prior layout without user data changes.

### MA-004f: Draft legal capacity and season evidence (#33)

After merged PR #58, make one behavior PR that separates legal roster
eligibility/capacity from the existing Draft acquisition preferences. An
otherwise legal third QB must be distinguishable from a policy-disfavored pick.
Do not infer Sleeper position maxima from starter slots or app preferences;
retain the existing unknown-rule advisory when enforcement is unresolved.
Keep selected strategy objectives, deterministic ties, K/DST treatment and
exact-build replay checks. Any intentionally changed decision gets a named
synthetic before/after case and migration impact.

Remove the implicit 2026 bye schedule from deterministic Draft strength.
Require explicit season-matched schedule evidence, validated at the CLI edge,
before bye-aware simulation or completed-mock scoring. Missing, incomplete or
wrong-season evidence fails with a recovery path; no private schedule, provider
call or Sleeper write is needed for tests. Exercise all 10/12-team snake slots,
final roster capacity and starter feasibility, edits/undos and schedule failure
cases using synthetic players and rules. Review same-machine fixed-seed Draft
timing/memory against MA-001 and record an absolute Draft clock budget before
MA-005. Run focused/full tests, Ruff, package/install smoke, context/privacy
gates and CI. Open one PR and stop without merging. Revert that PR to roll back;
no user data is migrated.

## 3. MA-001: completed baseline contract

### Problem and outcome

Existing tests and status notes are useful but do not specify the exact support
envelope, public compatibility surface, independent correctness expectations, or
runtime budget for migration. Establish that baseline before moving calculations.

### Allowed work and context

After separate activation: synthetic fixture/test additions, concise baseline
documentation, a reproducible offline comparison/benchmark harness when needed,
and read-only inventory of explicitly authorized current rule evidence. No
production algorithm changes. Provider retrieval is not automatic authorization:
if needed, follow IMPLEMENTATION_POLICY, preflight the exact data-only plan, and
record whether the source is current or unavailable. Never use private history as
public fixture material.

Load only requirements sections 2-5; architecture sections 3, 5-6; this section;
the selected test/source contracts; the active milestone and implementation
policy. Inspect additional feature requirement sections only for a named conflict.

### Deliverables and acceptance cases

1. Record the current main commit, Python/OS, dependency/tool versions and clean
   baseline checks. The audit's 802 passing tests are context, not a substitute
   for this new baseline run.
2. Inventory both reference profiles: full roster slots, bench, reserve count and
   eligibility, waiver/lock settings, scoring, draft ordering, and playoff rules.
   Preserve local source/date evidence; publish only synthetic/redacted rules.
   Resolve discrepancies with proposed scope before calling a profile verified.
3. Produce fixture factories for the two reference shapes with invented players,
   owners, IDs and provider data. Include two independent policies and raw
   evidence that may be shared without sharing derived state or calibration.
4. Capture each current public command/JSON schema and representative saved
   artifact readers: CLI flags/status/exit behavior, preparation, decisions,
   report fields, source/manifest checks and offline replay. Include defaults
   that might be changed by future unsupported-format gates.
5. Pin deterministic Draft recommendation/simulation/watch transitions; Trade
   diagnose/targets/search/entered-package and unequal-package consequences;
   Waiver search/evaluate, legal no-drop/full-roster choices, K/DST paths and
   shared-drop conditional plans. Keep expert horizons and observed limits.
6. Record a bounded known-defect ledger with synthetic reproductions and expected
   correct outcomes: missing scoring statistics labeled complete, caller-specific
   unsupported-category handling, taxi membership loss, Draft cap/season
   assumptions, and budget contention. Recheck suspected defects on current main
   before filing. Do not change runtime behavior in this milestone; encode fixes
   as later issue acceptance cases rather than a permanently red test suite.
7. Record baseline timings/memory and search coverage for the workloads in
   section 5. Select exact benchmark settings before optimization begins.
8. Produce a feature/operation capability inventory showing existing versus
   target behavior, and all evidence gaps. Structural support must never be
   recorded as empirical calibration or a ready current recommendation.

### Exclusions and stop condition

No broad file moves, new rankings or policy weights, fresh live recommendation,
new supported-format marketing claim, package dependency expansion, or changes
to user configuration. Stop with accepted baseline artifacts and linked
behavior-change issues. If current reference settings are unavailable, complete
synthetic/general work but report the profile inventory as incomplete; do not
activate MA-002 on an invented baseline.

### Verification and rollback

Run targeted baseline/contract tests while developing, then the complete compact
unit suite, Ruff, context routing, diff checks and working-tree/index privacy
gates for the final PR. Offline tests must make no external requests. Reverting
this additive test/documentation PR must not require changing user data.

## 4. Implementation issue template and change discipline

Each issue must include:

- Stable MA ID or child ID; mapped MR requirements and exact design sections.
- Concrete problem, observable outcome, scope and explicit exclusions.
- Dependencies, baseline commit/fixtures, affected compatibility surfaces.
- Named acceptance examples and independent expected results.
- Required tests, performance/evidence gates and rollback procedure.
- Policy/calibration implications, unavailable-data behavior and unresolved
  decisions; explicit statement that issue creation does not activate work.
- Completion evidence and PR links once delivered.

Separate mechanical extraction from bug fixes and policy changes. A renamed
module should preserve semantic results. Correcting a scoring coverage bug or
Draft cap has a separate PR with a demonstrated input, old output, correct output
and migration impact. Critical correctness fixes can precede the sequence only
through an explicitly revised active milestone and their own regression proof.

Do not merge experimentally improved recommendations as part of an architecture
PR. User-approved provisional thresholds remain provisional. Comparisons must
include the reason/coverage fields, not just the winning player.

## 5. Verification matrix and performance gates

### Correctness coverage

| Axis | Required checks |
| --- | --- |
| Reference profiles | Full three-feature workflows using exact verified rule maps and independent policies |
| Base roster family | All 12 half-PPR combinations; add the same 12 for standard and the same 12 for PPR in MA-006 |
| Draft slot/order | Every slot in 10- and 12-team snake rooms; early/middle/late states; next-pick and completion legality |
| Waiver/reserve/scoring modes | Every explicitly supported ancillary mode at least once end-to-end; pairwise combinations plus all known interacting combinations, especially capacity/IR/drop locks and scoring/position |
| Correctness oracles | Hand-scored stat lines; exhaustive small lineup/add-drop/trade cases; stable ties and exact-versus-bounded candidate equivalence where promised |
| Failures | Missing vs zero stats, invalid numbers, unsupported rules, incomplete identity, source/horizon mismatch, stale data, mid-run ownership changes, unavailable policy, provider failures and quota contention |
| Isolation | Same raw evidence with different league/scoring/policy/season keys cannot reuse derived results or readiness |
| Compatibility | CLI and artifact round trips, old-build replay, schema rejection/migration, cold/warm-cache semantic equivalence, offline/no-network behavior |

Do not rely exclusively on pairwise testing for critical interactions. A failing
combination restricts the advertised support matrix until resolved. Data-only
support and validated recommendation policy are reported separately.

### Workloads and thresholds

MA-001 freezes synthetic input sizes, seeds, search budgets and hardware details
for: cold/warm preparation without network latency; Draft single-turn and
strategy comparison; Trade entered/unequal package and bounded all-opponent
search; Waiver full candidate search; and offline replay. Include the largest
supported roster and both sparse and full evidence. Record stage timing, peak
memory, evaluated/pruned counts, cache sizes and completeness.

For behavior-preserving changes, proposed default gates are no more than 20%
median runtime regression or 25% peak-memory regression against the recorded
baseline on the same machine, using at least five measured repetitions after
warm-up and identical inputs/search scope. Reproduce failures and explain noisy
measurements rather than weakening search coverage. These are review gates, not
portable CI timing assertions. Before MA-005, establish and meet an absolute
Draft response-time budget suitable for the supported clock; preserving an
already-slow baseline alone is insufficient. Numerical targets come from MA-001
measurements and user workflow, not invented performance claims in this plan.

### Per-PR and promotion gates

- Appropriate focused tests while editing; one complete final unit-suite run for
  implementation PRs, plus configured Ruff and required CI.
- Dependency allowance may shrink but not grow; type-check changed shared
  interfaces once established. No huge style-only diff mixed into extraction.
- Clean package/install smoke checks when imports, resource paths or packaging
  change. Preserve required OS/Python CI coverage.
- Privacy checks on tracked tree and exact staged contents; inspect public PR
  bodies and fixtures for personal/provider evidence.
- Deterministic semantic comparisons include values, choices, reasons,
  limitations and evidence scope. Normalize only explicitly documented volatile
  presentation fields; never suppress an unexplained decision difference.
- Saved source hashes may change; exact-build replay checks must not be relaxed.
- Review planned-versus-measured performance and truthful bounded-search status.
- Support promotion requires all matrix entries and declared feature limitations,
  not merely a passing total test count or one successful live league result.

## 6. Active milestone and handoff

When implementation is explicitly authorized, keep ACTIVE_MILESTONE short and
link to the selected contract here. Include: MA issue/slice, permitted changes,
non-goals, baseline evidence, exact checks and stopping condition. Keep completed
history in existing completion records; this planning PR does not reorganize
that history. Load IMPLEMENTATION_POLICY only for implementation/provider work.

At milestone completion, record delivered PRs, test/benchmark evidence, remaining
limitations and the next proposed slice. Do not activate it automatically. No
Draft experiment promotion, live provider refresh or league-policy transfer is
implied by the next row in the table.

## 7. Review decisions and planning completion

Review the envelope, Trade specialist boundary, module ownership, conservative
compatibility approach and proposed performance gates as one planning package.
There are no additional blocking user decisions for this baseline. MA-001 records
observed profile settings and unresolved provider-stat/capability evidence.
Escalate only a discovered scope conflict or a proposed change to policy,
compatibility, runtime dependencies or operational permissions.

MA-000 delivered the three linked documents, reconciliation references and
context route through merged PR #27. Issue #29 tracks the separately activated
MA-001 baseline. Later issues remain inactive until their own bounded activation.
