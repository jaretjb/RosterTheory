# RosterTheory trade assistant requirements

Status: Approved baseline; expert-horizon policy amended September 5, 2026  
Created: September 4, 2026 (America/Los_Angeles)  
Scope: Requirements only; this document does not authorize implementation

Product-track boundaries and document precedence are defined in
`.codex/context/STEERING.md`. The proposed implementation architecture is in
`docs/TRADE_ASSISTANT_DESIGN.md`, and the planned delivery backlog is
`docs/TRADE_ASSISTANT_TASKS.md`. Those links are informational during
requirements-only work; load them only under the conditions in the steering
matrix. None of these planning documents authorizes implementation.

## 1. Purpose

RosterTheory should add a read-only trade assistant that helps a fantasy
manager improve the expected weekly strength and risk profile of an existing
team. The first supported use case is the 2026 League Alpha redraft league, where
Team 4 currently starts three Cincinnati Bengals.

The assistant must answer four different questions without collapsing them
into one trade grade:

1. Does the trade improve the user's expected points and usable depth over the
   rest of the fantasy season?
2. How does the trade change weekly downside, upside, bye-week pressure, and
   correlated exposure to one NFL offense?
3. Does the other manager receive a credible benefit under the same league
   rules, making the proposal plausibly fair?
4. Where does the selected-expert view disagree with market consensus strongly
   enough to create a buy-low or sell-high opportunity?

The assistant must not recommend diversification at any price. Three starters
from one offense are a reason to measure correlated risk, not an automatic
reason to discount all three players or force a trade. A high-value stack can
raise both expected points and weekly ceiling, and increased variance can help
an underdog. The result must therefore keep expected value, risk, and trade
fairness visible as separate dimensions.

## 2. Product boundary

### 2.1 Separate from drafting

The trade assistant is a distinct RosterTheory capability, not another draft
watcher mode.

- Its commands, reports, configuration, cached data, evidence, and tests must
  use a `trade` namespace or equally clear product boundary.
- Draft concepts such as ADP, next-pick survival, VONA, draft slot, and live
  room pace must not appear in trade recommendations unless shown only as
  historical context.
- Trade analysis begins from the current authoritative league roster and the
  remaining NFL/fantasy schedule, not from the completed draft board.
- A report must be visibly labeled `TRADE ASSISTANT` and show league, scoring,
  current NFL week, evaluation horizon, and data timestamps.
- The existing draft watcher remains read-only and unchanged. The trade
  assistant must also be read-only: it may never submit, accept, reject, or
  message a trade through Sleeper.

### 2.2 Shared platform capabilities

Separation at the product level must not produce duplicate football logic.
The trade assistant should consume reusable interfaces for:

- Sleeper league settings, users, rosters, matchups, transactions, and player
  identity;
- FantasyPros rankings, projections, expert metadata, injuries, and news;
- league-specific fantasy scoring;
- optimal legal lineup selection and replacement-level calculation;
- player identity reconciliation and data-completeness reporting; and
- provenance, caching, warnings, evidence exports, and deterministic tests.

These shared capabilities should later support waiver and start/sit assistants.
Draft-only policy rules and league-specific calibration must remain outside the
shared layer.

## 3. Users and primary workflows

The initial user is one manager evaluating trades in one Sleeper redraft
league. The assistant must support the following workflows.

### 3.1 Diagnose the current roster

The user can request a current-team diagnosis that:

- identifies the best projected legal lineup for each remaining fantasy week;
- identifies positional strength, weakness, and reserves that are unlikely to
  enter a useful lineup above waivers;
- measures bye conflicts and gaps in injury/absence coverage;
- identifies concentrations by NFL team and offense among starters and the
  full roster;
- reports expected weekly points separately from floor, ceiling, and
  concentration risk; and
- explains the smallest roster changes likely to improve the team.

For Team 4, the first report must recognize Ja'Marr Chase, Chase
Brown, and Tee Higgins as separate high-value players and as shared Bengals
exposure. It must preserve the completed-draft finding that the Week 6 bye is
coverable while newly measuring multi-week offense-wide downside.

### 3.2 Find trade targets

The user can ask for targets across the league. The assistant must:

- identify players who improve a real lineup or depth need rather than merely
  adding total projected points to the bench;
- identify managers whose roster construction gives them a plausible reason
  to trade that player;
