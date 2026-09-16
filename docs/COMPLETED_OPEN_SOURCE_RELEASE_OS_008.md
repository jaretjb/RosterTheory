# Completed OS-008 — Guided command discovery

Completed: September 14, 2026 (America/Los_Angeles)

## Outcome

Bare `roster-theory` displays a concise welcome and points to guided and full
help with a successful exit. `roster-theory help` groups league setup, Draft,
Trade, Waiver, and provider diagnostics. Each group includes a safe read-only
example, input requirements, and paths to detailed subcommand `--help`.

The guidance distinguishes a configured league from a calibrated decision
policy. It states that decision commands require approved league-specific
policy and that no Sleeper pick, trade, waiver claim, or lineup change is
submitted. The existing top-level and nested `--help` remain intact. The README
command table points new users to both discovery entry points.

## Validation

- From a temporary directory with no league config or FantasyPros key, checked
  bare, guided, top-level, Trade, and nested Waiver help with exit code 0.
- Checked `--config PATH help` before a config exists and invalid-command exit
  code 2. The test uses `python -m roster_theory`, which invokes the same CLI
  entry point as the package console script.
- `python -m unittest discover -s tests -q`: 472 tests passed.
- No provider request, Sleeper write, publication, history rewrite, or ignored
  evidence deletion occurred.
