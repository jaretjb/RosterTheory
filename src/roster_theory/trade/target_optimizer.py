from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from itertools import combinations
from typing import Callable, Mapping, Sequence

from roster_theory.core.errors import CoverageIncomplete, RosterIllegal
from roster_theory.core.models import FantasyTeam, Player, Projection
from roster_theory.core.provenance import stable_hash
from roster_theory.inseason.evaluation import (
    InSeasonContext,
    InSeasonWeek,
    WeeklyProjectionMatrix,
    build_weekly_projection_matrix,
    weighted_lineup_score,
)
from roster_theory.trade.boards import ValueBoard
from roster_theory.trade.consolidation import ConsolidationEvidence, analyze_consolidation
from roster_theory.trade.evaluation import (
    EvaluationOptions,
    PlayerAsset,
    RosterDiagnosis,
    TradeEvaluation,
    TradePackage,
    diagnose_roster,
    evaluate_trade,
)
from roster_theory.trade.market import TradeMarketEvidence
from roster_theory.trade.snapshot import SKILL_POSITIONS, TradeSnapshot, assert_current
from roster_theory.trade.targets import (
    TARGET_KINDS,
    TargetDiscoveryResult,
    TradeTarget,
    summarize_projection_warnings,
)


PACKAGE_SIZES = ((1, 1), (2, 1), (1, 2), (2, 2))
PACKAGE_SIZE_LABELS = tuple(f"{sent}-for-{received}" for sent, received in PACKAGE_SIZES)


@dataclass(frozen=True, slots=True)
class ExactEvaluationBudget:
    lane: str
    package_size: str
    limit: int

    def __post_init__(self) -> None:
        if self.lane not in TARGET_KINDS:
            raise ValueError(f"Unsupported target lane: {self.lane}")
        if self.package_size not in PACKAGE_SIZE_LABELS:
            raise ValueError(f"Unsupported package size: {self.package_size}")
        if self.limit < 0:
            raise ValueError("Exact-evaluation budget cannot be negative")


def uniform_exact_budgets(limit: int) -> tuple[ExactEvaluationBudget, ...]:
    if limit < 0:
        raise ValueError("Exact-evaluation budget cannot be negative")
    return tuple(
        ExactEvaluationBudget(lane, package_size, limit)
        for lane in TARGET_KINDS
        for package_size in PACKAGE_SIZE_LABELS
    )


@dataclass(frozen=True, slots=True)
class TargetOptimizerConfig:
    policy_id: str
    outgoing_pool_limit: int
    incoming_pool_limit: int
    construction_market_band_ratio: float
    construction_market_band_floor: float
    fair_market_band_ratio: float
    fair_market_band_floor: float
    consolidation_premium_policy_id: str
    consolidation_premium_ratio: float
    minimum_consolidation_starter_upgrade: float
    minimum_partner_asset_lineup_use: float
    minimum_partner_asset_depth_use: float
    minimum_user_lineup_gain: float
    partner_lineup_floor: float
    partner_selected_floor: float
    maximum_partner_depth_loss: float
    max_results_per_lane: int
    exact_budgets: tuple[ExactEvaluationBudget, ...]

    def __post_init__(self) -> None:
        if not self.policy_id.strip():
            raise ValueError("Target optimizer policy_id is required")
        if self.outgoing_pool_limit <= 0 or self.incoming_pool_limit <= 0:
            raise ValueError("Target optimizer pool limits must be positive")
        bands = (
            self.construction_market_band_ratio,
            self.construction_market_band_floor,
            self.fair_market_band_ratio,
            self.fair_market_band_floor,
        )
        if any(value < 0.0 for value in bands):
            raise ValueError("Market-band limits cannot be negative")
        if self.fair_market_band_ratio > self.construction_market_band_ratio:
            raise ValueError("Fair market-band ratio cannot exceed the construction ratio")
        if self.fair_market_band_floor > self.construction_market_band_floor:
            raise ValueError("Fair market-band floor cannot exceed the construction floor")
        if self.minimum_user_lineup_gain <= 0.0:
            raise ValueError("minimum_user_lineup_gain must be positive")
        if not self.consolidation_premium_policy_id.strip():
            raise ValueError("Consolidation premium policy_id is required")
        if not 0.0 <= self.consolidation_premium_ratio <= 1.0:
            raise ValueError("Consolidation premium ratio must be between zero and one")
        if self.minimum_consolidation_starter_upgrade <= 0.0:
            raise ValueError("Consolidation starter upgrade threshold must be positive")
        if self.minimum_partner_asset_lineup_use < 0.0 or self.minimum_partner_asset_depth_use < 0.0:
            raise ValueError("Partner asset-use thresholds cannot be negative")
        if self.maximum_partner_depth_loss < 0.0:
            raise ValueError("maximum_partner_depth_loss cannot be negative")
        if self.max_results_per_lane <= 0:
            raise ValueError("max_results_per_lane must be positive")
        expected = {
            (lane, package_size) for lane in TARGET_KINDS for package_size in PACKAGE_SIZE_LABELS
        }
        keys = [(row.lane, row.package_size) for row in self.exact_budgets]
        if len(keys) != len(set(keys)):
            raise ValueError("Exact-evaluation budgets contain duplicate lane/size entries")
        if set(keys) != expected:
            missing = sorted(expected - set(keys))
            extra = sorted(set(keys) - expected)
            raise ValueError(
                f"Exact-evaluation budgets must cover every lane/size; missing={missing}, "
                f"extra={extra}"
            )

    def budget(self, lane: str, package_size: str) -> int:
        return next(
            row.limit
            for row in self.exact_budgets
            if row.lane == lane and row.package_size == package_size
        )


@dataclass(frozen=True, slots=True)
class OutgoingSeedEvidence:
    lane: str
    target_player_id: str
    opponent_roster_id: str
    player_id: str
    seed_rank: int
    selected_value: float
    market_price: float
    exact_marginal_lineup_cost: float
    usable_surplus: bool
    addresses_partner_need: bool
    price_distance_from_target: float


@dataclass(frozen=True, slots=True)
class PremiumSensitivity:
    ratio: float
    user_price_delta: float
    allowed_difference: float
    within_band: bool
    status: str


@dataclass(frozen=True, slots=True)
class PackageMarketFairness:
    mode: str
    status: str
    sent_value: float
    received_value: float
    consolidation_premium_policy_id: str | None
    consolidation_premium_ratio: float | None
    consolidation_premium_value: float | None
    premium_adjusted_received_value: float | None
    raw_user_price_delta: float
    user_price_delta: float
    allowed_difference: float
    within_band: bool
    warnings: tuple[str, ...]
    premium_sensitivity: tuple[PremiumSensitivity, ...] = ()


