# RosterTheory Trade Assistant task list

Status: Phase 10 complete; no open Trade development task
Created: September 4, 2026 (America/Los_Angeles)  
Requirements: `docs/TRADE_ASSISTANT_REQUIREMENTS.md`  
Design: `docs/TRADE_ASSISTANT_DESIGN.md`

This is the Trade Assistant delivery backlog, not an implementation contract.
The user activated Trade implementation on September 4; only the phase named
in `.codex/context/ACTIVE_MILESTONE.md` authorizes work. No task ever authorizes a Sleeper
transaction.

## Loading and maintenance rules

- For backlog review or prioritization, load this file only after the two short
  routing files.
- For implementation, load the active milestone, the selected task row,
  and only the requirements/design sections named in its `Context` column.
- Load either full planning document only when changing its cross-cutting
  policy or architecture.
- Implement one numbered phase as one named milestone and stop at its gate.
- Change a task status only with its exit evidence. Keep detailed investigation
  narrative in the active milestone or a dated study, not in this list.
- Preserve task IDs. Add newly discovered work under the appropriate gate
  rather than silently expanding an existing task.

Status values are `PLANNED`, `ACTIVE`, `BLOCKED`, `DONE`, or `DEFERRED`.
Priorities are `P0` (required foundation), `P1` (MVP), and `P2` (post-MVP).
`R§` references requirements sections; `D§` references design sections.

## Delivery sequence

| Phase | Milestone outcome | Opens only when |
| --- | --- | --- |
| 0 | Trade work is explicitly activated without disrupting Draft | League Beta milestone is handed off and user approves |
| 1 | Live data capabilities are proven or explicitly degraded | Phase 0 gate passes |
| 2 | Feature-neutral core contracts are tested | Phase 1 gate passes |
| 3 | One immutable, complete trade snapshot can be built | Phase 2 gate passes |
| 4 | Selected and market ROS value boards are auditable | Phase 3 gate passes |
| 5 | Entered packages are evaluated correctly without final risk labels | Phase 4R gate passes and user approves |
| 5E | Common larger entered packages are evaluated correctly | Phase 5 gate passes and user approves |
| 6 | Risk, diagnosis, and final decision gates are validated | Phase 5E gate passes |
| 7 | League-wide opportunity search is safe and deterministic | Phase 6 gate passes |
| 8 | The read-only MVP is recommendation-ready | Phase 7 gate passes |
| 9 | League Beta's 12-team, two-FLEX format is supported and optimized | TA-801 passes and the user approves prioritizing League Beta |
| 10 | Trade reports survive legitimate ranking exclusions and automatic targets respect roster-context utility | User approves the September 18 correctness milestone |

## Phase 0 — Activation and baseline

Football consequence: protect the proven League Beta workflow while establishing a
separate in-season decision track.

| ID | P | Status | Work and deliverable | Depends | Context | Exit evidence |
| --- | --- | --- | --- | --- | --- | --- |
| TA-001 | P0 | DONE | Complete or formally hand off the active Draft milestone; record remaining Draft work without mixing it into Trade. | — | R§2.1; D§2-3 | The private Draft record separates the operational checkpoint from completed development. |
| TA-002 | P0 | DONE | Obtain user approval to activate the first Trade implementation milestone and replace, rather than coexist with, the Draft contract. | TA-001 | R§2.1; D§16 | User approved activation September 4; `ACTIVE_MILESTONE.md` names bounded Phase 1 and its gate. |
| TA-003 | P0 | DONE | Record a clean implementation baseline: repository status, 175+ passing tests, current module dependency map, and known personal/ignored artifacts. | TA-002 | R§2.2, §11; D§2-3, §15 | `COMPLETED_TRADE_ASSISTANT_PHASE_0.md` records status/dependencies; 175 tests pass in 3.594s. |
| TA-004 | P0 | DONE | Define trade-scoped configuration, cache, export, fixture, and test namespaces; verify existing ignore rules cover personal artifacts. | TA-003 | R§2.1, §10-11; D§3, §13 | The Phase 0 record defines eight non-colliding namespaces; existing ignore rules cover personal data. |

### Phase 0 gate

One Trade milestone is active, the Draft handoff is safe, the baseline suite
passes, and filesystem boundaries are approved. Otherwise stop.

## Phase 1 — Provider and data feasibility

Football consequence: prove that current ownership, ROS opinion, weekly value,
schedule, and availability can be sourced before building a trade model around
assumed fields.

| ID | P | Status | Work and deliverable | Depends | Context | Exit evidence |
| --- | --- | --- | --- | --- | --- | --- |
| TA-101 | P0 | DONE | Add a schema-only Sleeper probe for NFL state, league, users, rosters, required matchup weeks, transactions, brackets, player directory, and optional trends. Use GET only. | Phase 0 | R§4.1-4.2; D§5.1-5.2 | Live schema/count report covers all named GET endpoints and saves no raw rows; adapter has no write surface. |
| TA-102 | P0 | DONE | Audit a fresh League Alpha snapshot for roster limits, reserves/IR, trade deadline, playoff weeks, future matchup availability, and current user resolution. | TA-101 | R§3.1, §4.2, §6.1; D§5.2, §6 | September 4 audit resolves the user once, all 150 owned players uniquely, Weeks 1–17 matchups, and the Week 15–17 playoff horizon; raw deadline semantics remain labeled. |
| TA-103 | P0 | DONE | Run a budgeted authenticated FantasyPros schema probe for ROS ECR, individual ROS ranks, experts, ROS/weekly projections, injuries, news, player points, and external IDs. Store only parameters, shapes, counts, timestamps, and coverage. | Phase 0 | R§4.3, §5; D§5.3 | Ten-call reproducible report plus 31-call total exploration records exact capabilities/fallbacks without exposing the key or licensed rows. |
| TA-104 | P0 | DONE | Resolve the authoritative source for NFL schedule/byes and fantasy playoff horizon. Prefer Sleeper; document a small audited local schedule input only if neither provider is sufficient. | TA-102, TA-103 | R§4.1, §6.1; D§5.2-5.3, §16 | Sleeper defines the fantasy horizon; audited official-NFL local schedule config is required for games/byes and cross-checked against provider fields. |
| TA-105 | P0 | DONE | Determine available multi-year in-season accuracy leaderboards, field sizes, current selectable experts, update timestamps, and personal-license access. Do not reuse Draft accuracy files as authority. | TA-103 | R§5; D§7.1, §16 | Coverage report confirms 2021–2025 weekly in-season accuracy and 29 selectable experts; the user selected it as authority because FP does not provide ROS expert-accuracy rankings. |
| TA-106 | P0 | DONE | Publish the provider capability matrix, call plan, cache/freshness policy, degraded modes, and go/no-go recommendation for the intended MVP. | TA-101–TA-105 | R§4.4, §11; D§5.4, §14 | `TRADE_ASSISTANT_PROVIDER_FEASIBILITY_2026.md` records sources, calls, freshness, modes, and a no-go pending user fallback approval. |

### Phase 1 gate

Fresh Sleeper ownership is complete. On September 4 the user approved weekly
in-season accuracy for expert selection and `WEEKLY-PROXY` rankings/projections
until ROS publishes. Phase 2 is open. Do not quietly substitute preseason
ranks, undocumented Sleeper projections, or scraping.

## Phase 2 — Shared core foundations

Football consequence: create reusable scoring and lineup machinery without
letting Draft timing concepts contaminate current-roster value.

