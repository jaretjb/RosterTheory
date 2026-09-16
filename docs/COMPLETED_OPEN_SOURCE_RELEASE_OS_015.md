# OS-015 — Expert evidence and in-season pool refresh commands

Completed: September 16, 2026 (America/Los_Angeles)

## Outcome

`roster-theory inputs experts` now provides `inspect`, `refresh`, `validate`,
and `import` operations. One refresh can create every historical expert input
consumed by the Draft pipeline and the exact CSV schema consumed by Trade and
Waiver. Ordinary paths are season-derived; the in-season pool is also
league-scoped.

The Draft refresh reads five complete FantasyPros accuracy seasons and emits:

- category-level historical accuracy with QB, RB, WR, TE, K, DST, and IDP
  coverage;
- annual overall accuracy for the existing recency model; and
- per-season replay evidence containing the source URL, capture time, payload
  hash, and raw authorized response.

The in-season refresh uses weekly in-season historical accuracy plus current
ROS expert availability. It applies the existing recency, coverage,
freshness, required-position, and publisher-concentration rules. The output
records provider IDs, horizon, weights, freshness, and authority. A separate
machine audit records every selection and rejection reason and explicitly
forbids a preseason-accuracy proxy.

## Safety and usability

- Live plans enforce at least one second between FantasyPros requests and the
  shared 500-request daily budget.
- `--dry-run` performs no provider call or local write.
- `--replay-dir` and `inputs experts import --input DIR` reproduce outputs from
  hash-checked saved provider evidence without API calls or CSV editing.
- Missing access, incomplete five-season coverage, stale current expert
  availability, duplicate/ambiguous identity, wrong horizon, and undersized
  pools fail closed.
- Explicit config, data, evidence, budget, and every output path are supported.
- Reports follow `roster-theory.inputs/v1`, contain no credential or private
  provider/league ID, and always report `sleeper_write_performed: false`.
- Trade and Waiver default to
  `data/manual/policies/{league}/{season}/inseason_experts.csv`; pool results do
  not transfer between leagues.

The README now uses these commands instead of asking users to create category
accuracy or in-season pool CSV data manually.

## Validation

- Focused expert-input, Trade board, Doctor, CLI discovery, and machine-output
  tests pass.
- JSON dry-run and blocked validation were exercised through the installed CLI
  entry path.
- Complete suite: 537 tests pass.

No live provider call was needed for implementation validation. No private
provider data was added, and no Sleeper write occurred.
