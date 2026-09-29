# Issue #31: Draft saved-snapshot membership admission

September 28, 2026. Base: merged PR #64 (`b82db25`). This slice closes a
remaining saved-source admission gap. It does not infer Sleeper positional caps
or declare either reference league ready.

## Fantasy-football consequence

Before this change, a saved Draft snapshot could reach board preparation with
missing roster roles, duplicate ownership or an unknown taxi setting. The
reader only rejected a nonempty `taxi` array. It now normalizes all current
rosters and checks their membership against the league's actual roster slots
before admitting the source. A team may still be temporarily over the active
or reserve limit, as [Sleeper permits for drafting and trading](https://support.sleeper.com/en/articles/3956140-can-a-team-go-over-the-roster-limit);
the overage stays in the returned assessment. This does not authorize a
transaction or repair the roster.

The saved Draft snapshot remains schema version 1. A file with explicit zero
taxi capacity can establish empty taxi membership when `taxi` arrays are
absent. If capacity is missing, or required `players`, `starters` or `reserve`
arrays are missing or malformed, the reader rejects it with a read-only refresh
instruction. It also rejects duplicate ownership, unsupported taxi membership,
roster-count mismatches and unknown reserve capacity when reserve places are
occupied. Old files are not rewritten. Replay against their original build
remains available.

## Acceptance and remaining source gap

The prior MA-002d/e/f slices established provider normalization, neutral
membership and capacity assessment, three-feature taxi admission, reserve
eligibility and operation-specific overage behavior. This slice tests saved
Draft admission on both complete reference rosters, with and without an open
active slot and with each league's separate reserve configuration. Synthetic
invalid records and permitted overages exercise the before/after boundary.
Existing MA-001 output goldens and Trade/Waiver policies remain unchanged.

The [Sleeper position-limit help](https://support.sleeper.com/en/articles/5379935-how-do-i-set-positional-limits)
distinguishes positional maximums from roster slots and describes a separate
Draft enforcement toggle. The [public draft API reference](https://docs.sleeper.com/#get-a-specific-draft)
does not identify positional maximum fields, unlimited sentinels or missing
field semantics. The two redacted reference profiles have no verified maximums;
reference A also lacks an enforcement declaration. Both remain LIMITED, and
#31 stays open until fresh league-specific source evidence and a verified API
mapping support independent Draft and in-season admission. Do not substitute
roster slots or Draft acquisition preferences for those maximums.

Rollback: revert this PR as a unit. No source file or saved artifact is
migrated. A rejected old source can be refreshed read-only or inspected with
its original build.

Local verification: 960 tests, Ruff, compilation, 18 context-routing checks,
tracked and staged privacy gates, distribution validation, import and clean
wheel-install smoke pass. PR CI remains the remote gate.
