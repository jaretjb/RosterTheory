# RosterTheory Trade Assistant design

Status: Approved baseline; expert-horizon policy amended September 4, 2026  
Created: September 4, 2026 (America/Los_Angeles)  
Authority: `docs/TRADE_ASSISTANT_REQUIREMENTS.md`  
Scope: Design only; this document does not authorize implementation

Loading rule: do not load this document by default. Read it only for Trade
Assistant architecture, data flow, interfaces, implementation, design review,
or task-list creation. Startup, status, requirements-only, Draft Assistant,
test, and unrelated work must not load it.

Planned delivery tasks and their section-level context references are in
`docs/TRADE_ASSISTANT_TASKS.md`.

## 1. Design outcome

The Trade Assistant will be a separate, read-only product surface built on a
small shared football-analysis core. It will not be a mode inside the draft
watcher and will not import draft acquisition policy.

The first release will:

- refresh one Sleeper redraft league into a reproducible analysis snapshot;
- build independent, horizon-matched selected-expert and market-consensus value
  boards, using weekly proxy data only until ROS publishes;
- assign a common league-scored projection curve to each board's own player
  order;
- evaluate the user's and partner's legal weekly lineups before and after a
  package, including any required add or drop;
- report expected points, usable depth, market fairness, and risk separately;
- search the league for selected-versus-market value gaps and mutually useful
  packages; and
- emit a clearly labeled terminal report plus a local evidence bundle.

The design adopts the proposed requirements defaults: balanced expected points
is primary, conservative diversification and playoff emphasis are visible
sensitivities, entered-package evaluation is validated before automated
search, and the MVP is player-only 2026 redraft.

## 2. System shape

```text
 Sleeper API             FantasyPros API        audited local configuration
      |                         |                            |
      +------------ provider retrieval and cache -----------+
                                |
                       normalized snapshot
                 identity + league + schedule + provenance
                                |
             +------------------+------------------+
             |                                     |
       shared football core                  Trade Assistant
   scoring / lineup / replacement       value boards / risk / packages
             |                                     |
             +------------------+------------------+
                                |
                   trade application service
                                |
                 CLI report + JSON/CSV evidence

 Draft Assistant ----------------------------------------------
 stays operationally separate; it may consume proven shared primitives later
```

Dependency direction is one way: `trade` may depend on `core` and `providers`;
`core` and `providers` may not depend on `trade` or draft policy. The Draft
Assistant will not be moved wholesale during trade work. Shared extraction is
additive and regression-tested so the September 7 League Beta path remains stable.

## 3. Package boundaries

The target source layout is:

```text
src/roster_theory/
  core/
    models.py
    identity.py
    provenance.py
    scoring.py
    lineup.py
    replacement.py
  providers/
    base.py
    sleeper.py
    fantasypros.py
    cache.py
  trade/
    models.py
    snapshot.py
    experts.py
    value_boards.py
    weekly_value.py
    risk.py
    evaluator.py
    search.py
    report.py
    service.py
  cli.py
```

The filenames are design targets, not permission for a broad refactor.

| Boundary | Owns | Must not own |
| --- | --- | --- |
| `core.models` | normalized immutable football entities | provider payloads or feature scores |
| `core.identity` | explicit ID joins and ambiguity reports | fuzzy silent matches |
| `core.provenance` | capture times, horizons, hashes, warnings | network retrieval |
| `core.scoring` | Sleeper-stat scoring rules | draft rank or trade policy |
| `core.lineup` | legal maximum-weight lineup assignment | roster acquisition decisions |
| `core.replacement` | current free-agent and waiver floors | ADP or next-pick survival |
| `providers` | read-only retrieval, retry, rate limit, raw cache | recommendation logic |
| `trade.value_boards` | active-horizon aggregation and rank-slot value curves | weekly lineup selection |
| `trade.weekly_value` | week-aware team marginal value | market acceptance claims |
| `trade.risk` | transparent scenarios and correlation evidence | hidden composite penalty |
| `trade.evaluator` | apply and score one package symmetrically | league-wide enumeration |
| `trade.search` | prune, enumerate, and rank candidate packages | provider calls |
| `trade.report` | terminal/JSON/CSV presentation | football calculations |
| `trade.service` | orchestration and completeness gates | low-level parsing |

