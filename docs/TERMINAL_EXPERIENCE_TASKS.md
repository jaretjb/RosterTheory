# Roster Theory terminal experience task backlog

Updated: September 15, 2026 (America/Los_Angeles).

Scope: implement the proposed visual and human-report design in
docs/TERMINAL_EXPERIENCE_DESIGN.md. This is a new planned refinement after
completed OS-009 through OS-012. It does not reopen those records, activate a
milestone, or alter OS-006/OS-013 release dependencies. Schedule one task at a
time through .codex/context/ACTIVE_MILESTONE.md before implementation.

All tasks are presentation-only: no policy, provider, simulation, scoring,
evidence, exit-code, or Sleeper write changes. Preserve league-local Draft,
Trade, and Waiver boundaries.

| Task | Outcome | Depends on | Status |
| --- | --- | --- | --- |
| TX-001 | Terminal visual primitives and output boundaries | OS-009, OS-010 | complete |
| TX-002 | Full Roster Theory wordmark and command mastheads | TX-001 | complete — arcade amendment |
| TX-003 | Doctor health-board human view | TX-001, TX-002 | complete |
| TX-004 | Shared human report and failure grammar | TX-001, TX-002 | planned |
| TX-005 | Draft report adapter | TX-004 | planned |
| TX-006 | Trade report adapter | TX-004 | planned |
| TX-007 | Waiver report adapter | TX-004 | planned |
| TX-008 | End-to-end QA, documentation, and release decision | TX-003, TX-005, TX-006, TX-007 | planned |

## TX-001 — Terminal visual primitives and output boundaries

Design sections: 2, 3, 6.

- Define deterministic palette/status tokens, original border motifs, full
  width tiers, wrapping, ANSI-width handling, and ASCII/NO_COLOR fallbacks in
  terminal.py without a new production dependency.
- Keep redirected human text readable but undecorated; keep --json, CSV,
  evidence, logs, and error payloads free of art and ANSI.
- Inventory current machine-first commands and legacy human stderr payloads;
  preserve unflagged redirected output and explicit --json while specifying
  interactive-only human behavior in docs/CLI_OUTPUT_CONTRACT.md.
- Snapshot-test wide, standard, compact, narrow, redirected, Unicode-disabled,
  Windows VT, NO_COLOR, and --no-banner cases.

Stop: rendering capabilities are stable and machine output is unchanged.

## TX-002 — Full Roster Theory wordmark and command mastheads

Design sections: 2, 3.

- Build and visually review bespoke fixed-width glyphs spelling both words,
  plus the bordered full-name and plain full-name variants. No surface may
  leave RT as the only visible brand.
- Show hero identity on bare launch, guided help, and Doctor; show a
  command-labeled full-name masthead on routine interactive human commands
  and a small masthead on interactive command-specific help.
- Render art once per command, not on every progress tick. --no-banner
  suppresses decoration without removing the command title or status.
- Add CLI snapshot tests for all named command surfaces and fallbacks.
- Amendment: use bright arcade yellow, render `ROSTER` and `THEORY` as stacked
  large pixel words on capable terminals, carry a restrained 1980s video-game
  scoreboard language into command mastheads, and remove the `read-only`
  marketing tagline from the logo asset. Safety boundaries remain in factual
  command output where operationally relevant.
- README artwork refinement: enlarge and thicken the title with a hard-edged
  1990s arcade extrusion, vertically rebalance `ROSTER`, and place `FANTASY
  FOOTBALL ASSISTANT` immediately above the Draft/Trade/Waiver mode line.
- Console alignment: carry that product descriptor and mode hierarchy into
  wide, standard, compact, and narrow interactive heroes without changing
  redirected or machine output.

Stop: the brand is obvious, original, legible, and present early without
contaminating automation.

## TX-003 — Doctor health-board human view

Design section: 4.

- Keep audit_setup, its JSON shape, local-only checks, redaction, provider
  call count, and Sleeper write count unchanged.
