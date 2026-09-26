# MA-002k: Draft API ranking-source scope

Status: bounded issue #30 follow-up; CI and review remain the merge gate.

The FantasyPros Draft API import previously treated every consensus-rankings
response as a preseason board because the request was for a Draft season. A
weekly, rest-of-season, fallback, or mismatched response could therefore enter
expert ranks or ECR and still satisfy the import-readiness checks. FantasyPros'
[public API schema](https://api.fantasypros.com/public/v2/docs) declares the
ranking type, year, week, scoring format, and position on each response.

The import now requests `type=DRAFT` and `week=0` for ECR and each selected
expert. It uses a response only when those provider-declared fields identify
the requested preseason season, position, and scoring format, and when no
`fallback_for` label is present. A missing declaration is unverified; request
arguments do not stand in for provider evidence. Invalid responses contribute
no ranks or ECR. Other experts and positions remain usable, with each source's
declarations and issue reasons in board metadata. Any unverified ranking source
keeps `draft_ready` false, while the available board can still be inspected.

Synthetic tests cover wrong ranking horizons, fallback, missing declarations,
wrong year/week/scoring/position, explicit request arguments, and independent
valid-source preservation. No paid provider request, live Draft operation,
simulation, league write, expert-weight change, or Trade/Waiver change occurred.
The real provider's field values and source coverage are not yet verified;
`fum_rec`, the reference leagues' positional-cap source mapping, and broader
MA-002 acceptance remain open.

Local handoff: 913 tests pass with unchanged MA-001 reference goldens; Ruff,
compilation, context routing and tracked-tree privacy checks pass.
