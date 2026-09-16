# RosterTheory agent instructions

## Context loading

At the start of a task, read only `.codex/context/STEERING.md`. Select exactly one route
from its table, then load only that route's status file and named sections. Do
not read `.codex/context/DEVELOPMENT_STATUS.md`, every status file, a whole backlog, a
design document, a completed milestone, a runbook, or private history evidence
unless the selected route explicitly requires it.

Use `rg` headings and task IDs to load selected sections rather than whole long
documents. Do not duplicate a route's context “just in case.” Only
`.codex/context/ACTIVE_MILESTONE.md` authorizes product implementation.

For implementation or provider/data operation, also load
`.codex/context/IMPLEMENTATION_POLICY.md`. It contains the conditional working, API,
testing, and handoff rules and is not general startup context.

## Always-on boundaries

- Never transfer a league's calibration or result to another league without
  separate evidence.
- Product-track boundaries live in `.codex/context/STEERING.md`; Draft, Trade, Waiver,
  and future-assistant policy must not leak across them.
- Never make a Sleeper pick, submit a trade, place a waiver claim, or change a
  lineup. Recommendations are read-only.
- Never print, commit, or copy the FantasyPros API key. Read it only from
  ignored `.env` or `FANTASYPROS_API_KEY`.
- Report unmatched, ambiguous, partial, or unavailable data; never silently drop it.
- Expert rankings are authoritative; the model must not invent them.
- A ranking is authoritative only for its declared decision horizon: preseason
  draft, rest of season, or a specific week.
- Calculate projections from each league's actual Sleeper scoring.
- Use ordinary code for simulation; AI orchestrates and explains.
