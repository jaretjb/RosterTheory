# MA-002b: explicit provider projection coverage

Status: scoring integration tested (847 tests, all 20 CI checks at `ae07d4e`),
but PR #37 is held as a draft pending decision-specific readiness acceptance.
Tracking: [issue #30](https://github.com/jaretjb/RosterTheory/issues/30).
Requirements: MR-01, MR-02, MR-04, MR-06, MR-09.

## Behavior and boundaries

FantasyPros weekly projections now use the MA-002a scoring contract through one
shared adapter path. Trade preparation and its Waiver consumer use that same
path, including when re-reading cached raw responses. A player with 250 passing
yards and no touchdown forecast previously received 10 points marked complete
under 0.04 points/yard and 6 points/TD. The diagnostic total remains 10, but the
missing touchdown field blocks completeness. An explicit observed zero TD is
complete. Unknown nonzero rules, invalid statistics/multipliers, conflicting
aliases and unresolved position applicability also block completeness.

Existing coverage gates exclude incomplete players from Trade projection curves
and preserve missing points in shared Trade/Waiver lineup evidence. No partial
total becomes a zero-point observation or a usable recommendation input through
this path. Genuine complete fractional, negative and zero values remain usable.
Rankings still have their original provider authority and scoring label; raw
projection rescoring does not manufacture custom expert rankings.

This is deliberately conservative. It may make previously available results
unavailable. Passing and receiving remain possible for any individual offensive
position, including kickers; absent off-role forecasts are not assumed zero.
No documented provider structural-zero convention has been established here.
Rare events and exact specialist buckets can remain missing even in otherwise
substantial projection rows. **Neither reference league has been certified
recommendation-ready by this work.**

No paid provider retrieval, live simulation, league mutation, policy/calibration
change, historical-stat scoring change or Draft import change occurred. The
legacy `core.scoring.score_stats` remains for those other callers. MA-002 and
issue #30 remain open; this slice does not solve league admission or membership.

The user's subsequent clarification requires irrelevant missing players to stop
blocking independent trade/waiver decisions. See
[MR-02 section 3.1](MODULAR_REQUIREMENTS.md#31-missing-evidence-must-have-decision-specific-consequences).
The existing roster-wide Trade gate and coarse Waiver position grouping do not
yet establish that requirement. Preserve this scoring evidence work, but do not
promote its stricter gates as a usable rollout until candidate relevance and
conditional results are implemented and tested. This is an acceptance correction,
not permission to assign zero to unknown players or missing scoring categories.

## Rule catalogue and source evidence

`providers/projection_scoring.py` owns the provider translation and version
`fantasypros-weekly-v1`; provider aliases do not enter the neutral core. Its
catalogue describes linear arithmetic and applicability, not field availability.
Assessment happens once per response, before per-player evaluation.

Sleeper's [scoring category reference](https://support.sleeper.com/en/articles/3998131-what-scoring-options-are-available)
distinguishes passing, rushing, receiving, position reception premiums, kicking,
team defense, player special teams and miscellaneous events. Its
[special-teams explanation](https://support.sleeper.com/en/articles/3278982-special-teams-scoring-options)
explicitly separates player events from team-defense events. Reviewed September
26, 2026. These support category boundaries; they do not prove FantasyPros
projection completeness or sparse-field semantics.

The [FantasyPros public API documentation](https://api.fantasypros.com/public/v2/docs)
identifies the NFL projections endpoint and example stat fields. The private v2
documentation returned 403 in this review. Neither available documentation nor
the existing adapter establishes that every omitted field is zero. Existing
unambiguous aliases such as `pass_yds`, `pass_tds`, `rec_rec`, `rec_yds`,
`rush_yds`, `fumbles_lost`, `def_int` and `def_sack` remain explicit translation
inputs, with synthetic regression coverage. No season/position-wide delivery
guarantee is inferred from those examples or tests.

| Category | Treatment |
| --- | --- |
| Passing/rushing/receiving, player special teams, lost fumbles and fumble-return TDs | Require exact observations for individual positions QB/RB/WR/TE/K; team-defense fields cannot substitute |
| Position reception premiums | Require reception observations only for the named RB/WR/TE position |
| Kicking | Require exact counts/buckets for K; total field goals cannot supply distance buckets |
| Team defense and team special teams | Require exact observations for DST (`DEF` normalizes to DST); points-allowed averages cannot supply event probabilities |
| `fum_rec` | Applicability remains explicitly unresolved; preserves a limitation for later evidence review |
| Unknown nonzero settings | Unsupported; no threshold-event derivation from yardage averages |
| Zero settings | Disabled, including unknown settings; a string `"0"` is an invalid multiplier, not a disabled rule |

Ambiguous legacy translations are intentionally withheld: `fumbles` does not
prove `fum_lost`; `def_ff`/`def_fr` do not prove team-special-teams forced fumbles
or recoveries; `def_retd` does not prove team-special-teams TDs. Lettered
`def_pa_a` through `def_pa_g` also require verified bucket definitions before
use. Exact canonical event fields remain accepted. Multiple supplied aliases
must be finite and agree; alias order cannot hide a contradiction or null.

Both redacted MA-001 profiles are covered by an inventory regression:

| Reference | Active settings accounted for | Disabled settings | Remaining rule assessment |
| --- | ---: | ---: | --- |
| A | 35 | 113 | LIMITED: `fum_rec` applicability |
| B | 41 | 2 | LIMITED: `fum_rec` applicability |

Every supplied setting is classified. Empty provider evidence remains incomplete
for all six positions. These counts are rule accounting, not provider coverage.
The older MA-002a inventory stays frozen as the historical unverified inventory.

## Compatibility, provenance and rollback

Projection fields and artifact readers retain their existing shapes. Incomplete
rows now carry `scoring_incomplete_v1:<category>=<setting>;...`, with sorted,
deduplicated issues. This replaces the three narrower reception/rescoring failure
labels from the previous preparation path. Existing readers already preserve
the string and treat statuses outside the complete whitelist as incomplete.
Bare `normalize_projections` now defaults to `unverified_scoring_v1`; having some
numeric fields alone is no longer a completeness check.

Numeric strings are parsed; booleans, empty/non-numeric values and nonfinite
strings are invalid. Invalid required fields remain visible in coverage even
though the legacy raw-stat tuple accepts only numeric values. Raw NaN/Inf cannot
be canonically hashed and stop preparation visibly. Malformed or duplicate
player identities stop preparation rather than being silently discarded.

The source stamp retains the raw payload hash and provider-declared scoring
label, and now binds the actual scoring map. Its parameter hash covers provider
parameters, the scoring contract version and the league/season/week rule hash.
Prepared source evidence also declares `projection_scoring_contract`. Direct
callers can pass `league_id`; omitted IDs explicitly use `unbound` and are not
league-bound admission evidence. Trade/Waiver preparation supplies the actual ID.

Cached raw payloads need no rewrite and are reassessed on preparation. Previously
saved derived boards/results are historical evidence, not retroactively verified
by this patch; rerun preparation before relying on current coverage. MA-001
semantic goldens and CLI contracts stay unchanged. Rollback means reverting the
provider/preparation integration via a PR; it would restore the known false
completeness behavior and must not be described as a coverage fix.

## Validation and next handoff

Two independent regressions failed against the old adapter before the fix:
missing TDs and unsupported active scoring both appeared complete. Seventeen
new tests cover arithmetic, observed/missing/invalid zero, aliases, all positions,
unknown rules, event buckets, malformed rows, reference accounting, league/scope
hashes, fresh/cached preparation equivalence, serialization, canonicalization,
Trade curves and shared Trade/Waiver projection matrices.

Run `python -m unittest tests.test_provider_scoring_coverage` and the full suite
with `PYTHONPATH=src;.` on Windows (`src:.` on POSIX). The offline benchmark is
`python scripts/ma002_projection_benchmark.py`: 400 synthetic players per week,
both reference scoring maps, one warm-up and five measured repeats per path.
The legacy timing comparator deliberately preserves the old coverage bug;
performance comparison does not certify its result correctness. Synthetic zero
fields are explicit fixture observations, never a production zero convention.

Local validation: **847 tests passed in 102.698 seconds**, including unchanged
MA-001 semantic goldens and the PR #36 clock regressions. Ruff, compilation,
context routing and tracked/staged privacy checks pass. No existing baseline
artifact was regenerated. Required remote CI remains the merge gate.

Measured milliseconds on this Windows workspace (five repeats after warm-up):

| Reference/path | Repeats (ms) | Median (ms) |
| --- | --- | ---: |
| A / legacy | 81.865, 75.179, 73.904, 73.165, 76.562 | 75.179 |
| A / strict | 97.792, 99.023, 102.206, 106.495, 117.980 | 102.206 |
| B / legacy | 66.331, 67.887, 65.069, 65.582, 73.990 | 66.331 |
| B / strict | 107.094, 105.895, 105.870, 105.002, 121.192 | 105.895 |

The added median preparation cost is roughly 27/40 ms for a 400-player week.
These local measurements include normal background activity and are not an
end-to-end refresh SLA. No search/evaluation performance improvement is claimed.

Next: resolve provider event definitions and omitted-field semantics using
source evidence, then decide any bounded approximation policy explicitly before
restoring readiness. Handle historical production evidence and legacy Draft
scoring in separate reviewed slices; do not copy projection assumptions into
actual game-stat sources. League admission, full rule/context interfaces,
static type-check gates and roster membership (#31) also remain MA-002 work.