@dataclass(frozen=True, slots=True)
class EvaluatedPackageDecision:
    lane: str
    primary_target_player_id: str
    generated_by_target_ids: tuple[str, ...]
    opponent_roster_id: str
    package_size: str
    sent_player_ids: tuple[str, ...]
    received_player_ids: tuple[str, ...]
    intrinsic_outcome: str
    market_fairness: PackageMarketFairness
    consolidation: ConsolidationEvidence | None
    complete_and_legal: bool
    user_depth_passed: bool
    user_downside_passed: bool
    partner_plausible: bool
    partner_need_hit: bool
    received_asset_dropped: bool
    forced_add: bool
    forced_drop: bool
    accepted: bool
    reason: str
    user_weighted_lineup_delta: float
    user_selected_delta: float | None
    user_market_ecr_delta: float
    cross_model_agreement: bool
    user_depth_delta: float
    user_downside_delta: float
    partner_weighted_lineup_delta: float
    partner_selected_delta: float | None
    partner_depth_delta: float
    evaluation_hash: str


@dataclass(frozen=True, slots=True)
class TargetPackageOpportunity:
    lane: str
    primary_target_player_id: str
    generated_by_target_ids: tuple[str, ...]
    opponent_roster_id: str
    package_size: str
    sent_player_ids: tuple[str, ...]
    received_player_ids: tuple[str, ...]
    intrinsic_outcome: str
    market_fairness: PackageMarketFairness
    consolidation: ConsolidationEvidence | None
    objective_tags: tuple[str, ...]
    user_weighted_lineup_delta: float
    user_selected_delta: float
    user_market_ecr_delta: float
    cross_model_agreement: bool
    user_depth_delta: float
    user_downside_delta: float
    partner_weighted_lineup_delta: float
    partner_selected_delta: float
    partner_depth_delta: float
    forced_add: bool
    forced_drop: bool
    evaluation: TradeEvaluation


@dataclass(frozen=True, slots=True)
class LanePackageCoverage:
    lane: str
    package_size: str
    enumerated: int
    prefiltered: int
    deduplicated: int
    eligible: int
    budget_limit: int
    runtime_pruned: int
    attempted: int
    evaluated: int
    accepted: int


@dataclass(frozen=True, slots=True)
class TargetPackageStatus:
    lane: str
    player_id: str
    status: str
    partner_credible_offer_found: bool
    passing_offer_count: int
    obtainable: bool


@dataclass(frozen=True, slots=True)
class TargetPackageSearchResult:
    schema_version: int
    manifest_id: str
    league_key: str
    horizon: str
    target_evidence_hash: str
    pricing_mode: str
    config: TargetOptimizerConfig
    target_statuses: tuple[TargetPackageStatus, ...]
    outgoing_seeds: tuple[OutgoingSeedEvidence, ...]
    opportunities: tuple[TargetPackageOpportunity, ...]
    evaluated_decisions: tuple[EvaluatedPackageDecision, ...]
    coverage: tuple[LanePackageCoverage, ...]
    rejection_counts: tuple[tuple[str, str, str, int], ...]
    warnings: tuple[str, ...]
    evidence_hash: str


@dataclass(frozen=True, slots=True)
class _PlayerMetrics:
    removal_cost: float
    acquisition_gain: float


@dataclass(frozen=True, slots=True)
class _Candidate:
    lane: str
    primary_target_player_id: str
    primary_target_rank: int
    generated_by_target_ids: tuple[str, ...]
    opponent_roster_id: str
    sent_player_ids: tuple[str, ...]
    received_player_ids: tuple[str, ...]
    package_size: str
    pricing_mode: str
    broad_market_distance: float
    fair_market_distance: float
    fair_within_band: bool
    estimated_user_lineup_gain: float
    estimated_partner_lineup_gain: float
    partner_need_hits: int
    partner_prefilter_passed: bool


def _context(snapshot: TradeSnapshot) -> InSeasonContext:
    return InSeasonContext(
        players=snapshot.players,
        roster_positions=snapshot.league.roster_positions,
        weeks=tuple(
            InSeasonWeek(week.week, week.playoff, week.bye_teams) for week in snapshot.weeks
        ),
        unowned_player_ids=snapshot.free_agent_ids,
    )


def _active_roster(team: FantasyTeam) -> set[str]:
    return set(team.player_ids) - set(team.reserve_ids)


def _eligible_players(
    snapshot: TradeSnapshot,
    team: FantasyTeam,
    valued_player_ids: set[str],
) -> tuple[str, ...]:
    player_by_id = {player.player_id: player for player in snapshot.players}
    tradeable = set(snapshot.tradeable_player_ids)
    reserves = set(team.reserve_ids)
    return tuple(
        sorted(
            player_id
            for player_id in team.player_ids
            if player_id not in reserves
            and player_id in tradeable
            and player_id in valued_player_ids
            and (player := player_by_id.get(player_id)) is not None
            and bool(
                SKILL_POSITIONS.intersection(position.upper() for position in player.positions)
            )
        )
    )


def _diagnosis_sets(diagnosis: RosterDiagnosis) -> tuple[set[str], set[str]]:
    needs = {row.position for row in diagnosis.positions if row.need_above_waiver > 0.0}
    surplus = {
        player_id for row in diagnosis.positions for player_id in row.usable_surplus_player_ids
    }
    return needs, surplus


def _positions(player: Player) -> set[str]:
    return {position.upper() for position in player.positions}


def _package_size(sent: Sequence[str], received: Sequence[str]) -> str:
    return f"{len(sent)}-for-{len(received)}"


def _allowed_difference(
    sent_value: float,
    received_value: float,
    ratio: float,
    floor: float,
) -> float:
    return round(max(floor, ratio * max(sent_value, received_value, 1.0)), 6)