| ID | P | Status | Work and deliverable | Depends | Context | Exit evidence |
| --- | --- | --- | --- | --- | --- | --- |
| TA-201 | P0 | DONE | Add the minimal `core`, `providers`, and `trade` packages plus provider protocols and typed domain errors. Keep top-level Draft modules as compatibility surfaces. | Phase 1 | R§2.2, §10; D§2-3, §5.1, §14 | Minimal packages, six small read-only protocols, typed errors, and AST import-boundary tests exist. |
| TA-202 | P0 | DONE | Implement frozen core entities, `DataStamp`, canonical JSON serialization, stable hashes, and `AnalysisManifest`. | TA-201 | R§4.1, §11; D§4.1-4.2 | Frozen entities and deterministic manifest tests reproduce identical hashes/IDs and reject non-finite JSON. |
| TA-203 | P0 | DONE | Implement provider cache keys, atomic file writes, freshness checks, request deduplication, and FantasyPros daily-budget accounting. | TA-201, TA-202 | R§4, §11; D§5.4, §13 | Tests cover normalized keys, duplicate calls, atomic cleanup, fresh/stale data, budget exhaustion, and daily rollover. |
| TA-204 | P0 | DONE | Implement canonical player identity reconciliation using provider IDs first, then explicit auditable aliases; prohibit silent fuzzy matches. | TA-202 | R§2.2, §4.4; D§4.2, §6 | Fixtures cover exact IDs, shared external IDs, explicit aliases, unmatched rows, ambiguity, and duplicate claims; names are never fuzzy-matched. |
| TA-205 | P0 | DONE | Extract or wrap feature-neutral Sleeper scoring into `core.scoring`, preserving raw stats and unsupported-category reporting. | TA-201 | R§2.2, §6.3; D§3, §8.2 | Draft's compatibility function now delegates to shared scoring; raw stats and unsupported settings remain auditable. |
| TA-206 | P0 | DONE | Extract the deterministic legal-lineup optimizer into `core.lineup`, with dedicated, FLEX, WR/RB, receiver, and superflex assignments and stable ties. | TA-201 | R§6.5; D§8.1 | Dedicated/flex/superflex/DEF fixtures pass and multiple small lineups match an independent brute-force solver. |
| TA-207 | P0 | DONE | Implement current free-agent universe and common positional waiver-baseline contracts independently of ADP. | TA-204–TA-206 | R§6.5-6.6; D§3, §7.3, §8 | Controlled ownership fixture selects only unowned players, retains replacement identity, and uses current points with no ADP input. |
| TA-208 | P0 | DONE | Run the full Draft regression suite and dependency audit after shared extraction; remove no Draft code merely for tidiness. | TA-201–TA-207 | R§2.1, §13; D§2-3, §15 | All 192 tests pass; AST audit finds no feature-policy import in `core` or `providers`; Draft surfaces remain intact. |

### Phase 2 gate

Core scoring, identity, lineup, provenance, cache, and replacement contracts are
feature-neutral and tested. The Phase 2 gate passes with 192 tests; Phase 3 is
ready for a separately named milestone.

## Phase 3 — Immutable Trade snapshot

Football consequence: ensure every recommendation evaluates one coherent view
of the league rather than mixing rosters, ranks, and injuries captured at
different times.

| ID | P | Status | Work and deliverable | Depends | Context | Exit evidence |
| --- | --- | --- | --- | --- | --- | --- |
| TA-301 | P0 | DONE | Extend the Sleeper adapter with normalized NFL state, league, users, rosters, matchups, transactions, brackets, and once-daily player directory retrieval. | Phase 2, TA-101 | R§4.2; D§5.1-5.2 | Valid/malformed fixtures pass; live refresh normalizes all required GET data and the second run reuses the fresh daily player cache. |
| TA-302 | P0 | DONE | Extend the FantasyPros adapter only for capabilities proven by TA-103, with normalized market ranks, expert ranks, projections, availability, and player points. | Phase 2, TA-103 | R§4.3-4.4; D§5.1, §5.3 | Contract fixtures preserve timestamps, active horizon, scoring, contributors, raw stats, identities, news, and player points; Draft fallback raises a typed stop. |
| TA-303 | P0 | DONE | Build the preflight call planner and retrieval coordinator using fresh-cache hits and optional/required call classification. | TA-203, TA-301, TA-302 | R§4.3, §11; D§5.4 | Tests cover deduplication, required/optional calls, cache hits, paid-budget reservation, and exhaustion; live plan reports 41 Sleeper calls and 0 FantasyPros calls. |
| TA-304 | P0 | DONE | Normalize evaluation weeks, byes, fantasy matchups, trade deadline, and playoff/championship horizon from verified sources. | TA-104, TA-301 | R§6.1; D§4.2, §6 | Audited 32-team bye config plus Sleeper settings/bracket produces Weeks 1–17 and playoffs 15–17; missing schedule/matchups stop with `ScheduleIncomplete`. |
| TA-305 | P0 | DONE | Build authoritative ownership, user/opponent teams, unrostered pool, and the fixed tradeable player universe with identity coverage reports. | TA-204, TA-301, TA-302 | R§3, §4.4; D§4, §6 | Live snapshot resolves 10 teams, 150 owned players, 131 rostered tradeable players, 688 free agents, and 819 fixed tradeable players; duplicate/missing identity fixtures stop. |
| TA-306 | P0 | DONE | Assemble and freeze `TradeSnapshot`; implement completeness gates and immutable/offline loading with a visible non-current label. | TA-202–TA-305 | R§4.4, §11; D§6, §14 | Identical normalized inputs reproduce the manifest; saved JSON reloads with the same ID and forced `OFFLINE/NON-CURRENT`; stale ownership raises `StaleData`. |
| TA-307 | P1 | DONE | Add `trade refresh` as a data-only CLI surface with capability, budget, freshness, identity, and completeness reporting. | TA-306 | R§2.1, §9; D§12 | Live command reports complete current data, zero paid calls/recommendations/writes, cache status, horizon and manifest; required failures exit 2. |

### Phase 3 gate

A fresh League Alpha snapshot reconstructs every roster, owner, player, free agent,
week, and source timestamp with no ambiguous skill-player identity. Offline
replay is deterministic and explicitly non-current. The Phase 3 gate passes
with 205 tests; Phase 4 is ready for a separately named milestone.

## Phase 4 — In-season experts and independent value boards

Football consequence: identify players RosterTheory and the market value
differently while ensuring both opinions use the same point scale.

