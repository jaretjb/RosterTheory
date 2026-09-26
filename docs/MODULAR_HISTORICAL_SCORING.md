# MA-002g Waiver historical scoring evidence

September 26, 2026. Bounded #30 follow-up from merged PR #40. MA-002 and #30
remain open.

## Problem and result

Waiver's season and recent-game performance preparation previously used partial
`score_stats(...).points` directly. A synthetic QB row with 250 passing yards
but no passing-touchdown field became 10 season points and received a position
rank. The same row with an explicit touchdown count of zero also became 10; the
tool could not distinguish those cases. Unsupported active settings likewise
left a partial total in the ranking.

The historical Sleeper translator now uses the versioned scoring-evidence
contract. It assesses the **actual league's** rules once per season/week scope,
then scores only exact, finite observations applicable to each player position.
An explicit zero is valid. Missing, invalid, unknown-applicability and
unsupported settings make the historical points unavailable while retaining
the source row and a per-player reason. No absent field is treated as a
structural zero. [Sleeper's scoring categories](https://support.sleeper.com/en/articles/3998131-what-scoring-options-are-available)
support position/category separation; they do not establish a sparse-stat zero
convention for the public stats endpoint.

Season position ranks now use only complete season totals. A recent points-per-
game average and rank require every *included* observed week to score
completely; an incomplete week cannot contribute a partial value. The existing
game-sample count still describes the observed sample, not a claim that every
calendar week had a player row. Opportunity and yard metrics remain independent
of league-point coverage. A missing season/weekly row is reported as unavailable
for that player rather than filled with zero.

Warnings flow into the existing Waiver `PlayerValueInput.warnings` and an
additive `performance_scoring_unavailable_players` data-only build-report field.
Candidate evaluation already surfaces warnings for the
players it actually compares, so an unrelated player's missing history does not
veto that decision. Existing specialist projection-only policy remains in place
when historical production is unavailable; this slice does not change its
thresholds. Saved input readers and schema stay unchanged.

The Sleeper scoring-category catalogue is shared with the FantasyPros weekly
translator, without sharing source-stat assumptions. Its rule records and the
FantasyPros catalogue version are unchanged, preserving weekly calculation
behavior. Historical input accepts exact canonical stat keys and finite numeric
values, including numeric strings at the provider boundary; no unverified
aliases or zero defaults were added.

## Evidence and limits

Before-fix regressions demonstrated the omitted touchdown, unsupported-rule
and missing-warning failures. Synthetic tests now cover QB/receiver premiums,
K/DST applicability, explicit zero, invalid/nonfinite observations, a missing
week in a recent average, independent complete players and distinct league
scoring maps. The reference scoring maps still have unresolved `fum_rec`
applicability, so neither gains complete historical league-point evidence from
this slice. It does not certify either league for recommendations.

The full suite passes **902** tests, including unchanged MA-001 reference output
goldens. Ruff, compilation, context routing and repository privacy gates pass
locally; required PR CI and review remain the merge gate. No provider calls,
live simulation, league action, user configuration edit or calibration transfer
occurred.

Draft projection imports, other legacy `score_stats` consumers, provider sparse-
field definitions and full #30 capability admission remain separate work.

A local synthetic 5,000-row scoring batch took 0.463 seconds (0.093 ms per
row) versus 0.244 seconds for the legacy partial scorer. This measures only
calculation on one Windows host, not network or end-to-end preparation.