def _price_map(
    target_result: TargetDiscoveryResult,
    trade_market: TradeMarketEvidence,
    market_ecr_board: ValueBoard,
    required_player_ids: set[str],
) -> tuple[dict[str, float], str, tuple[str, ...]]:
    if target_result.pricing_mode == "ECR-PROXY":
        values = {row.player_id: float(row.reconciled_vorp) for row in market_ecr_board.players}
        missing = sorted(required_player_ids - set(values))
        if missing:
            raise CoverageIncomplete(
                "Market-ECR proxy misses rostered tradeable players: " + ", ".join(missing)
            )
        warnings = tuple(
            dict.fromkeys(
                (
                    *trade_market.warnings,
                    "ECR-PROXY constrains candidate construction but cannot make chart-fairness "
                    "claims",
                )
            )
        )
        return values, "ECR-PROXY", warnings
    board = trade_market.board
    if board is None or board.mode != (
        trade_market.mode if target_result.pricing_mode == "MIXED_CURRENT_PRIOR"
        else target_result.pricing_mode
    ):
        raise CoverageIncomplete("Target discovery and optimizer trade-market modes do not match")
    values = {row.player_id: float(row.value) for row in board.prices}
    missing = sorted(required_player_ids - set(values))
    warnings = list(board.warnings)
    warnings.extend(board.stamp.warnings)
    if missing and target_result.pricing_mode != "MIXED_CURRENT_PRIOR":
        warnings.append(
            f"{len(missing)} eligible rostered assets lack a selected-chart price; "
            "packages containing them were excluded"
        )
    if not board.league_scoring_exact:
        warnings.append(
            "Direct market price uses the provider's reception/TEP blend, not exact league scoring"
        )
    return values, target_result.pricing_mode, tuple(dict.fromkeys(warnings))


def _fairness(
    sent: Sequence[str],
    received: Sequence[str],
    prices: Mapping[str, float],
    mode: str,
    ratio: float,
    floor: float,
    warnings: tuple[str, ...],
    *,
    consolidation: bool,
    premium_policy_id: str,
    premium_ratio: float,
) -> PackageMarketFairness:
    sent_value = round(sum(prices[player_id] for player_id in sent), 6)
    received_value = round(sum(prices[player_id] for player_id in received), 6)
    premium_applies = consolidation and mode not in {"ECR-PROXY", "PRIOR_WEEK_MARKET"}
    premium_value = round(received_value * premium_ratio, 6) if premium_applies else None
    adjusted_received = round(received_value + premium_value, 6) if premium_value is not None else None
    comparison_value = adjusted_received if adjusted_received is not None else received_value
    delta = round(comparison_value - sent_value, 6)
    allowed = _allowed_difference(sent_value, comparison_value, ratio, floor)
    within = abs(delta) <= allowed
    if mode == "ECR-PROXY":
        status = "ECR-PROXY"
    elif mode == "PRIOR_WEEK_MARKET":
        status = "PRIOR_WEEK_MARKET"
    elif within:
        status = "FAIR"
    elif delta > 0.0:
        status = "USER_UNDERPAY"
    else:
        status = "USER_OVERPAY"
    sensitivity: list[PremiumSensitivity] = []
    if premium_applies:
        for candidate_ratio in sorted({0.0, 0.05, 0.10, premium_ratio}):
            candidate_received = round(received_value * (1.0 + candidate_ratio), 6)
            candidate_delta = round(candidate_received - sent_value, 6)
            candidate_allowed = _allowed_difference(
                sent_value, candidate_received, ratio, floor
            )
            candidate_within = abs(candidate_delta) <= candidate_allowed
            sensitivity.append(PremiumSensitivity(
                ratio=candidate_ratio,
                user_price_delta=candidate_delta,
                allowed_difference=round(candidate_allowed, 6),
                within_band=candidate_within,
                status=(
                    "FAIR" if candidate_within else
                    "USER_UNDERPAY" if candidate_delta > 0 else "USER_OVERPAY"
                ),
            ))
    return PackageMarketFairness(
        mode=mode,
        status=status,
        sent_value=sent_value,
        received_value=received_value,
        consolidation_premium_policy_id=premium_policy_id if premium_applies else None,
        consolidation_premium_ratio=premium_ratio if premium_applies else None,
        consolidation_premium_value=premium_value,
        premium_adjusted_received_value=adjusted_received,
        raw_user_price_delta=round(received_value - sent_value, 6),
        user_price_delta=delta,
        allowed_difference=allowed,
        within_band=within,
        warnings=warnings,
        premium_sensitivity=tuple(sensitivity),
    )


def _player_metrics(
    *,
    context: InSeasonContext,
    matrix: WeeklyProjectionMatrix,
    options: EvaluationOptions,
    teams_by_id: Mapping[str, FantasyTeam],
    base_scores: Mapping[str, float],
    roster_id: str,
    player_id: str,
    acquiring: bool,
) -> _PlayerMetrics:
    roster = _active_roster(teams_by_id[roster_id])
    if acquiring:
        acquisition = round(
            weighted_lineup_score(context, matrix, roster | {player_id}, options)
            - base_scores[roster_id],
            3,
        )
        return _PlayerMetrics(0.0, acquisition)
    removal = round(
        base_scores[roster_id]
        - weighted_lineup_score(context, matrix, roster - {player_id}, options),
        3,
    )
    return _PlayerMetrics(removal, 0.0)


def _outgoing_seeds(
    *,
    snapshot: TradeSnapshot,
    target: TradeTarget,
    opponent_id: str,
    user_players: Sequence[str],
    selected_values: Mapping[str, float],
    prices: Mapping[str, float],
    player_by_id: Mapping[str, Player],
    partner_needs: set[str],
    user_surplus: set[str],
    metric: Callable[[str, str, bool], _PlayerMetrics],
) -> tuple[OutgoingSeedEvidence, ...]:
    target_price = prices[target.player_id]
    rows = []
    for player_id in user_players:
        player_metrics = metric(snapshot.user_roster_id, player_id, False)
        rows.append(
            OutgoingSeedEvidence(
                lane=target.kind,
                target_player_id=target.player_id,
                opponent_roster_id=opponent_id,
                player_id=player_id,
                seed_rank=0,
                selected_value=round(selected_values[player_id], 6),
                market_price=round(prices[player_id], 6),
                exact_marginal_lineup_cost=player_metrics.removal_cost,
                usable_surplus=player_id in user_surplus,
                addresses_partner_need=bool(_positions(player_by_id[player_id]) & partner_needs),
                price_distance_from_target=round(abs(prices[player_id] - target_price), 6),
            )
        )
    ordered = sorted(
        rows,
        key=lambda row: (
            not row.usable_surplus,
            not row.addresses_partner_need,
            row.exact_marginal_lineup_cost,
            row.price_distance_from_target,
            -row.market_price,
            row.player_id,
        ),
    )
    return tuple(replace(row, seed_rank=index) for index, row in enumerate(ordered, 1))


def _candidate_sort_key(candidate: _Candidate) -> tuple[object, ...]:
    return (
        not candidate.fair_within_band,
        -candidate.estimated_user_lineup_gain,
        -candidate.partner_need_hits,
        -candidate.estimated_partner_lineup_gain,
        candidate.fair_market_distance,
        candidate.primary_target_rank,
        candidate.sent_player_ids,
        candidate.received_player_ids,
        candidate.opponent_roster_id,
    )


