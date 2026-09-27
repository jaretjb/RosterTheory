# MA-002m: FantasyPros projection-source tier evidence

Status: bounded issue #30 follow-up; CI and review remain the merge gate.

Four read-only 2026 week-zero FantasyPros projection requests were made on
September 26, paced more than one second apart. Only aggregate schema facts
were inspected; no response rows, player identities, values, league data or API
key were stored in this change. The RB, WR, K and DST responses declared the
requested season, week and position, and each returned
`public_api_limited=true`. Their player counts were 132, 203, 44 and 32.
Every observed player's `stats` value was a mapping. The
[public documentation](https://api.fantasypros.com/public/v2/docs) shows a
list-shaped example, but these actual sample-tier responses do not justify a
list-shape conversion in the scorer.

The observed RB and WR statistic-key sets included `fumbles` but not
`fum_rec`; K exposed `fg`, `fga` and `xpt` without field-goal distance buckets;
DST exposed `def_fr` and lettered points-allowed fields. These are observations
of limited public responses, not proof of HOF Premium coverage, provider field
definitions, omitted-field structural zeros or cross-league calibration.
`def_fr` cannot be equated to an individual `fum_rec` event without separate
evidence. Sleeper's [scoring-options guide](https://support.sleeper.com/en/articles/3998131-what-scoring-options-are-available)
distinguishes team-defense, special-teams and individual defensive recovery
categories. Both reference rule maps remain LIMITED for unresolved `fum_rec`.

Previously, Draft import readiness checked `public_api_limited` only on the
expert-directory response. A premium-looking directory could mask a limited
projection response. The board now requires every QB/RB/WR/TE projection
response to declare `public_api_limited=false` before `draft_ready` can be true.
An explicit limited or missing tier declaration produces a source-level issue;
diagnostic ranks and point totals remain inspectable. The top-level limited
flag records an explicit sample response, while the readiness check also
rejects unknown tier evidence. Expert weights and ranking policy are unchanged.

Synthetic regressions cover one limited source among otherwise ready
projections and a source with no tier declaration. No live Draft operation,
simulation or Sleeper write occurred. Actual premium provider coverage,
ranking-response tier evidence, `fum_rec` semantics, #31 and overall MA-002
remain open.

Local handoff: 915 tests pass with unchanged MA-001 reference goldens; Ruff,
compilation, context routing and tracked-tree privacy checks pass.
