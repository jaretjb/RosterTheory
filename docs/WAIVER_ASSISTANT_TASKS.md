# Waiver Assistant task backlog

Updated: September 14, 2026 (America/Los_Angeles)
Initial league: `league_alpha`

Only the task named in `.codex/context/ACTIVE_MILESTONE.md` authorizes implementation.
Later rows are planned scope, not permission to run live retrieval or change
recommendation policy.

## WA-001 — Shared Sleeper waiver-state foundation (complete)

Outcome: Preserve the read-only data required to reason about waiver legality
and acquisition cost without generating a recommendation.

- Preserve deterministic raw league and roster platform settings in shared
  normalized models.
- Normalize roster waiver position and budget-used fields.
- Preserve transaction creation/update timestamps, creator, waiver bid, and
  failure metadata when supplied.
- Add focused provider tests and retain Trade snapshot replay compatibility.
- Run the complete repository test suite.
- Do not call FantasyPros, run a live League Alpha analysis, or add a Sleeper write.

Stop: tested shared data foundation and updated handoff. WA-002 requires a new
active milestone.

Completed September 9, 2026. The focused 13-test provider/snapshot suite and
the 308-test repository suite pass. Evidence is recorded in
`docs/COMPLETED_WAIVER_ASSISTANT_WA_001.md`.

## WA-002 — Immutable Waiver snapshot and data-only refresh (complete)

- Add a `waiver` package and immutable League Alpha snapshot.
- Classify free-agent/waiver/locked/pending/unknown acquisition state from
  proved inputs.
- Validate roster capacity, reserve legality, ownership, identity, and
  freshness.
- Add `waiver refresh league_alpha` with ignored evidence output and an
  explicit `sleeper_write_performed: false` field.
- Perform a bounded GET-only live capability audit only after activation.

Stop: tested immutable snapshot and data-only refresh with the public Sleeper
availability limitation preserved as `UNKNOWN`; WA-003 requires a new active
milestone.

Completed September 9, 2026. The live League Alpha audit reconstructed all 10
rosters but proved that the public GET surface does not distinguish each
unowned player's `FREE_AGENT` versus `WAIVERS` state or guarantee complete
competing-claim visibility. No real player was evaluated; no FantasyPros
request or Sleeper write occurred. The 14-test WA-002 suite and 322-test
repository suite pass. Evidence is recorded in
`docs/COMPLETED_WAIVER_ASSISTANT_WA_002.md`.

## WA-003 — Entered add/drop evaluator (complete)

- Extract feature-neutral weekly projection, lineup, depth, and single-roster
  impact calculations from Trade with regression tests.
- Add `waiver evaluate --add [--drop]` for one skill player.
- Support an open slot and complete legal automatic drop enumeration.
- Preserve selected, market, raw-projection, weekly-use, depth, and risk views.
- Save deterministic evidence; do not apply an uncalibrated final label.

Stop: tested entered evaluator and replayable evidence with no final decision
label; WA-004 requires a new active milestone.

Completed September 9, 2026. Feature-neutral in-season calculations now serve
both Waiver and Trade. The evaluator handles an open slot, a named legal drop,
or complete proved-legal skill-player drop enumeration and saves separate
value, weekly lineup, depth, bye/playoff, risk, waiver-context, exclusion,
alternative, uncertainty, and provenance views. The focused 64-test
Waiver/Trade regression set and repository-root 338-test suite pass. No live
Sleeper or FantasyPros request was made, no write occurred, and no real player
was evaluated. Evidence is recorded in
`docs/COMPLETED_WAIVER_ASSISTANT_WA_003.md`.

## WA-004 — Waiver decision policy and controlled fixtures (complete)

- Define and version `config/waiver` gates for `ADD NOW`, `CLAIM`, `WATCH`, and
  `PASS`.
- Add controlled immediate-upgrade, insurance-only, and bad-drop cases.
- Hand-audit exact before/after arithmetic and reversal conditions.
- Keep waiver-wire ranking, long-term ownership value, and current-week signal
  separate.

Stop: tested, versioned decision policy with controlled-fixture arithmetic and
no live-player evaluation; WA-005 requires a new active milestone.

Completed September 9, 2026. Policy `wa-004-controlled-fixtures-v1` implements
transparent `ADD NOW`, `CLAIM`, `WATCH`, and `PASS` gates and candidate-aware
automatic drop selection. Generic controlled fixtures cover immediate upgrade,
bench insurance, and a bad-drop reversal without evaluating a real player.
The focused 97-test shared/Waiver/Trade set and repository-root 347-test suite
pass. No live provider request or Sleeper write occurred. Evidence is recorded
in `docs/COMPLETED_WAIVER_ASSISTANT_WA_004.md`.

## WA-004A — Player-agnostic scope correction (complete)

- Remove named-player coupling from requirements, controlled fixtures,
  handoff language, and future audit scope.
- Confirm production Waiver code and configuration remain player-agnostic.
- Preserve the promoted policy behavior and hash.

