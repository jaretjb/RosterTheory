# OS-010 — Original adaptive terminal identity

Completed September 15, 2026 (America/Los_Angeles).

RosterTheory now has an original "RT" pixel wordmark in amber ANSI for capable
interactive terminals. The same welcome and guided help paths use an ASCII
wordmark when color is unavailable, a one-line mark below 32 columns, and no
added art when stdout is redirected. Selected interactive human Trade and
Waiver reports get only a compact `[RT]` mark. `--no-banner` suppresses both.
The design takes only the broad amber-on-dark inspiration from the supplied
reference; it does not reproduce its name, typography, sprite, or layout.

The mark is applied only while printing human CLI content. JSON, CSV, saved
evidence, logs, diagnostics, error payloads, ordinary argparse `--help`, and
read-only decision behavior remain undecorated and unchanged.

Verification: six snapshot and output-boundary tests cover amber, ASCII,
narrow, redirected, suppressed, welcome/help, compact human reports, and JSON.
The focused CLI suite passed 18 tests; the final repository suite passed all
489 tests. A Windows terminal preview showed the ASCII fallback. No provider
request, Sleeper write, history rewrite, release publication, or ignored-data
deletion occurred.
