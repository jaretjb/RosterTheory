# TA-1308 provisional rollout and deferred calibration

The user approved read-only testing with explicit starting assumptions while
historical calibration evidence accumulates. Separate ignored league-local
`trade_target` policies now provide those assumptions. They are marked
`PROVISIONAL_HEURISTIC` in every target/search report; the 5% 2-for-1 premium,
three-game performance window, and all other thresholds are **not validated**.
Entered-package intrinsic evaluation still does not require a chart.

## Provisional finder behavior

- The normal `trade targets`/`trade search` workflow now prospectively saves
  current-week league-scored projected points to an ignored, hashed league
  history file. It joins only completed outcomes supplied in that file to
  captures from before the player's game. Missing, late, bye, inactive, partial,
  stale, and too-small samples remain visible but cannot support a signal.
- The starting performance policy looks at the last three completed weeks,
  requires two usable games, and shrinks point/rank surprises toward zero with
  a three-game prior. Position scales and the signal threshold are guesses.
  Performance is target context, never an expert-rank rewrite or independent
  offer approval. If no completed outcomes have been imported, the finder
  still runs on intrinsic/market evidence and says performance is insufficient.
- Displayed direct-chart 2-for-1 offers show market-fairness verdicts at 0%,
  5%, and 10% premium (and the configured premium if different). The 5%
  starting premium affects only market construction/fairness, not who wins on
  football value. `ECR-PROXY` never asserts a chart premium.
- Each run saves a feedback CSV beside its hashed JSON evidence. The template
  has target/offer identities and blank fields for your assessment, whether
  you would propose it, an actual response *only if proposed*, and a reason.
  Rerunning the finder will not overwrite filled notes. Responses are not
  acceptance-probability training data.

The `--target-policy` option selects a league's local provisional policy;
`--performance-history` optionally selects its ignored history file. Without
the latter, the finder uses a league/season/scoring-hashed path under
`data/cache/trade/performance/` and prints the chosen path. The public
synthetic policy template is
`config/trade-target.provisional.example.json`; its numbers are illustrative,
not a third league's calibration. The history JSON
has `schema_version`, `league_key`, `season`, `scoring_fingerprint`,
`pregame_expectations`, and `completed_outcomes`. Verified completed rows need
player, week, position, league-scored actual points/rank where available,
availability (`PLAYED`, `BYE`, `INACTIVE`, `PARTIAL`, or `UNKNOWN`), game-start
and completion timestamps, capture time, source, and the same scoring hash.
The finder does not fabricate these rows from current rankings or an unverified
zero-point Sleeper entry.

After verifying completed league-scored results and availability from an
authorized source, import a version-1 JSON containing the same league,
season, scoring fingerprint, and a `completed_outcomes` array:

```powershell
$env:PYTHONPATH='src'
python -m roster_theory.trade.performance_history "PATH_FROM_FINDER" "data/manual/trade_outcomes/verified_week.json"
```

The importer rejects a different league/scoring system, invalid timing,
unverified availability, and conflicting duplicates. It does not fetch or
infer results automatically. Until a verified import exists, recent-performance
support remains unavailable even though the finder captures new expectations.

## Evidence audit (2026-09-21)

Read-only inventory of ignored local trade exports, with no player rows copied:

| League | Snapshot files | Search exports | Value-board files | Capture dates |
| --- | ---: | ---: | ---: | --- |
| League A | 44 | 5 | 39 | Sep 7, 12–15, 18, 2026 |
| League B | 95 | 12 | 77 | Sep 4–5, 9, 12–15, 18, 2026 |

These are repeated operational captures over a short current-season period,
not three or more distinct completed decision weeks with independently labeled
future intrinsic outcomes. The workspace has no TA-1308 input export containing
contemporaneous independent community fairness judgments, leakage-safe
performance-window labels, and controlled exhaustive lane/size search groups.
The 2024–25 draft-proxy backtest is a different decision horizon and cannot
stand in for these trade-market or league-local outcomes. An operational trade
search result is also not evidence that an offer was accepted or fair.

## Reproducible study contract

Run one league at a time, from a separately prepared evidence JSON:

```powershell
$env:PYTHONPATH='src'
python -m roster_theory.trade.calibration data/manual/ta1308/league_a.json data/exports/trade/league_a/ta1308_study.json
```

The JSON schema is version 1, with `league_key`, `scoring_fingerprint`,
`origins`, `intrinsic`, `market`, `performance`, `search`, and `grids` keys.
Every evidence row repeats its league/scoring identity, names an origin, and
retains a source evidence hash.
Origins have distinct, chronological `(season, week)` and timezone-aware
`decision_at` values. At least two earlier origins train each later holdout.
The complete executable fixture is `tests/test_trade_calibration.py`.

- Intrinsic rows contain projected lineup gain, projected downside increase,
  realized later league-scored gain, and both feature and outcome availability
  timestamps. Candidate `edge` and `downside` gates are selected from prior
  outcomes available before each holdout cutoff. The report exposes selected,
  rejected, future-positive, mean gain, and 95% uncertainty estimates.
- Market rows contain contemporaneous chart package values and a distinct
  source's `COMMUNITY_FAIRNESS_ASSESSMENT`, never transaction acceptance.
  Candidate ratio/floor bands and 2-for-1 premium are compared with that
  independent fair/unfair judgment. Agreement and class-balanced agreement
  measure community-price concordance, **not future football value**.
- Performance rows supply point-in-time signals for each candidate window and
  later direction labels. The report gives directional accuracy, abstention,
  and 95% uncertainty. Performance remains context; it does not reorder expert
  rankings or silently override the intrinsic axis.
- Search rows are explicitly complete exhaustive candidate groups by lane and
  package size, with pre-exact heuristic ranks, projected candidate lineup
  gains, lane-signal gaps, exact gains, and measured exact runtime. Each of the
  16 groups gets its own candidate-gate and budget grid, coverage, oracle
  recall, regret, runtime, and uncertainty.

Every holdout records the entire training and holdout grid, the selected
setting, rejected alternatives and rejection reasons. Earlier outcome rows
are excluded until their `outcome_available_at` precedes the next decision.
No axis can borrow data from another league or scoring fingerprint. The output
is hash-addressed and always `NOT_PROMOTED`; a human-reviewed league policy is
a separate step after sufficient holdouts and uncertainty assessment. There
is no shared default and no fitted acceptance probability.

## Deferred empirical promotion (TA-1310)

Prepare separately authorized, provenance-preserving historical exports for
each league with enough distinct decision weeks, completed future outcomes,
independent contemporaneous fairness assessments, performance windows, and
controlled exhaustive candidate groups. Run each league study, inspect
holdout uncertainty and rejected grids, and promote only settings supported
locally. If evidence remains sparse, continue to label the finder provisional;
never turn fixture numbers or one league's results into claimed calibration.
