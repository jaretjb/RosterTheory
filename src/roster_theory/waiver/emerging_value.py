from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from typing import Mapping, Sequence

from roster_theory.core.models import Projection
from roster_theory.core.provenance import stable_hash
from roster_theory.core.scoring import score_stats
from roster_theory.inseason.evaluation import (
    ImpactOptions,
    InSeasonContext,
    WeeklyProjectionMatrix,
    build_weekly_projection_matrix,
    depth_above_waiver,
    lineup,
    weighted_lineup_score,
)
from roster_theory.waiver.emergence import EmergenceEvidence, PlayerEmergenceEvidence


FOOTBALL_PRIOR_VERSION = "wa-014-sustainable-efficiency-v1"
SCENARIO_STATES = ("MISS", "USEFUL_ROLE", "BREAKOUT")
SCENARIO_INPUT_SCHEMA_VERSION = 1
SCENARIO_OUTPUT_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class PositionFootballPrior:
    position: str
    catch_rate: float
    rush_yards_per_carry: float
    receiving_yards_per_reception: float
    rush_touchdowns_per_carry: float
    receiving_touchdowns_per_target: float
    fumbles_lost_per_opportunity: float
    source: str


# These are intentionally modest, transparent football priors rather than
# player forecasts. State differences come from opportunity, not an assumed
# efficiency spike. Empirical calibration is deferred to WA-016.
POSITION_PRIORS = {
    "RB": PositionFootballPrior(
        position="RB",
        catch_rate=0.72,
        rush_yards_per_carry=4.20,
        receiving_yards_per_reception=7.50,
        rush_touchdowns_per_carry=0.025,
        receiving_touchdowns_per_target=0.030,
        fumbles_lost_per_opportunity=0.010,
        source="Documented WA-014 sustainable-efficiency football prior",
    ),
    "WR": PositionFootballPrior(
        position="WR",
        catch_rate=0.64,
        rush_yards_per_carry=5.50,
        receiving_yards_per_reception=11.50,
        rush_touchdowns_per_carry=0.020,
        receiving_touchdowns_per_target=0.050,
        fumbles_lost_per_opportunity=0.006,
        source="Documented WA-014 sustainable-efficiency football prior",
    ),
    "TE": PositionFootballPrior(
        position="TE",
        catch_rate=0.68,
        rush_yards_per_carry=3.00,
        receiving_yards_per_reception=9.50,
        rush_touchdowns_per_carry=0.015,
        receiving_touchdowns_per_target=0.045,
        fumbles_lost_per_opportunity=0.006,
        source="Documented WA-014 sustainable-efficiency football prior",
    ),
}


@dataclass(frozen=True, slots=True)
class ScenarioOpportunityAssumption:
    week: int
    carries: float
    targets: float
    total_opportunities: float | None
    goal_line_work: float | None
    red_zone_work: float | None
    two_minute_usage: float | None
    designed_touches: float | None
    derivation: str


@dataclass(frozen=True, slots=True)
class EmergingStateInput:
    state: str
    source: str
    horizon: tuple[int, ...]
    opportunity_transformation: str
    assumptions: tuple[ScenarioOpportunityAssumption, ...]
    strongest_uncertainty: str


@dataclass(frozen=True, slots=True)
class EmergingScenarioInput:
    schema_version: int
    player_id: str
    position: str
    classification: str
    emergence_evidence_hash: str
    prior_version: str
    prior: PositionFootballPrior | None
    central_projection_hash: str
    complete: bool
    states: tuple[EmergingStateInput, ...]
    warnings: tuple[str, ...]
    input_hash: str


