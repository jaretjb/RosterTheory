# Active milestone

## Active WA-027c - Restore observed historical Waiver scoring

Authorized by the user's September 29 request to run both existing leagues
as soon as possible. Sleeper's played-game historical stat rows omit
zero-valued fields. Compare league-scored results against the same leagues'
official weekly matchup points before interpreting omitted applicable
supported fields as explicit zero. Keep absent rows, absent/invalid game
counts, invalid statistics, and unsupported settings incomplete. Preserve
per-league scoring and source provenance. Rebuild private Waiver inputs,
attempt read-only searches, and report any stale or incomplete inputs and
runtime limit honestly. Keep private values and outputs ignored, provider
support validation separate, and PR #69 open for review. Run focused/full
tests, Ruff, and context/privacy gates.

## Previous WA-027b - Validate the normalized specialist method for existing leagues

Authorized by the user's September 29 correction. Use the normalized K/DST
method for both existing private league policies instead of restoring raw-point
scoring. Compare complete controlled cases, including productive incumbents,
clear upgrades, small samples, and scale changes. Tune each policy separately;
keep numeric settings and backups in ignored private files. Do not claim
empirical accuracy from fixtures or convert old coefficients arithmetically.
Keep PR #69 focused on the read-only Sleeper winners-bracket repair and the
status handoff; remove the proposed raw-method compatibility code. Retry the
requested live Waiver run only if required league-scored evidence is complete.
Do not transfer calibration between leagues, submit a Sleeper action, or
promote provider support. Run focused/full tests, Ruff, context/privacy gates;
update PR #69 and leave it unmerged for review.

MA-005c merged in PR #68. Wider MA-005 and MA-006 support validation remains
separate from this Waiver repair.

Earlier sections preserve the status at the time of those slices. Issue #31
closed after PR #65; their open-issue instructions are historical.

## Previous MA-005c - Check full Waiver search on exact reference profiles (merged PR #68)

Authorized by the user's September 29 request after PR #67 merged, with
tonight's Waiver use in view. Exercise the full candidate search for both
exact synthetic reference profiles, each with a full roster and one open
active slot. Use each profile's own existing controlled-fixture policy,
complete invented three-week inputs, and no provider calls. Check search
completeness, exact evaluation of all eligible adds, legal drop/no-drop
behavior, league and source binding, read-only output, and visible failure
when an add projection is missing. Record the evidence and limits.

Preserve all decision behavior and MA-001 semantic goldens. Do not transfer
policy to another league, certify live provider coverage, promote wider
formats, or run a live Waiver operation. Actual league readiness is a
separate data and policy check. Run focused/full tests, Ruff, context/privacy
gates, then open one PR against main and leave it unmerged. Explain any
necessary behavior correction before implementing it.

## Previous MA-004g - Move Draft preference ownership into the Draft package (merged PR #67)

Authorized by the user's September 29 request after merged PRs #65 and #66.
Move Draft preference records and overlay decisions from the top-level module
to `draft/preferences.py`. Keep CSV reading and strict board matching at the
application boundary in `application/draft_preferences.py`; keep the old
`draft_preferences.py` import path as a compatibility adapter. Update safe
internal imports to the new owners without introducing cycles.

Preserve preference file validation, league scope, identity matching, source
hashes, recommendation ordering and scores, target/caution output, warning
texts, signatures, CLI behavior, serialized fields, and replay checks.
Preserve the original callable and class objects through compatibility imports.
Use synthetic fixtures and the MA-001 baseline to verify equivalence. No
provider call, support promotion, policy change, or league data mutation.
Position-cap source mapping and actual provider coverage remain separate.
Run focused and full tests, Ruff, import/package smoke, context/privacy gates,
then open one PR against main for review and leave it unmerged. If behavior
needs to change, explain it before implementation.

## Previous MA-002t - Complete remaining #31 membership admission evidence (merged PR #65; #31 closed)

Authorized by the user's request after PR #64 merged. Audit issue #31 against
the current Modular implementation and the MA-002 row of
`docs/MODULAR_MIGRATION_PLAN.md`. Close the Draft saved-snapshot membership gap:
unknown or malformed roster roles and invalid ownership must not become ready;
preserve explicit zero versus unavailable taxi evidence and permitted temporary
capacity overages. Use MR-01, MR-03, MR-05 and MR-10 plus architecture sections
3.1-3.2 and 5. Test both reference rosters and open-slot/reserve variants,
three-feature admission and old saved-evidence behavior with synthetic inputs.
Do not infer Sleeper position maxima from slots or app preferences; keep both
reference position-limit scopes LIMITED unless a verified source mapping and
league-specific values are supplied. No private history, league-setting changes,
calibration transfer, Sleeper write or support promotion. Run focused/full tests,
Ruff, package/import and context/privacy gates, then open one PR for review.
Close #31 only when every acceptance criterion is evidenced.

## Previous MA-002s - Complete #30 scoring evidence acceptance (merged PR #64; closed #30)

Authorized by the user's September 28 request after PR #63 merged. Audit #30's
full acceptance list against the current Modular implementation. Correct the
remaining legacy core scorer false-completeness case without changing its
diagnostic points or recommendation policy; preserve explicit missing,
invalid, unsupported and position-irrelevant evidence. Use the MA-002 row of
`docs/MODULAR_MIGRATION_PLAN.md`, MR-01, MR-02, MR-04, MR-06, MR-09 and MR-10,
and architecture sections 3.1 and 5. Prove both reference maps independently,
the Draft/Trade/Waiver readiness boundaries, saved-result compatibility and
MA-001 semantics with synthetic public evidence. Do not assume omitted provider
fields are zero or promote support, rankings or league calibration. No private
history, paid provider request or Sleeper write. Run focused/full tests, Ruff,
package/import smoke, context/privacy gates and CI. Open one PR without
merging; close #30 only when every acceptance criterion is demonstrated.

## Previous MA-002r - Map documented preseason FantasyPros lost fumbles (#30; merged PR #63)

Authorized by the user's September 28 request after PR #62 merged. Take one
bounded #30 scoring-source slice: verify whether FantasyPros preseason
`fumbles` means lost fumbles, then map only that documented field in the Draft
API projection scorer. Keep missing/invalid/conflicting evidence incomplete.
Use the MA-002 row of `docs/MODULAR_MIGRATION_PLAN.md`, MR-02, MR-04, MR-06,
MR-09, MR-10 and MR-14, and architecture sections 3.1 and 5. Record an
independent synthetic before/after score and admission example for each
reference map without treating other missing fields as zero. No paid provider
calls, private history, ranking or decision-policy changes, league calibration
transfer, Sleeper write or support promotion. Run focused/full tests, Ruff,
package/import smoke, context/privacy gates and CI. Open one PR without merging;
leave #30 open unless every acceptance criterion is met.

## Previous MA-002q - Verify #31 Sleeper Draft position-limit source semantics (merged PR #62)

Authorized by the user's September 28 request after PR #61 merged. Inspect the
two redacted reference profiles and current public Sleeper source documentation
for Draft enforcement and positional maximums. Use the MA-002 row of
`docs/MODULAR_MIGRATION_PLAN.md`, its MA-002e/MA-002f contracts, MR-01, MR-03,
MR-05, MR-10, MR-13 and MR-14, and architecture sections 3.1-3.2 and 5.
Map only verified source fields; never derive maxima from roster slots, Draft
preferences or platform defaults. If source mapping remains unverified, keep
both affected reference scopes LIMITED and record the missing evidence and
recovery path. No private history, league calibration transfer, decision-policy
change, Sleeper write or MA-005 support promotion. Run focused/full tests, Ruff,
package/import smoke, context/privacy gates and CI. Open one evidence PR without
merging; close #31 only if all its acceptance criteria are met.

## Previous MA-005b - Exercise Trade and Waiver evaluations across the half-PPR shapes (merged PR #61)

The synthetic matrix merged in PR #61. See
`docs/MODULAR_INSEASON_MATRIX.md`; it made no support-promotion claim.

Authorized by the user's September 28 request after merging PR #60. Use
invented rosters to run Trade diagnosis and one entered package, and Waiver
full/open-slot evaluation, across all 12 MA-005a roster shapes. Keep independent
lineup and package arithmetic; prove a missing add projection blocks its Waiver
case without hiding an independent Trade diagnosis. Do not apply any existing
league's decision-policy calibration to a new shape or claim feature readiness.
Use the MA-005b contract in `docs/MODULAR_MIGRATION_PLAN.md`, MR-02, MR-04,
MR-05, MR-07, MR-13 and MR-14, and architecture sections 3.1-3.3 and 6.
Synthetic inputs only; no provider calls, Sleeper writes, policy change or
support promotion. Run focused/full tests, Ruff, import, context/privacy gates
and CI. Open one PR and stop without merging.

## Previous MA-005a - Inventory the bounded half-PPR roster matrix (merged PR #60)

