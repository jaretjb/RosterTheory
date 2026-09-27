"""Trade policy and compatibility entry point for shared value preparation."""

from __future__ import annotations

from roster_theory.application import value_preparation as _shared
from roster_theory.application.value_preparation import *  # noqa: F403
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


def _trade_panel(inputs, now, league_key):
    return select_trade_ros_panel(inputs, now, league_key=league_key)


def refresh_value_boards(league_key: str, **kwargs):
    return _shared.refresh_value_boards(
        league_key,
        refresh_snapshot=refresh_trade_snapshot,
        retag_snapshot=retag_trade_snapshot,
        save_snapshot=save_trade_snapshot,
        default_expert_pool_resolver=_trade_panel,
        output_root="data/exports/trade",
        evidence_product="TRADE ASSISTANT",
        valuation_warning="Valuation gaps are signals, not trade recommendations or opponent preferences",
        **kwargs,
    )


def __getattr__(name: str):
    return getattr(_shared, name)