@dataclass(frozen=True, slots=True)
class ScenarioWeekImpact:
    week: int
    playoff: bool
    weight: float
    central_projection_points: float
    scenario_projection_points: float
    central_lineup_points: float
    scenario_lineup_points: float
    lineup_effect: float
    central_starters: tuple[str, ...]
    scenario_starters: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ScenarioAlternative:
    action: str
    state: str
    scenario_player_id: str | None
    weighted_lineup_points: float
    central_weighted_lineup_points: float
    weighted_effect: float
    current_week_effect: float
    playoff_effect: float
    starter_weeks: tuple[int, ...]
    bye_weeks: tuple[int, ...]
    depth_above_waiver: float
    central_depth_above_waiver: float
    depth_effect: float
    replacement_exposure: float
    scenario_projections: tuple[Projection, ...]
    weekly_impacts: tuple[ScenarioWeekImpact, ...]


@dataclass(frozen=True, slots=True)
class ScenarioComparison:
    state: str
    act_now: ScenarioAlternative
    retain_drop: ScenarioAlternative
    act_now_minus_retain_drop: float


@dataclass(frozen=True, slots=True)
class BreakEvenAnalysis:
    status: str
    breakout_gain: float
    miss_loss: float
    hit_rate: float | None
    formula: str
    explanation: str


@dataclass(frozen=True, slots=True)
class ExpectedValueSensitivity:
    hypothetical_miss_probability: float
    hypothetical_useful_role_probability: float
    hypothetical_breakout_probability: float
    expected_act_now_minus_retain_drop: float


@dataclass(frozen=True, slots=True)
class NoActionAlternative:
    weighted_lineup_points: float
    retained_player_id: str | None
    central_preferred: bool
    best_in_every_scenario: bool


@dataclass(frozen=True, slots=True)
class EmergingUpsideValuation:
    schema_version: int
    status: str
    add_player_id: str
    drop_player_id: str | None
    add_input: EmergingScenarioInput | None
    drop_input: EmergingScenarioInput | None
    add_central_projection_points: float
    drop_central_projection_points: float
    central_act_now_weighted_points: float
    central_retain_drop_weighted_points: float
    central_delta: float
    scenario_comparisons: tuple[ScenarioComparison, ...]
    breakout_gain: float
    useful_role_gain: float
    miss_case_loss: float
    acquisition_option_ceiling: float
    retained_option_ceiling: float
    incremental_option_value: float
    add_miss_protection: float
    drop_miss_protection: float
    no_action: NoActionAlternative
    break_even: BreakEvenAnalysis
    expected_value_equation: str
    sensitivity: tuple[ExpectedValueSensitivity, ...]
    named_teammate_contingency_kept_separate: bool
    named_teammate_acquisition_ceiling: float
    named_teammate_retained_ceiling: float
    strongest_uncertainty: str
    valuation_hash: str


def _verified_emergence(evidence: EmergenceEvidence) -> None:
    expected = stable_hash(asdict(replace(evidence, evidence_hash="")))
    if evidence.evidence_hash != expected:
        raise ValueError("Emergence evidence hash is invalid")


def _comparison_value(
    player: PlayerEmergenceEvidence,
    metric: str,
    state: str,
) -> float | None:
    comparison = next((row for row in player.comparisons if row.metric == metric), None)
    if comparison is None:
        return None
    if state == "MISS":
        return comparison.baseline_average
    if state == "USEFUL_ROLE":
        return comparison.rolling_average
    recent = tuple(
        value
        for value in (comparison.latest, comparison.rolling_average)
        if value is not None
    )
    return round(max(recent) * 1.15, 6) if recent else None


def _unsigned_input(value: EmergingScenarioInput) -> dict[str, object]:
    result = asdict(value)
    result["input_hash"] = ""
    return result


