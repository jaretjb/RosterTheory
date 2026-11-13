"""Trade policy and compatibility entry point for shared value preparation."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, replace
from functools import partial
from pathlib import Path

from roster_theory.application import value_preparation as _shared
from roster_theory.application.value_preparation import *  # noqa: F403
from roster_theory.core.errors import CoverageIncomplete
from roster_theory.core.expert_qualification import MAXIMUM_WEIGHTED_AVERAGE_RANK, qualify_expert
from roster_theory.providers.expert_accuracy import load_weekly_accuracy_history
from roster_theory.trade.expert_panel import select_trade_ros_panel
from roster_theory.trade.service import refresh_trade_snapshot
from roster_theory.trade.snapshot import retag_trade_snapshot, save_trade_snapshot


TradeScoringCapability = _shared.SkillProjectionScoringCapability
classify_trade_scoring = _shared.classify_skill_projection_scoring
validate_trade_scoring = _shared.validate_skill_projection_scoring


def board_refresh_report(result):
    return {
        **_shared.value_board_summary(result),
        "product": "TRADE ASSISTANT",
        "operation": "VALUE BOARD REFRESH",
        "sign_convention": "positive value_gap = market above selected (possible sell-high); negative = selected above market (possible buy-low)",
        "opponent_preference_claimed": False,
    }


def _trade_panel(inputs, now, league_key, season, *, pool_path=None):
    years = tuple(range(season - 5, season))
    path = Path(f"data/manual/fantasypros/inseason_accuracy_{years[0]}_{years[-1]}.csv")
    rows, history = load_weekly_accuracy_history(
        path, years, evidence_dir=Path(f"data/cache/fantasypros/{season}/expert_evidence"),
    )
    by_id = defaultdict(list)
    for row in rows:
        by_id[row.expert_id].append((row.year, row.overall_rank))
    qualification = {expert_id: qualify_expert(ranks, years) for expert_id, ranks in by_id.items()}
    if pool_path is None:
        panel = select_trade_ros_panel(inputs, now, league_key=league_key, qualification=qualification)
        return replace(panel, evidence={**panel.evidence, "history": history})

    members = []
    excluded = []
    for member in _shared.load_expert_pool(pool_path):
        result = qualification.get(member.expert_id)
        if result is None or result.issue:
            excluded.append({"expert_id": member.expert_id, "expert_name": member.expert_name,
                             "reason": result.issue if result else "insufficient_historical_accuracy"})
        else:
            members.append(member)
    if len(members) < 2:
        raise CoverageIncomplete(
            f"Configured Trade expert pool has {len(members)} qualified experts; at least two are required"
        )
    total = sum(member.weight for member in members)
    if total <= 0:
        raise CoverageIncomplete("Configured Trade expert pool has no positive qualified weight")
    pool = tuple(replace(member, weight=member.weight / total) for member in members)
    return _shared.ExpertPoolResolution(pool, {
        "status": "READY" if len(pool) >= 3 else "DEGRADED",
        "selection_method": "configured_expert_pool",
        "preferred_size": 3,
        "minimum_size": 2,
        "maximum_weighted_average_rank": MAXIMUM_WEIGHTED_AVERAGE_RANK,
        "history": history,
        "members": [asdict(member) for member in pool],
        "exclusions": excluded,
    })


def refresh_value_boards(league_key: str, **kwargs):
    pool_path = kwargs.pop("expert_pool_path", None)
    return _shared.refresh_value_boards(
        league_key,
        refresh_snapshot=refresh_trade_snapshot,
        retag_snapshot=retag_trade_snapshot,
        save_snapshot=save_trade_snapshot,
        default_expert_pool_resolver=partial(_trade_panel, pool_path=pool_path),
        output_root="data/exports/trade",
        evidence_product="TRADE ASSISTANT",
        valuation_warning="Valuation gaps are signals, not trade recommendations or opponent preferences",
        **kwargs,
    )


def __getattr__(name: str):
    return getattr(_shared, name)
