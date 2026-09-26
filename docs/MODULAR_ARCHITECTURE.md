# Modular RosterTheory: architecture and contracts

Status: Approved design baseline; implementation requires a separate active milestone

Date: September 25, 2026 (America/Los_Angeles)

Authority: [requirements](MODULAR_REQUIREMENTS.md)

Delivery: [migration plan](MODULAR_MIGRATION_PLAN.md)

## 1. Design decision and observed baseline

Retain one local Python application. Extract stable mechanics and explicit
interfaces while keeping Draft, Trade and Waiver decision policies separate.
Keep useful existing names (`core`, `inseason`, `providers`) instead of renaming
everything to fit a new architectural vocabulary.

The source audit found 94 Python files and about 50,400 physical lines, including
comments and blanks. Draft simulation and the CLI concentrate thousands of
lines; Draft has its own player and lineup implementation. Waiver input
preparation calls Trade's board workflow; shared run validation constructs a
Sleeper client. Scoring completeness varies by caller. Provider budget writes
are atomic, but reservation read/modify/write sequences are not coordinated
across processes. These are extraction targets, not proof of every live-path
failure. The inspected baseline passed 802 tests and configured Ruff checks;
MA-001 must record the exact current commit and fresh validation results.

## 2. Boundaries and allowed dependencies

```text
cli.py / presentation/ --------> application/ (composition and run lifecycle)
                                      |                 |
                              draft/ trade/ waiver/   providers/ storage/
                                      |                 |
                                  inseason/             |
                                      +------> core/ <--+
```

Arrows mean permitted dependency direction, not that every component imports
every downstream package. Composition constructs concrete clients and stores;
calculations receive normalized inputs and explicit policies.

| Package | Owns | Allowed internal dependencies |
| --- | --- | --- |
| `core` | Immutable identities/rules, scoring coverage, eligibility/capacity mechanics, provenance, interface contracts | Standard library only |
| `inseason` | Reusable weekly matrices, parameterized rank/value transformations, lineup/depth/replacement deltas and risk calculations | `core` |
| `draft` | Draft context, board policy, acquisition timing, simulations, strategy experiments, watcher state machine | `core`; neutral formulas only when contracts agree |
| `trade` | Expert selection policy, horizon/valuation choices, supported assets, partner/fairness and package search | `core`, `inseason` |
| `waiver` | Expert selection policy, acquisition/drop legality, candidate/retention rules and conditional plans | `core`, `inseason` |
| `providers` | Read-only clients, external payload normalization, declared schema capabilities | `core`, `storage` |
| `storage` | Raw/derived cache persistence, process-safe quota/pacing coordination, manifests and migrations | `core` |
| `application` | Config resolution, composition, shared preparation, feature run services, final revalidation | All calculation and infrastructure packages; never presentation |
| `presentation` | Feature-specific human/JSON/CSV renderers and terminal helpers | Typed result models; no provider access or evaluation |
| `cli.py` | Compatibility entry point, argument routing, status/exit mapping | `application`, `presentation` |

No feature imports another feature. Infrastructure must not choose recommendation
policy. `core` and `inseason` must not import clients, filesystem storage, feature
policy or CLI. Draft watcher polling is an application effect; its state
transitions and recommendation logic stay in Draft.

During migration, a checked-in allowlist identifies each existing forbidden
import, its owning issue and removal milestone. No new forbidden edge is allowed.
Compatibility modules delegate in one direction and do not form import cycles.
Direct/lazy imports both belong in the boundary check. The final gate removes
temporary edges, not merely moves them to another top-level file.

## 3. Data and service contracts

Use frozen/slotted records at calculation boundaries. Provider JSON and flexible
dictionaries belong at external/serialization edges. Schema versions apply to
persisted records; type hints alone are not runtime validation.

