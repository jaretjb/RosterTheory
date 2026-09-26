# MA-002d roster membership and eligibility

September 26, 2026. Bounded implementation under #31, following merged PR #37
(`75b6793e10f4bd674234dde9938dd22a09f52ad0`). Overall MA-002 and #31 remain open.

## Problem and resulting behavior

Before this change, normalizing a Sleeper roster with `players=[active,taxi]`
and `taxi=[taxi]` lost the taxi role entirely. The owned player survived, but
consumers could treat that player as active. Reserve capacity also did not prove
that an injured player's current status was eligible for a reserve slot.

The neutral membership assessment now retains owned, active, starter, reserve
and taxi roles. It reports duplicate ownership, duplicate role membership,
unowned starters/reserves/taxi players, overlapping roles and exceeded active,
starter or reserve capacity. Empty starter placeholders do not own a player.
Active capacity excludes explicit IR/reserve/taxi positions.

Trade and Waiver validate structural membership when building snapshots and
before current operations. Known taxi formats or occupied taxi roles are
unsupported. Draft rejects known taxi settings in reconciliation and known taxi
settings/membership in loaded league snapshots and board preparation. A standalone
Draft payload does not prove all league rules; this is deliberately narrow
admission, not a declaration of full Draft support.

Sleeper field names and reserve status rules live in the provider adapter;
the core accepts neutral facts. Required provider collections (`players`,
`starters`, `reserve`) must be present and contain player ID arrays; explicit
null is normalized as an empty collection. Taxi null/absence remains unknown,
while an explicit empty array means no membership. Explicit league taxi capacity
of zero can establish absence when the taxi collection is unavailable. Missing
capacity remains unknown; malformed numeric capacities are rejected rather than
coerced. No absent commissioner flag is assumed enabled or disabled.

Sleeper describes [IR/PUP eligibility and configurable status extensions](https://support.sleeper.com/en/articles/1983643-how-does-injured-reserve-ir-work)
and distinguishes [injury statuses and IR eligibility](https://support.sleeper.com/en/articles/3570017-injury-statuses-and-ir-eligibility).
The adapter accepts IR/PUP and checks explicit flags for supported extensions.
Missing identity, unrecognized status or missing extension flags produce UNKNOWN;
known disallowed statuses produce INVALID. The
[public roster API](https://docs.sleeper.com/#getting-rosters-in-a-league)
does not document every commissioner setting; this implementation does not infer
unverified Draft position-limit semantics from it.

For a trade involving a roster with unresolved or invalid reserve eligibility,
the comparison is marked MANUAL-LEGALITY and cannot pass the complete-evidence
gate. Whether Sleeper permits that trade can depend on further settings; the
tool does not claim an exact legal offer. Waiver acquisitions require the user's
reserve capacity and eligibility to be known and legal, with a fresh check of
the snapshot's player statuses even if saved capacity flags said legal.

These checks concern ownership and transaction eligibility. Missing rankings or
projections still use MA-002c's decision-scoped dependencies; irrelevant missing
forecasts do not acquire a new whole-roster veto.

## Saved evidence and compatibility

New Trade/Waiver snapshots use schema version 2. `FantasyTeam.taxi_ids` is a
required serialized field; null explicitly records unknown. `LeagueRules`
includes `taxi_slots`, with unavailable capacity represented by null. Fields
were appended to retain constructor positional compatibility.

Readers reject normalized team records lacking `taxi_ids` with an instruction
to refresh source evidence or replay using the original build. They do not
retroactively label lost membership empty. A version 1 record is readable only
if it already explicitly contains the new membership evidence, as current
trusted constructors can produce; missing evidence and unsupported future
snapshot versions are rejected. Typed replay restoration enforces the same
required membership field and array shape. Raw provider files remain unchanged.
Historical results can be inspected with their original build; copying an old
file's version number does not repair its missing evidence.

The original `tests/fixtures/modular/semantics.json` remains unchanged. Full
before/after canonical payloads for all 24 MA-001 synthetic workloads were
compared against the merged base. Exactly 96 paths changed:

| Change | Count |
| --- | ---: |
| Explicit empty `taxi_ids` additions | 44 |
| Explicit zero `taxi_slots` additions | 4 |
| Derived `evidence_hash` | 22 |
| Derived `manifest_id` | 22 |
| Derived `replay_hash` | 2 |
| Derived `snapshot_hash` | 2 |

No decision, lineup total, value, risk, warning or search count changed. Sixteen
workload hashes changed; eight stayed identical. The exact path/value receipt is
`tests/fixtures/modular/membership-v2-changes.json`. The current complete-output
golden is `semantics-membership-v2.json` in the same directory. Runtime provenance
and golden tests still compare full hashes; no production hash fields are
stripped or exempted. The baseline benchmark selects the matching golden version.

`scripts/ma002_membership_diff.py BEFORE AFTER --output RECEIPT` repeats the
bounded payload audit; it rejects any differences outside these additions and
derived hash fields and does not write a golden. Both payloads must be captured
from the same `scripts.ma001_baseline.workloads` with `offline()` and canonical
serialization, once on the merged base and once on this change. Local copies
are ignored `data/exports/ma002d-before.json` and `ma002d-after.json`. Their receipt
is review evidence, not a replacement for the current full-output tests. Do not
rerun the historical `ma001_baseline.py --capture` over the original golden.

## Verification and handoff

All 877 local tests pass (107.398 seconds), including all 24 full-output reference
workloads. Ruff, compilation, 18 context-routing tests and the tracked repository
privacy gate pass. Required PR CI and review remain the merge gate.

Offline tests cover lost taxi preservation; unknown/empty distinctions;
duplicates, overlaps and capacity; missing/malformed source fields; independent
reference profiles; enabled/disabled/unknown reserve rules; three-feature taxi
admission; saved-file round trips and rejection; and operation-level legality.
The two reference fixtures independently retain 15 active slots and correct
14-player open-roster behavior. Existing decision-coverage regressions remain
part of the full suite. No provider refresh, live simulation or league mutation
was performed.

Remaining #31 work: confirm `enforce_position_limits` semantics and source
position caps for Draft, and complete feature capability/admission contracts.
Scoring/provider gaps remain #30; both reference maps remain LIMITED for
`fum_rec`. This change establishes neither calibration nor the future 12-format
support matrix. Revert this PR as a unit if needed; original-build replay and
the retained v1 golden provide the historical compatibility boundary.
