from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from statistics import fmean
from typing import Any, Mapping, Sequence

from roster_theory.core.provenance import canonical_json, stable_hash
from roster_theory.providers.cache import atomic_write_json
from roster_theory.waiver.evaluation import WaiverEvaluation


DEFAULT_WAIVER_CONFIG_DIR = Path("config/waiver")
_SAFE_LEAGUE_KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*")
OUTCOME_STATUSES = ("COMPLETE", "PARTIAL", "CENSORED", "UNAVAILABLE", "UNMATCHED")
BASELINE_NAMES = ("ROS_ONLY", "WW_ONLY", "ROLE_PLUS_WW")


class LookAheadLeakage(ValueError):
    """Raised when decision or outcome evidence includes unavailable future data."""


class ImmutableEvidenceConflict(ValueError):
    """Raised when an immutable evidence path already contains different data."""


@dataclass(frozen=True, slots=True)
class WalkForwardPolicy:
    schema_version: int
    product: str
    league_key: str
    version: str
    outcome_windows: tuple[int, ...]
    minimum_complete_samples: int
    minimum_samples_per_signal_class: int
    maximum_window_hit_rate_spread: float
    role_persistence_ratio: float
    breakout_utility_gain: float
    severe_miss_regret: float
    policy_hash: str


@dataclass(frozen=True, slots=True)
class DecisionRoleMetric:
    metric: str
    basis: str
    baseline_average: float | None
    recent_average: float | None
    latest: float | None


@dataclass(frozen=True, slots=True)
class DecisionExpertRank:
    expert_id: str
    overall_rank: float | None
    position_rank: float | None


@dataclass(frozen=True, slots=True)
class DecisionScenario:
    state: str
    act_now_minus_retain_drop: float
    act_now_starter_weeks: tuple[int, ...]
    act_now_replacement_exposure: float


@dataclass(frozen=True, slots=True)
class DecisionSensitivity:
    hypothetical_miss_probability: float
    hypothetical_useful_role_probability: float
    hypothetical_breakout_probability: float
    expected_act_now_minus_retain_drop: float


@dataclass(frozen=True, slots=True)
class WaiverDecisionTimeSnapshot:
    schema_version: int
    product: str
    operation: str
    league_key: str
    decision_id: str
    captured_at: datetime
    decision_week: int
    outcome_windows: tuple[int, ...]
    evaluation_schema_version: int
    evaluation_evidence_hash: str
    input_bundle_hash: str | None
    manifest_id: str
    roster_state_hash: str
    availability_hash: str
    projection_value_hash: str
    policy_version: str
    policy_hash: str
    decision_label: str
    decision_path: str
    candidate_player_id: str
    drop_player_id: str | None
    acquisition_state: str
    availability_source: str | None
    raw_projection_delta: float
    ww_evidence_hash: str | None
    ww_captured_at: datetime | None
    ww_complete: bool
    ww_market_rank: float | None
    ww_selected_expert_ranks: tuple[DecisionExpertRank, ...]
    ww_signal_supported: bool
    role_evidence_hash: str | None
    role_captured_at: datetime | None
    role_complete: bool
    role_classification: str
    role_signal_strength: float
    role_signal_supported: bool
    role_metrics: tuple[DecisionRoleMetric, ...]
    scenario_valuation_hash: str
    scenarios: tuple[DecisionScenario, ...]
    break_even_status: str
    break_even_hit_rate: float | None
    break_even_explanation: str
    sensitivity: tuple[DecisionSensitivity, ...]
    no_action_weighted_points: float
    no_action_central_preferred: bool
    no_action_best_in_every_scenario: bool
    source_evaluation_json: str
    warnings: tuple[str, ...]
    sleeper_write_performed: bool
    snapshot_hash: str


@dataclass(frozen=True, slots=True)
class PlayerWeekOutcome:
    player_id: str
    week: int
    captured_at: datetime
    source_updated_at: datetime
    source: str
    identity_status: str
    coverage_status: str
    total_opportunities: float | None
    league_points: float | None
    replacement_value: float | None
    started: bool | None
    available_at_next_decision: bool | None
    reacquirable_at_next_decision: bool | None
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class WaiverOutcomeWindow:
    schema_version: int
    product: str
    operation: str
    league_key: str
    decision_id: str
    decision_snapshot_hash: str
    policy_version_retained: str
    window_weeks: int
    outcome_start_week: int
    outcome_end_week: int
    as_of_week: int
    captured_at: datetime
    candidate_player_id: str
    drop_player_id: str | None
    candidate_observations: tuple[PlayerWeekOutcome, ...]
    drop_observations: tuple[PlayerWeekOutcome, ...]
    coverage_status: str
    role_persisted: bool | None
    realized_state: str
    candidate_remained_available: bool | None
    drop_reacquirable: bool | None
    candidate_start_weeks: tuple[int, ...]
    drop_start_weeks: tuple[int, ...]
    candidate_league_points: float | None
    drop_league_points: float | None
    replacement_value: float | None
    act_now_roster_utility: float | None
    retain_drop_roster_utility: float | None
    realized_act_now_minus_retain_drop: float | None
    act_now_regret: float | None
    retain_drop_regret: float | None
    severe_miss: bool | None
    warnings: tuple[str, ...]
    sleeper_write_performed: bool
    outcome_hash: str


@dataclass(frozen=True, slots=True)
class WalkForwardCoverage:
    total: int
    complete: int
    partial: int
    censored: int
    unavailable: int
    unmatched: int
    missing_outcome_windows: int


@dataclass(frozen=True, slots=True)
class WalkForwardWindowSummary:
    window_weeks: int
    sample_size: int
    complete_samples: int
    role_evaluable_samples: int
    role_hits: int
    role_hit_rate: float | None
    average_act_now_utility: float | None
    average_retain_drop_utility: float | None
    average_realized_gain: float | None
    severe_miss_rate: float | None
    average_dropped_player_regret: float | None


@dataclass(frozen=True, slots=True)
class WalkForwardBaselineSummary:
    baseline: str
    window_weeks: int
    eligible_samples: int
    unavailable_signal_samples: int
    positive_calls: int
    true_positive_calls: int
    hit_rate: float | None
    accuracy: float | None
    average_roster_utility: float | None
    severe_miss_rate: float | None
    average_dropped_player_regret: float | None
    calibration_error: float | None
    calibration_note: str


@dataclass(frozen=True, slots=True)
class WalkForwardSignalSummary:
    signal_class: str
    sample_size: int
    hits: int
    hit_rate: float | None


@dataclass(frozen=True, slots=True)
class WalkForwardBreakEvenEvidence:
    decision_id: str
    status: str
    hit_rate: float | None
    explanation: str
    sensitivity: tuple[DecisionSensitivity, ...]


@dataclass(frozen=True, slots=True)
class StateProbabilityEvidence:
    status: str
    reason: str
    source_window_weeks: int
    complete_samples: int
    stable: bool
    probabilities: tuple[tuple[str, float], ...]


