# MA-002i: Draft manual projection scoring evidence

Status: bounded issue #30 follow-up; CI and review remain the merge gate.

The manual FantasyPros preseason CSV parser previously converted an absent
stat column, blank cell, malformed value and explicit zero to the same `0.0`.
It then published the resulting partial league point total as a complete
projection. Those points could enter replacement baselines and the import's
draft-readiness percentage. A QB row with 250 passing yards but blank passing
touchdowns, for example, could be counted as a 10-point complete projection
under 0.04 points per passing yard and six per passing touchdown.

The parser now retains only explicitly present cells. A finite numeric zero is
an observation; a blank or absent cell is missing; a nonnumeric or nonfinite
cell is invalid. The Draft manual export adapter assesses the actual Sleeper
scoring settings against the shared position-aware linear catalogue, scoped to
the league and preseason season. Only a complete score becomes
`projected_points`; incomplete rows retain their expert ranking and ADP but
carry a row-level `scoring_incomplete_v1` issue with every blocking category.
Only complete point totals enter replacement baselines and projection-coverage
readiness. The original board columns and command name are unchanged; metadata
adds a scoring-contract label and complete-scoring count.
It also records the scoped league, season and scoring/rule hashes for audit.

No absent off-role statistic is assumed zero. An ordinary manual export may
therefore retain no complete projections under a broad scoring map, including
the synthetic four-player sample: its rankings remain usable for review, but
it is not draft-ready. This is an evidence limitation, not proof that the
players score zero. `fum_rec` applicability remains unresolved for the two
reference leagues. The separate live FantasyPros API Draft import still uses
legacy scoring and remains issue #30 work. No provider field delivery or
structural-zero convention was established by this change.

Focused synthetic cases cover explicit zero versus blank, missing, invalid and
nonfinite fields, an applicable off-role statistic, an unsupported rule, and
retained expert rankings when projections are incomplete. The full suite and
unchanged MA-001 reference goldens are required for handoff. No provider call,
live Draft operation, simulation, league write, ranking-weight or acquisition
policy change occurred. #30, #31 and MA-002 remain open.

Local handoff: 907 tests pass, including unchanged MA-001 reference goldens;
Ruff, compilation, context-routing and tracked-tree privacy checks pass.