The existing top-level `sleeper.py`, `fantasypros.py`, `rankings.py`, and
simulation helpers remain compatibility surfaces initially. New provider
adapters may wrap their tested clients. A shared primitive is extracted only
when trade needs it, its feature-neutral contract is clear, and the existing
draft tests continue to pass.

## 4. Core data contracts

Use frozen, slotted dataclasses at calculation boundaries and plain JSON-safe
dictionaries only at provider and serialization edges.

### 4.1 Provenance

`DataStamp` contains:

- `source`, `endpoint`, and optional provider dataset name;
- `captured_at`, `season`, `week`, and `horizon_start`/`horizon_end`;
- scoring label and normalized scoring hash when applicable;
- request-parameter hash, payload hash, and cache status;
- freshness limit, freshness result, and licensing/export restriction; and
- warnings describing unavailable provider timestamps or partial coverage.

`AnalysisManifest` contains an analysis ID, league/user identity, current NFL
week, evaluation horizon, configuration hash, deterministic scenario seed,
all `DataStamp` records, coverage checks, warnings, and input file hashes. The
analysis ID is a SHA-256 hash of normalized inputs plus configuration, not a
random identifier.

### 4.2 Football entities

- `Player`: canonical internal ID, Sleeper ID, FantasyPros ID, name, NFL team,
  eligible positions, active/injury fields, and identity confidence.
- `LeagueRules`: league/season identity, team count, roster slots, scoring,
  reserve/IR/taxi rules exposed by Sleeper, transaction/trade settings, and
  playoff/championship weeks.
- `FantasyTeam`: roster ID, owner ID, display name, player IDs, starter IDs,
  reserve/IR IDs, and standing fields.
- `FantasyWeek`: NFL week, fantasy matchup ID/opponent where known, playoff
  weight, bye/game availability, and source status.
- `Projection`: player, kind (`ROS` or `WEEKLY`), week/horizon, raw stat line,
  league-scored points, source consensus, and coverage status.
- `RankObservation`: player, board source, expert ID, position/overall rank,
  tier, scoring, horizon, updated time, and contributor metadata.

### 4.3 Valuation and trade entities

- `ValueBoard`: board ID (`selected_raw`, `selected_final`, or `market`),
  ordered rank records, aligned positional curve, overall-rank curve,
  replacement baseline, completeness, and provenance.
- `PlayerValue`: raw projection, raw projection rank, positional aligned
  points, overall reconciled points, common-baseline VORP, tier, rank
  disagreement, weekly team use, and warnings for each view.
- `TradeAsset`: tagged union beginning with `PlayerAsset`; future asset tags do
  not enter the MVP evaluator.
- `TradePackage`: exactly two roster IDs, assets moving each direction, and
  explicit or automatically proposed secondary adds/drops.
- `TeamImpact`: weekly starter points, weighted horizon points, usable-depth
  value, replacement exposure, best/worst week, playoff delta, and risk profile
  before/after/delta.
- `TradeEvaluation`: legality, value sent/received under each board, market
  fairness, both `TeamImpact` results, decision label, reversal conditions,
  warnings, and manifest reference.

Every calculation uses canonical internal player IDs. User-entered names are
resolved to a unique Sleeper rostered player before evaluation; ambiguous or
unmatched names stop the analysis.

## 5. Provider design

### 5.1 Provider protocols

`providers.base` defines small `typing.Protocol` interfaces rather than one
large client:

- `LeagueStateSource`: league, users, rosters, NFL state, matchups, and
  transactions;
- `PlayerDirectorySource`: canonical player metadata and external IDs;
- `RankingSource`: consensus, individual expert ranks, and expert metadata;
- `ProjectionSource`: ROS and weekly stat projections;
- `AvailabilitySource`: injury and news records; and
- `PlayerPointsSource`: historical weekly fantasy points for validation and
  correlation research.

