from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, replace
from datetime import timedelta, timezone
from pathlib import Path

from roster_theory.core.provenance import stable_hash
from roster_theory.waiver.emergence import PlayerEmergenceEvidence
from roster_theory.waiver.evaluation import (
    DropCandidateEvaluation,
    PlayerContingencyEvidence,
    WaiverDecisionAssessment,
    WaiverDecisionGate,
    WaiverEvaluation,
    WaiverEvaluationOptions,
)
from roster_theory.waiver.snapshot import ACQUIRABLE_STATES, AcquisitionState


DEFAULT_WAIVER_CONFIG_DIR = Path("config/waiver")
_SAFE_LEAGUE_KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*")


def default_waiver_policy_path(
    league_key: str,
    *,
    config_dir: str | Path = DEFAULT_WAIVER_CONFIG_DIR,
) -> Path:
    if not _SAFE_LEAGUE_KEY.fullmatch(league_key):
        raise ValueError(f"Invalid Waiver league key: {league_key!r}")
    return Path(config_dir) / f"{league_key}.decision-policy.json"


@dataclass(frozen=True, slots=True)
class WaiverDecisionPolicy:
    schema_version: int
    product: str
    league_key: str
    version: str
    calibration_mode: str
    allow_watch_on_missing_news: bool
    selected_value_floor: float
    market_value_floor: float
    raw_projection_floor: float
    immediate_lineup_gain_floor: float
    insurance_selected_gain_floor: float
    insurance_market_gain_floor: float
    insurance_depth_floor: float
    maximum_current_week_loss: float
    maximum_depth_loss: float
    maximum_downside_increase: float
    watch_selected_value_floor: float
    watch_market_value_floor: float
    watch_raw_projection_floor: float
    watch_lineup_floor: float
    watch_maximum_current_week_loss: float
    watch_maximum_depth_loss: float
    watch_maximum_downside_increase: float
    special_teams_current_week_weight: float
    kicker_current_week_gain_floor: float
    dst_current_week_gain_floor: float
    special_teams_watch_current_week_gain_floor: float
    elite_dst_ros_rank_cutoff: int
    elite_dst_maximum_current_week_loss: float
    elite_dst_weighted_lineup_floor: float
    qb_streaming_stress_rank: int
    qb_starter_decision_margin: float
    qb_net_hold_value_floor: float
    qb_watch_net_hold_value_floor: float
    qb_insurance_advantage_floor: float
    qb_maximum_bench_slot_opportunity_cost: float
    contingency_evidence_max_age_hours: float
    contingency_standalone_selected_value_floor: float
    contingency_standalone_market_value_floor: float
    contingency_material_lineup_ceiling_gain: float
    contingency_acquisition_incremental_value_gate: float
    emerging_ww_support_mode: str
    emerging_market_ww_rank_cutoff: int
    emerging_selected_expert_rank_cutoff: int
    emerging_minimum_selected_expert_support: int
    emerging_maximum_miss_case_loss: float
    emerging_maximum_selected_value_deficit: float
    emerging_maximum_market_value_deficit: float
    emerging_maximum_raw_projection_deficit: float
    emerging_maximum_central_lineup_deficit: float
    emerging_minimum_incremental_option_value: float
    emerging_maximum_break_even_hit_rate: float
    emerging_evidence_max_age_hours: float
    emerging_minimum_role_signal_strength: float
    emerging_maximum_replacement_exposure: float
    emerging_maximum_current_week_loss: float
    emerging_maximum_offense_downside_increase: float
    emerging_near_threshold_fraction: float
    policy_hash: str


