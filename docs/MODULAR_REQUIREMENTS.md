# Modular RosterTheory: supported scope and requirements

Status: Approved planning baseline; implementation requires a separate active milestone

Date: September 25, 2026 (America/Los_Angeles)

Companions: [architecture](MODULAR_ARCHITECTURE.md), [migration plan](MODULAR_MIGRATION_PLAN.md)

## 1. Purpose and authority

Make the existing local, read-only Draft, Trade, and Waiver application easier to
maintain and dependable for a bounded family of Sleeper redraft leagues. Preserve
tested behavior and evidence safeguards while replacing inconsistent contracts
and duplicated mechanics incrementally. This is not a rewrite or a universal
fantasy-platform project.

The user approved this planning package and proceeding to the MA-001 baseline.
Detailed implementation remains bounded by the selected milestone contract.
Neither document approval, issue creation, nor merging a planning PR activates
product implementation. Only a separately authorized entry in
[ACTIVE_MILESTONE.md](../.codex/context/ACTIVE_MILESTONE.md) does that.

This document owns the proposed support envelope and cross-feature acceptance
requirements. Existing feature specifications continue to own decision policy.
Section 6 identifies precise reconciliations; it does not reopen completed work
or transfer calibration. No existing command is disabled by this planning PR.

## 2. Supported envelope and rollout

### 2.1 Target configuration family

| Dimension | Target | Excluded from this program |
| --- | --- | --- |
| Platform | Sleeper NFL | NFL.com or other platform integrations |
| Season model | Annual redraft; head-to-head points | Dynasty, keepers, best ball, salary contracts |
| League size | 10 or 12 teams | Other sizes until separately scoped |
| Fixed starters | 1 QB, 2 RB, 2 WR, 1 TE, 1 K, 1 DST | Two-QB, IDP, additional fixed starters |
| Flex layout | One RB/WR; one RB/WR/TE; or two RB/WR/TE | Superflex, other flex layouts |
| Bench | 5 or 6 active bench places | Deeper benches until separately scoped |
| Reception points | 0.5 first; 0 and 1 in the final expansion milestone | Other reception values and position premiums |
| Other scoring | Explicit, versioned supported-setting inventory, starting with both reference profiles | Unverified categories and arbitrary bonus schemes |
| Draft | Ordinary snake order; every slot | Auction, third-round reversal, keepers, traded-pick ordering |
| Transactions and reserves | Exact supported waiver, game-lock, reserve eligibility/capacity, and schedule settings inventoried for the two reference profiles | Taxi squads and unverified transaction/reserve modes |

Read actual settings; do not infer them from a league name, platform-default
label, or reception multiplier. Preserve unknown settings for diagnostics. A
setting may be explicitly irrelevant to an operation, but must not disappear
without classification. The application must not invent an IR count, waiver
mechanism, scoring map, or playoff calendar to complete a profile.

The roster family is a target, not a statement that every combination already
works. The 12 half-PPR base combinations are 2 team counts x 3 flex layouts x 2
bench sizes. Waiver/reserve/scoring variants are additional documented axes,
not implicitly covered by those 12 cases.

### 2.2 Reference profiles and evidence gate

Use public, synthetic profile identifiers:

| Profile | Known intended shape | Required baseline inventory |
| --- | --- | --- |
| `reference_a` | 10 teams; half PPR; one RB/WR flex; K and DST | Exact full roster, bench, scoring, waiver, reserve, lock and playoff settings |
| `reference_b` | 12 teams; half PPR; two RB/WR/TE flexes; five bench; K and DST | Exact full scoring, waiver, reserve, lock and playoff settings |

These profiles represent the user's two existing leagues without publishing
their names, IDs, owners, responses, or personal history. Public fixtures use
invented identities and synthetic player evidence. An authorized implementation
task must inventory current settings, preserve local provenance, and record the
redacted rule maps and source-observation date before declaring either profile
verified. The conversation and old status notes are not current provider facts.

MA-001's [baseline record](MODULAR_BASELINE.md) now contains the observed maps
and dates. Provider-stat coverage and operation-specific capability remain
separate evidence gates; observing a rule does not prove support for it.