def build_emerging_scenario_input(
    evidence: EmergenceEvidence,
    *,
    player_id: str,
    weeks: Sequence[int],
    central_projections: Sequence[Projection],
) -> EmergingScenarioInput:
    _verified_emergence(evidence)
    horizon = tuple(sorted(set(int(week) for week in weeks)))
    if not horizon or any(week <= 0 for week in horizon):
        raise ValueError("Emerging scenarios require a positive weekly horizon")
    central = tuple(
        sorted(
            (
                row
                for row in central_projections
                if row.player_id == player_id and row.horizon == "WEEKLY"
            ),
            key=lambda row: row.week or 0,
        )
    )
    central_hash = stable_hash(central)
    matches = tuple(row for row in evidence.players if row.player_id == player_id)
    warnings: list[str] = []
    player = matches[0] if len(matches) == 1 else None
    position = player.position.upper() if player else "UNKNOWN"
    prior = POSITION_PRIORS.get(position)
    if len(matches) != 1:
        warnings.append("Player lacks exactly one emergence-evidence row")
    elif not player.affirmative_eligible:
        warnings.append(
            f"Emergence classification {player.classification} is not affirmative"
        )
    if prior is None:
        warnings.append(
            f"No WA-014 opportunity-to-stat football prior exists for {position}"
        )
    if tuple(row.week for row in central) != horizon:
        warnings.append("Central weekly projections do not exactly cover the scenario horizon")

    states: list[EmergingStateInput] = []
    if player is not None and player.affirmative_eligible and prior is not None:
        for state in SCENARIO_STATES:
            carries = _comparison_value(player, "carries", state)
            targets = _comparison_value(player, "targets", state)
            if carries is None or targets is None:
                warnings.append(
                    f"{state} lacks explicit carries or targets; no metric was substituted"
                )
                continue
            total = _comparison_value(player, "total_opportunities", state)
            designed = _comparison_value(player, "designed_touches", state)
            if total is not None and abs(total - carries - targets) > 1.0:
                warnings.append(
                    f"{state} reported total opportunities differ from carries plus targets"
                )
            transformation = {
                "MISS": "Earlier-baseline opportunity averages, with no efficiency penalty",
                "USEFUL_ROLE": "Two-game rolling opportunity averages",
                "BREAKOUT": "1.15 times the stronger of latest and rolling opportunity",
            }[state]
            assumptions = tuple(
                ScenarioOpportunityAssumption(
                    week=week,
                    carries=round(carries, 6),
                    targets=round(targets, 6),
                    total_opportunities=total,
                    goal_line_work=_comparison_value(player, "goal_line_work", state),
                    red_zone_work=_comparison_value(player, "red_zone_work", state),
                    two_minute_usage=_comparison_value(player, "two_minute_usage", state),
                    designed_touches=designed,
                    derivation=transformation,
                )
                for week in horizon
            )
            states.append(
                EmergingStateInput(
                    state=state,
                    source=(
                        f"Emergence evidence {evidence.evidence_hash}; "
                        f"football prior {FOOTBALL_PRIOR_VERSION}"
                    ),
                    horizon=horizon,
                    opportunity_transformation=transformation,
                    assumptions=assumptions,
                    strongest_uncertainty=(
                        "State probabilities, role persistence, availability decay, claim "
                        "success, FAAB price, and waiver-priority cost are not estimated"
                    ),
                )
            )
    complete = not warnings and tuple(row.state for row in states) == SCENARIO_STATES
    base = EmergingScenarioInput(
        schema_version=SCENARIO_INPUT_SCHEMA_VERSION,
        player_id=player_id,
        position=position,
        classification=player.classification if player else "UNKNOWN",
        emergence_evidence_hash=evidence.evidence_hash,
        prior_version=FOOTBALL_PRIOR_VERSION,
        prior=prior,
        central_projection_hash=central_hash,
        complete=complete,
        states=tuple(states),
        warnings=tuple(sorted(set(warnings))),
        input_hash="",
    )
    return replace(base, input_hash=stable_hash(_unsigned_input(base)))


