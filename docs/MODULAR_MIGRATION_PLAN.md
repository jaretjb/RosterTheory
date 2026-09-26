# Modular RosterTheory: migration and validation plan

Status: MA-002 authorized; capacity merged in PR #40; MA-002g historical scoring active

Date: September 25, 2026 (America/Los_Angeles)

References: [requirements](MODULAR_REQUIREMENTS.md), [architecture](MODULAR_ARCHITECTURE.md)

## 1. Delivery contract

Approve the planning package before activating implementation. Keep one bounded
product milestone active; use separate branches and PRs for every change, never
commit or push directly to main. A roadmap row or GitHub issue is not execution
authorization. The current Draft closure and feature promotion gates remain.

This document is the canonical requirement-to-work mapping. GitHub issues track
delivery discussion and PR links; maintain IDs/status consistently here when
issues are opened or closed. Do not create a second competing full backlog.
Only the nearest milestone has a detailed implementation contract below.

MA-000 delivers the three planning documents, reconciliation links and issue
sequence. It does not run providers, alter private settings or product code,
change recommendation policy, activate later work, or merge itself.

## 2. Sequence and traceability

The user authorized MA-002 on September 26 and requested continuation after
merging PR #40. ACTIVE_MILESTONE selects MA-002g Waiver historical scoring
evidence, a bounded #30 follow-up. PRs #37–#40 brought scoring, decision-scoped
coverage, membership, Draft rule admission and operation capacity onto main. Remaining MA-002
slices need their own detailed contracts and activation after the tested handoff;
MA-003 onward remain **planned, not authorized**.

MA-001 evidence: [reference and migration baseline](MODULAR_BASELINE.md).
Tracking: [#29](https://github.com/jaretjb/RosterTheory/issues/29). Verified
follow-ups are #30/#31 (MA-002), #32 (MA-003), and #33 (MA-004); creating these
issues does not activate them.

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

## 3. MA-001: detailed next milestone contract

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
