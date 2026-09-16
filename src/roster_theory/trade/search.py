from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from itertools import combinations
from typing import Mapping, Sequence

from roster_theory.core.errors import CoverageIncomplete, RosterIllegal
from roster_theory.core.models import Projection
from roster_theory.core.provenance import stable_hash
from roster_theory.trade.boards import ValuationGap, ValueBoard
from roster_theory.trade.evaluation import (
    EvaluationOptions,
    PlayerAsset,
    RosterDiagnosis,
    TradeEvaluation,
    TradePackage,
    build_weekly_projection_matrix,
    diagnose_roster,
    evaluate_trade,
)
from roster_theory.trade.snapshot import SKILL_POSITIONS, TradeSnapshot


SMALL_PACKAGE_SIZES = ((1, 1), (2, 1), (1, 2), (2, 2))
LARGE_PACKAGE_SIZES = tuple(
    (sent, received)
    for sent in range(1, 5)
    for received in range(1, 5)
    if max(sent, received) >= 3 and abs(sent - received) <= 3
)


@dataclass(frozen=True, slots=True)
class SearchConfig:
    small_pool_per_team: int = 6
    large_pool_per_team: int = 4
    market_band_ratio: float = 0.50
    market_band_floor: float = 15.0
    bilateral_value_ratio: float = 0.60
    max_exact_per_opponent: int = 2
    max_large_exact_per_opponent: int = 1
    max_results: int = 20
    search_policy_version: str = "phase9-search-construction-v1"
    target_market_value_floor: float = 0.0
    target_raw_projection_floor: float = 0.0
    target_material_gap_floor: float = 5.0
    max_partner_lineup_loss: float = 10.0
    near_waiver_need_margin: float = 1.0
    reject_received_asset_drop: bool = True

    def __post_init__(self) -> None:
        integer_fields = (
            self.small_pool_per_team,
            self.large_pool_per_team,
            self.max_exact_per_opponent,
            self.max_large_exact_per_opponent,
            self.max_results,
        )
        if any(value < 0 for value in integer_fields):
            raise ValueError("Search pool, exact-evaluation, and result limits cannot be negative")
        if self.large_pool_per_team > self.small_pool_per_team:
            raise ValueError("large_pool_per_team cannot exceed small_pool_per_team")
        if self.market_band_ratio < 0 or self.market_band_floor < 0:
            raise ValueError("Market-band limits cannot be negative")
        if self.max_partner_lineup_loss < 0:
            raise ValueError("max_partner_lineup_loss cannot be negative")
        if self.near_waiver_need_margin < 0:
            raise ValueError("near_waiver_need_margin cannot be negative")
        if not 0 <= self.bilateral_value_ratio <= 1:
            raise ValueError("bilateral_value_ratio must be between zero and one")


@dataclass(frozen=True, slots=True)
class SearchCoverage:
    package_size: str
    enumerated: int
    pruned: int
    evaluated: int
    accepted: int


@dataclass(frozen=True, slots=True)
class SearchOpportunity:
    opponent_roster_id: str
    sent_player_ids: tuple[str, ...]
    received_player_ids: tuple[str, ...]
    package_size: str
    label: str
    user_rationale: str
    partner_rationale: str
    objective_tags: tuple[str, ...]
    user_lineup_delta: float
    user_depth_delta: float
    user_selected_delta: float
    user_market_delta: float
    user_raw_projection_delta: float
    user_downside_delta: float
    partner_lineup_delta: float
    partner_market_delta: float
    market_gap_edge: float
    evaluation: TradeEvaluation


@dataclass(frozen=True, slots=True)
class LeagueSearchResult:
    schema_version: int
    manifest_id: str
    league_key: str
    horizon: str
    risk_posture: str
    search_policy_version: str
    diagnostics: tuple[RosterDiagnosis, ...]
    opportunities: tuple[SearchOpportunity, ...]
    coverage: tuple[SearchCoverage, ...]
    rejection_counts: tuple[tuple[str, int], ...]
    exhaustive_large_search: bool
    evidence_hash: str


