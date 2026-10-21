# Waiver scoped completeness amendment

Authorized October 20, 2026 after the user reported recurring completeness
failures during a live waiver review. Scope: WA-032/WA-031 waiver evidence
admission and reporting; no scoring, numeric calibration or transaction changes.

## Root causes

- Both singleton policy and changed-roster planning vetoed a QB hold whenever
  any unowned directory quarterback lacked complete ownership and season-long
  forecasts. Directory-only backups therefore invalidated useful starters.
- Streaming candidates had to cover every horizon week before any week's
  forecast could contribute. Ownership ranks were unnecessarily required to
  establish a projected-points streaming baseline.
- Ranking preparation selected available experts at position level but did not
  retain eligible reserve contributor identities through the shared adapter.
  A missing player ballot could not use those next qualified contributors.
- Position-panel shortages could stop preparation before other usable panels
  reached per-player evaluation.

## Resulting behavior

Use available active QB forecasts independently each week. Retain omitted IDs,
show a concise warning, and preserve actual absence of a usable weekly pool.
Both policy paths and the final changed-roster validator use the same scoped
coverage rule. Known inactive/bye players are not available streaming choices.

Select the best qualified available contributors for each player, retaining
historical accuracy weights, freshness, horizon and source concentration.
Preserve the actual contributors in evidence. Keep market consensus separate;
do not invent ranks, recovery dates or observed zeros. Partial panels are
explicitly reviewed, and unsupported players remain unavailable. The shared
adapter's partial-panel option defaults off and is enabled only by Waiver.

## Verification

All 1,092 unit tests pass. Regressions cover unforecast directory QBs, per-week
forecast availability, ownership-rank-independent streaming, genuinely unknown
weekly pools, planner QB coverage repair, expert fallback, missing/low player
ballots, concentration and isolated unavailable position panels. Ruff and
repository privacy pass; wheel/source distribution privacy and isolated clean
installation pass.

A fresh league-local search completed with source and ownership revalidation.
The reported QB now passes `complete_required_evidence` despite hundreds of
directory omissions. Its remaining WATCH verdict reflects a negative Waiver
Value delta; the weekly planner separately rejects a consensus ROS ownership
loss. Those numeric policy thresholds were intentionally preserved. A saved
offline diagnostic independently reproduced that distinction. These checks
do not establish another league's calibration or guarantee claim success.

No Sleeper write, provider credential disclosure, or private input commit.
