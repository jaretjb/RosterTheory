# MA-002r: FantasyPros preseason lost-fumble field (#30)

September 28, 2026. Base: merged PR #62 (`87ab936`).

## Fantasy-football effect

A Draft projection that includes a FantasyPros `fumbles` value can now apply
the league's lost-fumble penalty. Previously, this one supplied value was
treated as missing in Draft scoring. A missing value is still missing; no
other absent statistic is filled with zero. Expert rankings, weights, Draft
preferences and Trade/Waiver decisions are unchanged.

FantasyPros's [preseason RB table](https://www.fantasypros.com/nfl/projections/rb.php?week=draft)
labels its fumble column `FL` and defines that as fumbles lost. Its
[NFL projection API example](https://api.fantasypros.com/v2/docs) is a week-zero
season response with `fumbles: 2.85` and 293.7 standard points. The shown
rushing and receiving line totals 299.398 before fumbles; subtracting
`2.85 × 2` yields 293.698, matching the example after rounding. This connects
the API field to lost fumbles for this preseason source. The same mapping was
already established for the separate weekly source in PR #50.

## Before and after

The following invented QB row has one interception and `fumbles: 2.85`.
Only the two named scoring rules were selected from each reference profile to
isolate the change; these are not complete league scoring maps.

| Reference | Interception rule | Before: usable score | After: usable score |
| --- | ---: | --- | ---: |
| A | -2 | unavailable; diagnostic -2, lost fumbles marked missing | -7.7 |
| B | -1 | unavailable; diagnostic -1, lost fumbles marked missing | -6.7 |

The before result was calculated with the merged main scorer and the after
result with this branch on the same synthetic row. The full reference scoring
maps still contain other unresolved categories, including `fum_rec`, so this
does not make either profile Draft-ready. A synthetic one-player API import now
retains the -5.7 lost-fumble score under a single-rule map, but does not pass
the independent board-readiness coverage requirements.

The Draft scoring contract label changes from
`fantasypros-draft-season-v1` to `fantasypros-draft-season-v2`. New imports
declare the corrected mapping. Saved v1 boards are not rewritten or
retroactively certified; exact-build replay keeps their original interpretation.
An old board should be re-imported from current source evidence for new scoring.

Tests cover both reference multipliers, missing and conflicting fields,
unchanged full-map incompleteness, and the actual API-board import path. No
paid provider request, Sleeper action, private history review, policy change or
support promotion occurred. #30 remains open for the other provider fields,
`fum_rec` applicability and full acceptance criteria. Reverting this PR
restores the prior mapping and v1 contract label; it does not alter saved data.

Local verification: 39 focused tests and all 956 repository tests pass,
including the unchanged MA-001 reference goldens. Ruff, compilation, 18
context-routing checks, tracked repository privacy, package build,
distribution checks, clean wheel-install smoke and import smoke pass. Staged
privacy and remote CI are the final PR gates.