def load_waiver_policy(
    path: str | Path,
) -> WaiverDecisionPolicy:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if int(value.get("schema_version") or 0) != 1:
        raise ValueError("Unsupported Waiver decision-policy schema")
    if str(value.get("product") or "") != "WAIVER ASSISTANT":
        raise ValueError("Decision policy must be Waiver-scoped")
    version = str(value.get("version") or "")
    if not version:
        raise ValueError("Waiver decision policy requires a version")
    if str(value.get("calibration_mode") or "") != "CONTROLLED_FIXTURES":
        raise ValueError("Waiver policy must identify controlled-fixture calibration")
    thresholds = value.get("thresholds") or {}
    required = (
        "selected_value_floor",
        "market_value_floor",
        "raw_projection_floor",
        "immediate_lineup_gain_floor",
        "insurance_selected_gain_floor",
        "insurance_market_gain_floor",
        "insurance_depth_floor",
        "maximum_current_week_loss",
        "maximum_depth_loss",
        "maximum_downside_increase",
        "watch_selected_value_floor",
        "watch_market_value_floor",
        "watch_raw_projection_floor",
        "watch_lineup_floor",
        "watch_maximum_current_week_loss",
        "watch_maximum_depth_loss",
        "watch_maximum_downside_increase",
    )
    missing = tuple(name for name in required if name not in thresholds)
    if missing:
        raise ValueError("Waiver decision policy misses threshold(s): " + ", ".join(missing))
    numeric = {name: float(thresholds[name]) for name in required}
    special = value.get("special_teams") or {}
    special_required = (
        "current_week_weight",
        "kicker_current_week_gain_floor",
        "dst_current_week_gain_floor",
        "watch_current_week_gain_floor",
        "elite_dst_ros_rank_cutoff",
        "elite_dst_maximum_current_week_loss",
        "elite_dst_weighted_lineup_floor",
    )
    missing_special = tuple(name for name in special_required if name not in special)
    if missing_special:
        raise ValueError(
            "Waiver decision policy misses special-team setting(s): "
            + ", ".join(missing_special)
        )
    special_numeric = {name: float(special[name]) for name in special_required}
    elite_cutoff = int(special_numeric["elite_dst_ros_rank_cutoff"])
    if special_numeric["current_week_weight"] <= 1:
        raise ValueError("Special-team current-week weight must be above 1")
    if elite_cutoff < 1 or elite_cutoff != special_numeric["elite_dst_ros_rank_cutoff"]:
        raise ValueError("Elite DST cutoff must be a positive integer")
    if special_numeric["elite_dst_maximum_current_week_loss"] < 0:
        raise ValueError("Elite DST current-week loss limit must be nonnegative")
    qb_holding = value.get("qb_holding") or {}
    qb_required = (
        "streaming_stress_rank",
        "starter_decision_margin",
        "net_hold_value_floor",
        "watch_net_hold_value_floor",
        "insurance_advantage_floor",
        "maximum_bench_slot_opportunity_cost",
    )
    missing_qb = tuple(name for name in qb_required if name not in qb_holding)
    if missing_qb:
        raise ValueError(
            "Waiver decision policy misses QB-holding setting(s): "
            + ", ".join(missing_qb)
        )
    qb_numeric = {name: float(qb_holding[name]) for name in qb_required}
    streaming_stress_rank = int(qb_numeric["streaming_stress_rank"])
    if streaming_stress_rank < 1 or streaming_stress_rank != qb_numeric["streaming_stress_rank"]:
        raise ValueError("QB streaming stress rank must be a positive integer")
    if qb_numeric["starter_decision_margin"] < 0:
        raise ValueError("QB starter decision margin must be nonnegative")
    if qb_numeric["watch_net_hold_value_floor"] > qb_numeric["net_hold_value_floor"]:
        raise ValueError("QB WATCH hold-value floor cannot exceed affirmative floor")
    if qb_numeric["insurance_advantage_floor"] < 0:
        raise ValueError("QB insurance advantage floor must be nonnegative")
    if qb_numeric["maximum_bench_slot_opportunity_cost"] < 0:
        raise ValueError("QB bench-slot cost limit must be nonnegative")
    contingency = value.get("contingent_upside") or {}
    contingency_required = (
        "evidence_max_age_hours",
        "standalone_selected_value_floor",
        "standalone_market_value_floor",
        "material_lineup_ceiling_gain",
        "acquisition_incremental_value_gate",
    )
    missing_contingency = tuple(
        name for name in contingency_required if name not in contingency
    )
    if missing_contingency:
        raise ValueError(
            "Waiver decision policy misses contingent-upside setting(s): "
            + ", ".join(missing_contingency)
        )
    contingency_numeric = {
        name: float(contingency[name]) for name in contingency_required
    }
    if contingency_numeric["evidence_max_age_hours"] <= 0:
        raise ValueError("Contingency evidence freshness window must be positive")
    if any(
        contingency_numeric[name] < 0
        for name in (
            "standalone_selected_value_floor",
            "standalone_market_value_floor",
            "material_lineup_ceiling_gain",
            "acquisition_incremental_value_gate",
        )
    ):
        raise ValueError("Contingent-upside value and ceiling thresholds must be nonnegative")
    emerging = value.get("emerging_upside") or {}
    emerging_required = (
        "ww_support_mode",
        "market_ww_rank_cutoff",
        "selected_expert_rank_cutoff",
        "minimum_selected_expert_support",
        "maximum_miss_case_loss",
        "maximum_selected_value_deficit",
        "maximum_market_value_deficit",
        "maximum_raw_projection_deficit",
        "maximum_central_lineup_deficit",
        "minimum_incremental_option_value",
        "maximum_break_even_hit_rate",
        "evidence_max_age_hours",
        "minimum_role_signal_strength",
        "maximum_replacement_exposure",
        "maximum_current_week_loss",
        "maximum_offense_downside_increase",
        "near_threshold_fraction",
    )
    missing_emerging = tuple(
        name for name in emerging_required if name not in emerging
    )
    if missing_emerging:
        raise ValueError(
            "Waiver decision policy misses emerging-upside setting(s): "
            + ", ".join(missing_emerging)
        )
    support_mode = str(emerging["ww_support_mode"])
    if support_mode not in {"MARKET_ONLY", "SELECTED_ONLY", "MARKET_OR_SELECTED", "MARKET_AND_SELECTED"}:
        raise ValueError("Unsupported emerging-upside Waiver Wire support mode")
    market_rank_cutoff = int(emerging["market_ww_rank_cutoff"])
    selected_rank_cutoff = int(emerging["selected_expert_rank_cutoff"])
    selected_support = int(emerging["minimum_selected_expert_support"])
    if min(market_rank_cutoff, selected_rank_cutoff, selected_support) < 1:
        raise ValueError("Emerging-upside rank cutoffs and support count must be positive")
    if any(
        parsed != float(emerging[name])
        for name, parsed in (
            ("market_ww_rank_cutoff", market_rank_cutoff),
            ("selected_expert_rank_cutoff", selected_rank_cutoff),
            ("minimum_selected_expert_support", selected_support),
        )
    ):
        raise ValueError("Emerging-upside rank cutoffs and support count must be integers")
    emerging_numeric_names = tuple(
        name
        for name in emerging_required
        if name
        not in {
            "ww_support_mode",
            "market_ww_rank_cutoff",
            "selected_expert_rank_cutoff",
            "minimum_selected_expert_support",
        }
    )
    emerging_numeric = {
        name: float(emerging[name]) for name in emerging_numeric_names
    }
    if any(value < 0 for value in emerging_numeric.values()):
        raise ValueError("Emerging-upside thresholds must be nonnegative")
    if emerging_numeric["evidence_max_age_hours"] <= 0:
        raise ValueError("Emerging-upside evidence freshness must be positive")
    if not 0 <= emerging_numeric["maximum_break_even_hit_rate"] <= 1:
        raise ValueError("Emerging-upside break-even limit must be between zero and one")
    if not 0 <= emerging_numeric["near_threshold_fraction"] < 1:
        raise ValueError("Emerging-upside near-threshold fraction must be below one")
    nonnegative = (
        "maximum_current_week_loss",
        "maximum_depth_loss",
        "maximum_downside_increase",
        "watch_maximum_current_week_loss",
        "watch_maximum_depth_loss",
        "watch_maximum_downside_increase",
    )
    if any(numeric[name] < 0 for name in nonnegative):
        raise ValueError("Waiver loss and risk limits must be nonnegative")
    if numeric["watch_selected_value_floor"] > numeric["selected_value_floor"]:
        raise ValueError("Waiver WATCH selected-value floor cannot exceed affirmative floor")
    if numeric["watch_market_value_floor"] > numeric["market_value_floor"]:
        raise ValueError("Waiver WATCH market floor cannot exceed affirmative floor")
    if numeric["watch_raw_projection_floor"] > numeric["raw_projection_floor"]:
        raise ValueError("Waiver WATCH projection floor cannot exceed affirmative floor")
    if numeric["watch_lineup_floor"] > numeric["immediate_lineup_gain_floor"]:
        raise ValueError("Waiver WATCH lineup floor cannot exceed immediate floor")
    if (
        numeric["watch_maximum_current_week_loss"]
        < numeric["maximum_current_week_loss"]
    ):
        raise ValueError("Waiver WATCH current-week tolerance cannot be narrower")
    if numeric["watch_maximum_depth_loss"] < numeric["maximum_depth_loss"]:
        raise ValueError("Waiver WATCH depth tolerance cannot be narrower than affirmative")
    if numeric["watch_maximum_downside_increase"] < numeric["maximum_downside_increase"]:
        raise ValueError("Waiver WATCH risk tolerance cannot be narrower than affirmative")
    return WaiverDecisionPolicy(
        schema_version=1,
        product="WAIVER ASSISTANT",
        league_key=str(value.get("league_key") or ""),
        version=version,
        calibration_mode="CONTROLLED_FIXTURES",
        allow_watch_on_missing_news=bool(value.get("allow_watch_on_missing_news")),
        special_teams_current_week_weight=special_numeric["current_week_weight"],
        kicker_current_week_gain_floor=special_numeric[
            "kicker_current_week_gain_floor"
        ],
        dst_current_week_gain_floor=special_numeric["dst_current_week_gain_floor"],
        special_teams_watch_current_week_gain_floor=special_numeric[
            "watch_current_week_gain_floor"
        ],
        elite_dst_ros_rank_cutoff=elite_cutoff,
        elite_dst_maximum_current_week_loss=special_numeric[
            "elite_dst_maximum_current_week_loss"
        ],
        elite_dst_weighted_lineup_floor=special_numeric[
            "elite_dst_weighted_lineup_floor"
        ],
        qb_streaming_stress_rank=streaming_stress_rank,
        qb_starter_decision_margin=qb_numeric["starter_decision_margin"],
        qb_net_hold_value_floor=qb_numeric["net_hold_value_floor"],
        qb_watch_net_hold_value_floor=qb_numeric["watch_net_hold_value_floor"],
        qb_insurance_advantage_floor=qb_numeric["insurance_advantage_floor"],
        qb_maximum_bench_slot_opportunity_cost=qb_numeric[
            "maximum_bench_slot_opportunity_cost"
        ],
        contingency_evidence_max_age_hours=contingency_numeric[
            "evidence_max_age_hours"
        ],
        contingency_standalone_selected_value_floor=contingency_numeric[
            "standalone_selected_value_floor"
        ],
        contingency_standalone_market_value_floor=contingency_numeric[
            "standalone_market_value_floor"
        ],
        contingency_material_lineup_ceiling_gain=contingency_numeric[
            "material_lineup_ceiling_gain"
        ],
        contingency_acquisition_incremental_value_gate=contingency_numeric[
            "acquisition_incremental_value_gate"
        ],
        emerging_ww_support_mode=support_mode,
        emerging_market_ww_rank_cutoff=market_rank_cutoff,
        emerging_selected_expert_rank_cutoff=selected_rank_cutoff,
        emerging_minimum_selected_expert_support=selected_support,
        emerging_maximum_miss_case_loss=emerging_numeric[
            "maximum_miss_case_loss"
        ],
        emerging_maximum_selected_value_deficit=emerging_numeric[
            "maximum_selected_value_deficit"
        ],
        emerging_maximum_market_value_deficit=emerging_numeric[
            "maximum_market_value_deficit"
        ],
        emerging_maximum_raw_projection_deficit=emerging_numeric[
            "maximum_raw_projection_deficit"
        ],
        emerging_maximum_central_lineup_deficit=emerging_numeric[
            "maximum_central_lineup_deficit"
        ],
        emerging_minimum_incremental_option_value=emerging_numeric[
            "minimum_incremental_option_value"
        ],
        emerging_maximum_break_even_hit_rate=emerging_numeric[
            "maximum_break_even_hit_rate"
        ],
        emerging_evidence_max_age_hours=emerging_numeric[
            "evidence_max_age_hours"
        ],
        emerging_minimum_role_signal_strength=emerging_numeric[
            "minimum_role_signal_strength"
        ],
        emerging_maximum_replacement_exposure=emerging_numeric[
            "maximum_replacement_exposure"
        ],
        emerging_maximum_current_week_loss=emerging_numeric[
            "maximum_current_week_loss"
        ],
        emerging_maximum_offense_downside_increase=emerging_numeric[
            "maximum_offense_downside_increase"
        ],
        emerging_near_threshold_fraction=emerging_numeric[
            "near_threshold_fraction"
        ],
        policy_hash=stable_hash(value),
        **numeric,
    )