Authorized by the user's September 28 request after merging PR #59. This first
MA-005 slice records synthetic structural evidence for the 12 target roster
shapes (10/12 teams, three flex layouts, five/six bench places). Test normalized
league shape, Draft slot interpretation/capacity, neutral lineup assignment and
roster membership with independent expected results. Record the exact reference
profiles and operation-specific blockers separately; a shape passing mechanics
must not become a Draft, Trade or Waiver readiness or calibration claim.
Use the MA-005a contract in `docs/MODULAR_MIGRATION_PLAN.md`, MR-01, MR-02,
MR-05, MR-13 and MR-14, and architecture sections 3.1-3.2 and 6. No provider
calls, league writes, policy changes or support promotion. Run focused/full
tests, Ruff, package/import smoke, context/privacy gates and CI. Open one PR
with the matrix and limitations, then stop without merging.

## Previous MA-004f - Correct Draft legal capacity and season evidence (merged PR #59; closed #33)

Authorized by the user's September 27 request after merging PR #58. Make one
reviewed Draft behavior PR from current main for issue #33. Distinguish roster
capacity and slot eligibility from the existing Draft acquisition preferences;
keep selected strategy objectives, preference caps, ties, and K/DST treatment
unless an independently tested legality case requires a named correction.
Remove the implicit 2026 bye-week default. Require an explicit season-matched,
validated schedule for bye-aware Draft simulation and completed-mock scoring;
reject missing, wrong-season, and incomplete evidence before evaluation.
Use the MA-004f contract in `docs/MODULAR_MIGRATION_PLAN.md`, requirements
MR-01, MR-05 through MR-07 and MR-13, and architecture sections 3.2 and 5-6.
Use synthetic examples for third-QB legality, every 10/12-team snake slot,
final rosters, edits/undos, and schedule failures. Record before/after decision
differences, fixed-seed timing and an absolute Draft response-time budget. Run
focused and full tests, Ruff, package/import smoke, context/privacy gates and
CI. No paid provider calls or Sleeper writes. Open one PR and stop without
merging. Do not promote wider format support or alter Trade/Waiver policy.

## Previous MA-004e - Complete Draft watcher effect and presentation boundaries (merged PR #58)

Authorized by the user's September 27 request to continue after MA-004d merged
in PR #57. Make one bounded, behavior-preserving PR from current main. Move
`MockDraftWatcher` polling into `application/draft_watcher.py` and the human
watcher formatter into `presentation/draft_watcher.py`. Keep `mock_watcher.py`
as a compatibility import for all previously exposed public and currently used
private names; point safe internal imports at the new owners. Do not change the
Draft state/recommendation implementation moved in MA-004d. Use the MA-004e
contract in `docs/MODULAR_MIGRATION_PLAN.md`, architecture sections 2 and 4-6,
and MA-001 synthetic compatibility, semantic and performance evidence. Preserve
watcher polling cadence, GET-only calls, state/cache behavior, report fields,
warnings, human/JSON output, CLI commands and exit codes, schemas and replay
checks. Leave ranking policy, issue #33 fixes, provider calls and Sleeper state
untouched. Run focused and full tests, Ruff, package/import smoke, context and
privacy gates, CI and synthetic watcher before-and-after comparison. Open one
PR with evidence and stop without merging. No new issue is needed.

## Previous MA-004d - Move Draft watcher decisions into its package (merged PR #57)

Authorized by the user's September 27 request after MA-004c merged in PR #56.
Make one bounded, behavior-preserving PR from current main. Move the watcher's
Draft state transitions, room timing and recommendation logic from
`mock_watcher.py` to `draft/watcher.py`. Keep the existing import path for
callers, including currently imported private helpers. Leave Sleeper polling
and human report formatting in their current entry point for later application
and presentation extraction. Update safe internal imports to the Draft owner.
Put the existing taxi membership admission check behind a neutral core helper
so the new Draft module does not import a provider; preserve the provider path.
Use the MA-004d contract in `docs/MODULAR_MIGRATION_PLAN.md`, architecture
sections 2 and 4-6, and MA-001 synthetic compatibility, semantic and
performance evidence. Preserve watcher decisions, report fields, CLI behavior,
sorting, policy caps, season assumptions, schemas and replay checks. Leave
ranking policy, issue #33 fixes, provider calls and Sleeper state untouched.
Run focused and full tests, Ruff, package/import smoke, context and privacy
gates, CI, and fixed-seed Draft performance comparison. Open one PR with
before-and-after evidence, then stop without merging. No new issue is needed.

## Previous MA-004c - Move Draft advice into its package (merged PR #56)

Authorized by the user's September 27 request after MA-004b merged in PR #55.
Make one behavior-preserving extraction PR from current main: move the
implementation of `src/roster_theory/assistant.py` into
`src/roster_theory/draft/assistant.py`, retain the old import path as a
compatibility adapter, and update safe internal imports. Use the MA-004c
contract in `docs/MODULAR_MIGRATION_PLAN.md`, architecture sections 2 and 4-6,
and MA-001 synthetic compatibility, semantic and performance evidence. Preserve
Draft advice, sorting, scores, signatures, commands, output fields, schemas,
and replay checks. Leave watcher, ranking policy, issue #33 fixes, provider
calls, and Sleeper state untouched. Run focused and full tests, Ruff,
package/import smoke, context and privacy gates, CI, and the fixed-seed Draft
performance comparison. Open one PR with before-and-after evidence, then stop
without merging. No new issue is needed.

## Previous MA-004b - Move Draft simulation into its package (merged PR #55)

Authorized by the user's September 27 request to proceed after MA-004a merged
in PR #54. Make one behavior-preserving extraction PR: move the implementation
of `src/roster_theory/simulation.py` into `draft/simulation.py`, retain the old
import path as a compatibility adapter, and update internal imports only where
they do not create a cycle. Use the MA-004b contract in
`docs/MODULAR_MIGRATION_PLAN.md`, architecture sections 2 and 4-6, and MA-001's
synthetic compatibility, semantic and performance evidence. Preserve all public
and currently imported private simulation names, signatures, Draft commands,
results, decisions, reasons, tie behavior, policy caps, season assumptions,
schemas and exact-build replay checks. Do not change watcher workflows, ranking
policy, hard-coded pick preferences, issue #33's cap/season rules, supported
formats, paid provider data, or Sleeper state. Run focused Draft/reference tests,
the full suite, Ruff, package/import smoke, context and staged privacy gates,
CI and same-machine fixed-seed Draft performance comparison. Stop at a tested
PR; later MA-004 work needs separate activation.

## Previous MA-004a - Establish the Draft analysis package (merged PR #54)

Authorized by the user's September 27 request to set the next milestone after
MA-003b merged in PR #52. Make one behavior-preserving Draft extraction PR:
create `src/roster_theory/draft/`, move the implementation of
`draft_analysis.py` into `draft/analysis.py`, and retain the old import path as
a compatibility adapter. Update internal imports only where they can point to
the new owner without a cycle. Use the MA-004a contract in
`docs/MODULAR_MIGRATION_PLAN.md`, architecture sections 2, 3.2 and 4-6, and
the MA-001 synthetic compatibility, semantic and performance evidence.
Preserve Draft commands, result fields, choices, reasons, rankings, policy caps,
season assumptions, schemas and replay checks. Do not move the large simulation
or watcher workflows, fix #33, add formats, run paid provider calls or write to
Sleeper in this slice. Run focused Draft and reference tests, full suite, Ruff,
package/import smoke, context and privacy gates, CI and a same-machine Draft
performance review. Stop at a tested PR; further MA-004 slices need their own
activation.

## Previous MA-003b - Complete the shared FantasyPros request limit (#32; merged PR #52)

Authorized by the user's September 27 request to finish the provider request-limit
follow-up after MA-003 merged. Make the remaining Draft, diagnostic and historical
accuracy entry points share the existing account-wide daily ledger and request
pacing. Keep the old ledger path and schema, count each real HTTP attempt including
retries, and preserve cache hits without a charge. Fail closed on invalid ledgers,
exhausted budget or lock contention. Use synthetic transport and process tests;
make no live paid-provider calls, league writes, or feature-policy changes. Record
the compatibility and rollback limits, run the repository gates, and stop at a
tested pull request. Issue #32 closed when this follow-up merged.

## Previous MA-003 - Extract shared in-season preparation (merged PR #51)

Authorized by the user's September 27 request. Extract factual preparation from
Trade so Trade and Waiver call one shared implementation without either feature
calling the other's workflow. Shared ownership includes provider retrieval and
cache coordination, identity matching, league scoring, freshness and neutral
value preparation. Keep expert selection, horizon choices and decision rules
explicitly feature-owned. Preserve the established read-only behavior, source
evidence, saved contracts and reference decisions through synthetic tests.
Use the MA-003 row in `docs/MODULAR_MIGRATION_PLAN.md` and architecture sections
2, 3.3, 3.4, 4-6. No new provider calls, league writes or policy promotion.
Stop at a tested handoff on a separate branch and PR.

