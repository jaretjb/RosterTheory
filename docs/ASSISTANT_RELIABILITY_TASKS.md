# Assistant reliability cleanup

Authorized September 25, 2026 following the Waiver/Trade audit. Work sequentially
in bounded, tested milestones. Every product change requires the named active
milestone, a branch, and a pull request; no Sleeper actions are permitted.

The local detailed audit is `data/exports/assistant-audit-2026-09-25/waiver-trade-audit.md`.
The IDs below preserve its 21 findings without publishing private league evidence.
Shared code owns factual evidence; Waiver and Trade retain separate policy.

## GitHub tracking

| Milestone | Issue | State |
| --- | --- | --- |
| AC-001 | [#7](https://github.com/jaretjb/RosterTheory/issues/7) | Merged in [PR #15](https://github.com/jaretjb/RosterTheory/pull/15) |
| AC-002 | [#8](https://github.com/jaretjb/RosterTheory/issues/8) | Merged in [PR #16](https://github.com/jaretjb/RosterTheory/pull/16) |
| AC-003 | [#9](https://github.com/jaretjb/RosterTheory/issues/9) | Merged in [PR #17](https://github.com/jaretjb/RosterTheory/pull/17) |
| AC-004 | [#10](https://github.com/jaretjb/RosterTheory/issues/10) | Merged in [PR #18](https://github.com/jaretjb/RosterTheory/pull/18) |
| AC-005 | [#11](https://github.com/jaretjb/RosterTheory/issues/11) | Planned |
| AC-006 | [#12](https://github.com/jaretjb/RosterTheory/issues/12) | Planned |
| AC-007 | [#13](https://github.com/jaretjb/RosterTheory/issues/13) | Planned |
| AC-008 | [#14](https://github.com/jaretjb/RosterTheory/issues/14) | Planned |

## AC-001 — Weekly availability and projection provenance

Status: MERGED in PR #15; all CI checks passed. Findings: T1, T2. Dependencies: none.
Acceptance evidence: `docs/COMPLETED_ASSISTANT_RELIABILITY_AC_001.md`.

Correct current-status leakage into future weeks and ensure missing/partial
projection rows never become authoritative zero-point evidence. Carry provenance
through the shared matrix, Trade evaluation, Waiver coverage checks, and provider
normalization. Audited bye/current inactive zeros remain valid only for the week
they establish. Preserve valid future projections and disclose uncertain return
dates; do not invent a season-long absence.

Acceptance: regressions for current OUT/IR/PUP/SUSP, inactive directory rows,
future supplied projections, current/future source omissions, actual zeroes,
audited byes, invalid/nonfinite rows, and explicit partial evaluation. Check the
value-curve boundary so synthetic omissions cannot contaminate rank-slot values.
Unrelated player gaps must not invalidate an otherwise complete projection matrix
subset. Full suite and Ruff must pass. No live data is required for this repair.

## AC-002 — Candidate-scoped safety and transaction legality

Status: MERGED in [PR #16](https://github.com/jaretjb/RosterTheory/pull/16),
all CI checks passed. Findings: W3, W5, T3, D1.
Depends on AC-001 (merged). Evidence:
`docs/COMPLETED_ASSISTANT_RELIABILITY_AC_002.md` (722 tests and Ruff).

Enforce mandatory completeness, lineup/depth/downside, and retention safeguards in
the production Waiver score path. WATCH must identify a plausible move and a
specific reversible blocker. Isolate missing Trade player/ranking coverage instead
of aborting an entire league. Verify drop legality from rules and game state, not
nonzero points. Unknown is not legal; unrelated uncertainty is not a global veto.

Acceptance: production-priority safety probes, severe-loss WATCH rejection,
missing unrelated versus decision-critical players, and zero-point started games.
Add partial-search exclusions and explicit coverage counts, not invented values.

## AC-003 — Joint cross-position optimization and claim plans

Status: MERGED in [PR #17](https://github.com/jaretjb/RosterTheory/pull/17).
Findings: W1, W2, W4, W7.
Depends on AC-002 (merged). Evidence: `docs/COMPLETED_ASSISTANT_RELIABILITY_AC_003.md`.
Verification: 737 tests and Ruff pass; no live league/provider writes.

Allow every legal cross-position drop to compete without a blanket same-position
preference or report filter. Assess the entire add/drop pair. Replace unproved
score-budget dominance with valid bounds or visible budget-limited coverage.
Unify recommendation identity/order and validate cumulative claim branches.

Acceptance: cross-position best-drop fixtures, injury/positional-depth protection,
named-versus-search equivalence, adversarial bounded-versus-exhaustive comparisons,
approved moves present in plans, specialist display not hiding approvals, and
multiple claims whose independent gains cannot safely be combined.

## AC-004 — Consistent Trade decisions and secondary moves

Status: MERGED in [PR #18](https://github.com/jaretjb/RosterTheory/pull/18).
Findings: T4, T5. Depends on AC-002 (merged).
Evidence: `docs/COMPLETED_ASSISTANT_RELIABILITY_AC_004.md`.
Verification: 746 tests, Ruff and diff checks pass. No live report/provider refresh.

Define common intrinsic, market, partner, legality, and confidence axes used by
entered evaluation and target search. Do not reinterpret the same exact package
silently. Select required adds/drops using all gates and retention value, not
lineup ties broken by player ID. Keep missing market pricing visibly provisional.

Acceptance: identical-package verdict parity, independent gate perturbations,
unequal trades, injured valuable bench players, ties, cross-position secondary
moves, and bounded-search disclosure. Waiver-specific policy must not leak here.

## AC-005 — Explicit ranking caps and specialist performance policy

Status: implemented; PR handoff pending. Findings: W6, W8, W9, D4.
Depends on AC-003 (merged). Evidence: `docs/COMPLETED_ASSISTANT_RELIABILITY_AC_005.md`.

Implement the requested RB/WR top-50 weekly evidence cutoff independently of
replacement normalization; document lower positional caps. Separate specialist
projection and rank/performance decision paths and truthful reasons. Make actual
league-scored production more influential for K than DST under an explicit,
scale/sample-aware universal method. Preserve ties, sample sizes, and as-of times.
Do not call manually chosen weights historically calibrated or transfer league
results. Validate finite configuration and supported override semantics.

Acceptance: rank 50/51 and other position boundaries, irrelevant-tail invariance,
early/late-season and bye samples, scoring scales, equal totals/changed IDs,
ranking/projection conflicts, truthful reasons, and independent league fixtures.
Any empirical calibration needing unavailable history remains explicitly unproven.

## AC-006 — Supported scoring formats and season portability

Status: PLANNED. Finding: D3. Depends on AC-001.

Replace hardcoded HALF ranking authority with documented format mapping or visible
unsupported-format handling. Keep league-scored projections independent of expert
identity order. Parameterize season-specific resources and remove implicit league
identity assumptions. Do not invent expert rankings for custom scoring formats.

Acceptance: standard/HALF/PPR, supported QB/premium/flex settings, unknown custom
formats, newly named leagues, and next-season preparation with no stale resource
reuse. Verify provider capabilities against primary documentation before changes.

## AC-007 — Freshness, readiness, provenance, and handoff contracts

Status: PLANNED. Findings: D2, Q3. Depends on AC-002 and AC-004.

Preserve per-source observation/fetch times and scope news coverage honestly.
Use an explicit as-of evaluation contract and revalidate volatile facts before
actionable output. Distinguish incomplete inputs, search limits, candidate
confidence, and informational warnings. Stamp schema/build/policy/scoring/source
provenance; correct affected status handoffs and document calibration limits.

Acceptance: fake-clock long runs, cache age, concurrent ownership changes,
empty-but-complete searches, harmless warnings, and manifest-based replay.
Do not claim complete per-player news from a finite global feed.

## AC-008 — End-to-end release gates and measured optimization

Status: PLANNED. Findings: Q1, Q2. Depends on AC-003 through AC-007.

Add production-path integration and metamorphic regressions across all repaired
contracts. Profile fixed saved/synthetic fixtures, move cheap valid filters ahead
of expensive calculations, cache identical exact packages across lanes without
sharing policy, and reduce duplicated report evidence. Add stage-level timing,
coverage, and cache metrics. Retire superseded code only with behavior coverage.

Acceptance: full suite, Ruff, independent league validation, supported-format
fixtures, bounded/exhaustive comparisons, deterministic replay, output semantics,
and measured before/after runtime/memory/size with unchanged decision coverage.
No claimed speedup without measurements and no hidden recommendation pruning.

## Completion protocol

Each milestone adds regressions before its fix, records focused/full test results,
updates this tracker and only affected status handoffs, and links its pull request.
Close a finding only when every mapped acceptance condition is met. Cross-cutting
tests belong in each repair, not only AC-008. Remaining tasks must stay visibly
open at every tested handoff; completing one milestone does not close the audit.
