from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import datetime
from typing import Sequence

from roster_theory.core.errors import CoverageIncomplete
from roster_theory.core.models import FantasyTeam, Projection
from roster_theory.core.provenance import DataStamp, stable_hash
from roster_theory.inseason.evaluation import (
    InSeasonContext,
    InSeasonWeek,
    WeeklyProjectionMatrix,
    build_weekly_projection_matrix,
    lineup,
    weighted_lineup_score,
)
from roster_theory.trade.boards import BoardPlayerValue, ValueBoard
from roster_theory.trade.evaluation import (
    EvaluationOptions,
    PositionDiagnosis,
    RosterDiagnosis,
    diagnose_roster,
)
from roster_theory.trade.market import TradeMarketBoard, TradeMarketEvidence, TradeMarketPrice
from roster_theory.trade.snapshot import SKILL_POSITIONS, TradeSnapshot, assert_current


TARGET_KINDS = ("BUY_LOW", "SELL_HIGH", "CONSOLIDATE", "NEED_FIT")
PERFORMANCE_SIGNALS = frozenset({"UNDERPERFORMING", "OUTPERFORMING", "NEUTRAL"})


@dataclass(frozen=True, slots=True)
class TargetDiscoveryConfig:
    """Explicit, unblended thresholds supplied by the governing league policy."""

    policy_id: str
    material_percentile_gap: float
    minimum_lineup_gain: float
    consolidation_lineup_gain: float
    maximum_disposable_lineup_cost: float
    max_targets_per_lane: int

    def __post_init__(self) -> None:
        if not self.policy_id.strip():
            raise ValueError("Target discovery policy_id is required")
        if not 0.0 <= self.material_percentile_gap <= 1.0:
            raise ValueError("material_percentile_gap must be between zero and one")
        if self.minimum_lineup_gain < 0.0:
            raise ValueError("minimum_lineup_gain cannot be negative")
        if self.consolidation_lineup_gain <= 0.0:
            raise ValueError("consolidation_lineup_gain must be positive")
        if self.maximum_disposable_lineup_cost < 0.0:
            raise ValueError("maximum_disposable_lineup_cost cannot be negative")
        if self.max_targets_per_lane <= 0:
            raise ValueError("max_targets_per_lane must be positive")


@dataclass(frozen=True, slots=True)
class TargetPerformanceContext:
    player_id: str
    signal: str
    sample_size: int
    as_of: datetime
    compatible: bool
    shrunk_point_residual: float | None = None
    shrunk_rank_residual: float | None = None
    fresh: bool | None = None
    source: str = ""
    exclusions: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.signal not in PERFORMANCE_SIGNALS:
            raise ValueError(f"Unsupported performance signal: {self.signal}")
        if self.sample_size < 0:
            raise ValueError("Performance sample_size cannot be negative")


@dataclass(frozen=True, slots=True)
class TargetBoardEvidence:
    board_id: str
    horizon: str
    overall_rank: int
    position_rank: int
    tier: int
    reconciled_vorp: float
    percentile: float
    universe_size: int
    stamps: tuple[DataStamp, ...]
    warnings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TargetTradePriceEvidence:
    mode: str
    percentile_source: str
    percentile: float
    universe_size: int
    raw_value: float | None
    overall_rank: int | None
    position_rank: int | None
    provider_change_7d: float | None
    provider_change_30d: float | None
    previous_board_change: float | None
    as_of: datetime | None
    captured_at: datetime | None
    scoring_variant: str | None
    te_premium_variant: str | None
    league_scoring_exact: bool
    source_url: str | None
    attribution: str | None
    stamp: DataStamp | None
    warnings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TargetMarketGap:
    price_minus_intrinsic_percentile: float
    market_ecr_minus_intrinsic_percentile: float
    material_percentile_gap: float
    signal: str
    market_ecr_corroboration: str


@dataclass(frozen=True, slots=True)
class TargetRosterEvidence:
    user_roster_id: str
    owner_roster_id: str
    owner_team_name: str
    direction: str
    lineup_value_basis: str
    user_fit: bool | None
    user_started_weeks: tuple[int, ...]
    user_standalone_lineup_gain: float | None
    user_depth_fit: bool | None
    user_need_positions: tuple[str, ...]
    owner_marginal_lineup_cost: float
    owner_usable_surplus: bool
    owner_disposable: bool
    owner_preference_claimed: bool
    ownership_captured_at: datetime
    ownership_current: bool
    ownership_stamps: tuple[DataStamp, ...]


