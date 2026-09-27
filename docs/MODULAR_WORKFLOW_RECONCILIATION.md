# MA-002o: working-workflow reconciliation

This review compares the accepted pre-MA-002 source at `c4e402a` with the
current main after PR #48. It uses synthetic public fixtures and aggregate
counts from ignored, locally retained metadata and cached provider responses.
No raw response, player, league, account, credential, or private path is
published. No new provider request or league mutation was made.

## What had worked

The repository README records a successful 2026 live Draft. One retained
September 2026 league board is marked draft-ready, with all its saved checks
passing. Its metadata identifies the grouped-ranking workflow, rather than the
direct API-board importer changed in PRs #43–#48. The grouped-ranking builder
itself was unchanged by MA-002; its league-board adapter gained a membership
check, and all four retained normalized Draft snapshots inspected here pass
that check. The direct-import probes do not establish that the earlier grouped
Draft workflow was inadequate.

## Confirmed changes to working paths

MA-002 added a Draft-room position-limit gate to the recommendation command
and live watcher. The two redacted reference rule maps contain, respectively,
an absent enforcement field and enabled enforcement without mapped position
maxima. Both now stop before calculating a room recommendation. Before MA-002,
the same path continued with the app's own draft preferences. Those preferences
are not proof of Sleeper legality; the previous behavior was usable advice
without a verified legality claim. This slice restores read-only suggestions
for an absent or explicitly enabled setting, adds a prominent position-limit
warning and `LIMITED` status, and recalculates a cached suggestion when that
setting changes. Explicitly malformed settings still stop the workflow.

MA-002 also replaced the in-season FantasyPros scoring path used to prepare
Trade and Waiver values. In 34 retained weekly projection payloads containing
15,061 player rows, the old path accepted 12,861 nonempty skill-player rows
under each reference scoring map; the new path marks **zero** rows complete.
The old path treated absent fields as zero and did not establish exact league
scoring. The new path correctly exposes missing fields, but its all-or-nothing
gate removes the projection distribution used for subsequent value boards.
This is a material availability change, not a harmless metadata warning.
The MA-001 semantic fixtures inject already-scored synthetic projections, so
their passing results do not exercise this provider-preparation change.

One of the new rule issues was mistaken: [Sleeper documents ordinary fumble
recovery scoring](https://support.sleeper.com/en/articles/3998131-what-scoring-options-are-available)
under **Team Defense**, separately from special-teams player
and defense categories. Treating that rule as potentially applicable to every
position made every forecast incomplete even with every applicable statistic
present. The rule's position is corrected to DST in this slice, so a missing
team-defense recovery no longer erases an unrelated quarterback's historical
Waiver points. The saved
FantasyPros payloads still omit several active scoring fields, so this
correction alone does not make those forecasts complete.

The retained grouped Draft board and its source metadata remain separate from
the direct API-board route. Recent `premium`/`limited` flags seen in that direct
route cannot be used to invalidate the grouped workflow. No ranking weights,
expert selections or grouped-board scoring were changed here.

## Boundaries for repair

Earlier successful use is evidence of utility, not proof that absent forecast
fields were zero or that every pick satisfied Sleeper's position limits. Any
restored analysis must state when it is an estimate based on available stats;
it must not label those points or a Draft pick's legality verified. The direct
API-board route remains distinct from the grouped Draft workflow. The meaning
of its contradictory `tier=premium` and `public_api_limited=true` fields has
not been established, so no account-access conclusion follows from the probes.

The review does not establish current live Trade/Waiver outcomes or renewed
provider completeness. Those require a separately scoped, read-only check with
the same workflow inputs after the affected behavior is repaired.

## Validation

The full local suite passes (916 tests), including the Draft room, provider
scoring, Waiver historical scoring, and reference baseline cases. Ruff, Python
compilation, context routing, and the tracked-tree privacy gate pass. This is
synthetic and retained-evidence validation; it is not a live provider run.

## Conditional in-season repair after PR #49

The 34 retained weekly responses contain 12,861 QB/RB/WR/TE rows. For both
reference scoring maps, zero rows prove exact scoring coverage, but all 12,861
have the observed position-core statistics needed for the older calculation.
The repaired path uses each league's actual scoring multipliers on observed
statistics and marks the result as an **estimate** when other active scoring
fields are missing. It does not assert that those missing fields equal zero.
An initial comparison found 8,356 point differences because the strict scorer
omitted the provider's `fumbles` field. That omission was incorrect for weekly
FantasyPros projections: its [projection table](https://www.fantasypros.com/nfl/projections/qb.php/?loggedin=&week=draft)
labels the projected category FL, meaning fumbles lost, and the
[published API example](https://api.fantasypros.com/v2/docs) reconciles to
its stated 293.7 standard points only when `fumbles: 2.85` receives the
lost-fumble deduction. The weekly scoring contract now maps this provider
field to `fum_lost`; Draft's separate source contract is unchanged. Both
reference maps then show zero old/new point differences on the 12,861
retained skill-player rows. They remain estimates because other active
scoring fields are absent.
Missing core statistics, invalid values, unknown rules and incomplete source
scope still make a row unavailable.

Estimated rows can populate Trade/Waiver value curves and weekly comparisons.
When a position's curve includes estimates, all values derived from that curve
carry the warning, even for a player whose own forecast is exact. The missing
fields remain in player warnings; the value-board report is
`PARTIAL`. An affected Trade verdict is `CONDITIONAL`. Waiver search may show
and rank an estimated candidate, but a favorable estimate yields `WATCH`
instead of an add/claim instruction. This restores analysis availability
without claiming that any retained forecast or current live run is exact.
The repaired slice passes 923 local tests, including provider preparation,
value curves, Trade evaluation, and Waiver evaluation/search regressions.