def _board_values(board: ValueBoard) -> dict[str, float]:
    return {row.player_id: float(row.reconciled_vorp) for row in board.players}


def _package_size(sent: Sequence[str], received: Sequence[str]) -> str:
    return f"{len(sent)}-for-{len(received)}"


def _diagnosis_maps(
    diagnosis: RosterDiagnosis,
    near_waiver_margin: float = 0.0,
) -> tuple[set[str], set[str]]:
    needs = {
        row.position
        for row in diagnosis.positions
        if row.need_above_waiver > 0.0
        or (
            near_waiver_margin > 0.0
            and row.weakest_starter_average_points is not None
            and row.waiver_average_points is not None
            and row.weakest_starter_average_points - row.waiver_average_points
            <= near_waiver_margin
        )
    }
    surplus = {
        player_id
        for row in diagnosis.positions
        for player_id in row.usable_surplus_player_ids
    }
    return needs, surplus


def _candidate_pool(
    snapshot: TradeSnapshot,
    roster_id: str,
    diagnosis: RosterDiagnosis,
    selected_values: Mapping[str, float],
    limit: int,
) -> tuple[str, ...]:
    team = next(team for team in snapshot.teams if team.roster_id == roster_id)
    player_by_id = {player.player_id: player for player in snapshot.players}
    _, surplus = _diagnosis_maps(diagnosis)
    eligible = tuple(
        player_id
        for player_id in team.player_ids
        if player_id not in set(team.reserve_ids)
        and player_id in selected_values
        and (player := player_by_id.get(player_id)) is not None
        and bool(SKILL_POSITIONS.intersection(player.positions))
    )
    # A value-only pool hides the exact players that make construction trades
    # work in shallow leagues: the weakest player at a thin position and the
    # expendable half of a same-position pair.  Retain diagnosed surplus first,
    # then one fringe asset per skill position, before filling the bounded pool
    # with the strongest remaining values.
    ordered_surplus = sorted(
        (player_id for player_id in eligible if player_id in surplus),
        key=lambda player_id: (-selected_values[player_id], player_id),
    )
    fringe_by_position = []
    for position in sorted(SKILL_POSITIONS):
        positional = tuple(
            player_id
            for player_id in eligible
            if position in player_by_id[player_id].positions
        )
        if positional:
            fringe_by_position.append(
                min(positional, key=lambda player_id: (selected_values[player_id], player_id))
            )
    strongest_remaining = sorted(
        eligible,
        key=lambda player_id: (-selected_values[player_id], player_id),
    )
    ordered = tuple(
        dict.fromkeys((*ordered_surplus, *fringe_by_position, *strongest_remaining))
    )
    return ordered[:limit]


def enumerate_candidate_packages(
    user_roster_id: str,
    opponent_roster_id: str,
    user_pool: Sequence[str],
    opponent_pool: Sequence[str],
    sizes: Sequence[tuple[int, int]],
) -> tuple[TradePackage, ...]:
    packages: dict[tuple[tuple[str, ...], tuple[str, ...]], TradePackage] = {}
    for sent_count, received_count in sizes:
        if sent_count > len(user_pool) or received_count > len(opponent_pool):
            continue
        for sent in combinations(sorted(set(user_pool)), sent_count):
            for received in combinations(sorted(set(opponent_pool)), received_count):
                key = (sent, received)
                packages[key] = TradePackage(
                    roster_a_id=user_roster_id,
                    roster_b_id=opponent_roster_id,
                    from_a=tuple(PlayerAsset(player_id) for player_id in sent),
                    from_b=tuple(PlayerAsset(player_id) for player_id in received),
                )
    return tuple(packages[key] for key in sorted(packages))