- propose balanced one-for-one and small multi-player packages;
- include any required drop when roster counts become uneven;
- avoid proposing a player who is not currently on the stated manager's
  authoritative Sleeper roster; and
- explain both teams' before/after outcomes.

Candidate generation must not be limited to same-position swaps. It must be
able to recognize mutually useful exchanges such as surplus WR depth for RB
depth, while enforcing legal rosters and usable starting lineups.

### 3.3 Find valuation gaps

The user can request a league-wide valuation-gap report. The assistant must:

- maintain horizon-matched selected-expert and market-consensus boards as
  separate player orders (`WEEKLY-PROXY` before ROS publishes, then `ROS`);
- identify players the market values materially higher than the selected
  experts do as possible sell-high assets;
- identify players the selected experts value materially higher than the
  market does as possible buy-low targets;
- locate each candidate on the authoritative Sleeper rosters;
- combine the valuation gap with each team's actual lineup needs and depth;
- use the market view as a proxy for how a typical opponent may value a player,
  not as proof that a specific manager agrees; and
- show rank gap, tier gap, rank-implied value gap, and source disagreement
  before proposing a trade package.

The default market proxy is complete current FantasyPros ECR at the active
horizon: weekly ECR before ROS publishes, then ROS ECR. Other market signals
may be added only as separately labeled inputs. Sleeper ownership and add/drop
trends may show popularity or momentum, but they must not silently replace the
market-value board.

### 3.4 Evaluate a proposed trade

The user can enter the players each side would send. The result must show:

- current ownership and player-identity validation;
- legality and any associated drop or open roster slot;
- rest-of-season value sent and received;
- the user's change in expected weekly starter points;
- changes in replacement-adjusted depth and absence coverage;
- week-by-week effects, including byes and fantasy playoffs;
- change in projected floor, median, ceiling, and downside-tail outcomes;
- change in NFL-team/offense concentration and correlated downside;
- the same before/after team impact for the trade partner;
- selected-expert consensus, general ECR, projection, and disagreement views;
  and
- an explanation of what assumptions would reverse the recommendation.

The output must use decision language such as `ACCEPTABLE`, `TARGET`,
`COUNTER`, or `DECLINE` only when a documented threshold is met. It must never
present a false precision such as a predicted acceptance percentage until a
separately validated offer-outcome model exists.

### 3.5 Compare alternatives

The user can compare multiple packages for the same goal. The assistant must
rank them for the user's team while retaining the partner impact and risk
tradeoffs. It must not hide a lower-variance option merely because another
package has slightly higher expected points.

### 3.6 Preserve an audit

The user can save a local, timestamped JSON or CSV report containing normalized
inputs, source timestamps, assumptions, warnings, and results. Reports must not
contain the FantasyPros API key or licensed bulk source data beyond what is
needed for personal reproducibility.

## 4. Data requirements and provider priority

### 4.1 Provider policy

Use Sleeper whenever Sleeper and FantasyPros both provide a datum needed for
league-specific analysis. Sleeper is the authority for the league's actual
state; FantasyPros is the preferred paid source only for analysis data that
Sleeper's documented API does not provide.

No recommendation may silently mix different capture times, seasons, scoring
formats, or player identities. Every source must carry `source`, `captured_at`,
`season`, `week` or horizon, and scoring metadata where applicable.

### 4.2 Sleeper requirements

Sleeper is the primary source for:

- league identity, season, status, roster positions, scoring settings, and
  roster/transaction rules exposed in league settings, including the trade
  deadline/window and playoff configuration where present;
- current roster membership, starters, reserves, roster IDs, and owner IDs;
- league users and team display names;
- weekly matchups, submitted starters, actual league-scored points, and the
  fantasy schedule that can be derived from matchup IDs;
- completed trades, waivers, free-agent moves, draft-pick transfers, and FAAB
  transfers exposed through weekly transactions;
- current ownership of traded draft picks when a future dynasty mode is added;
- Sleeper player IDs, team, position, active/injury fields, and external IDs;
  and
- add/drop trends as optional market-context evidence.

The documented Sleeper API is read-only, requires no token, and exposes the
league, roster, user, matchup, transaction, traded-pick, player, and trending
endpoints needed above. The full player map should be cached and fetched no
more than once per day as Sleeper recommends. Sleeper trending counts are
popularity evidence only; they are not player-value rankings.

Sleeper's undocumented projections/ADP service may remain a separately labeled
diagnostic source only. It must not become the primary in-season projection or
rank source without a fresh provenance, coverage, and reliability study.

