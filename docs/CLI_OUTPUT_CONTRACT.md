# CLI output contract

`roster-theory` is a local, read-only decision-support CLI. A command's
`--json` option selects machine output; ordinary help remains human-readable.
`doctor --json` is one redacted offline diagnostic value: it includes check
statuses, affected league keys (or entry numbers for numeric IDs), safe next
actions, and separate Draft/Trade/Waiver local data-only and decision states.
Missing setup is a successful diagnosis, not a provider failure. File and
policy checks never imply fresh evidence or portable calibration.

## Output channels

- Human commands write their report to stdout and expected failures to stderr.
  The existing machine-readable `uncalibrated` failure also appears on stderr
  for human decision commands as one unchanged JSON value.
- Human Draft, Trade, and Waiver decision reports lead with league/horizon,
  readiness, result, warnings, and limitations; detailed evidence follows, and
  saved paths appear last. The framing does not change expert horizons,
  recommendations, calculations, or saved artifacts.
- A `--json` command writes exactly one strict JSON value to stdout when it
  finishes, on success or failure. Saved-path notices and audit diagnostics go
  to stderr. Terminal color and human banners are absent from JSON output.
  Stray stdout becomes an `output_error` JSON result rather than a mixed stream.
- `watch-mock --json` writes one object with `reports`, `polls`, `termination`,
  and `status` when the watcher stops. `reports` preserves each displayed poll's
  full data. The human watcher continues to print its existing live report.
  Use `--once` or `--max-polls` when a script needs bounded completion.
- Explicit `--help` prints argparse help and exits successfully, even when
  another option asks for JSON.

## Exit codes and failure fields

| Code | Meaning |
| --- | --- |
| 0 | Command completed, including help or a bounded watcher poll. |
| 1 | Unexpected internal exception. |
| 2 | Invalid arguments, expected input/data failure, or broken output contract. |
| 130 | Watcher or command interrupted by the user. |

Machine failures include `status` and `reason`. Command failures also include
`product`, `league` when selected, and `error_type`; parser failures include
`command`. Typed statuses are `uncalibrated` for missing or mismatched approved
league policy, `unavailable` for unavailable provider/source capability,
`incomplete` for identity, coverage, or schedule gaps, and `stale` for stale
evidence. Other expected failures use `error`, malformed arguments use
`invalid_arguments`, and the stdout guard uses `output_error`. Unexpected
exceptions use `internal_error`. The full failure reason is preserved so
missing, ambiguous, partial, and unavailable evidence stays visible.

## Terminal detection

Terminal capabilities come from the standard library: stdout `isatty()`,
terminal width (80-column fallback), operating system, Windows virtual-terminal
support, `TERM=dumb`, and the presence of `NO_COLOR`. Redirected stdout never
uses ANSI. `NO_COLOR` disables color even when its value is empty. Width is
detected for narrow terminals without changing watcher decisions or evidence.
Terminal presentation uses deterministic wide (100+), standard (60-99),
compact (40-59), and narrow (below 40) tiers. Unicode border glyphs require an
interactive stream whose declared encoding can represent them; otherwise the
same hierarchy uses ASCII. `NO_COLOR` removes ANSI without removing readable
labels. Redirected human output remains linear and undecorated. `--no-banner`
suppresses decorative art while retaining semantic command titles.

Machine-first commands (`leagues`, `snapshot`, Trade/Waiver refresh, and probe
or export commands) retain their existing JSON/CSV behavior whenever stdout is
redirected. Explicit `--json`, saved evidence, CSV, logs, diagnostics, and
legacy redirected error payloads remain free of art and ANSI. Interactive-only
cards and mastheads never change the underlying value, exit code, provider call
plan, or write count.

Interactive bare launch, guided help, and Doctor use the adaptive full
bright-yellow arcade `ROSTER THEORY` hero, followed by `FANTASY FOOTBALL
ASSISTANT` and the Draft/Trade/Waiver mode line. Routine human commands and
command-specific help use a smaller full-name arcade masthead once per
invocation. Doctor's default human
view shows its offline/read-only boundary, global setup, per-league
Draft/Trade/Waiver data and decision states, every non-ready finding, and a
count of summarized ready checks. `doctor --details` displays every check;
`doctor --json` retains the original redacted diagnostic object without art.
Long Draft simulation and FantasyPros board refresh operations display only a
start/end line with a Ctrl-C hint on interactive human stdout. Progress is
absent from piped and machine-output modes, and cancellation retains exit 130.