def _prefilter(
    package: TradePackage,
    *,
    snapshot: TradeSnapshot,
    diagnostics: Mapping[str, RosterDiagnosis],
    selected_values: Mapping[str, float],
    market_values: Mapping[str, float],
    config: SearchConfig,
    options: EvaluationOptions,
) -> tuple[bool, str, tuple[float, float, float, tuple[str, ...], tuple[str, ...]]]:
    sent = tuple(asset.player_id for asset in package.from_a)
    received = tuple(asset.player_id for asset in package.from_b)
    selected_sent = sum(max(0.0, selected_values[player_id]) for player_id in sent)
    selected_received = sum(max(0.0, selected_values[player_id]) for player_id in received)
    market_sent = sum(max(0.0, market_values[player_id]) for player_id in sent)
    market_received = sum(max(0.0, market_values[player_id]) for player_id in received)
    selected_gain = selected_received - selected_sent
    partner_market_gain = market_sent - market_received
    if len(received) >= len(sent) and selected_gain < options.user_selected_floor:
        return False, "user_selected_upper_bound", (0.0, 0.0, 0, sent, received)
    if len(sent) >= len(received) and partner_market_gain < options.partner_market_floor:
        return False, "partner_market_upper_bound", (0.0, 0.0, 0, sent, received)
    market_scale = max(market_sent, market_received, 1.0)
    if abs(market_received - market_sent) > max(
        config.market_band_floor, config.market_band_ratio * market_scale
    ):
        return False, "market_band", (0.0, 0.0, 0, sent, received)
    player_by_id = {player.player_id: player for player in snapshot.players}
    user_needs, user_surplus = _diagnosis_maps(
        diagnostics[package.roster_a_id], config.near_waiver_need_margin
    )
    partner_needs, partner_surplus = _diagnosis_maps(
        diagnostics[package.roster_b_id], config.near_waiver_need_margin
    )
    user_received_positions = {
        position for player_id in received for position in player_by_id[player_id].positions
    }
    partner_received_positions = {
        position for player_id in sent for position in player_by_id[player_id].positions
    }
    user_need_hit = bool(user_needs & user_received_positions)
    partner_need_hit = bool(partner_needs & partner_received_positions)
    user_surplus_hit = bool(user_surplus & set(sent))
    partner_surplus_hit = bool(partner_surplus & set(received))
    user_reason = user_need_hit or user_surplus_hit
    partner_reason = partner_need_hit or partner_surplus_hit
    if not user_reason and selected_received < selected_sent * config.bilateral_value_ratio:
        return False, "user_rationale", (0.0, 0.0, 0, sent, received)
    if not partner_reason and market_sent < market_received * config.bilateral_value_ratio:
        return False, "partner_rationale", (0.0, 0.0, 0, sent, received)
    market_imbalance = abs(market_received - market_sent)
    need_bonus = (
        2 * int(user_need_hit)
        + 2 * int(partner_need_hit)
        + int(user_surplus_hit)
        + int(partner_surplus_hit)
    )
    gate_margin = min(
        selected_gain - options.user_selected_floor,
        partner_market_gain - options.partner_market_floor,
    )
    return True, "retained", (-need_bonus, -gate_margin, market_imbalance, sent, received)


