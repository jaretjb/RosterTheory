# Completed milestone — Trade Assistant Phase 7 initial-testing correction

Completed: September 5, 2026 (America/Los_Angeles)

## Trigger

FantasyPros comparison found that the three initial targets changed overall
team strength by -6.0%, +0.6%, and -1.3%. Evidence review also found that the
partner immediately dropped Michael Pittman in the second and third packages.

## Correction

- Automatic search rejects a package when either team's modeled required drop
  is an asset that team just received. Manual evaluation remains unchanged so
  users can still inspect any entered package.
- Automatic `TARGET` now requires positive exact user-lineup impact and
  nonnegative selected-expert, market, and raw-projection ownership deltas.
- `phase7-search-cross-model-v2` versions the zero target floors, the existing
  partner-lineup credibility limit, and received-asset-drop rule.
- Search evidence and CSV expose raw-projection delta and distinct rejection
  reasons, including combined market/raw failure.

## Validation

- Regression fixtures reproduce and reject received-then-dropped packages.
- A controlled trade with positive lineup and selected-expert value but
  negative market value is no longer a target.
- The full suite passes 279 tests.
- The corrected live League Alpha default completed in 120.40 seconds and returned
  zero targets. It explicitly rejected two received-then-dropped finalists and
  the mixed-value candidate rather than preserving the earlier recommendations.
- Sleeper remained read-only; no proposal or roster transaction was submitted.

Initial testing should continue with zero-result runs treated as valid. Phase 8
remains inactive pending separate approval.
