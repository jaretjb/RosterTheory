# Completed OS-009 — Interactive and machine-output contract

Completed: September 14, 2026 (America/Los_Angeles)

## Outcome

The CLI now detects interactive stdout, terminal width, ANSI support, Windows
virtual-terminal capability, `TERM=dumb`, `NO_COLOR`, and redirection in one
standard-library module. Redirected and JSON output never uses color; existing
human-readable watcher reports retain their format and decision behavior.

Every command with `--json` emits one strict JSON value when it finishes.
Trade saved-path and CSV notices move to stderr in JSON mode. The watcher
collects displayed poll reports into one final JSON object with `reports`,
`polls`, `termination`, and `status`; human mode still displays polls live.
The CLI guards against stray stdout and reports it as `output_error`.

Expected machine failures preserve `status`, `reason`, `error_type`, and command
context. Typed statuses distinguish uncalibrated league policy, unavailable
source/capability, incomplete evidence, and stale evidence. Parser errors also
return JSON when `--json` is requested. Exit codes are 0 for completion, 2 for
expected/argument/output failures, 1 for unexpected internal exceptions, and
130 for interruption. The contract is documented in `docs/CLI_OUTPUT_CONTRACT.md`.

## Validation

- Covered JSON success output for all seven Trade/Waiver decision commands and
  verified saved-path notices are outside stdout.
- Covered uncalibrated, unavailable, incomplete, stale, and ambiguous failures
  with intact reasons; parser errors and stray-output rejection were also
  checked from an arbitrary working directory. A real Python subprocess also
  returned exit code 2 for a runtime JSON failure.
- Covered piped, narrow, `NO_COLOR`, `TERM=dumb`, and Windows/Linux capability
  behavior. The human watcher output was compared with its existing formatter;
  one-poll, multi-poll, and interrupted JSON watcher output were checked.
- `python -m unittest discover -s tests -q`: 483 tests passed.
- No provider request, Sleeper write, publication, history rewrite, or ignored
  evidence deletion occurred.
