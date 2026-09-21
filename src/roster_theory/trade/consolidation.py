from __future__ import annotations

from dataclasses import dataclass

from roster_theory.inseason.evaluation import (
    InSeasonContext,
    WeeklyProjectionMatrix,
    team_impact,
)
from roster_theory.trade.evaluation import EvaluationOptions, TradeEvaluation
from roster_theory.trade.snapshot import TradeSnapshot


@dataclass(frozen=True, slots=True)
class PartnerAssetUse:
    player_id: str
    started_weeks: tuple[int, ...]
    marginal_lineup_points: float
    marginal_depth_above_waiver: float
    use: str
    passes_use_gate: bool


@dataclass(frozen=True, slots=True)
class ConsolidationEvidence:
    target_player_id: str
    target_started_weeks: tuple[int, ...]
    target_marginal_lineup_points: float
    user_exact_lineup_delta: float
    starter_upgrade_threshold: float
    starter_upgrade_passed: bool
    user_add_player_id: str | None
    user_add_marginal_lineup_points: float | None
    user_add_marginal_depth_above_waiver: float | None
    partner_drop_player_id: str | None
    partner_drop_lineup_effect: float | None
    partner_drop_depth_effect: float | None
    partner_asset_uses: tuple[PartnerAssetUse, ...]
    secondary_moves_complete: bool
    both_outgoing_assets_used: bool
    passes: bool
    warnings: tuple[str, ...]


def _final_roster(
    snapshot: TradeSnapshot,
    evaluation: TradeEvaluation,
    roster_id: str,
) -> set[str]:
    team = next(team for team in snapshot.teams if team.roster_id == roster_id)
    roster = set(team.player_ids) - set(team.reserve_ids)
    if roster_id == evaluation.package.roster_a_id:
        roster.difference_update(asset.player_id for asset in evaluation.package.from_a)
        roster.update(asset.player_id for asset in evaluation.package.from_b)
    else:
        roster.difference_update(asset.player_id for asset in evaluation.package.from_b)
        roster.update(asset.player_id for asset in evaluation.package.from_a)
    for move in evaluation.secondary_moves:
        if move.roster_id != roster_id:
            continue
        if move.kind == "ADD":
            roster.update(move.chosen_player_ids)
        elif move.kind == "DROP":
            roster.difference_update(move.chosen_player_ids)
    return roster