Completed September 9, 2026. Player names are now explicitly runtime inputs or
search results, never policy anchors. Generic controlled fixtures preserve all
WA-004 coverage, the policy hash is unchanged, the focused 97-test set and
repository-root 347-test suite pass, and no live provider request or Sleeper
write occurred. Evidence is recorded in
`docs/COMPLETED_WAIVER_ASSISTANT_WA_004A.md`.

## WA-005 — Complete skill-player search (complete)

- Search all eligible League Alpha QB/RB/WR/TE free agents against all legal user
  drops on one immutable snapshot.
- Use deterministic, coverage-safe pruning followed by exact evaluation.
- Report the best move, alternatives, omissions, bounds, and no-action option.
- Replay saved evidence and reject modified or stale inputs.

Completed September 9, 2026. `waiver search` enumerates every proved
QB/RB/WR/TE acquisition, exact-evaluates each retained player against every
legal user drop through the WA-004 policy, ranks alternatives deterministically,
and preserves the no-action comparator, omissions, candidate bounds, snapshot
and input hashes, and replay evidence. Controlled exhaustive and pruned searches
returned the same best move; the pruning proof retained one exact affirmative
candidate and safely bounded three lower candidates. The focused 47-test Waiver
set and repository-root 355-test suite pass. No live provider request or Sleeper
write occurred. Evidence is recorded in
`docs/COMPLETED_WAIVER_ASSISTANT_WA_005.md`.

## WA-006 — Fresh League Alpha waiver audit (complete)

- Refresh complete Sleeper and approved FantasyPros inputs within budget.
- Confirm authoritative current non-ownership and supported-position eligibility
  for every evaluated candidate. Exact free-agent versus waivers classification
  and observed pending claims are informational and do not block evaluation.
- Run entered evaluation and complete skill-player search.
- Manually cross-check the recommended move and strongest no-action case.
- Never submit a claim, add, or drop.

Completed September 9, 2026. The fresh read-only audit reconciled all 10
rosters, exactly evaluated 42 fully evidenced unrostered skill players, and
independently confirmed the `NO ACTION` result. Evidence and validation are in
`docs/COMPLETED_WAIVER_ASSISTANT_WA_006.md`. Later fresh league audits are a
recurring read-only operation and do not reopen this development task.

## WA-007 — League Beta league validation and normal workflow support

Status: complete September 12, 2026

Goal: make the existing read-only Waiver Assistant fully functional for League Beta
without transferring League Alpha calibration. Use League Beta's current Sleeper
scoring, roster, waiver evidence, and controlled League Beta fixtures to promote a
separately versioned decision policy, then expose `refresh`, `evaluate`, and
`search` through the normal CLI.

Requirements/design references:

- Requirements sections 2, 5, 6, and 8.
- Design sections Data flow, Initial interfaces, and Fail-closed boundaries.

Acceptance:

- League Beta and League Alpha each resolve their own explicit Waiver policy; a policy
  for one league cannot be applied to the other.
- The three normal Waiver CLI commands accept both configured league keys and
  default to the matching league policy.
- Controlled League Beta fixtures cover an immediate lineup upgrade, bench/depth
  insurance, and a negative required-drop transformation before promotion.
- A fresh League Beta search uses League Beta-only league/scoring/roster evidence,
  produces a policy-qualified label, preserves omissions and uncertainty, and
  performs no Sleeper write.
- Existing League Alpha evidence behavior and all other product tracks remain
  unchanged; focused and repository-root tests pass.

## Later extensions

- Ranked contingency claim queues.
- FAAB bid and waiver-priority opportunity-cost calibration.

## WA-008 — Kicker and DST streaming policy (complete)

Goal: include K and DST in entered evaluation and complete search without
transferring skill-player ownership calibration. K and ordinary DST decisions
use authoritative current-week rank and league-scored projection as the primary
signal; a DST with authoritative rest-of-season position rank 1-3 may use the
separate elite-defense path.

Acceptance:

- Snapshot, entered evaluation, search, and the live-input builder cover
  QB/RB/WR/TE/K/DST while preserving exact position and evidence omissions.
- Automatic K/DST replacements drop only the same position; skill-player
  automatic drops remain limited to skill players.
- K and ordinary DST affirmative decisions require a configured current-week
  lineup gain. Only a rest-of-season DST rank at or above the configured elite
  cutoff can use the elite exception, and its rank horizon is explicit.
- Search ordering prioritizes the current-week delta for K/DST, with the elite
  DST exception explicit and deterministic; skill-player ordering is unchanged.
- Each league resolves its own separately versioned WA-008 thresholds.
- Controlled fixtures cover a kicker stream, an ordinary DST stream, an elite
  DST exception, a non-elite bad matchup, missing rank evidence, and same-position
  drop enforcement. Run the complete repository test suite; no Sleeper write.

