# RosterTheory durable context

Last consolidated: September 9, 2026 (America/Los_Angeles)

Load only the relevant section of this file for product scope, league
assumptions, durable model decisions, or shared architecture. Do not load it by
default; current work belongs in the routed `.codex/context/status/` file.

## Goal and boundaries

RosterTheory is a small, local, modular, read-only fantasy-football
decision-support tool. Its current product tracks are:

1. **Draft Assistant:** completed support for the August 30 League Alpha draft and
   active preparation for the September 7 League Beta draft, using league-scored
   rankings, ADP/league-informed simulation, and live VBD/MVOR recommendations.
2. **Trade Assistant:** Phase 7 complete and ready for initial testing of
   in-season value, selected-expert versus market disagreement, lineup/depth
   impact, scenario risk, counterparty incentive, and bounded league-wide
   package discovery through four-player sides.
3. **Waiver Assistant:** active development for player-agnostic, read-only
   add/drop decisions using each configured league's rules.
4. **Future assistants:** start/sit remains a reserved extension.

`.codex/context/STEERING.md` owns product-track routing. Build one implementation
milestone at a time. Planning in another track may proceed without changing
active behavior. Keep the tool local and small, and never submit a Sleeper
transaction.

## Leagues

- `league_alpha`: completed 10-team Half-PPR draft from slot 4, with one
  WR/RB flex, K and DEF, and linked 2025 history. The user's team is
  `team_4`; Sleeper user `synthetic_owner`, ID
  `synthetic-user-id`, owns 2026 roster 2. Its calibration is archived and
  must not be treated as League Beta input.
- `league_beta`: 12 teams, live Half-PPR (`rec=0.5`), two WR/RB/TE flexes, five
  bench spots, K and DEF, 15 rounds, and a 60-second snake clock. synthetic_owner owns
  roster 11 and Sleeper's September 2 `draft_order` assigns that user ID to
  slot 1. The identified 2025 League Beta league was an
  8-team/120-pick room and is ineligible for the required 12-team/180-pick
  history gate. The scheduled start is September 7 at 5:00 PM Pacific.

The discovered per-user league configuration is canonical for IDs. Refresh Sleeper snapshots before trusting scoring, draft status, order, or slot.
For arbitrary Sleeper mocks, resolve the user's claimed slot with `--user-id synthetic-user-id`; do not carry a numeric slot over from another room.

## Data sources

- Sleeper: public read-only API; snapshots in ignored `data/cache/`.
- FantasyPros: HOF Premium API via ignored `.env`; 1 request/second, 500/day.
- Manual FantasyPros CSV import is fallback only.

For the Draft Assistant, the current historical selection source is
`data/manual/fantasypros/expert_accuracy_annual_2021_2025.csv`, using field-normalized annual
preseason draft accuracy and fixed recency weights of 8%/15%/21%/26%/30%.
Weekly accuracy is intentionally excluded from that preseason pool. One-year
skill analysts are ineligible; two-year analysts require consecutive top-10
finishes. The retained older master files are audit/fallback history, not the
live selection input.

The Trade Assistant selects its separate expert pool from multi-year weekly
in-season accuracy because FantasyPros does not provide annual ROS expert-
accuracy rankings. Before true ROS ranks publish, selected weekly rankings,
full weekly ECR, and weekly projections are explicitly labeled
`WEEKLY-PROXY`. Once ROS ranks exist, selected and market boards switch to ROS
together. Sleeper is preferred whenever it supplies the needed league or player
data; paid FantasyPros fills documented gaps. Provider, scoring, horizon,
timestamp, and expert/market provenance remain visible.

## Draft Assistant ranking model

- Skills membership uses coverage-adjusted overall accuracy; K and DST use their category accuracy.
- Final 2026 DST selection uses the user's weeks 1-3 streaming order in
  `config/defense_draft_order_2026.csv` for both leagues. Preserve the DST
  specialist consensus as audit data and as fallback if the ten preferred
  defenses are gone. This preference does not change DST timing; the existing
  K-first rule is preempted only by user-ranked DST1-DST3.