def analyze_consolidation(
    snapshot: TradeSnapshot,
    evaluation: TradeEvaluation,
    *,
    context: InSeasonContext,
    matrix: WeeklyProjectionMatrix,
    options: EvaluationOptions,
    minimum_starter_upgrade: float,
    minimum_partner_lineup_use: float,
    minimum_partner_depth_use: float,
) -> ConsolidationEvidence:
    """Audit a 2-for-1 against both final rosters, including add and drop."""

    if len(evaluation.package.from_a) != 2 or len(evaluation.package.from_b) != 1:
        raise ValueError("Consolidation evidence requires a user 2-for-1 package")
    if len(evaluation.team_impacts) != 2 or len(evaluation.secondary_moves) != 2:
        raise ValueError("Consolidation evidence requires exact two-team impacts and moves")
    if minimum_starter_upgrade <= 0.0:
        raise ValueError("minimum_starter_upgrade must be positive")
    if minimum_partner_lineup_use < 0.0 or minimum_partner_depth_use < 0.0:
        raise ValueError("Partner-use thresholds cannot be negative")

    user_id = evaluation.package.roster_a_id
    partner_id = evaluation.package.roster_b_id
    target_id = evaluation.package.from_b[0].player_id
    user_final = _final_roster(snapshot, evaluation, user_id)
    partner_final = _final_roster(snapshot, evaluation, partner_id)
    move_by_roster = {move.roster_id: move for move in evaluation.secondary_moves}
    user_move = move_by_roster[user_id]
    partner_move = move_by_roster[partner_id]
    secondary_complete = (
        user_move.kind == "ADD"
        and len(user_move.chosen_player_ids) == 1
        and partner_move.kind == "DROP"
        and len(partner_move.chosen_player_ids) == 1
    )
    add_id = user_move.chosen_player_id if secondary_complete else None
    drop_id = partner_move.chosen_player_id if secondary_complete else None

    target_impact = team_impact(
        context, matrix, user_id, user_final - {target_id}, user_final, options
    )
    started_weeks = tuple(
        week.week
        for week in evaluation.team_impacts[0].weeks
        if target_id in week.after_starters
    )
    starter_passed = bool(
        started_weeks
        and evaluation.team_impacts[0].weighted_delta >= minimum_starter_upgrade
        and target_impact.weighted_delta >= minimum_starter_upgrade
    )

    add_lineup: float | None = None
    add_depth: float | None = None
    drop_lineup: float | None = None
    drop_depth: float | None = None
    if add_id is not None:
        add_impact = team_impact(
            context, matrix, user_id, user_final - {add_id}, user_final, options
        )
        add_lineup = add_impact.weighted_delta
        add_depth = add_impact.depth_delta
    if drop_id is not None:
        drop_impact = team_impact(
            context, matrix, partner_id, partner_final | {drop_id}, partner_final, options
        )
        drop_lineup = drop_impact.weighted_delta
        drop_depth = drop_impact.depth_delta

    partner_uses: list[PartnerAssetUse] = []
    for asset in evaluation.package.from_a:
        player_id = asset.player_id
        if player_id not in partner_final:
            partner_uses.append(
                PartnerAssetUse(player_id, (), 0.0, 0.0, "DROPPED", False)
            )
            continue
        impact = team_impact(
            context, matrix, partner_id, partner_final - {player_id}, partner_final, options
        )
        started = tuple(
            week.week
            for week in evaluation.team_impacts[1].weeks
            if player_id in week.after_starters
        )
        lineup_use = bool(
            started and impact.weighted_delta > minimum_partner_lineup_use
        )
        depth_use = impact.depth_delta > minimum_partner_depth_use
        use = "STARTER" if lineup_use else "DEPTH" if depth_use else "UNUSED"
        partner_uses.append(
            PartnerAssetUse(
                player_id=player_id,
                started_weeks=started,
                marginal_lineup_points=impact.weighted_delta,
                marginal_depth_above_waiver=impact.depth_delta,
                use=use,
                passes_use_gate=lineup_use or depth_use,
            )
        )

    both_used = all(row.passes_use_gate for row in partner_uses)
    warnings = []
    if not secondary_complete:
        warnings.append("The user's add and partner's drop are not both resolved")
    if not starter_passed:
        warnings.append("The target does not clear the exact starter-upgrade threshold")
    if not both_used:
        warnings.append("At least one outgoing asset lacks partner lineup or waiver-relative depth use")
    if any(move.search_truncated for move in evaluation.secondary_moves):
        warnings.append("Secondary add/drop search was bounded")
    return ConsolidationEvidence(
        target_player_id=target_id,
        target_started_weeks=started_weeks,
        target_marginal_lineup_points=target_impact.weighted_delta,
        user_exact_lineup_delta=evaluation.team_impacts[0].weighted_delta,
        starter_upgrade_threshold=minimum_starter_upgrade,
        starter_upgrade_passed=starter_passed,
        user_add_player_id=add_id,
        user_add_marginal_lineup_points=add_lineup,
        user_add_marginal_depth_above_waiver=add_depth,
        partner_drop_player_id=drop_id,
        partner_drop_lineup_effect=drop_lineup,
        partner_drop_depth_effect=drop_depth,
        partner_asset_uses=tuple(partner_uses),
        secondary_moves_complete=secondary_complete,
        both_outgoing_assets_used=both_used,
        passes=secondary_complete and starter_passed and both_used,
        warnings=tuple(warnings),
    )
