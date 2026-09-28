# MA-005b: synthetic Trade and Waiver evaluation matrix

September 28, 2026. This slice extends the MA-005a structural roster matrix
through one bounded Trade and Waiver evaluation path per shape. It uses only
invented teams, players and three-week point inputs. The source profile supplies
a half-PPR test scoring map; no reference league's policy calibration or
readiness is transferred to another league.

## Twelve evaluation cases

Each row has 10 or 12 teams, the fixed QB/2 RB/2 WR/TE/K/DST starters, one
RB/WR flex (`WR/RB`), one RB/WR/TE flex (`FLEX`) or two such flexes, and five
or six bench places. The same invented positions and ordered points are used
throughout. The user roster's weekly skill lineup is 126 points with one flex
or 140 with two. The entered Trade sends one RB to a synthetic partner and
receives a different RB. Its three-week weighted lineup change is +3 for the
user and -3 for the partner. These are hand-calculated fixture expectations,
not predicted NFL outcomes.

| Teams | Flex | Bench | Weekly skill lineup | Trade user/partner delta | Waiver full/open |
| ---: | --- | ---: | ---: | --- | --- |
| 10 | WR/RB | 5 | 126 | +3 / -3 | Drop / no drop |
| 10 | WR/RB | 6 | 126 | +3 / -3 | Drop / no drop |
| 10 | FLEX | 5 | 126 | +3 / -3 | Drop / no drop |
| 10 | FLEX | 6 | 126 | +3 / -3 | Drop / no drop |
| 10 | 2 FLEX | 5 | 140 | +3 / -3 | Drop / no drop |
| 10 | 2 FLEX | 6 | 140 | +3 / -3 | Drop / no drop |
| 12 | WR/RB | 5 | 126 | +3 / -3 | Drop / no drop |
| 12 | WR/RB | 6 | 126 | +3 / -3 | Drop / no drop |
| 12 | FLEX | 5 | 126 | +3 / -3 | Drop / no drop |
| 12 | FLEX | 6 | 126 | +3 / -3 | Drop / no drop |
| 12 | 2 FLEX | 5 | 140 | +3 / -3 | Drop / no drop |
| 12 | 2 FLEX | 6 | 140 | +3 / -3 | Drop / no drop |

The Trade evaluation is bound to the synthetic league key and reports no
missing player-weeks for the entered package. Waiver evaluation is likewise
bound to that key, uses a rostered drop for a full team, and uses no drop when
there is an open active place. It has complete synthetic point/value inputs,
but no Waiver decision policy is supplied: the result generates no affirmative
recommendation and performs no Sleeper write. Trade's default provisional
decision engine executes for fixture coverage; its label is not accepted as
calibration or a support claim for any new league.

In every shape, removing the add player's projection blocks that affected
Waiver evaluation with the player identified. An independent Trade diagnosis
still returns the hand-calculated lineup. Missing evidence is not interpreted
as zero and does not become a league-wide veto.

## Limits and next gate

`tests/test_ma005b_inseason_matrix.py` covers these bounded evaluations and
retains the MA-001 exact-reference semantic tests. It does not exercise full
candidate searches, multi-asset Trades, waiver claims, game locks, reserve
rules, live provider semantics, source freshness or decision-policy validation
for the ten other roster shapes. Draft rule admission still awaits #31; actual
FantasyPros field/coverage evidence still awaits #30. No support is promoted
from this matrix. Reverting this PR removes only the synthetic fixture option,
tests and evidence document.