def evaluation_options_for_policy(
    policy: WaiverDecisionPolicy,
    base: WaiverEvaluationOptions = WaiverEvaluationOptions(),
) -> WaiverEvaluationOptions:
    return replace(
        base,
        qb_streaming_stress_rank=policy.qb_streaming_stress_rank,
        starter_decision_margin=policy.qb_starter_decision_margin,
        contingency_evidence_max_age_hours=policy.contingency_evidence_max_age_hours,
    )


def _apply_contingency_policy(
    candidate: DropCandidateEvaluation,
    policy: WaiverDecisionPolicy,
) -> DropCandidateEvaluation:
    evidence = candidate.contingency

    def is_bench_option(
        player_evidence: PlayerContingencyEvidence | None,
        selected: float,
        market: float,
    ) -> bool:
        if player_evidence is None or not player_evidence.current_authoritative:
            return False
        current = next(
            (row for row in player_evidence.weekly_impacts if row.week == candidate.lineup.weeks[0].week),
            None,
        )
        is_bench = current is not None and player_evidence.player_id not in current.standalone_starters
        return (
            is_bench
            and selected >= policy.contingency_standalone_selected_value_floor
            and market >= policy.contingency_standalone_market_value_floor
            and player_evidence.lineup_ceiling_gain
            >= policy.contingency_material_lineup_ceiling_gain
        )

    add_protected = is_bench_option(
        evidence.add,
        candidate.ownership.selected_add,
        candidate.ownership.market_add,
    )
    drop_protected = is_bench_option(
        evidence.drop,
        candidate.ownership.selected_drop,
        candidate.ownership.market_drop,
    )
    gate_passed = (
        not drop_protected
        or evidence.incremental_option_value
        >= policy.contingency_acquisition_incremental_value_gate
    )
    if drop_protected and gate_passed:
        reason = "Acquisition option ceiling clears the protected bench option"
    elif drop_protected:
        reason = "Drop is a protected standalone-plus-contingency bench option"
    elif add_protected:
        reason = "Acquisition qualifies as a protected standalone-plus-contingency bench option"
    else:
        reason = "No player in this add/drop pair qualifies for protected-upside state"
    return replace(
        candidate,
        contingency=replace(
            evidence,
            add_protected=add_protected,
            drop_protected=drop_protected,
            required_incremental_value=(
                policy.contingency_acquisition_incremental_value_gate
                if drop_protected
                else 0.0
            ),
            incremental_gate_passed=gate_passed,
            protection_reason=reason,
        ),
    )


def _gate(
    name: str,
    actual: float | bool,
    comparison: str,
    threshold: float | bool,
    passed: bool,
    explanation: str,
) -> WaiverDecisionGate:
    return WaiverDecisionGate(name, actual, comparison, threshold, passed, explanation)


