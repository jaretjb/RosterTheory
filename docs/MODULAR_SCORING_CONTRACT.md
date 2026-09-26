# MA-002a: explicit scoring evidence

Status: approved in PR #35 with all 20 CI checks passing. This is the first bounded MA-002 slice,
dependent on [MA-001 PR #34](https://github.com/jaretjb/RosterTheory/pull/34).
It prepares [issue #30](https://github.com/jaretjb/RosterTheory/issues/30); it
does not close that issue or complete the overall MA-002 milestone.
PR #35 merged into the former MA-001 base branch. MA-002b carries this approved
contract onto main and adds [provider integration](MODULAR_PROVIDER_SCORING.md).
The behavior and validation below describe the historical MA-002a slice.

## Scope and observable outcome

The new `core.scoring_contract` module separates **rule support** from **statistic
completeness**. It is additive: existing scoring, provider preparation, CLI
results and feature recommendations continue to use their current paths.
Known defects recorded by MA-001 remain reproducible until those paths migrate
in separately reviewed behavior-change PRs. No providers were contacted.

The module implements the shared contract in architecture section 3.1 and
requirements MR-01, MR-02, MR-04, MR-06, MR-09 and MR-10. It has no feature
policy, rankings, roster optimization, calibration or dependency on providers.
Roster membership (#31), provider coordination (#32) and Draft policy (#33)
remain later slices. No new runtime or development dependency is introduced.

Concrete example: with four points per passing touchdown and 0.04 per passing
yard, a row containing only 250 passing yards yields **10 diagnostic points**
and a missing-touchdown issue. `require_points()` raises `CoverageIncomplete`.
Supplying an observed touchdown count of zero makes 10 usable points available.
This prevents a consumer of the new contract from treating an omitted statistic
as a complete zero-valued contribution.

## Version 1 records and calculation

| Record/API | Contract |
| --- | --- |
| `ScoringScope` | League, season, operation, horizon and week/start week; no inferred current date |
| `LinearScoringRule` | Setting, canonical statistic, explicitly declared applicable positions and supporting evidence; `positions=None` means unverified applicability |
| `assess_scoring_rules` / `RuleAssessment` | Classifies every supplied setting before player scoring; versioned catalogue, separate scoring/scope hashes, active and disabled settings, issues and support state |
| `StatObservation` | Finite observed number, documented structural zero, or preserved invalid scalar; absence is not an observation |
| `observed_statistics` / `StatEvidence` | Canonical observations with source/schema, season, horizon, week and position; source evidence is reusable across leagues |
| `score_evidence` / `ScoredEvidence` | Diagnostic total, applied/inapplicable/structural-zero settings and all blocking issues; `require_points()` returns only a complete total |

`SUPPORTED` means this declared catalogue can calculate the active settings.
`LIMITED` means applicability remains unverified. `UNSUPPORTED` means an active
rule is undefined or a multiplier is invalid. None means a provider supplies
the required statistics, a snapshot is fresh, a league is fully supported or a
recommendation is ready. An all-zero map has no active scoring requirements.

Calculations are linear sums, rounded to three decimal places at the end, as in
the existing scorer. Negative values and fractional projected event counts are
valid finite numbers. A threshold bonus requires an explicit projected event
count, such as expected games exceeding a threshold; average yardage never
manufactures such an event. A rule catalogue is supplied explicitly and is
scoped/versioned by its owner. No production catalogue is installed in this PR.

Position names are canonical QB/RB/WR/TE/K/DST. Provider aliases such as DEF
must be normalized by an adapter. A known inapplicable rule does not require a
statistic; an unknown player position or unknown rule applicability cannot
silently make all missing fields irrelevant. Catalogue owners must account for
unusual but valid events, such as a non-QB passing, rather than assuming that
typical position usage proves an event is impossible.

## Missing, invalid and source evidence

- Canonical values must be finite numbers. Strings, booleans, nulls, NaN and
  infinity remain invalid observations; provider string parsing belongs at the
  adapter boundary. Invalid scalar representations remain JSON-serializable.
- A nonzero active rule with missing or invalid applicable evidence blocks usable
  points. Unsupported rules remain blocking even if similarly named raw fields
  exist. Zero multipliers are explicitly disabled, not mistaken for missing rules.
- A structural zero requires a nonempty source-schema rule citation and remains
  distinguishable from an observed zero. Conflicting observed/structural values
  are rejected. This PR approves **no real provider zero convention**.
- Source season, horizon and week must match the requested calculation. A mismatch
  preserves diagnostic evidence but blocks `require_points()`.
- Invalid multipliers and arithmetic overflow cannot produce a complete result or
  serialize nonfinite points. Invalid unused observations remain in source
  evidence; they do not block rules that do not consume them.

Adapters remain responsible for validating their source schema, applicability
and zero conventions. A caller-supplied citation is provenance, not external
verification. These are typed calculation records, not a signed artifact reader
or a substitute for the existing source-hash/revalidation checks.

## Reference inventory and unresolved evidence

[The explicit inventory](../tests/fixtures/modular/scoring_inventory.json) accounts
for all 35/41 nonzero settings and all disabled settings in the captured
reference A/B maps. It records each multiplier, candidate canonical statistic,
legacy alias candidates, missing-data behavior and outstanding evidence.
Regenerate it offline with `python scripts/ma002_scoring_inventory.py` using
`PYTHONPATH=src;.` on Windows (`src:.` on POSIX).

The legacy scorer recognizes arithmetic/aliases for many categories. That is
insufficient proof of the required provider fields, position applicability or
structural zeros. Those fields therefore remain explicitly unverified in this
inventory. Both full maps assess as unsupported against this deliberately
unverified inventory catalogue; this does **not** replace current feature
admission or invent a newly certified catalogue. Follow-up #30 must verify each
needed mapping before using the contract for real preparation.

Independent tests use a separate, explicitly synthetic arithmetic catalogue.
The same raw QB line yields 17 points under reference A's interception setting
and 18 under reference B's. Those tests cover a declared subset, not whole-map
provider support. K/DST and receiving totals have independent hand-calculated
examples, including negative and fractional values.

## Compatibility, validation and handoff

Existing `ScoringResult`, `Projection`, CLI output and saved artifact formats
are unchanged. New records have schema version 1 and reject unsupported versions.
They round-trip with the code-selected record restorer; no existing artifact is
silently converted into stronger completeness evidence. New code changes the
source-build hash, so old saved runs still require their exact original build.

Targeted tests cover independent totals; missing versus zero; unsupported and
position-specific rules; invalid/nonfinite inputs and overflow; source scope;
league/operation isolation; deterministic serialization and explicit schema
rejection. The complete suite must preserve all MA-001 semantic goldens and CLI
contracts. No baseline artifact is regenerated to accommodate this slice.

Validation: **828 tests passed in 100.840 seconds**, including 17 new contract
tests and unchanged MA-001 semantic goldens. Configured Ruff, all 18 context
checks and documentation-link checks passed. Tracked-tree and exact staged
privacy gates passed; required remote CI remains the merge gate.
No production calculation path invokes the new contract, and no performance
improvement is claimed. The integration PR must measure its actual preparation
cost. A pinned static type-check gate remains part of establishing the integrated
shared interfaces; this slice uses type hints and runtime shape/serialization
checks without claiming static type-check coverage.

Next bounded slice: verify the provider rule catalogue and propagate the new
coverage contract through scoring preparation and adapter results for #30,
with explicit before/after behavior tests. Decide the disposition of partial
historical production evidence per consuming operation. No recommendation
thresholds change implicitly. Rollback of MA-002a is an additive module/test/doc
revert; no user-data migration or cache rewrite is needed.