@dataclass(frozen=True, slots=True)
class TargetRankingFactor:
    name: str
    value: float
    preferred: str


@dataclass(frozen=True, slots=True)
class TradeTarget:
    kind: str
    rank_in_lane: int
    status: str
    player_id: str
    player_name: str
    position: str
    intrinsic: TargetBoardEvidence
    market_ecr: TargetBoardEvidence
    trade_price: TargetTradePriceEvidence
    market_gap: TargetMarketGap
    roster: TargetRosterEvidence
    performance: TargetPerformanceContext | None
    performance_support: str
    ranking_factors: tuple[TargetRankingFactor, ...]
    partner_credible_offer_found: bool
    obtainable: bool
    warnings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TargetExclusion:
    player_id: str
    owner_roster_id: str | None
    kind: str | None
    reason: str


@dataclass(frozen=True, slots=True)
class TargetDiscoveryResult:
    schema_version: int
    manifest_id: str
    league_key: str
    horizon: str
    pricing_mode: str
    selected_board_hash: str
    market_ecr_board_hash: str
    trade_market_board_hash: str | None
    config: TargetDiscoveryConfig
    targets: tuple[TradeTarget, ...]
    lane_counts: tuple[tuple[str, int, int], ...]
    exclusions: tuple[TargetExclusion, ...]
    warnings: tuple[str, ...]
    evidence_hash: str


@dataclass(frozen=True, slots=True)
class _RosterMetrics:
    acquire_lineup_gain: float | None
    acquire_started_weeks: tuple[int, ...]
    depth_fit: bool | None
    need_positions: tuple[str, ...]
    owner_lineup_cost: float
    owner_surplus: bool
    owner_disposable: bool


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


def _percentile(rank: int, universe_size: int) -> float:
    if universe_size <= 1:
        return 1.0
    bounded_rank = min(max(rank, 1), universe_size)
    return round((universe_size - bounded_rank) / (universe_size - 1), 6)


def _stamp_warnings(stamps: Sequence[DataStamp]) -> tuple[str, ...]:
    warnings = [warning for stamp in stamps for warning in stamp.warnings]
    warnings.extend(
        f"{stamp.source} freshness is not confirmed" for stamp in stamps if stamp.fresh is None
    )
    warnings.extend(f"{stamp.source} evidence is stale" for stamp in stamps if stamp.fresh is False)
    if not stamps:
        warnings.append("No source freshness stamp is attached to this value board")
    return tuple(dict.fromkeys(warnings))


def _board_evidence(board: ValueBoard, row: BoardPlayerValue) -> TargetBoardEvidence:
    warnings = tuple(dict.fromkeys((*row.warnings, *_stamp_warnings(board.stamps))))
    return TargetBoardEvidence(
        board_id=board.board_id,
        horizon=board.horizon,
        overall_rank=row.overall_rank,
        position_rank=row.position_rank,
        tier=row.tier,
        reconciled_vorp=round(float(row.reconciled_vorp), 6),
        percentile=_percentile(row.overall_rank, len(board.players)),
        universe_size=len(board.players),
        stamps=board.stamps,
        warnings=warnings,
    )


def _market_signal(gap: float, threshold: float) -> str:
    if gap >= threshold:
        return "SELL_HIGH"
    if gap <= -threshold:
        return "BUY_LOW"
    return "ALIGNED"


def _corroboration(direct_signal: str, ecr_signal: str, pricing_mode: str) -> str:
    if pricing_mode == "ECR-PROXY":
        return "ECR_PROXY_ONLY"
    if pricing_mode == "PRIOR_WEEK_MARKET":
        return "PRIOR_WEEK_INDICATIVE"
    if direct_signal == "ALIGNED" or ecr_signal == "ALIGNED":
        return "NEUTRAL"
    return "SUPPORTS" if direct_signal == ecr_signal else "DISAGREES"