Completed September 13, 2026. Snapshot, evaluation, search, formatting, and the
live-input builder now cover K/DST. Each league has a separately hashed WA-008
policy: ordinary K/DST adds require a `+1.0` current-week lineup gain and use a
`4.0x` current-week priority; an authoritative ROS DST rank 1-3 may tolerate a
current-week loss up to `2.0` only with nonnegative remaining-horizon lineup
impact. Special-team swaps are same-position, incomplete weekly ranks are
reported, and search pruning is disabled when K/DST require exact evaluation.
The 374-test repository suite, compilation, and diff checks pass. No live
provider request or Sleeper write occurred. Evidence is in
`docs/COMPLETED_WAIVER_ASSISTANT_WA_008.md`.

## WA-009 — Replacement-aware bench-slot holding cost (complete)

Depends on: WA-008

Goal: stop treating the full-season points of a held backup as free value when
a comparable player can be acquired only when needed. For one-QB rosters,
compare a backup quarterback's incremental starts with a league-specific
streaming baseline and charge the opportunity cost of occupying a bench slot.

Acceptance:

- Build the streaming baseline from the current league's unrostered,
  authoritative, position-matched pool. Preserve the exact candidate set and
  test conservative availability stress; do not assume one named player will
  remain available for months.
- Separate required bye coverage, injury insurance, and discretionary weekly
  starts. Report how much value comes from each, including the number of weeks
  a held player is expected to remain unused.
- Do not count small perfect-foresight start/sit edges as certain value. Apply a
  configured decision margin or uncertainty treatment before crediting close
  projected starter changes.
- Continue reporting raw league-scored projection, but do not use unnormalized
  QB-versus-RB point totals as an affirmative cross-position gate. Use
  position-relative replacement value for cross-position ownership decisions.
- Emit explicit `streaming_replacement_value`, `holding_period`,
  `bench_slot_opportunity_cost`, and `net_hold_value` evidence.
- Controlled fixtures cover a one-bye-week QB stash with comparable streamers,
  a materially superior backup, scarce replacement supply, and a multi-QB
  starting format. In the comparable-streamer one-QB fixture, sacrificing a
  useful RB bench option cannot receive an unqualified affirmative label.

Completed September 13, 2026. One-QB backup evaluations now use a
league-local, stressed streaming pool; separate required bye, discretionary,
and injury-insurance evidence; suppress sub-margin start/sit edges; and charge
position-relative bench opportunity cost. The evidence contract exposes the
exact pool, omissions, holding period, unused weeks, and net hold value. The
381-test repository suite passes. No live provider request or Sleeper write
occurred. Evidence is in `docs/COMPLETED_WAIVER_ASSISTANT_WA_009.md`.

## WA-010 — Contingent-upside bench option value (complete)

Depends on: WA-009

Goal: value bench players for both standalone contribution and their
counterfactual role expansion when a clearly identified teammate becomes
unavailable. This protects high-upside RB reserves without inventing an injury
probability or allowing speculative upside to overwhelm current evidence.

Acceptance:

- Preserve standalone projection/rank value separately from a named,
  evidence-backed contingency scenario; never blend an invented injury
  probability into expected points.
- Require current, authoritative team/role evidence for any teammate dependency
  or handcuff relationship. Missing, ambiguous, or stale relationships fail
  closed and remain visible.
- Recompute league-scored weekly lineup, depth, and replacement exposure under
  the contingency rather than applying a generic handcuff bonus.
- Add a policy-visible protected-upside state for a bench player who has both
  useful standalone value and a material scenario ceiling. Dropping such a
  player requires the acquisition to clear an explicit incremental-value gate.
- Controlled fixtures distinguish a Corum-like standalone-plus-contingency RB,
  a low-standalone pure handcuff, an ambiguous committee, and an acquisition
  whose upside legitimately exceeds the protected bench option.
- Keep scenario magnitude, evidence, and strongest uncertainty in deterministic
  output. Do not hard-code a real player's name or transfer one league's result
  to the other.

Completed September 13, 2026. Evaluation-input schema v2 now preserves named,
time-bounded role evidence and league-scored contingency projections separately
from standalone value. Evaluation evidence schema v4 recomputes weekly lineup,
depth, replacement exposure, and option ceilings. League-specific WA-010
policies expose protected add/drop states and require an explicit incremental
option-value gate before a protected bench player can be dropped. Controlled
fixtures cover standalone-plus-contingency value, a low-standalone pure
handcuff, an ambiguous committee, stale evidence, and a superior acquisition.
Search becomes exact whenever contingency inputs are present. The focused
59-test Waiver suite and repository-root 387-test suite pass. No live provider
request or Sleeper write occurred. Evidence is recorded in
`docs/COMPLETED_WAIVER_ASSISTANT_WA_010.md`.

## WA-011 — Combined skill-player recalibration and live promotion (complete)

Depends on: WA-009 and WA-010

Goal: integrate replacement-aware holding cost and contingent-upside value,
then separately recalibrate and promote the League Alpha and League Beta skill-player
policies from controlled fixtures plus league-specific live hand audits.

