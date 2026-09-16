# Trade Draft-proxy and horizon-validation study

Date: September 5, 2026 (America/Los_Angeles)  
Scope: Phase 4R tasks TA-414 and TA-416

## Decision

Keep `LONG_TERM` and `CURRENT_SIGNAL` separate and leave `BLENDED` disabled.
The 2024-selected Draft/weekly blends did not beat weekly-only ECR on the 2025
holdout. The study does not justify changing the approved final-Draft anchor
through Week 2 because only one full season is available for training and one
for holdout, provider update times have date rather than time precision, and
the Draft rank is only a proxy for unavailable point-in-time ROS opinion.

Begin prospective 2026 snapshots now. Revisit the transition or a blend only
after multiple cutoff-safe forecast blocks contain true ROS, weekly,
projection, news, bye, and outcome evidence.

### Subsequent season-stage decision

After reviewing these limits, the user chose final Draft ownership rankings
for Week 1 only and a joint fresh-complete ROS transition beginning in Week 2.
That product decision supersedes this study's conservative Week 2 Draft-anchor
retention; it does not change the historical results or promote a blend.

## Inputs and isolation

- FantasyPros HOF Premium final Draft Half-PPR ECR for 2024 and 2025.
- FantasyPros archived weekly Half-PPR ECR for Weeks 1-17 in both seasons.
- FantasyPros Half-PPR player points for Weeks 1-17 in both seasons.
- NFL official archived weekly schedules for verified 2024 and 2025 byes.
- QB30, RB70, WR90, and TE35 final-Draft player pools.
- The final Draft rank is always labeled `DRAFT_PROXY`; it is not described as
  historical ROS evidence.
- Draft ADP, survival, construction, simulation, and watcher policy are absent.

The collector used 152 paced API calls and cached licensed rows only under the
ignored `data/cache/trade/` namespace. The aggregate evidence is written under
ignored `data/exports/trade/`; no API key or licensed player row is in this
document.

## Method

For every season, week, and position, the harness converts rank order to a
common point-slot curve formed from actual remaining Weeks 1-17 Half-PPR
points. It reports:

- point-slot mean absolute error;
- standardized marginal lineup-value mean absolute error above the positional
  60th-percentile replacement point;
- pairwise positional ordering error;
- player count; and
- standard error of player-level absolute point error.

The grid tests Draft weights from 0% through 100% in 10% steps. Zero is the
weekly-only control; 100% is the Draft-only control. `RAW` treats a player
missing from weekly ECR as below that week's returned field.
`MATCHUP_BYE_AWARE` retains the matchup-sensitive weekly order but restores a
verified bye omission to the player's Draft-proxy order instead of treating
the bye as loss of ownership value.

Weights are selected on 2024 separately by week, position, and signal mode,
then scored without refitting on 2025. This is a season-level rolling-origin
holdout rather than a random player-row split.

## Holdout results

Across 3,791 2025 player/week/position rows:

| Signal/candidate | Point MAE | Lineup-value MAE | Ordering error |
| --- | ---: | ---: | ---: |
| Raw weekly-only | 27.22 | 17.54 | 0.25 |
| Raw 2024-selected blend | 27.50 | 17.97 | 0.27 |
| Draft-only | 31.38 | 20.19 | 0.34 |
| Bye-aware weekly-only | **25.99** | **17.09** | **0.25** |
| Bye-aware 2024-selected blend | 26.61 | 17.56 | 0.26 |

The aggregate in-sample-looking grid minimum is not the decision statistic.
The weight chosen only on the earlier season is worse than weekly-only on the
holdout in both signal modes, so no blend is promoted.

### Weeks 1-3

The raw and bye-aware modes are identical before 2025 byes begin.

| Week | Candidate | N | Point MAE | Lineup-value MAE |
| ---: | --- | ---: | ---: | ---: |
| 1 | Draft-only | 223 | **48.47** | **31.57** |
| 1 | 2024-selected blend | 223 | 48.99 | 31.75 |
| 1 | Weekly-only | 223 | 49.06 | 32.20 |
| 2 | Draft-only | 223 | 48.45 | 31.49 |
| 2 | 2024-selected blend | 223 | 46.97 | 30.50 |
| 2 | Weekly-only | 223 | **45.97** | **28.94** |
| 3 | Draft-only | 223 | 46.05 | 29.35 |
| 3 | 2024-selected blend | 223 | 41.01 | 25.59 |
| 3 | Weekly-only | 223 | **37.98** | **23.58** |

Week 1 narrowly favors Draft-only. Weekly-only leads by Week 2 and widens the
lead in Week 3. The position-specific selected weights are unstable—for
example Week 1 ranges from 0% Draft at QB/WR to 60% at TE—and do not generalize
well enough to replace the simpler approved stage rule.

## Prospective collection

The first 2026 Week 1 prospective snapshot contains 864 records: long-term
rank, long-term value, current rank, and current adjusted points for each of
216 actionable players. It is labeled `EARLY_SEASON_DRAFT_ANCHOR`, retains its
cutoff and source times, has stable hash
`5259b80a229d64c60be3579760f8099a2ef280ba3e235feea18c96cb8dc8c3c7`,
and contains no combined score.

The general rolling-origin harness separately supports `LONG_TERM_ONLY`,
`WEEKLY_ONLY`, `PROJECTION_ONLY`, and candidate blend controls. Prospective
snapshots reject any input published after their declared cutoff.

## Limitations

- FantasyPros historical rank responses expose `last_updated` as month/day,
  not a precise timestamp. The collector conservatively preserves this as a
  date-precision limitation. Archived weekly rank products are treated as
  pregame forecasts, but within-day cutoff order cannot be independently
  proven from this API response.
- Only 2024 can train and 2025 can hold out. Player-level standard errors do
  not substitute for additional season-level holdouts.
- The standardized lineup-value metric uses a positional replacement point;
  it is not a replay of the user's historical roster and opponents.
- The context adjustment is verified-bye restoration plus the matchup-aware
  weekly ECR order. Historical injury/news snapshots are not complete enough
  to distinguish every non-bye omission.
- No point-in-time historical ROS ballots exist in the personal API, so these
  results cannot validate a true ROS/weekly blend.

## Reproducibility

The ignored aggregate artifact is
`data/exports/trade/draft_proxy_backtest_2024_2025.json`, evidence hash
`e0bcd0de58a146f9acd3bad42ade5fbbe1b0f5ef01ec7036bb5e3ed582af4172`.
Re-running the collector against the 152 cached inputs makes zero paid calls
and reproduces the same 7,616 forecast rows, 1,496 holdout metrics, and hash.