def calculate_break_even(
    *,
    breakout_gain: float,
    miss_loss: float,
) -> BreakEvenAnalysis:
    gain = round(float(breakout_gain), 6)
    loss = round(float(miss_loss), 6)
    formula = "miss_loss / (breakout_gain + miss_loss)"
    if gain <= 0 and loss > 0:
        return BreakEvenAnalysis(
            status="DOMINATED",
            breakout_gain=gain,
            miss_loss=loss,
            hit_rate=None,
            formula=formula,
            explanation=(
                "ACT_NOW loses in the miss case and has no positive breakout gain, "
                "so no breakout belief justifies it under this two-state comparison."
            ),
        )
    if gain <= 0:
        return BreakEvenAnalysis(
            status="NO_POSITIVE_BREAKOUT_GAIN",
            breakout_gain=gain,
            miss_loss=loss,
            hit_rate=None,
            formula=formula,
            explanation=(
                "The breakout comparison supplies no positive gain; a conventional "
                "two-state hit threshold is not meaningful."
            ),
        )
    if loss <= 0:
        return BreakEvenAnalysis(
            status="NO_MISS_DOWNSIDE",
            breakout_gain=gain,
            miss_loss=loss,
            hit_rate=0.0,
            formula=formula,
            explanation=(
                "ACT_NOW is not worse in the modeled miss case, so the two-state "
                "break-even breakout belief is 0%; this is not a claim-success estimate."
            ),
        )
    rate = loss / (gain + loss)
    return BreakEvenAnalysis(
        status="AVAILABLE",
        breakout_gain=gain,
        miss_loss=loss,
        hit_rate=round(rate, 6),
        formula=formula,
        explanation=(
            f"ACT_NOW is justified in the two-state model only if the manager's "
            f"breakout belief exceeds {rate:.1%}; no probability is estimated here."
        ),
    )


def _state_projections(
    value: EmergingScenarioInput,
    state: str,
    scoring: Mapping[str, float],
) -> tuple[tuple[Projection, ...], tuple[str, ...]]:
    if stable_hash(_unsigned_input(value)) != value.input_hash:
        return (), ("Emerging scenario input hash is invalid",)
    state_rows = tuple(row for row in value.states if row.state == state)
    if not value.complete or len(state_rows) != 1 or value.prior is None:
        return (), tuple(value.warnings) or ("Emerging scenario input is incomplete",)
    state_input = state_rows[0]
    projections: list[Projection] = []
    warnings: list[str] = []
    prior = value.prior
    for assumption in state_input.assumptions:
        receptions = assumption.targets * prior.catch_rate
        raw_stats = {
            "rush_yd": assumption.carries * prior.rush_yards_per_carry,
            "rush_td": assumption.carries * prior.rush_touchdowns_per_carry,
            "rec": receptions,
            "rec_yd": receptions * prior.receiving_yards_per_reception,
            "rec_td": assumption.targets * prior.receiving_touchdowns_per_target,
            "fum_lost": (
                assumption.carries + assumption.targets
            )
            * prior.fumbles_lost_per_opportunity,
        }
        scored = score_stats(raw_stats, scoring)
        if not scored.complete:
            warnings.append(
                "Unsupported non-zero Sleeper scoring settings: "
                + ", ".join(scored.unsupported_settings)
            )
        projections.append(
            Projection(
                player_id=value.player_id,
                horizon="WEEKLY",
                week=assumption.week,
                raw_stats=tuple((key, float(raw)) for key, raw in scored.raw_stats),
                league_points=scored.points,
                source=(
                    f"{state_input.source}; {state}; {prior.source}; "
                    f"{state_input.opportunity_transformation}"
                ),
                coverage_status="complete" if scored.complete else "partial",
            )
        )
    return tuple(projections), tuple(sorted(set(warnings)))


def _scenario_matrix(
    context: InSeasonContext,
    central_projections: Sequence[Projection],
    overrides: Sequence[Projection],
) -> WeeklyProjectionMatrix:
    rows = {
        (row.player_id, row.week): row
        for row in central_projections
        if row.horizon == "WEEKLY" and row.week is not None
    }
    for row in overrides:
        rows[(row.player_id, row.week)] = row
    return build_weekly_projection_matrix(context, tuple(rows.values()))