## Previous MA-002p - Restore conditional in-season forecast estimates

Authorized by the user's September 27 request to correct the confirmed Trade
and Waiver projection regression after merging PR #49. Continue the MA-002
before-and-after reconciliation using synthetic fixtures and aggregate retained
cache evidence. Restore usable league-scored estimates only when position-core
forecast stats are observed and scoring rules otherwise resolve. Keep missing
fields explicit; invalid, missing-core, unknown-rule and unscoped data stay
unavailable. Carry estimate status through value boards and both analyses.
The user's fumble-field challenge prompted checking FantasyPros's published
projection table and API sample: its weekly `fumbles` means fumbles lost.
Restore that weekly mapping without changing the separate Draft source contract.
Trade decisions using estimates must be conditional; Waiver analysis may rank
them but may not issue an affirmative claim/add label. Do not alter expert
rankings, league-specific policy, Draft scoring, or Sleeper state. No new
provider calls or publication of private rows. Validate the reference
workflows, full suite, Ruff, context, privacy and CI; stop at a tested PR.
MA-002 and remaining provider/rule evidence remain open.

## Previous MA-002o - Reconcile working workflows before further migration (merged PR #49)

Authorized by the user's September 26 request for a before-and-after review
and fixes to confirmed regressions. Compare the accepted MA-001 baseline and
preserved local metadata with current Draft, Trade and Waiver paths. Reconcile
previously working behavior before changing it. Use only synthetic public
fixtures and aggregate facts from ignored local evidence; do not publish player,
league, account, credential or raw response data. No new provider calls or
Sleeper mutations.

Allowed: a focused report, regression tests and narrowly justified repairs to
Draft room admission or in-season projection preparation when the same inputs
demonstrate a lost workflow. Keep missing evidence visible and any approximate
conclusion explicitly conditional. Do not claim complete provider coverage,
change rankings or weights, transfer league policy, or begin structural MA-003
or MA-004 work in this slice. Validate reference workflows, full suite, Ruff,
context, privacy and CI. Stop at a tested PR against main; MA-002 and the
remaining provider/rule evidence stay open.

## Previous MA-002n - FantasyPros Draft ranking-source tier evidence (merged PR #48)

Authorized by the user's September 26 request to continue after merging PR #47.
Take a bounded #30 provider-evidence slice: inspect at most two read-only,
rate-paced Draft ranking responses, retain only aggregate scope/tier facts, and
guard Draft readiness against any ranking source explicitly marked sample-only.
Do not infer premium authority from the request or the expert directory when
a ranking response disagrees. Requirements MR-02, MR-06, MR-09, MR-10 and MR-14;
architecture sections 3.1 and 5.

Allowed: FantasyPros read-only ranking calls at no more than one per second,
the Draft API ranking readiness and CLI report, synthetic regressions and public
aggregate evidence. Do not print or persist the API key, player rows, private
responses or league data. Do not alter ranking weights, projection scoring,
manual import, Trade/Waiver, league state or existing coverage thresholds.
Missing tier declarations stay visibly unverified unless the sampled provider
contract establishes an independent authority signal. Gates: sample versus
unknown tier, independent valid ranks, unchanged reference goldens, full
suite/Ruff/context/privacy/CI. Stop at a tested PR against main; #30 and MA-002
remain open.

Implementation complete: 915 tests pass with unchanged reference goldens;
Ruff, compilation, context routing and tracked-tree privacy gates pass.
Evidence: `docs/MODULAR_RANKING_SOURCE_TIER.md`. CI/review remain the merge gate.

## Previous MA-002m - FantasyPros projection-source tier evidence (merged PR #47)

Authorized by the user's September 26 request to continue after merging PR #46.
Take a bounded #30 provider-evidence slice: inspect at most four read-only,
rate-paced 2026 preseason projection responses, retain only aggregate schema
facts, and require each Draft projection response to prove non-sample access
before the imported board can be draft-ready. Missing tier evidence is
incomplete; observed statistic shapes do not prove unobserved field coverage or
structural zeros. Requirements MR-02, MR-04,
MR-06, MR-09, MR-10 and MR-14; architecture sections 3.1 and 5.

Allowed: FantasyPros read-only projection calls at no more than one per second,
the Draft projection readiness check and CLI report warning, synthetic
regressions, and focused public evidence.
Do not print or persist the API key, player rows, private responses or league
data. Do not change expert rankings, manual import, Trade/Waiver behavior,
league state, or existing rank/projection thresholds. Gates: independently
limited versus explicitly premium projection sources, observed-versus-inferred
field classification, unchanged reference goldens,
full suite/Ruff/context/privacy/CI. Stop at a tested PR against main; #30 and
MA-002 remain open.

Implementation complete: 915 tests pass with unchanged reference goldens;
Ruff, compilation, context routing and tracked-tree privacy gates pass.
Evidence: `docs/MODULAR_PROJECTION_SOURCE_TIER.md`. CI/review remain the merge gate.

## Previous MA-002l - Draft API preseason projection-source scope (merged PR #46)

Authorized by the user's September 26 request to continue after merging PR #45.
Implement a bounded #30 follow-up: explicitly request week-zero FantasyPros
Draft projections and require each response to declare the requested season,
week zero and position before any raw statistic can become a league-scored point
total. Missing or conflicting source scope remains incomplete, and valid
position sources remain independent. Requirements MR-02, MR-04, MR-06, MR-09 and
MR-10; architecture sections 3.1 and 5.

Allowed: Draft API projection import, additive metadata, synthetic regressions
and focused evidence. No paid-provider calls, league writes, expert-weight or
ranking policy changes, manual import, or Trade/Waiver behavior changes.
Preserve complete-case scoring and top-board readiness; prevent rejected
sources from contaminating duplicate-ID checks. Gates: missing/mismatched
source declarations, independent valid-position preservation, unchanged
reference goldens, full suite/Ruff/context/privacy/CI. Stop at a tested PR
against main; #30 and MA-002 remain open.

Implementation complete: 915 tests pass with unchanged reference goldens;
Ruff, compilation, context routing and tracked-tree privacy gates pass.
Evidence: `docs/MODULAR_DRAFT_PROJECTION_SCOPE.md`. CI/review remain the merge gate.

## Previous MA-002k - Draft API ranking-source scope (merged PR #45)

Authorized by the user's September 26 request to continue after merging PR #44.
Implement a bounded #30 follow-up: explicitly request preseason Draft rankings,
verify each FantasyPros ranking response declares the requested season, week zero,
scoring format, position and draft ranking type, and exclude unverified or
mismatched ranking rows from the board. Report source-level scope evidence and
keep independently valid expert/position responses usable. Requirements MR-02,
MR-06, MR-09 and MR-10; architecture sections 3.1 and 5.

Allowed: Draft API ranking import, additive board metadata, synthetic regressions
and focused evidence. No paid-provider calls, league writes, expert-weight changes,
projection-scoring changes, manual import, or Trade/Waiver behavior changes.
Keep unknown source declarations incomplete rather than inferring them from
request parameters. Gates: wrong and missing declarations, partial-source
preservation, existing Draft reference, full suite/Ruff/context/privacy/CI.
Stop at a tested PR against main; #30 and MA-002 remain open.

Implementation complete: 913 tests pass with unchanged reference goldens;
Ruff, compilation, context routing and tracked-tree privacy gates pass.
Evidence: `docs/MODULAR_DRAFT_RANKING_SCOPE.md`. CI/review remain the merge gate.

## Previous MA-002j - Draft API projection scoring evidence (merged PR #44)

Authorized by the user's September 26 request to continue after merging PR #43.
Implement a bounded #30 follow-up for the FantasyPros preseason API board:
assess actual Sleeper rules and season-scoped provider statistics; use only
complete projections for point totals and replacement baselines; report missing,
invalid, ambiguous and unsupported scoring evidence without losing independent
expert ranks. Keep provider-declared scope distinct from ranking authority.
Requirements MR-01, MR-02, MR-04, MR-06, MR-09, MR-10; architecture sections
3.1 and 5.

Allowed: the Draft API projection adapter, board preparation and its readiness
report, CLI scope handoff, synthetic regressions and evidence. Do not call paid
providers during implementation or tests. Do not change manual import, expert
weights, acquisition policy, live Draft operation, Trade/Waiver behavior or
league state. Missing fields are not zero without verified provider evidence.
Preserve complete-case point totals, board columns and command names; additive
metadata/issue evidence is allowed. Gates: missing-versus-explicit-zero,
invalid/unsupported/ambiguous source and scope cases, unchanged reference
goldens, full suite/Ruff/context/privacy/CI. Stop at a tested PR against main;
#30 and MA-002 remain open.

