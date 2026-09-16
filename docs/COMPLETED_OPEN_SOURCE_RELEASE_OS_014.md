# OS-014 — Runtime-input inventory and authority contract

Completed: September 16, 2026 (America/Los_Angeles)

OS-014 defines one season-aware `roster-theory inputs` namespace and a stable
`roster-theory.inputs/v1` JSON result. Normal Draft, Trade, and Waiver commands
will invoke the same prepare planner automatically: fresh inputs are reused,
stale fetchable evidence is refreshed within provider budgets, and missing
human decisions fail with an exact scaffold/import action.

The inventory in `docs/RUNTIME_INPUT_CONTRACT.md` covers league configuration,
all league policies, historical accuracy, current expert pools and overrides,
preseason/weekly/rest-of-season rankings, projections, ADP, news, Waiver Wire
evidence, schedule/byes, player identity, and current Sleeper state. Every row
declares authority, scope, horizon, freshness, default ignored path, producing
command behavior, and fail-closed behavior.

Provider facts are separated from user decisions. Trusted-expert membership,
overrides, and league calibration can be scaffolded, imported, and validated,
but never silently inferred. Two synthetic v1 fixtures prove that raw provider
evidence may be shared while policies, derived evidence, and results remain
league-scoped.

The NFL schedule source decision uses nflverse's schedule release under CC BY
4.0. Follow-on implementation must pin the downloaded asset, retain attribution
and full provenance, validate complete season/team/bye coverage, and keep real
schedule data in ignored local storage. If source/license/schema validation
fails, the command must use the documented import path rather than scrape or
retain an unproven hand-edited file.

Validation:

- `python -m unittest tests.test_runtime_input_contract`
- complete `unittest` suite

No assistant decision behavior, provider call, private data, or Sleeper state
was changed by this contract task.