@dataclass(frozen=True, slots=True)
class WaiverWalkForwardReport:
    schema_version: int
    product: str
    operation: str
    league_key: str
    generated_at: datetime
    walk_forward_policy_version: str
    walk_forward_policy_hash: str
    retained_waiver_policy_versions: tuple[str, ...]
    decision_count: int
    coverage: WalkForwardCoverage
    windows: tuple[WalkForwardWindowSummary, ...]
    baselines: tuple[WalkForwardBaselineSummary, ...]
    signal_classes: tuple[WalkForwardSignalSummary, ...]
    break_even_evidence: tuple[WalkForwardBreakEvenEvidence, ...]
    state_probability_evidence: StateProbabilityEvidence
    policy_promotion_performed: bool
    sleeper_write_performed: bool
    warnings: tuple[str, ...]
    report_hash: str


def default_walk_forward_policy_path(
    league_key: str,
    *,
    config_dir: str | Path = DEFAULT_WAIVER_CONFIG_DIR,
) -> Path:
    if not _SAFE_LEAGUE_KEY.fullmatch(league_key):
        raise ValueError(f"Invalid Waiver league key: {league_key!r}")
    return Path(config_dir) / f"{league_key}.walk-forward.json"


def load_walk_forward_policy(path: str | Path, *, league_key: str | None = None) -> WalkForwardPolicy:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if int(value.get("schema_version") or 0) != 1:
        raise ValueError("Unsupported Waiver walk-forward policy schema")
    if str(value.get("product") or "") != "WAIVER ASSISTANT":
        raise ValueError("Walk-forward policy must be Waiver-scoped")
    configured_league = str(value.get("league_key") or "")
    if not configured_league or league_key is not None and configured_league != league_key:
        raise ValueError("Waiver walk-forward policy is for a different league")
    windows = tuple(int(item) for item in value.get("outcome_windows") or ())
    if windows != tuple(sorted(set(windows))) or not windows or any(item <= 0 for item in windows):
        raise ValueError("Outcome windows must be unique positive weeks in ascending order")
    minimum_complete = int(value.get("minimum_complete_samples") or 0)
    minimum_signal = int(value.get("minimum_samples_per_signal_class") or 0)
    if minimum_complete < 2 or minimum_signal < 1:
        raise ValueError("Walk-forward sample gates must be positive and documented")
    spread = float(value.get("maximum_window_hit_rate_spread"))
    persistence = float(value.get("role_persistence_ratio"))
    if not 0 <= spread <= 1 or not 0 < persistence <= 1:
        raise ValueError("Walk-forward stability and persistence thresholds are invalid")
    breakout_gain = float(value.get("breakout_utility_gain"))
    severe_miss = float(value.get("severe_miss_regret"))
    if breakout_gain < 0 or severe_miss <= 0:
        raise ValueError("Walk-forward utility and severe-miss thresholds are invalid")
    version = str(value.get("version") or "")
    if not version:
        raise ValueError("Waiver walk-forward policy requires a version")
    unsigned = dict(value)
    policy_hash = stable_hash(unsigned)
    return WalkForwardPolicy(
        schema_version=1,
        product="WAIVER ASSISTANT",
        league_key=configured_league,
        version=version,
        outcome_windows=windows,
        minimum_complete_samples=minimum_complete,
        minimum_samples_per_signal_class=minimum_signal,
        maximum_window_hit_rate_spread=spread,
        role_persistence_ratio=persistence,
        breakout_utility_gain=breakout_gain,
        severe_miss_regret=severe_miss,
        policy_hash=policy_hash,
    )


def _verified_hash(value: Any, field: str) -> None:
    expected = getattr(value, field)
    actual = stable_hash(asdict(replace(value, **{field: ""})))
    if not expected or expected != actual:
        raise ValueError(f"{type(value).__name__} hash is invalid")


def _gate_actual(evaluation: WaiverEvaluation, name: str) -> float | bool | None:
    if evaluation.decision is None:
        return None
    gate = next((row for row in evaluation.decision.gates if row.name == name), None)
    return gate.actual if gate is not None else None


def _gate_passed(evaluation: WaiverEvaluation, name: str) -> bool:
    if evaluation.decision is None:
        return False
    gate = next((row for row in evaluation.decision.gates if row.name == name), None)
    return bool(gate and gate.passed)


