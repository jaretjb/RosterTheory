# MA-002h: Waiver emerging-scenario scoring evidence

Status: bounded #30 follow-up; merge requires CI and review.

The WA-014 breakout model supplies six weekly statistics for an RB, WR or TE:
rushing yards and touchdowns, receptions, receiving yards and touchdowns, and
lost fumbles. Previously its legacy scorer marked a scenario complete whenever
the league had no *unsupported* rule, even if an active rule lacked a modeled
statistic. For example, a nonzero `pass_td` rule with no scenario passing
touchdowns silently contributed zero. The scenario could then influence its
option-value comparison as if it were a complete league score.

The scorer now assesses the actual league map for each modeled week with the
shared Sleeper linear-rule catalogue and the neutral scoring contract. Its
source is the explicit WA-014 scenario model, not a provider forecast or expert
ranking. Only complete evidence enters the scenario projection. Missing,
invalid, unsupported or unknown-applicability settings return a specific
`SCORING_OR_ADD_INPUT_INCOMPLETE` reason. A disabled zero-multiplier rule needs
no observation. Position reception bonuses use modeled receptions for the
matching position. Diagnostic partial points are never passed to the option
comparison. The base Waiver decision and unrelated candidate evaluation remain
available; no player statistic is inferred to be zero merely because this
six-field model omits it.

The calculation is bound to the evaluated league, season and modeled week.
Complete-case point rounding and sorted raw-stat ordering are retained. The
saved evaluation schema and reader are unchanged. Old saved evaluations are
historical evidence and must be regenerated for current scoring coverage.
Neither reference league is newly certified: `fum_rec` applicability remains
unresolved, and typical scoring maps may require events this narrow scenario
model does not predict. A blocked breakout comparison is distinct from an
unavailable base Waiver recommendation.

Synthetic regressions cover a missing active passing category, a disabled
category, position reception bonus, existing unsupported-rule behavior,
complete-case point changes and unchanged base decision. Full suite, reference
goldens, Ruff, context and privacy checks are the local handoff gates. No paid
provider request, live league operation, simulation, football-prior change or
calibration was performed. Draft import scoring and provider field semantics
remain under #30; #31 and MA-002 remain open.

Local handoff: 905 tests pass, including unchanged MA-001 reference goldens;
Ruff, compilation, context routing and tracked-tree privacy checks pass.