_ROLE_SIGNAL_SCALES = {
    "offensive_snap_share": 0.15,
    "route_participation": 0.15,
    "target_share": 0.05,
    "targets": 3.0,
    "carries": 4.0,
    "total_opportunities": 5.0,
    "designed_touches": 3.0,
}


def emerging_role_signal_strength(player: PlayerEmergenceEvidence) -> float:
    """Return a dimensionless multiple of the WA-013 role-change floor."""

    strengths = tuple(
        max(0.0, float(row.delta_from_baseline)) / _ROLE_SIGNAL_SCALES[row.metric]
        for row in player.comparisons
        if row.metric in _ROLE_SIGNAL_SCALES
        and row.delta_from_baseline is not None
    )
    return round(max(strengths, default=0.0), 3)


def _ww_support(
    evaluation: WaiverEvaluation,
    selected: DropCandidateEvaluation,
    policy: WaiverDecisionPolicy,
) -> tuple[bool, bool, int, int, bool]:
    market_rank = selected.ownership.waiver_wire_market_add_rank
    market_support = (
        market_rank is not None
        and market_rank <= policy.emerging_market_ww_rank_cutoff
    )
    expert_ranks = tuple(
        row.overall_rank
        for row in selected.ownership.waiver_wire_selected_add_ranks
        if row.overall_rank is not None
    )
    selected_support_count = sum(
        rank <= policy.emerging_selected_expert_rank_cutoff
        for rank in expert_ranks
    )
    selected_support = (
        selected_support_count >= policy.emerging_minimum_selected_expert_support
    )
    mode = policy.emerging_ww_support_mode
    combined = {
        "MARKET_ONLY": market_support,
        "SELECTED_ONLY": selected_support,
        "MARKET_OR_SELECTED": market_support or selected_support,
        "MARKET_AND_SELECTED": market_support and selected_support,
    }[mode]
    disagreement = bool(
        expert_ranks
        and (
            (
                selected_support_count
                and selected_support_count != len(expert_ranks)
            )
            or market_support != selected_support
        )
    )
    return (
        combined,
        market_support,
        selected_support_count,
        len(expert_ranks),
        disagreement,
    )