Implementation complete: 910 tests pass with unchanged reference goldens;
Ruff, compilation, context and tracked-tree privacy gates pass. Evidence:
`docs/MODULAR_DRAFT_API_SCORING.md`. Required CI and review remain the merge gate.

## Previous MA-002i - Draft manual projection scoring evidence (merged PR #43)

Authorized by the user's September 26 request to continue after merging PR #42.
Implement a bounded #30 follow-up for the manual FantasyPros preseason export:
preserve absent, blank, explicit zero, invalid and nonfinite raw-stat evidence;
score only complete applicable categories under the actual league rules; keep
expert ordering available while incomplete projections stay out of replacement
baselines and draft-readiness counts. Requirements MR-01, MR-02, MR-04, MR-06,
MR-09, MR-10; architecture sections 3.1 and 5.

Allowed: manual export parsing/scoring, its CLI scope handoff, synthetic tests
and evidence. No live FantasyPros API import, provider call, new Draft operation,
acquisition policy or ranking-weight change. Do not infer absent off-role event
counts or provider structural zeros. Preserve complete-case scoring, command
names and saved board shape; additive issue/metadata evidence is allowed. Gates:
missing/blank/zero/invalid examples, independent ranking availability, unchanged
MA-001 reference goldens, full suite/Ruff/context/privacy/CI. Stop at a tested
PR against main; #30 and MA-002 remain open.

Implementation complete: 907 tests pass with unchanged reference goldens;
Ruff, compilation, context and tracked-tree privacy gates pass. Evidence:
`docs/MODULAR_DRAFT_MANUAL_SCORING.md`. Required CI and review remain the merge gate.

## Previous MA-002h - Waiver emerging-scenario scoring evidence (merged PR #42)

Authorized by the user's September 26 request to continue after merging PR #41.
Implement a bounded #30 follow-up: value Waiver breakout scenarios only when
their modeled statistics cover every applicable nonzero Sleeper scoring rule.
Requirements MR-01, MR-02, MR-04, MR-06 and MR-10; architecture sections 3.1
and 5. Missing, invalid, unsupported and unknown-applicability rules must block
the scenario comparison with specific reasons, while unrelated players and the
base Waiver evaluation remain available. Explicit disabled rules require no
statistic. Position reception bonuses use the modeled reception count.

Allowed: the Waiver scenario scorer and its scoped rule/evidence translation,
synthetic regressions and handoff evidence. Keep existing complete-case points,
saved result shape, Draft/Trade policy and Waiver decision policy. Do not infer
off-role zero events, change football priors, calibrate, call providers, simulate
live leagues or mutate league state. Gates: missing-versus-disabled and
position-bonus cases, unchanged MA-001 complete-data goldens, full suite/Ruff/
context/privacy/CI. Stop at a tested PR against main; #30 and MA-002 remain open.

Implementation complete: 905 tests pass with unchanged reference goldens;
Ruff, compilation, context and tracked-tree privacy gates pass. Evidence:
`docs/MODULAR_EMERGING_SCORING.md`. Required CI and review remain the merge gate.

## Previous MA-002g - Waiver historical scoring evidence (merged PR #41)

Authorized by the user's September 26 request to continue after PR #40 merged.
Implement a bounded #30 follow-up: score Sleeper season and recent-week
historical statistics through the explicit, position-aware coverage contract.
Requirements MR-01, MR-02, MR-04, MR-06, MR-09, MR-10; architecture section 3.1
and compatibility section 5.

Season points and per-game averages must be usable only when every applicable
nonzero rule has observed, finite evidence. Missing, invalid, unsupported and
unknown-applicability settings remain visible per player; an incomplete week
cannot enter a complete recent average or position rank. Preserve independent
opportunity/yard metrics and other candidates. No omitted stat becomes zero
without verified source-schema evidence. Keep source season/week and actual
league scoring distinct. Use existing saved Waiver input warnings plus an
additive data-only build-report field; saved input readers remain compatible.

Allowed: a scoped Sleeper historical-stat translator, Waiver input preparation,
synthetic regression tests and handoff evidence. Do not change Draft imports,
Trade boards, FantasyPros projection scoring, recommendation thresholds,
calibration, provider requests, user settings or league state. No live/provider
operation or simulation. Gates: before-fix partial-score ranking examples,
position/applicability and explicit-zero cases, independent-candidate invariance,
unchanged MA-001 complete-data goldens, full suite/Ruff/context/privacy/CI.
Stop at a tested PR against main; #30 and MA-002 remain open.

## MA-002f - Operation-specific roster capacity

Authorized by the user's September 26 request to continue after merging PR #39.
Implement the next bounded #31 follow-up: distinguish observed over-limit roster
state from structural membership defects, and apply capacity restrictions to the
specific Trade or Waiver action. Requirements MR-01, MR-03, MR-05, MR-10;
architecture sections 3 and 5.

Allow read-only snapshots and independent Trade comparisons when an unrelated
roster exceeds active/reserve capacity. Trades involving an over-limit roster
may be compared, but modeled lineup changes must be visibly conditional while
Sleeper lineup edits are locked. Waiver refresh may observe any overage;
acquisition and search must reject the user's own over-limit or reserve-ineligible
roster. Retain structural identity, ownership, overlap and unsupported taxi
admission, and report all observed gaps. Do not infer positional-cap semantics,
claim success, or provider readiness.

Use synthetic examples and preserve complete-data MA-001 goldens. No scoring,
rankings, Draft policy, calibration, provider refresh, live simulation or league
mutation. Gates: before-fix overage regressions for refresh/current/evaluation/
search, structural defect counterexamples, unchanged reference decisions, full
suite/Ruff/context/privacy and required CI. Stop at a tested PR against main;
#31 and MA-002 remain open.

## MA-002e - Draft position-limit evidence and room admission

Authorized by the user's September 26 request to continue after merging PR #38.
Implement a bounded #31 follow-up: establish the meaning/evidence boundary of
Sleeper's draft position-limit setting, represent supported/unknown/unsupported
rule assessments separately from readiness, and gate room-backed Draft
recommendation entry points before computation or reuse of a cached recommendation.
Requirements MR-01, MR-05, MR-10; architecture sections 3 and 5.

Allowed: neutral capability records, Sleeper-specific position-limit translation,
offline rule inspection, the recommend command and mock-watcher admission,
synthetic regressions and handoff evidence. Missing or undocumented cap evidence
must not become unlimited capacity. Preserve source values for diagnosis, and
keep app acquisition preferences separate from platform rules. Do not guess API
field defaults or encourage changes to league settings to bypass admission.

Preserve pure offline Draft calculations, MA-001 parser/output goldens, scoring,
ranking weights, acquisition caps, user configuration and Trade/Waiver policy.
No provider refresh, paid calls, live simulation, league mutation or Draft
season reopening. Full feature support admission and provider cap-schema
verification remain separate slices; this check alone cannot establish readiness.

Gates: independent absent/disabled/enabled/malformed rule cases, both reference
profiles, blocked commands before decision work, per-poll revalidation including
cached recommendations, unchanged semantic goldens, bounded preflight timing,
full suite/Ruff/context/privacy and required CI. Stop at a tested PR against
main; #31 and MA-002 remain open.

Implementation complete: 888 tests pass, including unchanged parser and all
24 reference output goldens. Before-fix regressions prove both admission gaps;
cache invalidation and fresh-room requests are covered. Local assessment costs
approximately 3–6 microseconds; Ruff, compilation, context and privacy gates pass.
Evidence: `docs/MODULAR_DRAFT_RULE_ADMISSION.md`. Required CI/review remain the
merge gate. No live/provider operation or Draft reopening was performed.

## Previous MA-002d - Preserve and validate roster membership (merged PR #38)

Authorized by the user's request to continue after merging PR #37 on September
26. Implement the membership slice of #31: explicit taxi membership in normalized
teams; neutral active/starter/reserve/taxi reconciliation; duplicate ownership,
overlap and capacity validation; visible rejection of taxi formats in feature
admission. Preserve player identities and missing evidence rather than guessing.
Requirements MR-01, MR-03, MR-05, MR-10; architecture sections 3 and 5.

Allowed: core membership contracts, Sleeper translation, Trade/Waiver snapshot
and operation gates, narrow Draft taxi admission, artifact readers, synthetic
tests and compatibility evidence. Version intentional serialized additions;
retain old golden evidence and prove ordinary decision fields unchanged. Reject
old normalized artifacts that cannot establish lost taxi membership with a
refresh instruction. Raw provider evidence is never rewritten.

Reserve status/settings checks must distinguish invalid from unknown; no absent
setting is invented. Unverified Draft position-limit semantics and broad league
admission remain separate follow-ups under #31/MA-002. Do not change Draft caps,
ranking weights, scoring, calibration, providers, user configuration or league
state. No live simulation or provider refresh.

