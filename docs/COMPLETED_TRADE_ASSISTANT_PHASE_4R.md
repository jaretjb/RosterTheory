# Completed Trade Assistant milestone: ranking-horizon refinement

Completed September 5, 2026 (America/Los_Angeles). This record closes Phase
4R, tasks TA-412 through TA-416. TA-411's prerequisite research is recorded in
`docs/TRADE_RANK_HORIZON_RESEARCH_2026.md`.

Subsequent policy note: the user later shortened the Draft-anchor window to
Week 1 and directed a joint ROS transition beginning Week 2. TA-417 supersedes
the Week 2/Week 3 timing recorded below while preserving the study results and
all separation/freshness controls.

## Football outcome

Trade ownership value no longer follows a one-week rank or treats a bye as a
long-term downgrade. Through Week 2, both selected and market boards use the
final Draft ranking anchor while current-week rankings and league-scored
projections remain a separate `CURRENT_SIGNAL`. Entering Week 3, both ownership
boards switch together only when complete, fresh ROS evidence passes. A failed
Week 3 gate keeps the labeled Draft anchor for review; after Week 3 the tool
stops unless an extension is explicitly approved.

`BLENDED` remains disabled. The historical proxy study did not establish an
out-of-sample advantage over weekly-only ECR, and a final Draft rank is not
historical point-in-time ROS evidence.

## Delivered contracts

- ROS freshness is evaluated per expert and position from the ballot revision,
  never the response capture. The hard maximum age is 14 days. The August 8 TE
  fixture is excluded while the same expert's fresh RB ballot remains usable.
- Newer injury, suspension, transaction, and depth-chart news invalidates only
  the affected player row and leaves an auditable conflict.
- `LONG_TERM` and `CURRENT_SIGNAL` preserve separate ranks, values, source
  times, warnings, and provenance. Bye status changes current-week use to zero
  without changing long-term value.
- The final selected and market Draft boards are ranking-only early-season
  inputs. ADP, survival, construction, simulation, and watcher policies do not
  enter Trade.
- The prospective snapshot writer rejects future-published evidence and
  produces stable, canonical hashes. The rolling-origin harness compares
  long-term-only, weekly-only, projection-only, and candidate blended controls.
- The historical collector is cache-aware, request-budgeted, paced, and stores
  licensed rows only in ignored cache paths. Its aggregate artifact reports
  point, standardized marginal lineup-value, ordering, sample-size, and
  uncertainty metrics.

## Historical Draft-proxy result

The full methodology and limitations are in
`docs/TRADE_DRAFT_PROXY_BACKTEST_2026.md`. The study used 2024 for selection and
2025 as the untouched holdout, with 7,616 forecast rows and 1,496 holdout
metrics across Weeks 1-17.

Across 3,791 holdout rows, bye-aware weekly-only ECR had point MAE 25.99 and
lineup-value MAE 17.09. The 2024-selected bye-aware blend was worse at 26.61 and
17.56; Draft-only was worse again at 31.38 and 20.19. Draft-only narrowly led
Week 1, but weekly-only led in Weeks 2 and 3. One training season, one holdout
season, date-only provider update precision, and a positional-replacement proxy
for lineup value prevent a stronger claim.

The paced first collection used 152 FantasyPros calls. A cache-only rerun used
zero paid calls and reproduced evidence hash
`e0bcd0de58a146f9acd3bad42ade5fbbe1b0f5ef01ec7036bb5e3ed582af4172`.

## Live read-only validation

The final Week 1 validation produced 216 complete actionable-player horizon
views under `EARLY_SEASON_DRAFT_ANCHOR`, with 18 fresh FantasyPros cache hits
and three paid refreshes. The prospective snapshot contains 864 unblended data
records and stable snapshot hash
`5259b80a229d64c60be3579760f8099a2ef280ba3e235feea18c96cb8dc8c3c7`.
The daily ledger records 258 of 500 requests used, leaving 242.

No package was evaluated, no opponent preference or recommendation was made,
and no Sleeper write occurred.

## Validation and gate

The required repository-root command passes 234 tests in 3.403 seconds:

```powershell
$env:PYTHONPATH = "src"
python -m unittest discover -s tests -v
```

Phase 4R's gate passes. Phase 5 is ready for a separately approved milestone;
it is not active and no entered-package evaluation has begun.