def _opportunity(
    evaluation: TradeEvaluation,
    gaps: Mapping[str, ValuationGap],
    diagnostics: Mapping[str, RosterDiagnosis],
    snapshot: TradeSnapshot,
    config: SearchConfig,
) -> tuple[SearchOpportunity | None, str]:
    if not evaluation.team_impacts or not evaluation.risk_impacts:
        return None, "incomplete_exact_evaluation"
    user_team, partner_team = evaluation.team_impacts
    user_value, partner_value = evaluation.ownership_impacts
    user_selected = (
        float(user_value.selected_package_delta or 0.0)
        + float(user_value.selected_secondary_delta or 0.0)
    )
    user_market = user_value.market_package_delta + user_value.market_secondary_delta
    user_raw = (
        user_value.raw_projection_received
        - user_value.raw_projection_sent
        + user_value.raw_projection_secondary_delta
    )
    partner_market = partner_value.market_package_delta + partner_value.market_secondary_delta
    if evaluation.decision_label != "ACCEPTABLE":
        return None, "phase6_decision_gate"
    if user_team.weighted_delta <= 0.0:
        return None, "user_lineup_gate"
    incoming_by_roster = {
        evaluation.package.roster_a_id: {
            asset.player_id for asset in evaluation.package.from_b
        },
        evaluation.package.roster_b_id: {
            asset.player_id for asset in evaluation.package.from_a
        },
    }
    if config.reject_received_asset_drop and any(
        move.kind == "DROP"
        and bool(set(move.chosen_player_ids) & incoming_by_roster[move.roster_id])
        for move in evaluation.secondary_moves
    ):
        return None, "received_asset_immediately_dropped"
    if (
        partner_team.weighted_delta < -config.max_partner_lineup_loss
        and partner_market <= 0.0
    ):
        return None, "partner_lineup_credibility"
    market_failed = user_market < config.target_market_value_floor
    raw_failed = user_raw < config.target_raw_projection_floor
    if market_failed and raw_failed:
        return None, "target_market_and_raw_projection_gates"
    if market_failed:
        return None, "target_market_value_gate"
    if raw_failed:
        return None, "target_raw_projection_gate"
    sent = tuple(asset.player_id for asset in evaluation.package.from_a)
    received = tuple(asset.player_id for asset in evaluation.package.from_b)
    gap_edge = sum(-gaps[player_id].value_gap for player_id in received) - sum(
        -gaps[player_id].value_gap for player_id in sent
    )
    player_by_id = {player.player_id: player for player in snapshot.players}
    user_diagnosis = diagnostics[evaluation.package.roster_a_id]
    strict_user_needs, user_surplus = _diagnosis_maps(user_diagnosis)
    user_needs, _ = _diagnosis_maps(
        user_diagnosis, config.near_waiver_need_margin
    )
    received_positions = {
        position
        for player_id in received
        for position in player_by_id[player_id].positions
    }
    if strict_user_needs & received_positions:
        target_basis = "fills a diagnosed roster need"
    elif user_needs & received_positions:
        target_basis = "upgrades a near-replacement starter"
    elif user_surplus & set(sent):
        target_basis = "converts diagnosed usable surplus"
    elif gap_edge >= config.target_material_gap_floor:
        target_basis = "exploits a material selected-versus-market gap"
    else:
        return None, "target_rationale_gate"
    partner_rationale = (
        "improves the partner's exact projected lineup"
        if partner_team.weighted_delta > 0.0
        else "keeps the partner's market-value return within the policy floor"
    )
    return SearchOpportunity(
        opponent_roster_id=evaluation.package.roster_b_id,
        sent_player_ids=sent,
        received_player_ids=received,
        package_size=_package_size(sent, received),
        label="TARGET",
        user_rationale=target_basis,
        partner_rationale=partner_rationale,
        objective_tags=(),
        user_lineup_delta=user_team.weighted_delta,
        user_depth_delta=user_team.depth_delta,
        user_selected_delta=round(user_selected, 3),
        user_market_delta=round(user_market, 3),
        user_raw_projection_delta=round(user_raw, 3),
        user_downside_delta=evaluation.risk_impacts[0].offense_downside_loss_delta,
        partner_lineup_delta=partner_team.weighted_delta,
        partner_market_delta=round(partner_market, 3),
        market_gap_edge=round(gap_edge, 3),
        evaluation=evaluation,
    ), "accepted"


def _dominates(first: SearchOpportunity, second: SearchOpportunity) -> bool:
    first_values = (
        first.user_lineup_delta,
        first.user_selected_delta,
        first.partner_market_delta,
        -first.user_downside_delta,
        -float(len(first.sent_player_ids) + len(first.received_player_ids)),
    )
    second_values = (
        second.user_lineup_delta,
        second.user_selected_delta,
        second.partner_market_delta,
        -second.user_downside_delta,
        -float(len(second.sent_player_ids) + len(second.received_player_ids)),
    )
    return all(a >= b for a, b in zip(first_values, second_values)) and any(
        a > b for a, b in zip(first_values, second_values)
    )