| ID | P | Status | Work and deliverable | Depends | Context | Exit evidence |
| --- | --- | --- | --- | --- | --- | --- |
| TA-401 | P0 | DONE | Create trade-scoped annual weekly in-season accuracy inputs with field-normalized finishes, coverage, source dates, and separate position/overall evidence. | Phase 3, TA-105 | R§5.1; D§7.1 | The 308-row 2021-2025 input records audited field sizes and top-10 public coverage; unavailable rows remain missing and no Draft field enters selection. |
| TA-402 | P0 | DONE | Run the in-season expert-selection study across candidate recency, coverage, pool-size, site concentration, freshness, and optional anchor controls. | TA-401 | R§5.1, §5.3; D§7.1, §16 | The dated study selects equal-year, coverage-adjusted top three with a two-expert site cap and records holdout results plus rejected alternatives. |
| TA-403 | P0 | DONE | Implement selected active-horizon aggregation with actual-contributor reweighting, pre-shrink ranks, approved ECR shrinkage, final ranks, dispersion, and omission reasons. | TA-302, TA-402 | R§5.1; D§7.1 | Fixtures preserve ballots, omissions, raw/final ranks, and dispersion; live evidence has 202 full-contribution and 37 partial-contribution rows labeled `WEEKLY-PROXY`. |
| TA-404 | P0 | DONE | Build untouched complete market ECR on the identical universe, scoring, active horizon, and timestamp boundary. | TA-302, TA-305 | R§3.3, §6.2; D§7 | The untouched market board independently covers the same 234 actionable players and horizon as the selected board. |
| TA-405 | P0 | DONE | Score direct ROS projections when available or the verified sum of remaining weekly projections under live Sleeper scoring; freeze each position's common descending distribution. | TA-205, TA-302, TA-305 | R§6.3-6.4; D§7.2 | Seventeen all-position weekly calls form audited QB/RB/WR/TE league-scored distributions with weekly coverage and source provenance. |
| TA-406 | P0 | DONE | Align the common positional projection distribution independently to selected and market rank order without shifting missing slots. | TA-403–TA-405 | R§6.2, §6.4; D§7.2 | The RB10 fixture assigns 150 points to each board's RB10; five retained slot placeholders prevent live rank shifting. |
| TA-407 | P0 | DONE | Apply the common waiver baseline, fit board-specific monotone overall-rank-to-VORP curves, and re-enforce each board's positional order. | TA-207, TA-406 | R§6.4, §6.6-6.7; D§7.3 | PAVA curves are monotone, positional order is enforced, and selected/market views share current free-agent replacement baselines. |
| TA-408 | P0 | DONE | Calibrate selected/weekly reconciliation and ECR shrinkage; compare pre-shrink, final, raw, positional, and overall-rank views without optimizing to one roster. | TA-402, TA-407 | R§5.1, §6.7; D§7, §16 | The study rejects a fixed anchor/blend; adaptive ECR shrinkage equals only missing selected-expert weight and all raw views remain exported. |
| TA-409 | P1 | DONE | Compute signed rank, tier, and common-scale value gaps; label buy-low/sell-high candidates without claiming opponent preference. | TA-407, TA-408 | R§3.3, §8.2; D§7.3 | Directional fixtures pass; reports define positive market-minus-selected VORP as sell-high and negative as buy-low, explicitly without preference claims. |
| TA-410 | P1 | DONE | Export board metadata, contributor/coverage issues, curve assignments, replacement evidence, and freshness checks. | TA-403–TA-409 | R§3.6, §9, §11; D§4.3, §13 | Manifest-linked ignored JSON evidence reproduces all 234 values with raw/final boards, gaps, warnings, curves, and common baselines. |

### Phase 4 gate

Selected and market boards cover the fixed required universe, use the same
projection distribution and common baseline, retain raw/pre-shrink views, pass
rank-order tests, and reproduce the controlled RB10 case. No package scoring
starts on a partial board.

The Phase 4 gate passes with 220 tests and a bounded live read-only validation.
Phase 4R completed the September 5 ranking-horizon refinement before Phase 5.

### Phase 4R — Ranking-horizon refinement

| ID | P | Status | Work and deliverable | Depends | Context | Exit evidence |
| --- | --- | --- | --- | --- | --- | --- |
| TA-411 | P0 | DONE | Audit historical weekly and point-in-time ROS rank availability without retaining licensed rows. | Phase 4 | R§5.1-5.2; D§5.3, §7.1, §16 | Authenticated 2024/2025 probes return distinct Week 8/14 weekly boards but zero rows for matching ROS-week calls; `TRADE_RANK_HORIZON_RESEARCH_2026.md` records counts and limitations. |
| TA-412 | P0 | DONE | Enforce per-expert/per-position ROS ballot freshness with a 14-day hard cutoff and immediate invalidation by newer material player news. | TA-411 | R§5.1, §11; D§5.4, §7.1 | Fixtures prove a new response cannot refresh an old ballot; the August 8 TE case is excluded while fresh RB remains eligible, and newer material news removes only the affected player row. |
| TA-413 | P0 | DONE | Implement separate `LONG_TERM` ROS and matchup/bye-aware `CURRENT_SIGNAL` weekly views without an arbitrary fixed blend. | TA-412 | R§5.2, §6; D§7-8 | The 216-player live evidence keeps separate sources/times; a bye fixture zeros current use without reducing ownership value, and `blend_enabled` is false. |
| TA-414 | P0 | DONE | Add reproducible prospective snapshot capture and a leakage-safe rolling-origin backtest harness for ROS-only, weekly-only, projection-only, and candidate blended views. | TA-411–TA-413 | R§5.2-5.3, §11; D§7.1, §15-16 | Future evidence is rejected; the deterministic harness reports point, lineup-value, ordering, sample-size, and standard-error metrics, and the Week 1 prospective snapshot has 864 records. |
| TA-415 | P0 | DONE | Implement the season-stage ownership source: final Draft selected/market boards through Week 2, conditional fresh-ROS transition entering Week 3, and an explicit review stop if the transition fails. | TA-412–TA-414 | R§4.4, §5.1-5.2; D§7.1 | Fixtures prove early ROS cannot displace the Draft anchor, both boards switch together only at a passing Week 3 gate, and failed post-Week-3 transition stops without approval. |
| TA-416 | P0 | DONE | Backtest a grid of historical weekly/final-Draft rank blends with Draft explicitly acting as the unavailable ROS proxy; measure early-week fit and Draft-signal decay. | TA-411, TA-413 | R§5.2-5.3; D§7.1, §15-16 | `TRADE_DRAFT_PROXY_BACKTEST_2026.md` reports 7,616 rows, 1,496 holdout metrics, Weeks 1-3, controls, modes, uncertainty, errors, limitations, and a reproducible cache-only hash; no blend is promoted. |
| TA-417 | P0 | DONE | Apply the user-directed season-stage amendment: Draft ownership rankings only in Week 1, joint fresh-complete ROS transition beginning Week 2, and prospective live comparison with weekly evidence kept separate. | TA-415, TA-416 | R§4.4, §5.1-5.3, §11; D§5.4, §7-8, §15-16 | `COMPLETED_TRADE_ASSISTANT_PHASE_4R_WEEK2_AMENDMENT.md` records the policy; fixtures prove Week 1 Draft, joint Week 2 ROS/fallback, Week 3 stop, and rejection of empty/fallback ROS boards. |

#### Phase 4R gate

Freshness is enforced on the actual ballot rather than the response, the
Draft-to-ROS transition is deterministic, both unblended modes are auditable,
the Draft-proxy blend study is reproducible, and prospective snapshots can
validate a true ROS blend without look-ahead. Phase 5 may then open while
`BLENDED` remains disabled until its evidence threshold passes.

The amended gate passed with 235 tests. At that stopping point Phase 5 remained
inactive until separately approved.

## Phase 5 — Entered-package evaluation core

Football consequence: correctly measure what a proposed trade does to both
actual teams before attempting to discover offers automatically.