Acceptance:

- Version the evaluation and search evidence contracts so every affirmative
  skill-player move exposes normalized ownership value, holding cost, streaming
  baseline, credited starter weeks, and contingent-upside scenarios.
- Re-run exhaustive-versus-pruned equivalence tests after the ranking basis
  changes; pruning may not hide the best affirmative move or a required
  no-action proof.
- Use the Love-for-White League Beta case as a required audit: if comparable streaming
  QBs remain available in a one-QB league, a one-bye-week hold must resolve to
  `WATCH` or `PASS`, absent separately proved insurance value.
- Use the Corum/Kyren League Beta relationship as a required audit of the generic
  contingent-upside model: Corum must not be selected as a routine low-value
  drop when fresh evidence proves standalone and material contingency value.
- Treat the named audits as validation cases only, never player-specific policy
  anchors. Repeat calibration independently for both leagues.
- Run fresh read-only searches for both leagues, hand-audit every promoted move,
  replay evidence, run the repository test suite, and confirm no Sleeper write.

Completed September 13, 2026. Evaluation-input schema v3, evaluation evidence
schema v5, and search schema v2 expose the combined skill-player contract.
League-local controlled fixtures preserve exhaustive/pruned best-move and
no-action equivalence. Fresh read-only searches selected NO ACTION in both
leagues; League Beta's Love-for-White result is WATCH, while Corum was owned by a
different live roster and the generic Corum/Kyren protection passed its
controlled League Beta audit. Both evidence artifacts replayed by hash, the 393-test
suite passed, and no Sleeper write occurred. Evidence is recorded in
`docs/COMPLETED_WAIVER_ASSISTANT_WA_011.md`.

## Emerging-upside implementation sequence

The following planned tasks add an early-signal acquisition path without
weakening the normal ownership-value path. The governing comparison is always
the complete roster after acting now versus the complete roster after retaining
the proposed drop. A large fantasy-point result alone is not evidence of a
durable role, Waiver Wire rankings are authoritative only as acquisition
signals, and article prose must not be converted into an invented rank or hit
probability. Scenario calculations and calibration use ordinary deterministic
code. Every policy threshold and empirical result remains league-specific.

These rows do not authorize implementation or live provider access. When a row
is activated, load Waiver requirements sections 4-6 and Waiver design sections
Architecture, Data flow, and Fail-closed boundaries in addition to the context
required by `.codex/context/STEERING.md`.

## WA-012 — Genuine FantasyPros Waiver Wire evidence (complete)

Depends on: WA-011

Goal: replace the mislabeled weekly-rank proxy with separately normalized,
freshness-checked FantasyPros Waiver Wire consensus and selected-expert
evidence, without changing recommendation policy.

Implementation:

- Extend the FantasyPros adapter with a canonical `WAIVER` ranking horizon that
  requests the documented `type=WW` capability. Normalize provider labels such
  as `WW` and `Waiver Wire` to that canonical horizon while preserving the raw
  provider label in provenance.
- Capability-probe market consensus and configured selected-expert requests
  under the existing request budget. Fail visibly on entitlement failure,
  fallback-to-another-horizon responses, missing players, stale updates, or an
  unsupported position/scoring combination. Never print or copy the API key.
- Preserve overall rank, positional rank, best/worst or dispersion fields when
  returned, contributor identities, scoring, week, capture time, provider
  update time, endpoint parameters, and completeness status.
- Add Waiver-owned configuration for trusted expert IDs and any minimum
  freshness requirement. Do not inherit a Draft or Trade expert policy, and do
  not assume that an expert valid for ROS is valid for the Waiver horizon.
- Keep `weekly_position_rank`, `rest_of_season_position_rank`, market Waiver
  rank, and selected-expert Waiver ranks as distinct typed fields. Remove the
  current live-input assignment that places the weekly positional rank in
  `waiver_wire_rank`.
- Store trusted-expert observations independently rather than averaging them
  into consensus. Preserve disagreement because early disagreement is decision
  evidence, not a data error.

Acceptance:

- Controlled provider fixtures prove successful market and single-expert WW
  responses, canonical-label normalization, rank dispersion, freshness, and
  provenance.
- Fallback, stale, unauthorized, partial, unmatched, and ambiguous responses
  remain visible and cannot masquerade as complete WW coverage.
- A regression test proves that a weekly positional rank can no longer populate
  a Waiver Wire field.
- Evaluation-input and evidence schemas are versioned, hash-replay remains
  deterministic, and reports label WW evidence as acquisition-only.
- Existing ROS, weekly, K/DST, one-QB, contingency, search-pruning, and no-action
  behavior is unchanged. No decision threshold is changed in this task.