def _emerging_policy_assessment(
    evaluation: WaiverEvaluation,
    selected: DropCandidateEvaluation,
    policy: WaiverDecisionPolicy,
) -> tuple[
    tuple[WaiverDecisionGate, ...],
    bool,
    bool,
    float,
    str,
    tuple[str, ...],
    bool,
]:
    emergence = evaluation.emergence_evidence
    matches = tuple(
        row
        for row in (emergence.players if emergence is not None else ())
        if row.player_id == evaluation.add_player_id
    )
    player = matches[0] if len(matches) == 1 else None
    role_strength = emerging_role_signal_strength(player) if player else 0.0
    upside = selected.emerging_upside
    ww = evaluation.waiver_wire_evidence
    combined_ww, market_support, expert_support, expert_count, disagreement = (
        _ww_support(evaluation, selected, policy)
    )
    evidence_age_limit = timedelta(hours=policy.emerging_evidence_max_age_hours)
    ww_age = (
        evaluation.evaluated_at - ww.captured_at.astimezone(timezone.utc)
        if ww is not None
        else None
    )
    role_age = (
        evaluation.evaluated_at - emergence.captured_at.astimezone(timezone.utc)
        if emergence is not None
        else None
    )
    ww_fresh = bool(
        ww_age is not None
        and timedelta(0) <= ww_age <= evidence_age_limit
    )
    role_fresh = bool(
        role_age is not None
        and timedelta(0) <= role_age <= evidence_age_limit
    )
    role_complete = bool(
        player is not None
        and player.identity_status == "MATCHED"
        and player.coverage_status == "COMPLETE"
        and player.classification in {"ROLE_EXPANSION", "SUPPORTED_TREND"}
        and player.affirmative_eligible
    )
    evidence_complete = bool(
        evaluation.material_news_fresh
        and evaluation.value_inputs_complete
        and evaluation.projection_inputs_complete
        and ww is not None
        and ww.complete
        and ww_fresh
        and emergence is not None
        and role_complete
        and role_fresh
        and upside.status == "COMPLETE"
    )
    break_even_rate = upside.break_even.hit_rate
    break_even_pass = bool(
        upside.status == "COMPLETE"
        and break_even_rate is not None
        and break_even_rate <= policy.emerging_maximum_break_even_hit_rate
    )
    replacement_exposure = max(
        (
            row.act_now.replacement_exposure
            for row in upside.scenario_comparisons
        ),
        default=0.0,
    )
    gates = (
        _gate(
            "emerging_complete_fresh_evidence",
            evidence_complete,
            "==",
            True,
            evidence_complete,
            "Fresh genuine Waiver Wire, role, scenario, ranking, projection, and material-news evidence is required",
        ),
        _gate(
            "player_currently_active",
            evaluation.add_currently_active,
            "==",
            True,
            evaluation.add_currently_active,
            "A currently inactive target cannot receive an affirmative label",
        ),
        _gate(
            "emerging_role_signal_strength",
            role_strength,
            ">=",
            policy.emerging_minimum_role_signal_strength,
            role_complete
            and role_strength >= policy.emerging_minimum_role_signal_strength,
            "Opportunity growth must meet the league-local role-signal floor; fantasy points alone do not count",
        ),
        _gate(
            "waiver_wire_support",
            combined_ww,
            policy.emerging_ww_support_mode,
            True,
            combined_ww,
            (
                f"Market support={market_support}; selected-expert support="
                f"{expert_support}/{expert_count}; mode={policy.emerging_ww_support_mode}"
            ),
        ),
        _gate(
            "emerging_selected_value_deficit",
            selected.ownership.selected_delta,
            ">=",
            -policy.emerging_maximum_selected_value_deficit,
            selected.ownership.selected_delta
            >= -policy.emerging_maximum_selected_value_deficit,
            "Emerging upside may tolerate only the configured selected-value deficit",
        ),
        _gate(
            "emerging_market_value_deficit",
            selected.ownership.market_delta,
            ">=",
            -policy.emerging_maximum_market_value_deficit,
            selected.ownership.market_delta
            >= -policy.emerging_maximum_market_value_deficit,
            "Emerging upside may tolerate only the configured market-value deficit",
        ),
        _gate(
            "emerging_raw_projection_deficit",
            selected.ownership.raw_projection_delta,
            ">=",
            -policy.emerging_maximum_raw_projection_deficit,
            selected.ownership.raw_projection_delta
            >= -policy.emerging_maximum_raw_projection_deficit,
            "Emerging upside may tolerate only the configured central projection deficit",
        ),
        _gate(
            "emerging_central_lineup_deficit",
            selected.lineup.weighted_delta,
            ">=",
            -policy.emerging_maximum_central_lineup_deficit,
            selected.lineup.weighted_delta
            >= -policy.emerging_maximum_central_lineup_deficit,
            "The central optimized roster cannot fall beyond the league-local deficit limit",
        ),
        _gate(
            "emerging_miss_case_loss",
            upside.miss_case_loss,
            "<=",
            policy.emerging_maximum_miss_case_loss,
            upside.status == "COMPLETE"
            and upside.miss_case_loss <= policy.emerging_maximum_miss_case_loss,
            "The modeled miss cost must remain explicitly bounded",
        ),
        _gate(
            "emerging_incremental_option_value",
            upside.incremental_option_value,
            ">=",
            policy.emerging_minimum_incremental_option_value,
            upside.status == "COMPLETE"
            and upside.incremental_option_value
            >= policy.emerging_minimum_incremental_option_value,
            "The acquisition ceiling must clear the retained drop's symmetric option ceiling",
        ),
        _gate(
            "emerging_break_even_hit_rate",
            break_even_rate if break_even_rate is not None else -1.0,
            "<=",
            policy.emerging_maximum_break_even_hit_rate,
            break_even_pass,
            "The required breakout belief must not exceed the league-local break-even limit",
        ),
        _gate(
            "emerging_current_week_loss",
            selected.current_week_delta,
            ">=",
            -policy.emerging_maximum_current_week_loss,
            selected.current_week_delta >= -policy.emerging_maximum_current_week_loss,
            "An early bet cannot create an excessive current-week loss",
        ),
        _gate(
            "emerging_replacement_exposure",
            replacement_exposure,
            "<=",
            policy.emerging_maximum_replacement_exposure,
            replacement_exposure <= policy.emerging_maximum_replacement_exposure,
            "Scenario depth loss and replacement exposure must stay bounded",
        ),
        _gate(
            "emerging_offense_downside_increase",
            selected.risk.offense_downside_loss_delta,
            "<=",
            policy.emerging_maximum_offense_downside_increase,
            selected.risk.offense_downside_loss_delta
            <= policy.emerging_maximum_offense_downside_increase,
            "The move cannot add excessive same-offense downside",
        ),
        _gate(
            "protected_contingency_drop",
            selected.contingency.incremental_gate_passed,
            "==",
            True,
            selected.contingency.incremental_gate_passed,
            "A protected named-teammate contingency drop must clear its separate gate",
        ),
    )
    affirmative = all(gate.passed for gate in gates)
    margin = policy.emerging_near_threshold_fraction
    role_potential = bool(
        player is not None
        and player.classification != "EFFICIENCY_ONLY"
        and role_strength
        >= policy.emerging_minimum_role_signal_strength * (1 - margin)
    )
    ww_potential = bool(
        combined_ww
        or market_support
        or expert_support > 0
        or ww is None
        or not ww.complete
    )
    central_near = all(
        (
            selected.ownership.selected_delta
            >= -policy.emerging_maximum_selected_value_deficit * (1 + margin),
            selected.ownership.market_delta
            >= -policy.emerging_maximum_market_value_deficit * (1 + margin),
            selected.ownership.raw_projection_delta
            >= -policy.emerging_maximum_raw_projection_deficit * (1 + margin),
            selected.lineup.weighted_delta
            >= -policy.emerging_maximum_central_lineup_deficit * (1 + margin),
            selected.current_week_delta
            >= -policy.emerging_maximum_current_week_loss * (1 + margin),
            selected.risk.offense_downside_loss_delta
            <= policy.emerging_maximum_offense_downside_increase * (1 + margin),
            selected.contingency.incremental_gate_passed,
        )
    )
    scenario_near = (
        True
        if upside.status != "COMPLETE"
        else all(
            (
                upside.miss_case_loss
                <= policy.emerging_maximum_miss_case_loss * (1 + margin),
                upside.incremental_option_value
                >= policy.emerging_minimum_incremental_option_value * (1 - margin),
                replacement_exposure
                <= policy.emerging_maximum_replacement_exposure * (1 + margin),
                break_even_rate is not None
                and break_even_rate
                <= policy.emerging_maximum_break_even_hit_rate * (1 + margin),
            )
        )
    )
    watch = bool(
        not affirmative
        and evaluation.add_currently_active
        and evaluation.value_inputs_complete
        and evaluation.projection_inputs_complete
        and role_potential
        and ww_potential
        and central_near
        and scenario_near
    )
    first_failed = next((gate for gate in gates if not gate.passed), None)
    uncertainty = (
        first_failed.explanation
        if first_failed is not None
        else upside.strongest_uncertainty
    )
    priority = round(
        upside.incremental_option_value - max(0.0, upside.miss_case_loss), 3
    )
    reversal_conditions = (
        f"Market Waiver Wire rank falls below support cutoff {policy.emerging_market_ww_rank_cutoff}",
        f"Selected-expert support falls below {policy.emerging_minimum_selected_expert_support} rank(s) inside {policy.emerging_selected_expert_rank_cutoff}",
        f"Role-signal strength falls below {policy.emerging_minimum_role_signal_strength:.2f}",
        f"Miss-case loss exceeds {policy.emerging_maximum_miss_case_loss:.1f}",
        f"Incremental option value falls below {policy.emerging_minimum_incremental_option_value:+.1f}",
        f"Break-even hit rate exceeds {policy.emerging_maximum_break_even_hit_rate:.1%}",
        "The retained drop gains a comparable or superior emergence or named-contingency ceiling",
        f"Waiver Wire or role evidence exceeds {policy.emerging_evidence_max_age_hours:.0f} hours",
    )
    return (
        gates,
        affirmative,
        watch,
        priority,
        uncertainty,
        reversal_conditions,
        disagreement,
    )