| ID | P | Status | Work and deliverable | Depends | Context | Exit evidence |
| --- | --- | --- | --- | --- | --- | --- |
| TA-501 | P0 | DONE | Implement `PlayerAsset`, two-team `TradePackage`, exact name/ID resolution, ownership checks, supported-size checks, and simultaneous exchange. | Phase 4R | R§3.4, §8.4; D§4.3, §10 | Invalid owner, duplicate player, unsupported asset, self-trade, and valid package fixtures behave correctly. |
| TA-502 | P0 | DONE | Build the league-scored weekly projection matrix with bye/inactive handling, missing-week warnings, equal horizon weights, and playoff sensitivity. | TA-205, TA-304, TA-302 | R§6.1, §6.3, §6.5; D§8.2 | Every likely starter/week is covered or the result is explicitly partial/stopped. |
| TA-503 | P0 | DONE | Calculate before/after optimal lineups, starter displacement, weighted weekly delta, best/worst week, and playoff delta for either team. | TA-206, TA-502 | R§3.4, §6.5; D§8.1-8.2 | Hand calculations match one-for-one and cross-position fixtures. |
| TA-504 | P0 | DONE | Resolve unequal-package roster counts by enumerating legal drops or free-agent adds, showing the chosen and next-best options, with user overrides. | TA-207, TA-501–TA-503 | R§3.2, §6.6; D§8.3 | Controlled 2-for-1 fixture includes the secondary move and can reverse the result. |
| TA-505 | P0 | DONE | Implement symmetric `TradeEvaluator` values sent/received, raw/selected/market ownership views, weekly team impact, depth above waivers, and partner result. | TA-503, TA-504 | R§3.4, §8.1-8.2; D§10 | Swapping team perspective negates the appropriate package deltas and preserves team-specific value. |
| TA-506 | P1 | DONE | Add provisional reversal-condition generation from injuries, missing weeks, add/drop dependence, projection/rank disagreement, and playoff sensitivity. | TA-505 | R§3.4, §9; D§10 | Each controlled assumption change names the condition and exact affected component. |
| TA-507 | P1 | DONE | Add `trade evaluate` with compact terminal and canonical JSON output; defer final `ACCEPTABLE/TARGET/COUNTER/DECLINE` labels until Phase 6. | TA-505, TA-506 | R§2.1, §9; D§12 | Output leads with football consequences and keeps points, depth, market, and model views separate. |
| TA-508 | P1 | DONE | Save manifest-linked evaluation evidence and implement explicitly labeled `ECR-ONLY`, rank-only, schedule-partial, and manual-legality behavior. | TA-306, TA-507 | R§3.6, §4.4, §11; D§13-14 | Replay is deterministic; degraded modes cannot overclaim value, freshness, or full ROS. |

### Phase 5 gate

The exact evaluator passes one-for-one, cross-position, and 2-for-1 hand audits
for both teams. It emits component results but no final recommendation label
until risk and decision boundaries pass Phase 6.

The gate passed September 5 with 254 tests. Phase 5E remains inactive and
requires a separately approved milestone.

## Phase 5E — Larger entered-package extension

Football consequence: support the three- and four-player packages that occur
in this league without hiding the roster moves needed to make unequal trades
legal or choosing those moves greedily.

| ID | P | Status | Work and deliverable | Depends | Context | Exit evidence |
| --- | --- | --- | --- | --- | --- | --- |
| TA-509 | P1 | DONE | Expand manually entered player packages to one through four players per team. Preserve exact two-team ownership and simultaneous exchange; jointly enumerate up to three required adds/drops for unequal packages, expose the chosen and next-best legal move sets, accept repeated explicit overrides, and impose deterministic combination/runtime bounds. This does not expand automatic league-wide search. | Phase 5 | R§3.2, §3.4, §6.6, §8.4; D§8.3, §10, §12 | Hand-audited 3-for-3, 4-for-4, and unequal large-package fixtures match both roster perspectives; a controlled case proves joint move selection can beat greedy one-at-a-time choices; CLI/evidence replay is deterministic and the full suite passes. |

### Phase 5E gate

Entered packages with one through four players on either side retain correct
two-roster lineup, depth, ownership, and add/drop effects under a documented
local runtime bound. Automated Phase 7 search begins with smaller packages and
expands to bounded three- and four-player packages under TA-707.

The gate passed September 5 with 261 tests. Phase 6 remains inactive and
requires a separately approved milestone.

## Phase 6 — Risk, roster diagnosis, and decision gates

Football consequence: distinguish a valuable stack from dangerous shared
downside and avoid recommending diversification at the cost of expected wins.

| ID | P | Status | Work and deliverable | Depends | Context | Exit evidence |
| --- | --- | --- | --- | --- | --- | --- |
| TA-601 | P0 | DONE | Calculate NFL-team starter/full-roster counts, projected point-share concentration, pair types, byes, and playoff concentration before/after. | Phase 5 | R§3.1, §7.2; D§9 | Bengals fixture identifies Chase/Brown/Higgins individually and jointly without applying a penalty. |
| TA-602 | P0 | DONE | Implement transparent independent-absence, offense-wide downside, and offense-wide upside scenarios using versioned configurable multipliers. | TA-503, TA-601 | R§7.1-7.2; D§9 | Scenario deltas are deterministic, auditable, and never labeled probabilities. |
| TA-603 | P0 | DONE | Study historical player-points coverage and derive candidate position-pair/same-offense priors under league scoring; document licensing/sample limitations. | TA-103, TA-205 | R§4.3, §7.2; D§9, §16 | `TRADE_RISK_EVIDENCE_STUDY_2026.md` selects scenario-only fallback because one PPR RB season cannot calibrate multi-position half-PPR priors. |
| TA-604 | P0 | DONE | If TA-603 supports it, implement sample-aware player-pair correlation shrinkage toward priors with overlap count and confidence; otherwise preserve the fallback. | TA-603 | R§7.2; D§9 | `SCENARIO-ONLY-RISK` is explicit; no unsupported coefficients or probabilities are fitted. |
| TA-605 | P1 | DONE | Define conservative, balanced, and ceiling-seeking ordering rules that alter package preference without changing ranks/projections. | TA-602, TA-604 | R§7.3; D§9-10, §16 | Tests hold team/value components fixed while printed depth/downside thresholds change by posture. |
| TA-606 | P1 | DONE | Implement roster diagnosis: weekly lineups, positional need/surplus, unusable depth, waiver recovery, bye gaps, concentration, and smallest useful change. | TA-503, TA-601–TA-605 | R§3.1; D§8-9 | Controlled diagnosis distinguishes unused below-waiver depth; live roster diagnosis identifies Week 13 coverage and Cincinnati concentration. |
| TA-607 | P0 | DONE | Calibrate partner near-neutral and decision-label boundaries across golden fixtures and sensitivity cases; print every threshold and gate. | TA-505–TA-606 | R§3.4, §7.3, §8.1, §8.3, §9; D§10, §16 | Versioned v1 policy and study define `ACCEPTABLE`, `COUNTER`, and `DECLINE`; every gate is printed and no acceptance probability appears. |
| TA-608 | P0 | DONE | Hand-audit two Bengals cases: a fair diversification improvement and a discounted offer where keeping the stack wins. | TA-607 | R§12.2-12.3, §12.14; D§9, §15 | Equal-value diversification is `ACCEPTABLE`; discounted diversification is `DECLINE` despite lower concentration. |
| TA-609 | P1 | DONE | Integrate final risk vector, posture, labels, and reversal conditions into `trade diagnose` and `trade evaluate` reports/evidence. | TA-606–TA-608 | R§9, §12; D§10, §12-13 | Both CLI surfaces expose weekly, depth, risk, value, partner, gates, provenance, and saved evidence. |
| TA-610 | P0 | DONE | Make live evaluation warnings decision-relevant: aggregate missing-projection coverage by affected roster/role, name incomplete package or secondary-move players individually, suppress per-week fringe-player floods from compact output, and remove stale phase-state warnings. Preserve auditable counts/details in saved evidence. | TA-508 | R§4.4, §9, §11; D§12-14 | Live package names complete evaluated coverage and aggregates 5,270 outside-evaluation player-weeks into one coverage line; stale warning is removed. |

### Phase 6 gate

