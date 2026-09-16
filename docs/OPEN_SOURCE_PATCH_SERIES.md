# Open-source review patch series

This document defines the review order for the public candidate assembled during
OS-001. Each changed path belongs to exactly one patch. The patches themselves
are local release-engineering artifacts under ignored `data/manual/` storage;
the repository remains unstaged until the owner chooses how to commit them.

## 01 — Shared runtime and Trade Assistant

Purpose: establish shared call-plan, scoring, provider, in-season evaluation,
and Trade Assistant behavior required by later product patches.

Paths:

- `config/trade/phase7_search_policy.json`
- `src/roster_theory/core/call_plan.py`
- `src/roster_theory/core/lineup.py`
- `src/roster_theory/core/models.py`
- `src/roster_theory/inseason/`
- `src/roster_theory/providers/fantasypros.py`
- `src/roster_theory/providers/sleeper.py`
- `src/roster_theory/trade/`
- `tests/test_trade_search.py`
- `tests/test_trade_snapshot.py`
- `tests/test_trade_value_boards.py`

## 02 — Draft runtime

Purpose: retain reusable draft-board, simulation, mock-evidence, and mock-watcher
capabilities without the completed league-specific experiments.

Paths:

- `src/roster_theory/draft_preferences.py`
- `src/roster_theory/league_boards.py`
- `src/roster_theory/mock_evidence.py`
- `src/roster_theory/mock_watcher.py`
- `src/roster_theory/simulation.py`
- `src/roster_theory/specialist_preferences.py`
- `tests/test_league_boards.py`
- `tests/test_mock_evidence.py`
- `tests/test_mock_watcher.py`
- `tests/test_simulation.py`

## 03 — Waiver Assistant

Purpose: add the generic, read-only Waiver Assistant, its CLI, synthetic policy
fixtures, and tests. This patch depends on patch 01.

Paths:

- `scripts/waiver_live_inputs.py`
- `src/roster_theory/cli.py`
- `src/roster_theory/waiver/`
- `tests/fixtures/waiver/`
- `tests/test_waiver_emergence.py`
- `tests/test_waiver_emerging_policy.py`
- `tests/test_waiver_emerging_value.py`
- `tests/test_waiver_evaluation.py`
- `tests/test_waiver_policy.py`
- `tests/test_waiver_search.py`
- `tests/test_waiver_snapshot.py`
- `tests/test_waiver_walk_forward.py`
- `tests/test_waiver_ww_evidence.py`

## 04 — Public boundary, documentation, and cleanup

Purpose: define the public/private boundary, add synthetic setup material,
remove completed experimental modules from the public surface, and preserve
accurate project steering and release handoff documentation. This patch is
applied last because the documentation describes the completed candidate.

Paths:

- `.gitignore`
- `AGENTS.md`
- `README.md`
- `config/leagues.json` (removed from the public candidate)
- `config/leagues.example.json`
- `docs/`
- `src/roster_theory/guardrail_experiment.py` (removed)
- `src/roster_theory/sleeper.py`
- `src/roster_theory/team_size_experiment.py` (removed)
- `tests/test_context_routing.py`
- `tests/test_sleeper_client.py`
- `tests/test_team_size_experiment.py` (removed)

## Verification result

Completed September 14, 2026:

- 81 changed, non-ignored paths; 81 covered entries; zero missing, duplicate,
  or extra paths.
- The real Git index remained untouched.
- All four patches applied in order to a detached worktree at `HEAD`
  (`6f693eb`).
- On Microsoft Windows NT 10.0.22631.0 with Python 3.13.4, the README's
  `python -m pip install -e .` command completed and CLI help loaded.
- `python -m unittest discover -s tests` passed all 461 tests in the clean
  installed environment.
- A deliberately offline `--no-build-isolation` install could not import
  `setuptools.build_meta` because Python 3.13's fresh virtual environment did
  not bundle setuptools. The normal documented install provisioned the
  declared build backend. Offline build-backend bootstrapping remains outside
  OS-001's release-baseline scope.
