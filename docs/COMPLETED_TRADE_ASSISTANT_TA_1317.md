# TA-1317 — Staged Trade search and consistent final offer checks

Implemented November 1, 2026 following the user's request for roughly
30-second searches that reserve expensive analysis for promising candidates.

## Behavior

The v2 execution profile defaults to 30 seconds in either scope, with no
required objective. Price-indexed construction still covers all nine shapes.
Current-chart fairness and impossible equal-count ownership-value losses are
screened first. A deterministic pool mixes promising shapes and opponents,
then checks joint weekly roster use with the same bye replacement floor.
Only the bounded final shortlist receives full add/drop, depth, risk,
consolidation, roster coverage and incoming-use checks. Repairs follow the
primary shortlist and screen price mismatches before exact evaluation.

Automatic secondary alternatives are cheaply ranked without scenarios/depth;
four final move sets receive the existing full gates. Explicit complete
replacement overrides skip the automatic search. Every bounded exclusion is
disclosed; unexamined alternatives may be better. Existing v1 profiles and raw
historical evidence remain supported. Only the requested league's ignored
execution configuration was migrated; expert weights and football thresholds
were not changed or transferred between leagues.

The finder, entered evaluator and comparison now share one final offer
assessment. Intrinsic verdicts remain separate. Fresh cached or authorized
imported chart evidence identifies provider, date, format, raw prices, premium
and limitations. Missing price/policy evidence cannot approve an offer. The
55-for-28 synthetic overpay is explicitly rejected regardless of intrinsic
approval. No unpublished FantasyPros chart endpoint or formula was invented.

JSON/CSV record screened, checked and shortlisted counts by opponent/shape,
deferred work and stage timing. `SHORTLIST_LIMIT` does not imply exhaustive
search. Entered/comparison replay retains the chart and finder policy; unavailable
assessments remain unavailable. Finder text uses ASCII arrows to avoid the
previous redirected Windows report encoding failure.

## Saved-input evidence

All league evidence stayed in ignored local artifacts. Replays were offline,
non-current and non-actionable, with no new provider calls or Sleeper writes.

| Measure | Prior saved run | Staged replay |
| --- | ---: | ---: |
| Search seconds | 120.013 | 16.735 |
| Detailed evaluation seconds | 115.371 | 12.320 |
| Completed exact packages | 21 | 12 |
| Supported negotiation candidates | 1 | 4 |
| Strict recommended offers | 0 | 0 |

The staged replay spent 1.809 seconds in setup, 1.083 in construction and 1.521
in screening. It recorded 9,217 screen exclusions, 96 joint roster checks,
12 shortlisted packages and 2,605 constructed but unevaluated packages.
These are one-case measurements, not a general quality or acceptance claim.
Provider preparation and restoration are separate from the search budget.

A search-only cProfile completed at its 30.024-second deadline under profiling
overhead, with eight completed evaluations and the unfinished ninth omitted.
Secondary move analysis remains the largest remaining cost. The benchmark
supports `--profile PATH` and `--legacy` for reproducible further investigation.

## Validation

All 1,106 unit tests pass. New cases cover global consolidation ordering,
price screening before expensive calls, shortlist accounting, unfinished
deadline exclusion, overpay rejection, missing-chart behavior and identical
entered/finder final checks. Existing exhaustive v1 scheduling, roster,
consolidation and policy tests remain intact. Reviewed command/schema baselines
changed only for the new Trade flags and optional offer assessment.

An additional provider-free priced-offer manifest replay reproduces its final
assessment. Ruff, compilation, context/privacy gates, distribution inspection
and isolated wheel installation pass. The wheel matches every production source
file byte for byte and is installed in the existing local command environment;
installed help and v2 defaults were checked. Delivery is through a separate PR
without merging.