- Each skill pool contains 10 recently updated experts. Sean Koerner is the
  approved solo anchor at a four-ordinary-expert equivalent; the other nine are
  split into cohorts of five and four. K and DST retain independent 20-expert
  pools split into four cohorts of five.
- FantasyPros averages each cohort; cohort weights derive from summed squared
  historical scores, with Koerner's configured multiplier making the solo
  cohort exactly four ordinary experts' mass. Skill rankings require a
  provable update within 14 days, with dated UI corrections stored separately
  in `data/manual/fantasypros/expert_pool_overrides_2026.csv`.
- Skill rank is 85% grouped consensus and 15% full ECR. K and DST remain 75%
  grouped consensus and 25% ECR.
- If an expert lacks a position ranking, that position's cohort weight is recalculated from actual contributors.
- FantasyPros accepts the cross-position `position=ALL` cheat sheet only when `type=DRAFT` is explicit. Skills also retain separate QB/RB/WR/TE consensus ranks.
- The selected ranking experts publish no machine-readable projection rows. Their weighted rankings are authoritative; league-scored point estimates are labeled unfiltered FantasyPros projection consensus.
- League scoring comes from Sleeper settings, not canned FantasyPros point totals.
- Cross-position expert ordering comes from the weighted selected-expert ALL Draft board. Projections and replacement-level VBD quantify league-specific roster value but may not silently replace that board.

## Draft Assistant decision model

- VBD: projected value over a league-derived replacement player.
- MVOR: VBD plus option value—primarily next-pick survival, roster needs, and league tendencies.
- ADP is acquisition cost, not player quality.
- The primary completed-roster objective uses no-bye weekly-use stress
  scenarios and credits a reserve only when he enters the legal lineup above
  projected post-draft waiver floors. No-absence, light, moderate, and heavy
  levels remain separate sensitivities rather than an asserted injury rate.
  The old bye-adjusted optimal-lineup plus usable-bench grade remains a labeled
  sensitivity only. The calibrated League Alpha pick-time reserve proxy is 20%.
  Its fast reserve term counts only the strongest same-position reserves up to
  that position's legal starter/flex coverage capacity; an additional reserve
  must displace a credited reserve to add value. This prevents a redundant
  sixth RB from receiving flat depth credit that the weekly-use evaluator does
  not realize.
- Usable reserve value is roster-specific. In League Alpha its QB/RB/WR/TE factors
  are 1/3, 1, 1, and 2/3. League Beta's two FLEX starters change them to 1/4, 1, 1,
  and 3/4. Never copy a finished-roster score or reserve calibration between
  leagues.
- Both leagues independently report live Half-PPR scoring in Sleeper.
- FantasyPros projections supply value spacing, not player identity order. Within each skill position, sort the untouched raw projection distribution and assign it in selected-expert positional-rank order. Compute VBD, VONA, replacement baselines, roster strength, and the rank-value sensitivities from that expert-ordered positional curve while retaining the raw projection separately for audit.
- Rank reconciliation fits a monotone selected-expert-`OvrRk`-to-VORP curve from those positional values, then re-monotonizes each position by selected `PosRk` and evaluates the positional curve, 50% blend, and full overall-rank channels. It does not infer expert stat lines, permit the cross-position blend to invert positional value order, or boost zero-projection players.
- Selected-expert order is authoritative: round one follows selected overall rank. A lower same-position player may lead only through an explicit acquisition-timing or two-pick path, not because FantasyPros projected that player higher.
- The promoted League Alpha primary drafts with the 50% overall-rank blend and a 0.5 positional-rank tolerance. The former one-QB/one-TE hard caps are retained as experiments but are not live. The secondary shows the unblended expert-ordered positional value curve.
- League Beta's exact-slot calibration recommends retaining the strict 50%
  rank-reconciled Half-PPR primary with the expert-ordered positional value
  curve as secondary, pending user approval for watcher use. A subsequent
  8,512-policy-draft stress phase directly tested the League Alpha primary and six
  acquisition environments; it did not merely assume that the generic
  fallback was adequate. It inherits no ten-team
  positional tolerance, elite-TE exception, QB timing conclusion, historical
  acquisition curve, or manager exclusions.