def _alternative(
    *,
    action: str,
    state: str,
    scenario_player_id: str | None,
    context: InSeasonContext,
    central_matrix: WeeklyProjectionMatrix,
    scenario_matrix: WeeklyProjectionMatrix,
    roster: set[str],
    scenario_projections: Sequence[Projection],
    current_week: int,
    options: ImpactOptions,
) -> ScenarioAlternative:
    weighted_central = weighted_lineup_score(context, central_matrix, roster, options)
    weighted_scenario = weighted_lineup_score(context, scenario_matrix, roster, options)
    weekly: list[ScenarioWeekImpact] = []
    starter_weeks: list[int] = []
    bye_weeks: list[int] = []
    player_by_id = {row.player_id: row for row in context.players}
    scenario_player = player_by_id.get(scenario_player_id) if scenario_player_id else None
    for week in context.weeks:
        central_lineup = lineup(
            context,
            central_matrix,
            roster,
            week.week,
            allow_partial=options.allow_partial_schedule,
        )
        scenario_lineup = lineup(
            context,
            scenario_matrix,
            roster,
            week.week,
            allow_partial=options.allow_partial_schedule,
        )
        central_ids = tuple(sorted(row.player_id for row in central_lineup.assignments))
        scenario_ids = tuple(sorted(row.player_id for row in scenario_lineup.assignments))
        if scenario_player_id in scenario_ids:
            starter_weeks.append(week.week)
        if scenario_player is not None and scenario_player.nfl_team in week.bye_teams:
            bye_weeks.append(week.week)
        central_cell = central_matrix.cell(scenario_player_id, week.week) if scenario_player_id else None
        scenario_cell = scenario_matrix.cell(scenario_player_id, week.week) if scenario_player_id else None
        weekly.append(
            ScenarioWeekImpact(
                week=week.week,
                playoff=week.playoff,
                weight=options.playoff_weight if week.playoff else 1.0,
                central_projection_points=round(float(central_cell.points or 0.0), 3) if central_cell else 0.0,
                scenario_projection_points=round(float(scenario_cell.points or 0.0), 3) if scenario_cell else 0.0,
                central_lineup_points=round(central_lineup.score, 3),
                scenario_lineup_points=round(scenario_lineup.score, 3),
                lineup_effect=round(scenario_lineup.score - central_lineup.score, 3),
                central_starters=central_ids,
                scenario_starters=scenario_ids,
            )
        )
    current = next(row for row in weekly if row.week == current_week)
    central_depth = depth_above_waiver(context, central_matrix, roster, options)
    scenario_depth = depth_above_waiver(context, scenario_matrix, roster, options)
    depth_effect = round(scenario_depth - central_depth, 3)
    return ScenarioAlternative(
        action=action,
        state=state,
        scenario_player_id=scenario_player_id,
        weighted_lineup_points=weighted_scenario,
        central_weighted_lineup_points=weighted_central,
        weighted_effect=round(weighted_scenario - weighted_central, 3),
        current_week_effect=current.lineup_effect,
        playoff_effect=round(
            sum(row.lineup_effect * row.weight for row in weekly if row.playoff), 3
        ),
        starter_weeks=tuple(starter_weeks),
        bye_weeks=tuple(bye_weeks),
        depth_above_waiver=scenario_depth,
        central_depth_above_waiver=central_depth,
        depth_effect=depth_effect,
        replacement_exposure=round(max(0.0, -depth_effect), 3),
        scenario_projections=tuple(scenario_projections),
        weekly_impacts=tuple(weekly),
    )


