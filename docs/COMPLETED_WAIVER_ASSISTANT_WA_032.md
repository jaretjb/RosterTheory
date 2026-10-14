# WA-032 - Exact weekly roster plans

Implemented October 13, 2026 following the user's reviewed weekly-roster
requirements. The normal Waiver search now delivers a concrete ordered plan
instead of leading with a season ranking-score winner.

## Resulting behavior

- Discover legal IR preparations and evaluate resulting no-drop acquisitions.
  Keep platform statuses unchanged and show eventual reactivation cost.
- Compare actual owned-player coverage and offensive points separately from
  replacement-floor comparisons. Preserve fixed-position coverage and known
  outgoing QB bye needs without promising a future waiver replacement.
- Evaluate bounded combinations of skill moves. Each extra move needs coverage
  repair or material lineup benefit. Within the weekly forecast margin prefer
  fewer acquisitions, durable expert ROS value and useful depth. Selected and
  consensus ownership losses have separate limits; units remain distinct.
- Re-evaluate every successful prefix, recompute joint depth/risk, then append
  independent same-position specialist swaps through their existing policies.
  Failed-claim repair branches preserve successful prerequisites and exclude
  the failed target. Screened alternatives are labeled as comparisons requiring
  changed-roster verification, not executable substitute promises.
- Remove the marginal current-starter QB holding exemption. A third QB's
  insurance compares against already-owned backups. Preserve multi-QB formats.
  Retention distinguishes the exact replacement cutoff from players above it.
- Admit only scoped, sourced, expiring current-week availability scenarios and
  retain the platform-status fallback. Show expert weights and update dates.
- Preserve read-only providers, private league scoring/decision settings,
  source/freshness gates, caching, budgets, and Draft/Trade policy.

## Interfaces and evidence

`waiver search` defaults to the weekly plan. `--objective ros` retains the
season-oriented single-pair view. Optional `--plan-policy` and `--availability`
inputs are documented in README and the requirements. Planning controls are
league-bound and separately hashed; the defaults are controlled settings, not
outcome-calibrated accuracy or win probabilities.

Search evidence schema 13 retains the primary `weekly_plan`, bounded coverage,
omissions, alternatives and failure branches. Legacy single-pair rankings remain
in `exact_evaluations` and `claim_plan`. Manifests bind objective, planning settings
and availability assumptions; unchanged-build offline replay verifies the exact
result hash. Re-evaluation of earlier private data under the new rules is
explicitly offline/non-current and never claims to reproduce the old build.

## Validation

All 1,087 unit tests pass. Eighteen new planning regressions cover IR openings
and reactivation, two-move coverage, fixed/only-TE safety, outgoing QB coverage,
close calls, marginal third QBs, superflex, missing forecasts/news, policy scope,
expired availability, deterministic bounds, failed-claim prerequisites and
incumbent specialist swaps when the original roster has an open active spot.
Independent synthetic reference profiles retain their other assistant semantic
baselines; only Waiver semantics and the three new search options were updated.

The two user-requested private examples were audited independently with their
own saved scoring, policy and immutable inputs. The revised plans reproduce the
agreed skill acquisitions and drops in one case and the IR/no-drop acquisition
plus independent specialist swaps in the other. An initial unnecessary extra
swap was caught and removed by the general close-call/fewer-moves rule and
consensus-loss guard. Private reports and numeric evidence remain ignored.

Ruff, conditional context routing, repository privacy, distribution contents,
and a clean wheel installation pass. The verified local wheel is installed in
the user's managed command environment, and its new search options are verified.
No Sleeper roster, IR placement, claim, bid, trade or lineup was submitted.

Fresh read-only input preparation and publication audits passed separately in
both leagues, including unchanged-roster revalidation. The first preparation
used one new FantasyPros request; the final audits reused cached premium
evidence. Current ownership was respected, including an already-filled IR
slot, and a newly supported specialist change appeared in the other league.
The fresh plans retained the agreed skill moves and specialist comparisons.
Unchanged-build, GET-free offline replay independently verified each fresh
result's exact evidence hash. All private names, scores, settings and replay
artifacts remain ignored.

The implementation is handed off in [PR #85](https://github.com/jaretjb/RosterTheory/pull/85)
on `codex/waiver-weekly-roster-plans`, stacked
on the unmerged WA-031 dependency; neither branch is merged by this task.
Bounded combinations do not establish a global optimum;
forecast and historical-expert coverage limitations remain visible in reports.