Protocols make recorded fixtures first-class and let a future assistant reuse
only the sources it needs. Provider-native fields remain in raw cache files;
the rest of the application consumes normalized models.

### 5.2 Sleeper adapter

The adapter extends the tested read-only client with these documented calls:

| Need | Endpoint |
| --- | --- |
| current NFL week | `GET /state/nfl` |
| rules and scoring | `GET /league/{league_id}` |
| ownership/starters | `GET /league/{league_id}/rosters` |
| owner/team names | `GET /league/{league_id}/users` |
| league schedule/results | `GET /league/{league_id}/matchups/{week}` |
| prior moves/trades | `GET /league/{league_id}/transactions/{week}` |
| playoff evidence | winners/losers bracket endpoints when relevant |
| player identity | `GET /players/nfl` |
| optional popularity | trending add/drop endpoints |

League, users, rosters, and NFL state are fetched together at the start of
every recommendation. The full player directory is reused for at most 24
hours. Matchups and transactions are fetched only for the weeks required by
the analysis. Trending data is optional context and never fills a rank.

The normalizer must not assume that every future matchup endpoint is populated
or that every league setting uses the same key. It records missing future
opponents and derives the evaluation horizon from verified league settings.
If championship week, trade deadline, or future pairings cannot be verified,
the affected output is labeled or stopped according to the completeness gate.

### 5.3 FantasyPros adapter

The existing HOF client supplies the base URL, authentication, error handling,
and secret boundary. It gains explicit methods for news, injuries, compare
players, player points, and parameterized ROS/weekly datasets only after an
authenticated schema probe verifies the 2026 responses.

The probe records shapes and counts without exporting bulk licensed rows. It
must establish:

- exact `ROS` parameters for consensus and individual rankings;
- whether overall and positional ROS ranks share one selectable expert set;
- contributor IDs, update times, tiers, and rank-spread fields;
- exact weekly and ROS projection parameters and stat coverage;
- injury/news timestamps and practice fields;
- player-points week-range and scoring behavior;
- external Sleeper IDs or other reliable cross-reference fields; and
- actual key limits and which historical seasons are available to the personal
  HOF license.

The design deliberately does not guess parameters that the public overview
does not specify. A failed probe disables that capability and activates the
requirements-defined degraded mode; it does not trigger scraping.

### 5.4 Call budget and caching

Before retrieval, the service builds a call plan showing required calls,
fresh-cache hits, optional calls, and remaining daily budget. FantasyPros calls
remain paced at one per second and capped by the project limit. Equivalent
requests are deduplicated by normalized endpoint and parameter hash.

Default freshness limits are configurable and shown in every report:

| Dataset | Default maximum age | Behavior when stale |
| --- | ---: | --- |
| Sleeper league/users/rosters/NFL state | current run only | recommendation stops |
| Sleeper player directory | 24 hours | refresh before analysis |
| Sleeper matchup/transaction week | current run for current week; immutable after final | stop or clearly historical |
| FantasyPros ROS dataset capture | 24 hours | refresh the dataset before analysis |
| FantasyPros ROS contributor ballot by position | 14 days | exclude the stale ballot; later material news invalidates it immediately |
| FantasyPros weekly projections/ranks | current game week; 12-hour dataset capture | week-level recommendation stops |
| injuries and news | 2 hours | prominent warning; injured-player automation stops |
| historical player points | immutable by completed week | reuse verified cache |

When a source provides no trustworthy update time, freshness is measured from
capture time and the limitation is shown.

## 6. Snapshot and completeness pipeline

One analysis uses one immutable `TradeSnapshot`; it never reads changing cache
files midway through scoring.

1. Fetch and normalize current Sleeper league, users, rosters, NFL state, and
   player identities.
2. Resolve the user's roster from configured user ID, never from roster number
   copied from another season.
3. Derive the remaining fantasy horizon and obtain required matchup, schedule,
   bye, transaction, and playoff evidence.
