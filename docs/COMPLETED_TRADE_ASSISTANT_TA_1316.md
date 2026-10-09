# TA-1316 — Plausible Trade packages and useful counteroffers

Authorized October 8, 2026 after review of the saved timed finder results.
Two-QB packages could strip an opponent's entire QB group while assuming a
waiver addition, increase redundant one-QB depth, and reach the counteroffer
list despite failed user risk gates. The cheap estimate also added each QB's
individual improvement over the same baseline.

## Changes

The Trade-owned `trade-finder-roster-v1` checks both teams' viable dedicated
starter coverage before free-agent additions. Packages cannot worsen an
existing shortage or strip required coverage. The existing Phase 10 rule
permits one reserve at a position with one eligible starter slot and rejects
increasing its player count beyond two. Actual slot eligibility preserves QB
exchanges, superflex and multi-QB formats. Required final drops are checked too.
Construction allows mandatory drops to resolve excess depth when the actual
exchange preserves starter coverage; the final check verifies the chosen drop.

For potentially supported exact results, every incoming asset is measured
conditional on the complete final roster. Useful lineup or above-waiver depth
must clear the existing asset-use thresholds. Cheap QB estimates replace
independent marginal additions/removals with a joint slot calculation;
multi-QB/flexible formats use the neutral legal-lineup solver.

Counteroffers require a strict COUNTER, intrinsic WIN, the existing minimum
lineup gain, all user value/risk/depth/evidence checks, complete roster checks,
and a partner result within the existing lineup/depth policy. Negotiation
candidates retain the sole opponent-value-floor exception. User-loss and
implausible packages remain diagnostic. Football verdicts, expert weights,
price bands, premiums and numerical thresholds are unchanged.

Construction and repairs record separate roster-pruning counts, complete
reason totals and up to three rejection examples per opponent/shape/stage/
reason. Completed checks retain raw failures and incoming-use evidence. A
pruned repair has no exact verdict or evaluation hash. JSON and CSV preserve
these fields, and human coverage includes the roster-pruned count. Saved timed
replay continues to verify recorded results without rerunning a timer.

## Validation

Focused regression coverage includes no waiver rescue for a stripped QB
group, redundant third-QB rejection, legal QB swaps, superflex and two-QB
capacity, zero-forecast backup coverage, joint QB estimates, conditional
incoming use, strict verdict preservation, rejection counts and bounded repairs.

All 1,051 repository tests pass in 106.879 seconds, including 11 focused roster
regressions. The dedicated 18-test context gate, 66 local documentation links,
Ruff, compilation and tracked/staged repository privacy checks pass.
The saved league case runs at its
original evidence time with no provider refresh: 120.036 seconds, 21 completed
exact evaluations and four supported ideas (one strict recommendation and
three negotiation candidates). Both invalid two-QB offers are excluded. The
11,031 construction roster rejections have complete reason counts and 687
bounded diagnostic samples. Every selected incoming asset passes conditional
usefulness; all selected ideas pass user value/risk/depth and roster gates.
Enumerated pairs reconcile to price pruning, roster pruning, eligible and
unconstructed counts, and the maximum sample count is three per key.

The saved source's football optimizer configuration matches exactly. This is
an offline, non-actionable regression case, not a fresh recommendation or an
exhaustive search. Its provider evidence, league details and private artifacts
remain ignored under `data/exports/trade/`.

Wheel and source distribution build successfully. Distribution privacy and
clean-install smoke checks pass. The verified wheel is installed in the
existing local pipx environment; dependency checks pass, the installed module
reports `trade-finder-roster-v1`, and `trade search --help` retains opponent
scope and time-budget controls. README, the finder guide, requirements,
design, CLI contract, task index and Trade handoff are updated.

Separate branch: `codex/trade-finder-roster-plausibility`. Handoff:
[PR #83](https://github.com/jaretjb/RosterTheory/pull/83), open for review.
No provider refresh, league-policy mutation or Sleeper write was performed.