def _unavailable_valuation(
    *,
    status: str,
    add_player_id: str,
    drop_player_id: str | None,
    add_input: EmergingScenarioInput | None,
    drop_input: EmergingScenarioInput | None,
    add_central_projection_points: float,
    drop_central_projection_points: float,
    central_act_now: float,
    central_retain: float,
    named_teammate_acquisition_ceiling: float,
    named_teammate_retained_ceiling: float,
    uncertainty: str,
) -> EmergingUpsideValuation:
    no_action = NoActionAlternative(
        weighted_lineup_points=central_retain,
        retained_player_id=drop_player_id,
        central_preferred=central_retain >= central_act_now,
        best_in_every_scenario=False,
    )
    break_even = calculate_break_even(breakout_gain=0.0, miss_loss=0.0)
    base = EmergingUpsideValuation(
        schema_version=SCENARIO_OUTPUT_SCHEMA_VERSION,
        status=status,
        add_player_id=add_player_id,
        drop_player_id=drop_player_id,
        add_input=add_input,
        drop_input=drop_input,
        add_central_projection_points=add_central_projection_points,
        drop_central_projection_points=drop_central_projection_points,
        central_act_now_weighted_points=central_act_now,
        central_retain_drop_weighted_points=central_retain,
        central_delta=round(central_act_now - central_retain, 3),
        scenario_comparisons=(),
        breakout_gain=0.0,
        useful_role_gain=0.0,
        miss_case_loss=0.0,
        acquisition_option_ceiling=central_act_now,
        retained_option_ceiling=central_retain,
        incremental_option_value=round(central_act_now - central_retain, 3),
        add_miss_protection=0.0,
        drop_miss_protection=0.0,
        no_action=no_action,
        break_even=break_even,
        expected_value_equation="Unavailable until all three scenario states are valid",
        sensitivity=(),
        named_teammate_contingency_kept_separate=True,
        named_teammate_acquisition_ceiling=named_teammate_acquisition_ceiling,
        named_teammate_retained_ceiling=named_teammate_retained_ceiling,
        strongest_uncertainty=uncertainty,
        valuation_hash="",
    )
    return replace(base, valuation_hash=stable_hash(asdict(base)))


def _miss_protection(alternative: ScenarioAlternative) -> float:
    projection_loss = sum(
        max(0.0, row.central_projection_points - row.scenario_projection_points)
        * row.weight
        for row in alternative.weekly_impacts
    )
    lineup_loss = max(0.0, -alternative.weighted_effect)
    return round(max(0.0, projection_loss - lineup_loss), 3)


def _weighted_player_projection(
    context: InSeasonContext,
    matrix: WeeklyProjectionMatrix,
    player_id: str | None,
    options: ImpactOptions,
) -> float:
    if player_id is None:
        return 0.0
    return round(
        sum(
            float(cell.points or 0.0)
            * (options.playoff_weight if week.playoff else 1.0)
            for week in context.weeks
            if (cell := matrix.cell(player_id, week.week)) is not None
        ),
        3,
    )