4. Load fresh, horizon-matched market ECR and selected-expert observations,
   remaining weekly projections (plus direct ROS projections when available),
   and availability data.
5. Reconcile every rostered skill player and every player admitted to the
   tradeable/free-agent universe.
6. Freeze normalized inputs and create the manifest.
7. Run completeness gates before constructing values or packages.

Automated evaluation requires:

- exact league, scoring, roster-slot, user-roster, season, and current-week
  identity;
- 100% identity coverage for rostered skill players and proposed assets;
- complete ownership with no player on multiple active rosters;
- contiguous rank/projection coverage through each position's required curve;
- fresh complete market ECR and either a complete selected board or explicit
  `ECR-ONLY` mode;
- weekly projections for every likely starter in every evaluated week;
- a verified common replacement/free-agent baseline; and
- no unresolved injury/news conflict for a proposed player.

Opportunity search has the stricter requirement of complete coverage for all
players it may enumerate. A manually entered package may proceed with a smaller
complete universe only if every omitted capability is labeled and the weekly
and replacement calculations remain valid.

## 7. In-season expert and market boards

### 7.1 Selected in-season expert aggregation

Weekly in-season expert-accuracy history is stored separately from preseason
history under a trade-scoped configuration path. Selection uses normalized
annual field finishes, recency, coverage, current availability, freshness, and
contributor concentration limits. Exact years, weights, pool size, and any
anchor are outputs of the later expert-selection study, not copied constants.

During Week 1, both ownership boards deliberately reuse the
final approved Draft ranking evidence and are labeled
`EARLY_SEASON_DRAFT_ANCHOR`. This imports no ADP, acquisition timing, roster
construction, survival, or watcher policy into Trade. A provider response that
silently falls back to Draft remains invalid because this stage is selected by
RosterTheory, not inferred from response contents.

Beginning in Week 2, both selected and market ownership boards switch together to
`ROS` only when genuine ROS ranks pass coverage and freshness gates; selected
aggregation then uses only chosen in-season experts who actually contributed
ROS ranks and reweights their approved weights. If that gate fails during Week
2, retain the labeled Draft anchor for review. From Week 3 onward, stop before
any Draft-anchor extension unless it is explicitly approved.

ROS eligibility is evaluated per expert and position from the contributor's
own revision timestamp, with a 14-day hard cutoff. The consensus response or
cache timestamp cannot make an old ballot fresh. Injury, suspension,
transaction, or depth-chart news newer than a ballot invalidates that ballot
for affected players until the expert updates it or the conflict is manually
resolved and recorded.

When both horizons exist, retain two first-class views before any blend:

- `LONG_TERM`: the stage-appropriate Draft anchor during Week 1, then fresh
  ROS rank order aligned to the remaining-season point distribution; and
- `CURRENT_SIGNAL`: current-week expert and projection evidence used for
  health, role, and near-term lineup value after bye and matchup effects are
  identified.

A later `BLENDED` view must be calibrated by rolling-origin backtests. Each
forecast may use only ranks, projections, news, and statuses available at its
historical cutoff. Position-specific and freshness-dependent weights compete
against ROS-only, weekly-only, and projection-only controls; no fixed blend is
accepted merely because it looks reasonable on the current roster.

The first retrospective study substitutes the final Draft rank for unavailable
point-in-time historical ROS rank and labels every result `DRAFT_PROXY`. For
each season, position, and forecast week it compares Draft-only, weekly-only,
and a documented grid of Draft/weekly weights on a common rank-slot point
scale. It evaluates Weeks 1-3 separately and continues far enough into the
season to estimate Draft-signal decay. Raw weekly blends and bye/matchup-aware
weekly residual blends are separate candidates. The study uses rolling-origin
season holdouts, never random player-row splits, and publishes sample counts,
uncertainty, rank-slot point error, positional ordering error, and marginal
lineup-value error. Its output can calibrate the early Draft anchor but cannot
claim to validate a true ROS/weekly blend.

For each player retain:

