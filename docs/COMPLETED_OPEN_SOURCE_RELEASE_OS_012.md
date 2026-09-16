# OS-012 — Consistent reports and interactive progress

Completed September 15, 2026 (America/Los_Angeles).

The human-only reporting layer frames supported Draft, Trade, and Waiver
decision commands in the same order: league and decision horizon, readiness,
result, warnings, limitations, existing detailed evidence, then saved paths.
Incomplete results and unavailable failures are explicit; uncalibrated failures
retain their existing machine-readable stderr payload. The
original expert horizon, league-scoped provenance, calculations, recommendation
labels, and serialized evidence are not rewritten by presentation code.

Draft simulation and FantasyPros board refresh show restrained, cancellable start
and end messages only on interactive human stdout. JSON and redirected output
remain free of progress text; the Sleeper read-only boundary is unchanged.

Verification: focused wide/narrow, color/plain, success/degraded/uncalibrated,
silent machine/piped, failure, and Ctrl-C tests, plus the complete 502-test
suite, pass. The next planned release task is OS-005.