def _performance_support(kind: str, context: TargetPerformanceContext | None) -> tuple[str, float]:
    if context is None:
        return "UNAVAILABLE", 0.0
    if not context.compatible:
        return "EXCLUDED_INCOMPATIBLE", 0.0
    if context.fresh is not True:
        return "EXCLUDED_STALE", 0.0
    expected = {
        "BUY_LOW": "UNDERPERFORMING",
        "SELL_HIGH": "OUTPERFORMING",
        "CONSOLIDATE": "UNDERPERFORMING",
        "NEED_FIT": "UNDERPERFORMING",
    }.get(kind)
    if context.signal == "NEUTRAL":
        return "CONTEXT_ONLY", 0.0
    if context.signal == expected:
        return "SUPPORTS", 1.0
    return "DISAGREES", -1.0


def _direct_board_usable(
    evidence: TradeMarketEvidence,
) -> tuple[TradeMarketBoard | None, tuple[str, ...]]:
    board = evidence.board
    warnings = list(evidence.warnings)
    if evidence.mode == "ECR-PROXY" or board is None or not evidence.chart_price_available:
        return None, tuple(dict.fromkeys(warnings))
    reasons: list[str] = []
    if not board.complete:
        reasons.append("trade-market board is marked incomplete")
    if not board.league_format_compatible:
        reasons.append("trade-market board format is incompatible with the league")
    if board.stamp.fresh is not True and evidence.mode != "PRIOR_WEEK_MARKET":
        reasons.append("trade-market board freshness is not confirmed")
    if reasons:
        warnings.append(
            "ECR-PROXY: direct trade-market pricing was disabled because " + "; ".join(reasons)
        )
        return None, tuple(dict.fromkeys(warnings))
    return board, tuple(dict.fromkeys(warnings))


def summarize_projection_warnings(warnings: tuple[str, ...]) -> tuple[str, ...]:
    """Keep missing universe projections visible without thousands of repeats."""

    missing = [row for row in warnings if row.endswith(": missing projection")]
    retained = [row for row in warnings if not row.endswith(": missing projection")]
    if missing:
        players = {row.split(" Week ", 1)[0] for row in missing}
        retained.append(
            f"{len(missing)} player-week projections are missing across "
            f"{len(players)} players in the valuation universe; exact-package "
            "coverage is checked separately"
        )
    return tuple(dict.fromkeys(retained))


def _trade_price_evidence(
    board: TradeMarketBoard | None,
    price: TradeMarketPrice | None,
    market_ecr: TargetBoardEvidence,
    fallback_warnings: tuple[str, ...],
) -> TargetTradePriceEvidence:
    if board is None or price is None:
        return TargetTradePriceEvidence(
            mode="ECR-PROXY",
            percentile_source="MARKET_ECR",
            percentile=market_ecr.percentile,
            universe_size=market_ecr.universe_size,
            raw_value=None,
            overall_rank=None,
            position_rank=None,
            provider_change_7d=None,
            provider_change_30d=None,
            previous_board_change=None,
            as_of=None,
            captured_at=None,
            scoring_variant=None,
            te_premium_variant=None,
            league_scoring_exact=False,
            source_url=None,
            attribution=None,
            stamp=None,
            warnings=fallback_warnings,
        )
    warnings = list(board.warnings)
    warnings.extend(board.stamp.warnings)
    if not board.league_scoring_exact:
        warnings.append(
            "Trade-market reception and tight-end-premium settings are a provider blend, "
            "not this league's exact scoring"
        )
    if (
        price.provider_change_7d is None
        and price.provider_change_30d is None
        and price.previous_board_change is None
    ):
        warnings.append("No trade-market change is available for this player")
    return TargetTradePriceEvidence(
        mode=board.mode,
        percentile_source="TRADE_MARKET",
        percentile=_percentile(price.overall_rank, len(board.prices)),
        universe_size=len(board.prices),
        raw_value=round(float(price.value), 6),
        overall_rank=price.overall_rank,
        position_rank=price.position_rank,
        provider_change_7d=price.provider_change_7d,
        provider_change_30d=price.provider_change_30d,
        previous_board_change=price.previous_board_change,
        as_of=board.as_of,
        captured_at=board.captured_at,
        scoring_variant=board.scoring_variant,
        te_premium_variant=board.te_premium_variant,
        league_scoring_exact=board.league_scoring_exact,
        source_url=board.source_url,
        attribution=board.attribution,
        stamp=board.stamp,
        warnings=tuple(dict.fromkeys(warnings)),
    )


