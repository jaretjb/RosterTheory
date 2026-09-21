# TA-1307 — Target-first Trade CLI handoff

Completed September 21, 2026 (America/Los_Angeles) on
`codex/ta-1307-target-presentation`. This is read-only presentation and
orchestration; it does not change the intrinsic evaluator or submit an offer.

`trade targets` now performs one prepared current refresh and target discovery
only. `trade search` uses that identical target evidence, then runs the exact
target-lane optimizer. Compact output leads with `BUY LOW`, `SELL HIGH`,
`CONSOLIDATE`, and fallback `NEED FIT` cards, including `WATCH` cards without
an offer. Offers follow under their generating target and print separate
intrinsic and market outcomes, user/partner lineup and depth effects, weekly
and risk deltas, add/drop consequences, and a provisional reversal condition
when available. Missing chart/performance data is labeled; no offer is called
obtainable or assigned an acceptance probability.

The canonical saved JSON includes target and package evidence with a wrapper
hash. `--snapshot` verifies it and labels replay `OFFLINE/NON-CURRENT` without
live preparation. Optional CSV includes flat target and offer summary rows;
even an empty result retains a stable header. Machine JSON remains one stdout
value, with saved-path notices on stderr. The commands preserve expert-pool,
decision/target-policy, risk, search-budget, authorized chart-import, and
explicit `ECR-PROXY` overrides. A local import bypasses the live chart GET.

Both commands require a separately supported, league-scoped `trade_target`
policy, selectable from league config or `--target-policy PATH`; there is no
fixture premium or cross-league policy default. A policy has
`target_discovery` fields for `TargetDiscoveryConfig` and, for `search`,
`target_optimizer` fields for `TargetOptimizerConfig` plus either all 16
`exact_budgets` or `uniform_exact_budget`. Existing `trade_decision` policy
continues to govern exact evaluation. The configured leagues have not yet
been calibrated for this new policy; until TA-1308 supplies it, the commands
stop as `uncalibrated`. This is a deliberate readiness boundary, not a claim
that a live target search is ready.

Synthetic integration and CLI fixtures verify card/search evidence identity,
target-before-offer ordering, both decision axes, `WATCH`, proxy degradation,
JSON/CSV output, tamper detection, replay without preparation, and clean
machine output. All 624 unit tests and Ruff pass. No live provider request,
league operation, Sleeper write, secret, or licensed bulk player row was used.
