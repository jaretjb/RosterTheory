# MA-002n: FantasyPros Draft ranking-source tier evidence

Status: bounded issue #30 follow-up; CI and review remain the merge gate.

Two read-only FantasyPros 2026 Draft RB/HALF ranking requests were made on
September 26, paced more than one second apart. One consensus response reported
259 rows and 192 experts; one filtered single-expert response reported 94 rows
and one expert. Both declared year 2026, week zero, RB, HALF, and Draft scope.
Both also returned `public_api_limited=true` alongside `tier="premium"`.
These are aggregate response facts only; no player rows, identities, ranking
values, private responses or API key are included in the change. The
[public API reference](https://api.fantasypros.com/public/v2/docs) documents
ranking scope fields but does not establish that a `premium` tier label overrides
an explicit limited-response flag.

Before this change, Draft readiness checked the expert-directory tier and each
projection response, but not the consensus or selected-expert ranking
responses. A limited ranking source could therefore influence a board called
draft-ready if the other checks passed. The importer now records the tier
declaration for every ranking source and requires each to report
`public_api_limited=false`. Explicitly limited and undeclared tier responses
remain inspectable as diagnostic ranks, with distinct source-level issues;
neither can establish Draft readiness. The top-level sample flag reflects an
explicitly limited ranking source even if another endpoint says premium.

Synthetic regressions cover limited ECR, unknown single-expert tier, the
contradictory `tier="premium"` label, intact independent ranks and unchanged
scoring coverage. All 915 local tests pass, along with Ruff, compilation,
context-routing and tracked-tree privacy checks. No live Draft operation,
simulation, league write, expert
weight or Trade/Waiver change occurred. Real HOF Premium source coverage,
provider field definitions, `fum_rec`, #31 and overall MA-002 remain open.