def _diagnosis_position(diagnosis: RosterDiagnosis, position: str) -> PositionDiagnosis | None:
    return next((row for row in diagnosis.positions if row.position == position), None)


def _started_weeks(
    context: InSeasonContext,
    matrix: WeeklyProjectionMatrix,
    roster: set[str],
    player_id: str,
    options: EvaluationOptions,
) -> tuple[int, ...]:
    return tuple(
        week.week
        for week in context.weeks
        if player_id
        in {
            assignment.player_id
            for assignment in lineup(
                context,
                matrix,
                roster,
                week.week,
                allow_partial=options.allow_partial_schedule,
            ).assignments
        }
    )


def _roster_metrics(
    *,
    snapshot: TradeSnapshot,
    context: InSeasonContext,
    matrix: WeeklyProjectionMatrix,
    options: EvaluationOptions,
    config: TargetDiscoveryConfig,
    player_id: str,
    position: str,
    owner_id: str,
    selected_by_id: dict[str, BoardPlayerValue],
    teams_by_id: dict[str, FantasyTeam],
    diagnoses: dict[str, RosterDiagnosis],
    score_by_roster: dict[str, float],
) -> _RosterMetrics:
    user_id = snapshot.user_roster_id
    user_roster = _active_roster(teams_by_id[user_id])
    owner_roster = _active_roster(teams_by_id[owner_id])
    owner_after = owner_roster - {player_id}
    owner_lineup_cost = round(
        score_by_roster[owner_id] - weighted_lineup_score(context, matrix, owner_after, options),
        3,
    )
    owner_position = _diagnosis_position(diagnoses[owner_id], position)
    owner_surplus = bool(owner_position and player_id in owner_position.usable_surplus_player_ids)
    owner_disposable = owner_surplus or owner_lineup_cost <= config.maximum_disposable_lineup_cost
    user_position = _diagnosis_position(diagnoses[user_id], position)
    user_need_positions = tuple(
        row.position for row in diagnoses[user_id].positions if row.need_above_waiver > 0.0
    )
    if owner_id == user_id:
        return _RosterMetrics(
            acquire_lineup_gain=None,
            acquire_started_weeks=(),
            depth_fit=None,
            need_positions=user_need_positions,
            owner_lineup_cost=owner_lineup_cost,
            owner_surplus=owner_surplus,
            owner_disposable=owner_disposable,
        )
    user_after = user_roster | {player_id}
    acquire_gain = round(
        weighted_lineup_score(context, matrix, user_after, options) - score_by_roster[user_id],
        3,
    )
    waiver_value = None
    if user_position and user_position.waiver_player_id:
        waiver_row = selected_by_id.get(user_position.waiver_player_id)
        waiver_value = float(waiver_row.reconciled_vorp) if waiver_row else None
    player_value = float(selected_by_id[player_id].reconciled_vorp)
    depth_fit = bool(
        user_position
        and not user_position.usable_surplus_player_ids
        and waiver_value is not None
        and player_value > waiver_value
    )
    return _RosterMetrics(
        acquire_lineup_gain=acquire_gain,
        acquire_started_weeks=_started_weeks(context, matrix, user_after, player_id, options),
        depth_fit=depth_fit,
        need_positions=user_need_positions,
        owner_lineup_cost=owner_lineup_cost,
        owner_surplus=owner_surplus,
        owner_disposable=owner_disposable,
    )