### 4.3 FantasyPros requirements

FantasyPros is the primary source for:

- complete current ROS ECR as the default market-consensus board once
  published, kept separate from the selected-expert board;
- current ROS rankings when published and current weekly rankings as the
  explicitly labeled pre-ROS proxy, including individual selected-expert
  ranks, overall and positional ranks, tiers, and rank disagreement;
- rest-of-season and weekly stat projections when available;
- weekly rankings for matchup timing and a future start/sit assistant;
- injuries, practice status/probabilities where supplied, and player news;
- scored player points over a requested week range for validation and
  correlation research; and
- canonical player metadata and external-ID cross-references when Sleeper's
  mapping is absent or ambiguous.

FantasyPros documents rankings, consensus rankings, expert metadata, weekly
and rest-of-season projections, injuries, news, compare-player data, and NFL
player points in its v2 API. Before implementation, an authenticated schema
probe must verify the exact 2026 parameters and coverage for `ROS`, weekly,
and selected-expert calls. Public FantasyPros trade-analyzer pages may be used
as external validation, but RosterTheory must not scrape or depend on a private
trade-grade formula or an undocumented write/integration endpoint.

The existing one-request-per-second and 500-request-per-day project limits
remain controlling unless the actual key reports a stricter limit. Requests
must be cached, deduplicated, budgeted before execution, and summarized without
printing the key.

### 4.4 Required fallbacks

- If Sleeper league state is unavailable, stop. A cached roster may be shown
  for inspection but must not be called current or used to recommend an offer.
- During NFL Week 1, use the final approved Draft selected-
  expert board and final Draft ECR as an explicitly labeled
  `EARLY_SEASON_DRAFT_ANCHOR`; weekly evidence remains a separate current
  signal. Beginning in Week 2, switch both ownership boards to ROS only when
  true, fresh, complete ROS data passes its gates. A provider's silent Draft fallback
  is still rejected because the application selects the anchor deliberately.
- If selected-expert ranks are unavailable but complete same-horizon ECR and
  projections exist, allow an explicitly labeled `ECR-ONLY` degraded analysis.
- If ROS projections are unavailable, rank-implied values may be shown as a
  sensitivity but must not be represented as projected points.
- If any rostered skill player cannot be matched confidently across sources,
  the completeness gate fails for automated recommendations. Report every
  unmatched or ambiguous identity.
- Manual FantasyPros CSV import remains a fallback only and must retain its
  source date, scoring type, ranking type, and expert selection.

## 5. Expert-selection requirements

The trade assistant must not reuse the preseason draft-expert pool merely
because it already exists. FantasyPros evaluates draft, weekly in-season, and
rest-of-season accuracy as separate skills. The user-approved exception is the
early-season ownership baseline during Week 1, when the final Draft board is
preferred to immature ROS rankings. This reuses ranking evidence only, never
Draft acquisition, construction, survival, or watcher policy.

### 5.1 In-season expert pool

Player ownership value and trade comparison must use dedicated, horizon-aware
in-season expert evidence. Multi-year weekly in-season accuracy is the verified
fallback history. ROS-specific accuracy may become the primary ROS selector
only after its field meaning, annual coverage, and provenance are validated;
it must remain separate from weekly accuracy.
Selection should mirror the disciplined draft workflow:

- compile annual weekly in-season accuracy results for the most recent seasons
  available;
- normalize each finish by that season's field size;
- apply an explicit recency weighting and coverage adjustment;
- require availability in the current ranking horizon and a documented
  freshness threshold per expert and position;
- limit concentration so one site or analyst cannot dominate accidentally;
- preserve annual ranks, field sizes, current availability, update times, and
  exclusion reasons; and
- shrink the selected pool toward complete ROS ECR rather than inventing
  rankings when contributors omit players.

The selected-pool consensus and full ROS ECR must remain separately available
even when a documented shrinkage factor contributes to the selected board.
RosterTheory must measure the pre-shrink and final rank/value gaps so an ECR
anchor cannot erase the disagreement the trade search is intended to find.

The exact years, weights, pool size, and any anchor treatment require a
separate empirical selection study. The draft pool's 2021-2025 weights and
Sean Koerner multiplier are candidate controls, not automatic trade settings.

During Week 1, use the approved final Draft selected-expert board as the
long-term ownership order. Weekly ranks remain a separate health, role, and
near-term signal. Beginning in Week 2, use fresh selected in-season experts'
ROS contributions when available, reweighting only actual contributors and
shrinking omissions toward complete ROS ECR.