def _merge_candidate(existing: _Candidate, incoming: _Candidate) -> _Candidate:
    target_ids = tuple(
        dict.fromkeys((*existing.generated_by_target_ids, *incoming.generated_by_target_ids))
    )
    preferred = min(
        (existing, incoming),
        key=lambda row: (row.primary_target_rank, row.primary_target_player_id),
    )
    return replace(preferred, generated_by_target_ids=tuple(sorted(target_ids)))


def _enumerate_for_target(
    *,
    snapshot: TradeSnapshot,
    target: TradeTarget,
    opponent_id: str,
    user_pool: Sequence[str],
    opponent_pool: Sequence[str],
    prices: Mapping[str, float],
    player_by_id: Mapping[str, Player],
    partner_needs: set[str],
    target_owner_disposable: bool,
    package_delta: Callable[[str, Sequence[str], Sequence[str]], float],
    config: TargetOptimizerConfig,
    pricing_mode: str,
) -> tuple[_Candidate, ...]:
    fixed_sent = (target.player_id,) if target.kind == "SELL_HIGH" else ()
    fixed_received = () if target.kind == "SELL_HIGH" else (target.player_id,)
    optional_sent = tuple(player_id for player_id in user_pool if player_id not in fixed_sent)
    optional_received = tuple(
        player_id for player_id in opponent_pool if player_id not in fixed_received
    )
    candidates: list[_Candidate] = []
    for sent_count, received_count in PACKAGE_SIZES:
        if target.kind == "CONSOLIDATE" and (sent_count, received_count) != (2, 1):
            continue
        extra_sent = sent_count - len(fixed_sent)
        extra_received = received_count - len(fixed_received)
        if extra_sent < 0 or extra_received < 0:
            continue
        if extra_sent > len(optional_sent) or extra_received > len(optional_received):
            continue
        for sent_extra in combinations(optional_sent, extra_sent):
            sent = tuple(sorted((*fixed_sent, *sent_extra)))
            for received_extra in combinations(optional_received, extra_received):
                received = tuple(sorted((*fixed_received, *received_extra)))
                sent_value = sum(prices[player_id] for player_id in sent)
                received_value = sum(prices[player_id] for player_id in received)
                comparison_value = (
                    received_value * (1.0 + config.consolidation_premium_ratio)
                    if target.kind == "CONSOLIDATE"
                    and pricing_mode not in {"ECR-PROXY", "PRIOR_WEEK_MARKET"}
                    else received_value
                )
                difference = abs(comparison_value - sent_value)
                broad_allowed = _allowed_difference(
                    sent_value,
                    comparison_value,
                    config.construction_market_band_ratio,
                    config.construction_market_band_floor,
                )
                fair_allowed = _allowed_difference(
                    sent_value,
                    comparison_value,
                    config.fair_market_band_ratio,
                    config.fair_market_band_floor,
                )
                user_gain = package_delta(snapshot.user_roster_id, sent, received)
                partner_gain = package_delta(opponent_id, received, sent)
                partner_need_hits = sum(
                    bool(_positions(player_by_id[player_id]) & partner_needs) for player_id in sent
                )
                partner_prefilter = bool(
                    partner_need_hits
                    or target_owner_disposable
                    or partner_gain >= config.partner_lineup_floor
                )
                candidates.append(
                    _Candidate(
                        lane=target.kind,
                        primary_target_player_id=target.player_id,
                        primary_target_rank=target.rank_in_lane,
                        generated_by_target_ids=(target.player_id,),
                        opponent_roster_id=opponent_id,
                        sent_player_ids=sent,
                        received_player_ids=received,
                        package_size=_package_size(sent, received),
                        pricing_mode=pricing_mode,
                        broad_market_distance=round(difference - broad_allowed, 6),
                        fair_market_distance=round(difference - fair_allowed, 6),
                        fair_within_band=difference <= fair_allowed,
                        estimated_user_lineup_gain=round(user_gain, 3),
                        estimated_partner_lineup_gain=round(partner_gain, 3),
                        partner_need_hits=partner_need_hits,
                        partner_prefilter_passed=partner_prefilter,
                    )
                )
    return tuple(candidates)


def _gate_passed(evaluation: TradeEvaluation, name: str) -> bool:
    if evaluation.decision is None:
        return False
    return any(gate.name == name and gate.passed for gate in evaluation.decision.gates)


def _selected_delta(evaluation: TradeEvaluation, index: int) -> float | None:
    impact = evaluation.ownership_impacts[index]
    if impact.selected_package_delta is None or impact.selected_secondary_delta is None:
        return None
    return round(impact.selected_package_delta + impact.selected_secondary_delta, 3)


def _received_asset_dropped(evaluation: TradeEvaluation) -> bool:
    incoming = {
        evaluation.package.roster_a_id: {asset.player_id for asset in evaluation.package.from_b},
        evaluation.package.roster_b_id: {asset.player_id for asset in evaluation.package.from_a},
    }
    return any(
        move.kind == "DROP"
        and bool(set(move.chosen_player_ids) & incoming.get(move.roster_id, set()))
        for move in evaluation.secondary_moves
    )