Both Bengals audits pass, a high-value stack is not automatically sold, risk
components remain visible, labels are threshold-backed, and no acceptance
percentage appears. Compact reports contain only decision-relevant warnings;
full saved evidence remains auditable.

## Phase 7 — League-wide gaps and package search

Football consequence: turn trustworthy evaluation into actionable targets
that solve real needs for both managers rather than listing nominally equal
players.

| ID | P | Status | Work and deliverable | Depends | Context | Exit evidence |
| --- | --- | --- | --- | --- | --- | --- |
| TA-701 | P1 | DONE | Diagnose every team with the same lineup/depth logic; identify weak slots, usable surplus, waiver alternatives, and partner needs. | Phase 6 | R§3.2-3.3, §8.1; D§11 | Controlled league fixture distinguishes unused surplus from roster-count surplus. |
| TA-702 | P1 | DONE | Enumerate unique 1-for-1, 2-for-1, 1-for-2, and bounded 2-for-2 player packages within each exact opponent roster. | TA-501, TA-701 | R§3.2, §8.4; D§11 | Enumeration has no duplicates, wrong-owner assets, unsupported assets, or three-team packages. |
| TA-703 | P1 | DONE | Add safe prefilters for broad market band, legal roster shape, bilateral need, and dominated bundles; verify they do not prune controlled best packages. | TA-409, TA-702 | R§3.2-3.3; D§11 | Exhaustive small-league comparison proves retained optimum/frontier. |
| TA-704 | P1 | DONE | Run exact evaluation on survivors, remove Pareto-dominated results, and produce frontiers for expected points, lower risk, market gap, and partner-positive simplicity. | TA-609, TA-703 | R§3.2, §3.5, §8; D§11 | Frontier keeps materially distinct alternatives and explains both teams. |
| TA-705 | P1 | DONE | Add `trade gaps`, `trade search`, and `trade compare`; complete `trade diagnose` with namespaced terminal/JSON/CSV output. | TA-409, TA-609, TA-704 | R§3, §9; D§12 | Commands never mix Draft terminology and expose data time/horizon on every output. |
| TA-706 | P1 | DONE | Bound search size and runtime, cache team baselines, verify deterministic ordering, and report candidates enumerated/pruned/evaluated. | TA-704, TA-705 | R§3.2, §11; D§11-12 | Full League Alpha fixture completes within an approved local budget with identical replay. |
| TA-707 | P1 | DONE | Expand automatic opportunity discovery to bounded three- and four-player packages on either side. Seed larger bundles from diagnosed needs, usable surpluses, and the smaller-package frontier; exact-evaluate every survivor and report the searched coverage rather than implying exhaustive enumeration. | TA-509, TA-704, TA-706 | R§3.2-3.4, §8.4; D§11 | Controlled fixtures retain a best 3-for-2 and a materially distinct four-player-side opportunity that smaller search cannot find; live search stays within the approved runtime bound and reports all size-specific candidate/pruning counts. |

### Phase 7 gate

Search evaluates all opponents from current Sleeper ownership, returns only
packages with a user benefit and credible partner rationale, retains the
lower-variance frontier, includes bounded larger-package discovery, discloses
its search coverage, and exactly reproduces saved results.

Implementation and automated gates passed September 5 with 276 tests. The
live default exact-evaluates two small and one seeded large finalist per
opponent and completed in 119.80 seconds. Initial user testing is ready; Phase
8 remains inactive pending separate approval.

### Phase 7 initial-testing correction

| ID | P | Status | Work and deliverable | Depends | Context | Exit evidence |
| --- | --- | --- | --- | --- | --- | --- |
| TA-708 | P0 | DONE | Reject a searched package when either roster's required drop is a player it just received; keep manual evaluation available for diagnosis. | TA-704, TA-707 | R§3.2, §6.6, §8.1; D§10-11 | Regression fixture records `received_asset_immediately_dropped`; both Pittman-padded live candidates are rejected. |
| TA-709 | P0 | DONE | Version a conservative automatic-target agreement gate requiring nonnegative selected-expert, market, and raw-projection ownership deltas alongside positive exact lineup value. Preserve every view separately. | TA-704, initial FP comparison | R§6.7, §8.2, §9; D§10-11 | Mixed-model fixture is rejected; live corrected search returns no false targets and reports the exact gate. |

The correction passed 279 tests. A live default run completed in 120.40
seconds and returned zero targets: two finalists were received-then-dropped
packages, one failed partner-lineup credibility, one failed the new target
value gate, and the others failed existing Phase 6 gates. Zero is preferable
to recommending a package without cross-model agreement.

## Phase 8 — MVP readiness and handoff

Football consequence: make the assistant trustworthy enough to influence a
real offer while retaining an obvious stop when data or assumptions are weak.

| ID | P | Status | Work and deliverable | Depends | Context | Exit evidence |
| --- | --- | --- | --- | --- | --- | --- |
| TA-801 | P0 | DONE | Run the complete golden fixture matrix and map all 14 MVP acceptance criteria to passing tests/evidence. | Phase 7 | R§12; D§15 | All deterministic fixture criteria pass in the 283-test suite; every remaining live or audit obligation is explicitly assigned below. |
| TA-802 | P0 | OPERATIONAL | Refresh a real read-only League Alpha snapshot; hand-audit ownership, boards, waiver baselines, diagnosis, gaps, one entered package, and top search alternatives. This is an on-demand recurring operation, not unfinished development. | TA-801 | R§12; D§6, §15 | Every run uses fresh League Alpha evidence and reconciles automated results to current Sleeper rosters and exact calculations. |
| TA-803 | P0 | SUPERSEDED | Audit network methods, secrets, cache/export contents, source attribution/licensing, and failure behavior. | OS-006, OS-007, OS-013 | R§2.1, §3.6, §11-13; D§5, §13-14 | Public-release gates, full-history review, redistribution review, and the automated GET-only boundary cover the intended evidence. |
| TA-804 | P0 | SUPERSEDED | Run full unit/regression suite, CLI smoke checks, deterministic replay, coverage/completeness checks, and documentation/link validation. | OS-006, OS-007, OS-013 | R§12.10-12.13; D§15 | Blocking multi-platform CI, clean-candidate validation, and post-publication verification cover the release checks; generic link maintenance is repository work. |
| TA-805 | P1 | CLOSED | Update README commands, current handoff, product context, and a concise Trade operations runbook without making large docs startup context. | OS-005, OS-008–OS-012, OS-014–OS-018 | R§9-11; D§12-14 | The public README documents Trade workflows and routed status/context files provide the handoff. A dedicated runbook is optional documentation, not a blocker. |
| TA-806 | P0 | OBSOLETE | Present the audited MVP and known limitations for user approval; close or extend the active milestone based on evidence. | Phase 9, OS-013 | R§12-13; D§16 | League Beta Phase 9 and the approved public alpha supersede this sequencing gate; no Trade milestone remains active. |

Backlog audit completed September 17, 2026. TA-802 is retained only as a fresh,
on-demand League Alpha operation because its evidence expires and it is not a
publication or development prerequisite. TA-803 through TA-806 no longer form
an executable dependency chain: the public-release program, completed League
Beta Phase 9, public documentation, and blocking release workflow supplied or
superseded their intended evidence. The historical Phase 8 gate below remains
design history and does not authorize work.

### Historical Phase 8 gate — original MVP definition of done

This original gate required every acceptance criterion to pass on fixtures and
a fresh League Alpha snapshot. It also required read-only outputs, complete
current ownership and identity, auditable valuation boards and raw projections,
correct lineup/depth/risk effects for both teams, reproducible saved results, a
green Draft suite, and user acceptance of the handoff.

