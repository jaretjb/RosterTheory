# MA-002e Draft position-limit admission

September 26, 2026. Bounded #31 follow-up from merged PR #38, main
`9b8b14ac4ac7d1cef617a1196938330892e94ec1`. This does not complete MA-002 or #31.

## Finding and evidence boundary

Sleeper's [position-limit documentation](https://support.sleeper.com/en/articles/5379935-how-do-i-set-positional-limits)
distinguishes roster slots from positional maximums and describes a separate
draft-enforcement toggle. It says enforcement is enabled by default and excludes
IR/taxi players from positional counts. This resolves the purpose of the setting;
it does not establish the actual maximums for either reference league.

The [public draft API documentation](https://docs.sleeper.com/#get-a-specific-draft)
does not define positional-cap fields, unlimited sentinels or missing-field
semantics. The adapter recognizes only explicit integer binary values for
`enforce_position_limits`: 0 as disabled and 1 as enabled. This binding interprets
the observed field's name and binary convention alongside the documented toggle;
the public API page does not itself specify this field. Missing, null, malformed,
boolean and non-binary values remain UNKNOWN. The documented UI default is never
used to fill absent API evidence. Numeric cap aliases are not guessed.

| Observed evidence | Enforcement assessment | Maxima assessment | This scope admitted? |
| --- | --- | --- | --- |
| Explicit integer 0 | SUPPORTED: disabled | IRRELEVANT to draft picks | Yes |
| Explicit integer 1 | SUPPORTED: enabled | UNKNOWN: cap mapping unverified | No |
| Absent, null or malformed | UNKNOWN | UNKNOWN | No |

An irrelevant cap check when enforcement is disabled does not claim that the
league has no positional limits. `slots_qb`, bench capacity and the app's
`POSITION_CAPS` are not evidence of legal maximums. Supplying an arbitrary
`max_qb` or `position_limits` object cannot override the gate.

Reference A omits the enforcement field; Reference B contains integer 1. Neither
redacted reference inventory establishes verified positional caps. Both therefore
remain LIMITED for this narrow Draft check. These observations are independent
of their scoring limitations and cannot be transferred between leagues.

## Resulting behavior and boundaries

`core.capabilities` defines versioned, neutral rule assessments with explicit
feature, operation and scope. Individual rules are SUPPORTED, IRRELEVANT, UNKNOWN
or UNSUPPORTED; the aggregate is SUPPORTED, LIMITED or UNSUPPORTED. An empty
assessment cannot admit a scope. This is separate from data readiness, calibration
and the future support matrix. There is no universal feature-ready boolean.

The `recommend` command and `MockDraftWatcher.poll_once` check position-limit
evidence after fetching the room, before fetching picks or computing/reusing a
recommendation. Each poll reassesses the returned rules. A failed check clears
the cached recommendation and planned turn. Restoring valid source evidence
requires recomputation. Both entry points request the client's existing cache
bypass for room settings, as the watcher already does for picks; this adds no
request or provider. It does not claim a new end-to-end source freshness guarantee.

Unresolved rules raise a typed completeness error with the reason and source
evidence needed. The legacy `recommend` path also uses the existing taxi check.
Passing the position-limit check proves only that scope; other unsupported draft
modes and full league capability admission remain follow-ups.

Pure offline calculation/reconciliation functions, saved output schemas, CLI
parser contracts and acquisition preferences are unchanged. They are calculation
primitives, not supported-room admission APIs. The 2026 Draft closure and
experimental offline boundary remain closed. This PR authorizes no live use.

This is an intentional operational change: existing room-backed commands with
missing or enabled-but-unverified enforcement evidence now stop. Do not modify
league settings or edit saved source records to bypass it. Preserve the raw
evidence; obtain a verified provider cap mapping or controlled source observation
before enabling that case in a later reviewed slice. No old artifacts are
rewritten, and no golden files were regenerated.

## Offline inspection and validation

With the repository source on `PYTHONPATH`, run:

```powershell
$env:PYTHONPATH = 'src;.'
.venv/Scripts/python.exe scripts/ma002_draft_rules.py PATH_TO_RAW_DRAFT_JSON
```

The inspector reads one saved raw draft, makes no provider calls, and prints a
versioned JSON rule report. Exit 0 means only this scope passes; exit 2 means it
is unresolved. Neither code declares feature readiness. It leaves its input intact.

Two regressions reproduced the pre-fix behavior: the watcher proceeded with an
absent enforcement field, and `recommend` proceeded with enabled enforcement
without cap evidence. They failed because the expected completeness error was
not raised. They now prove rejection before picks, board loading and decision
work. Further tests cover enabled/disabled/malformed values; scoped aggregation;
independent references; unchanged allowed-command output; cache invalidation;
fresh-room request URLs; and saved inspection/record restoration.

All 888 tests pass in the final full run (109.566 seconds), including unchanged
parser and 24 complete-output MA-001 goldens and the cache-bypass addition.
Ruff, compilation, context routing and tracked/staged privacy checks pass.
Required PR CI and review remain the merge gate.
The synthetic watcher fixture now explicitly disables position-limit enforcement;
the actual reference inventories remain unchanged.

A local microbenchmark on Windows 11 AMD64 / Python 3.13.4 measured five batches
of 10,000 assessments after warm-up, plus a separate traced assessment:

| Case | Median per assessment | Peak traced Python bytes |
| --- | ---: | ---: |
| Reference A | 3.032 microseconds | 546 |
| Reference B | 5.209 microseconds | 539 |
| Explicit disabled enforcement, including admission | 5.867 microseconds | 683 |

Receipt: ignored `data/exports/ma002e-preflight-timing.json`. Reproduce with
`timeit.repeat` (repeat=5, number=10000) on `assess_draft_position_limits`, or
`require_draft_position_limits` for the disabled case, then a separate
`tracemalloc` run. This measures the added local check, not network latency or
whole-search performance. Existing calculation workloads are unchanged.

## Remaining work and rollback

Verify the provider mapping and actual positional maximums before implementing
their neutral counting/enforcement mechanics. Complete admission separately for
other Draft modes and Trade/Waiver operations; retain scoring work under #30.

Sleeper also documents that [temporary roster excess is permitted for drafting
and trading](https://support.sleeper.com/en/articles/3956140-can-a-team-go-over-the-roster-limit),
and its position-limit article distinguishes acquisition from subsequent lineup
eligibility. Review the current strict in-season capacity gates against those
operation-specific rules in a separate #31 slice; this Draft setting must not
become a universal trade/waiver veto.

Reverting this PR restores the former operational behavior and requires no file
conversion, but also removes the unresolved-rule protection. Preserve source
evidence and original-build replay when investigating older results.