Completed September 14, 2026. FantasyPros `type=WW` is normalized to the
canonical `WAIVER` horizon with the raw provider label, market dispersion,
contributors, selected-expert observations, freshness, and provenance retained.
Evaluation-input schema v4, evaluation evidence schema v6, and search schema v3
carry acquisition-only WW evidence without changing policy. Legacy ambiguous
`waiver_wire_rank` values are ignored, and the live builder no longer copies a
weekly rank into that field. Both league audits retained their prior no-action
outcomes, shared the identical provider cache, and replayed by hash. The
404-test repository suite passes. Detailed evidence and known live coverage
limits are recorded in `docs/COMPLETED_WAIVER_ASSISTANT_WA_012.md`.

## WA-013 — Volume, role change, and trusted-editorial evidence (complete)

Depends on: WA-012 only for final evidence-bundle integration; the
provider-neutral role schema may be developed independently.

Goal: distinguish sustainable opportunity growth from touchdown, long-play, or
small-sample scoring noise using auditable role and volume observations.

Implementation:

- Define a provider-neutral, versioned `EmergenceEvidence` contract with player,
  team, position, game/week, source, capture time, source update time, identity
  resolution, coverage, and warnings. Do not assume FantasyPros supplies every
  required usage metric.
- Represent available opportunity measures without silently substituting one
  for another: offensive snap share, route participation, target share,
  targets, carries, total opportunities, goal-line work, red-zone work,
  two-minute usage, and designed touches. Preserve both numerator and team
  denominator where a share is reported.
- Compare the latest game and a short rolling window with the player's earlier
  baseline. Record sample sizes, inactive/bye games, overtime, teammate injury
  context, and material depth-chart or coaching news so a forced one-week role
  is not presented as an unconditional promotion.
- Decompose the triggering fantasy result into opportunity-driven and
  efficiency/variance-driven components, including touchdowns and long plays.
  The model may classify a signal as `ROLE_EXPANSION`, `SUPPORTED_TREND`,
  `EFFICIENCY_ONLY`, `INJURY_CONDITIONAL`, `CONFLICTING`, or `UNKNOWN`; an LLM
  may explain the evidence but may not assign or alter the classification.
- Support provenance-only trusted-editorial observations containing author,
  source URL or artifact ID, publication and capture times, player identity,
  and the author's explicit language such as `priority add`, `stash`, stated
  rank/tier, role claim, or FAAB range. Preserve quotations only within source
  and license limits. Do not infer a numeric rank, tier, probability, or role
  claim that the expert did not state.
- Make unavailable metrics, unmatched identities, contradictory sources, and
  stale role/news evidence first-class output. Do not silently drop a player
  because one metric or article is unavailable.

Acceptance:

- Controlled fixtures distinguish a low-volume multi-touchdown game from a
  high-participation role expansion, a one-week injury fill-in from a durable
  promotion, and a multi-week opportunity trend from a single observation.
- Equivalent raw observations produce identical classifications and hashes;
  explanatory text cannot affect the classification.
- Missing team denominators, incomplete games, conflicting reports, stale
  evidence, and ambiguous identity resolution fail closed for an affirmative
  emerging-upside path while remaining visible in reports.
- Explicit expert ranks remain ranks, explicit prose labels remain prose labels,
  and neither is treated as a ROS value or league-scored projection.
- Provider and schema tests contain no real licensed player payloads or secrets,
  and all retrieval remains read-only.

## WA-014 — Symmetric emerging-upside scenario valuation (complete)

Depends on: WA-013

Goal: quantify the upside, ordinary outcome, and miss cost of an early waiver
bet while charging the full opportunity cost and retained upside of the player
who must be dropped.

Implementation:

- Add `MISS`, `USEFUL_ROLE`, and `BREAKOUT` scenario inputs for an emerging
  acquisition. Scenario opportunity assumptions must derive from the normalized
  volume/role evidence and documented, versioned football priors; scenario
  projections must be calculated with ordinary code under the league's actual
  Sleeper scoring.
- Keep scenario construction separate from authoritative ROS and weekly
  projections. Preserve the central projection unchanged and label every
  scenario assumption, transformation, source, horizon, and uncertainty.
- Re-evaluate the complete legal roster in every scenario with the existing
  weekly lineup optimizer. Preserve starter weeks, current-week effect, weighted
  remaining-week effect, depth, byes, playoffs, and replacement exposure.
- Evaluate the proposed drop symmetrically. Include its central value, miss
  protection, named-teammate contingency, and any separately proved emergence
  scenario. Never call a bench player worthless because it lacks an immediate
  starter delta.
- Compare `ACT_NOW` with `RETAIN_DROP`. Expose breakout gain, useful-role gain,
  miss-case loss, acquisition option ceiling, retained option ceiling, and
  incremental option value. The no-action roster is an explicit alternative.
- Calculate and report a two-state break-even hit rate when the inputs permit:
  `miss_loss / (breakout_gain + miss_loss)`. For three-state output, expose the
  expected-value equation and sensitivity table without supplying an
  uncalibrated state probability.
- Keep availability decay, claim-success probability, FAAB price, and waiver
  priority cost outside expected value until each has its own league-specific
  calibration. Known budget and priority context may still be displayed.
