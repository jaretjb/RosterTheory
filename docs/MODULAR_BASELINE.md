# MA-001: reference and migration baseline

Status: implementation-complete; local gates passed, awaiting PR review/merge.
Tracking: [issue #29](https://github.com/jaretjb/RosterTheory/issues/29).
Planning [PR #27](https://github.com/jaretjb/RosterTheory/pull/27) is merged.

This is a characterization of current behavior, not a claim that every result is
correct or that another league is ready. No production code, user policy, player
ranking or recommendation algorithm changes in this milestone. MA-002 remains
inactive. Requirements are in [the approved scope](MODULAR_REQUIREMENTS.md).

## 1. Source and reference profiles

Baseline main: `bb34bac81ef580167fecc02e06f91655df4459f0`. Before additions,
803 tests passed in 67.976 seconds. Local tools: Python 3.13.4, pip 26.2.1,
Ruff 0.16.7, roster-theory 0.1.0, no runtime third-party dependencies.
OS/architecture are recorded in the performance artifact; processor identifier
is AMD64 Family 25 Model 33 Stepping 2, AuthenticAMD. Exact CPU model was
unavailable through the local hardware query. Timings are same-machine evidence,
not portable CI assertions.

Six read-only Sleeper GETs captured league settings, draft settings and draft
traded-pick lists for the two configured profiles on September 26, 2026 at
06:11 UTC (September 25 locally). No FantasyPros request or Sleeper mutation
occurred. Raw responses stay in ignored `data/cache/ma001/rules.json`.
[Public rules](../tests/fixtures/modular/reference_rules.json) preserve numeric
rules, scoring maps and capture times, with identities removed. Omitted
operational counters and draft scheduling keys are listed in that artifact.
Draft scheduling controls are outside the roster/order contract; original
values remain local. No real player, roster, manager or league identity is a
test fixture.

| Observed rule | reference_a | reference_b |
| --- | --- | --- |
| Teams | 10 | 12 |
| Fixed starters | QB, 2 RB, 2 WR, TE, K, DST | Same |
| Flex | 1 RB/WR | 2 RB/WR/TE |
| Active bench | 6 | 5 |
| Reserve places | 0 | 1; Out, Doubtful and Suspended flags enabled |
| Receptions | 0.5 | 0.5 |
| Passing interception | -2 | -1 |
| Kicking 40-49 yards | 3 | 4 |
| Longer kicks | 50+: 5 | 50-59: 5; 60+: 6 |
| Draft | Snake, 15 rounds, 60-second clock, no reversal | Same |
| Observed traded picks | 0 | 0 (pick-trading setting enabled) |
| Draft enforce-position-limits field | Absent | 1 |
| Waivers | type 1, budget 100, minimum bid 0, clear days 2, day 2 | Same |
| Daily waivers / bench lock / taxi slots | 0 / 0 / 0 | Same |
| Playoffs | 6 teams, start week 15, round/type/seed flags 0 | Same |
| Trade review / deadline setting | 2 days / 99 | 2 days / 11 |

The complete maps, not this abbreviated table, define the captured profiles.
Both league-type fields are 0 and best-ball flags are 0. Dormant `max_keepers=1`
and league `draft_rounds=3` do not override the observed redraft's 15-round draft.
Future admission must resolve absent fields and position-limit semantics rather
than guessing from provider names. Rules are **observed**, while universal
mechanical support and fresh provider statistics remain **unverified**.

Every nonzero scoring category is inventoried by the existing Trade classifier
and shared scorer in [defect observations](../tests/fixtures/modular/defect_observations.json).
Both maps include `fum_rec`/`fum_rec_td`, currently projection-limited in Trade.
Other specialist/defense categories are explicitly out of scope there. Raw-stat
provider coverage has not been refreshed or established by synthetic estimates.
MA-002 must assess these categories per operation before declaring support.

## 2. Reproducible fixtures and compatibility

[Fixture factory](../tests/ma001_fixtures.py) creates all 10 or 12 rosters, each
with 15 active places, plus the applicable reserve, and six free agents across
QB/RB/WR/TE/K/DST. There are 156/187 players and three synthetic projected weeks.
Players, ranks, forecasts, owners and IDs are invented. Independent synthetic
Waiver policies remain separate; no current league policy is loaded. Shared raw
stat lines have independently hand-scored expectations (17 versus 18 points for
the same QB line). This proves scoring isolation, not whole-map stat coverage.

Trade retains the existing skill-player evaluation scope. Full team membership
still includes specialists and reserve; the evaluated player directory is
QB/RB/WR/TE. Its completeness flag means completeness within that existing scope.
Do not interpret Trade's totals as a fully scored K/DST lineup or as validation
of specialist transactions. Waiver evaluates the existing specialist paths.

The [parser inventory](../tests/fixtures/modular/compatibility.json) pins all 63
parser paths, including root/groups, options, positionals, defaults, choices,
required flags and argument counts. The
[semantic inventory](../tests/fixtures/modular/semantics.json) pins complete
canonical result hashes, serialized byte sizes, record field lists, decisions,
warnings and search coverage for both profiles. Hashes cover the full results,
including explanations and limitations; they are not winner-only comparisons.
No volatile decision fields are stripped. Replay's source-build and outer
manifest hashes are validated by the real reader but intentionally not pinned
across source refactors; the replay, policy and scoring hashes remain pinned.

| Compatibility surface | Evidence and reader/guard |
| --- | --- |
| CLI discovery, flags, defaults | Parser snapshot; `test_cli_discovery`, `test_modular_baseline` |
| JSON stdout, typed failures, exit codes 0/1/2/130 | `test_cli_output_contract`; existing [contract](CLI_OUTPUT_CONTRACT.md) |
| Preparation, raw-cache reuse, profile isolation, dry-run/offline behavior | `test_runtime_input_contract`, `test_run_contract`; cold/serialized-warm bundle equality |
| Draft recommendation and seeded comparison | Both full profiles in semantic inventory; two 15-round trials, slot 1 |
| Draft watch edits/undos/duplicates | Both profiles in `test_modular_baseline`; full mock and missed-turn tests in `test_mock_watcher` |
| Trade diagnose, target discovery, entered and unequal packages, broad search | Both full profiles in semantic inventory; existing exact/target workflow tests cover saved cards and replay |
| Waiver full candidate search and reasons | Both full profiles; six candidates, full active rosters, explicit drop/news evidence |
| Named evaluation, open slots, K/DST and conditional claims | Both profiles' no-drop specialist tests; `test_waiver_joint_plans` independently covers same-drop/open-slot conflicts, pair equivalence and cumulative impact |
| Artifact schema, manifest, source hash and replay rejection | Field inventory; real `restore_record` and manifest reader; tampering/build checks in `test_run_contract`, `test_trade_target_workflow` |
| Sparse roster projection | Both profiles explicitly reject a missing starting QB rather than silently dropping it |

Existing integration tests remain the authority for report dictionaries and
legacy readers not exercised by the new full-profile workload. This is a
compatibility inventory, not a newly published JSON Schema specification.
All-slot/12-layout/ancillary pairwise validation and comprehensive future format
admission belong to MA-002 through MA-005; they are not claimed here.

## 3. Known behavior requiring separate fixes

Run `python scripts/ma001_defects.py` offline to reproduce the observations.
These are diagnostic records, not passing assertions that defects should persist.
Future fixes require independent correct-outcome tests and reviewed baseline
differences; do not regenerate golden files to conceal a changed decision.

| Reproduction and correct expectation | Follow-up |
| --- | --- |
| 250 passing yards with TD absent currently yields 10 points and complete=true; unknown TD must differ from explicit zero. Adapter also loses unsupported bonus evidence. | [#30 / MA-002 scoring](https://github.com/jaretjb/RosterTheory/issues/30) |
| Taxi player survives in player IDs but taxi membership disappears; preserve membership so unsupported formats can be rejected before evaluation. | [#31 / MA-002 roster contracts](https://github.com/jaretjb/RosterTheory/issues/31) |
| Two readers each reserve 499/500; both succeed and the persisted count is 499. Atomic replacement must be combined with process-safe reservation/pacing. | [#32 / MA-003 infrastructure](https://github.com/jaretjb/RosterTheory/issues/32) |
| Third QB is blocked by fixed Draft cap; default bye schedule is 2026. Separate policy preferences from legality and require season evidence. | [#33 / MA-004 Draft contracts](https://github.com/jaretjb/RosterTheory/issues/33) |

The budget probe uses a deterministic lost-update interleaving, with no paid
calls. The future fix must additionally prove safety with independent processes.
None of these issue links authorizes implementation.

## 4. Performance scope and reproduction

Use the repository virtual environment with `PYTHONPATH=src;.` on Windows (or
`src:.` on POSIX). From the repository root:

```text
python -m unittest tests.test_modular_baseline
python scripts/ma001_baseline.py --benchmark --repeat 5 --output baseline-local.json
python scripts/ma001_baseline.py --search-metrics --output search-metrics-local.json
python scripts/ma001_defects.py
```

`--capture` deliberately replaces the reviewed compatibility/semantic artifacts;
use only for an explained baseline change, not to make a failing test pass.
Network connection attempts fail immediately inside all new workloads.

Frozen settings: both full roster sizes; 300-player Draft board; seed 2026;
Draft slot 1, 15 rounds, two scenario-safe trials with K/DST, one availability
rate 0.1/two samples, bench weight 0.2 and rank weight 0.0. Trade covers three
weeks, exact 1-for-1/2-for-1 packages and every opponent, with small pool 2,
one exact package per opponent and no large pool. It is explicitly bounded,
not exhaustive. Waiver covers one week and all six available candidates with
pruning disabled and no exact budget; it includes the existing conditional
branch construction. Wider horizons and production simulation trial counts
are not represented by these small reproducible workloads.

Cold preparation means constructing/normalizing synthetic records; warm means
deserializing the same bundle, with identical semantic hash. Neither includes
network latency or provider disk-cache admission; existing runtime-input tests
cover those behaviors. The artifact records serialized evidence size and search
counts. [Search metrics](../tests/fixtures/modular/search_metrics.json) add a
separate diagnostic run's stage times and exact/contingency cache counts; they
do not separately measure every internal cache allocation.
Sparse-input rejection is its own measured workload. Replay uses a temporary
manifest and enforces same-build validation without network access.

The [performance artifact](../tests/fixtures/modular/performance.json) records
five timed repetitions after one excluded warm-up, each checked for identical
semantic evidence. Python allocation peak is measured in one separate traced
run to avoid contaminating runtime with tracing overhead; it is not OS resident
memory. Recheck peak measurements before treating a regression as conclusive.
Future reviews use the proposed 20% runtime / 25% allocation gates on this
machine and frozen scope. No timings are asserted in CI.

| Workload | A median seconds | B median seconds | A/B peak Python MiB |
| --- | ---: | ---: | ---: |
| Cold preparation | 0.0066 | 0.0069 | 0.23 / 0.25 |
| Serialized warm preparation | 0.0336 | 0.0396 | 0.23 / 0.24 |
| Draft turn | 0.1097 | 0.1116 | 2.90 / 2.90 |
| Draft two-trial comparison | 0.4154 | 0.4679 | 1.28 / 1.13 |
| Trade diagnosis | 0.0061 | 0.0083 | 0.10 / 0.09 |
| Trade entered package | 0.1293 | 0.3266 | 0.66 / 0.76 |
| Trade unequal package | 0.4526 | 1.0747 | 1.65 / 2.11 |
| Trade targets | 0.1697 | 0.2353 | 1.31 / 1.71 |
| Trade bounded all-opponent search | 1.2804 | 3.2658 | 4.65 / 6.79 |
| Waiver full six-candidate search | 4.9417 | 20.9743 | 10.13 / 51.87 |
| Offline replay | 0.0743 | 0.0847 | 1.30 / 1.54 |
| Sparse-input rejection | 0.0075 | 0.0083 | 0.24 / 0.27 |

All five timed repetitions reproduced each workload's semantic evidence. The
larger profile's Waiver cost is material even with only six candidates and one
week; do not extrapolate this to a full NFL pool or long horizon. Candidate/branch
coverage must remain visible in any later optimization. Typed deserialization
also costs more than constructing this small synthetic bundle; “warm” does not
promise a speedup for this isolated workload.

Proposed Draft acceptance budget before MA-005: at most **2 seconds** per offline
recommendation after inputs are ready, tested at early/middle/late states and all
supported seats. The measured initial turns are about 0.11 seconds, and the
observed clock is 60 seconds; two seconds preserves substantial decision time
without treating network refresh or multi-trial simulation as part of a pick.
This is a future acceptance target, not proof for every state or hardware type.

## 5. Handoff gates and next slice

Final local validation: **811 tests passed in 103.054 seconds**, configured Ruff
passed, all 18 context-routing tests passed, and both tracked-tree/exact-index
privacy gates and diff checks passed. All 24 measured workloads and four search
diagnostic results match the semantic inventory. No production source changed.
Required remote CI checks are the remaining merge gate; their exact-head results
are recorded on the PR linked to issue #29.
Rollback is an additive test/documentation revert; no user data migration exists.
After review, the next small slice should be MA-002's explicit league-rule and
scoring-coverage contract, informed by #30 and #31. Do not begin bulk file moves
or activate every follow-up at once. Provider schema evidence and any genuinely
non-obvious support decision must be resolved at that gate.
