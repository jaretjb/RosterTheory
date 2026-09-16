# Completed Trade Assistant Phase 0: activation and baseline

Completed: September 4, 2026 (America/Los_Angeles)

## Activation evidence

- League Beta development is formally handed off in
  `docs/COMPLETED_LEAGUE_BETA_DRAFT_ASSISTANT_MILESTONE.md`; its time-sensitive
  September 7 work remains an operational runbook.
- The user approved activating Trade implementation on September 4.
- `.codex/context/ACTIVE_MILESTONE.md` now names the bounded Phase 1 provider and data
  feasibility milestone. Draft and Trade do not coexist as implementation
  milestones.

## Clean baseline

- Runtime: Python 3.11+ standard-library local application.
- Test command: `$env:PYTHONPATH = "src"; python -m unittest discover -s tests -v`.
- Result: 175 tests passed on September 4 in 3.594 seconds.
- Source baseline: 23 top-level `roster_theory` modules, one CLI composition
  root, and no `core`, `providers`, or `trade` package yet.
- Dependency shape: top-level Draft modules import one another through
  `roster_theory.*`; `cli.py` is the main composition surface. New Trade code
  must be additive, and feature-neutral extraction must retain these
  compatibility imports until regression evidence permits a change.
- The working tree contains the requirements, design, task-list, steering, and
  milestone documentation changes accumulated during this planning effort.
  No source or test behavior changed during Phase 0.

## Approved filesystem namespaces

| Concern | Namespace | Policy |
| --- | --- | --- |
| Versioned Trade configuration | `config/trade/` | Small, non-secret, reviewed inputs only |
| Provider cache | `data/cache/trade/` | Ignored, reproducible, freshness-controlled |
| Reports and evidence | `data/exports/trade/` | Ignored, reproducible/personal |
| Manual licensed/personal input | `data/manual/trade/` | Ignored; never treated as silently complete |
| Minimized test fixtures | `tests/fixtures/trade/` | Versioned, synthetic or license-safe |
| Trade tests | `tests/test_trade_*.py` | Discoverable by the existing unittest command |
| Product code | `src/roster_theory/trade/` | Trade policy only |
| Shared code targets | `src/roster_theory/core/`, `src/roster_theory/providers/` | Feature-neutral contracts only |

The existing `.gitignore` entries for `.env`, `data/cache/`, `data/exports/`,
and `data/manual/` already cover all personal Trade subdirectories. No
database, framework, hosting surface, or new secret location is approved.

## Phase 0 gate

Passed. League Beta has a safe operational handoff, one Trade milestone is active,
the baseline suite is green, and the namespaces do not collide with Draft.
