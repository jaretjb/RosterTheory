# RosterTheory context router

Updated: September 14, 2026 (America/Los_Angeles)

Read this file alone at startup. Select one route from the user's request and
load only that row. A `section` or `task row` means targeted heading/ID lookup,
not the whole document.

Implementation and provider/data-operation routes also load the short shared
rules in `.codex/context/IMPLEMENTATION_POLICY.md`.

| Route | Load after this file |
| --- | --- |
| Waiver status or work | `.codex/context/status/WAIVER.md` |
| Waiver requirements or design | Waiver status, then the requested sections of `docs/WAIVER_ASSISTANT_REQUIREMENTS.md` or `docs/WAIVER_ASSISTANT_DESIGN.md` |
| Waiver planning | Waiver status plus only the selected row in `docs/WAIVER_ASSISTANT_TASKS.md` |
| Waiver implementation | Waiver status, `.codex/context/ACTIVE_MILESTONE.md`, selected task row, and only sections explicitly referenced there |
| Trade status or work | `.codex/context/status/TRADE.md` |
| Trade requirements or design | Trade status, then requested sections of `docs/TRADE_ASSISTANT_REQUIREMENTS.md` or `docs/TRADE_ASSISTANT_DESIGN.md` |
| Trade planning | Trade status plus only the selected row in `docs/TRADE_ASSISTANT_TASKS.md` |
| Trade implementation | Trade status, active milestone, selected task row, and only explicitly referenced sections |
| Draft status or work | `.codex/context/status/DRAFT.md` |
| Draft planning or implementation | Draft status, selected `docs/OPEN_TASKS.md` row, then active milestone for implementation only |
| Shared architecture | Only relevant sections of `.codex/context/PROJECT_CONTEXT.md` and affected track status files |
| Open-source release planning | `docs/OPEN_SOURCE_RELEASE_TASKS.md` |
| Open-source release implementation | Selected `docs/OPEN_SOURCE_RELEASE_TASKS.md` row, `.codex/context/ACTIVE_MILESTONE.md`, and `.codex/context/IMPLEMENTATION_POLICY.md` |
| Terminal experience design or planning | Only relevant sections of `docs/TERMINAL_EXPERIENCE_DESIGN.md` and selected `docs/TERMINAL_EXPERIENCE_TASKS.md` row |
| Terminal experience implementation | Selected `docs/TERMINAL_EXPERIENCE_TASKS.md` row, `.codex/context/ACTIVE_MILESTONE.md`, `.codex/context/IMPLEMENTATION_POLICY.md`, and only design sections it names |
| Repository/process work | Only files directly in scope; do not load product status |
| Project-wide status, priorities, or “what's next?” | `.codex/context/DEVELOPMENT_STATUS.md`, then only the backlog row or track status it names |
| Historical audit | Only the named public record; use private local evidence solely when the user explicitly requests it and it is available |

Never preload all track files, whole backlogs, full designs, completed records,
runbooks, or private local history evidence. Only
`.codex/context/ACTIVE_MILESTONE.md` authorizes implementation.

Keep Draft, Trade, Waiver, and future-assistant policy separate. Shared code may
own only feature-neutral provider, identity, scoring, projection, lineup,
replacement, risk, provenance, and evidence behavior. All recommendations are
read-only; never submit a Sleeper action.
Terminal presentation work must not change decision policy or evidence.