def _assess_candidate(
    evaluation: WaiverEvaluation,
    selected: DropCandidateEvaluation,
    policy: WaiverDecisionPolicy,
) -> tuple[WaiverDecisionAssessment, str]:
    if evaluation.add_position in {"K", "DST"}:
        return _assess_special_team_candidate(evaluation, selected, policy)
    ownership = selected.ownership
    holding = selected.holding
    contingency = selected.contingency
    rank_dominance = ownership.fresh_rank_dominance
    immediate_case = (
        selected.lineup.weighted_delta >= policy.immediate_lineup_gain_floor
    )
    insurance_case = (
        ownership.selected_delta >= policy.insurance_selected_gain_floor
        and ownership.market_delta >= policy.insurance_market_gain_floor
        and selected.lineup.depth_delta >= policy.insurance_depth_floor
    )
    hold_net_case = (
        holding.applicable
        and holding.net_hold_value >= policy.qb_net_hold_value_floor
    )
    hold_insurance_case = (
        holding.applicable
        and holding.injury_insurance_value >= policy.qb_insurance_advantage_floor
        and holding.bench_slot_opportunity_cost
        <= policy.qb_maximum_bench_slot_opportunity_cost
    )
    support_case = (
        hold_net_case or hold_insurance_case
        if holding.applicable
        else (
            immediate_case
            or insurance_case
            or contingency.add_protected
            or rank_dominance
        )
    )
    raw_projection_pass = (
        holding.applicable
        or ownership.raw_projection_delta >= policy.raw_projection_floor
    )
    depth_pass = (
        holding.applicable
        or selected.lineup.depth_delta >= -policy.maximum_depth_loss
    )
    evidence_complete = (
        evaluation.material_news_fresh
        and evaluation.value_inputs_complete
        and evaluation.projection_inputs_complete
        and (not holding.applicable or not holding.streaming_omission_ids)
    )
    gates = (
        _gate(
            "complete_required_evidence",
            evidence_complete,
            "==",
            True,
            evidence_complete,
            "Ranks, projections, material-news freshness, and any one-QB streamer pool must be complete",
        ),
        _gate(
            "player_currently_active",
            evaluation.add_currently_active,
            "==",
            True,
            evaluation.add_currently_active,
            "A currently inactive target cannot receive an affirmative label",
        ),
        _gate(
            "selected_ownership_delta",
            ownership.selected_delta,
            ">=",
            policy.selected_value_floor,
            ownership.selected_delta >= policy.selected_value_floor or rank_dominance,
            (
                "Fresh same-position weekly rank, ROS rank, and remaining projection "
                "may override a common non-ROS ownership-value horizon"
                if rank_dominance
                else "The add minus drop must not lose selected-expert ownership value"
            ),
        ),
        _gate(
            "market_ownership_delta",
            ownership.market_delta,
            ">=",
            policy.market_value_floor,
            ownership.market_delta >= policy.market_value_floor or rank_dominance,
            (
                "Fresh same-position weekly rank, ROS rank, and remaining projection "
                "may override a common non-ROS ownership-value horizon"
                if rank_dominance
                else "The add minus drop must not lose market-consensus ownership value"
            ),
        ),
        _gate(
            "raw_projection_delta",
            ownership.raw_projection_delta,
            ">=",
            policy.raw_projection_floor,
            raw_projection_pass,
            (
                "Raw QB-versus-drop points are reported but are not a one-QB hold gate"
                if holding.applicable
                else "Raw remaining-horizon projection must independently support the move"
            ),
        ),
        _gate(
            "immediate_insurance_or_qb_hold_value",
            support_case,
            "==",
            True,
            support_case,
            (
                "A one-QB backup needs positive net hold value or materially superior injury insurance"
                if holding.applicable
                else "The move needs a lineup gain or a separately strong bench-insurance case"
            ),
        ),
        _gate(
            "current_week_delta",
            selected.current_week_delta,
            ">=",
            -policy.maximum_current_week_loss,
            selected.current_week_delta >= -policy.maximum_current_week_loss,
            "A future-facing add cannot create an excessive current-week loss",
        ),
        _gate(
            "depth_delta",
            selected.lineup.depth_delta,
            ">=",
            -policy.maximum_depth_loss,
            depth_pass,
            (
                "One-QB hold replacement exposure is charged as bench-slot opportunity cost"
                if holding.applicable
                else "The required drop cannot create excessive replacement exposure"
            ),
        ),
        _gate(
            "offense_downside_increase",
            selected.risk.offense_downside_loss_delta,
            "<=",
            policy.maximum_downside_increase,
            selected.risk.offense_downside_loss_delta <= policy.maximum_downside_increase,
            "The move cannot add excessive same-offense downside",
        ),
        _gate(
            "protected_upside_incremental_value",
            contingency.incremental_option_value,
            ">=",
            contingency.required_incremental_value,
            contingency.incremental_gate_passed,
            (
                "Dropping a protected bench option requires the acquisition option ceiling to clear the explicit incremental-value gate"
                if contingency.drop_protected
                else "No protected contingent-upside drop gate applies"
            ),
        ),
    )
    affirmative = all(gate.passed for gate in gates)
    holding_watch_plausible = (
        holding.net_hold_value >= policy.qb_watch_net_hold_value_floor
        if holding.applicable
        else True
    )
    watch_plausible = (
        (ownership.selected_delta >= policy.watch_selected_value_floor or rank_dominance)
        and (ownership.market_delta >= policy.watch_market_value_floor or rank_dominance)
        and (
            holding.applicable
            or ownership.raw_projection_delta >= policy.watch_raw_projection_floor
        )
        and (
            holding.applicable
            or selected.lineup.weighted_delta >= policy.watch_lineup_floor
        )
        and holding_watch_plausible
        and contingency.incremental_gate_passed
        and selected.current_week_delta >= -policy.watch_maximum_current_week_loss
        and selected.lineup.depth_delta >= -policy.watch_maximum_depth_loss
        and selected.risk.offense_downside_loss_delta
        <= policy.watch_maximum_downside_increase
        and (
            rank_dominance
            or ownership.selected_delta >= 0
            or ownership.market_delta >= 0
            or selected.lineup.weighted_delta >= 0
            or selected.lineup.depth_delta >= 0
        )
    )
    emerging_present = bool(
        evaluation.emergence_evidence is not None
        and any(
            row.player_id == evaluation.add_player_id
            for row in evaluation.emergence_evidence.players
        )
    )
    (
        emerging_gates,
        emerging_affirmative,
        emerging_watch,
        emerging_priority,
        emerging_uncertainty,
        emerging_reversals,
        expert_disagreement,
    ) = _emerging_policy_assessment(evaluation, selected, policy)
    if affirmative:
        if evaluation.acquisition_state == AcquisitionState.FREE_AGENT.value:
            label = "ADD NOW"
        elif evaluation.acquisition_state == AcquisitionState.WAIVERS.value:
            label = "CLAIM"
        else:
            label = "ACQUIRE"
        if holding.applicable:
            decision_path = "QB_HOLD" if hold_net_case else "QB_INJURY_INSURANCE"
        elif contingency.add_protected:
            decision_path = "CONTINGENT_UPSIDE"
        elif rank_dominance:
            decision_path = "FRESH_RANK_DOMINANCE"
        else:
            decision_path = "IMMEDIATE" if immediate_case else "INSURANCE"
        strongest_uncertainty = (
            contingency.strongest_uncertainty
            if contingency.add_protected or contingency.drop_protected
            else (
                "The ownership-value model still uses a non-ROS horizon; the move "
                "depends on fresh weekly rank, ROS consensus, and projection dominance"
                if rank_dominance
                else "Policy thresholds are controlled-fixture calibrated, not validated "
                "against historical waiver outcomes"
            )
        )
        decision_gates = gates
        decision_reversals = None
        decision_priority = (
            round(holding.net_hold_value, 3)
            if holding.applicable
            else (
                ownership.raw_projection_delta
                if rank_dominance
                else selected.lineup.weighted_delta
            )
        )
    elif emerging_affirmative:
        if evaluation.acquisition_state == AcquisitionState.FREE_AGENT.value:
            label = "ADD NOW"
        elif evaluation.acquisition_state == AcquisitionState.WAIVERS.value:
            label = "CLAIM"
        else:
            label = "ACQUIRE"
        decision_path = "EMERGING_UPSIDE"
        strongest_uncertainty = (
            "Selected trusted experts disagree on whether the player clears the "
            "Waiver Wire support cutoff"
            if expert_disagreement
            else selected.emerging_upside.strongest_uncertainty
        )
        decision_gates = emerging_gates
        decision_reversals = emerging_reversals
        decision_priority = emerging_priority
    elif emerging_present and emerging_watch:
        label = "WATCH"
        decision_path = "EMERGING_UPSIDE_INCOMPLETE_OR_NEAR_THRESHOLD"
        strongest_uncertainty = emerging_uncertainty
        decision_gates = emerging_gates
        decision_reversals = emerging_reversals
        decision_priority = emerging_priority
    elif (
        emerging_present
        and selected.emerging_upside.status == "COMPLETE"
        and selected.emerging_upside.incremental_option_value <= 0
    ):
        label = "PASS"
        decision_path = "EMERGING_UPSIDE_RETAINED_DROP_PROTECTED"
        strongest_uncertainty = (
            "The retained drop has a comparable or superior symmetric option ceiling"
        )
        decision_gates = emerging_gates
        decision_reversals = emerging_reversals
        decision_priority = emerging_priority
    elif watch_plausible and (
        evidence_complete or policy.allow_watch_on_missing_news
    ):
        label = "WATCH"
        decision_path = "INCOMPLETE_OR_NEAR_THRESHOLD"
        first_failed = next(gate for gate in gates if not gate.passed)
        strongest_uncertainty = first_failed.explanation
        decision_gates = gates
        decision_reversals = None
        decision_priority = (
            round(holding.net_hold_value, 3)
            if holding.applicable
            else selected.lineup.weighted_delta
        )
    else:
        label = "PASS"
        if emerging_present:
            decision_path = "EMERGING_UPSIDE_VALUE_OR_SAFETY_FAILURE"
            strongest_uncertainty = emerging_uncertainty
            decision_gates = emerging_gates
            decision_reversals = emerging_reversals
            decision_priority = emerging_priority
        else:
            decision_path = "VALUE_OR_SAFETY_FAILURE"
            first_failed = next(gate for gate in gates if not gate.passed)
            strongest_uncertainty = first_failed.explanation
            decision_gates = gates
            decision_reversals = None
            decision_priority = (
                round(holding.net_hold_value, 3)
                if holding.applicable
                else selected.lineup.weighted_delta
            )
    ordinary_reversal_conditions = (
        (
            f"Net one-QB hold value falls below {policy.qb_net_hold_value_floor:+.1f} and "
            f"injury-insurance advantage falls below {policy.qb_insurance_advantage_floor:.1f}"
            if holding.applicable
            else f"Raw projection delta below {policy.raw_projection_floor:+.1f}"
        ),
        f"Selected ownership delta below {policy.selected_value_floor:+.1f}",
        f"Market ownership delta below {policy.market_value_floor:+.1f}",
        f"Current-week loss exceeds {policy.maximum_current_week_loss:.1f}",
        f"Offense-downside increase exceeds {policy.maximum_downside_increase:.1f}",
        "Material-news freshness becomes unproved",
        "The added player becomes currently inactive",
        (
            f"Protected-upside incremental option value falls below "
            f"{policy.contingency_acquisition_incremental_value_gate:+.1f}"
        ),
    )
    if rank_dominance:
        ordinary_reversal_conditions = (
            "Added player no longer outranks the drop for the current week",
            "Added player no longer outranks the drop in current ROS consensus",
            "Remaining league-scored projection delta falls below +0.0",
            "Ownership values transition to a current ROS horizon",
            *ordinary_reversal_conditions[3:],
        )
    decision = WaiverDecisionAssessment(
        label=label,
        decision_path=decision_path,
        policy_version=policy.version,
        policy_hash=policy.policy_hash,
        calibration_mode=policy.calibration_mode,
        priority_score=decision_priority,
        elite_dst_exception=False,
        gates=decision_gates,
        reversal_conditions=(
            decision_reversals
            if decision_reversals is not None
            else ordinary_reversal_conditions
        ),
    )
    return decision, strongest_uncertainty