def _exact_decision(
    *,
    candidate: _Candidate,
    evaluation: TradeEvaluation,
    fairness: PackageMarketFairness,
    consolidation: ConsolidationEvidence | None,
    diagnoses: Mapping[str, RosterDiagnosis],
    player_by_id: Mapping[str, Player],
    config: TargetOptimizerConfig,
    options: EvaluationOptions,
) -> EvaluatedPackageDecision:
    user_team, partner_team = evaluation.team_impacts
    user_selected = _selected_delta(evaluation, 0)
    partner_selected = _selected_delta(evaluation, 1)
    user_market_ecr = round(
        evaluation.ownership_impacts[0].market_package_delta
        + evaluation.ownership_impacts[0].market_secondary_delta,
        3,
    )
    cross_model_agreement = bool(
        user_selected is not None
        and (
            (user_selected >= 0.0 and user_market_ecr >= 0.0)
            or (user_selected <= 0.0 and user_market_ecr <= 0.0)
        )
    )
    complete = (
        _gate_passed(evaluation, "complete_evidence")
        and "MANUAL-LEGALITY" not in set(evaluation.modes)
        and partner_selected is not None
    )
    user_depth_passed = user_team.depth_delta >= -options.max_depth_loss
    downside_passed = (
        evaluation.risk_impacts[0].offense_downside_loss_delta <= options.max_downside_increase
    )
    user_value_passed = user_selected is not None and user_selected >= options.user_selected_floor
    if (
        complete
        and user_depth_passed
        and downside_passed
        and user_value_passed
        and user_team.weighted_delta >= config.minimum_user_lineup_gain
    ):
        intrinsic = "WIN"
    elif (
        complete
        and user_depth_passed
        and downside_passed
        and user_value_passed
        and user_team.weighted_delta >= 0.0
    ):
        intrinsic = "NEUTRAL"
    else:
        intrinsic = "LOSS"
    partner_needs, _ = _diagnosis_sets(diagnoses[candidate.opponent_roster_id])
    partner_need_hit = any(
        _positions(player_by_id[player_id]) & partner_needs
        for player_id in candidate.sent_player_ids
    )
    partner_depth_passed = partner_team.depth_delta >= -config.maximum_partner_depth_loss
    partner_value_passed = (
        partner_selected is not None and partner_selected >= config.partner_selected_floor
    )
    partner_plausible = partner_depth_passed and (
        partner_team.weighted_delta >= config.partner_lineup_floor
        or (partner_need_hit and partner_value_passed)
    )
    dropped = _received_asset_dropped(evaluation)
    forced_add = any(move.kind == "ADD" for move in evaluation.secondary_moves)
    forced_drop = any(move.kind == "DROP" for move in evaluation.secondary_moves)
    if not complete:
        reason = "INCOMPLETE_OR_ILLEGAL"
    elif not user_depth_passed:
        reason = "USER_DEPTH_GATE"
    elif not downside_passed:
        reason = "USER_DOWNSIDE_GATE"
    elif intrinsic != "WIN":
        reason = f"INTRINSIC_{intrinsic}"
    elif fairness.mode == "PRIOR_WEEK_MARKET":
        reason = "STALE_MARKET_INDICATIVE_ONLY"
    elif not fairness.within_band:
        reason = "MARKET_FAIRNESS_GATE"
    elif consolidation is not None and not consolidation.secondary_moves_complete:
        reason = "CONSOLIDATION_SECONDARY_MOVES"
    elif consolidation is not None and not consolidation.starter_upgrade_passed:
        reason = "CONSOLIDATION_STARTER_UPGRADE"
    elif consolidation is not None and not consolidation.both_outgoing_assets_used:
        reason = "CONSOLIDATION_PARTNER_ASSET_USE"
    elif dropped:
        reason = "RECEIVED_ASSET_DROPPED"
    elif not partner_plausible:
        reason = "PARTNER_PLAUSIBILITY_GATE"
    else:
        reason = "ACCEPTED"
    accepted = reason == "ACCEPTED"
    return EvaluatedPackageDecision(
        lane=candidate.lane,
        primary_target_player_id=candidate.primary_target_player_id,
        generated_by_target_ids=candidate.generated_by_target_ids,
        opponent_roster_id=candidate.opponent_roster_id,
        package_size=candidate.package_size,
        sent_player_ids=candidate.sent_player_ids,
        received_player_ids=candidate.received_player_ids,
        intrinsic_outcome=intrinsic,
        market_fairness=fairness,
        consolidation=consolidation,
        complete_and_legal=complete,
        user_depth_passed=user_depth_passed,
        user_downside_passed=downside_passed,
        partner_plausible=partner_plausible,
        partner_need_hit=partner_need_hit,
        received_asset_dropped=dropped,
        forced_add=forced_add,
        forced_drop=forced_drop,
        accepted=accepted,
        reason=reason,
        user_weighted_lineup_delta=user_team.weighted_delta,
        user_selected_delta=user_selected,
        user_market_ecr_delta=user_market_ecr,
        cross_model_agreement=cross_model_agreement,
        user_depth_delta=user_team.depth_delta,
        user_downside_delta=evaluation.risk_impacts[0].offense_downside_loss_delta,
        partner_weighted_lineup_delta=partner_team.weighted_delta,
        partner_selected_delta=partner_selected,
        partner_depth_delta=partner_team.depth_delta,
        evaluation_hash=evaluation.evidence_hash,
    )


def _dominates(first: TargetPackageOpportunity, second: TargetPackageOpportunity) -> bool:
    first_values = (
        first.user_weighted_lineup_delta,
        first.user_selected_delta,
        float(first.cross_model_agreement),
        first.partner_weighted_lineup_delta,
        -abs(first.market_fairness.user_price_delta),
        -first.user_downside_delta,
    )
    second_values = (
        second.user_weighted_lineup_delta,
        second.user_selected_delta,
        float(second.cross_model_agreement),
        second.partner_weighted_lineup_delta,
        -abs(second.market_fairness.user_price_delta),
        -second.user_downside_delta,
    )
    return all(a >= b for a, b in zip(first_values, second_values)) and any(
        a > b for a, b in zip(first_values, second_values)
    )


def _frontier(
    opportunities: Sequence[TargetPackageOpportunity],
    limit: int,
) -> tuple[TargetPackageOpportunity, ...]:
    retained = tuple(
        row
        for row in opportunities
        if not any(other is not row and _dominates(other, row) for other in opportunities)
    )
    if not retained:
        return ()
    objectives = {
        "BEST_INTRINSIC": max(
            retained,
            key=lambda row: (
                row.user_weighted_lineup_delta,
                row.user_selected_delta,
                row.sent_player_ids,
                row.received_player_ids,
            ),
        ),
        "BEST_PARTNER": max(
            retained,
            key=lambda row: (
                row.partner_weighted_lineup_delta,
                row.partner_selected_delta,
                row.sent_player_ids,
                row.received_player_ids,
            ),
        ),
        "CROSS_MODEL": max(
            retained,
            key=lambda row: (
                row.cross_model_agreement,
                row.user_weighted_lineup_delta,
                row.user_selected_delta,
                row.sent_player_ids,
                row.received_player_ids,
            ),
        ),
        "LOWER_RISK": min(
            retained,
            key=lambda row: (
                row.user_downside_delta,
                -row.user_weighted_lineup_delta,
                row.sent_player_ids,
                row.received_player_ids,
            ),
        ),
        "MARKET_CLOSEST": min(
            retained,
            key=lambda row: (
                abs(row.market_fairness.user_price_delta),
                -row.user_weighted_lineup_delta,
                row.sent_player_ids,
                row.received_player_ids,
            ),
        ),
        "SIMPLE": min(
            retained,
            key=lambda row: (
                len(row.sent_player_ids) + len(row.received_player_ids),
                row.forced_drop,
                -row.user_weighted_lineup_delta,
                row.sent_player_ids,
                row.received_player_ids,
            ),
        ),
    }
    tags: dict[tuple[tuple[str, ...], tuple[str, ...], str], list[str]] = {}
    for name, row in objectives.items():
        key = (row.sent_player_ids, row.received_player_ids, row.opponent_roster_id)
        tags.setdefault(key, []).append(name)
    tagged = tuple(
        replace(
            row,
            objective_tags=tuple(
                sorted(
                    tags.get(
                        (row.sent_player_ids, row.received_player_ids, row.opponent_roster_id),
                        ("PARETO_ALTERNATIVE",),
                    )
                )
            ),
        )
        for row in retained
    )
    ordered = sorted(
        tagged,
        key=lambda row: (
            -row.user_weighted_lineup_delta,
            -row.user_selected_delta,
            -float(row.cross_model_agreement),
            -row.partner_weighted_lineup_delta,
            abs(row.market_fairness.user_price_delta),
            row.user_downside_delta,
            len(row.sent_player_ids) + len(row.received_player_ids),
            row.forced_drop,
            row.sent_player_ids,
            row.received_player_ids,
            row.opponent_roster_id,
        ),
    )
    representatives = {
        (row.sent_player_ids, row.received_player_ids, row.opponent_roster_id)
        for row in objectives.values()
    }
    prioritized = [
        row
        for row in ordered
        if (row.sent_player_ids, row.received_player_ids, row.opponent_roster_id) in representatives
    ]
    prioritized.extend(row for row in ordered if row not in prioritized)
    return tuple(prioritized[:limit])