def _roster_evidence(
    snapshot: TradeSnapshot,
    owner: FantasyTeam,
    kind: str,
    metrics: _RosterMetrics,
) -> TargetRosterEvidence:
    lineup_fit = bool(metrics.acquire_lineup_gain is not None and metrics.acquire_lineup_gain > 0.0)
    return TargetRosterEvidence(
        user_roster_id=snapshot.user_roster_id,
        owner_roster_id=owner.roster_id,
        owner_team_name=owner.display_name,
        direction="SHOP" if kind == "SELL_HIGH" else "ACQUIRE",
        lineup_value_basis="WEIGHTED_HORIZON_POINTS",
        user_fit=(None if kind == "SELL_HIGH" else lineup_fit or bool(metrics.depth_fit)),
        user_started_weeks=metrics.acquire_started_weeks,
        user_standalone_lineup_gain=metrics.acquire_lineup_gain,
        user_depth_fit=metrics.depth_fit,
        user_need_positions=metrics.need_positions,
        owner_marginal_lineup_cost=metrics.owner_lineup_cost,
        owner_usable_surplus=metrics.owner_surplus,
        owner_disposable=metrics.owner_disposable,
        owner_preference_claimed=False,
        ownership_captured_at=snapshot.captured_at,
        ownership_current=snapshot.current,
        ownership_stamps=snapshot.stamps,
    )


def _ranking_factors(
    kind: str,
    gap: TargetMarketGap,
    intrinsic: TargetBoardEvidence,
    roster: TargetRosterEvidence,
    corroboration_value: float,
    performance_value: float,
) -> tuple[TargetRankingFactor, ...]:
    lineup_gain = float(roster.user_standalone_lineup_gain or 0.0)
    disposable = float(roster.owner_disposable)
    depth_fit = float(bool(roster.user_depth_fit))
    if kind == "BUY_LOW":
        values = (
            ("intrinsic_discount_percentile", -gap.price_minus_intrinsic_percentile, "HIGHER"),
            ("user_standalone_lineup_gain", lineup_gain, "HIGHER"),
            ("owner_disposable", disposable, "HIGHER"),
            ("market_ecr_corroboration", corroboration_value, "HIGHER"),
            ("performance_support", performance_value, "HIGHER"),
        )
    elif kind == "SELL_HIGH":
        values = (
            ("market_premium_percentile", gap.price_minus_intrinsic_percentile, "HIGHER"),
            ("owner_disposable", disposable, "HIGHER"),
            ("owner_marginal_lineup_cost", roster.owner_marginal_lineup_cost, "LOWER"),
            ("market_ecr_corroboration", corroboration_value, "HIGHER"),
            ("performance_support", performance_value, "HIGHER"),
        )
    elif kind == "CONSOLIDATE":
        values = (
            ("user_standalone_lineup_gain", lineup_gain, "HIGHER"),
            ("intrinsic_percentile", intrinsic.percentile, "HIGHER"),
            ("owner_disposable", disposable, "HIGHER"),
            ("owner_marginal_lineup_cost", roster.owner_marginal_lineup_cost, "LOWER"),
            ("market_ecr_corroboration", corroboration_value, "HIGHER"),
            ("performance_support", performance_value, "HIGHER"),
        )
    else:
        values = (
            ("user_standalone_lineup_gain", lineup_gain, "HIGHER"),
            ("user_depth_fit", depth_fit, "HIGHER"),
            ("owner_disposable", disposable, "HIGHER"),
            ("owner_marginal_lineup_cost", roster.owner_marginal_lineup_cost, "LOWER"),
            ("intrinsic_percentile", intrinsic.percentile, "HIGHER"),
            ("performance_support", performance_value, "HIGHER"),
        )
    return tuple(
        TargetRankingFactor(name, round(float(value), 6), preferred)
        for name, value, preferred in values
    )


def _target_sort_key(target: TradeTarget) -> tuple[float | str, ...]:
    factors = tuple(
        -factor.value if factor.preferred == "HIGHER" else factor.value
        for factor in target.ranking_factors
    )
    return (*factors, target.player_id, target.roster.owner_roster_id)


