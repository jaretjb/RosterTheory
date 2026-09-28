# MA-004f: Draft legality and season evidence (#33)

This behavior PR uses invented players, synthetic rosters and synthetic schedule
inputs only. It makes no paid provider request and no Sleeper mutation.

## Named before-and-after cases

| Case | Before | After |
| --- | --- | --- |
| Third QB with one QB starter and enough bench space | `_can_draft` returned false at the app's two-QB cap | Slot capacity returns true. The selected Draft acquisition preference still disfavors QB3 while preferred options remain. If only QB3 is available, the ranked row and human report mark the preference override and warn that Sleeper position limits need checking. |
| Candidate or next-turn player cannot occupy any remaining slot | A fallback could rank any board player after preferred candidates were exhausted | Candidate and continuation checks use declared slot capacity. With no eligible board player, no pick is invented. |
| Current edited roster cannot fit declared slots | Advice could proceed from an impossible roster | Watcher returns no recommendation and a visible invalid-roster reason; edit/undo rebuilds from current picks. |
| Bye-aware Draft evaluation without matched source season | `deterministic_roster_strength` silently used a 2026 constant | A season-bound schedule is required. The simulation CLI validates the normalized schedule document for the configured season before loading a board. Missing, invalid and wrong-season artifacts give the schedule-refresh command. |

The same app preference counts remain in selected Draft strategies. They are
named `DRAFT_PREFERENCE_CAPS`; the prior `POSITION_CAPS` import remains an alias.
Sleeper's enabled position maxima still have no verified mapping, so the
existing `LIMITED` advisory remains. Slot fit alone is not a claim that an
unknown Sleeper maximum permits a pick. K/DST selection and ties remain in
their Draft policies. Trade and Waiver decisions are unchanged.

## Synthetic comparison

The MA-001 two-trial, fixed-seed Draft strategy workload now passes explicit
synthetic bye evidence. Its four fixture teams use the same bye assignments
that the old code used, allowing a semantic comparison without claiming the
fixture is a live schedule. Both complete output hashes are unchanged:

| Profile | Before and after semantic hash |
| --- | --- |
| `reference_a` | `6763472316a335b1af612d7e398b235956232a7484c7fdd9e` |
| `reference_b` | `cf0f1d3a5cdee398cc44a1692f781f105e6b434c52cc6cc60cde0d2d68d00a9a` |

Independent examples cover QB3, flex and bench assignment, full roster
capacity, every seat in 10- and 12-team snake drafts, edits/undos, invalid
current rosters, valid synthetic source admission and missing/wrong-season
source rejection. The all-seat tests retain starter completion and K/DST.

## Performance and verification

Same Windows 11 / Python 3.13.4 machine, five timed runs after warm-up, two
trials per profile, with a separate traced Python-allocation run:

| Profile | Before median | After median | Before peak bytes | After peak bytes |
| --- | ---: | ---: | ---: | ---: |
| `reference_a` | 0.411625 s | 0.390280 s | 1,341,877 | 1,554,159 |
| `reference_b` | 0.467728 s | 0.437741 s | 1,184,718 | 1,418,851 |

Runtime changed about -5% and -6%; traced peaks rose about 16% and 20%.
Both are within MA-001's 20% runtime and 25% memory review thresholds.

The MA-001 absolute budget is two seconds for ready-input offline Draft advice
under the observed 60-second pick clock. `python -m scripts.ma004f_draft_clock`
measured five repetitions after warm-up at early, middle and late turns for
every reference seat (66 states). The largest median was 0.421 seconds and
largest individual measured turn was 0.434 seconds. This is same-machine
synthetic evidence, not a portable CI timing assertion or a network-latency
claim.

Focused tests: 120 passed. Full suite: 950 passed. Ruff passed. Package,
privacy and CI outcomes are recorded in the PR. Reverting the PR restores the
old decision code; no private data is migrated. A new season needs its own
validated schedule artifact before bye-aware simulation or completed-mock
scoring. This PR does not promote the broader MA-005 support matrix.