## Acceptance-criteria traceability

TA-801 result: the complete deterministic golden-fixture matrix passes. There
are no genuine fixture-coverage gaps. Criteria whose definition also requires
current League Alpha evidence remain explicitly pending TA-802; the broader safety
audit and final release regression remain pending TA-803 and TA-804.

| Requirement acceptance criterion | TA-801 result | Exact deterministic evidence | Remaining evidence |
| --- | --- | --- | --- |
| 1. Reconstruct all rosters/owners | FIXTURE PASS | `tests/test_trade_snapshot.py::ScheduleAndSnapshotTests.test_snapshot_is_deterministic_complete_and_offline_is_noncurrent`; `tests/test_core_foundations.py::IdentityTests.test_exact_external_alias_unmatched_and_ambiguous_are_audited` | TA-802: reconcile every fresh League Alpha roster, owner, and skill-player identity. |
| 2. Detect three-Bengals concentration without forced sale | FIXTURE PASS | `tests/test_trade_evaluation.py::ProjectionAndEvaluationTests.test_bengals_diversification_and_discounted_offer_have_opposite_labels`; `tests/test_trade_evaluation.py::ProjectionAndEvaluationTests.test_same_offense_concentration_and_scenarios_are_explicit_not_a_tax` | TA-802: confirm the current three-Bengals starting exposure. |
| 3. Weekly lineup, waiver depth, bye, offense downside | FIXTURE PASS | `tests/test_trade_evaluation.py::ProjectionAndEvaluationTests.test_roster_diagnosis_distinguishes_unused_depth_from_player_count`; `tests/test_trade_evaluation.py::ProjectionAndEvaluationTests.test_bye_zeroes_only_the_affected_week`; `tests/test_trade_evaluation.py::ProjectionAndEvaluationTests.test_same_offense_concentration_and_scenarios_are_explicit_not_a_tax`; `tests/test_core_foundations.py::ReplacementTests.test_baseline_uses_only_current_unowned_points` | TA-802: hand-audit current lineup, waiver baselines, byes, and downside. |
| 4. Two complete independently aligned boards | FIXTURE PASS | `tests/test_trade_value_boards.py::TradeBoardTests.test_boards_share_distribution_and_baseline_but_not_identity_order`; `tests/test_trade_value_boards.py::TradeBoardTests.test_selected_aggregation_preserves_raw_and_missing_weight_anchor`; `tests/test_trade_horizon_refinement.py::SeasonStageTests.test_draft_anchor_is_mandatory_during_week_one`; `tests/test_trade_horizon_refinement.py::SeasonStageTests.test_week_two_switches_both_boards_or_retains_both_for_review` | TA-802: audit fresh same-horizon boards, raw projections, completeness, and the active horizon label. |
| 5. RB10 rank-slot transfer | PASS | `tests/test_trade_value_boards.py::TradeBoardTests.test_rb10_rank_slot_transfer_and_raw_projection_are_both_preserved` | None. |
| 6. Correct buy-low/sell-high direction without preference claim | FIXTURE PASS | `tests/test_trade_value_boards.py::TradeBoardTests.test_boards_share_distribution_and_baseline_but_not_identity_order`; `tests/test_trade_search.py::LeagueSearchTests.test_gap_report_includes_owner_and_sign_convention`; `tests/test_trade_search.py::LeagueSearchTests.test_user_sell_high_can_return_a_partner_credible_target`; `tests/test_trade_value_boards.py::TradeBoardTests.test_gap_report_never_claims_an_opponent_preference` | TA-802: hand-audit current gaps. |
| 7. Search every opponent with bilateral rationale | FIXTURE PASS | `tests/test_trade_search.py::LeagueSearchTests.test_candidate_enumeration_visits_every_opponent_roster`; `tests/test_trade_search.py::LeagueSearchTests.test_results_are_bilateral_deterministic_and_auditable`; `tests/test_trade_search.py::LeagueSearchTests.test_safe_small_pruning_retains_controlled_exhaustive_frontier` | TA-802: reconcile the fresh all-opponent run; large packages remain visibly bounded, not exhaustive. |
| 8. Legal 1-for-1 and 2-for-1 with add/drop | FIXTURE PASS | `tests/test_trade_evaluation.py::ProjectionAndEvaluationTests.test_cross_position_one_for_one_reports_both_teams_and_model_split`; `tests/test_trade_evaluation.py::ProjectionAndEvaluationTests.test_two_for_one_enumerates_add_and_drop_with_next_best`; `tests/test_trade_evaluation.py::ProjectionAndEvaluationTests.test_four_for_one_jointly_resolves_three_adds_and_three_drops`; `tests/test_trade_evaluation.py::ProjectionAndEvaluationTests.test_one_for_two_required_drop_reverses_apparent_package_gain` | TA-802: hand-audit one current entered package. |
| 9. Separate lineup, depth, risk, value, partner deltas | FIXTURE PASS | `tests/test_trade_evaluation.py::ProjectionAndEvaluationTests.test_cross_position_one_for_one_reports_both_teams_and_model_split`; `tests/test_trade_evaluation.py::ProjectionAndEvaluationTests.test_same_offense_concentration_and_scenarios_are_explicit_not_a_tax`; `tests/test_trade_evaluation.py::TradeEvaluationCliTests.test_compact_report_keeps_value_views_separate_and_prints_decision_gates` | TA-802: reconcile each component for the current package/search evidence. |
| 10. Reproducible saved result | FIXTURE PASS | `tests/test_trade_evaluation.py::ProjectionAndEvaluationTests.test_evidence_is_deterministic_and_offline_replay_is_labeled`; `tests/test_trade_evaluation.py::ProjectionAndEvaluationTests.test_evidence_replay_rejects_modified_contents`; `tests/test_trade_search.py::LeagueSearchTests.test_saved_search_evidence_replays_and_rejects_tampering` | TA-802: retain and reconcile fresh evidence inputs/results. |
| 11. Visible stale/unknown/ambiguous/incomplete failure | PASS | `tests/test_trade_snapshot.py::ScheduleAndSnapshotTests.test_snapshot_is_deterministic_complete_and_offline_is_noncurrent`; `tests/test_trade_snapshot.py::ScheduleAndSnapshotTests.test_duplicate_ownership_stops_snapshot`; `tests/test_core_foundations.py::ScoringAndLineupTests.test_scoring_preserves_stats_and_reports_unsupported_settings`; `tests/test_trade_evaluation.py::PackageContractTests.test_ambiguous_exact_name_stops`; `tests/test_trade_value_boards.py::TradeBoardTests.test_missing_fixed_universe_member_stops_board`; `tests/test_trade_evaluation.py::ProjectionAndEvaluationTests.test_missing_fringe_projection_is_aggregated_without_warning_flood` | None for fixture coverage. |
| 12. No Sleeper write or key exposure | CURRENT SAFETY PASS | `tests/test_sleeper_client.py::SleeperClientTests.test_trade_surfaces_use_documented_get_paths`; `tests/test_fantasypros_client.py::FantasyProsClientTests.test_records_safe_request_metadata_and_count`; `tests/test_trade_provider_probe.py::TradeProviderProbeTests.test_probe_records_only_get_schema_evidence`; `tests/test_trade_value_boards.py::TradeBoardTests.test_gap_report_never_claims_an_opponent_preference` | TA-803: complete network, secret, cache/export, licensing, and failure-path audit. |
| 13. Required automated coverage | CURRENT SUITE PASS (283) | Repository-root `python -m unittest discover -s tests -v`; the named tests above plus scoring, provider normalization, symmetry, correlation, pruning, degraded-mode, and explanation tests | TA-804: rerun the final release regression/CLI/replay/documentation gate. |
| 14. Opposite Bengals case hand audits | PASS | `tests/test_trade_evaluation.py::ProjectionAndEvaluationTests.test_bengals_diversification_and_discounted_offer_have_opposite_labels` pins both teams at 23.0 before/after per week for the fair case and the user at 23.0 to 20.0 per week for the discounted case. | None. |