An ROS ballot is eligible only when each used position was updated within the
previous 14 days. A newer feed capture does not refresh an older contributor
ballot. Material injury, suspension, transaction, or depth-chart news after the
ballot timestamp makes the affected ballot stale immediately, regardless of
age. Staleness is recorded per expert, position, and player impact.

### 5.2 Ranking horizon and weekly proxy

The ranking source follows an explicit season-stage policy:

- preseason and Week 1: `EARLY_SEASON_DRAFT_ANCHOR` uses the
  final approved Draft selected board and final Draft market ECR;
- beginning in Week 2: `LONG_TERM` switches to selected and market ROS together
  only when true ROS data is fresh and complete; and
- if the Week 2 transition gate fails, retain the labeled Draft anchor for
  Week 2 and require review; from Week 3 onward, stop before extending it
  without explicit approval.

At every stage, `CURRENT_SIGNAL` uses current-week evidence for health, role,
and near-term lineup value after bye and matchup context are accounted for.
Weekly data is never silently relabeled as ROS, and material disagreement among
the stage-appropriate long-term view, weekly signal, and projections is shown.

A combined view may be added only after rolling-origin backtesting chooses and
validates its weights without using information published after each forecast
date. Until then, reports must not present an arbitrary ROS/weekly blend as the
most accurate view.

Because point-in-time historical ROS boards are unavailable from the personal
API, the retrospective calibration must also test weighted blends in which the
final preseason Draft rank is the explicitly labeled proxy for long-term ROS
opinion and the historical current-week rank supplies the short-term opinion.
Draft-only and weekly-only are mandatory controls. Test all forecast weeks
needed to measure Draft-signal decay, with separate reporting for Weeks 1-3.
This proxy study may recommend an early-season weight or crossover rule, but it
must not be presented as direct validation of an ROS/weekly blend.

### 5.3 Current-season learning

Current-season results may be shown as evidence, but they must be shrunk toward
multi-year history until the sample is large enough. No expert should be
promoted from one unusually accurate week.

## 6. Player and roster value requirements

### 6.1 Evaluation horizon

The default horizon is the remaining fantasy-relevant regular season through
the configured league championship week, excluding NFL Week 18 unless the
league actually uses it. The user may request:

- all remaining weeks;
- the next configurable number of weeks; or
- fantasy-playoff weeks only.

The report must state the horizon and any playoff weighting. The MVP should
default to equal remaining-week weights; alternative playoff emphasis is a
visible sensitivity, not a hidden preference.

### 6.2 Two independent horizon-matched value boards

The assistant must construct and retain two complete, horizon-matched
valuation boards:

- `selected-expert value`: RosterTheory's in-season-accuracy-weighted,
  freshness-gated expert consensus for the active horizon; and
- `market-consensus value`: complete current FantasyPros ECR for that same
  horizon.

The active horizon is `WEEKLY-PROXY` before true ROS data is published and
`ROS` afterward. A report must never compare selected weekly ranks against
market ROS ranks or vice versa.

Both boards must use the same player universe, scoring settings, projection
distribution, replacement baseline, and evaluation timestamp wherever
possible. Their player order, tiers, disagreement, and rank-implied values must
remain distinct. Do not average the two boards together before calculating the
valuation gap.

The selected-expert board represents RosterTheory's football opinion. The
market-consensus board estimates a typical public valuation. Neither one alone
proves what a particular opponent believes.

### 6.3 League-scored projection inputs

When full stat projections are available, calculate fantasy points from the
actual Sleeper scoring settings. Do not substitute a canned standard, Half-PPR,
or PPR point total. Preserve the raw source stats and calculation provenance.

Weekly projections should drive week-by-week lineup effects and, when direct
ROS projections are unavailable, their remaining-week sum supplies the common
ownership-value distribution. ROS ranks constrain total ownership value once
published. Differences between rank-implied and projection values must be
reported rather than silently reconciled.

### 6.4 Rank-aligned remaining-horizon projection curves

The trade assistant must reuse the draft watcher's core projection-spacing
method with current in-season inputs. For each skill position and valuation
board:

1. Score direct consensus ROS stat projections when available; otherwise sum
   the verified remaining weekly consensus stat projections under the actual
   Sleeper league settings.
2. Sort that position's projected point totals from highest to lowest to form
   a value curve.