def capture_decision_time_snapshot(
    evaluation: WaiverEvaluation,
    policy: WalkForwardPolicy,
    *,
    captured_at: datetime | None = None,
) -> WaiverDecisionTimeSnapshot:
    if evaluation.league_key != policy.league_key:
        raise ValueError("Walk-forward policy and Waiver evaluation leagues differ")
    _verified_hash(evaluation, "evidence_hash")
    if not evaluation.recommendation_generated or evaluation.decision is None:
        raise ValueError("Decision-time capture requires a completed Waiver policy evaluation")
    captured = captured_at or evaluation.evaluated_at
    if captured.tzinfo is None:
        raise ValueError("Decision-time capture timestamp must be timezone-aware")
    captured = captured.astimezone(timezone.utc)
    if captured < evaluation.evaluated_at.astimezone(timezone.utc):
        raise LookAheadLeakage("Decision snapshot cannot predate its evaluation")
    selected = evaluation.candidates[0]
    emergence = evaluation.emergence_evidence
    role_player = next(
        (
            row
            for row in (emergence.players if emergence is not None else ())
            if row.player_id == evaluation.add_player_id
        ),
        None,
    )
    if evaluation.waiver_wire_evidence is not None:
        ww_time = evaluation.waiver_wire_evidence.captured_at.astimezone(timezone.utc)
        if ww_time > captured:
            raise LookAheadLeakage("Waiver Wire evidence was captured after the decision")
        provider_updated = evaluation.waiver_wire_evidence.provider_updated_at
        if provider_updated:
            parsed = datetime.fromisoformat(provider_updated.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                raise ValueError("Waiver Wire provider timestamp must be timezone-aware")
            if parsed.astimezone(timezone.utc) > captured:
                raise LookAheadLeakage("Waiver Wire provider update occurred after the decision")
        for player in evaluation.waiver_wire_evidence.players:
            for expert in player.selected_expert_ranks:
                if expert.updated_at:
                    updated = datetime.fromisoformat(expert.updated_at.replace("Z", "+00:00"))
                    if updated.tzinfo is None:
                        raise ValueError("Selected-expert timestamp must be timezone-aware")
                    if updated.astimezone(timezone.utc) > captured:
                        raise LookAheadLeakage("Selected-expert rank update occurred after the decision")
    if emergence is not None:
        if emergence.captured_at.astimezone(timezone.utc) > captured:
            raise LookAheadLeakage("Role evidence was captured after the decision")
        for player in emergence.players:
            for observation in player.observations:
                if observation.week > evaluation.current_week:
                    raise LookAheadLeakage("Decision-time role evidence contains a future week")
                if observation.captured_at.astimezone(timezone.utc) > captured:
                    raise LookAheadLeakage("Decision-time role evidence has a future capture")
                if observation.source_updated_at.astimezone(timezone.utc) > captured:
                    raise LookAheadLeakage("Decision-time role evidence has a future source update")
            for editorial in player.editorials:
                if editorial.captured_at.astimezone(timezone.utc) > captured:
                    raise LookAheadLeakage("Decision-time editorial evidence has a future capture")
                if editorial.published_at.astimezone(timezone.utc) > captured:
                    raise LookAheadLeakage("Decision-time editorial evidence has a future publication")
    role_metrics = tuple(
        DecisionRoleMetric(
            metric=row.metric,
            basis=row.basis,
            baseline_average=row.baseline_average,
            recent_average=row.rolling_average,
            latest=row.latest,
        )
        for row in (role_player.comparisons if role_player is not None else ())
    )
    scenarios = tuple(
        DecisionScenario(
            state=row.state,
            act_now_minus_retain_drop=row.act_now_minus_retain_drop,
            act_now_starter_weeks=row.act_now.starter_weeks,
            act_now_replacement_exposure=row.act_now.replacement_exposure,
        )
        for row in selected.emerging_upside.scenario_comparisons
    )
    sensitivity = tuple(
        DecisionSensitivity(
            hypothetical_miss_probability=row.hypothetical_miss_probability,
            hypothetical_useful_role_probability=row.hypothetical_useful_role_probability,
            hypothetical_breakout_probability=row.hypothetical_breakout_probability,
            expected_act_now_minus_retain_drop=row.expected_act_now_minus_retain_drop,
        )
        for row in selected.emerging_upside.sensitivity
    )
    roster_state_hash = stable_hash(
        {
            "manifest_id": evaluation.manifest_id,
            "drop_player_id": selected.drop_player_id,
            "before": tuple(
                (row.week, row.before_points, row.before_starters)
                for row in selected.lineup.weeks
            ),
        }
    )
    availability_hash = stable_hash(
        {
            "candidate": evaluation.add_player_id,
            "state": evaluation.acquisition_state,
            "source": evaluation.availability_source,
            "candidate_hash": evaluation.candidate_hash,
        }
    )
    market_rank = selected.ownership.waiver_wire_market_add_rank
    role_strength = _gate_actual(evaluation, "emerging_role_signal_strength")
    base = WaiverDecisionTimeSnapshot(
        schema_version=1,
        product="WAIVER ASSISTANT",
        operation="WAIVER WALK-FORWARD DECISION CAPTURE",
        league_key=evaluation.league_key,
        decision_id=stable_hash(
            {
                "league_key": evaluation.league_key,
                "evaluation_evidence_hash": evaluation.evidence_hash,
                "captured_at": captured,
            }
        ),
        captured_at=captured,
        decision_week=evaluation.current_week,
        outcome_windows=policy.outcome_windows,
        evaluation_schema_version=evaluation.schema_version,
        evaluation_evidence_hash=evaluation.evidence_hash,
        input_bundle_hash=evaluation.input_bundle_hash,
        manifest_id=evaluation.manifest_id,
        roster_state_hash=roster_state_hash,
        availability_hash=availability_hash,
        projection_value_hash=evaluation.value_input_hash,
        policy_version=evaluation.policy_version or "",
        policy_hash=evaluation.policy_hash or "",
        decision_label=evaluation.decision_label or "",
        decision_path=evaluation.decision.decision_path,
        candidate_player_id=evaluation.add_player_id,
        drop_player_id=selected.drop_player_id,
        acquisition_state=evaluation.acquisition_state,
        availability_source=evaluation.availability_source,
        raw_projection_delta=selected.ownership.raw_projection_delta,
        ww_evidence_hash=(
            evaluation.waiver_wire_evidence.evidence_hash
            if evaluation.waiver_wire_evidence is not None
            else None
        ),
        ww_captured_at=(
            evaluation.waiver_wire_evidence.captured_at.astimezone(timezone.utc)
            if evaluation.waiver_wire_evidence is not None
            else None
        ),
        ww_complete=bool(
            evaluation.waiver_wire_evidence
            and evaluation.waiver_wire_evidence.complete
        ),
        ww_market_rank=market_rank,
        ww_selected_expert_ranks=tuple(
            DecisionExpertRank(row.expert_id, row.overall_rank, row.position_rank)
            for row in selected.ownership.waiver_wire_selected_add_ranks
        ),
        ww_signal_supported=bool(_gate_actual(evaluation, "waiver_wire_support")),
        role_evidence_hash=emergence.evidence_hash if emergence is not None else None,
        role_captured_at=(
            emergence.captured_at.astimezone(timezone.utc)
            if emergence is not None
            else None
        ),
        role_complete=bool(emergence and emergence.complete and role_player),
        role_classification=(role_player.classification if role_player else "UNAVAILABLE"),
        role_signal_strength=(
            float(role_strength)
            if isinstance(role_strength, (int, float)) and not isinstance(role_strength, bool)
            else 0.0
        ),
        role_signal_supported=_gate_passed(evaluation, "emerging_role_signal_strength"),
        role_metrics=role_metrics,
        scenario_valuation_hash=selected.emerging_upside.valuation_hash,
        scenarios=scenarios,
        break_even_status=selected.emerging_upside.break_even.status,
        break_even_hit_rate=selected.emerging_upside.break_even.hit_rate,
        break_even_explanation=selected.emerging_upside.break_even.explanation,
        sensitivity=sensitivity,
        no_action_weighted_points=selected.emerging_upside.no_action.weighted_lineup_points,
        no_action_central_preferred=selected.emerging_upside.no_action.central_preferred,
        no_action_best_in_every_scenario=(
            selected.emerging_upside.no_action.best_in_every_scenario
        ),
        source_evaluation_json=canonical_json(evaluation),
        warnings=tuple(sorted(set(evaluation.warnings))),
        sleeper_write_performed=False,
        snapshot_hash="",
    )
    return replace(base, snapshot_hash=stable_hash(asdict(base)))


def _save_immutable(value: Any, path: str | Path, hash_field: str) -> Path:
    target = Path(path)
    if target.exists():
        existing = json.loads(target.read_text(encoding="utf-8"))
        expected = str(existing.get(hash_field) or "")
        unsigned = dict(existing)
        unsigned[hash_field] = ""
        if not expected or stable_hash(unsigned) != expected:
            raise ImmutableEvidenceConflict("Existing immutable evidence is invalid")
        if canonical_json(existing) != canonical_json(value):
            raise ImmutableEvidenceConflict(
                "Immutable evidence path already contains a different bundle"
            )
        return target
    return atomic_write_json(target, value)


def save_decision_time_snapshot(snapshot: WaiverDecisionTimeSnapshot, path: str | Path) -> Path:
    _verified_hash(snapshot, "snapshot_hash")
    return _save_immutable(snapshot, path, "snapshot_hash")


def _datetime(value: Any) -> datetime:
    parsed = datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        raise ValueError("Walk-forward timestamps must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def decision_time_snapshot_from_json(value: Mapping[str, Any]) -> WaiverDecisionTimeSnapshot:
    snapshot = WaiverDecisionTimeSnapshot(
        schema_version=int(value["schema_version"]),
        product=str(value["product"]),
        operation=str(value["operation"]),
        league_key=str(value["league_key"]),
        decision_id=str(value["decision_id"]),
        captured_at=_datetime(value["captured_at"]),
        decision_week=int(value["decision_week"]),
        outcome_windows=tuple(int(row) for row in value["outcome_windows"]),
        evaluation_schema_version=int(value["evaluation_schema_version"]),
        evaluation_evidence_hash=str(value["evaluation_evidence_hash"]),
        input_bundle_hash=(str(value["input_bundle_hash"]) if value.get("input_bundle_hash") is not None else None),
        manifest_id=str(value["manifest_id"]),
        roster_state_hash=str(value["roster_state_hash"]),
        availability_hash=str(value["availability_hash"]),
        projection_value_hash=str(value["projection_value_hash"]),
        policy_version=str(value["policy_version"]),
        policy_hash=str(value["policy_hash"]),
        decision_label=str(value["decision_label"]),
        decision_path=str(value["decision_path"]),
        candidate_player_id=str(value["candidate_player_id"]),
        drop_player_id=(str(value["drop_player_id"]) if value.get("drop_player_id") is not None else None),
        acquisition_state=str(value["acquisition_state"]),
        availability_source=(str(value["availability_source"]) if value.get("availability_source") is not None else None),
        raw_projection_delta=float(value["raw_projection_delta"]),
        ww_evidence_hash=(str(value["ww_evidence_hash"]) if value.get("ww_evidence_hash") is not None else None),
        ww_captured_at=(_datetime(value["ww_captured_at"]) if value.get("ww_captured_at") is not None else None),
        ww_complete=bool(value["ww_complete"]),
        ww_market_rank=(float(value["ww_market_rank"]) if value.get("ww_market_rank") is not None else None),
        ww_selected_expert_ranks=tuple(
            DecisionExpertRank(str(row["expert_id"]), float(row["overall_rank"]) if row.get("overall_rank") is not None else None, float(row["position_rank"]) if row.get("position_rank") is not None else None)
            for row in value.get("ww_selected_expert_ranks") or ()
        ),
        ww_signal_supported=bool(value["ww_signal_supported"]),
        role_evidence_hash=(str(value["role_evidence_hash"]) if value.get("role_evidence_hash") is not None else None),
        role_captured_at=(_datetime(value["role_captured_at"]) if value.get("role_captured_at") is not None else None),
        role_complete=bool(value["role_complete"]),
        role_classification=str(value["role_classification"]),
        role_signal_strength=float(value["role_signal_strength"]),
        role_signal_supported=bool(value["role_signal_supported"]),
        role_metrics=tuple(
            DecisionRoleMetric(str(row["metric"]), str(row["basis"]), float(row["baseline_average"]) if row.get("baseline_average") is not None else None, float(row["recent_average"]) if row.get("recent_average") is not None else None, float(row["latest"]) if row.get("latest") is not None else None)
            for row in value.get("role_metrics") or ()
        ),
        scenario_valuation_hash=str(value["scenario_valuation_hash"]),
        scenarios=tuple(
            DecisionScenario(str(row["state"]), float(row["act_now_minus_retain_drop"]), tuple(int(week) for week in row.get("act_now_starter_weeks") or ()), float(row["act_now_replacement_exposure"]))
            for row in value.get("scenarios") or ()
        ),
        break_even_status=str(value["break_even_status"]),
        break_even_hit_rate=(float(value["break_even_hit_rate"]) if value.get("break_even_hit_rate") is not None else None),
        break_even_explanation=str(value["break_even_explanation"]),
        sensitivity=tuple(
            DecisionSensitivity(
                float(row["hypothetical_miss_probability"]),
                float(row["hypothetical_useful_role_probability"]),
                float(row["hypothetical_breakout_probability"]),
                float(row["expected_act_now_minus_retain_drop"]),
            )
            for row in value.get("sensitivity") or ()
        ),
        no_action_weighted_points=float(value["no_action_weighted_points"]),
        no_action_central_preferred=bool(value["no_action_central_preferred"]),
        no_action_best_in_every_scenario=bool(value["no_action_best_in_every_scenario"]),
        source_evaluation_json=str(value["source_evaluation_json"]),
        warnings=tuple(str(row) for row in value.get("warnings") or ()),
        sleeper_write_performed=bool(value["sleeper_write_performed"]),
        snapshot_hash=str(value["snapshot_hash"]),
    )
    if snapshot.schema_version != 1 or snapshot.product != "WAIVER ASSISTANT":
        raise ValueError("Unsupported Waiver decision-time snapshot")
    if snapshot.sleeper_write_performed:
        raise ValueError("Decision-time snapshot violates the Sleeper read-only guard")
    _verified_hash(snapshot, "snapshot_hash")
    return snapshot


def load_decision_time_snapshot(path: str | Path) -> WaiverDecisionTimeSnapshot:
    return decision_time_snapshot_from_json(json.loads(Path(path).read_text(encoding="utf-8")))


def _outcome_status(rows: Sequence[PlayerWeekOutcome], expected_weeks: set[int]) -> str:
    if any(row.identity_status == "UNMATCHED" for row in rows):
        return "UNMATCHED"
    if any(row.coverage_status == "UNAVAILABLE" for row in rows):
        return "UNAVAILABLE"
    if any(row.coverage_status == "PARTIAL" for row in rows):
        return "PARTIAL"
    if {row.week for row in rows} != expected_weeks or any(row.coverage_status == "CENSORED" for row in rows):
        return "CENSORED"
    if any(row.identity_status != "MATCHED" or row.coverage_status != "COMPLETE" for row in rows):
        return "PARTIAL"
    return "COMPLETE"


def _first_known(rows: Sequence[PlayerWeekOutcome], field: str) -> bool | None:
    return next((getattr(row, field) for row in rows if getattr(row, field) is not None), None)


def _sum_known(rows: Sequence[PlayerWeekOutcome], field: str) -> float | None:
    values = [getattr(row, field) for row in rows]
    return round(sum(float(value) for value in values), 3) if values and all(value is not None for value in values) else None


def build_outcome_window(
    snapshot: WaiverDecisionTimeSnapshot,
    policy: WalkForwardPolicy,
    *,
    window_weeks: int,
    as_of_week: int,
    captured_at: datetime,
    candidate_observations: Sequence[PlayerWeekOutcome],
    drop_observations: Sequence[PlayerWeekOutcome] = (),
) -> WaiverOutcomeWindow:
    _verified_hash(snapshot, "snapshot_hash")
    if snapshot.league_key != policy.league_key:
        raise ValueError("Outcome policy and decision snapshot leagues differ")
    if window_weeks not in policy.outcome_windows:
        raise ValueError("Outcome window is not configured for this league")
    if captured_at.tzinfo is None:
        raise ValueError("Outcome capture timestamp must be timezone-aware")
    captured = captured_at.astimezone(timezone.utc)
    if captured <= snapshot.captured_at:
        raise LookAheadLeakage("Outcome capture must occur after the decision snapshot")
    start = snapshot.decision_week + 1
    end = snapshot.decision_week + window_weeks
    if as_of_week < snapshot.decision_week:
        raise LookAheadLeakage("Outcome as-of week predates the decision")
    candidate_rows = tuple(sorted(candidate_observations, key=lambda row: row.week))
    drop_rows = tuple(sorted(drop_observations, key=lambda row: row.week))
    if any(row.player_id != snapshot.candidate_player_id for row in candidate_rows):
        raise ValueError("Candidate outcome identity differs from decision snapshot")
    if snapshot.drop_player_id is None and drop_rows:
        raise ValueError("No-drop decision cannot receive drop observations")
    if snapshot.drop_player_id is not None and any(row.player_id != snapshot.drop_player_id for row in drop_rows):
        raise ValueError("Drop outcome identity differs from decision snapshot")
    all_rows = candidate_rows + drop_rows
    if len({(row.player_id, row.week) for row in all_rows}) != len(all_rows):
        raise ValueError("Duplicate player-week outcome observation")
    for row in all_rows:
        if row.captured_at.tzinfo is None or row.source_updated_at.tzinfo is None:
            raise ValueError("Outcome observations require timezone-aware timestamps")
        if row.week < start or row.week > end or row.week > as_of_week:
            raise LookAheadLeakage("Outcome input includes a week beyond the allowed cutoff")
        if row.captured_at.astimezone(timezone.utc) <= snapshot.captured_at:
            raise LookAheadLeakage("Outcome observation does not postdate the decision")
        if row.source_updated_at.astimezone(timezone.utc) <= snapshot.captured_at:
            raise LookAheadLeakage("Outcome source update does not postdate the decision")
        if row.captured_at.astimezone(timezone.utc) > captured:
            raise LookAheadLeakage("Outcome observation was captured after the record cutoff")
        if row.source_updated_at.astimezone(timezone.utc) > captured:
            raise LookAheadLeakage("Outcome source update occurred after the record cutoff")
        if row.league_points is not None and not row.source.strip():
            raise ValueError("League-scored outcome points require source provenance")
        if row.total_opportunities is not None and row.total_opportunities < 0:
            raise ValueError("Outcome opportunities cannot be negative")
    expected = set(range(start, end + 1))
    candidate_status = _outcome_status(candidate_rows, expected)
    drop_status = (
        _outcome_status(drop_rows, expected)
        if snapshot.drop_player_id is not None
        else "COMPLETE"
    )
    coverage_status = max(
        (candidate_status, drop_status),
        key=lambda status: OUTCOME_STATUSES.index(status),
    )
    total_metric = next(
        (row for row in snapshot.role_metrics if row.metric == "total_opportunities"),
        None,
    )
    complete_candidate = candidate_status == "COMPLETE"
    role_persisted: bool | None = None
    if (
        complete_candidate
        and total_metric is not None
        and total_metric.baseline_average is not None
        and total_metric.recent_average is not None
        and all(row.total_opportunities is not None for row in candidate_rows)
    ):
        threshold = total_metric.baseline_average + (
            total_metric.recent_average - total_metric.baseline_average
        ) * policy.role_persistence_ratio
        role_persisted = fmean(float(row.total_opportunities) for row in candidate_rows) >= threshold
    candidate_points = _sum_known(candidate_rows, "league_points")
    replacement = _sum_known(candidate_rows, "replacement_value")
    drop_points = (
        _sum_known(drop_rows, "league_points")
        if snapshot.drop_player_id is not None
        else replacement
    )
    act_utility: float | None = None
    retain_utility: float | None = None
    if coverage_status == "COMPLETE" and candidate_points is not None and replacement is not None and drop_points is not None:
        act_utility = round(
            sum(max(float(row.league_points), float(row.replacement_value)) for row in candidate_rows),
            3,
        )
        retain_source = drop_rows if snapshot.drop_player_id is not None else candidate_rows
        retain_utility = round(
            sum(
                max(
                    float(row.league_points) if snapshot.drop_player_id is not None else float(row.replacement_value),
                    float(row.replacement_value),
                )
                for row in retain_source
            ),
            3,
        )
    realized_gain = round(act_utility - retain_utility, 3) if act_utility is not None and retain_utility is not None else None
    best = max(act_utility, retain_utility) if act_utility is not None and retain_utility is not None else None
    act_regret = round(best - act_utility, 3) if best is not None and act_utility is not None else None
    retain_regret = round(best - retain_utility, 3) if best is not None and retain_utility is not None else None
    severe_miss = act_regret >= policy.severe_miss_regret if act_regret is not None else None
    realized_state = (
        "UNKNOWN"
        if role_persisted is None or realized_gain is None
        else "MISS"
        if not role_persisted
        else "BREAKOUT"
        if realized_gain >= policy.breakout_utility_gain
        else "USEFUL_ROLE"
    )
    warnings = set()
    if coverage_status != "COMPLETE":
        warnings.add(f"Outcome is {coverage_status.lower()}; it remains in coverage counts")
    if role_persisted is None:
        warnings.add("Role persistence is unavailable from complete opportunity observations")
    if _first_known(candidate_rows, "available_at_next_decision") is None:
        warnings.add("Candidate next-decision availability is unknown; no competing claim is inferred")
    if snapshot.drop_player_id is not None and _first_known(drop_rows, "reacquirable_at_next_decision") is None:
        warnings.add("Drop reacquisition status is unknown; no hidden availability is inferred")
    warnings.update(warning for row in all_rows for warning in row.warnings)
    base = WaiverOutcomeWindow(
        schema_version=1,
        product="WAIVER ASSISTANT",
        operation="WAIVER WALK-FORWARD OUTCOME",
        league_key=snapshot.league_key,
        decision_id=snapshot.decision_id,
        decision_snapshot_hash=snapshot.snapshot_hash,
        policy_version_retained=snapshot.policy_version,
        window_weeks=window_weeks,
        outcome_start_week=start,
        outcome_end_week=end,
        as_of_week=as_of_week,
        captured_at=captured,
        candidate_player_id=snapshot.candidate_player_id,
        drop_player_id=snapshot.drop_player_id,
        candidate_observations=candidate_rows,
        drop_observations=drop_rows,
        coverage_status=coverage_status,
        role_persisted=role_persisted,
        realized_state=realized_state,
        candidate_remained_available=_first_known(candidate_rows, "available_at_next_decision"),
        drop_reacquirable=_first_known(drop_rows, "reacquirable_at_next_decision"),
        candidate_start_weeks=tuple(row.week for row in candidate_rows if row.started is True),
        drop_start_weeks=tuple(row.week for row in drop_rows if row.started is True),
        candidate_league_points=candidate_points,
        drop_league_points=drop_points,
        replacement_value=replacement,
        act_now_roster_utility=act_utility,
        retain_drop_roster_utility=retain_utility,
        realized_act_now_minus_retain_drop=realized_gain,
        act_now_regret=act_regret,
        retain_drop_regret=retain_regret,
        severe_miss=severe_miss,
        warnings=tuple(sorted(warnings)),
        sleeper_write_performed=False,
        outcome_hash="",
    )
    return replace(base, outcome_hash=stable_hash(asdict(base)))


def save_outcome_window(outcome: WaiverOutcomeWindow, path: str | Path) -> Path:
    _verified_hash(outcome, "outcome_hash")
    return _save_immutable(outcome, path, "outcome_hash")


def _observation_from_json(row: Mapping[str, Any]) -> PlayerWeekOutcome:
    return PlayerWeekOutcome(
        player_id=str(row["player_id"]),
        week=int(row["week"]),
        captured_at=_datetime(row["captured_at"]),
        source_updated_at=_datetime(row["source_updated_at"]),
        source=str(row["source"]),
        identity_status=str(row["identity_status"]),
        coverage_status=str(row["coverage_status"]),
        total_opportunities=(float(row["total_opportunities"]) if row.get("total_opportunities") is not None else None),
        league_points=(float(row["league_points"]) if row.get("league_points") is not None else None),
        replacement_value=(float(row["replacement_value"]) if row.get("replacement_value") is not None else None),
        started=(bool(row["started"]) if row.get("started") is not None else None),
        available_at_next_decision=(bool(row["available_at_next_decision"]) if row.get("available_at_next_decision") is not None else None),
        reacquirable_at_next_decision=(bool(row["reacquirable_at_next_decision"]) if row.get("reacquirable_at_next_decision") is not None else None),
        warnings=tuple(str(item) for item in row.get("warnings") or ()),
    )


def outcome_window_from_json(value: Mapping[str, Any]) -> WaiverOutcomeWindow:
    outcome = WaiverOutcomeWindow(
        schema_version=int(value["schema_version"]),
        product=str(value["product"]),
        operation=str(value["operation"]),
        league_key=str(value["league_key"]),
        decision_id=str(value["decision_id"]),
        decision_snapshot_hash=str(value["decision_snapshot_hash"]),
        policy_version_retained=str(value["policy_version_retained"]),
        window_weeks=int(value["window_weeks"]),
        outcome_start_week=int(value["outcome_start_week"]),
        outcome_end_week=int(value["outcome_end_week"]),
        as_of_week=int(value["as_of_week"]),
        captured_at=_datetime(value["captured_at"]),
        candidate_player_id=str(value["candidate_player_id"]),
        drop_player_id=(str(value["drop_player_id"]) if value.get("drop_player_id") is not None else None),
        candidate_observations=tuple(_observation_from_json(row) for row in value.get("candidate_observations") or ()),
        drop_observations=tuple(_observation_from_json(row) for row in value.get("drop_observations") or ()),
        coverage_status=str(value["coverage_status"]),
        role_persisted=(bool(value["role_persisted"]) if value.get("role_persisted") is not None else None),
        realized_state=str(value["realized_state"]),
        candidate_remained_available=(bool(value["candidate_remained_available"]) if value.get("candidate_remained_available") is not None else None),
        drop_reacquirable=(bool(value["drop_reacquirable"]) if value.get("drop_reacquirable") is not None else None),
        candidate_start_weeks=tuple(int(row) for row in value.get("candidate_start_weeks") or ()),
        drop_start_weeks=tuple(int(row) for row in value.get("drop_start_weeks") or ()),
        candidate_league_points=(float(value["candidate_league_points"]) if value.get("candidate_league_points") is not None else None),
        drop_league_points=(float(value["drop_league_points"]) if value.get("drop_league_points") is not None else None),
        replacement_value=(float(value["replacement_value"]) if value.get("replacement_value") is not None else None),
        act_now_roster_utility=(float(value["act_now_roster_utility"]) if value.get("act_now_roster_utility") is not None else None),
        retain_drop_roster_utility=(float(value["retain_drop_roster_utility"]) if value.get("retain_drop_roster_utility") is not None else None),
        realized_act_now_minus_retain_drop=(float(value["realized_act_now_minus_retain_drop"]) if value.get("realized_act_now_minus_retain_drop") is not None else None),
        act_now_regret=(float(value["act_now_regret"]) if value.get("act_now_regret") is not None else None),
        retain_drop_regret=(float(value["retain_drop_regret"]) if value.get("retain_drop_regret") is not None else None),
        severe_miss=(bool(value["severe_miss"]) if value.get("severe_miss") is not None else None),
        warnings=tuple(str(row) for row in value.get("warnings") or ()),
        sleeper_write_performed=bool(value["sleeper_write_performed"]),
        outcome_hash=str(value["outcome_hash"]),
    )
    if outcome.schema_version != 1 or outcome.product != "WAIVER ASSISTANT":
        raise ValueError("Unsupported Waiver outcome window")
    if outcome.sleeper_write_performed:
        raise ValueError("Outcome window violates the Sleeper read-only guard")
    _verified_hash(outcome, "outcome_hash")
    return outcome


def load_outcome_window(path: str | Path) -> WaiverOutcomeWindow:
    return outcome_window_from_json(json.loads(Path(path).read_text(encoding="utf-8")))


def _mean(values: Sequence[float]) -> float | None:
    return round(fmean(values), 6) if values else None


def _baseline_call(snapshot: WaiverDecisionTimeSnapshot, baseline: str) -> bool | None:
    if baseline == "ROS_ONLY":
        return snapshot.raw_projection_delta >= 0
    if baseline == "WW_ONLY":
        return snapshot.ww_signal_supported if snapshot.ww_complete else None
    if baseline == "ROLE_PLUS_WW":
        return (
            snapshot.role_signal_supported and snapshot.ww_signal_supported
            if snapshot.role_complete and snapshot.ww_complete
            else None
        )
    raise ValueError(f"Unsupported walk-forward baseline: {baseline}")


def build_walk_forward_report(
    snapshots: Sequence[WaiverDecisionTimeSnapshot],
    outcomes: Sequence[WaiverOutcomeWindow],
    policy: WalkForwardPolicy,
    *,
    generated_at: datetime,
) -> WaiverWalkForwardReport:
    if generated_at.tzinfo is None:
        raise ValueError("Walk-forward report timestamp must be timezone-aware")
    generated = generated_at.astimezone(timezone.utc)
    snapshot_by_id = {}
    for snapshot in snapshots:
        _verified_hash(snapshot, "snapshot_hash")
        if snapshot.league_key != policy.league_key:
            raise ValueError("Decision snapshot belongs to a different league")
        if snapshot.outcome_windows != policy.outcome_windows:
            raise ValueError("Decision snapshot uses a different outcome-window contract")
        if snapshot.decision_id in snapshot_by_id:
            raise ValueError("Duplicate walk-forward decision ID")
        snapshot_by_id[snapshot.decision_id] = snapshot
    seen_windows = set()
    for outcome in outcomes:
        _verified_hash(outcome, "outcome_hash")
        if outcome.league_key != policy.league_key:
            raise ValueError("Outcome belongs to a different league")
        if outcome.window_weeks not in policy.outcome_windows:
            raise ValueError("Outcome window is not configured for this report")
        if outcome.captured_at > generated:
            raise LookAheadLeakage("Walk-forward report includes an outcome captured after report generation")
        snapshot = snapshot_by_id.get(outcome.decision_id)
        if snapshot is None or outcome.decision_snapshot_hash != snapshot.snapshot_hash:
            raise ValueError("Outcome is not attached to its immutable decision snapshot")
        key = (outcome.decision_id, outcome.window_weeks)
        if key in seen_windows:
            raise ValueError("Duplicate outcome window for one decision")
        seen_windows.add(key)
    expected_windows = {
        (snapshot.decision_id, window)
        for snapshot in snapshots
        for window in policy.outcome_windows
    }
    missing_windows = expected_windows - seen_windows
    status_counts = Counter(row.coverage_status for row in outcomes)
    coverage = WalkForwardCoverage(
        total=len(expected_windows),
        complete=status_counts["COMPLETE"],
        partial=status_counts["PARTIAL"],
        censored=status_counts["CENSORED"] + len(missing_windows),
        unavailable=status_counts["UNAVAILABLE"],
        unmatched=status_counts["UNMATCHED"],
        missing_outcome_windows=len(missing_windows),
    )
    window_summaries = []
    baseline_summaries = []
    for window in policy.outcome_windows:
        window_rows = tuple(row for row in outcomes if row.window_weeks == window)
        complete = tuple(row for row in window_rows if row.coverage_status == "COMPLETE")
        role_evaluable = tuple(row for row in complete if row.role_persisted is not None)
        hits = sum(row.role_persisted is True for row in role_evaluable)
        window_summaries.append(
            WalkForwardWindowSummary(
                window_weeks=window,
                sample_size=len(window_rows) + sum(
                    missing_window == window for _, missing_window in missing_windows
                ),
                complete_samples=len(complete),
                role_evaluable_samples=len(role_evaluable),
                role_hits=hits,
                role_hit_rate=round(hits / len(role_evaluable), 6) if role_evaluable else None,
                average_act_now_utility=_mean([row.act_now_roster_utility for row in complete if row.act_now_roster_utility is not None]),
                average_retain_drop_utility=_mean([row.retain_drop_roster_utility for row in complete if row.retain_drop_roster_utility is not None]),
                average_realized_gain=_mean([row.realized_act_now_minus_retain_drop for row in complete if row.realized_act_now_minus_retain_drop is not None]),
                severe_miss_rate=(round(sum(row.severe_miss is True for row in complete) / len(complete), 6) if complete else None),
                average_dropped_player_regret=_mean([row.act_now_regret for row in complete if row.act_now_regret is not None]),
            )
        )
        for baseline in BASELINE_NAMES:
            paired = tuple(
                (snapshot_by_id[row.decision_id], row)
                for row in role_evaluable
            )
            classified = tuple((snapshot, row, _baseline_call(snapshot, baseline)) for snapshot, row in paired)
            calls = tuple((snapshot, row, called) for snapshot, row, called in classified if called is not None)
            positives = tuple((snapshot, row) for snapshot, row, called in calls if called is True)
            true_positives = sum(row.role_persisted is True for _, row in positives)
            correct = sum(called == (row.role_persisted is True) for _, row, called in calls)
            chosen_utility = [
                row.act_now_roster_utility if called else row.retain_drop_roster_utility
                for _, row, called in calls
                if (row.act_now_roster_utility if called else row.retain_drop_roster_utility) is not None
            ]
            baseline_summaries.append(
                WalkForwardBaselineSummary(
                    baseline=baseline,
                    window_weeks=window,
                    eligible_samples=len(calls),
                    unavailable_signal_samples=len(classified) - len(calls),
                    positive_calls=len(positives),
                    true_positive_calls=true_positives,
                    hit_rate=(round(true_positives / len(positives), 6) if positives else None),
                    accuracy=(round(correct / len(calls), 6) if calls else None),
                    average_roster_utility=_mean(chosen_utility),
                    severe_miss_rate=(round(sum(row.severe_miss is True for _, row in positives) / len(positives), 6) if positives else None),
                    average_dropped_player_regret=_mean([row.act_now_regret for _, row in positives if row.act_now_regret is not None]),
                    calibration_error=None,
                    calibration_note="No baseline emits a probability; calibration error is not applicable",
                )
            )
    largest_window = max(policy.outcome_windows)
    final_rows = tuple(
        row
        for row in outcomes
        if row.window_weeks == largest_window
        and row.coverage_status == "COMPLETE"
        and row.realized_state != "UNKNOWN"
    )
    by_signal: dict[str, list[WaiverOutcomeWindow]] = defaultdict(list)
    for row in final_rows:
        by_signal[snapshot_by_id[row.decision_id].role_classification].append(row)
    signal_summaries = tuple(
        WalkForwardSignalSummary(
            signal_class=signal,
            sample_size=len(rows),
            hits=sum(row.role_persisted is True for row in rows),
            hit_rate=round(sum(row.role_persisted is True for row in rows) / len(rows), 6),
        )
        for signal, rows in sorted(by_signal.items())
    )
    window_rates = tuple(
        row.role_hit_rate
        for row in window_summaries
        if row.role_evaluable_samples >= policy.minimum_complete_samples
        and row.role_hit_rate is not None
    )
    sample_gate = len(final_rows) >= policy.minimum_complete_samples
    class_gate = bool(signal_summaries) and all(
        row.sample_size >= policy.minimum_samples_per_signal_class
        for row in signal_summaries
    )
    stability_gate = len(window_rates) == len(policy.outcome_windows) and (
        max(window_rates) - min(window_rates) <= policy.maximum_window_hit_rate_spread
        if window_rates
        else False
    )
    probability_allowed = sample_gate and class_gate and stability_gate
    if probability_allowed:
        state_counts = Counter(row.realized_state for row in final_rows)
        probabilities = tuple(
            (state, round(state_counts[state] / len(final_rows), 6))
            for state in ("MISS", "USEFUL_ROLE", "BREAKOUT")
        )
        probability_evidence = StateProbabilityEvidence(
            status="EMPIRICAL_ESTIMATE",
            reason="Minimum complete-sample, signal-class, and cross-window stability gates passed",
            source_window_weeks=largest_window,
            complete_samples=len(final_rows),
            stable=True,
            probabilities=probabilities,
        )
    else:
        failed = []
        if not sample_gate:
            failed.append(f"complete sample {len(final_rows)}/{policy.minimum_complete_samples}")
        if not class_gate:
            failed.append(f"signal-class minimum {policy.minimum_samples_per_signal_class} not met")
        if not stability_gate:
            failed.append("cross-window hit-rate stability not proved")
        probability_evidence = StateProbabilityEvidence(
            status="GATED_OFF",
            reason="; ".join(failed),
            source_window_weeks=largest_window,
            complete_samples=len(final_rows),
            stable=stability_gate,
            probabilities=(),
        )
    warnings = {
        "Walk-forward evidence is shadow-only and cannot change WA-015 labels or thresholds",
        "Hidden competing claims and claim success are not inferred",
    }
    if coverage.total != coverage.complete:
        warnings.add("Incomplete, censored, unavailable, and unmatched outcomes remain in coverage counts")
    if missing_windows:
        warnings.add(f"{len(missing_windows)} expected outcome window(s) are missing and counted as censored")
    role_unknown = sum(
        row.coverage_status == "COMPLETE" and row.role_persisted is None
        for row in outcomes
    )
    if role_unknown:
        warnings.add(
            f"{role_unknown} complete outcome record(s) lack evaluable opportunity-based role persistence"
        )
    if not probability_allowed:
        warnings.add("State probability estimation remains gated off; use break-even thresholds and sensitivity")
    retained_versions = tuple(sorted({snapshot.policy_version for snapshot in snapshots}))
    break_even_evidence = tuple(
        WalkForwardBreakEvenEvidence(
            decision_id=snapshot.decision_id,
            status=snapshot.break_even_status,
            hit_rate=snapshot.break_even_hit_rate,
            explanation=snapshot.break_even_explanation,
            sensitivity=snapshot.sensitivity,
        )
        for snapshot in sorted(snapshots, key=lambda row: row.decision_id)
    )
    base = WaiverWalkForwardReport(
        schema_version=1,
        product="WAIVER ASSISTANT",
        operation="WAIVER WALK-FORWARD REPORT",
        league_key=policy.league_key,
        generated_at=generated,
        walk_forward_policy_version=policy.version,
        walk_forward_policy_hash=policy.policy_hash,
        retained_waiver_policy_versions=retained_versions,
        decision_count=len(snapshots),
        coverage=coverage,
        windows=tuple(window_summaries),
        baselines=tuple(baseline_summaries),
        signal_classes=signal_summaries,
        break_even_evidence=break_even_evidence,
        state_probability_evidence=probability_evidence,
        policy_promotion_performed=False,
        sleeper_write_performed=False,
        warnings=tuple(sorted(warnings)),
        report_hash="",
    )
    return replace(base, report_hash=stable_hash(asdict(base)))


def save_walk_forward_report(report: WaiverWalkForwardReport, path: str | Path) -> Path:
    _verified_hash(report, "report_hash")
    return atomic_write_json(path, report)


def load_walk_forward_report(path: str | Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if int(value.get("schema_version") or 0) != 1:
        raise ValueError("Unsupported Waiver walk-forward report schema")
    if str(value.get("product") or "") != "WAIVER ASSISTANT":
        raise ValueError("Walk-forward report must be Waiver-scoped")
    if value.get("sleeper_write_performed") is not False:
        raise ValueError("Walk-forward report violates the Sleeper read-only guard")
    if value.get("policy_promotion_performed") is not False:
        raise ValueError("WA-016 report cannot promote a Waiver policy")
    expected = str(value.get("report_hash") or "")
    unsigned = dict(value)
    unsigned["report_hash"] = ""
    if not expected or stable_hash(unsigned) != expected:
        raise ValueError("Waiver walk-forward report failed hash verification")
    value["current"] = False
    value["offline_replay"] = True
    value.setdefault("warnings", []).append("OFFLINE/NON-CURRENT Waiver walk-forward report")
    return value


def format_walk_forward_report(report: WaiverWalkForwardReport) -> str:
    lines = [
        f"WAIVER WALK-FORWARD - {report.league_key}",
        f"Decisions: {report.decision_count}; outcome records: {report.coverage.total}; complete: {report.coverage.complete}",
        f"Coverage exceptions: partial {report.coverage.partial}; censored {report.coverage.censored}; unavailable {report.coverage.unavailable}; unmatched {report.coverage.unmatched}; missing windows {report.coverage.missing_outcome_windows}",
    ]
    lines.extend(
        f"Window {row.window_weeks}: complete {row.complete_samples}/{row.sample_size}; role-evaluable {row.role_evaluable_samples}; role hit rate "
        + (f"{row.role_hit_rate:.1%}" if row.role_hit_rate is not None else "unavailable")
        + "; average ACT_NOW minus RETAIN_DROP "
        + (f"{row.average_realized_gain:+.2f}" if row.average_realized_gain is not None else "unavailable")
        + "; severe miss rate "
        + (f"{row.severe_miss_rate:.1%}" if row.severe_miss_rate is not None else "unavailable")
        + "; average dropped-player regret "
        + (f"{row.average_dropped_player_regret:.2f}" if row.average_dropped_player_regret is not None else "unavailable")
        for row in report.windows
    )
    lines.extend(
        f"Baseline {row.baseline} W{row.window_weeks}: calls {row.positive_calls}/{row.eligible_samples}; hit rate "
        + (f"{row.hit_rate:.1%}" if row.hit_rate is not None else "unavailable")
        + "; average roster utility "
        + (f"{row.average_roster_utility:.2f}" if row.average_roster_utility is not None else "unavailable")
        + "; severe miss rate "
        + (f"{row.severe_miss_rate:.1%}" if row.severe_miss_rate is not None else "unavailable")
        + "; dropped-player regret "
        + (f"{row.average_dropped_player_regret:.2f}" if row.average_dropped_player_regret is not None else "unavailable")
        + "; calibration error not applicable (no probability emitted)"
        for row in report.baselines
    )
    lines.append(
        f"Decision-time break-even evidence retained: {len(report.break_even_evidence)} threshold(s) with hypothetical sensitivity rows"
    )
    lines.append(
        f"State probabilities: {report.state_probability_evidence.status}; {report.state_probability_evidence.reason}"
    )
    lines.append(
        "Policy promotion: none; retained "
        + (", ".join(report.retained_waiver_policy_versions) or "no source policy")
    )
    lines.append("Sleeper write performed: false")
    return "\n".join(lines)