def _pareto_frontier(opportunities: Sequence[SearchOpportunity]) -> tuple[SearchOpportunity, ...]:
    retained = tuple(
        row
        for row in opportunities
        if not any(
            other is not row and _dominates(other, row)
            for other in opportunities
        )
    )
    if not retained:
        return ()
    objectives: dict[str, SearchOpportunity] = {
        "EXPECTED_POINTS": max(retained, key=lambda row: (row.user_lineup_delta, row.sent_player_ids, row.received_player_ids)),
        "LOWER_RISK": min(retained, key=lambda row: (row.user_downside_delta, -row.user_lineup_delta, row.sent_player_ids, row.received_player_ids)),
        "MARKET_GAP": max(retained, key=lambda row: (row.market_gap_edge, row.user_lineup_delta, row.sent_player_ids, row.received_player_ids)),
        "PARTNER_POSITIVE": max(retained, key=lambda row: (row.partner_market_delta, row.partner_lineup_delta, row.sent_player_ids, row.received_player_ids)),
        "SIMPLE": min(retained, key=lambda row: (len(row.sent_player_ids) + len(row.received_player_ids), -row.user_lineup_delta, row.sent_player_ids, row.received_player_ids)),
    }
    tags_by_key: dict[tuple[tuple[str, ...], tuple[str, ...]], list[str]] = {}
    for tag, row in objectives.items():
        tags_by_key.setdefault((row.sent_player_ids, row.received_player_ids), []).append(tag)
    return tuple(
        replace(
            row,
            objective_tags=tuple(
                sorted(
                    tags_by_key.get(
                        (row.sent_player_ids, row.received_player_ids),
                        ("PARETO_ALTERNATIVE",),
                    )
                )
            ),
        )
        for row in sorted(
            retained,
            key=lambda item: (
                -item.user_lineup_delta,
                -item.user_selected_delta,
                -item.partner_market_delta,
                len(item.sent_player_ids) + len(item.received_player_ids),
                item.sent_player_ids,
                item.received_player_ids,
            ),
        )
    )