Gates: reproduce lost taxi membership; direct and saved evidence preserve it;
membership/capacity/eligibility cases and feature admission; reviewed schema-only
baseline differences; full suite, Ruff, context/privacy and required CI. Stop at
a tested PR against main; broader MA-002 and unfinished #31 acceptance stay open.

Implementation complete: all 877 local tests pass, including 24 reference
workloads against the explicit membership-v2 golden. The original golden is
retained; the reviewed receipt contains only membership additions and derived
hashes. Ruff, compilation, context and repository privacy checks pass. Detailed
evidence: `docs/MODULAR_ROSTER_MEMBERSHIP.md`. Required CI and review remain the
merge gate.

## Previous MA-002c - Decision-scoped missing player evidence (merged PR #37)

Authorized by the user's request to implement MR-02 section 3.1 now.
Continue on draft PR #37: retain strict source scoring, protect unknown assets
and roster capacity, preserve independent comparisons and expose conditional
Trade/Waiver results instead of rejecting an entire roster. Feature-owned
readiness/search/report paths and neutral lineup dependency mechanics are in
scope, with offline regression tests and handoff evidence. No invented ranks,
zero-filled missing forecasts, arbitrary materiality cutoff, live simulation,
provider refresh, calibration transfer or league action.

Gates: independent comparison invariance; connected FLEX/bye/secondary-move
dependencies; missing assets cannot be traded/dropped; conditional search and
reports remain visibly conditional; full tests, unchanged complete-data MA-001
goldens, measured bounded search overhead, Ruff/context/privacy and required CI.
Stop at a tested PR handoff; provider schema questions and overall MA-002 remain open.

Implementation complete: 860 tests pass, including unchanged MA-001 goldens;
unknown assets/capacity, independent projection sweeps, connected future-week
and secondary dependencies, conditional searches and reports are covered.
Evidence and repeatable before/after search timings:
`docs/MODULAR_DECISION_COVERAGE.md`. Final local gates pass; required PR CI and
review remain the merge gate. No baseline artifacts were regenerated.

## Previous MA-002b - Provider projection scoring coverage (not active)

Active by the user's September 26 request to continue after merging PRs.
Integrate MA-002a's approved contracts into shared FantasyPros weekly projection
preparation used by Trade and Waiver. Preserve diagnostic partial totals, but
expose missing/invalid statistics and unsupported rules to readiness checks.
Use explicit provider aliases and rule applicability; do not infer absent zeros.
Requirements: MR-01, MR-02, MR-04, MR-06, MR-09; follow-up issue #30.

Allowed: shared provider scoring translation, direct adapter and prepared-board
integration, offline regression tests, evidence and handoff documentation.
Keep feature policies, ranking authority, historical-stat scoring, legacy Draft
imports, roster membership, provider budgeting and live operations outside this
slice. No new dependencies, provider refresh, calibration or league mutations.

Gates: independent arithmetic and missing/zero/invalid/unsupported coverage;
consistent direct/prepared results and downstream readiness; unchanged MA-001
goldens; full compact tests, Ruff, context/privacy checks and required CI.
Stop at a tested PR against main. Overall MA-002 and issue #30 remain open.

Implementation complete: 847 tests pass, including unchanged MA-001 goldens;
Ruff, compilation, context and privacy gates pass. Two original defects were
reproduced before the fix. Evidence and measured preparation overhead:
`docs/MODULAR_PROVIDER_SCORING.md`. Await required PR CI and review. Both reference
maps remain LIMITED for unresolved `fum_rec`; provider coverage is unverified.

September 26 user clarification: irrelevant missing players must not disable
independent Trade/Waiver decisions. PR #37 remains a draft until decision-specific
readiness satisfies MR-02 section 3.1. This follow-up records that requirement,
dependency criteria and acceptance examples; it does not silently relax runtime
policy. Passing scoring tests alone is insufficient for promotion. The next
implementation slice must scope feature-owned dependencies and conditional
results while protecting unknown assets and retaining all evidence gaps.

## Previous Trade snapshot clock regression repair (not active)

Authorized by the user on September 26, 2026 after the intermittent post-merge
PR #34 failure. Scope: anchor schedule provenance age to the snapshot's recorded
capture time, preserve deterministic IDs/seeds for identical evidence, and add
second-boundary and freshness-boundary regression tests. Follow AC-007's explicit
as-of contract in `docs/ASSISTANT_RELIABILITY_TASKS.md`.

No ranking, scoring, recommendation policy, schema, provider calls, or Sleeper
writes. Preserve current-time publication/ownership validation and MA-001 semantic
goldens. Separate branch; do not modify the parallel MA-002a worktree.

Gates: prove the new tests fail before the fix; focused/full tests, Ruff,
tracked/index privacy checks, and required CI. Stop at a tested pull request.

Implementation complete: new regressions fail before the fix and pass after it.
All 813 tests pass, including unchanged MA-001 semantic goldens. The original
intermittent test passed 100 repeats; 15 run-contract tests, Ruff, and privacy
gates pass. Merged by the user through PR #36; preserve this repair.

## Previous MA-002a - Explicit scoring rule and evidence contracts (not active)

Authorized on September 26, 2026 as a bounded shared-contract slice.
MA-001 PR #34 is merged to main. MA-002a PR #35 was merged into its former
MA-001 base branch; this follow-up carries the approved contract onto main.
MA-002a is implementation-complete: 828 tests, Ruff and context checks pass.
All 20 CI checks passed. Evidence: `docs/MODULAR_SCORING_CONTRACT.md`.
Requirements: MR-01, MR-02, MR-04, MR-06, MR-09, MR-10; architecture sections
3.1 and 5-6; migration plan MA-002 row. Follow-up integration is tracked in #30.

Allowed: pure versioned scoring-rule/evidence records and calculations under
`src/roster_theory/core/`, independent synthetic contract tests, explicit
reference-rule inventory and handoff documentation. Separate rule support from
per-player evidence completeness. Preserve observed zero, documented structural
zero, missing/invalid values, unsupported rules, position and source/horizon.

