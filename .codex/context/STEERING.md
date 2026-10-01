# RosterTheory context router

Updated: September 30, 2026 (America/Los_Angeles)

Select one route; load only its named sections.

Implementation/provider routes also load
`.codex/context/IMPLEMENTATION_POLICY.md`.

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
| Modular redesign | `.codex/context/status/MODULAR.md`; requested modular document sections; implementation also loads active milestone and selected migration contract |
| Open-source release planning | `docs/OPEN_SOURCE_RELEASE_TASKS.md` |
| Open-source release implementation | Selected `docs/OPEN_SOURCE_RELEASE_TASKS.md` row, `.codex/context/ACTIVE_MILESTONE.md`, and `.codex/context/IMPLEMENTATION_POLICY.md` |
| Terminal experience design or planning | Only relevant sections of `docs/TERMINAL_EXPERIENCE_DESIGN.md` and selected `docs/TERMINAL_EXPERIENCE_TASKS.md` row |
| Terminal experience implementation | Selected `docs/TERMINAL_EXPERIENCE_TASKS.md` row, `.codex/context/ACTIVE_MILESTONE.md`, `.codex/context/IMPLEMENTATION_POLICY.md`, and only design sections it names |
| Repository/process work | Only files directly in scope; do not load product status |
| Project-wide status, priorities, or “what's next?” | `.codex/context/DEVELOPMENT_STATUS.md`, then only the backlog row or track status it names |
| Historical audit | Only the named public record; use private local evidence solely when the user explicitly requests it and it is available |

Only
`.codex/context/ACTIVE_MILESTONE.md` authorizes implementation.

## Git workflow

Use separate branches and PRs; never commit/push to `main` or bypass protection.

Keep assistant policies separate. Share only neutral providers, identity,
scoring, projections, lineups, replacement, risk, provenance and evidence.
Recommendations are read-only; never submit Sleeper actions. Presentation must
preserve decision policy and evidence.

Forecast completeness is position-aware across Draft, Trade and Waiver.
Omitted off-role/rare stats must not block; supplied stats still count.
Missing core stats and invalid values remain explicit.
See `docs/POSITION_FORECAST_COVERAGE.md`.
