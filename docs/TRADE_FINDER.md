# Trade finder usage and configuration

`trade search` finds player trades using your league's scoring, current
ownership, selected expert weights and football decision policy. It searches
ordinary roster upgrades as well as opportunities identified by target cards.
Recommendations are read-only.

## Choose a search scope

```text
roster-theory trade search home_league
roster-theory trade search home_league --opponent 3
roster-theory trade search home_league --opponent "Team name" --time-budget-seconds 180
```

League search defaults to a 120-second search budget. Single-opponent search
defaults to 300 seconds. `--opponent` accepts a roster ID or an exact,
case-sensitive displayed team name, including its spaces. Roster IDs take
precedence. Self, unknown and ambiguous opponents are rejected with valid
choices. Scope is resolved before roster diagnosis and target discovery.

Both modes construct all nine shapes with one to three players on each side.
League mode uses every eligible rostered skill player for one-for-one trades;
larger packages use the player pools configured in the league's search policy.
Single-opponent mode uses both full eligible rosters. Missing player prices or
roster coverage remain explicit exclusions. The full league snapshot, common
value boards and free-agent universe remain the valuation inputs in either mode.

Provider/input preparation has its own reported timer. The search budget
includes fresh target discovery, package construction, exact evaluation and
repair work. Deadline checks occur during computation; preparation, the next
checkpoint and report writing can make total command time longer than the
budget. Only completed evaluations are published.

## Read the results

The finder returns up to ten supported ideas. It can return fewer when the
completed evaluations do not support ten. The result labels mean:

| Label | Meaning |
| --- | --- |
| `RECOMMENDED` | Passes the existing exact evaluator and search gates. |
| `NEGOTIATION_CANDIDATE` | Improves both lineups and passes user value, risk, depth, evidence, legality, chart fairness and partner usefulness checks. Its sole failed strict gate is the opponent's consensus-value floor; its strict verdict remains `COUNTER`. |
| `COUNTEROFFER_IDEA` | A complete, legal strict `COUNTER` that passes user value, risk, depth, minimum lineup gain and roster checks. The partner remains within the existing lineup/depth policy, and every incoming asset has a useful role. Remaining price/value checks show what needs to change. |

Negotiation candidates and counteroffer ideas are starting points for review,
not passing offers or predictions that another manager will accept. Incomplete,
illegal, declined, ECR-proxy and prior-week chart cases remain diagnostics and
do not fill the ranked list.

The finder ranks by result tier, user lineup gain, opponent lineup gain,
downside, chart-price distance, asset count and stable IDs. League results
choose an opponent representative before filling the remaining slots. Player
names, both lineup gains, required adds/drops and failed checks are visible in
the human report. JSON and CSV retain the detailed evidence.

Before exact evaluation, both teams must retain their existing viable coverage
for dedicated starter positions using the actual exchanged assets. An assumed
waiver addition cannot rescue a package that strips that coverage. Known
existing shortages remain disclosed; the package cannot worsen them.

The existing Trade rule permits one reserve at a position with exactly one
eligible starting slot. After required drops, an exchange that increases that
position's player count beyond two is filtered. This excludes adding a third
quarterback in a one-QB league, while preserving QB-for-QB exchanges and using actual slot
capacity in superflex or multi-QB leagues. Required drops are checked again
after exact evaluation. Construction allows a required drop to resolve excess
depth only when the actual exchanged assets already preserve starter coverage.

Incoming-player usefulness is measured conditional on the full final roster:
remove each acquired player in turn and measure lost lineup points or usable
depth above waivers. Both teams' incoming assets must clear the existing
asset-use thresholds. Starting the player in a few modeled weeks does not by
itself prove useful marginal value. The cheap queue estimate also scores the
QB bundle jointly rather than adding improvements that compete for one slot.

The finder records `trade-finder-roster-v1` separately from the unchanged
expert weights, football thresholds and execution profile. User-loss and
implausible partner cases remain diagnostics even when their raw projected
point change is positive.

For a counteroffer idea, the finder can evaluate up to three direct repairs
that add, remove or substitute one asset. Repairs use the same evaluator and
stay within three players on each side. They share the deadline and evaluation
caps; repair results do not generate further repairs. An unfinished repair is
reported as unfinished, not as a failed offer.

## Control execution

`--time-budget-seconds` overrides the selected mode's budget with a finite,
positive number. `--max-results` accepts 1 through 10.

Optional caps apply separately to each opponent/package-shape queue:

- `--max-exact` caps one-for-one and two-for-one attempts.
- `--max-large-exact` caps each of the other seven shapes, including
  three-for-one.

Repair attempts count against the cap for their resulting package shape. A
zero cap disables attempts for the affected shapes. Without these flags,
fresh finder search uses the time budget rather than the legacy optimizer's
uniform or lane/shape evaluation limits.

The optional top-level `execution_profile` in an existing league-local
`trade_target` policy controls execution defaults:

```json
{
  "execution_profile": {
    "version": "trade-finder-execution-v1",
    "league_seconds": 120.0,
    "opponent_seconds": 300.0,
    "max_ideas": 10,
    "repairs_per_counter": 3
  }
}
```

This is a configuration excerpt, not a complete search-policy file. Keep the
existing league identity, season, discovery and optimizer settings. Budgets
must be finite and positive, `max_ideas` must be 1-10, and
`repairs_per_counter` must be 0-3. Older policies without this section load the
defaults above. Execution controls do not recalibrate expert weights, price
bands, premiums, risk, depth or decision thresholds.

Fresh search requires a league-scoped `trade_target` policy, configured in the
league settings or selected with `--target-policy PATH`. A missing search
configuration does not mean previously chosen expert weights were lost. The
failure reason identifies the missing configuration; the existing machine
failure status remains `uncalibrated`.

## Check coverage and replay

Reports disclose the scope, execution profile, timers and termination reason.
Per-opponent/shape coverage separates enumerated pairs, price pruning,
constructed eligible packages, attempts, completed evaluations, errors,
unevaluated packages, unfinished construction, explicit caps and pool limits.
Roster pruning has its own count and per-reason totals; a package can fail
multiple checks. Saved rejection samples retain up to three examples per
opponent, shape, stage and reason. Completed package checks retain exact failed
gates and incoming-use evidence. Repairs apply the same rules, and a
roster-pruned repair has no exact verdict or evaluation hash.
`TIME_BUDGET` or `EXACT_CAP` means further work remains. `EXHAUSTED` describes
the constructed search domain; configured pools and bounded add/drop search
still limit coverage. Unevaluated packages may contain better trades.

```text
roster-theory trade search home_league --snapshot PATH
```

Use the saved evidence path for `PATH`. New timed manifests verify and replay
recorded completed results without rerunning a timer. Legacy saved reports
retain their offline loader. Replays are non-current and non-actionable.

For development comparisons,
`scripts/benchmark_trade_finder.py MANIFEST EVIDENCE --output PATH` restores
verified saved inputs at the original evidence time. Add `--opponent ID` and
`--seconds NUMBER` to select scope and budget. It reuses saved target discovery,
so its search timing measures construction and evaluation rather than a fresh
end-to-end command. It never refreshes providers or submits a transaction.

See [TA-1316 validation](COMPLETED_TRADE_ASSISTANT_TA_1316.md) for the roster and
counteroffer corrections, [TA-1315 validation](COMPLETED_TRADE_ASSISTANT_TA_1315.md)
for the original timed finder's recorded benchmarks and tests, and the
[Trade design](TRADE_ASSISTANT_DESIGN.md#11-league-wide-search)
for the execution contract.