def search_league(
    snapshot: TradeSnapshot,
    *,
    projections: Sequence[Projection],
    selected_board: ValueBoard,
    market_board: ValueBoard,
    gaps: Sequence[ValuationGap],
    options: EvaluationOptions = EvaluationOptions(),
    config: SearchConfig = SearchConfig(),
) -> LeagueSearchResult:
    projection_matrix = build_weekly_projection_matrix(snapshot, projections)
    diagnostics = tuple(
        diagnose_roster(
            snapshot,
            projections,
            roster_id=team.roster_id,
            options=options,
            projection_matrix=projection_matrix,
        )
        for team in sorted(snapshot.teams, key=lambda row: row.roster_id)
    )
    diagnosis_by_id = {row.roster_id: row for row in diagnostics}
    selected_values = _board_values(selected_board)
    market_values = _board_values(market_board)
    gap_by_id = {row.player_id: row for row in gaps}
    user_pool = _candidate_pool(
        snapshot,
        snapshot.user_roster_id,
        diagnosis_by_id[snapshot.user_roster_id],
        selected_values,
        config.small_pool_per_team,
    )
    coverage_counts: dict[str, list[int]] = {}
    rejection_counts: dict[str, int] = {}
    opportunities: list[SearchOpportunity] = []
    for opponent in sorted(
        (team for team in snapshot.teams if team.roster_id != snapshot.user_roster_id),
        key=lambda row: row.roster_id,
    ):
        opponent_pool = _candidate_pool(
            snapshot,
            opponent.roster_id,
            diagnosis_by_id[opponent.roster_id],
            selected_values,
            config.small_pool_per_team,
        )
        for group_index in range(2):
            if group_index == 0:
                sizes = SMALL_PACKAGE_SIZES
                sent_pool = user_pool
                received_pool = opponent_pool
                exact_limit = config.max_exact_per_opponent
            else:
                sizes = LARGE_PACKAGE_SIZES
                opponent_frontier = tuple(
                    row
                    for row in opportunities
                    if row.opponent_roster_id == opponent.roster_id
                )
                seeded_sent = tuple(
                    dict.fromkeys(
                        player_id
                        for row in opponent_frontier
                        for player_id in row.sent_player_ids
                    )
                )
                seeded_received = tuple(
                    dict.fromkeys(
                        player_id
                        for row in opponent_frontier
                        for player_id in row.received_player_ids
                    )
                )
                sent_pool = tuple(
                    dict.fromkeys((*seeded_sent, *user_pool))
                )[: config.large_pool_per_team]
                received_pool = tuple(
                    dict.fromkeys((*seeded_received, *opponent_pool))
                )[: config.large_pool_per_team]
                exact_limit = config.max_large_exact_per_opponent
            packages = enumerate_candidate_packages(
                snapshot.user_roster_id,
                opponent.roster_id,
                sent_pool,
                received_pool,
                sizes,
            )
            retained: list[
                tuple[
                    tuple[float, float, float, tuple[str, ...], tuple[str, ...]],
                    TradePackage,
                ]
            ] = []
            for package in packages:
                size = _package_size(package.from_a, package.from_b)
                counts = coverage_counts.setdefault(size, [0, 0, 0, 0])
                counts[0] += 1
                keep, reason, sort_key = _prefilter(
                    package,
                    snapshot=snapshot,
                    diagnostics=diagnosis_by_id,
                    selected_values=selected_values,
                    market_values=market_values,
                    config=config,
                    options=options,
                )
                if keep:
                    retained.append((sort_key, package))
                else:
                    counts[1] += 1
                    rejection_counts[reason] = rejection_counts.get(reason, 0) + 1
            retained.sort(key=lambda row: row[0])
            for _, package in retained[exact_limit:]:
                size = _package_size(package.from_a, package.from_b)
                coverage_counts[size][1] += 1
                rejection_counts["runtime_bound"] = (
                    rejection_counts.get("runtime_bound", 0) + 1
                )
            for _, package in retained[:exact_limit]:
                size = _package_size(package.from_a, package.from_b)
                coverage_counts[size][2] += 1
                try:
                    evaluation = evaluate_trade(
                        snapshot,
                        package,
                        projections=projections,
                        selected_board=selected_board,
                        market_board=market_board,
                        options=options,
                        projection_matrix=projection_matrix,
                    )
                except (CoverageIncomplete, RosterIllegal) as exc:
                    key = type(exc).__name__
                    rejection_counts[key] = rejection_counts.get(key, 0) + 1
                    continue
                opportunity, exact_reason = _opportunity(
                    evaluation,
                    gap_by_id,
                    diagnosis_by_id,
                    snapshot,
                    config,
                )
                if opportunity is None:
                    rejection_counts[exact_reason] = (
                        rejection_counts.get(exact_reason, 0) + 1
                    )
                    continue
                coverage_counts[size][3] += 1
                opportunities.append(opportunity)
    frontier = _pareto_frontier(opportunities)[: config.max_results]
    coverage = tuple(
        SearchCoverage(size, *coverage_counts[size]) for size in sorted(coverage_counts)
    )
    base = LeagueSearchResult(
        schema_version=1,
        manifest_id=snapshot.manifest.analysis_id,
        league_key=snapshot.league_key,
        horizon=snapshot.ranking_horizon,
        risk_posture=options.risk_posture.upper(),
        search_policy_version=config.search_policy_version,
        diagnostics=diagnostics,
        opportunities=frontier,
        coverage=coverage,
        rejection_counts=tuple(sorted(rejection_counts.items())),
        exhaustive_large_search=False,
        evidence_hash="",
    )
    return replace(base, evidence_hash=stable_hash(asdict(base)))