- Render a bordered Doctor/offline/read-only heading, global setup summary,
  per-league Draft/Trade/Waiver data-only versus decision matrix, all
  non-ready findings, deterministic next actions, and a clear freshness/
  calibration caveat.
- Group findings by Setup/Draft/Trade/Waiver. Add --details for every check
  row in human mode; JSON shape stays unchanged. If ready rows are summarized
  by default, state the count explicitly.
- Test missing config, wrong-league policy, partial inputs, two synthetic
  leagues, long reasons, selected-league and all-league modes, narrow output,
  --json parity, redaction, and zero external operations.

Stop: a first-time user can find the next safe action at a glance without
mistaking local readiness for a recommendation.

## TX-004 — Shared human report and failure grammar

Design sections: 3, 5, 6.

- Extend feature-neutral ReportFrame presentation with full-name command
  masthead, status/result panel, important facts, blockers, limitations,
  safe next action, and deduplicated saved-path footer.
- Add compact human failure treatment on stderr for missing, invalid,
  unavailable, stale, incomplete, and uncalibrated states in interactive
  terminals; preserve exact status, reason, explicit --json payload,
  unflagged redirected machine payload, and exit code.
- Give current machine-first commands human cards on an unflagged TTY,
  preserve their redirected output, and add explicit --json where missing.
  Record the intentional mode behavior in docs/CLI_OUTPUT_CONTRACT.md.
- Provide adapters with typed facts; never parse rendered prose to infer
  decision results or turn an incomplete search into an affirmative move.
- Snapshot-test status combinations, no action versus cannot recommend,
  wrapping, empty fields, and redirected output.

Stop: human reports are scannable and consistent without changing the facts.

## TX-005 — Draft report adapter

Design section: 5.

- Bring human Draft refresh, boards, simulate, and recommendation reports into
  the shared grammar while retaining draft horizon, authoritative expert
  provenance, league scoring, availability, and incomplete-evidence warnings.
- Keep Draft preference policy and simulation unchanged; compare saved
  artifacts, decision labels, and hashes before and after.

Stop: Draft presentation improves without borrowing Trade or Waiver policy.

## TX-006 — Trade report adapter

Design section: 5.

- Bring human Trade refresh, diagnose, values, evaluate, gaps, and search into
  the shared grammar while retaining both-team outcomes, ranking horizon,
  waiver-relative context, risk, and league-local policy gates.
- Keep exact calculations, package selection, and evidence immutable; test
  uncalibrated, partial, no-package, and degraded scenarios.

Stop: Trade presentation improves without changing bilateral decisions.

## TX-007 — Waiver report adapter

Design section: 5.

- Bring human Waiver refresh, entered evaluation, and search into the shared
  grammar. Distinguish a proved no-action result from unavailable inputs.
- Surface selected-expert versus market evidence, week-specific projection
  coverage, availability/legality, protected drops, and partial/unmatched
  players without inventing ranks or sending a claim.
- Compare decision labels, input/replay hashes, evidence, call plans, and
  Sleeper write count before and after.

Stop: Waiver reports are vivid but conservative and read-only.

## TX-008 — End-to-end QA, documentation, and release decision

Design sections: 1-7.

- Visually inspect full-name glyphs, borders, and Doctor/report specimens in
  Windows PowerShell and a Linux terminal at multiple widths, with ANSI,
  NO_COLOR, ASCII fallback, redirected stdout, and --no-banner.
- Verify all --json commands still produce one valid value, no ANSI, and
  unchanged failure contracts; verify CSV/evidence/replay and decision
  invariants. Run the relevant existing CLI and track tests.
- Update README's terminal-behavior examples only after implementation and
  add synthetic screenshots or transcript specimens without private data.
- Decide explicitly whether the completed refinement enters the public alpha
  candidate; do not silently make it an OS-006 gate or publish the repository.

Stop: the experience is attractive in a capable terminal, readable everywhere
else, and independently verified not to change decisions.