| Contract | Required content / responsibility |
| --- | --- |
| `LeagueRules` | League and season identity, team count, slot definitions/eligibility, bench and reserve capacity, explicit relevant scoring/transaction/calendar rules, preserved unclassified platform settings |
| `RosterState` | Canonical membership in active/reserve/taxi, starters, owner, observation stamp; preserve unsupported membership for diagnostics |
| `Player` and feature views | One canonical identity and eligible-position set; Draft ADP/board rank and in-season value belong in feature/context records referencing that identity |
| `CapabilityAssessment` | Feature/operation, profile/version, supported/limited/unsupported rules, evidence and reasons; independent of readiness and calibration |
| `StatEvidence` / `ScoredProjection` | Raw observed stats, explicit zero/missing distinction, source schema and horizon, applied scoring hash, used/missing/unsupported categories and points completeness |
| `RankEvidence` | Provider-declared horizon/format, expert/contributor identity, actual observation/update times and authority limitations |
| `LeagueSnapshot` | One normalized as-of league/ownership/player/schedule view with source stamps; feature views add acquisition or trade context without refetching independent contradictory base state |
| `PreparedEvidence` | Immutable snapshot, horizon-scoped datasets, source coverage and call/write outcomes; no recommended move or implicitly selected feature policy |
| `RunContext` / feature results | Explicit as-of time, seed, approved/provisional policy identity, typed result/readiness/search coverage; publication verification is a separate wall-clock step |

Public interface names are design targets; MA-001 inventories actual serialized
names before implementation freezes them. Do not create a universal feature
result with dozens of irrelevant optional fields. Reuse small factual records
and keep the three feature result models separate.

### 3.1 Rule and scoring pipeline

1. Provider adapters validate external shapes and preserve unfamiliar fields.
2. Normalize relevant league facts and membership without inferring defaults.
3. Assess the requested operation's supported rules before expensive analysis.
4. Resolve required raw statistics by position, active scoring category and
   provider schema. Distinguish absent/inapplicable/documented-zero values.
5. Score only with explicit coverage. Return partial diagnostic points when
   useful, but never label them complete or pass them into a complete valuation.
6. Apply feature-specific readiness/degraded-mode rules to each candidate's
   actual dependencies and retain every reason. Partial source coverage alone
   is not a whole-roster veto: preserve independent comparisons, label conditional
   conclusions and block only unsupported candidates/claims (MR-02 section 3.1).

Place stat aliases and conversion facts in the provider schema layer where
provider-specific; use canonical statistic names in scoring. Unknown categories
and nonfinite inputs fail visibly. Standard/HALF/PPR request selection must not
overwrite provider-declared projection scope. Valid raw-stat rescoring remains
possible under the existing approved contract.

### 3.2 Lineup, capacity and policy

Share slot eligibility and roster-capacity mechanics. Make lineup objectives
explicit: maximize points with legal empty slots versus prioritize filled slots,
required occupied slots, replacement limits and deterministic tie rules. Draft
and in-season implementations currently need semantic comparison; replacing one
with the other is not automatically behavior-preserving.

Draft position caps are acquisition preferences unless actual league rules say
otherwise. Separate them from legal eligibility. Preserve their current effect
during extraction; change them in a behavior PR with before/after evidence.
Replacement calculations receive actual league supply, ownership and intended
horizon. A shared formula must not select a league's calibration or weights.

### 3.3 Shared preparation without shared policy

`application` exposes preparation requests that name league, season, operation,
evidence horizon, coverage universe, offline/refresh mode and required datasets.
Feature policy provides expert-panel selection and valuation choices explicitly.
The preparation service orchestrates provider calls and returns factual inputs;
neutral rank-slot/value transforms live in `inseason`. Trade's partner model and
Waiver's acquisition/retention rules never enter that service.

Raw provider evidence may be shared by its full request scope. Scored projections,
derived boards, policy state and results are keyed by league, season, rules,
policy and source hashes as applicable. Reuse one normalized run snapshot or
prove equality of every relevant shared fact; comparing season/scoring alone is
not enough. No mandatory extra manual refresh step is added to normal commands.

### 3.4 Effects, budgets and clocks

Use injected ports for provider retrieval, evidence stores and clocks. Keep
concrete defaults in application composition, not in pure evaluators. The
existing as-of scope can remain a compatibility adapter during extraction.

Use a small standard-library cross-process lock abstraction around a shared
provider-account quota ledger and pacing state. POSIX and Windows backends must
release locks on process exit and have bounded acquisition waits. Avoid stale
PID-file guesses or per-league quota ledgers. Reserve durably before issuing
requests; count retry attempts according to the provider contract; ambiguous
interruption remains conservatively charged. Coordinate request spacing across
commands and retain actual retrieval timestamps. Do not introduce SQLite or a
server to solve this bounded local coordination problem.

Keep source freshness policies explicit and feature-owned where they differ.
This plan does not replace recently tightened freshness gates with older design
defaults. Publication revalidation remains a fresh observation, not a guarantee
of atomic state through the moment a user acts.

## 4. Current-to-target extraction map

Targets are responsibility groups; detailed file splits follow cohesive APIs,
not arbitrary line-count limits.