Do not wire the contract into existing providers or feature decisions in this
slice. Those behavior fixes require their own reviewed before/after evidence.
No new dependencies, providers, live simulation, calibration, roster-membership
changes (#31), Draft policy changes, or league mutations. Existing CLI/artifact
contracts and MA-001 semantic goldens must stay unchanged.

Gates: independent arithmetic and missing/invalid/unsupported cases; both
reference scoring inventories; deterministic serialization; full compact unit
suite, Ruff, context/privacy checks and required CI. Stop at a tested dependent
PR for MA-002a; do not claim #30 or the overall MA-002 milestone complete.

## Previous MA-001 handoff (not active)

Active by user authorization on September 25, 2026. Planning PR #27 is merged.
MA-001 implementation is complete and locally validated; awaiting PR review/merge.
Evidence: `docs/MODULAR_BASELINE.md`. All 811 tests and local gates passed.
Tracking: https://github.com/jaretjb/RosterTheory/issues/29.
Contract: `docs/MODULAR_MIGRATION_PLAN.md`, section 3; requirements sections 2-5;
architecture sections 3, 5-6; `IMPLEMENTATION_POLICY.md`.

Allowed: additive synthetic fixtures/tests, offline baseline/benchmark tooling,
compatibility and defect inventories, and read-only current Sleeper rule capture
for the two configured reference leagues. Keep raw responses/identity local and
publish only redacted rules and synthetic evidence. No FantasyPros refresh.

No production algorithm changes, new policy/calibration, live recommendations,
league mutation or reopened Draft operations. User authorization covers offline
synthetic validation after completeness checks, not live Draft simulation.

Gates: targeted and full compact unit suite, Ruff, context routing, privacy of
tracked/index contents, deterministic results, five measured benchmark repeats
after warm-up, and CI. Stop at a tested MA-001 handoff; unresolved profile/scope
gaps remain explicit. MA-002 is not activated automatically.

## Previous milestone history (not active)

TA-1313 — Trade Finder projection scoring compatibility is implementation-complete;
delivery is through PR #25. Projections retain provider-declared scope and use
verified raw stats with each league's Sleeper rules; ranking authority is
unchanged. The affected league's ignored policy remains local and provisional.
Revalidation against PR #26's privacy cleanup passed all 802 tests, Ruff, and
tracked-tree/index privacy gates. No additional provider refresh or Sleeper
write was performed. The prior live League Beta run remains incomplete for two
unrelated missing Week 3 roster projections, so no offer is recommendation-ready.

AC-005 — Explicit ranking caps and specialist performance policy (issue #11) is
merged in PR #19; all 20 CI checks passed and issue #11 is closed.
Evidence: `docs/COMPLETED_ASSISTANT_RELIABILITY_AC_005.md`.
AC-006 — Supported scoring formats and season portability (issue #12) merged in
PR #21 with all 20 checks passing. Tracking reconciliation merged in PR #20.
AC-007 — Freshness, readiness, provenance, and handoff contracts (issue #13)
merged in PR #22 with all 20 checks passing. AC-008 — End-to-end release gates and
measured optimization (issue #14) merged in PR #23 with all 20 checks passing;
issue #14 is closed. Evidence: `docs/COMPLETED_ASSISTANT_RELIABILITY_AC_008.md`.
No further Trade implementation milestone is active. New implementation
requires explicit authorization and a separate branch and pull request.

AC-001 and prerequisite PR #6 are merged through PRs into main. PR #15 passed
all CI checks. Evidence: `docs/COMPLETED_ASSISTANT_RELIABILITY_AC_001.md`.
AC-002/#8 through AC-005/#11 merged in PRs #16–#19 with all checks passing.
Release gate: 797 tests, Ruff and diff checks pass. The audit remains open.
All league actions remain read-only.

WA-027 — League-scored specialist performance weighting completed September
25, 2026 (America/Los_Angeles). K and DST exact evidence now preserves actual
season and recent league-scored production, and rank fallback must clear one
transparent combined score rather than any favorable rank authorizing a swap.
The current league uses a larger K season-points weight and a smaller DST
weight; other leagues retain neutral defaults pending separate evidence.

Fresh read-only validation protects the productive rostered kicker, removes
Detroit from the claim plan behind Cincinnati, and retains only San Francisco
and New England as affirmative DST alternatives. All 676 tests and Ruff pass;
no Sleeper write occurred. Acceptance evidence is in WA-027 of
`docs/WAIVER_ASSISTANT_TASKS.md`.

WA-026 — Universal retention safety and pruning equivalence completed
September 24, 2026 (America/Los_Angeles). Retention-safe Waiver Value is now
application-default behavior for every league policy, while calibrated weight
overrides remain league-local. Exact-budget pruning yields to fresh
same-position weekly/ROS/projection dominance, with bounded-versus-exhaustive
decision and drop equivalence covered by regression tests.

The fresh League Beta read-only proof selected J.K. Dobbins for Rachaad White.
Kyle Pitts improved projected lineup output over Oronde Gadsden but failed the
retention-safe value gate, 60.1 to 68.4. The coverage-isolation amendment now
records rostered player `12508` as `ROSTER_VALUE_UNAVAILABLE` while completing
League Alpha and keeping unrelated alternatives eligible. The result was an
ACQUIRE recommendation with a different legal drop; no Sleeper write occurred.
Trade retains strict all-roster coverage. Ruff and all 673 tests pass. Full
acceptance evidence is in the WA-026 row of `docs/WAIVER_ASSISTANT_TASKS.md`.

Trade TA-1312 — ROS expert-panel resilience completed September 23, 2026
(America/Los_Angeles). Trade now prefers three accurate, fresh experts who
actually contribute to all current ROS position feeds, accepts two as an
explicitly degraded panel, renormalizes their weights, and fails closed below
two. FantasyPros Latest ECR remains an independent market board; Waiver
acquisition scoring, weekly weighting, and Waiver Wire policy did not transfer.

Today's cached League Beta value-board refresh completed with three actual
contributors, complete selected and market ROS boards, 25 cache hits, zero
FantasyPros calls, and no Sleeper write. League Alpha passed the repaired expert
selection and then stopped at the separate rostered-player coverage gate for
inactive player 12508. All 666 tests and Ruff pass. Details:
`docs/COMPLETED_TRADE_ASSISTANT_TA_1312.md`.

WA-025 — Retention-safe Waiver Value and ordered claim portfolio completed
September 22, 2026 (America/Los_Angeles). Waiver Wire rank now affects only
acquisition; roster retention excludes below-replacement weekly ranks and
protects injury-uncertain, above-replacement ROS players. League-scored season
and last-two-week performance provide a bounded modifier. Same-position ROS,
nonnegative-lineup, and retention gates prevent destructive drops. K/DST can
use weekly, ROS, and league-scored season/recent ranks when projections do not
settle the choice. Search schema 10 returns a nine-item claim plan with shared-
drop alternatives identified.

The fresh read-only League Alpha proof protected Caleb Williams and Rico
Dowdle and exactly reproduced the four requested skill moves and two kicker
moves. Current defensive evidence changed after the user's dated list and now
ranks Minnesota, New England, and Carolina; Cincinnati fell to DST17 for the
week and was not forced into the result. The run evaluated 57 candidates,
pruned 75, and performed no Sleeper write. Ruff and all 661 tests pass. The
40/35/25 calibration remains league-local and was not transferred.

WA-024 completed September 22, 2026 (America/Los_Angeles). Waiver now combines
normalized weekly, Waiver Wire, and selected-panel ROS ranks at initial
50/30/20 weights. Missing ranks are neutral and the remaining weights
renormalize. The score applies to both adds and drops and owns the skill-player
value comparison. Waiver Wire uses the three most accurate trustworthy current
contributors when at least three are available; otherwise it uses FantasyPros
Latest ECR. Trade expert policy remains unchanged.

The read-only League Alpha proof selected Pat Fitzmaurice, Derek Brown, and
Andrew Erickson for Waiver Wire evidence and Pat Fitzmaurice, Derek Brown, and
Scott Pianowski for ROS evidence. It evaluated 57 candidates exactly, pruned 75
lower-valued candidates with audited bounds, and performed no Sleeper write.
All 658 tests and Ruff pass.

Trade TA-1309 completed September 21, 2026 (America/Los_Angeles). TA-1310
remains planned for separate league-local empirical calibration when
sufficient dated evidence exists.

TA-1309 replaced the whole-universe chart gate with explicit per-target and
per-package pricing coverage. Current chart prices remain primary; missing
current prices use one compatible archived prior-week chart for an entire
candidate package, visibly indicative and never current-market FAIR. An
unpriced asset without either chart is excluded and counted. Fresh read-only
searches in both leagues used current chart prices; one yielded four modeled
offers, the other none. Prior-week behavior was verified on fixtures because
there is not yet an older local chart. All 649 tests and Ruff pass. Details:
`docs/COMPLETED_TRADE_ASSISTANT_TA_1309.md`. The earlier failed gate is retained
as chronology in `docs/TRADE_ASSISTANT_TA_1309_GATE_2026-09-21.md`.

TA-1308 completed record: `docs/COMPLETED_TRADE_ASSISTANT_TA_1308.md`.
The deterministic per-league study harness remains available, but the local
export audit found no complete historical calibration corpus. No empirical
parameter was promoted. All 643 tests and Ruff pass; no live finder was run.

TA-1301 selected the documented Stats Guy Fantasy API as the weekly redraft
trade-market provider, with an authorized local import and explicit
`ECR-PROXY` as fail-closed fallbacks. The provider offers separately calculated
1QB and superflex redraft values, Sleeper player IDs, daily provider timestamps,
historical values, and application-compatible terms. Its market is a reception
and TEP blend, so that limitation must remain visible and exact team value must
continue to use each league's Sleeper scoring.

Phase 13 now has an explicit two-axis decision contract. The finder maximizes
the user's intrinsic/team-value gain subject to a current trade-market fairness
band, partner exact-roster plausibility, legality, and downside gates. Market
price constructs and prunes offers; it never determines the football-value
winner. Entered-package evaluation remains useful without a chart and exposes
market fairness only as a separate optional or `ECR-PROXY` result.

FantasyPros has no documented weekly chart endpoint. No FantasyPros support
request was sent; no endpoint was guessed; and its article was not scraped or
reverse-engineered. Twelve documented, unauthenticated provider GETs verified
current metadata and a dated FantasyPros/CBS relative-agreement check without
retaining a player row. The dated decision is in
`docs/TRADE_MARKET_PROVIDER_CAPABILITY_2026-09-20.md`.

Completed records below are retained as handoff history and do not authorize
additional work.

Trade TA-1303 — Leakage-safe optional recent-performance evidence is complete.
Completed results now join only to compatible pregame point/rank captures at a
rolling-origin decision time, with visible exclusions, position-aware
shrinkage, and claim-disabled small/stale samples. Expert order is untouched.
Six focused tests, all 630 tests, and Ruff pass. No live history was read or
calibration promoted. Details: `docs/COMPLETED_TRADE_ASSISTANT_TA_1303.md`.

Trade TA-1307 — Target-first CLI presentation is complete. `trade targets`
shows `WATCH` cards without claiming an offer; `trade search` uses the same
cards before exact grouped offers and prints separate intrinsic/market axes.
Hashed JSON, flat CSV, offline replay, one-command evidence preparation, and
advanced overrides have synthetic CLI coverage. All 624 tests and Ruff pass.
Live use awaits a league-scoped `trade_target` policy in TA-1308; no fixture
premium was promoted. Details: `docs/COMPLETED_TRADE_ASSISTANT_TA_1307.md`.

Trade TA-1306 — Exact 2-for-1 consolidation is complete. The consolidation
lane now constructs only 2-for-1 offers, applies a visible versioned chart
premium to construction and fairness, and audits the user's starter gain/add
plus partner drop and each outgoing player's post-drop lineup/depth use.
`ECR-PROXY` makes no chart-premium claim. Four new focused tests, all 622 tests,
and Ruff pass. The fixture premium is not an empirical league calibration;
TA-1308 owns that later work. No live league or Sleeper write occurred. Details
are in `docs/COMPLETED_TRADE_ASSISTANT_TA_1306.md`.

Trade TA-1305 — Target-lane constrained package optimization is complete. All
four target lanes and four package sizes receive independent exact-evaluation
budgets and coverage. Outgoing seeds expose exact surplus, marginal cost,
market price, and partner need. Exact decisions keep intrinsic outcome, direct
fairness or `ECR-PROXY`, market-ECR corroboration, partner plausibility,
legality, depth, and downside separate. Controlled exhaustive fixtures retain
the best intrinsic result in all 16 groups, including the formerly crowded-out
consolidation 2-for-1. Six focused tests, all 618 tests, and Ruff pass. No
provider request, live league operation, calibration, recommendation, or
Sleeper write occurred. Details are in
`docs/COMPLETED_TRADE_ASSISTANT_TA_1305.md`.

Trade TA-1304 — Deterministic target discovery and evidence contracts is
complete. `BUY_LOW`, `SELL_HIGH`, `CONSOLIDATE`, and fallback `NEED_FIT` cards
now preserve intrinsic, market-ECR, direct-price or `ECR-PROXY`, team-fit,
owner-disposability, optional performance, and freshness evidence separately.
Visible lexicographic factors replace any blended score. Every target remains
`WATCH` without a passing package, owner preference is never inferred, and
partial direct-price coverage fails the complete run to a named proxy. Seven
focused tests, all 612 tests, and Ruff pass. No provider request, live league
operation, calibration, recommendation, or Sleeper write occurred. Details are
in `docs/COMPLETED_TRADE_ASSISTANT_TA_1304.md`.

Trade TA-1302 — Trade-market ingestion and normalization is complete. A
GET-only Stats Guy bulk client now produces a fresh, complete, attributed 1QB
or superflex `TradeMarketBoard` keyed by Sleeper ID, with raw changes and
scoring-blend limitations. Authorized import, hashed replay, and claim-disabled
`ECR-PROXY` fallbacks pass synthetic tests. A metadata-only live check
normalized 396 source rows into 211 1QB redraft prices without retaining a
player row. All 605 tests and Ruff pass. Details are in
`docs/COMPLETED_TRADE_ASSISTANT_TA_1302.md`.

Trade TA-1301 — Weekly trade-market provider contract is complete. The
documented Stats Guy Fantasy API supplies daily trade-derived 1QB and superflex
redraft values keyed by Sleeper player ID; authorized local import and
`ECR-PROXY` remain fail-closed fallbacks. The provider's reception/TEP blend is
explicit, exact team value remains league-scored, and no FantasyPros article
scrape, secret, provider row, recommendation, or Sleeper write occurred.

WA-023 — Availability-aware DST streaming valuation is complete. DST decisions
now use a four-week `1.0/0.5/0.25/0.125` comparison against the incumbent and
currently acquirable streamers, require both an immediate and weighted edge,
and classify future-only cases as WATCH. Fixed K/DST replacement slots cannot
be filled by another position. Both live Denver recommendations became WATCH;
all 591 tests and Ruff pass. Details are in
`docs/COMPLETED_WAIVER_ASSISTANT_WA_023.md`.

Trade TA-1201 — Search runtime optimization and publication is complete.
League Beta's full search fell from about 225 seconds to about 63 seconds while
retaining 6,226 enumerated packages, 33 exact evaluations, identical rejection
counts, and no target. League Alpha retained 5,094/27 and no target. Complete
quality, privacy, packaging, publication, and remote checks pass. Details are
in `docs/COMPLETED_TRADE_ASSISTANT_TA_1201.md`.

Trade TA-1101 — Single-command Trade analysis is complete. Diagnose, evaluate,
gaps, search, and compare now prepare required current evidence automatically,
reuse fresh caches, preserve explicit overrides and offline replay, retain
league-local policy authority, and remain read-only. Both configured leagues
completed direct diagnosis and search from the default config. All 588 tests
and Ruff pass. League Beta's roughly 225-second bounded search remains a performance
target. Details are in `docs/COMPLETED_TRADE_ASSISTANT_TA_1101.md`.

WA-022 — Single-command Waiver readiness and report reliability is complete.
`roster-theory waiver search LEAGUE` now prepares stale/missing provider facts,
builds or reuses the league-local input bundle, and produces the report without
requiring `inputs prepare`, `waiver inputs`, or `--inputs`. The FantasyPros
expert-directory parameters and timestamp handling match the live provider
contract; shared history is resumable; five-minute freshness is consistent;
legacy same-league policy metadata migrates with backups; and per-search caches
reduce verified live runtime while preserving results. Both configured leagues
complete read-only from the default per-user config. All 582 tests and Ruff
pass. Details are in `docs/COMPLETED_WAIVER_ASSISTANT_WA_022.md`.

Replacement Counterfactual Consistency is complete. Trade and general Waiver
lineup deltas now optimize the active bench first and compare bye/inactive
capacity with the best legal, acquirable waiver alternative. A Waiver target
is excluded from its own baseline, structural roster holes do not assume an
extra transaction, and replacement IDs are auditable in evidence and human
reports. Draft's legacy bye sensitivity now reports reserve value above the
waiver floor while retaining the total filled and floor components. Focused
feature tests, all 575 repository tests, and Ruff pass. No provider request,
league calibration transfer, transaction, or Sleeper write occurred. Details
are in `docs/COMPLETED_REPLACEMENT_COUNTERFACTUAL_CONSISTENCY.md`.

Trade Phase 10 — Ranking-exclusion resilience and roster-context targets is
complete. Provider-only rank slots no longer collapse projection curves;
automatic targets respect one-starter roster capacity and report incoming
lineup use. League Alpha evidence hash `f46d834e73b0935a` and League Beta hash
`7cfa494b39a6ed4b` both replay and return no target. Beta passes the former WR
106/107 stop. The dedicated context gate passes 14 tests, all 568 repository
tests pass, and CI runs context routing separately on every push and pull
request. No Sleeper write occurred. Exact evidence is in Trade Phase 10.

OS-013 — GitHub publication and post-publication verification is complete as
of September 16, 2026 (America/Los_Angeles). The reviewed source-only alpha is
public at <https://github.com/jaretjb/RosterTheory>. Remote `main` was replaced
by a fresh repository whose history starts at the approved sanitized root. The
original GitHub repository is retained as the private
`RosterTheory-private-archive`; this avoids exposing unreachable objects that
GitHub retained after the initial force-update. The replacement's complete
release workflow and full-history Gitleaks scan pass. Anonymous repository,
README, license, clone, install, retired-SHA, and offline `doctor` checks pass.
No tag, GitHub release, PyPI upload, provider request, or Sleeper write occurred.
Details are in
`docs/COMPLETED_OPEN_SOURCE_RELEASE_OS_013.md`.

OS-007 — Public alpha release candidate is complete as of September 16, 2026
(America/Los_Angeles). The reviewable `0.1.0` source-only alpha is a sanitized
single-root local branch whose tree matches the reviewed preparation branch.
The existing private history and ignored evidence remain preserved. Clean-clone
release gates, full-candidate-history Gitleaks, identity/privacy review,
redistribution review, packaging, and isolated installation pass. No candidate
history was pushed; no tag, GitHub release, visibility change, or package upload
occurred. Details are in `docs/COMPLETED_OPEN_SOURCE_RELEASE_OS_007.md`.

OS-006 — Automated public-release quality and security gates is complete as of
September 16, 2026 (America/Los_Angeles). The `release gates` workflow blocks
on the complete suite across supported Linux/Windows Python versions plus a
macOS smoke matrix, focused CLI/output contracts, unsafe tracked artifacts,
full-history Gitleaks findings, pinned Ruff and pip-audit checks, distribution
contents, and a clean wheel install. All 564 tests and every locally runnable
gate pass; remote CI will execute on push or pull request. Details are in
`docs/COMPLETED_OPEN_SOURCE_RELEASE_OS_006.md`.

OS-018 — Unified season preparation and runtime refresh is complete as of
September 16, 2026 (America/Los_Angeles). `roster-theory inputs prepare/status`
now provides preflighted, resumable, freshness-aware preparation for
selected/all leagues and Draft/Trade/Waiver modes. Shared provider evidence is
reused while league policies, derived inputs, readiness, and results remain
isolated. The installed CLI also builds Waiver input bundles without a source
checkout. All 560 tests pass; wheel workflows were verified in PowerShell and
Git Bash with paths containing spaces and redirected JSON. Details are in
`docs/COMPLETED_OPEN_SOURCE_RELEASE_OS_018.md`.

OS-015 — Expert evidence and in-season pool refresh commands is complete as of
September 16, 2026 (America/Los_Angeles). `roster-theory inputs experts`
provides inspect, refresh, validate, and import workflows for all Draft accuracy
inputs and the league-scoped in-season pool. Refreshes retain replayable source
evidence and an auditable selection/rejection record, respect the one-request-
per-second and 500-request daily limits, and fail closed on incomplete coverage,
stale availability, or ambiguous identity. Preseason accuracy is never used as
in-season authority. All 537 tests pass; no Sleeper write occurred. Details are
in `docs/COMPLETED_OPEN_SOURCE_RELEASE_OS_015.md`.

TX-002 console marquee alignment is complete as of September 16, 2026
(America/Los_Angeles). Wide, standard, compact, narrow, Unicode, and ASCII
interactive heroes now carry the finalized `ROSTER THEORY` marquee hierarchy:
`FANTASY FOOTBALL ASSISTANT` immediately above the Draft/Trade/Waiver mode
line. Redirected, JSON, and suppressed-banner output remain unchanged. All 528
tests pass; decision behavior is unchanged.

TX-002 README artwork refinement is complete as of September 16, 2026
(America/Los_Angeles). The vector marquee now uses larger, heavier pixel
letters with a hard-edged 1990s arcade extrusion; `ROSTER` is vertically
rebalanced, and `FANTASY FOOTBALL ASSISTANT` appears immediately above the
Draft/Trade/Waiver mode line. A native 1200x520 browser render was visually
reviewed. All 528 tests pass; terminal behavior, machine output, and decision
policy are unchanged.

TX-002 arcade amendment is complete as of September 16, 2026
(America/Los_Angeles). The terminal and README now use an original
bright-yellow 1980s arcade-scoreboard identity. Wide terminals render both
`ROSTER` and `THEORY` as equally large stacked pixel words; standard and
compact command mastheads inherit the arcade framing, with aligned ASCII and
narrow fallbacks. The logo's `read-only` marketing tagline was removed while
factual safety boundaries remain in operational text. All 528 tests pass;
machine output and recommendation behavior are unchanged.

TX-003 — Doctor health-board human view is complete as of September 16, 2026
(America/Los_Angeles). Doctor now opens with the full interactive identity and
renders a concise offline/read-only checkup, a per-league Draft/Trade/Waiver
data-versus-decision matrix, league-scoped next actions, and an explicit ready
check count. `--details` exposes every original check. JSON remains unchanged,
and Doctor still makes zero provider calls and zero Sleeper writes. All 527
tests pass. Details are in `docs/COMPLETED_TERMINAL_EXPERIENCE_TX_003.md`.

TX-002 — Full Roster Theory wordmark and command mastheads is complete as of
September 16, 2026 (America/Los_Angeles). The interactive hero spells out the
full product name with adaptive original sideline-card borders; routine
commands and command help use full-name command mastheads. Redirected and
machine output remain undecorated. Details are in
`docs/COMPLETED_TERMINAL_EXPERIENCE_TX_002.md`.

TX-001 — Terminal visual primitives and output boundaries is complete as of
September 16, 2026 (America/Los_Angeles). Shared width tiers, Unicode/ASCII
fallbacks, palette tokens, status styling, and visible-width handling now
provide the stable foundation for human terminal presentation. Details are in
`docs/COMPLETED_TERMINAL_EXPERIENCE_TX_001.md`.

WA-018 — Action-first human Waiver search report is complete as of September
16, 2026 (America/Los_Angeles). Human search output now leads with the action,
best move, plain-English reason, and current-week effect, followed by compact
DST, kicker, and watchlist sections. Audit counts, policy IDs, pruning proofs,
and full reversals remain in JSON and saved evidence. Windows PowerShell and
narrow/redirected output are verified. All 520 tests pass; no decision logic or
Sleeper state changed. Details are in
`docs/COMPLETED_WAIVER_ASSISTANT_WA_018.md`.

WA-019 — Reliable FantasyPros-to-Sleeper DST identity reconciliation is
complete as of September 16, 2026 (America/Los_Angeles). Waiver value refreshes
retain the Sleeper K/DST identity directory without expanding Trade's valuation
universe, and uniquely normalized NFL team abbreviations reconcile FantasyPros
numeric defense IDs. Exact DST evidence now preserves and reports both defenses'
current-week points and ranks. A live read-only search recovered the full DST
pool and surfaced the expected streaming alternatives. All 519 tests pass; no
Sleeper write occurred. Details are in
`docs/COMPLETED_WAIVER_ASSISTANT_WA_019.md`.

WA-021 — Prevent stale Draft anchors from vetoing fresh Waiver dominance is
complete as of September 16, 2026 (America/Los_Angeles). Waiver input evidence
now identifies the actual long-term value horizon and uses a two-hour ranking
and expert cache window. The narrowly bounded same-position dominance path is
protected from pruning and rechecked by exact evaluation. Live local validation
selects the intended same-position upgrade. All 514 tests pass; no Sleeper
write occurred. Details are in `docs/COMPLETED_WAIVER_ASSISTANT_WA_021.md`.

WA-020 — Explain notable omitted and pruned Waiver candidates is complete as
of September 16, 2026 (America/Los_Angeles). Human search output now gives a
small deterministic shortlist with available ranks, roster comparison, and a
plain exclusion reason. Top Waiver players outside complete value-board
coverage remain visible but ineligible. The completed amendment raises the
shared RB valuation minimum from 50 to 60, so RB51-RB60 receive normal complete
evaluation. All 511 tests pass. No provider request or Sleeper write occurred.
Details are in
`docs/COMPLETED_WAIVER_ASSISTANT_WA_020.md`.

WA-017 — Current-week inactive projection omission resilience is complete as
of September 15, 2026 (America/Los_Angeles). Waiver search and entered
evaluation reconcile only a current-week FantasyPros omission zero supported
by fresh league-local Sleeper inactive status. Waiver player-directory cache
age is capped at five minutes; future availability is not inferred. All 508
tests pass. No live provider request or Sleeper write occurred. Details are in
`docs/COMPLETED_WAIVER_ASSISTANT_WA_017.md`.

WA-015 — Live audit acceptance closure is complete as of September 15, 2026
(America/Los_Angeles). Both leagues were audited read-only; saved successful
searches replay by hash, and the fresh incomplete search failed closed on a
FantasyPros Week 2 projection omission. There was no affirmative move or
Sleeper write. Provider coverage and role limitations remain visible, and no
policy was promoted. The Waiver JSON reporting defect is repaired; all 505
tests pass. Details are in docs/COMPLETED_WAIVER_ASSISTANT_WA_015.md.

OS-005 — Installable package and public documentation is
complete as of September 15, 2026 (America/Los_Angeles). The initial release
is GitHub source-only; no distribution was published. OS-006 is next and must
be activated separately.

OS-009 — Interactive and machine-output contract is complete. Terminal
capabilities are detected centrally; `--json` commands produce one valid JSON
value with saved-path notices on stderr. Machine failures preserve status,
type, and reason. Watcher JSON is one report collection when it stops, while
human reports remain readable. Redirected, narrow, `NO_COLOR`, Windows/Linux,
and exit-code coverage pass; the complete 483-test suite passes.

OS-010 — Original adaptive terminal identity is complete. Original amber/ASCII
RT art appears only on interactive welcome and guided help; narrow terminals
get a one-line fallback, selected human reports get a compact mark, and
`--no-banner` suppresses both. Redirected, JSON, CSV, evidence, log, error,
and ordinary argparse help output are undecorated. Snapshot and boundary tests
pass, and the full 489-test suite is green. Details are in
`docs/COMPLETED_OPEN_SOURCE_RELEASE_OS_010.md`.

OS-011 — Read-only setup diagnostics is complete. The offline `doctor` command
checks config, identity, league-scoped policies, and selected local inputs;
Draft, Trade, and Waiver readiness remain separate. Human and redacted JSON
views preserve safe next actions without implying fresh evidence or portable
calibration. All 496 tests pass. Details are in
`docs/COMPLETED_OPEN_SOURCE_RELEASE_OS_011.md`.

OS-012 — Draft, Trade, and Waiver human decision reports now share a context-
first frame, with prominent failure readiness and evidence paths at the end.
Draft simulation and board-source refresh show cancellable start/end progress
only on interactive human stdout. JSON/piped modes stay silent. All 502 tests
pass; details are in `docs/COMPLETED_OPEN_SOURCE_RELEASE_OS_012.md`.

OS-005 — Complete package metadata and public setup, contribution, security,
conduct, and changelog documents are in place. A bundled synthetic config
works from a wheel outside the checkout; external expert and schedule inputs
give actionable errors. Wheel and source archive contents were inspected,
fresh-wheel offline smoke tests passed, and all 505 tests pass. Details are in
`docs/COMPLETED_OPEN_SOURCE_RELEASE_OS_005.md`.
