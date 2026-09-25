# AC-001 — Weekly availability and projection provenance

September 25, 2026. Issue: https://github.com/jaretjb/RosterTheory/issues/7.
Pull request: https://github.com/jaretjb/RosterTheory/pull/15 (stacked on PR #6).
Implementation is tested on `codex/assistant-audit-data-integrity`, based on the
existing Waiver fixes in PR #6. Not a claim that the entire audit is resolved.

## Corrected behavior

- Current OUT/IR/PUP/SUSP and explicit inactive-directory status affect only the
  actual current week. Supplied future projections survive with an uncertainty
  warning. Unknown activity is not confirmed inactivity.
- Shared projection validation distinguishes complete forecasts, audited byes,
  current-week inactive zeroes, explicitly verified week-specific absences,
  incomplete/omitted rows, and counterfactual scenario zeroes. Current-week
  status cannot be extended by the former broad status switch.
- Missing/partial/nonfinite/invalid zero rows become MISSING with null points and
  retained source/coverage warnings. Valid actual zeroes and negative points are
  not confused with missing data. A known bye can establish zero without a
  provider row.
- Provider normalization no longer manufactures a complete future-zero series
  for a currently inactive player. It preserves supplied future rows, repairs
  supported current-week omissions only, reports missing future weeks, and
  retains nonrequired player omissions for audit instead of silently dropping them.
- Projection curves exclude incomplete/invalid player series, retain exclusion
  reasons, reject duplicate weeks and nonfinite totals, and do not pad rank slots
  with synthetic zeroes. Expert identity order is unchanged.
- Trade relevant omissions are now counted as missing evidence; explicit partial
  evaluations cannot claim complete coverage. Out-of-evaluation omissions remain
  disclosed without making the evaluated package incomplete.
- Waiver search, evaluation, and contingency preparation consume the same
  projection evidence contract. Counterfactual teammate absence is accepted only
  in a deliberately enabled scenario matrix, never as central factual evidence.

## Verification

- Before repair: the new 14-test regression module reproduced 20 failing subcases
  and one missing-context API error. Tests were added before production changes.
- Final expanded module: 20 new regression tests; existing fixtures were corrected
  where they previously encoded future inactive zeroes, nonzero bye zeroes, or
  treated a proven bye omission as an unknown non-bye projection.
- `PYTHONPATH=src python -m unittest discover -s tests`: **696 tests pass**, 32.276s.
- `python -m ruff check src tests`: passes.
- `git diff --check`: passes (Git notes the existing CRLF conversion configuration).
- Original offline audit probe now returns current/future injured-player points
  **0 / 10 / 10**, not **0 / 0 / 0**. Its source-omission probe now returns
  `complete=false`, `points=null`, `availability=MISSING`, with explicit provenance.
- No provider requests, Sleeper writes, live league claims, calibration changes,
  or private league evidence publication were needed.

## Remaining boundary

AC-002 through AC-008 remain open. In particular, candidate-scoped board/search
recovery, mandatory production Waiver safety gates, cross-position selection,
and consistent Trade verdicts are NOT fixed by AC-001. A genuinely insufficient
projection distribution still cannot supply authoritative rank slots; broader
partial-board continuation belongs to AC-002, not fabricated zero filling.
Old saved numeric board values should be rebuilt through the corrected pipeline;
this milestone does not retroactively rewrite archived reports.

Next authorized cleanup task to activate: AC-002 / issue #8.