def evaluate_emerging_upside(
    *,
    context: InSeasonContext,
    central_matrix: WeeklyProjectionMatrix,
    central_projections: Sequence[Projection],
    before_roster: set[str],
    after_roster: set[str],
    add_player_id: str,
    drop_player_id: str | None,
    add_input: EmergingScenarioInput | None,
    drop_input: EmergingScenarioInput | None,
    scoring: Mapping[str, float],
    current_week: int,
    options: ImpactOptions,
    named_teammate_acquisition_ceiling: float = 0.0,
    named_teammate_retained_ceiling: float = 0.0,
) -> EmergingUpsideValuation:
    central_act_now = weighted_lineup_score(context, central_matrix, after_roster, options)
    central_retain = weighted_lineup_score(context, central_matrix, before_roster, options)
    add_central_projection = _weighted_player_projection(
        context, central_matrix, add_player_id, options
    )
    drop_central_projection = _weighted_player_projection(
        context, central_matrix, drop_player_id, options
    )
    if add_input is None:
        return _unavailable_valuation(
            status="NOT_PROVIDED",
            add_player_id=add_player_id,
            drop_player_id=drop_player_id,
            add_input=None,
            drop_input=drop_input,
            add_central_projection_points=add_central_projection,
            drop_central_projection_points=drop_central_projection,
            central_act_now=central_act_now,
            central_retain=central_retain,
            named_teammate_acquisition_ceiling=named_teammate_acquisition_ceiling,
            named_teammate_retained_ceiling=named_teammate_retained_ceiling,
            uncertainty="No affirmative emergence scenario exists for the acquisition",
        )
    if not add_input.complete:
        return _unavailable_valuation(
            status="ADD_EVIDENCE_NOT_READY",
            add_player_id=add_player_id,
            drop_player_id=drop_player_id,
            add_input=add_input,
            drop_input=drop_input,
            add_central_projection_points=add_central_projection,
            drop_central_projection_points=drop_central_projection,
            central_act_now=central_act_now,
            central_retain=central_retain,
            named_teammate_acquisition_ceiling=named_teammate_acquisition_ceiling,
            named_teammate_retained_ceiling=named_teammate_retained_ceiling,
            uncertainty="; ".join(add_input.warnings),
        )
    comparisons: list[ScenarioComparison] = []
    for state in SCENARIO_STATES:
        add_projections, add_warnings = _state_projections(add_input, state, scoring)
        if add_warnings:
            return _unavailable_valuation(
                status="SCORING_OR_ADD_INPUT_INCOMPLETE",
                add_player_id=add_player_id,
                drop_player_id=drop_player_id,
                add_input=add_input,
                drop_input=drop_input,
                add_central_projection_points=add_central_projection,
                drop_central_projection_points=drop_central_projection,
                central_act_now=central_act_now,
                central_retain=central_retain,
                named_teammate_acquisition_ceiling=named_teammate_acquisition_ceiling,
                named_teammate_retained_ceiling=named_teammate_retained_ceiling,
                uncertainty="; ".join(add_warnings),
            )
        drop_projections: tuple[Projection, ...] = ()
        if drop_input is not None:
            drop_projections, drop_warnings = _state_projections(drop_input, state, scoring)
            if drop_warnings:
                return _unavailable_valuation(
                    status="DROP_EVIDENCE_NOT_READY",
                    add_player_id=add_player_id,
                    drop_player_id=drop_player_id,
                    add_input=add_input,
                    drop_input=drop_input,
                    add_central_projection_points=add_central_projection,
                    drop_central_projection_points=drop_central_projection,
                    central_act_now=central_act_now,
                    central_retain=central_retain,
                    named_teammate_acquisition_ceiling=named_teammate_acquisition_ceiling,
                    named_teammate_retained_ceiling=named_teammate_retained_ceiling,
                    uncertainty="; ".join(drop_warnings),
                )
        act_matrix = _scenario_matrix(context, central_projections, add_projections)
        retain_matrix = _scenario_matrix(context, central_projections, drop_projections)
        act = _alternative(
            action="ACT_NOW",
            state=state,
            scenario_player_id=add_player_id,
            context=context,
            central_matrix=central_matrix,
            scenario_matrix=act_matrix,
            roster=after_roster,
            scenario_projections=add_projections,
            current_week=current_week,
            options=options,
        )
        retain = _alternative(
            action="RETAIN_DROP",
            state=state,
            scenario_player_id=drop_player_id if drop_input is not None else None,
            context=context,
            central_matrix=central_matrix,
            scenario_matrix=retain_matrix,
            roster=before_roster,
            scenario_projections=drop_projections,
            current_week=current_week,
            options=options,
        )
        comparisons.append(
            ScenarioComparison(
                state=state,
                act_now=act,
                retain_drop=retain,
                act_now_minus_retain_drop=round(
                    act.weighted_lineup_points - retain.weighted_lineup_points, 3
                ),
            )
        )
    by_state = {row.state: row for row in comparisons}
    breakout_gain = by_state["BREAKOUT"].act_now_minus_retain_drop
    useful_gain = by_state["USEFUL_ROLE"].act_now_minus_retain_drop
    miss_loss = round(-by_state["MISS"].act_now_minus_retain_drop, 3)
    acquisition_ceiling = by_state["BREAKOUT"].act_now.weighted_lineup_points
    retained_ceiling = by_state["BREAKOUT"].retain_drop.weighted_lineup_points
    break_even = calculate_break_even(
        breakout_gain=breakout_gain,
        miss_loss=miss_loss,
    )
    deltas = {
        state: by_state[state].act_now_minus_retain_drop for state in SCENARIO_STATES
    }
    mixes = (
        (1.0, 0.0, 0.0),
        (0.5, 0.5, 0.0),
        (1 / 3, 1 / 3, 1 / 3),
        (0.5, 0.0, 0.5),
        (0.0, 0.5, 0.5),
        (0.0, 0.0, 1.0),
    )
    sensitivity = tuple(
        ExpectedValueSensitivity(
            hypothetical_miss_probability=round(miss, 6),
            hypothetical_useful_role_probability=round(useful, 6),
            hypothetical_breakout_probability=round(breakout, 6),
            expected_act_now_minus_retain_drop=round(
                miss * deltas["MISS"]
                + useful * deltas["USEFUL_ROLE"]
                + breakout * deltas["BREAKOUT"],
                3,
            ),
        )
        for miss, useful, breakout in mixes
    )
    no_action_best = all(row.act_now_minus_retain_drop <= 0 for row in comparisons)
    no_action = NoActionAlternative(
        weighted_lineup_points=central_retain,
        retained_player_id=drop_player_id,
        central_preferred=central_retain >= central_act_now,
        best_in_every_scenario=no_action_best,
    )
    base = EmergingUpsideValuation(
        schema_version=SCENARIO_OUTPUT_SCHEMA_VERSION,
        status="COMPLETE",
        add_player_id=add_player_id,
        drop_player_id=drop_player_id,
        add_input=add_input,
        drop_input=drop_input,
        add_central_projection_points=add_central_projection,
        drop_central_projection_points=drop_central_projection,
        central_act_now_weighted_points=central_act_now,
        central_retain_drop_weighted_points=central_retain,
        central_delta=round(central_act_now - central_retain, 3),
        scenario_comparisons=tuple(comparisons),
        breakout_gain=breakout_gain,
        useful_role_gain=useful_gain,
        miss_case_loss=miss_loss,
        acquisition_option_ceiling=acquisition_ceiling,
        retained_option_ceiling=retained_ceiling,
        incremental_option_value=round(acquisition_ceiling - retained_ceiling, 3),
        add_miss_protection=_miss_protection(by_state["MISS"].act_now),
        drop_miss_protection=_miss_protection(by_state["MISS"].retain_drop),
        no_action=no_action,
        break_even=break_even,
        expected_value_equation=(
            f"EV(ACT_NOW - RETAIN_DROP) = p_miss*({deltas['MISS']:.3f}) + "
            f"p_useful*({deltas['USEFUL_ROLE']:.3f}) + "
            f"p_breakout*({deltas['BREAKOUT']:.3f}), where probabilities sum to 1"
        ),
        sensitivity=sensitivity,
        named_teammate_contingency_kept_separate=True,
        named_teammate_acquisition_ceiling=named_teammate_acquisition_ceiling,
        named_teammate_retained_ceiling=named_teammate_retained_ceiling,
        strongest_uncertainty=(
            "The sensitivity rows are hypothetical beliefs, not calibrated state, "
            "availability, or claim-success probabilities"
        ),
        valuation_hash="",
    )
    return replace(base, valuation_hash=stable_hash(asdict(base)))
