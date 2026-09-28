# MA-005a: synthetic half-PPR roster matrix

September 28, 2026. This is the first bounded MA-005 evidence slice. It tests
roster shape and shared mechanics, not a claim that all three assistants are
ready for every league below. No provider request, real roster, recommendation
policy change or Sleeper write was used.

## Twelve base combinations

The fixed starters in every row are QB, two RB, two WR, TE, K and DST. The
synthetic scoring map has 0.5 reception points. `WR/RB` denotes one RB/WR flex;
`FLEX` denotes one RB/WR/TE flex. Each row has a full roster and an otherwise
identical one-open-slot case. `PASS` means normalized size and slots, Draft room
slot translation and legal fit, neutral lineup assignment, and active capacity
matched independent expectations. It is not a feature support classification.

| Teams | Flex | Bench | Active places | Lineup points | Structural result |
| ---: | --- | ---: | ---: | ---: | --- |
| 10 | WR/RB | 5 | 14 | 135 | PASS |
| 10 | WR/RB | 6 | 15 | 135 | PASS — `reference_a` shape |
| 10 | FLEX | 5 | 14 | 136 | PASS |
| 10 | FLEX | 6 | 15 | 136 | PASS |
| 10 | 2 FLEX | 5 | 15 | 152 | PASS |
| 10 | 2 FLEX | 6 | 16 | 152 | PASS |
| 12 | WR/RB | 5 | 14 | 135 | PASS |
| 12 | WR/RB | 6 | 15 | 135 | PASS |
| 12 | FLEX | 5 | 14 | 136 | PASS |
| 12 | FLEX | 6 | 15 | 136 | PASS |
| 12 | 2 FLEX | 5 | 15 | 152 | PASS — `reference_b` shape |
| 12 | 2 FLEX | 6 | 16 | 152 | PASS |

The point oracle starts with eight fixed starters worth 117 points. A 15-point
WR replaces a 13-point WR. The eligible remaining flex values are RB 16 and TE
17, so the three flex layouts score 135, 136 and 152. Extra bench players have
one point and cannot improve those lineups. Every full roster fits its declared
slots; adding one more RB does not. Removing one bench player opens exactly one
active place. These are invented inputs, not projections or calibrated value.

## Feature and command limits

| Scope | Current evidence and limit |
| --- | --- |
| Draft simulation and advice | The two exact reference sizes have prior fixed-seed semantic and all-seat Draft checks. This slice checks slot mechanics for the wider 12 shapes. Room-backed `recommend` and `watch` still require actual position-limit admission; missing or enabled-but-unmapped maxima remain LIMITED under #31. Synthetic `enforce_position_limits=0` admits only that narrow rule scope. Season-bound schedule evidence remains required for bye-aware scoring. No other Draft mode or wider policy is admitted here. |
| Trade diagnose, evaluate and search | The two exact profiles have MA-001 synthetic workflow evidence. Shared scoring may be a conditional estimate under MA-002p; provider event definitions and actual coverage remain open in #30. This slice does not run these commands for the ten other shapes, establish specialist Trade valuation, or validate each league's policy. |
| Waiver evaluate, search and add/drop planning | The two exact profiles have MA-001 synthetic workflow evidence. Waiver cannot affirmatively add or claim from conditional forecasts. This slice does not run the ten other shapes through full waiver evidence, game locks, reserve or claim modes. Existing per-league decision policy remains separate. |
| Data and support status | Structural PASS is distinct from rule support, data readiness, search completeness and policy calibration. No 12-row feature support promotion follows. Standard and PPR remain MA-006 validation work. |

Ancillary modes are not implied by the 12 shape rows. Reserve eligibility and
capacity, waiver mechanisms, game locks, scoring categories, traded picks and
source freshness need their operation-specific checks. The exact reference
profiles retain their own observed rules; the synthetic rows do not transfer
one league's evidence or calibration to another.

## Validation and next gate

`tests/test_ma005a_roster_matrix.py` enumerates all 12 distinct rows, asserts
the independent lineup values, full/open capacity and an overfull Draft
rejection. It also proves the Draft room gate stays LIMITED with absent or
enabled-but-unverified position limits. Existing MA-001 semantic goldens cover
the two exact profiles. Full feature validation, ancillary interactions and
performance gates remain before MA-005 support publication. Issue #31 needs
verified position-limit source rules; #30 needs provider field and coverage
evidence. Reverting this PR removes only this inventory and test coverage.