3. Sort players by the board's positional rank for the active horizon.
4. Assign the highest projection total to that board's position rank 1, the
   second-highest to position rank 2, and so on through the covered player
   pool.

For example, if the consensus projection distribution gives its RB10 150
remaining points, RosterTheory assigns 150 points to the selected experts'
RB10 even when that player is not the projection source's original RB10. The
same common distribution is independently aligned to market ECR so selected-
expert and market values are comparable on the same point scale.

This rank-slot transfer makes expert player order authoritative while allowing
consensus projections to supply the magnitude and tier spacing. It does not
claim that a selected expert personally projected the assigned stat line.

The system must preserve, but not use to override the aligned order:

- each player's original consensus projection and raw projection rank;
- selected-expert positional and overall active-horizon ranks;
- market ECR positional and overall active-horizon ranks; and
- projection coverage, rank coverage, and all assignment provenance.

Cross-position value must follow the proven watcher pattern: use the aligned
positional values to fit a monotone overall-rank-to-value or VORP curve, apply
the appropriate board's overall active-horizon ranks, and enforce the board's
positional order afterward. Exact fitting and shrinkage parameters must be
recalibrated for current in-season player pools rather than copied from the
draft model.

If projection or rank coverage is incomplete within the required tradeable
pool, the assistant must report the gap and fail the automated opportunity
search rather than shift rank slots silently.

### 6.5 Optimal weekly use

For every remaining week and every before/after roster, choose the best legal
lineup subject to eligibility, bye, known unavailability, and the configured
replacement pool. A player's trade value is not his raw projected total. It is
the value his presence adds to the team's actual weekly lineup and depth above
the best plausible waiver replacement.

The existing optimal-lineup and weekly-use machinery may be reused after it is
made week-aware and validated for in-season rosters. Draft calibration weights,
draft acquisition logic, and completed-roster scores must not be copied into
the trade model.

### 6.6 Scarcity and replacement

Replacement levels must be recalculated from current league ownership and the
actual free-agent pool on every analysis. Position scarcity must reflect team
count, starter/flex structure, current rosters, and available players.

When a multi-player trade changes roster counts, the model must include the
best resulting add or required drop. It must show the value attributed to that
secondary move and must allow the user to override it.

### 6.7 Rank/projection reconciliation

Selected in-season expert order at the active horizon is authoritative for
player identity; projections provide league-scored value spacing. The initial
model should retain separate views comparable to the draft system:

- raw projection/weekly-lineup value for audit;
- selected-expert active-horizon rank-implied value;
- market-ECR active-horizon rank-implied value; and
- a documented selected-expert/weekly-projection reconciliation view.

The reconciled rule must be recalibrated for in-season decisions. A preseason
50% rank blend is not automatically valid after games, injuries, role changes,
and waivers alter the player pool.

Reconciliation may combine selected-expert rank-implied ownership value with
weekly projection evidence for RosterTheory's team-impact score. It must not
merge away the selected-versus-market valuation gap used to find trade
opportunities.

## 7. Risk requirements

### 7.1 Risk is multidimensional

The assistant must report at least:

- expected weekly lineup points;
- a median or central outcome;
- downside-tail and upside-tail lineup outcomes;
- player-specific availability/role uncertainty when supported by evidence;
- positional depth and recovery above waivers;
- bye-week and playoff-week coverage; and
- correlated exposure by NFL offense.

No single `risk score` may hide these components. A compact summary may be
added only if its weights are explicit and every component remains visible.

### 7.2 Correlation and NFL-team concentration

The model must distinguish types of same-team exposure:

- QB/pass-catcher correlation can raise weekly ceiling and variance;
- two pass catchers may compete for the same passing volume;
- a running back and pass catchers can share offense-wide scoring and game-
  environment risk while having different within-game relationships; and
- all same-team players share schedule, bye, quarterback, coaching, and
  offense-wide downside to varying degrees.

Correlation inputs should come from historical league-scored weekly outcomes
and be shrunk toward position-pair/offense priors. The current season alone is
too small to estimate stable player-pair covariance early in the year. Missing
evidence must produce a broad sensitivity range, not a confident penalty.

The assistant must show team concentration before and after each trade and run
at least these scenarios:

- ordinary independent player misses;
- an offense-wide underperformance affecting every starter on that team; and
- a positive high-scoring offense scenario.

### 7.3 User risk preference