If actual settings fall outside section 2.1, report the discrepancy and resolve
the scope before claiming support. Do not modify the user's league or silently
approximate its rules. Missing settings are an evidence task, not a reason to
ask the user to guess platform behavior during design.

### 2.3 Stages and feature limits

1. Validate both exact reference profiles in half PPR across all three features.
2. Validate the 12 half-PPR base combinations with supported ancillary rules.
3. Validate standard and PPR using the same engine and corresponding evidence.

Existing standard/PPR parsing and tests remain in place throughout; staged
validation does not authorize removing functionality. New support restrictions
require explicit compatibility review and a versioned behavior-change PR.

| Feature | Initial claim | Important boundary |
| --- | --- | --- |
| Draft | Boards, strategy comparison and read-only recommendation/watch behavior for the supported snake roster | K/DST treatment and timing remain explicit feature policy; no new live 2026 operation or experimental-policy promotion |
| Trade | Diagnose, target/search, compare and evaluate supported QB/RB/WR/TE player packages | K/DST membership and roster capacity are preserved; K/DST assets, draft picks and FAAB trading are not promoted by this work; unchanged specialist contributions must be explicitly bounded in comparisons |
| Waiver | Evaluate/search supported skill players and existing K/DST paths; preserve conditional claim-plan behavior | No automatic bid optimization or claim-success probability; mechanism and reserve evidence must meet the operation's contract |

Do not turn this program into new specialist Trade policy. If a Trade operation
requires a specialist valuation it cannot support, return the affected limitation
or unavailable result rather than implying a complete valuation of every slot.

## 3. Requirements and acceptance contracts

| ID | Requirement | Observable acceptance |
| --- | --- | --- |
| MR-01 | Determine support from normalized actual rules, per feature and operation | Every setting is supported, explicitly irrelevant, unknown, or unsupported; rejected fixtures list affected rules before decision evaluation |
| MR-02 | Separate format support, decision-specific data readiness and policy validation | A supported half-PPR fixture with stale ranks remains stale; a supported profile with unvalidated thresholds remains uncalibrated; irrelevant missing players do not veto independent decisions; no state inherits another league's readiness |
| MR-03 | Preserve canonical identities and roster membership | Active, starter and reserve sets reconcile; duplicate ownership and ambiguous identities are reported; taxi state is preserved and rejected as unsupported rather than counted as active bench |
| MR-04 | Score from actual league rules with explicit stat coverage | Required missing statistics, invalid/nonfinite values and unsupported settings cannot yield a complete score; provider-documented structural zero is distinguishable from missing data |
| MR-05 | Share legal mechanics, retain feature objectives | Eligibility, capacity and scoring agree on common fixtures; acquisition preferences are not platform limits; different lineup fill/empty-slot objectives and tie rules are declared and tested |
| MR-06 | Keep authoritative rank scope and projection scope separate | No preseason rank is presented as current weekly/ROS authority; rescored projections do not create custom expert rankings; declared provider scope remains visible |
| MR-07 | Keep decision policy within its feature and league | Trade partner/fairness logic cannot enter Waiver; Draft timing cannot enter in-season ownership value; shared formulas receive explicit parameters without selecting feature policy |
| MR-08 | Make ordinary preparation reusable and read-only | Existing automatic preparation, dry-run/offline semantics, bounded calls, raw-cache reuse and per-league derived artifacts remain covered by runtime-input tests |
| MR-09 | Preserve provenance and publication safety | Original source times, missing coverage, snapshot changes, kickoff boundaries and replay hashes remain visible; replay never implies current actionability |
| MR-10 | Preserve external contracts or version intentional changes | Existing command names, exit codes and JSON behavior pass compatibility fixtures; saved schema changes have a documented reader/migration/rejection strategy |
| MR-11 | Coordinate provider budgets across commands | Simultaneous processes cannot double-reserve the same remaining quota; pacing/retry accounting and interrupted reservations have tested conservative behavior |
| MR-12 | Enforce module boundaries and testable calculation contracts | Dependency checks prevent new forbidden imports; selected shared contracts pass type checks; deterministic calculations run with no filesystem, network or wall-clock dependency |
| MR-13 | Validate correctness and bounded performance across scope | Format matrix, independent calculation oracles, search completeness/budget disclosure and measured runtime/memory gates pass before support is advertised |
| MR-14 | Preserve privacy and read-only operation | Synthetic public evidence only; no credential exposure or Sleeper mutation; repository/index privacy gates and public output tests pass |