## Phase 9 — League Beta format expansion and optimization

Football consequence: evaluate League Beta's deeper 12-team player pool and second
FLEX from its actual current rosters without letting kicker/defense-only
scoring block or distort QB/RB/WR/TE trade advice.

This phase is a user-approved multi-league capability expansion after TA-801's
complete deterministic fixture gate. It does not change Phase 8's definition
of done, authorize a Sleeper transaction, or import League Beta Draft acquisition
and construction policy into Trade. The September 7 attempted
`trade search league_beta` stopped visibly after encountering the nonzero scoring
settings `blk_kick`, `ff`, `fgm_50_59`, `fgm_60p`, `st_ff`, and
`st_fum_rec`; it produced no recommendation.

| ID | P | Status | Work and deliverable | Depends | Context | Exit evidence |
| --- | --- | --- | --- | --- | --- | --- |
| TA-901 | P0 | DONE | Capture a fresh GET-only League Beta Trade snapshot and publish the exact format capability contract: 12 teams; QB/2 RB/2 WR/TE/2 FLEX/K/DEF/five bench; reserves; playoffs; trade deadline; every nonzero Sleeper scoring setting; and current ownership. Classify each scoring setting by affected player positions and verified FantasyPros stat coverage. Record the September 7 stop and reuse fresh cached data where valid rather than spending paid quota for discovery. | TA-801, user approval | R§2.1, §4.1-4.4, §6.1, §11; D§5-6, §14-16 | `TRADE_LEAGUE_BETA_FORMAT_CAPABILITY_2026.md` records the fresh 12-team/two-FLEX contract, all 40 nonzero scoring settings, complete ownership/horizon evidence, cached position-specific FantasyPros schemas, the exact six-category stop, and the late-preflight quota flaw with zero new paid calls. |
| TA-902 | P0 | DONE | Move the league-scoring capability preflight ahead of FantasyPros call reservation and retrieval. Make it position-aware for the supported Trade universe so a genuinely unsupported QB/RB/WR/TE category stops with zero paid calls, while verified K/DST-only categories remain explicit audit metadata instead of blocking skill-player valuation. | TA-901 | R§4.3-4.4, §6.3, §11; D§5.4, §8.2, §14 | Tests prove unsupported skill scoring stops before any FantasyPros request or budget mutation; the exact League Beta scoring contract passes preflight; all ignored non-skill categories appear in evidence with their position rationale. |
| TA-903 | P0 | DONE | Extend feature-neutral scoring aliases/capability metadata only where TA-901 proves an exact Sleeper-to-FantasyPros mapping. Do not add a blanket unknown-setting allowlist. Keep K and DST as authoritative roster occupants but outside automatic player-package valuation unless separately supported; prove their unchanged scores cannot leak into skill-player points or before/after deltas. | TA-901, TA-902 | R§2.2, §4.4, §6.3, §10-11; D§3, §7.2, §8.2, §14 | Unit fixtures cover all six observed League Beta stop categories, distinguish K/DST-only from skill-relevant settings, preserve raw scoring inputs, and still fail on a new nonzero unsupported skill category. Existing League Alpha projection totals are unchanged. |
| TA-909 | P0 | DONE | Remove the hard-coded League Alpha Week 1 Draft-anchor default. Resolve the final anchor and its source timestamp from the requested league's audited board metadata; verify league key/ID and fail closed on missing or cross-league evidence. | TA-903, live League Beta audit | R§2.1, §4.1, §4.4, §5.2, §11; D§6-7, §14-15 | League Beta loads only `league_beta_board.csv` and its generated timestamp; controlled mismatched metadata stops; cache-only League Alpha regression still resolves its own anchor; evidence records the selected anchor path and league identity. |
| TA-904 | P0 | DONE | Add a deterministic League Beta-shaped golden fixture covering 12 complete rosters, 180 occupied slots, two FLEX starters, five bench slots, K/DST occupancy, 11 opponents, league-sized free agency, exact user resolution, and the full remaining fantasy horizon. Validate optimal eight-skill-player lineups plus legal equal and unequal packages, including joint add/drop consequences without silently dropping a received asset or a fixed K/DST occupant. | TA-909 | R§3.1-3.4, §4.4, §6.1, §6.5-6.6, §12; D§6, §8-11, §15 | Hand calculations match lineup, replacement, roster-count, and partner deltas; all 11 opponents reach candidate enumeration; duplicated ownership, missing matchup rows, incomplete identity, and illegal secondary moves stop visibly. |
| TA-905 | P0 | DONE | Calibrate the shared Trade decision gates for League Beta's exact scarcity and lineup shape without fitting to one desired offer. Recalculate QB/RB/WR/TE waiver baselines, usable-depth thresholds, need/surplus behavior, two-FLEX starter displacement, bye/playoff coverage, and offense-concentration scenarios. Test controlled League Beta cases plus cross-league isolation; retain the shared policy when evidence does not justify a League Beta override. | TA-904 | R§3.1-3.5, §6.5-6.7, §7-9; D§7.3, §8-11, §15-16 | `COMPLETED_TRADE_ASSISTANT_PHASE_9.md` records the shared gates retained and the versioned near-waiver construction need; ranks, projections, Draft policy, and League Alpha live state were not changed. |
| TA-906 | P1 | DONE | Benchmark and optimize the bounded league search for 11 opponents and the League Beta roster/free-agent sizes. Profile refresh, baseline diagnosis, candidate construction, exact evaluation, and evidence export; improve reuse or safe pruning before reducing search coverage. Predeclare runtime/memory bounds and compare optimized results with exhaustive controlled fixtures and the unoptimized deterministic baseline. | TA-904, TA-905 | R§3.2-3.5, §8, §11; D§10-12, §15-16 | Live runtime fell from a greater-than-five-minute freshness failure to 105.66 seconds; 6,226 enumerated and 33 exact evaluations remain visible, while brute-force lineup and exhaustive controlled-frontier tests pass. |
| TA-907 | P0 | DONE | Run a fresh read-only League Beta acceptance audit: reconcile every roster and skill-player identity; independently check the active season-stage selected/market boards and raw projections; hand-audit waiver baselines, diagnosis, two-FLEX lineups, gaps, one entered package, and the top search alternatives. Use League Beta's own Week 1 Draft anchor only when the governing Trade horizon policy requires it; never use League Alpha ranks or calibration. | TA-901–TA-906 | R§3-9, §11-12; D§6-15 | The final current search reconciles every roster and Week 1-17, visits all 11 opponents, and reproduces the hand-audited Deebo Samuel plus Juwan Johnson for Mark Andrews target with explicit secondary moves and no cross-league input. |
| TA-908 | P0 | DONE | Complete the expansion regression and safety handoff: full unit suite, deterministic replay, zero-paid-call preflight-failure check, GET-only/network and secret audit, cache/export inspection, documentation links, and concise League Beta Trade operating guidance. Honor the user's deferral of the separate live League Alpha refresh. | TA-907 | R§2.1, §3.6, §9-13; D§5, §12-16 | 308 tests pass; final hash replay succeeds; the ledger remains at 21 cached-call uses; no secret/licensed rows or Sleeper writes occur; League Alpha live remains deferred to TA-802. |