Expected points remain the default recommendation objective. The user may
select a conservative, balanced, or ceiling-seeking risk posture. Changing the
posture may change package ordering, but the underlying projections and expert
ranks must remain unchanged.

The report should also note that lower variance is not universally better in a
head-to-head league. When reliable opponent and standings context is available,
the assistant may show a labeled favorite/underdog sensitivity; it must not
pretend to know the user's optimal variance without that context.

## 8. Trade-market and fairness requirements

### 8.1 Two-team benefit

A recommended outgoing offer must provide a nontrivial modeled benefit or a
clear need-based rationale for the other manager. RosterTheory should show the
partner's lineup, depth, and risk changes using the same inputs, while noting
that the partner may have different preferences.

### 8.2 Selected-expert, market, and team value

The assistant must keep these three concepts distinct:

- `selected-expert value`: RosterTheory's opinion from the in-season-accuracy-
  weighted active-horizon board and its rank-aligned projection curve;
- `market value`: current full same-horizon ECR, its independently aligned
  value curve, and optional observed market context; and
- `team value`: marginal effect on this exact roster under this league's rules.

A player can have greater team value than market value because he fills a
scarce starter slot, or lower team value because equivalent depth sits unused.
That difference is a source of mutually beneficial trades, not an error to
average away.

The opportunity search must calculate a signed selected-versus-market gap on a
common rank-implied point or VORP scale:

- market value materially above selected-expert value is a possible sell-high
  signal; and
- selected-expert value materially above market value is a possible buy-low
  signal.

The signal becomes actionable only after lineup impact, replacement depth,
risk, and the partner's needs are evaluated. Rank disagreement alone is not a
trade recommendation.

### 8.3 Acceptance claims

Sleeper transaction history exposes completed transactions but not a complete
population of rejected or ignored proposals. It therefore cannot support a
calibrated trade-acceptance probability by itself. The MVP may label packages
`partner-positive`, `near-neutral`, or `partner-negative` under explicit
thresholds, but must not claim a percentage chance of acceptance.

Historical league trades may inform manager tendencies only after identity,
format, and sample-size checks. Never infer a manager's preference from one
accepted trade or apply one manager's history to the whole league.

### 8.4 Supported assets

MVP support is limited to active redraft player-for-player and small multi-
player packages. Draft picks, keepers, dynasty aging curves, FAAB, conditional
assets, and three-team trades are future extensions. The normalized trade
asset model should allow these types later without placing dynasty logic in the
MVP scorer.

## 9. Explanation and presentation requirements

Every evaluated package must lead with football consequences and include:

- a one-sentence verdict;
- expected weekly starter-point change over the stated horizon;
- best and worst affected weeks;
- depth/replacement change;
- concentration and downside change;
- partner benefit or cost;
- source freshness and completeness; and
- the strongest reason to disagree with the verdict.

Detailed output should expose player-level ranks, projected points, tier,
lineup usage, waiver replacement, risk contribution, selected-expert rank,
market ECR, signed valuation gap, and expert disagreement. Do not combine
projected points, rank slots, and standardized scores under a single unlabeled
number.

Warnings must be prominent for stale data, current injury/news conflicts,
missing weekly projections, ambiguous identity, incomplete free-agent pools,
illegal post-trade rosters, unknown playoff weeks, and material expert/model
disagreement.

## 10. Modularity and extensibility requirements

The implementation design must separate these responsibilities behind stable
interfaces:

1. provider adapters;
2. normalized league, roster, player, schedule, projection, rank, and trade-
   asset models;
3. player identity reconciliation;
4. league-scoring and weekly lineup optimization;
5. replacement/free-agent analysis;
6. in-season expert aggregation, independent selected/market boards, rank-aligned
   projection curves, and value reconciliation;
7. risk/correlation scenarios;
8. trade candidate generation and package evaluation; and
9. CLI/report presentation and evidence export.

A waiver assistant should be able to reuse items 1-7 and replace only the
candidate/action layer. A start/sit assistant should be able to reuse provider,
scoring, schedule, projection, risk, and lineup modules without importing trade
or draft workflows.

The project remains a small Python 3.11+ standard-library local tool. Do not add
hosting, user accounts, a database, a web framework, or background services
without separate agreement.

## 11. Freshness, reproducibility, and safety requirements

- Refresh current Sleeper league/roster state at the start of an analysis.
- Cache the Sleeper player directory for no more than one day.
- Define configurable freshness gates for ROS ranks/projections, weekly
  projections, injuries, and news during design; always display actual capture
  times.