Support assessment is factual: `SUPPORTED`, `LIMITED`, or `UNSUPPORTED`, with
reasons and operation scope. It is independent of data readiness, search
completeness, candidate confidence, informational warnings and policy validation.
These are proposed internal fields, not permission to replace existing CLI
statuses. Numerical readiness and recommendation quality are separate claims.

### 3.1 Missing evidence must have decision-specific consequences

User clarification, September 26: a player who does not materially affect a
trade or waiver decision must not disable that decision or the whole tool.
Scoring completeness (MR-04) describes evidence; it is not a roster-wide veto.

For each candidate move, preserve three distinct outcomes:

- **Independent:** the missing evidence cannot change the supported conclusion
  within the declared horizon and dependencies. Continue the comparison and
  disclose the excluded evidence. Do not claim complete whole-roster forecasts.
- **Conditional:** the influence cannot yet be established. Retain useful
  comparisons with explicit assumptions and affected metrics; do not present an
  unconditional recommendation, exact win odds or a proved best option.
- **Blocked candidate:** missing evidence is required to value the actual
  acquired/traded/dropped asset, establish legality, or support the conclusion.
  Block that candidate or claim while retaining independently supported options.

An unknown player stays on the roster, consumes the correct capacity and remains
protected from automatic trade/drop selection. Missing ranks never imply zero
value. Being unchanged on a bench, absent from rankings, low-ranked or currently
injured does not by itself prove irrelevance over future weeks.

Relevance must consider lineup eligibility and shared FLEX slots, bye/return
weeks, depth/replacement effects, secondary add/drop moves and the quantities
actually being reported. Feature policy owns these dependencies. Use proved
independence or documented evidence bounds; do not invent projections, a rank
cutoff or a universal materiality threshold. If independence is unresolved, use
the conditional outcome rather than silently discarding the player.

Acceptance examples for the next implementation slice:

1. Adding an unrelated missing-evidence player preserves an independently
   supported comparison and its conclusion, with a visible exclusion.
2. That player cannot become a free roster slot, cheap trade asset or drop target.
3. If the same player becomes relevant through FLEX eligibility, a bye, a return
   week or a secondary move, the affected candidate becomes conditional/blocked.
4. A gap on one opponent's roster cannot suppress independent opponents.
5. Material missing asset data still prevents an unconditional recommendation;
   missing league-wide scoring terms need their own relevance/bounds evidence.
6. All claims distinguish partial source coverage from candidate readiness and
   search completeness, including saved results and user-facing explanations.

These are acceptance requirements, not claims that the current runtime already
satisfies them. Existing broad Trade roster exclusions and Waiver skill-position
grouping require review before promoting stricter scoring gates.

## 4. Scoring and recommendation limits

The first scoring inventory must enumerate every nonzero setting in the exact
reference profiles, its applicable positions, required provider fields,
calculation semantics and missing-data behavior. Reception scoring alone is
insufficient. Kicking and team-defense categories need the same scrutiny as
offense. No observed absence may become zero without a provider-schema rule.

Linear categories can use expected raw statistics. Threshold or event bonuses
need the corresponding projected event/distribution evidence; applying a
threshold to an average yardage projection is not an acceptable substitute.
Unsupported categories stay unavailable until a separately scoped capability
has adequate evidence and tests.

Expert rankings remain authoritative only for their declared horizon and
format. A baseline ranking format can be retained with truthful limitations
where existing policy permits it. No engine test establishes predictive quality,
cross-league calibration, or trade acceptance probability. Existing provisional
policy labels and promotion gates remain in force.

## 5. Compatibility and safety invariants