### Phase 9 gate

League Beta is supported only when its exact live format passes position-aware
scoring preflight, every roster and evaluation week is complete, two-FLEX
lineups and 12-team waiver scarcity reconcile by hand, the bounded search
visits all 11 opponents within the approved local budget, identical evidence
replays deterministically, League Alpha and Draft regressions remain green, and the
user accepts the read-only handoff. An unclassified nonzero skill scoring
setting, partial ownership/identity, or failed horizon gate still stops before
recommendations.

## Phase 10 — Ranking-exclusion resilience and roster-context targets

Football consequence: an injured or otherwise unranked player must not prevent a
league report, while an automatic target must not call the full generic value of
a redundant third quarterback a benefit when that quarterback barely affects the
user's optimal lineup.

This phase is a user-approved correctness repair after the September 18 live
searches. It applies league-neutral mechanics and verifies League Alpha and
League Beta independently. It does not copy either league's calibration, alter
authoritative expert ranks, change Draft or Waiver policy, or authorize a Sleeper
transaction.

| ID | P | Status | Work and deliverable | Depends | Context | Exit evidence |
| --- | --- | --- | --- | --- | --- | --- |
| TA-1001 | P0 | DONE | Preserve the complete authoritative provider rank-slot distribution when building Trade projection curves even when a ranked player cannot map into the current Sleeper player universe. Continue to exclude unmapped players from roster/value boards, audit the mismatch, and fail visibly only when the provider distribution itself is incomplete. | September 18 League Beta false stop | R§6.4, §6.7, §11-12; D§6, §7.2, §14-15 | The curve builder now receives the complete canonical provider distribution. A provider-only WR slot remains in the curve but outside the board universe; genuine curve and board coverage failures remain covered. All 25 value-board tests pass. |
| TA-1002 | P0 | DONE | Make automatic Trade target selection use roster-context marginal utility. Prevent an incoming asset at a one-starter position from being credited as an unrestricted upgrade when it only creates excess redundant depth, bind need/surplus rationale to the assets that supply it, and expose incoming-asset lineup use so small incidental gains cannot disguise a negative core exchange. Entered packages remain evaluable. | TA-1001 | R§3.2, §6.5-6.7, §8.1-8.2, §9, §12; D§7.3, §8.2-8.3, §10-12, §15 | The Phase 10 search policy derives starting capacity from each league's actual slots, permits one reserve at a one-starter position, rejects an added third 1QB, preserves QB-for-QB and superflex cases, binds need rationale to incoming starters, and reports incoming use. All 18 search tests and all 112 Trade tests pass. |
| TA-1003 | P0 | DONE | Run focused and full regressions, then fresh GET-only Trade searches for League Alpha and League Beta. Reconcile each league separately and compare the corrected outputs with the September 18 evidence. | TA-1001-TA-1002 | R§11-12; D§14-15 | Live evidence passes and replays: Alpha hash `f46d834e73b0935a` returns no target after 5,094 enumerated/27 exact packages and records two redundant-position rejections; Beta hash `7cfa494b39a6ed4b` returns no target after 6,226/33 and no longer stops at WR 106/107. The dedicated 14-test context gate and all 568 repository tests pass. CI now runs the context gate separately on every push and pull request. No Sleeper write occurred. |

### Phase 10 gate

Phase 10 completes only when provider-only ranking exclusions preserve the
authoritative positional distribution without entering roster boards, automatic
targets value redundant positions through actual roster use, both leagues have
separate fresh evidence, all regressions pass, and no Sleeper write or expert-rank
invention occurs.

## Phase 11 — Single-command Trade analysis

Football consequence: asking for a roster diagnosis, trade search, valuation-gap
report, entered-offer evaluation, or package comparison should use current,
league-correct evidence without making the manager operate the data pipeline.

This phase is user-approved on September 18. It changes orchestration and
documentation only: explicit refresh/preparation commands and replay overrides
remain available, league policies remain isolated, and every operation remains
read-only.

| ID | P | Status | Work and deliverable | Depends | Context | Exit evidence |
| --- | --- | --- | --- | --- | --- | --- |
| TA-1101 | P0 | DONE | Make every user-facing Trade analysis command automatically prepare required schedule/expert evidence and then refresh current Sleeper/value-board inputs. Reuse fresh caches, preserve explicit overrides and snapshot replay, show concise interactive progress, keep machine output clean, repair same-league legacy policy metadata when safe, document the one-command workflow, and verify both configured leagues independently without a Sleeper write. | OS-018, WA-022, Phase 10 | R§3.1-3.6, §9-11; D§12-14 | Diagnose, evaluate, gaps, search, and compare now prepare automatically; replay stays offline and advanced overrides remain. Both default-config leagues pass live diagnosis and search independently. Alpha search enumerated 5,094/evaluated 27; Beta 6,226/33; both returned no target. All 588 tests and Ruff pass; no Sleeper write occurred. |

### Phase 11 gate

Phase 11 completes only when the normal Trade workflow starts with the requested
analysis command rather than `inputs prepare` or `trade refresh`, fresh evidence
is reused, failures name the actual unresolved prerequisite, replay remains
offline, both leagues retain separate policy/evidence, and no Sleeper write or
expert-rank invention occurs.

## Phase 12 — Search runtime optimization and publication

Football consequence: a 12-team, two-FLEX league search must remain broad
enough to find the same credible packages while completing quickly enough to
feel like an interactive analysis rather than a batch job.

This phase is user-approved on September 18. Optimize repeated deterministic
calculation before considering any reduction in candidate coverage. Preserve
the exact package enumeration, pruning, evaluation, ordering, evidence, and
league-local policy behavior. Publish the complete tested Waiver and Trade
changes to the external repository only after privacy and release gates pass.

| ID | P | Status | Work and deliverable | Depends | Context | Exit evidence |
| --- | --- | --- | --- | --- | --- | --- |
| TA-1201 | P0 | DONE | Profile the current League Beta search, remove repeated pure calculations through scoped immutable caches/precomputation, and prove identical search semantics on controlled fixtures and both saved/live league cases. Record before/after runtime and do not reduce enumeration or exact-evaluation coverage. Run the complete quality/privacy gates, commit all intended Waiver/Trade work, and push the tested branch to the public external repository. | TA-1101, Phase 10 | R§3.2, §10-11; D§11, §15 | The measured two-FLEX allocation bug is fixed and repeated per-shape selection work is precomputed. League Beta fell from about 225s to 63s while retaining 6,226/33 and no target; League Alpha retained 5,094/27 and no target. Complete tests, Ruff, release/privacy gates, commit, push, and remote verification passed. |

### Phase 12 gate

Phase 12 completes only when measured runtime improves materially without
changing candidate coverage or recommendation semantics, deterministic tests
and live league-isolated comparisons pass, no private artifact enters the
commit, release gates pass, and the resulting commit is verified on the public
remote. No Sleeper write is authorized.

## Deferred beyond the player-only redraft MVP

These are intentionally unnumbered so they cannot be mistaken for active work:

- submitting, accepting, rejecting, or messaging trades;
- calibrated acceptance probability;
- dynasty, keeper, draft-pick, FAAB, auction, conditional, or three-team assets;
- manager-specific psychology from incomplete rejected-offer data;
- probabilistic P10/P90 labels before distribution backtesting;
- a hosted, account-based, or multi-user interface;
- waiver and Start/Sit product surfaces; and
- any Trade result that changes Draft rankings, simulation, or watcher policy.