| Current implementation | Target ownership | Preservation / migration constraint |
| --- | --- | --- |
| `core/models.py`, identity/scoring/lineup/replacement | `core` | Extend contracts through compatibility adapters; prove lineup objective/tie semantics |
| `core/run_contract.py` | Pure provenance/time contracts in `core`; revalidation/run lifecycle in `application`; I/O in `storage` | Preserve hashes, as-of semantics and exact-build replay checks |
| Top-level `sleeper.py`, `fantasypros.py`; existing provider adapters | Network/normalization in `providers`; config resolution in `application` | Preserve injectable transport and command compatibility; remove mixed config/client ownership incrementally |
| `providers/cache.py`; budget copies in board/expert/waiver services | `storage` and shared preparation | Preserve atomic writes and raw evidence; add process-safe reservations separately |
| `trade/board_service.py`, neutral portions of `trade/boards.py`, schedule loading | Retrieval in `application`; neutral transforms in `inseason`; provider facts in `providers` | Trade retains expert/horizon choices; Waiver supplies its own policies; no copy of Trade workflow |
| `waiver_inputs.py`, `season_prepare.py`, feature `service.py` files | `application` preparation and feature run services | Keep existing automatic-preparation/output contracts; split rendering separately |
| `simulation.py`, `assistant.py`, `draft_analysis.py`, draft preferences, watcher/mocks | `draft` context, policy, simulation, analysis and watcher modules; effects in `application` | Pin decisions first; segregate experiments; no live-policy promotion or live 2026 reopening |
| `rankings.py`, `league_boards.py`, `grouped_rankings.py`, expert inputs | Classify each responsibility: provider facts, neutral math, or Draft policy | Do not move the whole ranking stack into shared core; preserve authority/order |
| `inseason/evaluation.py` | `inseason` | Keep feature-neutral inputs; split coherent calculations when necessary |
| Trade and Waiver evaluation/search | Respective features | Separate validation, candidate generation, exact evaluation and decision gates without merging policy |
| `cli.py`, reporting/terminal helpers and service formatters | Thin `cli.py`, `presentation`, application command adapters | Preserve CLI spelling, output channels, schemas and exit behavior |
| Specialist preferences and season-specific tables | Feature policy/config and provider schedule evidence | Keep league-local choices; no static historical season becomes a new default |

## 5. Compatibility, replay and rollback

Keep command entry points and temporary import shims while internals move.
Inventory public machine schemas and artifact readers before removing shims.
Use explicit schema versions and tested converters only when conversion preserves
meaning; otherwise reject an old artifact with a precise recovery instruction.
Never migrate private policy automatically into a new calibration claim.

The current manifest hashes source files. A refactor changes that hash even if
decisions do not change. Preserve old commit/package references and private
evidence locally for exact-build replay. For migration comparisons, run old and
new builds separately against equivalent synthetic inputs and compare declared
decision fields, reasons, numerical outputs and coverage. Do not disable hash
checks or blanket-ignore provenance differences to make tests pass.

Small PRs provide rollback points. Avoid destructive cache/schema rewrites;
write new derived artifact versions alongside old ones when formats change.
Rollback to a known build restores its matching reader and evidence. A critical
confirmed correctness fix is not rolled back merely to preserve a faulty golden
result; isolate the regression and document the decision.

## 6. Verification design

- Characterization cases pin established feature behavior; independent arithmetic
  and exhaustive small-case oracles establish correctness, rather than assuming
  the old result is correct.
- Property/invariant checks cover unique assignment, legal slots, deterministic
  ties, unchanged identities, scoring linearity where applicable, and isolation.
- Golden end-to-end cases use synthetic provider responses and exercise ordinary
  CLI preparation, evaluation, rendering, persistence and offline replay.
- Import checks prevent forbidden dependency growth. Gradual type checks begin
  at changed core/preparation boundaries with a pinned development-only tool;
  no runtime framework or repository-wide annotation rewrite is required.
- Fault cases include missing raw stats, unsupported categories, partial ranks,
  stale cache hits, changed ownership, timezone/season changes, quota contention,
  interrupted writes and unsupported roster mechanisms.
- Performance measurements use fixed inputs/seeds, the same recorded machine,
  repeated runs, bounded searches and memory observations. Reporting faster
  incomplete search is not a valid optimization proof.

The migration plan owns milestone-specific gates and support promotion. Passing
tests does not prove that a league's empirical thresholds are calibrated.