- Keep the local Python 3.11+ application and standard-library runtime. No new
  hosting, accounts, database, framework, or background service is in scope.
- Preserve the [CLI contract](CLI_OUTPUT_CONTRACT.md) and
  [runtime-input contract](RUNTIME_INPUT_CONTRACT.md); explain/version any
  approved behavior change instead of silently changing outputs.
- Use the current league season and source schedule. Remove hard-coded season
  defaults only through a separately tested behavior change.
- The 2026 Draft closure and offline-only experimental rollout remain closed.
- No feature may make a Sleeper pick, trade, claim or lineup change.
- Preserve exact-build replay integrity. Moving files changes build identity;
  compare semantic outputs separately and retain old-build replay capability.
- A refactor preserves established semantics. A verified bug fix has its own
  expected-result change and evidence; faulty output is not a golden truth.

## 6. Reconciliation with existing specifications

This approved package governs only the shared redesign and its validation
envelope. Existing product policy and completed reliability protections remain
authoritative. A conflict not listed here must be resolved in the relevant issue
before implementation; broad wording here does not override a stronger gate.

| Existing source / selected sections | Relationship to this proposal |
| --- | --- |
| [Trade requirements](TRADE_ASSISTANT_REQUIREMENTS.md), 2, 6.3, 8.4, 10-13 | Preserve read-only separation, actual scoring, player-asset limits and policy. Shared reuse now includes a bounded format envelope; supersede the implication in section 10 that Waiver may import Trade-owned policy to reuse items 1-7. Historical single-league acceptance is necessary history, not new multi-format proof. |
| [Trade design](TRADE_ASSISTANT_DESIGN.md), 2-5, 15-16 | Preserve normalized records and empirical gates. Replace the shared ownership/layout targets with the companion architecture when approved; keep Trade-only algorithms and choices. Old extraction timing around a completed draft does not authorize current Draft work. |
| [Waiver requirements](WAIVER_ASSISTANT_REQUIREMENTS.md), 2, 4, 7-8 | Preserve ownership, capacity, evidence and league isolation. Initial skill-only/single-claim scope describes the first slice; current K/DST and claim-plan paths remain subject to their existing gates, as recorded in current Waiver status. New matrix validation does not invent replacement thresholds. |
| [Waiver design](WAIVER_ASSISTANT_DESIGN.md), Architecture, Fail-closed boundaries, Current extraction seams | Fulfill the temporary Trade-import boundary through neutral preparation. Preserve acquisition/drop rules and all current safety gates. |
| [Draft durable context](../.codex/context/PROJECT_CONTEXT.md), Draft ranking/decision model; [Draft status](../.codex/context/status/DRAFT.md) | Preserve authoritative expert ordering, acquisition policy and closed operations. Package extraction is separately scoped; hard-coded cap/season corrections need behavior issues. No historical calibration is universalized. |
| [Runtime input contract](RUNTIME_INPUT_CONTRACT.md), Ordinary-use rule, Authority classes, Two-league isolation; [CLI contract](CLI_OUTPUT_CONTRACT.md) | Retain authority separation, automatic preparation, per-league derivation, offline behavior, channels and exit codes. |
| Current [Trade](../.codex/context/status/TRADE.md) and [Waiver](../.codex/context/status/WAIVER.md) status | Preserve current exact gates, ranking caps, freshness/readiness and replay contracts; earlier prose does not revert subsequent safeguards. Completed records need not be preloaded for this plan. |

## 7. Decisions and unresolved evidence

Planning defaults: incremental modular monolith; exact-profile half-PPR first;
standard/PPR later; Trade assets remain QB/RB/WR/TE; no new live Draft work;
synthetic fixtures; existing policy and safety gates retained. No additional
user choice is necessary to draft or review this package.

Before baseline acceptance, establish the exact ancillary rules and scoring maps,
available projection schemas, support/limitation list per command, and measured
performance baseline. These are evidence deliverables in MA-001, not assumed
facts or hidden implementation discretion. Ask the user only if verified facts
require expanding the agreed scope or changing recommendation policy, public
compatibility, dependencies, or operational behavior.