- every contributing rank and expert weight;
- coverage and omitted-expert reasons;
- pre-shrink weighted rank (`selected_raw`);
- any approved ECR shrinkage and final selected rank (`selected_final`); and
- market ECR untouched by that shrinkage.

The opportunity report shows both pre-shrink and final gaps so shrinkage cannot
erase the signal invisibly.

### 7.2 Common rank-slot projection curve

Let `Q[p]` be the descending league-scored remaining-horizon consensus values
for position `p`, using direct ROS projections when available or the verified
sum of weekly projections otherwise. Let `r_b(x)` be player `x`'s positional
rank on board `b`, where `b` is selected or market. Then:

```text
aligned_points(b, x) = Q[position(x)][r_b(x)]
```

The projection distribution is constructed once per position and horizon.
Each board receives its own identity assignment. If the raw projection source's
RB10 is John Doe at 150 points, both boards use 150 as the RB10 slot value, but
the selected board may assign it to Joe Smith while market ECR assigns it to a
different RB10.

Coverage is fixed before sorting. Missing rows never collapse the array and
shift later rank slots. The curve includes at least the FantasyPros ROS
accuracy pools (QB25, RB50, WR60, TE20) and expands as needed to cover every
rostered player, proposed asset, and plausible waiver replacement. If either
board lacks a contiguous rank through the required position cutoff, automated
search stops.

### 7.3 Common replacement scale and cross-position value

Selected-versus-market gaps require a common numerical zero. For each
position, calculate one waiver baseline from the current unrostered player pool
using league-scored raw weekly/ROS consensus evidence and the league's legal
starter/flex demand. Apply that same numeric baseline to both aligned boards:

```text
board_vorp(b, x) = aligned_points(b, x) - common_replacement[position(x)]
```

The actual replacement-player identity and weekly add candidate remain visible
and may differ by week; they do not change the common comparison zero.

For each board independently, fit the existing pool-adjacent-violators monotone
overall-rank-to-VORP curve from positional aligned values. Apply that board's
overall ROS ranks, then re-enforce its positional order. The trade module may
reuse the proven algorithm after extracting it from draft-specific `Player`
fields; it must recalibrate the in-season fit range and any blend weight.

The primary valuation-gap fields are:

```text
rank_gap       = market_rank - selected_rank
value_gap      = market_vorp - selected_vorp
tier_gap       = market_tier - selected_tier
```

Positive `value_gap` means the market values the player more highly and is a
possible sell-high signal. Negative `value_gap` is a possible buy-low signal.
Reports state the sign convention. No gap alone becomes a recommendation.

## 8. Weekly lineup and team value

### 8.1 Legal lineup optimizer

Extract the feature-neutral eligibility and optimal-lineup behavior currently
embedded in `simulation.py` into `core.lineup`. The implementation uses a
deterministic maximum-weight slot assignment supporting dedicated positions,
FLEX, WR/RB flex, receiver flex, and superflex. It returns selected player IDs,
slot assignments, unused players, score, and ties resolved by stable canonical
ID.

The optimizer accepts a `player -> points` mapping, so the same contract works
for weekly projections, ROS sensitivities, absences, waivers, and future
start/sit analysis. It contains no draft roster caps, rounds, ADP, or VONA.

### 8.2 Week-aware marginal value

For each team and remaining week:

1. score raw weekly stat projections under the exact Sleeper rules;
2. remove verified bye/inactive players and mark uncertain availability;
3. optimize the legal lineup;
4. repeat after the complete trade plus associated add/drop; and
5. retain lineup entrants, displaced starters, bench coverage, and delta.

The primary expected-points result is the equally weighted sum of weekly
optimal-lineup deltas. A playoff sensitivity applies explicit extra weights to
the verified playoff weeks. ROS rank-implied value constrains ownership value
and provides a model sensitivity; it does not overwrite known week-specific
matchup effects.

Usable depth is measured only when a reserve replaces a starter above the
current waiver alternative in explicit absence scenarios. There is no flat
bench bonus and no copied draft reserve weight.