- Enforce the approved 14-day hard cutoff on each ROS expert-position ballot;
  later material player news invalidates affected ballots immediately.
- Snapshot normalized inputs used for a saved recommendation so the result can
  be reproduced even after live sources change.
- Never print, save, commit, or transmit the FantasyPros API key.
- Respect source licenses and attribution. Personal cache/export data remains
  ignored under `data/cache/`, `data/exports/`, or `data/manual/`.
- Use deterministic ordinary code for scoring and scenario evaluation. AI may
  explain the output but must not invent expert ranks, projections, injuries,
  transactions, or trades.
- Never submit a Sleeper trade or roster transaction.

## 12. MVP acceptance criteria

The trade-assistant MVP is acceptable only when all of the following pass on
recorded fixtures and a fresh read-only League Alpha snapshot:

1. It reconstructs every league roster and owner with complete skill-player
   identity coverage.
2. It detects the user's three-Bengals starting concentration without treating
   player count alone as a forced sell signal.
3. It reports the current roster's weekly lineup, waiver-replacement depth,
   bye coverage, and offense-wide downside sensitivity.
4. It builds complete, same-horizon selected-expert and market-ECR boards,
   aligns the same projection distribution to each board's rank order,
   preserves the raw projections for audit, and labels weekly proxy data.
5. A controlled fixture in which projection-source RB10 John Doe has 150
   remaining points assigns those 150 points to selected-expert RB10 Joe Smith
   without rewriting the raw projection record.
6. It identifies controlled buy-low and sell-high valuation gaps in the
   correct direction and does not treat the market proxy as a known manager
   preference.
7. It searches every opponent roster and returns only target packages that
   address an identified user need and give the partner a credible roster
   rationale.
8. It evaluates legal one-for-one and two-for-one packages, including the
   required add/drop consequence of unequal packages.
9. It reports expected lineup, depth, risk, selected-versus-market value, and
   partner deltas separately.
10. It produces the same result from the same saved inputs.
11. It fails visibly on stale league state, unknown scoring, ambiguous player
   identity, or incomplete valuation coverage.
12. It never performs a Sleeper write or exposes the FantasyPros key.
13. Unit tests cover provider normalization, scoring, rank-slot projection
    transfer, valuation-gap direction, lineup use, replacement, trade legality,
    package symmetry, correlation scenarios, degraded data, and explanation
    fields.
14. At least one hand-audited Bengals-diversification case and one case where
    keeping the stack is better than a discounted trade agree with the exact
    before/after weekly calculations.

## 13. Explicit non-goals for the first release

- submitting, accepting, rejecting, or messaging trades;
- predicting another manager's psychology or precise acceptance probability;
- dynasty, keeper, draft-pick, salary-cap, or auction-dollar valuation;
- generic public trade charts detached from the user's league;
- fully automated injury probabilities or medical advice;
- a hosted or multi-user application;
- a waiver or start/sit user interface; and
- changing any draft simulation or watcher recommendation.

## 14. Proposed defaults to confirm before design

These recommendations do not block the requirements draft, but the user should
confirm or revise them before the design is finalized:

1. Default to `balanced expected points`, with a conservative diversification
   view beside it rather than silently penalizing the Bengals stack.
2. Weight remaining weeks equally in the primary result and show a separate
   playoff-emphasis sensitivity by default.
3. Implement and validate user-entered package evaluation first, then include
   all-opponent target search in the same MVP once the scorer is trustworthy.
4. Limit the MVP to player-only 2026 redraft trades; leave FAAB, keepers,
   dynasty aging, and future draft picks for later.

## 15. Research sources

- [Sleeper API documentation](https://docs.sleeper.com/) — documented read-only
  league, roster, matchup, transaction, player, and trending endpoints.
- [FantasyPros API overview](https://www.fantasypros.com/api-data/) — v2
  rankings, projections, expert metadata, injuries, news, player points, access,
  and licensing overview.
- [FantasyPros rest-of-season accuracy methodology](https://www.fantasypros.com/about/faq/football-rest-of-season-accuracy-methodology/)
  — ROS expert scoring and its stated relevance to waiver and trade analysis.
- [FantasyPros in-season weekly accuracy methodology](https://www.fantasypros.com/about/faq/football-inseason-accuracy-methodology/)
  — separate weekly/start-sit expert evaluation.