- Preserve the named-teammate contingency path as a distinct scenario subtype;
  do not replace or silently broaden it into general emergence.

Acceptance:

- Controlled fixtures cover high-upside/cheap-drop, high-upside/protected-drop,
  low-volume box-score spike, useful-but-not-breakout, equal option ceilings,
  no-drop roster capacity, and no-action-best cases.
- The break-even formula handles zero, negative, and dominated gains without
  division errors or misleading percentages and includes a human-readable
  explanation of what belief would justify the move.
- Property and regression tests prove add/drop symmetry, monotonicity of the
  break-even threshold as miss loss rises, actual-league scoring, and unchanged
  central projections.
- Evidence schemas version all scenario inputs and outputs, and hash-verified
  offline replay reproduces the same roster transformations and values.

## WA-015 — Emerging-upside policy, search, and presentation

Completed September 15, 2026. Both live league audits were read-only. Saved
successful searches and fresh inputs verify by hash; a fresh incomplete search
failed closed on a genuine Week 2 projection omission and its machine report
matches the saved failure. No affirmative move or Sleeper write occurred.
Partial Waiver Wire coverage and absent role evidence remain explicit; no
policy was promoted. The full 505-test suite passes. See
docs/COMPLETED_WAIVER_ASSISTANT_WA_015.md.

Depends on: WA-012, WA-013, and WA-014

Goal: allow a bounded early acquisition when leading Waiver and role evidence
supports it, without turning uncertainty into a blanket exception to normal
ownership, projection, drop-protection, or safety gates.

Implementation:

- Add `EMERGING_UPSIDE` as a Waiver decision path beneath the existing
  `ADD NOW`, `CLAIM`, `ACQUIRE`, `WATCH`, and `PASS` labels. Do not create a
  Sleeper write path.
- Leave the ordinary ownership-value path unchanged. An emerging-upside
  candidate may tolerate only explicitly bounded negative ROS/market/projection
  deltas; it may not bypass evidence completeness, activity, legality, current
  roster state, excessive miss loss, replacement exposure, same-offense risk,
  or protected-drop gates.
- Require fresh, genuine WW evidence plus material role evidence for an
  affirmative emerging-upside result. Define separately whether market WW
  consensus, selected trusted experts, or both can satisfy support. Never
  silently blend the two, and expose expert disagreement and staleness.
- Add league-local thresholds for maximum miss-case loss, maximum allowed
  central-value deficits, minimum acquisition-over-retained option value,
  maximum break-even hit rate, evidence freshness, and minimum role-signal
  strength. Calibrate `league_alpha` and `league_beta` independently.
- If the upside is plausible but a required signal is incomplete, stale,
  conflicting, or near threshold, select `WATCH`. A fantasy-point spike without
  opportunity growth cannot independently produce an affirmative label.
- Rank search results by decision tier and then by a documented combination of
  bounded downside and incremental option value. Update pruning so every
  potentially affirmative or protected-drop emerging case receives exact
  evaluation; prove exhaustive-versus-pruned and no-action equivalence.
- Report the role evidence, true WW ranks, trusted-expert support/disagreement,
  all three roster outcomes, drop option value, break-even belief threshold,
  strongest reason the recommendation could be wrong, and concrete reversal
  conditions.

Acceptance:

- League-specific controlled fixtures prove an affirmative cheap-drop breakout
  bet, a `WATCH` on compelling but incomplete evidence, a `PASS` on a
  touchdown-only spike, and a `PASS` when the retained drop has comparable or
  superior option value.
- No selected expert or threshold from one league can affect the other league;
  cross-league policy use fails closed.
- Existing immediate, insurance, QB-hold, named-contingency, K/DST, and ordinary
  negative cases retain their expected results unless a reviewed fixture
  documents an intentional change.
- Both live league audits are read-only, every affirmative move is hand-audited,
  all inputs and reports replay by hash, the complete repository suite passes,
  and the handoff confirms that no Sleeper write occurred.

## WA-016 — Walk-forward outcome capture and empirical calibration

Status: long-running research; not active and not a blocker for the current
public alpha. Required only before a future evidence-based probability or
policy-threshold promotion.

Depends on: WA-015 evidence contracts. This task may collect shadow evidence
before WA-015 policy promotion, but it may not change labels without a later
active milestone.

Goal: learn how often identified role changes persist and how costly early
adds, misses, waits, and dropped-player breakouts are, without look-ahead bias
or cross-league transfer.

Implementation:

- Save immutable decision-time candidate, roster, availability, WW, expert,
  role, projection, scenario, and no-action snapshots before outcomes are known.
- Define outcome windows such as one, two, and four weeks. Measure role
  persistence with opportunity metrics as well as fantasy production so a
  touchdown does not retroactively turn a weak process into a successful role
  prediction.
- Record whether the candidate remained available at the next decision point,
  whether the proposed drop was reacquirable, subsequent starts, league-scored
  points, replacement value, and realized regret for `ACT_NOW` and
  `RETAIN_DROP`. Do not infer hidden competing claims or claim success.