### 8.3 Add/drop consequence

Apply all traded assets simultaneously. If a team finishes above its legal
active-roster count, enumerate legal drops and choose the one that maximizes
that team's post-trade weekly value; report the choice and next-best
alternative. If a team gains an open slot, propose the best eligible free-agent
add under the same calculation. The user may override either player.

IR/reserve eligibility is validated from Sleeper state when available. If the
API does not expose enough rule detail to prove legality, the evaluator reports
`MANUAL LEGALITY CHECK` rather than guessing.

## 9. Risk and correlation design

Risk is a vector, not a trade tax. `RiskProfile` retains:

- central weekly lineup points;
- modeled lower/upper outcomes when distribution coverage passes;
- absence-scenario lineup loss and recoverable depth;
- bye and playoff coverage;
- player-specific rank/projection disagreement;
- NFL-team starter counts and point-share concentration; and
- pairwise/offense-wide covariance evidence and confidence.

Historical weekly player points form position-pair and same-offense priors.
Current player-pair observations are used only when enough overlapping active
weeks exist and are shrunk toward those priors. The shrinkage strength, sample
count, seasons, scoring transformation, and confidence are explicit. An
unavailable or unlicensed historical dataset produces a broad scenario range,
not a fabricated correlation.

Every package is evaluated under at least:

- central weekly projections;
- independent single- and multi-starter absence sensitivities;
- an offense-wide downside multiplier applied to all starters on one NFL
  offense; and
- an offense-wide upside multiplier.

Scenario multipliers are configuration with evidence, not hidden constants.
Until calibrated outcome distributions pass backtests, reports use
`DOWNSIDE SCENARIO`, `CENTRAL`, and `UPSIDE SCENARIO`, not probabilistic P10 or
P90 labels. A later fixed-seed or hash-keyed sampler may add quantiles while
preserving identical results from identical snapshots.

For the Bengals case, the report shows Chase, Brown, and Higgins individually,
their combined expected starter share, relevant pair types, ordinary absence
coverage, offense-wide downside, and offense-upside benefit. Reducing the count
is favorable only if the acquired package clears the expected-value and team-
value gates for the chosen risk posture.

## 10. Package evaluation

`TradeEvaluator.evaluate(snapshot, package, options)` is a pure calculation:

1. validate ownership, uniqueness, supported asset types, and roster IDs;
2. apply the full exchange and resolve explicit or proposed adds/drops;
3. validate both post-trade rosters;
4. calculate sent/received selected, market, and raw values;
5. calculate both teams' weekly lineups and usable-depth deltas;
6. calculate both risk profiles and scenario deltas;
7. identify best/worst weeks and reversal conditions; and
8. derive a transparent label from the component gates.

Labels do not come from one opaque grade:

| Label | Design rule |
| --- | --- |
| `ACCEPTABLE` | user central team value is positive across required selected/reconciled views, no hard downside gate fails, and partner is at least near-neutral in a market or need-based view |
| `TARGET` | an `ACCEPTABLE` search result also exploits a material selected-versus-market gap or solves a documented roster need |
| `COUNTER` | the concept helps but value, depth, risk, legality, or partner incentive misses a documented boundary that an adjacent package can address |
| `DECLINE` | user value is negative across required views, a hard completeness/legality gate fails, or downside is unacceptable under the selected posture |

Numerical boundaries are versioned configuration and require fixture and
historical calibration. The report prints the boundary values and the exact
failed/passed gates. It never estimates acceptance probability.

Reversal conditions are generated from actual sensitivity results, such as
“acceptable only if Player A is active by Week 3,” “market fairness disappears
without the proposed waiver add,” or “the conservative posture prefers the
alternative package because offense-wide downside falls.”

## 11. League-wide search

Search is a two-stage deterministic process so correctness stays tractable.

1. Diagnose every team's weekly starters, weak slots, surplus usable depth,
   waiver alternatives, and selected-versus-market gaps.
2. For each opponent, enumerate unique player-only 1-for-1, 2-for-1, 1-for-2,
   and bounded 2-for-2 packages.
