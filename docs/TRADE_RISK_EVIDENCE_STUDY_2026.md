# Trade Assistant Phase 6 risk-evidence study

Date: September 5, 2026 (America/Los_Angeles)
Decision: use transparent scenario-only risk; do not fit player-pair correlation.

## Question

Does the available historical player-points evidence support stable,
league-scored position-pair or same-offense priors for the League Alpha half-PPR
Trade Assistant?

## Available evidence

The authenticated capability probe found one usable FantasyPros historical
player-points surface: 166 running-back rows for the 2025 season, Weeks 1–17.
The response declares PPR scoring. The probe retained only schema, parameters,
counts, and metadata; no licensed player rows were copied into the repository.

That evidence does not cover multiple seasons, all required positions, or the
league's half-PPR scoring. It cannot estimate QB/pass-catcher, two-pass-catcher,
RB/pass-catcher, or same-offense priors, and it cannot support overlap-aware
player-pair shrinkage.

## Decision

TA-603 selects the requirements-approved broad `SCENARIO_ONLY` fallback. TA-604
does not fit correlation coefficients. The evaluator instead retains visible
pair types, starter/full-roster concentration, point shares, sample-free
independent-absence tests, and deterministic offense-wide downside/upside
scenarios. These scenarios are sensitivities, not probabilities or P10/P90
claims.

The versioned `phase6-scenario-fallback-v1` policy uses a 0.70 offense-downside
multiplier and a 1.20 offense-upside multiplier. Those values intentionally
describe broad stress cases; live testing may motivate a later policy version,
but no league or player-specific probability is inferred from them.

## Revisit gate

Correlation may be activated only after an audited dataset provides multiple
seasons, all required skill positions, weekly player identity/team context,
active-game overlap, and scoring that can be reproduced under the league's
actual rules. Any fitted coefficients must report sample count, seasons,
shrinkage strength, and holdout results.

## Reproducible evidence

- `data/exports/trade/fantasypros_capability_probe.json`
- `docs/TRADE_ASSISTANT_PROVIDER_FEASIBILITY_2026.md`
- `config/trade/phase6_policy.json`