- Run walk-forward comparisons against at least ROS-only, WW-only, and combined
  role-plus-WW baselines. Report coverage, sample size, hit rate by signal class,
  calibration error where probabilities exist, average roster utility, severe
  miss rate, and dropped-player regret.
- Estimate state probabilities only after a documented minimum sample and
  stability gate. Until then, continue reporting the break-even belief threshold
  and sensitivity analysis rather than an asserted probability.
- Calibrate each league independently. If a pooled positional prior is ever
  proposed, keep it separate from league policy and require evidence that the
  league-specific conversion remains valid.

Acceptance:

- Tests prove decision-time snapshots cannot read future observations and that
  reruns cannot mutate the original evidence bundle.
- Reports include unmatched, unavailable, partial, and censored outcomes rather
  than silently retaining only evaluable or successful cases.
- Synthetic walk-forward fixtures recover known hit rates and expose deliberate
  look-ahead leakage.
- No probability or policy promotion occurs when sample or stability gates are
  unmet; the evidence says why and retains the prior policy version.
- Any later threshold promotion requires a separate active milestone, versioned
  league policies, controlled regressions, live read-only hand audits, offline
  replay, and a full-suite pass.

## WA-017 — Current-week inactive projection omission resilience

Status: complete September 15, 2026

Goal: keep read-only Waiver evaluation and search usable when a refreshed
Sleeper snapshot verifies that a roster player is inactive for the current
week and FantasyPros omits that player's current-week projection.

Acceptance:

- Reconcile only a zero-valued, source-omission current-week row against the
  same league's fresh Sleeper IR/PUP/SUSP/OUT status, with explicit provenance.
- Do not infer future-week inactivity, invent rankings, or accept other missing
  projection coverage; healthy or stale-status omissions still fail closed.
- Entered evaluation and complete search use the reconciled projection while
  preserving the input-bundle and snapshot evidence hashes.
- Focused regression tests and the repository-root suite pass; no provider
  request or Sleeper write is part of implementation verification.

## WA-018 — Action-first human Waiver search report

Status: complete September 16, 2026

Goal: replace the audit-log-style terminal output with a short, understandable
decision report that tells a fantasy manager what to do, why, and what deserves
attention next.

Acceptance:

- Lead with the recommended action or `NO ACTION`, followed by the best move,
  the decisive reason, and any current-week lineup emergency.
- Give defense/kicker streams and notable skill-player alternatives their own
  compact sections instead of burying them in generic warnings.
- Translate internal gates, pruning, and coverage states into plain English;
  keep hashes, policy versions, counts, and detailed reversal conditions in a
  collapsed/technical view or machine JSON rather than the primary report.
- Avoid repeating the same limitation in the frame and details. Preserve full
  evidence in `--json` and saved artifacts.
- Snapshot tests cover ordinary, degraded, no-action, affirmative, narrow
  terminal, redirected, and `--json` output.

## WA-019 — Reliable FantasyPros-to-Sleeper DST identity reconciliation

Status: complete September 16, 2026

Goal: ensure available team defenses with authoritative weekly and ROS ranks
are evaluated instead of being discarded as `NO_AUTHORITATIVE_VALUE`.

Observed case: Week 2 FantasyPros ranked Tampa Bay DST2 and San Francisco DST3
while the rostered Denver defense was DST11, but Tampa Bay and San Francisco
were omitted because FantasyPros numeric DST IDs did not map to Sleeper's
team-abbreviation IDs.

Acceptance:

- Reconcile DST identities by a unique, normalized NFL team abbreviation when
  shared player IDs are unavailable; do not extend this fallback to individual
  players or accept ambiguous/mismatched teams.
- Carry mapped DST weekly ranks, ROS ranks, league-scored projections, current
  ownership, and same-position drop legality into Waiver search.
- Evaluate available ordinary DST streams exactly before skill-player pruning
  and report the current-week points/rank comparison against the rostered DST.
- Controlled fixtures prove the Tampa Bay/San Francisco-style case, ambiguous
  identity failure, owned-defense exclusion, and same-position replacement.
- No test or live run may submit an add, drop, claim, or lineup change.

## WA-020 — Explain notable omitted and pruned Waiver candidates

Status: complete, including RB60 coverage amendment, September 16, 2026

Goal: make promising players visible even when incomplete evidence or policy
gates prevent a recommendation, without weakening fail-closed behavior.

Observed cases: Kaelon Black had strong Waiver Wire placement and a reported
14-carry, 65-yard role signal but lacked authoritative value coverage; Jakobi
Meyers was available and ranked but was silently pruned because no legal drop
passed both ownership-value floors.

Acceptance:

- Add a concise `Worth a look` section containing the most relevant omitted or
  pruned candidates, their position/team, available weekly and ROS comparison,
  and one plain-English reason they were not recommended.