3. Apply cheap admissible filters: ownership, supported positions, legal
   roster count, broad market-value band, a plausible need for both teams, and
   no clearly dominated asset bundle.
4. Run the exact `TradeEvaluator` on survivors, including add/drop effects.
5. Remove duplicate and Pareto-dominated packages.
6. Return a small frontier spanning best expected-points gain, best lower-risk
   alternative, strongest market-gap opportunity, and easiest partner-positive
   construction.

Search is not restricted to same-position swaps. A partner's “surplus” means a
player is displaced from useful weekly lineups and can be replaced above the
waiver floor; roster count alone is insufficient.

Default ordering is lexicographic, not a hidden weighted sum:

1. pass user-value and downside gates;
2. pass partner near-neutral/need gate;
3. maximize balanced expected weekly gain;
4. prefer stronger cross-model agreement;
5. apply the selected risk posture; and
6. prefer fewer assets and no forced drop when otherwise tied.

## 12. CLI and report design

All commands live under a visible `trade` namespace:

```text
python -m roster_theory trade refresh league_alpha
python -m roster_theory trade diagnose league_alpha
python -m roster_theory trade gaps league_alpha
python -m roster_theory trade evaluate league_alpha --send PLAYER --receive PLAYER
python -m roster_theory trade search league_alpha
python -m roster_theory trade compare league_alpha --packages FILE
```

`PLAYER` accepts a Sleeper ID or an exact unique name and prints the resolved
identity before calculation. Repeated `--send`/`--receive` flags form packages;
`--drop`, `--add`, `--horizon`, `--risk-posture`, `--playoff-weight`,
`--snapshot`, `--json`, and `--save-evidence` provide explicit overrides.

`refresh` retrieves and validates data but makes no recommendation. Analysis
commands refresh current Sleeper ownership even when reusable FantasyPros data
is cached. `--snapshot` is the explicit reproducibility/offline mode and is
labeled non-current.

The compact terminal report begins:

```text
TRADE ASSISTANT — League Alpha — Half-PPR — Weeks 1-17
Data: Sleeper current | WEEKLY-PROXY ranks 4h | weekly projections 2h | injuries 18m
```

It then presents, in order:

1. verdict and one-sentence football consequence;
2. user weekly starter-point, depth, and playoff deltas;
3. concentration/downside/upside changes;
4. partner lineup/depth result and market fairness;
5. selected, pre-shrink, market, raw projection, and disagreement views;
6. best/worst affected weeks and add/drop consequences;
7. strongest reversal condition; and
8. completeness, freshness, and provenance warnings.

JSON is the canonical full result. CSV exports contain flat player-value,
weekly-impact, and candidate-summary tables. Terminal output never collapses
rank, projected points, team value, and risk into one unlabeled score.

## 13. Evidence storage

All personal/reproducible artifacts remain ignored:

```text
data/cache/trade/sleeper/{league_key}/...
data/cache/trade/fantasypros/{season}/...
data/exports/trade/{league_key}/{analysis_id}/manifest.json
data/exports/trade/{league_key}/{analysis_id}/normalized_inputs.json
data/exports/trade/{league_key}/{analysis_id}/report.json
data/exports/trade/{league_key}/{analysis_id}/player_values.csv
data/exports/trade/{league_key}/{analysis_id}/weekly_impacts.csv
```

Writes use a temporary sibling file followed by atomic replacement. The
manifest is written last and identifies every completed artifact. Exports keep
only the normalized rows needed for personal reproduction, never the API key
or an unnecessary licensed bulk payload.

## 14. Error and degraded-mode behavior

Errors are typed and converted to concise user-facing stop reasons:

- `SourceUnavailable`: Sleeper current state cannot be fetched; stop.
- `StaleData`: required data exceeds its freshness gate; stop or refresh.
- `IdentityIncomplete`: any affected player is unmatched/ambiguous; stop.
- `CoverageIncomplete`: a required rank/projection curve has a gap; automated
  search stops.