def _card(
    *,
    kind: str,
    snapshot: TradeSnapshot,
    player_id: str,
    player_name: str,
    position: str,
    owner: FantasyTeam,
    intrinsic: TargetBoardEvidence,
    market_ecr: TargetBoardEvidence,
    trade_price: TargetTradePriceEvidence,
    market_gap: TargetMarketGap,
    metrics: _RosterMetrics,
    performance: TargetPerformanceContext | None,
) -> TradeTarget:
    roster = _roster_evidence(snapshot, owner, kind, metrics)
    performance_support, performance_value = _performance_support(kind, performance)
    corroboration_value = {
        "SUPPORTS": 1.0,
        "NEUTRAL": 0.0,
        "ECR_PROXY_ONLY": 0.0,
        "PRIOR_WEEK_INDICATIVE": 0.0,
        "DISAGREES": -1.0,
    }[market_gap.market_ecr_corroboration]
    warnings = [
        *snapshot.warnings,
        *intrinsic.warnings,
        *market_ecr.warnings,
        *trade_price.warnings,
        "Owner disposability is modeled from roster use; it is not a claim about manager preference",
        "WATCH: package search has not established a partner-credible offer or obtainability",
    ]
    if performance is None:
        warnings.append(
            "Recent-performance context is unavailable; it is optional and did not block the target"
        )
    else:
        warnings.extend(performance.warnings)
        if not performance.compatible:
            warnings.append("Incompatible recent-performance context was excluded from ranking")
        if performance.fresh is False:
            warnings.append("Recent-performance context is stale")
        elif performance.fresh is None:
            warnings.append("Recent-performance freshness is not confirmed")
    if kind == "CONSOLIDATE":
        warnings.append(
            "The outgoing pair, partner uses, required drop, and market premium have not yet "
            "been established"
        )
    ranking_factors = _ranking_factors(
        kind,
        market_gap,
        intrinsic,
        roster,
        corroboration_value,
        performance_value,
    )
    return TradeTarget(
        kind=kind,
        rank_in_lane=0,
        status="WATCH",
        player_id=player_id,
        player_name=player_name,
        position=position,
        intrinsic=intrinsic,
        market_ecr=market_ecr,
        trade_price=trade_price,
        market_gap=market_gap,
        roster=roster,
        performance=performance,
        performance_support=performance_support,
        ranking_factors=ranking_factors,
        partner_credible_offer_found=False,
        obtainable=False,
        warnings=tuple(dict.fromkeys(warnings)),
    )