def optimize_target_packages(
    snapshot: TradeSnapshot,
    *,
    projections: Sequence[Projection],
    selected_board: ValueBoard,
    market_ecr_board: ValueBoard,
    trade_market: TradeMarketEvidence,
    target_result: TargetDiscoveryResult,
    config: TargetOptimizerConfig,
    options: EvaluationOptions = EvaluationOptions(),
) -> TargetPackageSearchResult:
    """Construct and exactly evaluate packages around precomputed target lanes."""

    assert_current(snapshot)
    if target_result.manifest_id != snapshot.manifest.analysis_id:
        raise CoverageIncomplete("Target evidence belongs to a different snapshot manifest")
    if target_result.horizon != snapshot.ranking_horizon:
        raise CoverageIncomplete("Target evidence does not match the snapshot horizon")
    if selected_board.horizon != snapshot.ranking_horizon:
        raise CoverageIncomplete("Selected board does not match the snapshot horizon")
    if market_ecr_board.horizon != snapshot.ranking_horizon:
        raise CoverageIncomplete("Market-ECR board does not match the snapshot horizon")
    if not selected_board.complete or not market_ecr_board.complete:
        raise CoverageIncomplete("Target optimization requires complete value boards")
    if stable_hash(asdict(selected_board)) != target_result.selected_board_hash:
        raise CoverageIncomplete("Target discovery and optimizer selected boards do not match")
    if stable_hash(asdict(market_ecr_board)) != target_result.market_ecr_board_hash:
        raise CoverageIncomplete("Target discovery and optimizer market-ECR boards do not match")
    if target_result.pricing_mode != "ECR-PROXY":
        if (
            trade_market.board is None
            or trade_market.board.evidence_hash != target_result.trade_market_board_hash
        ):
            raise CoverageIncomplete(
                "Target discovery and optimizer trade-market boards do not match"
            )
    if target_result.pricing_mode == "MIXED_CURRENT_PRIOR" and (
        trade_market.prior_board is None
        or trade_market.prior_board.mode != "PRIOR_WEEK_MARKET"
    ):
        raise CoverageIncomplete("Mixed market search requires a dated prior chart")
    selected_by_id = {row.player_id: row for row in selected_board.players}
    market_ecr_by_id = {row.player_id: row for row in market_ecr_board.players}
    if set(selected_by_id) != set(market_ecr_by_id):
        raise CoverageIncomplete("Selected and market-ECR boards have different universes")
    player_by_id = {player.player_id: player for player in snapshot.players}
    teams_by_id = {team.roster_id: team for team in snapshot.teams}
    if snapshot.user_roster_id not in teams_by_id:
        raise CoverageIncomplete("User roster is absent from the current snapshot")
    valued_ids = set(selected_by_id)
    eligible_by_team = {
        roster_id: _eligible_players(snapshot, team, valued_ids)
        for roster_id, team in teams_by_id.items()
    }
    required_price_ids = {
        player_id for players in eligible_by_team.values() for player_id in players
    }
    prices, pricing_mode, price_warnings = _price_map(
        target_result,
        trade_market,
        market_ecr_board,
        required_price_ids,
    )
    if pricing_mode not in {"ECR-PROXY", "PRIOR_WEEK_MARKET"} and not trade_market.consolidation_premium_available:
        raise CoverageIncomplete("Direct trade market does not support consolidation premium")
    prior_prices = (
        {row.player_id: float(row.value) for row in trade_market.prior_board.prices}
        if trade_market.prior_board is not None else {}
    )
    if pricing_mode == "PRIOR_WEEK_MARKET":
        prior_prices = prices
    current_eligible_by_team = eligible_by_team
    if pricing_mode != "ECR-PROXY":
        current_eligible_by_team = {
            roster_id: tuple(player_id for player_id in player_ids if player_id in prices)
            for roster_id, player_ids in eligible_by_team.items()
        }
    prior_eligible_by_team = {
        roster_id: tuple(player_id for player_id in player_ids if player_id in prior_prices)
        for roster_id, player_ids in eligible_by_team.items()
    }
    selected_values = {
        player_id: float(row.reconciled_vorp) for player_id, row in selected_by_id.items()
    }
    context = _context(snapshot)
    matrix = build_weekly_projection_matrix(context, projections)
    diagnoses = {
        roster_id: diagnose_roster(
            snapshot,
            projections,
            roster_id=roster_id,
            options=options,
            projection_matrix=matrix,
        )
        for roster_id in sorted(teams_by_id)
    }
    base_scores = {
        roster_id: weighted_lineup_score(
            context,
            matrix,
            _active_roster(teams_by_id[roster_id]),
            options,
        )
        for roster_id in teams_by_id
    }
    metric_cache: dict[tuple[str, str, bool], _PlayerMetrics] = {}
    package_delta_cache: dict[tuple[str, tuple[str, ...], tuple[str, ...]], float] = {}

    def metric(roster_id: str, player_id: str, acquiring: bool) -> _PlayerMetrics:
        key = (roster_id, player_id, acquiring)
        if key not in metric_cache:
            metric_cache[key] = _player_metrics(
                context=context,
                matrix=matrix,
                options=options,
                teams_by_id=teams_by_id,
                base_scores=base_scores,
                roster_id=roster_id,
                player_id=player_id,
                acquiring=acquiring,
            )
        return metric_cache[key]

    def package_delta(
        roster_id: str,
        sent: Sequence[str],
        received: Sequence[str],
    ) -> float:
        key = (roster_id, tuple(sent), tuple(received))
        if key not in package_delta_cache:
            roster = _active_roster(teams_by_id[roster_id])
            after = (roster - set(sent)) | set(received)
            package_delta_cache[key] = round(
                weighted_lineup_score(context, matrix, after, options) - base_scores[roster_id],
                3,
            )
        return package_delta_cache[key]

    _, user_surplus = _diagnosis_sets(diagnoses[snapshot.user_roster_id])
    all_seeds: list[OutgoingSeedEvidence] = []
    candidates_by_key: dict[
        tuple[str, str, str, str, tuple[str, ...], tuple[str, ...]], _Candidate
    ] = {}
    construction_rejections: dict[tuple[str, str, str], int] = {}
    enumerated_counts: dict[tuple[str, str], int] = {
        (lane, size): 0 for lane in TARGET_KINDS for size in PACKAGE_SIZE_LABELS
    }
    prefiltered_counts: dict[tuple[str, str], int] = dict.fromkeys(enumerated_counts, 0)
    deduplicated_counts: dict[tuple[str, str], int] = dict.fromkeys(enumerated_counts, 0)
    target_keys = {(target.kind, target.player_id) for target in target_result.targets}
    for target in target_result.targets:
        if target.status != "WATCH":
            raise CoverageIncomplete("TA-1305 expects immutable WATCH target evidence")
        target_mode = target.trade_price.mode
        target_prices = prior_prices if target_mode == "PRIOR_WEEK_MARKET" else prices
        target_eligible = (
            prior_eligible_by_team if target_mode == "PRIOR_WEEK_MARKET"
            else current_eligible_by_team
        )
        if target.player_id not in selected_by_id or target.player_id not in target_prices:
            raise CoverageIncomplete(
                f"Target {target.player_id} is absent from optimizer value evidence"
            )
        if target.kind == "SELL_HIGH":
            opponent_ids = tuple(
                roster_id
                for roster_id in sorted(teams_by_id)
                if roster_id != snapshot.user_roster_id
            )
        else:
            opponent_ids = (target.roster.owner_roster_id,)
        for opponent_id in opponent_ids:
            if opponent_id == snapshot.user_roster_id or opponent_id not in teams_by_id:
                key = (target.kind, "TARGET", "INVALID_TARGET_OWNER")
                construction_rejections[key] = construction_rejections.get(key, 0) + 1
                continue
            partner_needs, _ = _diagnosis_sets(diagnoses[opponent_id])
            seeds = _outgoing_seeds(
                snapshot=snapshot,
                target=target,
                opponent_id=opponent_id,
                user_players=target_eligible[snapshot.user_roster_id],
                selected_values=selected_values,
                prices=target_prices,
                player_by_id=player_by_id,
                partner_needs=partner_needs,
                user_surplus=user_surplus,
                metric=metric,
            )
            all_seeds.extend(seeds)
            outgoing_pool = tuple(row.player_id for row in seeds[: config.outgoing_pool_limit])
            if target.kind == "SELL_HIGH" and target.player_id not in outgoing_pool:
                outgoing_pool = (
                    target.player_id,
                    *(player_id for player_id in outgoing_pool if player_id != target.player_id),
                )[: config.outgoing_pool_limit]
            opponent_players = target_eligible[opponent_id]
            user_needs, _ = _diagnosis_sets(diagnoses[snapshot.user_roster_id])
            incoming_ordered = tuple(
                sorted(
                    opponent_players,
                    key=lambda player_id: (
                        not bool(_positions(player_by_id[player_id]) & user_needs),
                        -metric(snapshot.user_roster_id, player_id, True).acquisition_gain,
                        -selected_values[player_id],
                        abs(target_prices[player_id] - target_prices[target.player_id]),
                        player_id,
                    ),
                )
            )
            incoming_pool = incoming_ordered[: config.incoming_pool_limit]
            if target.kind != "SELL_HIGH" and target.player_id not in incoming_pool:
                incoming_pool = (
                    target.player_id,
                    *(player_id for player_id in incoming_pool if player_id != target.player_id),
                )[: config.incoming_pool_limit]
            generated = _enumerate_for_target(
                snapshot=snapshot,
                target=target,
                opponent_id=opponent_id,
                user_pool=outgoing_pool,
                opponent_pool=incoming_pool,
                prices=target_prices,
                player_by_id=player_by_id,
                partner_needs=partner_needs,
                target_owner_disposable=(
                    target.roster.owner_disposable if target.kind != "SELL_HIGH" else False
                ),
                package_delta=package_delta,
                config=config,
                pricing_mode=target_mode,
            )
            for candidate in generated:
                group = (candidate.lane, candidate.package_size)
                enumerated_counts[group] += 1
                if candidate.broad_market_distance > 0.0:
                    prefiltered_counts[group] += 1
                    key = (candidate.lane, candidate.package_size, "CONSTRUCTION_MARKET_BAND")
                    construction_rejections[key] = construction_rejections.get(key, 0) + 1
                    continue
                if not candidate.partner_prefilter_passed:
                    prefiltered_counts[group] += 1
                    key = (candidate.lane, candidate.package_size, "PARTNER_PREFILTER")
                    construction_rejections[key] = construction_rejections.get(key, 0) + 1
                    continue
                key = (
                    candidate.lane,
                    candidate.package_size,
                    candidate.pricing_mode,
                    candidate.opponent_roster_id,
                    candidate.sent_player_ids,
                    candidate.received_player_ids,
                )
                existing = candidates_by_key.get(key)
                if existing is not None:
                    deduplicated_counts[group] += 1
                candidates_by_key[key] = (
                    _merge_candidate(existing, candidate) if existing else candidate
                )

    decisions: list[EvaluatedPackageDecision] = []
    accepted_rows: list[TargetPackageOpportunity] = []
    coverage: list[LanePackageCoverage] = []
    rejection_counts = dict(construction_rejections)
    for lane in TARGET_KINDS:
        for package_size in PACKAGE_SIZE_LABELS:
            group_key = (lane, package_size)
            eligible = sorted(
                (
                    row
                    for row in candidates_by_key.values()
                    if row.lane == lane and row.package_size == package_size
                ),
                key=_candidate_sort_key,
            )
            budget = config.budget(lane, package_size)
            runtime_pruned = max(0, len(eligible) - budget)
            if runtime_pruned:
                key = (lane, package_size, "EXACT_BUDGET")
                rejection_counts[key] = rejection_counts.get(key, 0) + runtime_pruned
            evaluated_count = 0
            accepted_count = 0
            attempted = min(len(eligible), budget)
            for candidate in eligible[:budget]:
                package = TradePackage(
                    roster_a_id=snapshot.user_roster_id,
                    roster_b_id=candidate.opponent_roster_id,
                    from_a=tuple(PlayerAsset(player_id) for player_id in candidate.sent_player_ids),
                    from_b=tuple(
                        PlayerAsset(player_id) for player_id in candidate.received_player_ids
                    ),
                )
                try:
                    evaluation = evaluate_trade(
                        snapshot,
                        package,
                        projections=projections,
                        selected_board=selected_board,
                        market_board=market_ecr_board,
                        options=options,
                        projection_matrix=matrix,
                    )
                except (CoverageIncomplete, RosterIllegal) as exc:
                    reason = type(exc).__name__.upper()
                    key = (lane, package_size, reason)
                    rejection_counts[key] = rejection_counts.get(key, 0) + 1
                    continue
                evaluated_count += 1
                fairness = _fairness(
                    candidate.sent_player_ids,
                    candidate.received_player_ids,
                    prior_prices if candidate.pricing_mode == "PRIOR_WEEK_MARKET" else prices,
                    candidate.pricing_mode,
                    config.fair_market_band_ratio,
                    config.fair_market_band_floor,
                    (
                        tuple(trade_market.prior_board.warnings)
                        if candidate.pricing_mode == "PRIOR_WEEK_MARKET"
                        and trade_market.prior_board is not None
                        else price_warnings
                    ),
                    consolidation=lane == "CONSOLIDATE" and package_size == "2-for-1",
                    premium_policy_id=config.consolidation_premium_policy_id,
                    premium_ratio=config.consolidation_premium_ratio,
                )
                consolidation = (
                    analyze_consolidation(
                        snapshot,
                        evaluation,
                        context=context,
                        matrix=matrix,
                        options=options,
                        minimum_starter_upgrade=config.minimum_consolidation_starter_upgrade,
                        minimum_partner_lineup_use=config.minimum_partner_asset_lineup_use,
                        minimum_partner_depth_use=config.minimum_partner_asset_depth_use,
                    )
                    if lane == "CONSOLIDATE" and package_size == "2-for-1"
                    else None
                )
                decision = _exact_decision(
                    candidate=candidate,
                    evaluation=evaluation,
                    fairness=fairness,
                    consolidation=consolidation,
                    diagnoses=diagnoses,
                    player_by_id=player_by_id,
                    config=config,
                    options=options,
                )
                decisions.append(decision)
                if not decision.accepted:
                    key = (lane, package_size, decision.reason)
                    rejection_counts[key] = rejection_counts.get(key, 0) + 1
                    continue
                accepted_count += 1
                accepted_rows.append(
                    TargetPackageOpportunity(
                        lane=lane,
                        primary_target_player_id=candidate.primary_target_player_id,
                        generated_by_target_ids=candidate.generated_by_target_ids,
                        opponent_roster_id=candidate.opponent_roster_id,
                        package_size=package_size,
                        sent_player_ids=candidate.sent_player_ids,
                        received_player_ids=candidate.received_player_ids,
                        intrinsic_outcome=decision.intrinsic_outcome,
                        market_fairness=fairness,
                        consolidation=consolidation,
                        objective_tags=(),
                        user_weighted_lineup_delta=decision.user_weighted_lineup_delta,
                        user_selected_delta=float(decision.user_selected_delta),
                        user_market_ecr_delta=decision.user_market_ecr_delta,
                        cross_model_agreement=decision.cross_model_agreement,
                        user_depth_delta=decision.user_depth_delta,
                        user_downside_delta=decision.user_downside_delta,
                        partner_weighted_lineup_delta=decision.partner_weighted_lineup_delta,
                        partner_selected_delta=float(decision.partner_selected_delta),
                        partner_depth_delta=decision.partner_depth_delta,
                        forced_add=decision.forced_add,
                        forced_drop=decision.forced_drop,
                        evaluation=evaluation,
                    )
                )
            coverage.append(
                LanePackageCoverage(
                    lane=lane,
                    package_size=package_size,
                    enumerated=enumerated_counts[group_key],
                    prefiltered=prefiltered_counts[group_key],
                    deduplicated=deduplicated_counts[group_key],
                    eligible=len(eligible),
                    budget_limit=budget,
                    runtime_pruned=runtime_pruned,
                    attempted=attempted,
                    evaluated=evaluated_count,
                    accepted=accepted_count,
                )
            )

    opportunities = tuple(
        row
        for lane in TARGET_KINDS
        for row in _frontier(
            tuple(candidate for candidate in accepted_rows if candidate.lane == lane),
            config.max_results_per_lane,
        )
    )
    passing_by_target: dict[tuple[str, str], int] = dict.fromkeys(target_keys, 0)
    for row in accepted_rows:
        for target_id in row.generated_by_target_ids:
            key = (row.lane, target_id)
            if key in passing_by_target:
                passing_by_target[key] += 1
    target_statuses = tuple(
        TargetPackageStatus(
            lane=target.kind,
            player_id=target.player_id,
            status=(
                "OFFER_FOUND" if passing_by_target[(target.kind, target.player_id)] else "WATCH"
            ),
            partner_credible_offer_found=bool(passing_by_target[(target.kind, target.player_id)]),
            passing_offer_count=passing_by_target[(target.kind, target.player_id)],
            obtainable=False,
        )
        for target in target_result.targets
    )
    warnings = tuple(
        dict.fromkeys(
            (
                *target_result.warnings,
                *summarize_projection_warnings(matrix.warnings),
                *price_warnings,
                "Passing offers are modeled partner-credible constructions, not acceptance "
                "predictions",
                "No target or package is called obtainable and no transaction is submitted",
            )
        )
    )
    base = TargetPackageSearchResult(
        schema_version=1,
        manifest_id=snapshot.manifest.analysis_id,
        league_key=snapshot.league_key,
        horizon=snapshot.ranking_horizon,
        target_evidence_hash=target_result.evidence_hash,
        pricing_mode=pricing_mode,
        config=config,
        target_statuses=target_statuses,
        outgoing_seeds=tuple(
            sorted(
                all_seeds,
                key=lambda row: (
                    TARGET_KINDS.index(row.lane),
                    row.target_player_id,
                    row.opponent_roster_id,
                    row.seed_rank,
                    row.player_id,
                ),
            )
        ),
        opportunities=opportunities,
        evaluated_decisions=tuple(decisions),
        coverage=tuple(coverage),
        rejection_counts=tuple(
            (lane, size, reason, count)
            for (lane, size, reason), count in sorted(rejection_counts.items())
        ),
        warnings=warnings,
        evidence_hash="",
    )
    return replace(base, evidence_hash=stable_hash(asdict(base)))
