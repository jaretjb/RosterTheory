# How RosterTheory makes recommendations

This guide explains the implemented Draft, Trade, and Waiver algorithms. It is
an explanation of the decision engine, not a published player ranking. Examples
are synthetic. Policy names, weights, thresholds, coverage, and evidence timestamps
in a run determine what that run can claim.

- [Shared foundations](#shared-foundations)
- [Draft](#draft)
- [Trade](#trade)
- [Waiver](#waiver)
- [Interpreting results](#interpreting-results)

## Shared foundations

### Scoring, horizons, and missing data

For player `i` in week `w`, the league-scored forecast is:

```text
P(i,w) = sum over scoring categories s of [projected_stat(i,w,s) × league_weight(s)]
```

The scorer uses the actual Sleeper rules, including supported position premiums
and scoring buckets. Preseason, weekly, and rest-of-season (ROS) rankings retain
their own horizons. A preseason rank cannot silently substitute for a current
weekly or ROS rank. Expert consensus ranking is abbreviated **ECR** below.

Forecast completeness is position-aware. QB passing and rushing and RB rushing
and receiving are core inputs; WR/TE receiving is core. Omitted WR passing, QB
receiving, and individual two-point conversion forecasts do not block analysis.
Any supplied applicable statistic still counts. Missing core fields, invalid
values, ambiguous identities, and unsupported scoring rules remain explicit.
See the complete [position contract](POSITION_FORECAST_COVERAGE.md), including
fumbles and K/DST requirements.

### Lineups and units

For a fixed roster and week, the lineup engine maximizes points over legal slot
assignments, respecting FLEX/SUPER_FLEX eligibility and using each player once.
It uses position-allocation enumeration where applicable and a dynamic-programming
assignment fallback for general eligibility. For in-season moves:

```text
lineup_gain = sum over weeks w of weight(w) × [best_lineup_after(w) − best_lineup_before(w)]
```

Bench depth, replacement access, availability, and downside are additional
considerations. A player's own projected points are not their marginal value to
a roster: a new player can simply displace an almost equally good starter.

| Quantity | Meaning |
| --- | --- |
| League-scored points | Forecast production under this league's scoring |
| VORP | Value over replacement: modeled points above a positional replacement baseline |
| Trade-chart price | Provider market units; not fantasy points |
| Trade percentile gap | Difference in relative board positions; not a percentage price discount |
| Waiver Value | A bounded 0–100 ranking-based decision score; not fantasy points |

Implementation: [forecast scoring](../src/roster_theory/core/forecast_scoring.py),
[lineup optimization](../src/roster_theory/core/lineup.py).

## Draft

Draft has two recommendation entry points. The live watcher uses the named
roster policies and simulation machinery described below. The standalone
`recommend` command uses a smaller board heuristic:

```text
mvor_score = board_VBD + 20 × (1 − survival_to_next_pick) + roster_need_adjustment
```

It removes drafted players, adds 4 for an RB/WR position with fewer than two
already drafted, subtracts 7 for a QB/TE position already represented, and sorts
by score followed by expert rank. This command does not run the full live
two-pick or rollout calculation. `board_VBD` is the board's stored value-based
drafting score. Implementation: [standalone recommendation](../src/roster_theory/draft/assistant.py).

### 1. Build an expert-ordered value board

The Draft workflow combines authoritative expert rankings with league-scored
projections. Where authorized accuracy evidence is available, expert selection
and weighting use position-specific historical performance; the model does not
invent expert ranks.

`expert_ordered_projection_players` sorts players by selected-expert positional
rank and assigns the descending projected-point distribution in that order.
For example, raw projections of 240, 225, and 210 become values of 240, 225, and
210 for expert ranks 1, 2, and 3, even if the raw projections originally belonged
to different players. Raw forecasts remain available for audit. This transform
uses the full board so a player's value does not change merely because someone
else was drafted.

Reconciled policies also fit a nonincreasing curve `C(r)` from overall expert
rank to VORP. Adjacent order violations are pooled and the resulting curve is
interpolated. The rank adjustment is:

```text
raw_VORP(i) = current_board_points(i) − replacement(position(i))
adjusted_points(i) = max(0, current_board_points(i)
                           + alpha × [C(overall_rank(i)) − raw_VORP(i)])
```

Here `alpha` belongs to the selected policy. Positional expert order is restored
after adjustment. This reconciles overall and positional evidence while keeping
the projection distribution's point scale.

### 2. Estimate whether a player will last

ADP describes acquisition timing. The basic conditional survival model treats
the acquisition pick as normally distributed:

```text
X ~ Normal(mean = acquisition_ADP, standard_deviation = max(2.5, 0.18 × acquisition_ADP))
survival(current, next) = Pr(X > next + 0.5) / Pr(X > current + 0.5)
```

The denominator has a small numerical floor and the result is bounded to `[0,1]`.
Room-derived survival overrides can replace this estimate. A player available
later than their ADP becomes more urgent to simulated opponents.

### 3. Compare taking a player now with waiting

There is a family of named Draft policies, rather than one universal score.
Some use value over next available (**VONA**):

```text
VONA(i) = board_points(i) − expected_same_position_fallback_at_next_pick(i)
score(i) = VORP(i) + policy_weight × VONA(i)
```

Other policies use a two-pick roster objective. For the total-team variant,
`U(roster)` is the best legal lineup with replacements plus a configured fraction
of usable bench VORP. Reserve value is discounted by the fraction of legal
starting slots its position can cover; applicable variants also cap redundant
reserves. The availability-based variant instead credits the best two bench
edges by the average modeled absence rate.

For each legal candidate `i`, the two-pick calculation is:

```text
gain_now(i) = U(roster + i) − U(roster)
gain_next(j | i) = U(roster + i + j) − U(roster + i)
q(j) = survival(j) × product over higher-valued options k of [1 − survival(k)]
path_score(i) = gain_now(i) + sum over next-pick options j of q(j) × gain_next(j | i)
```

The options are a bounded shortlist ordered by marginal roster contribution.
The product models mutually exclusive best-available choices; it is an
approximation to the room, not a calibrated joint probability model. Certain
turn-aware policies extend the calculation through the following contested
interval. Roster legality, ability to finish the starting lineup, position caps,
and named near-tie/deferral rules can constrain or reorder candidates.

### 4. Test strategies and expose uncertainty

Strategy comparison runs seeded Monte Carlo drafts. Simulated opponents combine
conditional ADP hazard, Gaussian market noise, roster needs, and available
round-specific position tendencies. Strategies are compared through resulting
roster and availability-scenario scores. Trial counts and seeds are configurable.

The bounded multi-turn beam rollout gives leading candidates the same scenario
seeds, branches over a limited number of future choices, and prunes paths. It
reports mean score, lower-tail score, and regret relative to the best candidate
in each scenario. Its reported status is `shadow_only`; it is diagnostic evidence,
not an automatic replacement of live ordering. Simulated roster strength is not
a calibrated championship probability.

Implementation: [board transforms, survival, candidate scoring, and simulation](../src/roster_theory/draft/simulation.py),
[live policy selection and evidence](../src/roster_theory/draft/watcher.py),
[expert accuracy inputs](../src/roster_theory/expert_inputs.py).

## Trade

Trade separates **what a player is worth to our model**, **what the market charges**,
and **whether a particular package helps this roster**.

### 1. Calculate intrinsic value

The in-season value builder constructs each position's descending curve from
league-scored remaining-horizon projections. Selected-expert positional rank
chooses a point on that curve:

```text
aligned_points(i) = positional_projection_curve(position(i), selected_position_rank(i))
positional_VORP(i) = aligned_points(i) − replacement(position(i))
```

It then fits a nonincreasing overall-rank/VORP curve by pooling adjacent order
violations and interpolating. A positional running-minimum pass preserves
positional rank order. The result is `reconciled_vorp`, the intrinsic ownership
value used in package comparisons. If authoritative overall ranks are absent,
the builder derives overall ordering from positional VORP and records that path.
Selected-expert and market-ECR boards remain separate.

### 2. Find buy-low and sell-high candidates

A direct trade chart supplies independent market prices. The Stats Guy Fantasy
chart uses its reception/TE-premium blend; it does not reproduce every league's
exact scoring. Market ECR can corroborate a target or serve as an explicitly
labeled proxy when requested.

Since chart units and intrinsic VORP differ, discovery compares board percentiles:

```text
percentile(rank, N) = (N − rank) / (N − 1)     for N > 1
percentile(rank, N) = 1                       for N <= 1
gap(i) = market_price_percentile(i) − intrinsic_percentile(i)

BUY_LOW:  gap <= −configured_threshold
SELL_HIGH: gap >= configured_threshold
ALIGNED:  otherwise
```

Ranks are bounded to their board's valid range. Each board has its own population
size. A player at intrinsic percentile 0.90 and market percentile 0.74 has a gap
of `−0.16`: a 16-percentile-point discount signal, **not 16% cheaper in price**.
Coverage changes can affect these comparisons.

A buy-low candidate also needs lineup or depth fit. A sell-high candidate must
be owned by the user and sufficiently disposable under the roster policy.
Candidates are ordered lexicographically: each factor breaks ties left by the
previous factor, rather than contributing to a weighted sum.

| Lane | Factor order, strongest first |
| --- | --- |
| Buy low | Discount size → user lineup gain → owner disposability → ECR corroboration → performance support |
| Sell high | Premium size → disposability → lower owner lineup cost → ECR corroboration → performance support |

Separate consolidation and roster-fit lanes also exist. A target card identifies
someone to investigate; it does not specify an acceptable offer.

### 3. Use recent performance as supporting evidence

Trade compares completed results with expectations actually captured before the
game. For point residuals:

```text
residual(game) = actual_league_points − pregame_projected_points
shrunk_mean_residual = n / (n + prior_games) × mean(residuals)
```

Rank residuals receive analogous shrinkage. Available residuals are scaled by
position and combined; opposing point/rank signals are neutralized. Minimum
sample size, freshness, and compatibility checks apply. Underperformance can
support a buy-low interpretation, but cannot by itself create a discount or
rewrite intrinsic value. Performance is the last target-ranking factor above.

Missing historical pregame captures cannot be reconstructed using today's
forecasts. Completed game results alone are insufficient to measure surprise.

### 4. Evaluate actual packages

Search builds explicit sent/received combinations, including required roster
additions or drops. It computes intrinsic ownership gain and optimized lineup
gain separately:

```text
intrinsic_gain = sum(received intrinsic values) − sum(sent intrinsic values)
                 + intrinsic value of required secondary roster moves
```

Market fairness uses chart units, with an applicable consolidation premium:

```text
S = sum(sent chart prices)
R = sum(received chart prices)
R_adjusted = R × (1 + premium)   when the consolidation premium applies; otherwise R
tolerance = max(configured_floor, configured_ratio × max(S, R_adjusted, 1))
within_band = abs(R_adjusted − S) <= tolerance
```

Synthetic example: with `S=50`, `R=48`, a 5% premium, a 10% tolerance ratio,
and a floor of 2, adjusted received price is 50.4 and tolerance is 5.04.
The package passes this price test. Those numbers are illustrative policy
choices, not recommended defaults. Both excessive underpayment and excessive
overpayment fail the final price screen. Candidate generation can use a wider
band before exact evaluation.

Passing price fairness is only one gate. Accepted search results also need
complete/legal evidence, the evaluator's intrinsic `WIN` and `ACCEPTABLE` verdict,
minimum user lineup gain, bounded depth/downside losses, sufficiently current
market evidence, and partner plausibility. Consolidations additionally check
the starter upgrade, secondary moves, and use of both outgoing assets. Packages
that immediately drop a received asset are excluded.

Partner plausibility requires bounded depth loss and either sufficient partner
lineup gain **or** a relevant roster need plus sufficient intrinsic value. It
does not guarantee that both lineups improve or predict an owner's acceptance.
Cross-model agreement compares selected-expert and market-ECR value directions;
it is distinct from chart fairness.

Search is bounded by candidate pools and exact-evaluation budgets. It retains
alternatives on a Pareto frontier: packages not dominated across the compared
outcomes. `ECR-PROXY` results cannot claim direct-chart fairness; prior-week
market evidence is indicative only. Every run must disclose its pricing mode,
omissions, and search limits.

Implementation: [intrinsic boards](../src/roster_theory/inseason/boards.py),
[target discovery](../src/roster_theory/trade/targets.py),
[performance residuals](../src/roster_theory/trade/performance.py),
[package construction and gates](../src/roster_theory/trade/target_optimizer.py).

## Waiver

Waiver evaluates **an acquisition and its roster cost**. Search compares eligible
adds with legal drops, or an open roster spot, then applies decision gates. A
player's attractive standalone score is insufficient to recommend dropping
someone more valuable.

### 1. Normalize weekly, Waiver Wire, and ROS ranks

The composite Waiver Value policy uses three signals. Weekly and ROS positional
ranks are normalized around a league-relative replacement rank `R`, currently
the number of rostered players at that position plus one. Let `N` be the ranking
scope, `B=max(N,R+1)`, and `r` the rank capped at `B`:

```text
position_score(r) = 50 + 50 × (R − r) / max(1, R − 1)   if r <= R
position_score(r) = 50 × (B − r) / (B − R)              if r > R
```

Scores are bounded to `[0,100]`; replacement is 50. Waiver Wire's overall rank
uses a different normalization:

```text
wire_score(rank, N) = 100 × [1 − (min(rank,N) − 1) / N]
```

This assigns the top rank 100 and the last rank `100/N`. Available component
weights are renormalized:

```text
base_value = sum(available weight × normalized score) / sum(available weights)
```

The weight object defaults to weekly 0.50, Waiver Wire 0.30, and ROS 0.20;
the loaded league policy controls a run. Weights must sum to one and satisfy
`weekly > wire > ROS > 0`. For scores of 80, 70, and 60, those weights give 73.

Waiver Wire is an acquisition signal and is excluded for already-rostered
players. Owned players use weekly/ROS retention evidence, with weekly ranks
below the retention cutoff omitted explicitly. Missing components are reported
and remaining weights renormalized; they are not assigned zero. Selected ROS
panel ranks are preferred, with authoritative ROS Latest ECR as the fallback.

### 2. Add a bounded performance adjustment

Available positional performance ranks are normalized with the same rank-to-100
formula used for Waiver Wire. Their weights are season production 0.45, recent
production 0.30, recent opportunity 0.15, and recent yards 0.10, renormalized over
available signals. Calling that score `performance`:

```text
adjustment = clamp(0.12 × (performance − 50), −6, +6)
Waiver_Value = clamp(base_value + adjustment, 0, 100)
```

Without performance evidence the adjustment is zero and the missing evidence
remains visible. A performance score of 75 adds 3 points to the example base
of 73, yielding Waiver Value 76.

### 3. Compare the full add/drop and apply gates

```text
value_gain = Waiver_Value(add) − Waiver_Value(drop)
```

An open roster spot has zero displaced Waiver Value. The composite policy uses
this gain as its priority score, then orders by decision tier and applicable
tie-breakers. Affirmative `ADD NOW`, `CLAIM`, or `ACQUIRE` labels require more:
value and lineup thresholds, complete required evidence, fresh material news,
an active target, bounded current-week/depth/downside losses, and applicable
retention and contingent-upside protections. Same-position acquisitions must
have a strictly better authoritative ROS rank. Injured rostered players with
above-replacement ROS value receive retention protection.

One-QB backup decisions also charge the opportunity cost of occupying the bench
spot and compare streaming/insurance value. Protected bench options require
sufficient incremental upside to justify replacing them. These checks can
prevent an acquisition despite a positive composite score. Failed affirmative
gates lead to `WATCH` or `PASS` according to the policy's separate watch criteria.

### 4. Handle kickers and defenses separately

K/DST use streaming and sampled-production rules. For a same-position comparison
with eligible weekly ranks and known season totals/game counts:

```text
weekly_advantage = (drop_weekly_rank − add_weekly_rank) / 15
production_advantage = clamp((add_total − drop_total) / max(abs(add_total), abs(drop_total)), −1, 1)
confidence = min(add_games, drop_games) / [min(add_games, drop_games) + prior_games]
specialist_score = (1 − production_weight) × weekly_advantage
                   + production_weight × confidence × production_advantage
```

If both totals are zero, production advantage is zero. These are season totals,
not points per game. Missing game counts remain unknown. A positive fresh
rank/production comparison can support streaming; the projection path instead
requires the configured current-week improvement and, for DST, rolling-horizon
advantage. A negative complete production balance cannot be bypassed by that
projection path. News, activity, and cross-position roster protections still apply.
Specialist weights are manual policy choices with unproven historical calibration.

Implementation: [Waiver Value](../src/roster_theory/waiver/priority.py),
[move evaluation](../src/roster_theory/waiver/evaluation.py),
[labels and gates](../src/roster_theory/waiver/policy.py),
[specialist formula](../src/roster_theory/waiver/specialists.py),
[search and omissions](../src/roster_theory/waiver/search.py).

## Interpreting results

- Read the policy/version, horizon, pricing mode, coverage, and failed gates
  alongside the headline recommendation. Configurable thresholds are not
  universal validated constants, and calibration does not transfer between leagues.
- Inspect the actual transaction: drafted player and continuation options,
  players sent/received, or player added/dropped. A target list is not a package.
- Conditional estimates, unavailable evidence, and bounded searches limit what
  a result establishes. A model score is not a promise of future performance.
- All three assistants produce read-only advice. Ordinary code performs the
  scoring and simulations; AI orchestrates and explains the evidence.

[Back to README](../README.md)