- Surface high Waiver Wire rank, authoritative roster-relative weekly/ROS rank,
  or validated role/volume evidence; do not elevate a player from anecdotes or
  incomplete evidence alone.
- Distinguish `missing evidence`, `considered but below threshold`, `not
  available`, and `not a legal roster move` rather than folding them into a
  thousands-row omission count.
- Preserve complete omissions and pruning proofs in saved evidence and JSON;
  cap the human shortlist deterministically.
- Player-agnostic fixtures cover the Kaelon Black-style missing-value case and
  Jakobi Meyers-style ranked-but-pruned case, including roster comparisons and
  unchanged no-action safety.
- Amendment: the shared complete RB valuation universe extends through RB60 so
  ordinary rank movement around RB50 does not turn a viable player into an
  incomplete visibility-only candidate.

## WA-021 — Prevent stale Draft anchors from vetoing fresh Waiver dominance

Status: complete September 16, 2026

Goal: recommend a legal same-position add/drop when complete fresh evidence
shows that the add strictly beats the drop in the current week, ROS consensus,
and league-scored remaining projection, even if the shared value board has
temporarily retained an early-season Draft anchor because selected ROS expert
coverage is incomplete.

Implementation:

- Preserve and expose the horizon actually used by each ownership-value input;
  never label a Draft-anchor value as current ROS evidence.
- Add a player-agnostic strict-dominance path requiring the same position, a
  better current-week rank, a better ROS rank, a non-negative remaining
  projection delta, complete inputs, current activity, legal drop, and all
  existing lineup, depth, concentration, and downside safety gates.
- Allow that proved dominance to satisfy the stale selected/market ownership
  gates and the bench-support gate only when both ownership values use the same
  non-ROS horizon. Preserve the old gates when current ROS values are present.
- Protect every potentially dominant candidate from ownership-floor pruning so
  pruned and exhaustive search remain equivalent.
- Use a Waiver-specific two-hour ranking and expert cache window while
  preserving shared Trade defaults and the FantasyPros request budget.

Acceptance:

- A controlled Monangai/White-style fixture recommends the add when fresh
  weekly rank, ROS ECR, and remaining projection all dominate a same-position
  legal drop but Draft-anchor values disagree.
- Losing any dominance leg, changing position, using current ROS ownership
  values, incomplete evidence, inactive status, or a protected/illegal drop
  does not receive the exception.
- Search pruning evaluates the dominant candidate exactly and matches
  exhaustive search.
- Existing Waiver fixtures, Trade behavior, and read-only boundaries remain
  unchanged; the full repository suite passes with no Sleeper write.

## WA-022 — Single-command Waiver readiness and report reliability

Status: complete September 18, 2026

Goal: make `waiver search LEAGUE` the ordinary end-user workflow by preparing
fetchable and derived prerequisites automatically, while preserving explicit
league-local calibration and fail-closed recommendation behavior.

Acceptance:

- When `--inputs` is omitted, `waiver search LEAGUE` refreshes stale or missing
  provider evidence, builds the league-local Waiver input bundle, and runs the
  report. Explicit `--inputs` and saved-snapshot replay remain supported.
- Migrate this repository's legacy league-matched Waiver policies to the
  season-aware metadata contract without replacing calibrated thresholds;
  retain recoverable backups and never transfer policy between leagues.
- Persist successfully parsed shared historical expert accuracy before current
  expert selection, so a limited/empty current-expert response is resumable
  and is reported as the actual provider-access failure rather than a missing
  CSV.
- Automatic preparation remains read-only with respect to Sleeper, respects
  FantasyPros request budgets and freshness, and never turns incomplete
  evidence into a recommendation.
- Focused tests cover automatic preparation, explicit-input compatibility,
  legacy-policy migration, empty expert responses, resumability, and human/JSON
  failures. The full repository suite and Ruff pass.

## WA-023 — Availability-aware DST streaming valuation

Status: complete September 18, 2026

Goal: make DST waiver advice optimize the near-term decisions a manager can
actually take instead of treating a defense as a forced season-long hold.

Acceptance:

- Score DST add/drop decisions over Weeks 0–3 with league-local projected
  points and explicit horizon weights `1.0, 0.5, 0.25, 0.125`.
- Compare the target with the incumbent and legal, currently acquirable DST
  streaming alternatives; do not credit a target for beating an implausible
  season-long hold baseline.
- Require an immediate DST acquisition to clear the weighted streaming
  baseline. A future-only advantage is `WATCH`/stash context, not an
  affirmative one-for-one DST swap.
- Restrict replacement-floor players to eligibility for the uncovered lineup
  slots so a QB or other position cannot substitute for a missing DST.
- Preserve league-local scoring, evidence completeness, read-only Sleeper
  behavior, deterministic JSON proofs, and existing non-DST Waiver behavior.
- Focused regression tests cover the Denver/Tampa Bay and Denver/San Francisco
  shapes, streaming alternatives, and same-position replacement floors. The
  full repository suite and Ruff pass, and both configured leagues are
  validated read-only before publication.
