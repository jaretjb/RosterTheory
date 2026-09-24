# Trade Assistant TA-1312 completion

Completed September 23, 2026 (America/Los_Angeles).

## Outcome

Trade no longer requires five fresh ROS experts. The preferred panel is three,
two is a visible `DEGRADED` but usable panel, and fewer than two still blocks.
Weights are normalized across the selected members.

The deeper shared Waiver lesson also applies: directory availability is not
enough. Trade now selects only trustworthy experts who actually contributed to
QB, RB, WR, and TE in the current ROS ranking payload. It uses a 70/30 blend of
current/prior weekly accuracy rank for selection and excludes an expert ranked
100th or worse in both seasons. Selected-expert intrinsic value remains
separate from the FantasyPros Latest ECR market board.

Waiver Wire rank, Waiver's combined acquisition score, and weekly matchup
weighting were not copied into Trade.

## Verification

- Synthetic tests cover three-expert `READY`, two-expert `DEGRADED`, one-expert
  failure, actual-contributor filtering, poor-expert exclusion, and normalized
  weights.
- Today's saved FantasyPros evidence reproduced the former two-of-five case for
  both configured leagues without a provider call.
- League Beta's actual Trade value-board refresh completed with three current
  contributors, both ROS boards complete, 25 cache hits, zero provider calls,
  and no Sleeper write.
- League Alpha passed expert selection, then correctly stopped at an unrelated
  active-board coverage failure for rostered inactive player `12508`.
- All 666 tests and Ruff pass.