- `UnsupportedScoring`: Sleeper scoring contains an unimplemented stat; stop.
- `RosterIllegal`: the package cannot produce legal rosters; decline without
  scoring it.
- `ScheduleIncomplete`: report only verified weeks and do not call the result
  full ROS.
- `ProviderCapabilityMissing`: use only a requirements-approved degraded mode.

`WEEKLY-PROXY` retains separate selected and market boards but labels their
ranking horizon as current-week evidence rather than ROS ownership opinion.
`ECR-ONLY` retains market ranks, raw/weekly projections, lineup analysis, and
risk scenarios, but it disables selected-versus-market opportunity claims.
Rank-only mode may show a value sensitivity but may not claim projected weekly
points. Current ownership is never allowed to degrade to a stale recommendation.

## 15. Verification strategy

Unit tests use recorded, minimized fixtures and never call live providers.
Required test groups are:

- provider response normalization and provenance;
- player identity exact match, external-ID match, ambiguity, and failure;
- Sleeper scoring aliases and unsupported-stat detection;
- flexible-lineup optimality and stable tie behavior;
- current free-agent replacement and multi-player add/drop consequences;
- in-season expert weighting, active-horizon coverage, shrinkage audit, and
  concentration cap;
- independent selected/market rank-slot transfers, including the RB10
  John Doe/Joe Smith fixture;
- monotone overall-rank curves and positional-order preservation;
- valuation-gap sign and tier direction;
- weekly team marginal value and package symmetry;
- correlation shrinkage and offense-wide scenarios;
- candidate pruning without loss of controlled optimal packages;
- decision labels and reversal explanations;
- freshness, incomplete coverage, and `ECR-ONLY` behavior; and
- deterministic evidence reproduction from an identical manifest.

Golden integration fixtures cover:

1. the current League Alpha roster with three Bengals starters;
2. a fair diversification trade that improves or preserves expected value;
3. a discounted diversification offer where keeping the stack wins;
4. a selected-expert buy-low against market ECR;
5. a market-favored sell-high that also solves the partner's need; and
6. a 2-for-1 whose required drop reverses the apparent result.

The entire existing Draft Assistant suite remains a regression gate after each
shared extraction. Live authenticated probes are manual integration checks
that record only schemas, counts, parameters, and coverage; they are not unit
tests and must respect the request budget.

## 16. Design gates and deferred choices

This design deliberately leaves empirical values out of code until evidence is
available. Before implementation can be called recommendation-ready, separate
studies must settle:

- available historical weekly in-season accuracy years and the selected-expert
  formula;
- point-in-time ROS rank history or a prospective snapshot corpus sufficient
  to validate dual-mode reconciliation and any blend without look-ahead;
- exact FantasyPros 2026 ROS/weekly schemas and call budget;
- the source and completeness of future NFL schedule, bye, and playoff-week
  data;
- common waiver-baseline depth by position;
- rank-reconciliation and ECR-shrinkage weights;
- risk priors, correlation shrinkage, and scenario multipliers; and
- numerical label and partner-near-neutral boundaries.

These are calibration inputs, not reasons to couple the Trade Assistant to the
draft model. `docs/TRADE_ASSISTANT_TASKS.md` maps them into independently
testable slices, beginning with provider/schema and package-evaluation
foundations and enabling automated search only after the exact evaluator
passes its golden fixtures.

## 17. Sources informing the design

- [Sleeper API documentation](https://docs.sleeper.com/) — the official
  read-only league, roster, matchup, transaction, player, NFL-state, and
  trending contracts and player-directory caching guidance.
- [FantasyPros API overview](https://www.fantasypros.com/api-data/) — the
  official rankings, projections, expert, injury, news, and player-points
  capabilities and personal HOF access boundary.
- [FantasyPros ROS accuracy methodology](https://www.fantasypros.com/about/faq/football-rest-of-season-accuracy-methodology/)
  — separate ROS evaluation, rank-slot point methodology, player-pool depths,
  and earlier-horizon weighting.
