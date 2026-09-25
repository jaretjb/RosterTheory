# AC-005 — Ranking caps and specialist performance policy

Implemented September 25, 2026; issue #11.
[PR #19](https://github.com/jaretjb/RosterTheory/pull/19) awaits review/merge.
Prerequisites: AC-003 merged in PR #17; AC-004 merged in PR #18.
The overall reliability audit remains open: AC-006–AC-008 are not implemented.

## Weekly evidence contract

Universal weekly positional caps are RB/WR 50, QB/TE 24, and K/DST 16.
The smaller caps reflect the narrower specialist/one-slot pools; they are explicit
product policy, not historically calibrated thresholds. These caps cannot be
overridden per league. Rank 50 is usable for RB/WR; 51 is not a weekly signal.
Omitted ranks remain visible as raw evidence and receive an exclusion reason.
They do not make an entire player or report disappear.

Weekly normalization uses the fixed cap rather than the provider's observed tail.
Replacement rank remains independently derived from league ownership; the
fallback with no owned players is half the positional cap. Rostered players retain
the separate below-replacement weekly exclusion and injury/ROS protection.
Fresh-rank overrides and search ranking explanations/tiebreakers also respect caps.
ROS and actual-production evidence are not weekly ranking tails and retain their
separate horizons. Adding only ignored weekly tail entries cannot move a score.
Equal production totals and equal panel aggregate ranks retain competition ties
(1, 1, 3), without player-ID-created differences.

## Specialist decision contract

`NORMALIZED_SEASON_V1` applies to every league. Actual Sleeper season statistics
are scored using that league's scoring rules. For same-position K/DST comparisons:

- Weekly advantage: `(drop_weekly_rank - add_weekly_rank) / 15`, with both ranks
  inside the K/DST cap.
- Production advantage: `(add_total - drop_total) / max(abs(add_total), abs(drop_total))`,
  clipped to [-1, 1]; two zero totals have zero advantage.
- Sample confidence: `n / (n + prior_games)`, where `n` is the smaller observed
  played-game count. Default `prior_games` is 2.
- Combined advantage: `(1 - weight) * weekly_advantage + weight * confidence * production_advantage`.
  Defaults are K 0.75 and DST 0.40. Positive scaling of scoring leaves this
  comparison unchanged. Season totals, not PPG, remain the performance signal;
  bye/sample differences are displayed rather than converted to fictitious games.

These defaults are manually chosen policy, fixture-tested but **not historically
calibrated**. Missing game counts are unknown. Season/recent sample counts and
capture timestamps survive input serialization; zero-game weekly rows are not
counted as games. Comparisons require both captures within the previous 72 hours.

A complete projection path still requires its current-week (and DST rolling)
improvement floors. When a fresh production comparison is available, a negative
balance blocks that path. Alternatively, a strictly positive complete sampled
rank/production comparison can approve a move. Its distinct `K_RANK_PERFORMANCE`
or `DST_RANK_PERFORMANCE` path explicitly discloses that projections do not prove
the required streaming improvement. Reversal conditions match the chosen path.
Missing/stale performance does not stop the report: a complete projection-only
path can proceed with a disclosure. Cross-position moves use lineup evidence and
retain all prior cross-position safety gates; positional totals are not compared.

Priority uses the available normalized production balance, otherwise a bounded
projection-only advantage. It never takes the maximum of raw rank and point
scores. Exact decision evidence records basis, raw projection priority, normalized
components, game counts, timestamps, coverage and historical-calibration limits.

## Overrides and compatibility

Absent specialist weights use the universal defaults. Explicit weights require
`special_teams.method: "NORMALIZED_SEASON_V1"` and finite fractions satisfying
`0 < dst_season_points_weight < kicker_season_points_weight < 1`.
`prior_games` must be finite and positive. Unknown specialist/priority keys,
unsupported methods, nonfinite configuration and disabling universal retention
are rejected. Legacy raw-point weights require explicit migration rather than
silently changing their units. Existing projection thresholds remain league-point
thresholds and must be set in that league's scoring units.

The ignored local policy using raw multipliers was migrated to the new
method/defaults; the other local policy already omitted weights and receives the
same universal defaults. Both local policies load successfully. No league outcome or empirical
calibration was transferred. Ignored local policies are not committed.

Input schema 9 writes the new metadata; input schemas 1–8 remain readable with
unknown samples. Exact evaluation schema is 17, advertised by search artifacts.

## Verification

Regressions were introduced before implementation. Coverage includes every cap
boundary, ignored weekly tails, replacement independence, finite values and
override migration, early/late/bye/missing samples, scoring scales, ties/changed
IDs, missing projections, projection/production conflicts, truthful reasons,
timestamp freshness, independently constructed league-policy fixtures and input
round trips. Existing cross-position and candidate safety suites remain intact.

Verification: 762 tests pass, including 16 new targeted AC-005 regressions;
Ruff and diff checks pass. Focused ranking/policy/joint-plan validation: 68 tests pass.
No live report, paid provider refresh, Sleeper write or historical backtest ran.
Historical streaming performance remains explicitly unproven.