def _assess_special_team_candidate(
    evaluation: WaiverEvaluation,
    selected: DropCandidateEvaluation,
    policy: WaiverDecisionPolicy,
) -> tuple[WaiverDecisionAssessment, str]:
    ownership = selected.ownership
    weekly_rank_complete = (
        ownership.current_week_add_rank is not None
        and ownership.current_week_add_rank >= 1
    )
    evidence_complete = (
        evaluation.material_news_fresh
        and evaluation.value_inputs_complete
        and evaluation.projection_inputs_complete
        and weekly_rank_complete
    )
    elite = (
        evaluation.add_position == "DST"
        and ownership.rest_of_season_add_rank is not None
        and ownership.rest_of_season_add_rank >= 1
        and ownership.rest_of_season_add_rank <= policy.elite_dst_ros_rank_cutoff
    )
    stream_floor = (
        policy.kicker_current_week_gain_floor
        if evaluation.add_position == "K"
        else policy.dst_current_week_gain_floor
    )
    stream_pass = selected.current_week_delta >= stream_floor
    elite_pass = (
        elite
        and selected.current_week_delta >= -policy.elite_dst_maximum_current_week_loss
        and selected.lineup.weighted_delta >= policy.elite_dst_weighted_lineup_floor
    )
    gates = (
        _gate(
            "complete_special_team_evidence",
            evidence_complete,
            "==",
            True,
            evidence_complete,
            "Weekly rank, league-scored projections, value coverage, and material news must be complete",
        ),
        _gate(
            "player_currently_active",
            evaluation.add_currently_active,
            "==",
            True,
            evaluation.add_currently_active,
            "A currently inactive target cannot receive an affirmative label",
        ),
        _gate(
            "current_week_stream_or_elite_dst",
            stream_pass or elite_pass,
            "==",
            True,
            stream_pass or elite_pass,
            "K/DST must improve the current week unless an authoritative top-three ROS DST passes the elite guard",
        ),
    )
    affirmative = all(gate.passed for gate in gates)
    watch_plausible = (
        selected.current_week_delta
        >= policy.special_teams_watch_current_week_gain_floor
        or elite
    )
    if affirmative:
        if evaluation.acquisition_state == AcquisitionState.FREE_AGENT.value:
            label = "ADD NOW"
        elif evaluation.acquisition_state == AcquisitionState.WAIVERS.value:
            label = "CLAIM"
        else:
            label = "ACQUIRE"
        decision_path = (
            "ELITE_DST" if elite_pass and not stream_pass else f"{evaluation.add_position}_STREAM"
        )
        strongest_uncertainty = (
            "Special-team thresholds are controlled-fixture calibrated, not validated against historical streaming outcomes"
        )
    elif watch_plausible and (
        evidence_complete or policy.allow_watch_on_missing_news
    ):
        label = "WATCH"
        decision_path = "SPECIAL_TEAM_NEAR_THRESHOLD"
        first_failed = next(gate for gate in gates if not gate.passed)
        strongest_uncertainty = first_failed.explanation
    else:
        label = "PASS"
        decision_path = "SPECIAL_TEAM_WEEKLY_FAILURE"
        first_failed = next(gate for gate in gates if not gate.passed)
        strongest_uncertainty = first_failed.explanation
    residual = selected.lineup.weighted_delta - selected.current_week_delta
    priority_score = round(
        policy.special_teams_current_week_weight * selected.current_week_delta
        + residual,
        3,
    )
    decision = WaiverDecisionAssessment(
        label=label,
        decision_path=decision_path,
        policy_version=policy.version,
        policy_hash=policy.policy_hash,
        calibration_mode=policy.calibration_mode,
        priority_score=priority_score,
        elite_dst_exception=elite_pass and not stream_pass,
        gates=gates,
        reversal_conditions=(
            f"Current-week lineup gain falls below {stream_floor:+.1f}",
            f"DST rest-of-season rank is worse than {policy.elite_dst_ros_rank_cutoff} or unavailable",
            f"Elite DST current-week loss exceeds {policy.elite_dst_maximum_current_week_loss:.1f}",
            f"Elite DST remaining-week lineup delta falls below {policy.elite_dst_weighted_lineup_floor:+.1f}",
            "Authoritative weekly rank, projections, value coverage, or material-news freshness becomes incomplete",
        ),
    )
    return decision, strongest_uncertainty