def discover_trade_targets(
    snapshot: TradeSnapshot,
    *,
    projections: Sequence[Projection],
    selected_board: ValueBoard,
    market_ecr_board: ValueBoard,
    trade_market: TradeMarketEvidence,
    config: TargetDiscoveryConfig,
    performance_context: Sequence[TargetPerformanceContext] = (),
    options: EvaluationOptions = EvaluationOptions(),
) -> TargetDiscoveryResult:
    """Discover auditable player targets without constructing or grading packages."""

    assert_current(snapshot)
    if not selected_board.complete or not market_ecr_board.complete:
        raise CoverageIncomplete(
            "Target discovery requires complete selected and market-ECR boards"
        )
    if selected_board.horizon != snapshot.ranking_horizon:
        raise CoverageIncomplete("Selected board does not match the snapshot ranking horizon")
    if market_ecr_board.horizon != snapshot.ranking_horizon:
        raise CoverageIncomplete("Market-ECR board does not match the snapshot ranking horizon")
    selected_by_id = {row.player_id: row for row in selected_board.players}
    market_ecr_by_id = {row.player_id: row for row in market_ecr_board.players}
    if set(selected_by_id) != set(market_ecr_by_id):
        raise CoverageIncomplete("Selected and market-ECR boards have different universes")
    performance_by_id: dict[str, TargetPerformanceContext] = {}
    for row in performance_context:
        if row.player_id in performance_by_id:
            raise CoverageIncomplete(f"Duplicate performance context for {row.player_id}")
        performance_by_id[row.player_id] = row

    player_by_id = {player.player_id: player for player in snapshot.players}
    teams_by_id = {team.roster_id: team for team in snapshot.teams}
    owners = dict(snapshot.owner_by_player)
    if snapshot.user_roster_id not in teams_by_id:
        raise CoverageIncomplete("User roster is absent from the current snapshot")
    rostered_tradeable = {
        player_id
        for player_id in snapshot.tradeable_player_ids
        if player_id in owners
        and (player := player_by_id.get(player_id)) is not None
        and bool(SKILL_POSITIONS.intersection(position.upper() for position in player.positions))
    }
    fully_valued = rostered_tradeable & set(selected_by_id) & set(market_ecr_by_id)
    exclusions: list[TargetExclusion] = [
        TargetExclusion(
            player_id,
            owners.get(player_id),
            None,
            "MISSING_SELECTED_OR_MARKET_ECR_VALUE",
        )
        for player_id in sorted(rostered_tradeable - fully_valued)
    ]
    direct_board, market_warnings = _direct_board_usable(trade_market)
    pricing_mode = trade_market.mode if direct_board is not None else "ECR-PROXY"
    price_by_id = (
        {row.player_id: row for row in direct_board.prices} if direct_board is not None else {}
    )
    prior_board = (
        trade_market.prior_board
        if direct_board is not None
        and trade_market.mode != "PRIOR_WEEK_MARKET"
        and trade_market.prior_board is not None
        and trade_market.prior_board.mode == "PRIOR_WEEK_MARKET"
        and trade_market.prior_board.complete
        and trade_market.prior_board.league_format_compatible
        else None
    )
    prior_prices = (
        {row.player_id: row for row in prior_board.prices} if prior_board else {}
    )
    if direct_board is not None:
        prior_only_ids = (fully_valued - set(price_by_id)) & set(prior_prices)
        missing_chart_ids = fully_valued - set(price_by_id) - prior_only_ids
        exclusions.extend(
            TargetExclusion(
                player_id, owners[player_id], None, "MISSING_TRADE_MARKET_PRICE"
            )
            for player_id in sorted(missing_chart_ids)
        )
        if missing_chart_ids:
            market_warnings = tuple(dict.fromkeys((
                *market_warnings,
                f"{len(missing_chart_ids)} rostered players lack a price on the "
                "selected trade chart; they were excluded from chart-priced targets",
            )))
        if prior_only_ids:
            pricing_mode = "MIXED_CURRENT_PRIOR"
            market_warnings = tuple(dict.fromkeys((
                *market_warnings,
                f"{len(prior_only_ids)} rostered players lack a current chart price; "
                "their candidate packages use one prior-week chart for every asset "
                "and cannot be accepted as current-market fair",
            )))

    context = _context(snapshot)
    matrix = build_weekly_projection_matrix(context, projections)
    diagnoses = {
        team.roster_id: diagnose_roster(
            snapshot,
            projections,
            roster_id=team.roster_id,
            options=options,
            projection_matrix=matrix,
        )
        for team in sorted(snapshot.teams, key=lambda row: row.roster_id)
    }
    score_by_roster = {
        roster_id: weighted_lineup_score(
            context, matrix, _active_roster(teams_by_id[roster_id]), options
        )
        for roster_id in teams_by_id
    }
    candidates: dict[str, list[TradeTarget]] = {kind: [] for kind in TARGET_KINDS}
    for player_id in sorted(fully_valued):
        if direct_board is not None and player_id not in price_by_id and player_id not in prior_prices:
            continue
        owner_id = owners[player_id]
        owner = teams_by_id.get(owner_id)
        player = player_by_id.get(player_id)
        if owner is None or player is None:
            exclusions.append(TargetExclusion(player_id, owner_id, None, "OWNER_OR_PLAYER_MISSING"))
            continue
        selected_row = selected_by_id[player_id]
        market_ecr_row = market_ecr_by_id[player_id]
        intrinsic = _board_evidence(selected_board, selected_row)
        market_ecr = _board_evidence(market_ecr_board, market_ecr_row)
        player_board = (
            prior_board if player_id in prior_prices and player_id not in price_by_id
            else direct_board
        )
        player_price = (
            prior_prices[player_id] if player_board is prior_board and prior_board is not None
            else price_by_id.get(player_id)
        )
        trade_price = _trade_price_evidence(
            player_board,
            player_price,
            market_ecr,
            market_warnings,
        )
        price_gap = round(trade_price.percentile - intrinsic.percentile, 6)
        ecr_gap = round(market_ecr.percentile - intrinsic.percentile, 6)
        signal = _market_signal(price_gap, config.material_percentile_gap)
        ecr_signal = _market_signal(ecr_gap, config.material_percentile_gap)
        market_gap = TargetMarketGap(
            price_minus_intrinsic_percentile=price_gap,
            market_ecr_minus_intrinsic_percentile=ecr_gap,
            material_percentile_gap=config.material_percentile_gap,
            signal=signal,
            market_ecr_corroboration=_corroboration(
                signal, ecr_signal, trade_price.mode
            ),
        )
        metrics = _roster_metrics(
            snapshot=snapshot,
            context=context,
            matrix=matrix,
            options=options,
            config=config,
            player_id=player_id,
            position=selected_row.position,
            owner_id=owner_id,
            selected_by_id=selected_by_id,
            teams_by_id=teams_by_id,
            diagnoses=diagnoses,
            score_by_roster=score_by_roster,
        )
        performance = performance_by_id.get(player_id)
        kinds: list[str] = []
        if owner_id == snapshot.user_roster_id:
            if signal == "SELL_HIGH" and metrics.owner_disposable:
                kinds.append("SELL_HIGH")
            elif signal == "SELL_HIGH":
                exclusions.append(
                    TargetExclusion(player_id, owner_id, "SELL_HIGH", "USER_MARGINAL_COST_TOO_HIGH")
                )
            else:
                exclusions.append(
                    TargetExclusion(player_id, owner_id, "SELL_HIGH", "NO_SELL_HIGH_SIGNAL")
                )
        else:
            lineup_fit = bool(
                metrics.acquire_lineup_gain is not None
                and metrics.acquire_lineup_gain > 0.0
                and metrics.acquire_lineup_gain >= config.minimum_lineup_gain
            )
            user_fit = lineup_fit or bool(metrics.depth_fit)
            if not user_fit:
                exclusions.append(
                    TargetExclusion(player_id, owner_id, None, "NO_USER_LINEUP_OR_DEPTH_FIT")
                )
                continue
            if signal == "BUY_LOW":
                kinds.append("BUY_LOW")
            if (
                metrics.acquire_lineup_gain is not None
                and metrics.acquire_lineup_gain >= config.consolidation_lineup_gain
            ):
                kinds.append("CONSOLIDATE")
            if not kinds and signal == "ALIGNED":
                kinds.append("NEED_FIT")
            if not kinds:
                exclusions.append(
                    TargetExclusion(player_id, owner_id, None, "OPPONENT_MARKET_PREMIUM")
                )
        for kind in kinds:
            card = _card(
                kind=kind,
                snapshot=snapshot,
                player_id=player_id,
                player_name=player.name,
                position=selected_row.position,
                owner=owner,
                intrinsic=intrinsic,
                market_ecr=market_ecr,
                trade_price=trade_price,
                market_gap=market_gap,
                metrics=metrics,
                performance=performance,
            )
            candidates[kind].append(card)

    targets: list[TradeTarget] = []
    lane_counts: list[tuple[str, int, int]] = []
    for kind in TARGET_KINDS:
        ordered = sorted(candidates[kind], key=_target_sort_key)
        retained = ordered[: config.max_targets_per_lane]
        targets.extend(
            replace(target, rank_in_lane=index) for index, target in enumerate(retained, 1)
        )
        exclusions.extend(
            TargetExclusion(
                target.player_id,
                target.roster.owner_roster_id,
                kind,
                "LANE_LIMIT",
            )
            for target in ordered[config.max_targets_per_lane :]
        )
        lane_counts.append((kind, len(ordered), len(retained)))
    result_warnings = tuple(
        dict.fromkeys(
            (
                *snapshot.warnings,
                *summarize_projection_warnings(matrix.warnings),
                *market_warnings,
                "All targets are WATCH until package search clears both teams' exact gates",
                "Owner disposability is modeled roster evidence, not opponent preference",
            )
        )
    )
    base = TargetDiscoveryResult(
        schema_version=1,
        manifest_id=snapshot.manifest.analysis_id,
        league_key=snapshot.league_key,
        horizon=snapshot.ranking_horizon,
        pricing_mode=pricing_mode,
        selected_board_hash=stable_hash(asdict(selected_board)),
        market_ecr_board_hash=stable_hash(asdict(market_ecr_board)),
        trade_market_board_hash=(direct_board.evidence_hash if direct_board is not None else None),
        config=config,
        targets=tuple(targets),
        lane_counts=tuple(lane_counts),
        exclusions=tuple(exclusions),
        warnings=result_warnings,
        evidence_hash="",
    )
    return replace(base, evidence_hash=stable_hash(asdict(base)))
