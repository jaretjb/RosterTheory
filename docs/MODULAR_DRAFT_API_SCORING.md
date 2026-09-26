# MA-002j: Draft API projection scoring evidence

Status: bounded issue #30 follow-up; CI and review remain the merge gate.

The FantasyPros API Draft board previously passed each preseason `stats` map
through the legacy scorer. It used the resulting subtotal as `projected_points`
even when an active Sleeper rule lacked a statistic or had invalid evidence.
Those totals could enter replacement baselines. The CLI also called any
non-sample API board ready, regardless of projection coverage.

The Draft API path now assesses the actual league scoring map in an explicit
league/season `DRAFT-API-IMPORT` scope and translates unambiguous FantasyPros
aliases through the provider scoring adapter. Its source schema is
`fantasypros-draft-season-v1`, distinct from weekly/ROS projections. An explicit
finite zero is usable; a missing, invalid or conflicting value is not. Unknown
active scoring rules and unresolved position applicability block complete
points. Provider responses with a conflicting declared season or positive week
cannot supply preseason points. Malformed rows, missing or duplicate FantasyPros
IDs, position mismatches, missing stats and unmatched projection/ranking IDs
produce metadata issues rather than silently becoming scores.

Expert ranking rows, weights, ECR and ADP remain independent. Only complete
projection totals enter the board and replacement baselines. Import readiness
now requires explicit premium API evidence, multi-year accuracy for at least
five experts with current returned rankings, at least
150 ranked skill players, all four positional replacement baselines and at
least 90% complete projection coverage in the top 180 ranked players. These
mirror the existing manual-import coverage gates. A missing player below that
group does not veto the board; a material top-board gap does. This is import
readiness, not approval to operate a live Draft room.

Metadata retains provider-declared season/week/scoring labels per position and
records the scoring/rule hashes, support state, coverage and detailed issues.
The provider's absent scope declaration is not proof of a season-wide delivery
guarantee; the requested season is the calculation scope unless the response
contradicts it. No provider structural-zero convention is assumed. Expert rank
fallback/horizon authority and the two reference leagues' unresolved `fum_rec`
still require separate evidence. The legacy scorer remains only as a
compatibility wrapper, not a production Draft scoring path.

Synthetic fake-client regressions cover explicit zero versus missing/nonfinite,
conflicting aliases, unknown rules, duplicate IDs, weekly response mismatch,
independent expert ranks and top-board versus unrelated-player readiness. The
weekly/ROS adapter retains its existing schema. No paid API call, live Draft
operation, simulation, league write, ranking-weight or acquisition-policy
change occurred. #30, #31 and MA-002 remain open.

Local handoff: 910 tests pass, including unchanged MA-001 reference goldens;
Ruff, compilation, context routing and tracked-tree privacy checks pass.