def apply_waiver_policy(
    evaluation: WaiverEvaluation,
    policy: WaiverDecisionPolicy,
) -> WaiverEvaluation:
    if evaluation.league_key != policy.league_key:
        raise ValueError("Waiver decision policy is for a different league")
    if evaluation.acquisition_state not in ACQUIRABLE_STATES:
        raise ValueError("Waiver policy requires a currently unowned eligible player")
    policy_candidates = tuple(
        _apply_contingency_policy(candidate, policy)
        for candidate in evaluation.candidates
    )
    assessments = tuple(
        (candidate, *_assess_candidate(evaluation, candidate, policy))
        for candidate in policy_candidates
    )
    label_tier = {"ADD NOW": 0, "CLAIM": 0, "ACQUIRE": 0, "WATCH": 1, "PASS": 2}
    ordered = tuple(
        sorted(
            assessments,
            key=lambda row: (
                label_tier[row[1].label],
                row[0].contingency.drop_protected
                and not row[0].contingency.incremental_gate_passed,
                -row[1].priority_score,
                -row[0].lineup.after_weighted_points,
                -row[0].ownership.selected_delta,
                -row[0].ownership.market_delta,
                row[0].drop_player_id or "",
            ),
        )
    )
    selected, decision, strongest_uncertainty = ordered[0]
    candidates = tuple(row[0] for row in ordered)
    selected_expert_disagreement = any(
        _ww_support(evaluation, candidate, policy)[4]
        for candidate in candidates
    )
    warnings = tuple(
        sorted(
            {
                *(
                    warning
                    for warning in evaluation.warnings
                    if "No Waiver decision policy was applied" not in warning
                ),
                "Waiver policy is controlled-fixture calibrated; it does not estimate "
                "claim success or a FAAB bid",
                *(
                    (
                        "Protected contingent-upside is a counterfactual option ceiling; no teammate-unavailability probability is assumed",
                    )
                    if any(
                        candidate.contingency.add_protected
                        or candidate.contingency.drop_protected
                        for candidate in candidates
                    )
                    else ()
                ),
                *(
                    (
                        "Emerging-upside priority equals incremental option value minus modeled miss loss; no state probability is inferred",
                    )
                    if any(
                        row[1].decision_path.startswith("EMERGING_UPSIDE")
                        for row in assessments
                    )
                    else ()
                ),
                *(
                    (
                        "Selected trusted experts disagree on the configured Waiver Wire support cutoff",
                    )
                    if selected_expert_disagreement
                    else ()
                ),
                *(
                    (
                        "Genuine Waiver Wire evidence is incomplete or stale for emerging-upside policy",
                    )
                    if evaluation.waiver_wire_evidence is not None
                    and not evaluation.waiver_wire_evidence.complete
                    else ()
                ),
                *(
                    (
                        "Role evidence is incomplete, stale, or conflicting for at least one emerging candidate",
                    )
                    if evaluation.emergence_evidence is not None
                    and not evaluation.emergence_evidence.complete
                    else ()
                ),
            }
        )
    )
    base = replace(
        evaluation,
        selected_drop_player_id=selected.drop_player_id,
        selection_basis=(
            "best Waiver decision tier, then current-week-weighted special-team "
            "priority" if evaluation.add_position in {"K", "DST"} else
            "best Waiver decision tier, protected-upside gates, then emerging "
            "incremental option value minus miss loss, one-QB net hold value, or "
            "remaining-week optimal-lineup points; ties preserve selected-expert "
            "then market ownership value"
        ),
        candidates=candidates,
        next_best_drop_player_ids=tuple(
            row.drop_player_id for row in candidates[1:] if row.drop_player_id is not None
        ),
        policy_version=policy.version,
        policy_hash=policy.policy_hash,
        decision=decision,
        decision_label=decision.label,
        recommendation_generated=True,
        strongest_uncertainty=strongest_uncertainty,
        warnings=warnings,
        evidence_hash="",
    )
    return replace(base, evidence_hash=stable_hash(asdict(base)))