- League Beta's only larger-stress finalist was WR4-by-round-8. It improved the
  reconciled rank channels but lost in the raw expert-ordered channel under a
  synthetic QB/TE surge, including a 128-room extension. Keep WR scarcity near
  round 8 visible in live VONA/two-pick evidence; do not force WR4.
- League isolation does not imply duplicate machinery. League Beta should reuse the
  selected-expert/projection pipeline, VBD/MVOR and sequencing calculations,
  no-bye weekly-use sensitivity framework, simulation harness, read-only
  watcher, warnings, preferences, cache handling, and evidence/audit tooling.
  Recalibrate the parameters and policies whose football meaning changes with
  12 teams, two FLEX starters, five bench spots, exact draft slot, or League Beta-
  specific acquisition behavior.
- Simulation uses ordinary deterministic code; AI explains results.

## Trade Assistant valuation boundary

- `docs/TRADE_ASSISTANT_REQUIREMENTS.md` is the requirements authority and
  `docs/TRADE_ASSISTANT_DESIGN.md` owns the architecture. The one active or
  most-recent implementation contract is routed through `ACTIVE_MILESTONE.md`.
- Maintain two independent, horizon-matched identity orders: the in-season-
  accuracy-weighted selected-expert board and the market-consensus board.
- Use one league-scored consensus projection distribution, sorted within each
  position, and align its rank slots independently to each board. Thus each
  board's RB10 receives the RB10 projection value without allowing the
  projection source to reorder player identities. Preserve raw projections and
  every aligned value for audit.
- The selected-versus-market gap is an opportunity signal, not proof that a
  particular opponent follows market ECR. Evaluate an actual proposal by the
  user's expected lineup, usable depth, replacement exposure, risk and
  correlation, plus the counterparty's likely benefit.
- Three starters from one NFL offense increase shared-outcome exposure, but
  are not an automatic sell rule. Report expected-value and risk changes
  separately so diversification does not masquerade as a points gain.
- Draft ADP, VONA, round timing, and preseason expert weights do not determine
  ROS trade value. Trade outputs likewise do not alter draft recommendations.
- The Trade Assistant remains read-only and never submits or accepts a trade.

## Shared architecture boundary

The proposed [modular architecture](../../docs/MODULAR_ARCHITECTURE.md) and
[scope reconciliation](../../docs/MODULAR_REQUIREMENTS.md#6-reconciliation-with-existing-specifications)
refine this boundary for review. They do not activate implementation or replace
existing feature policy before approval.

Provider access, canonical identities, league scoring, projections, lineup
optimization, replacement value, risk, caching, provenance, and evidence may
be shared. Product policy and feature-specific orchestration stay in their own
modules. The design document will choose concrete package boundaries; this
context does not pre-commit to speculative paths or a framework.

The Waiver Assistant reuses feature-neutral provider, identity, scoring,
lineup, replacement, in-season valuation, risk, cache, provenance, and evidence
interfaces. It owns acquisition state, single-roster add/drop legality,
candidate generation, decision gates, and reporting. It must not import Draft
acquisition policy or Trade partner/fairness policy. Its initial validation is
League Alpha only.

## Code map

- `fantasypros.py`: API client
- `grouped_rankings.py`: current pools and grouped ranking export
- `manual_import.py`: fallback CSV import/audits
- `rankings.py`: weighting, scoring, baselines, VBD
- `sleeper.py`: read-only Sleeper data
- `draft_analysis.py`, `simulation.py`, `assistant.py`: Draft Assistant analysis
- `cli.py`: commands

This map describes the current draft-heavy implementation. Trade and shared
module boundaries belong in the reviewed Trade Assistant design rather than
being inferred from these filenames.
