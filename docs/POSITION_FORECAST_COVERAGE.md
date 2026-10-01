# Position-aware forecast coverage

MA-002u implements the user's September 30, 2026 clarification for Draft,
Trade and Waiver. A position's normal forecast does not need every conceivable
football event. Requiring QB receiving or WR passing statistics caused usable
forecasts to disappear from all three assistants. Merely allowing estimates in
Trade Finder would leave the same flawed requirements elsewhere.

## Permanent rule

`core/forecast_scoring.py` owns `position-forecast-v1`. Required fields are
determined by a fixed position contract, **not** inferred from whichever fields
an individual row happens to omit. Only active league scoring rules require
observations. Disabled rules require none.

| Position | Required forecast statistics when scored by the league |
| --- | --- |
| QB | Passing yards, touchdowns, interceptions; rushing yards and touchdowns; lost fumbles |
| RB | Rushing yards and touchdowns; receptions, receiving yards and touchdowns; lost fumbles |
| WR / TE | Receptions, receiving yards and touchdowns; lost fumbles |
| K | Applicable kicking categories, including the league's exact distance buckets |
| DST | Applicable team-defense categories, including the league's exact points-allowed buckets |

Passing is optional for non-QBs. Receiving is optional for QBs and kickers.
Rushing is optional for WRs, TEs and kickers. Individual two-point conversions,
fumble-recovery touchdowns and special-teams events are optional forecast
fields. Kicker fumbles are also optional. These omissions do not downgrade a
projection to an estimate or block a recommendation.

**Every supplied applicable statistic still counts under actual league scoring.**
A supplied WR rushing or passing forecast, QB reception, or two-point forecast
is included. Invalid or conflicting supplied values still fail. Missing core
touchdowns, receiving yards, rushing yards or other required fields remain
missing. Position reception premiums require receptions for that position.
Unknown positions/rules, source mismatch, an absent player, and specialist
bucket ambiguity do not acquire an exemption.

Optional omission is a forecast assumption, not a claim that the provider
observed zero or that an unusual play is impossible. `ScoredEvidence` records
`optional_missing_settings` and `coverage_policy`, preserving the original
observations and numeric total. No synthetic stat rows or structural zeros are
created. Historical actual-stat scoring and the generic diagnostic scorer stay
strict: their purpose is to account for events that happened.

## Integration and evidence

- The weekly FantasyPros adapter serves Trade and Waiver. Its source stamps
  name optional omissions by position and the coverage version.
- Draft API and manual CSV imports use the same forecast scorer and retain
  omission metadata. Rankings remain provider-authored and horizon-specific.
- Waiver emerging-player scenarios use the same forecast requirements.
- Trade discovery, package search and entered evaluation agree on admitting
  usable estimates. Actual remaining estimate limitations keep their existing
  conditional labels; this does not turn missing core evidence into a forecast.

The FantasyPros weekly and season scoring contracts advance to v3; manual
preseason scoring advances to v2. Raw caches are reusable and are rescored.
New derived evidence carries the new contract/hash; saved runs retain their
original build checks. Added scored-evidence fields default to strict legacy
behavior when absent. No saved incomplete result is silently promoted.

## Verification

`tests/test_position_forecast_coverage.py` uses independent arithmetic for both
full synthetic reference rule maps. It checks position requirements, supplied
unusual events, invalid/core-missing failures, K/DST applicability, strict
historical scoring, serialization, Draft API/CSV parity, real adapter inputs
through Waiver search, and Trade target/package admission including estimates.
Existing tests that required missing RB passing or rare events to block have
been corrected to assert the requested behavior. Provider evidence is checked
locally in ignored exports; licensed rows and league identities stay untracked.

Validation: all 971 unit tests pass, including the existing semantic baselines;
Ruff, package build, distribution content checks and clean wheel installation
pass. Cached provider verification reprocessed 5,044 skill-player forecasts
over 14 weeks: all pass position requirements with their supplied points
unchanged. Specialist rows still require their own scoring inputs. A separate
read-only reference-league Trade rerun valued all 130 rostered skill players,
excluded no rosters, found 24 targets, evaluated 81 packages, and returned one
acceptable provisional offer. Its package had no relevant projection gaps.
The global manifest still reports unrelated outside-evaluation player gaps,
two missing chart prices, and bounded search; this is not full support promotion.
