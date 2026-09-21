# TA-1306 — Exact 2-for-1 consolidation handoff

Completed September 20, 2026 (America/Los_Angeles) on
`codex/ta-1306-consolidation`. This is a read-only search-engine slice, not a
live recommendation or a change to the entered-package evaluator.

The `CONSOLIDATE` target lane now constructs only 2-for-1 offers and retains
its independent exact-evaluation budget and frontier. A simpler 1-for-1 cannot
displace it. The candidate construction band and separate market-fairness
decision compare the outgoing chart sum against the sole incoming player's
chart price plus an explicit, versioned percentage premium. Evidence preserves
raw and premium-adjusted price deltas, premium ratio, amount, policy ID, and
fairness band. In `ECR-PROXY`, no chart-premium value or chart-fairness claim is
made. The ratio is required configuration; the synthetic 10% fixture is not a
recommended production or league-specific calibration. TA-1308 owns the
rolling-origin, league-local calibration of this parameter and the fairness
bands. No empirical acceptance probability is inferred.

After exact evaluation, `ConsolidationEvidence` reconstructs both final rosters
with the user's open-slot add and the partner's required drop. It records the
target's started weeks and marginal lineup gain, the user's net weekly gain,
the add's marginal lineup/depth value, the drop's lineup/depth effect, and each
outgoing player's partner started weeks, marginal lineup gain, and
waiver-relative depth contribution. Acceptance requires a material net user
gain and target starter contribution, both secondary moves, and distinct
lineup/depth use for both outgoing assets after the drop. A value-balanced
package with an unusable or dropped second player fails explicitly. The
existing legality, downside, partner-plausibility, and intrinsic/market gates
remain separate.

Four new focused tests accept a mutually useful package, show a tight price
band admitting it only after the premium, reject an additive-value mirage, and
reverse the exact result with wrong add/drop overrides. The existing optimizer
suite checks that `ECR-PROXY` has no chart premium and validates premium
configuration. Full validation: 622 unit tests pass; `python -m ruff check`
passes on the changed Python files. No provider call, live league operation,
Sleeper write, secret, or licensed player row was used or persisted.

TA-1307 remains the planned CLI/report presentation of this evidence; TA-1308
remains its empirical calibration. This task does not authorize either one.
