# Trade ranking-horizon and history research

Date: September 5, 2026 (America/Los_Angeles)  
Scope: Read-only source audit for the proposed Phase 4R refinement

## Decision

Use a 14-day hard freshness cutoff for each ROS expert-position ballot. Through
completion of Week 2, prefer the final approved Draft selected and market
boards to immature ROS rankings. Entering Week 3, switch both ownership views
to ROS only if freshness and completeness gates pass. Keep the stage-appropriate
long-term view and matchup-aware weekly evidence separate until a leakage-safe
rolling-origin study validates a blend.

## Authenticated FantasyPros probe

Eight paced HOF Premium requests compared RB Half-PPR consensus ranks with
`experts=show`. No API key or player rows were printed or saved.

| Season | Horizon | Requested week | Rows | Experts | Response week |
| --- | --- | ---: | ---: | ---: | ---: |
| 2024 | Weekly | 8 | 132 | 44 | 8 |
| 2024 | Weekly | 14 | 91 | 42 | 14 |
| 2025 | Weekly | 8 | 94 | 45 | 8 |
| 2025 | Weekly | 14 | 115 | 45 | 14 |
| 2024 | ROS | 8 | 0 | 0 | 8 |
| 2024 | ROS | 14 | 0 | 0 | 14 |
| 2025 | ROS | 8 | 0 | 0 | 8 |
| 2025 | ROS | 14 | 0 | 0 | 14 |

Weekly response hashes differ by requested week, confirming real historical
snapshots with contributor ballots. Historical season-level ROS calls can
return the last surviving board, but the week-specific calls above prove that
the personal API does not expose the point-in-time ROS sequence needed to test
an ROS/weekly blend. The probe reserved eight requests and left 420 of the 500
daily requests.

## Backtest feasibility

Immediately feasible:

- score archived 2024-2025 weekly ECR and selected-expert ballots against
  actual weekly points;
- validate weekly expert pools, injury handling, matchup effects, and current
  lineup decisions; and
- compare weekly rankings with same-week projections without future leakage.

Not yet feasible from the HOF API alone:

- reproduce what an expert's ROS board said in each historical week;
- fit an exact historical ROS/weekly blend; or
- sum later archived weekly projections as though they were known earlier.
  Doing so would leak information published after the forecast cutoff.

## Best paths to blend evidence

1. Ask FantasyPros whether a personal historical ROS export is available or
   whether historical/bulk access requires a separate license. This is the
   highest-quality retrospective route.
2. Beginning in 2026 Week 2, capture Tuesday ROS ballots/ECR with each expert's
   positional update time, then capture current-week rankings, projections,
   injuries, and material news at fixed decision times. These ignored local
   snapshots become the clean prospective corpus.
3. Use FantasyPros archived weekly ranks plus player points to calibrate the
   `CURRENT_SIGNAL` component now, while leaving blend weight unselected.
4. Consider Fantasy Football Analytics historical weekly/season projections
   as a licensed projection benchmark. It does not replace missing historical
   ROS expert ballots.
5. Use nflverse/DynastyProcess for open player IDs, outcomes, and supporting
   simulation data. Its latest/all ECR datasets are not a verified archive of
   weekly point-in-time ROS contributor boards.
6. Public dated ROS articles from FantasyPros, Roto Street Journal, ESPN,
   Legendary Upside, and similar publishers can support spot checks. Embedded
   widgets may resolve to newer data and expert/depth coverage varies, so these
   are supplementary rather than validation-grade unless the actual dated rows
   can be recovered and licensed.

FantasyCalc redraft values are a promising independent *market* signal because
they are inferred from completed trades rather than expert forecasts. They can
help test whether FantasyPros ECR represents real manager prices, but they are
not a substitute for an ROS football-performance forecast.

## Proposed validation

For every forecast week, freeze only information available at that cutoff and
evaluate by position against remaining league-scored points and marginal legal
lineup value. Compare ROS-only, weekly-only, projection-only, simple candidate
weights, and freshness-dependent weights. Use rolling-origin holdouts by week
and season, publish sample size and uncertainty, and prefer the simplest model
whose out-of-sample improvement is material. Until that gate passes, expose
`LONG_TERM` and `CURRENT_SIGNAL` separately and do not label either a combined
truth score.

The early-season study additionally compares final Draft ranks, Draft plus
current-signal corrections, and weekly-only evidence for forecasts made before
Weeks 1, 2, and 3. This can be backtested from final historical Draft boards,
archived weekly ranks, and outcomes without historical ROS snapshots. It will
validate the early anchor and inform the eventual crossover, while the exact
Draft-versus-ROS transition must also be tested prospectively once 2026 ROS
snapshots are captured.

### Draft-proxy blend matrix

TA-416 makes this a separate required calibration rather than an incidental
part of the prospective harness. The final preseason Draft rank stands in for
historical ROS opinion and is always labeled `DRAFT_PROXY`. For each position
and historical forecast week, test Draft weights from 0% through 100% against
the complementary current-week weight, retaining the 0% weekly-only and 100%
Draft-only endpoints. Compare raw weekly rank with a second weekly signal that
removes byes and identifies matchup-driven movement before blending.

Primary outputs are rank-slot implied-point error and marginal legal-lineup
value error against the remaining season. Secondary outputs are rank
correlation, top-tier retention, injury/role-change response, and the week at
which Draft information materially stops helping. Hold out complete seasons or
forecast blocks, report uncertainty and player/position counts, and do not tune
and score on the same rows. The study may change the Week 2/Week 3 crossover or
recommend position-specific early weights; it cannot authorize a general ROS
blend because Draft is only a proxy.
