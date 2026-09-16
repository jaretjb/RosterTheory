from __future__ import annotations

import math
import random
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field, replace
from functools import lru_cache
from hashlib import sha256
from itertools import combinations
from statistics import NormalDist, fmean, median, pstdev
from typing import Any, Iterable, Mapping

from roster_theory.draft_analysis import HistoricalPositionCurves
from roster_theory.specialist_preferences import (
    defense_draft_rank,
    defense_draft_sort_key,
)


SKILL_POSITIONS = ("QB", "RB", "WR", "TE")
DRAFT_POSITIONS = (*SKILL_POSITIONS, "K", "DST")
POSITION_CAPS = {"QB": 2, "RB": 6, "WR": 7, "TE": 2, "K": 1, "DST": 1}
MARKET_POSITION_PRIOR = {"QB": 0.13, "RB": 0.31, "WR": 0.33, "TE": 0.10, "K": 0.065, "DST": 0.065}
OPPONENT_POSITION_STRESS_PROFILES = (
    "raw",
    "early_rb",
    "early_wr",
    "middle_qb_te",
)
# Official 2026 NFL schedule release; update this year-specific map with the board season.
NFL_BYE_WEEKS_2026 = {
    "CAR": 5, "KC": 5,
    "CIN": 6, "DET": 6, "MIA": 6, "MIN": 6,
    "BUF": 7, "JAX": 7, "LAC": 7, "WAS": 7,
    "HOU": 8, "NO": 8, "NYG": 8, "SF": 8,
    "PIT": 9, "TEN": 9,
    "CHI": 10, "DEN": 10, "PHI": 10, "TB": 10,
    "ATL": 11, "CLE": 11, "GB": 11, "LAR": 11, "NE": 11, "SEA": 11,
    "BAL": 13, "IND": 13, "LV": 13, "NYJ": 13,
    "ARI": 14, "DAL": 14,
}


@dataclass(frozen=True, slots=True)
class Player:
    key: str
    name: str
    position: str
    projected_points: float
    adp: float
    vbd: float
    rank_score: float
    overall_rank_score: float = 999.0
    overall_ecr_rank: float = 999.0
    grouped_rank: float = 999.0
    ecr: float = 999.0
    board_order: float = 999.0
    team: str = ""
    acquisition_adp: float | None = None
    acquisition_position_slot: int | None = None
    raw_projected_points: float | None = None
    projection_value_position_rank: int | None = None
    overall_rank_stddev: float | None = None
    overall_rank_min: float | None = None
    overall_rank_max: float | None = None
    overall_rank_experts: int | None = None
    overall_rank_weight_coverage: float | None = None
    position_rank_stddev: float | None = None
    position_rank_min: float | None = None
    position_rank_max: float | None = None
    position_rank_experts: int | None = None
    position_rank_weight_coverage: float | None = None

    @property
    def acquisition_pick(self) -> float:
        return self.adp if self.acquisition_adp is None else self.acquisition_adp

    @property
    def source_projected_points(self) -> float:
        """Return the untouched FantasyPros projection used to build value curves."""

        return (
            self.projected_points
            if self.raw_projected_points is None
            else self.raw_projected_points
        )

    @classmethod
    def from_mapping(cls, row: Mapping[str, Any]) -> "Player":
        def optional_float(name: str) -> float | None:
            value = row.get(name)
            if value in (None, ""):
                return None
            try:
                return float(value)
            except (TypeError, ValueError):
                return None

        def optional_int(name: str) -> int | None:
            value = optional_float(name)
            return int(value) if value is not None else None

        position = str(row.get("position")).upper()
        if position == "DEF":
            position = "DST"
        overall_rank_value = float(
            row.get("overall_rank_score")
            or row.get("weighted_overall_rank")
            or 999.0
        )
        if overall_rank_value <= 0.0:
            overall_rank_value = 999.0
        overall_ecr_value = float(row.get("overall_ecr") or 999.0)
        if overall_ecr_value <= 0.0:
            overall_ecr_value = 999.0
        projected_points = float(row.get("projected_points") or 0.0)
        return cls(
            key=str(row.get("player_key") or row.get("sleeper_id") or row.get("player_name")),
            name=str(row.get("player_name")),
            position=position,
            projected_points=projected_points,
            # Position-relative expert rank is not an overall acquisition cost.
            # Missing overall ADP must stay late instead of pushing fringe QBs/TEs
            # into the early rounds by their within-position rank.
            adp=float(row.get("adp") or 999.0),
            vbd=float(row.get("vbd") or 0.0),
            rank_score=float(row.get("rank_score") or row.get("adp") or 999.0),
            overall_rank_score=overall_rank_value,
            overall_ecr_rank=overall_ecr_value,
            grouped_rank=float(row.get("weighted_cohort_rank") or row.get("rank_score") or 999.0),
            ecr=float(row.get("ecr") or row.get("rank_score") or 999.0),
            board_order=float(row.get("board_order") or row.get("adp") or 999.0),
            team=str(row.get("team") or "").upper().replace("JAC", "JAX"),
            raw_projected_points=projected_points,
            overall_rank_stddev=optional_float("overall_rank_stddev"),
            overall_rank_min=optional_float("overall_rank_min"),
            overall_rank_max=optional_float("overall_rank_max"),
            overall_rank_experts=optional_int("overall_rank_experts"),
            overall_rank_weight_coverage=optional_float(
                "overall_rank_weight_coverage"
            ),
            position_rank_stddev=optional_float("position_rank_stddev"),
            position_rank_min=optional_float("position_rank_min"),
            position_rank_max=optional_float("position_rank_max"),
            position_rank_experts=optional_int("position_rank_experts"),
            position_rank_weight_coverage=optional_float(
                "position_rank_weight_coverage"
            ),
        )


def expert_ordered_projection_players(players: Iterable[Player]) -> list[Player]:
    """Assign each positional projection distribution in selected-expert order.

    FantasyPros consensus projections provide the size and spacing of the value
    curve, but never player order.  Within each skill position, the highest raw
    projection is assigned to the best selected-expert positional rank, the
    next-highest projection to the next rank, and so on.  Raw projections stay
    attached for audit output.  The transform is computed from the full board
    by callers so values do not move merely because another player was drafted.
    """

    player_list = list(players)
    aligned_by_key: dict[str, Player] = {}
    for position in SKILL_POSITIONS:
        ranked = sorted(
            (
                player
                for player in player_list
                if player.position == position
                and player.projected_points > 0.0
                and 0.0 < player.rank_score < 999.0
            ),
            key=lambda player: (
                player.rank_score,
                player.overall_rank_score,
                player.adp,
                player.key,
            ),
        )
        projection_values = sorted(
            (player.projected_points for player in ranked), reverse=True
        )
        for position_rank, (player, projected_points) in enumerate(
            zip(ranked, projection_values), start=1
        ):
            adjustment = projected_points - player.projected_points
            aligned_by_key[player.key] = replace(
                player,
                projected_points=projected_points,
                vbd=player.vbd + adjustment,
                raw_projected_points=player.source_projected_points,
                projection_value_position_rank=position_rank,
            )
    return [
        aligned_by_key.get(
            player.key,
            replace(
                player,
                raw_projected_points=player.source_projected_points,
                projection_value_position_rank=None,
            ),
        )
        for player in player_list
    ]


def apply_acquisition_adp(
    players: Iterable[Player],
    history: HistoricalPositionCurves | None,
    history_weight: float,
) -> list[Player]:
    """Attach a positional-slot acquisition cost without changing raw ADP."""

    if not 0.0 <= history_weight <= 1.0:
        raise ValueError("Acquisition-history weight must be between 0 and 1")
    player_list = list(players)
    adjusted_by_key: dict[str, Player] = {}
    history_available = bool(history and history.available)
    censored_pick = (
        float(history.draft_end_pick + 1)
        if history_available and history and history.draft_end_pick is not None
        else None
    )
    for position in SKILL_POSITIONS:
        position_players = sorted(
            (
                player
                for player in player_list
                if player.position == position and 0.0 < player.adp < 999.0
            ),
            key=lambda player: (player.adp, player.rank_score),
        )
        targets = (
            history.position_picks.get(position, ())
            if history_available and history
            else ()
        )
        running_max = 0.0
        for slot, player in enumerate(position_players, start=1):
            if history_available:
                target = (
                    float(targets[slot - 1])
                    if slot <= len(targets)
                    else censored_pick
                )
                assert target is not None
                acquisition_adp = (
                    (1.0 - history_weight) * player.adp
                    + history_weight * target
                )
            else:
                acquisition_adp = player.adp
            acquisition_adp = max(running_max, acquisition_adp)
            running_max = acquisition_adp
            adjusted_by_key[player.key] = replace(
                player,
                acquisition_adp=acquisition_adp,
                acquisition_position_slot=slot,
            )
    return [
        adjusted_by_key.get(
            player.key,
            replace(
                player,
                acquisition_adp=player.adp,
                acquisition_position_slot=None,
            ),
        )
        for player in player_list
    ]


def acquisition_adp_metadata(
    history: HistoricalPositionCurves | None,
    history_weight: float | None,
) -> dict[str, Any]:
    variant_enabled = history_weight is not None
    available = bool(history and history.available)
    applied = bool(
        variant_enabled and available and float(history_weight or 0.0) > 0.0
    )
    if not variant_enabled:
        fallback = "legacy_raw_adp_with_optional_round_position_rates"
    elif not available:
        fallback = "history_unavailable_raw_adp"
    elif float(history_weight or 0.0) == 0.0:
        fallback = "zero_weight_raw_adp"
    else:
        fallback = None
    return {
        "variant_enabled": variant_enabled,
        "history_weight": history_weight,
        "history_available": available,
        "history_applied": applied,
        "history_source": history.source if history else None,
        "history_sources": list(history.sources) if history else [],
        "draft_count": (
            len(history.sources)
            if history and history.sources
            else int(bool(history and history.available))
        ),
        "draft_end_pick": history.draft_end_pick if history else None,
        "excluded_user_ids": list(history.excluded_user_ids) if history else [],
        "exclusion_audit": (
            [dict(row) for row in history.exclusion_audit] if history else []
        ),
        "fallback_state": fallback,
        "issues": list(history.issues) if history else [],
    }


@dataclass(frozen=True, slots=True)
class RankVorpCurve:
    """Monotone translation from general overall ECR rank to typical VORP."""

    points: tuple[tuple[float, float], ...]
    observation_count: int
    block_count: int

    def value(self, rank: float) -> float:
        if not self.points:
            return 0.0
        if rank <= self.points[0][0]:
            return self.points[0][1]
        if rank >= self.points[-1][0]:
            return self.points[-1][1]
        for (left_rank, left_value), (right_rank, right_value) in zip(
            self.points, self.points[1:]
        ):
            if left_rank <= rank <= right_rank:
                distance = right_rank - left_rank
                if distance <= 1e-9:
                    return left_value
                fraction = (rank - left_rank) / distance
                return left_value + fraction * (right_value - left_value)
        return self.points[-1][1]


def fit_rank_vorp_curve(
    players: Iterable[Player],
    replacement_baselines: Mapping[str, float],
    maximum_rank: float | None = None,
) -> RankVorpCurve:
    """Fit a nonincreasing overall-rank curve from the supplied model values."""
    observations = sorted(
        (
            player.overall_rank_score,
            player.projected_points
            - float(replacement_baselines.get(player.position) or 0.0),
        )
        for player in players
        if player.position in SKILL_POSITIONS
        and player.projected_points > 0.0
        and 0.0 < player.overall_rank_score < 999.0
        and (maximum_rank is None or player.overall_rank_score <= maximum_rank)
    )
    blocks: list[dict[str, float]] = []
    for rank, vorp in observations:
        blocks.append(
            {
                "rank_sum": float(rank),
                "vorp_sum": float(vorp),
                "count": 1.0,
            }
        )
        # Pool adjacent violations for a curve that cannot rise as rank worsens.
        while len(blocks) >= 2:
            left = blocks[-2]
            right = blocks[-1]
            left_mean = left["vorp_sum"] / left["count"]
            right_mean = right["vorp_sum"] / right["count"]
            if left_mean >= right_mean:
                break
            blocks[-2:] = [
                {
                    "rank_sum": left["rank_sum"] + right["rank_sum"],
                    "vorp_sum": left["vorp_sum"] + right["vorp_sum"],
                    "count": left["count"] + right["count"],
                }
            ]
    points = tuple(
        (
            block["rank_sum"] / block["count"],
            block["vorp_sum"] / block["count"],
        )
        for block in blocks
    )
    return RankVorpCurve(
        points=points,
        observation_count=len(observations),
        block_count=len(blocks),
    )


def rank_adjusted_player(
    player: Player,
    curve: RankVorpCurve,
    rank_weight: float,
    replacement_baselines: Mapping[str, float],
) -> Player:
    """Blend raw VORP with the absolute VORP implied by selected-expert rank."""
    if not 0.0 <= rank_weight <= 1.0:
        raise ValueError("Rank weight must be between zero and one")
    if (
        rank_weight == 0.0
        or player.position not in SKILL_POSITIONS
        or player.projected_points <= 0.0
        or not 0.0 < player.overall_rank_score < 999.0
        or player.position not in replacement_baselines
    ):
        return player
    raw_vorp = player.projected_points - float(replacement_baselines[player.position])
    adjustment = rank_weight * (
        curve.value(player.overall_rank_score) - raw_vorp
    )
    return replace(
        player,
        projected_points=max(0.0, player.projected_points + adjustment),
        vbd=player.vbd + adjustment,
    )


def rank_adjusted_players(
    players: Iterable[Player],
    curve: RankVorpCurve,
    rank_weight: float,
    replacement_baselines: Mapping[str, float],
) -> list[Player]:
    """Apply the overall-rank blend without undoing selected positional order."""

    adjusted = [
        rank_adjusted_player(player, curve, rank_weight, replacement_baselines)
        for player in players
    ]
    return expert_ordered_projection_players(adjusted)


@dataclass(slots=True)
class SimulationResult:
    strategy: str
    scores: list[float] = field(default_factory=list)
    position_counts: Counter[str] = field(default_factory=Counter)
    first_picks: Counter[str] = field(default_factory=Counter)
    special_rank_totals: Counter[str] = field(default_factory=Counter)
    roster_records: list[dict[str, Any]] = field(default_factory=list)
    base_lineup_scores: list[float] = field(default_factory=list)
    bye_coverage_scores: list[float] = field(default_factory=list)
    bye_adjusted_scores: list[float] = field(default_factory=list)
    bench_vorp_scores: list[float] = field(default_factory=list)
    usable_bench_vorp_scores: list[float] = field(default_factory=list)
    total_roster_vorp_scores: list[float] = field(default_factory=list)
    draft_scores_by_bench_weight: dict[float, list[float]] = field(default_factory=dict)
    reconciled_draft_scores: dict[float, dict[float, list[float]]] = field(
        default_factory=dict
    )
    reconciled_lineup_scores: dict[float, list[float]] = field(default_factory=dict)
    reconciled_usable_bench_scores: dict[float, list[float]] = field(
        default_factory=dict
    )
    weekly_use_scores: dict[float, dict[str, list[float]]] = field(
        default_factory=dict
    )
    weekly_use_reserve_lifts: dict[float, dict[str, list[float]]] = field(
        default_factory=dict
    )
    first_qb_selections: list[dict[str, Any]] = field(default_factory=list)
    near_tie_scarcity_promotions: int = 0
    trace: dict[str, Any] | None = None

    def summary(self) -> dict[str, Any]:
        ordered = sorted(self.scores)
        if not ordered:
            return {"strategy": self.strategy, "trials": 0}

        def percentile(fraction: float) -> float:
            return ordered[round((len(ordered) - 1) * fraction)]

        summary = {
            "strategy": self.strategy,
            "trials": len(ordered),
            "mean_score": round(fmean(ordered), 3),
            "median_score": round(median(ordered), 3),
            "p10_score": round(percentile(0.10), 3),
            "p90_score": round(percentile(0.90), 3),
            "average_position_counts": {
                position: round(count / len(ordered), 2) for position, count in self.position_counts.items()
            },
            "most_common_first_picks": self.first_picks.most_common(5),
            "average_special_ranks": {
                position: round(total / len(ordered), 3)
                for position, total in self.special_rank_totals.items()
            },
        }
        scarcity_config = _near_tie_scarcity_config(self.strategy)
        if scarcity_config is not None:
            summary["near_tie_scarcity"] = {
                "config": scarcity_config,
                "promotions": self.near_tie_scarcity_promotions,
                "promotions_per_draft": round(
                    self.near_tie_scarcity_promotions / len(ordered), 4
                ),
            }
        if self.bye_adjusted_scores:
            summary["mean_base_lineup_score"] = round(
                fmean(self.base_lineup_scores), 3
            )
            summary["mean_bye_coverage_points"] = round(
                fmean(self.bye_coverage_scores), 3
            )
            summary["mean_bye_adjusted_lineup_score"] = round(
                fmean(self.bye_adjusted_scores), 3
            )
            summary["mean_bench_vorp"] = round(fmean(self.bench_vorp_scores), 3)
            summary["mean_usable_bench_vorp"] = round(
                fmean(self.usable_bench_vorp_scores), 3
            )
            summary["mean_total_roster_vorp"] = round(
                fmean(self.total_roster_vorp_scores), 3
            )
        if self.first_qb_selections:
            summary["first_qb_selection"] = {
                "mean_round": round(
                    fmean(float(row["round"]) for row in self.first_qb_selections),
                    3,
                ),
                "mean_raw_adp": round(
                    fmean(float(row["raw_adp"]) for row in self.first_qb_selections),
                    3,
                ),
                "mean_acquisition_adp": round(
                    fmean(
                        float(row["acquisition_adp"])
                        for row in self.first_qb_selections
                    ),
                    3,
                ),
                "round_counts": dict(
                    sorted(Counter(row["round"] for row in self.first_qb_selections).items())
                ),
                "player_counts": dict(
                    Counter(row["player_name"] for row in self.first_qb_selections).most_common()
                ),
            }
        ordered_records = sorted(self.roster_records, key=lambda record: float(record["score"]))
        if ordered_records:
            summary["representative_rosters"] = {
                "worst": ordered_records[0],
                "median": ordered_records[round((len(ordered_records) - 1) * 0.5)],
                "best": ordered_records[-1],
            }
        if self.trace is not None:
            summary["trace"] = self.trace
        return summary


def snake_slot(pick_no: int, teams: int) -> int:
    round_index, within_round = divmod(pick_no - 1, teams)
    return within_round + 1 if round_index % 2 == 0 else teams - within_round


def next_pick_for_slot(after_pick: int, slot: int, teams: int, rounds: int = 30) -> int | None:
    for pick_no in range(after_pick + 1, teams * rounds + 1):
        if snake_slot(pick_no, teams) == slot:
            return pick_no
    return None


def survival_probability(adp: float, current_pick: int, target_pick: int) -> float:
    """Conditional chance a currently available player lasts through target_pick."""
    if target_pick <= current_pick:
        return 1.0
    sigma = max(2.5, adp * 0.18)
    normal = NormalDist(mu=adp, sigma=sigma)
    survived_now = max(1e-9, 1.0 - normal.cdf(current_pick + 0.5))
    survived_target = max(0.0, 1.0 - normal.cdf(target_pick + 0.5))
    return max(0.0, min(1.0, survived_target / survived_now))


def _top3_dst_guard_candidates(
    available: Iterable[Player],
    roster: Iterable[Player],
    *,
    pick_no: int,
    round_no: int,
    teams: int,
    draft_slot: int,
    simulation_rounds: int,
    roster_positions: Iterable[str],
    minimum_round: int = 9,
    maximum_next_turn_survival: float = 0.50,
    maximum_user_dst_rank: int = 3,
) -> list[Player]:
    roster_list = list(roster)
    positions = tuple(roster_positions)
    if round_no < minimum_round:
        return []
    if _filled_starter_slots(roster_list, positions) != len(
        _starter_eligibility(positions)
    ):
        return []
    next_user_pick = next_pick_for_slot(
        pick_no,
        draft_slot,
        teams,
        simulation_rounds,
    )
    if next_user_pick is None:
        return []
    return [
        player
        for player in available
        if player.position == "DST"
        and _can_draft(player, roster_list)
        and defense_draft_rank(player.team) is not None
        and defense_draft_rank(player.team) <= maximum_user_dst_rank
        and survival_probability(
            player.acquisition_pick,
            pick_no,
            next_user_pick,
        )
        <= maximum_next_turn_survival
    ]


def _strategy_modifier(strategy: str, position: str, round_no: int, roster: list[Player]) -> float:
    counts = Counter(player.position for player in roster)
    modifier = 0.0
    if strategy == "zero_rb":
        if position == "RB" and round_no <= 5:
            modifier -= 65.0
        if position == "WR" and round_no <= 5:
            modifier += 22.0
    elif strategy == "hero_rb":
        if position == "RB" and round_no <= 2 and counts["RB"] == 0:
            modifier += 42.0
        if position == "RB" and 2 <= round_no <= 6 and counts["RB"] >= 1:
            modifier -= 28.0
        if position == "WR" and 2 <= round_no <= 6:
            modifier += 16.0
    elif strategy == "robust_rb":
        if position == "RB" and round_no <= 4 and counts["RB"] < 3:
            modifier += 30.0
    elif strategy == "wr_heavy":
        if position == "WR" and round_no <= 6 and counts["WR"] < 4:
            modifier += 28.0
    elif strategy == "early_qb":
        if position == "QB" and round_no <= 4 and counts["QB"] == 0:
            modifier += 35.0
    elif strategy == "late_qb":
        if position == "QB" and round_no <= 7:
            modifier -= 70.0
    elif strategy == "early_te":
        if position == "TE" and round_no <= 4 and counts["TE"] == 0:
            modifier += 32.0
    return modifier


def _experimental_profile(policy: str, draft_slot: int | None = None) -> dict[str, Any] | None:
    """Decode independently testable first-round, starter, and late-round features."""
    turn_aware = policy.endswith("_turn_aware")
    horizon_guard = policy.endswith("_horizon_guard")
    if turn_aware:
        policy = policy.removesuffix("_turn_aware")
    elif horizon_guard:
        policy = policy.removesuffix("_horizon_guard")
    specialist_gate_mode = None
    if policy.endswith("_top3_dst_guard"):
        policy = policy.removesuffix("_top3_dst_guard")
        specialist_gate_mode = "top3_dst_guard"
    elif policy.endswith("_live_specialist_gate"):
        policy = policy.removesuffix("_live_specialist_gate")
        specialist_gate_mode = "live_specialist_gate"
    if specialist_gate_mode is not None:
        profile = _experimental_profile(policy, draft_slot)
        return {
            **(profile or {}),
            "offline_specialist_gate": {
                "mode": specialist_gate_mode,
                "minimum_round": 9,
                "maximum_next_turn_survival": 0.50,
                "maximum_user_dst_rank": 3,
                "requires_skill_starters_complete": True,
            },
        }
    reconciled_upside_match = re.fullmatch(
        r"half_ppr_reconciled_(?:tol05_)?w(10|20|30|40|50|60)_upside(25|50|100)",
        policy,
    )
    if reconciled_upside_match:
        return _experimental_profile(
            f"half_ppr_team_w{reconciled_upside_match.group(1)}_u"
            f"{reconciled_upside_match.group(2)}",
            draft_slot,
        )
    reconciled_reserve_cap_match = re.fullmatch(
        r"half_ppr_reconciled_w(10|20|30|40|50|60)_reserve_cap", policy
    )
    if reconciled_reserve_cap_match:
        return _experimental_profile(
            f"half_ppr_team_w{reconciled_reserve_cap_match.group(1)}_reserve_cap",
            draft_slot,
        )
    reserve_cap_match = re.fullmatch(
        r"half_ppr_team_w(10|20|30|40|50|60)_reserve_cap", policy
    )
    if reserve_cap_match:
        profile = _experimental_profile(
            f"half_ppr_team_w{reserve_cap_match.group(1)}", draft_slot
        )
        assert profile is not None
        return {**profile, "reserve_redundancy_cap": True}
    specialist_plans = {
        "half_ppr_reconciled_special_k14_dst15": {
            14: "K",
            15: "DST",
        },
        "half_ppr_reconciled_special_dst14_k15": {
            14: "DST",
            15: "K",
        },
        "half_ppr_reconciled_special_k13_dst14_flier15": {
            13: "K",
            14: "DST",
            15: "sleeper",
        },
        "half_ppr_reconciled_special_dst13_k14_flier15": {
            13: "DST",
            14: "K",
            15: "sleeper",
        },
    }
    if policy in specialist_plans:
        profile = _experimental_profile("half_ppr_team_w30", draft_slot)
        assert profile is not None
        return {**profile, "specialist_plan": specialist_plans[policy]}
    if policy == "half_ppr_reconciled_tol05_w20_endgame":
        profile = _experimental_profile("half_ppr_team_w20", draft_slot)
        assert profile is not None
        return {**profile, "late_round_plan": True}
    consensus_match = re.fullmatch(
        r"(?:standard|half_ppr)_consensus_(?:anchored|band(?:4|6|8|12))",
        policy,
    )
    if consensus_match:
        policy = "half_ppr_team_w30"
    weighted_live_match = re.fullmatch(
        r"half_ppr_reconciled_tol05_w(10|20|30|40|50|60)", policy
    )
    if weighted_live_match:
        policy = f"half_ppr_team_w{weighted_live_match.group(1)}"
    policy = {
        "half_ppr_total_team": "half_ppr_team_w30",
        "half_ppr_total_team_safe": "half_ppr_team_w10",
        "standard_total_team": "half_ppr_team_w30",
        "standard_total_team_safe": "half_ppr_team_w10",
    }.get(policy, policy)
    total_team_upside_match = re.fullmatch(
        r"half_ppr_team_w(10|20|30|40|50|60)_u(25|50|100)", policy
    )
    total_team_match = re.fullmatch(r"half_ppr_team_w(10|20|30|40|50|60)", policy)
    total_team_bench_weight = (
        int(total_team_upside_match.group(1)) / 100.0
        if total_team_upside_match
        else int(total_team_match.group(1)) / 100.0
        if total_team_match
        else None
    )
    starter_deferral = policy in {
        "half_ppr_next_pick",
        "half_ppr_next_pick_safe",
    } or total_team_match is not None or total_team_upside_match is not None
    if total_team_upside_match:
        policy = f"v4_bn_p5_u{total_team_upside_match.group(2)}"
    elif total_team_match:
        policy = "v4_bn_p5_u0"
    elif policy == "half_ppr_next_pick":
        policy = "v4_bn_p5_u0"
    elif policy == "half_ppr_next_pick_safe":
        policy = "v4_bn_p100_u0"
    elif policy == "half_ppr_calibrated":
        policy = "v4_b0_p5_u0"
    elif policy == "half_ppr_safe":
        policy = "v4_b0_p100_u0"
    elif policy == "half_ppr_replacement_calibrated":
        policy = "v4_b0_p5_u0"
    elif policy == "half_ppr_replacement_safe":
        policy = "v4_b0_p100_u0"
    policy = {
        "scenario_calibrated": "v3_bs40_p200_u0",
        "scenario_safe": "v3_b1_p0_u0",
    }.get(policy, policy)
    fixed_scenario_match = re.fullmatch(
        r"v3x_w(\d+)_b(0|1|2|s\d+)_p(\d+)_u(\d+)", policy
    )
    scenario_match = re.fullmatch(r"v3_b(0|1|2|s\d+)_p(\d+)_u(\d+)", policy)
    replacement_scenario_match = re.fullmatch(
        r"v4_b(0|1|2|n|s\d+)_p(\d+)_u(\d+)", policy
    )
    if fixed_scenario_match or scenario_match or replacement_scenario_match:
        match = fixed_scenario_match or scenario_match or replacement_scenario_match
        assert match is not None
        offset = 1 if fixed_scenario_match else 0
        bench_rule = match.group(1 + offset)
        slot = draft_slot or 6
        slot_vona_weight = (
            int(match.group(1)) / 100.0
            if fixed_scenario_match
            else 5.0 if slot <= 4 else 7.5 if slot <= 8 else 3.0
        )
        return {
            "first_round_vols": True,
            "bench_before_starters": int(bench_rule) if bench_rule.isdigit() else None,
            "soft_bench_penalty": (
                int(bench_rule[1:]) if bench_rule.startswith("s") else 0
            ),
            "late_round_plan": False,
            "vona_weight": slot_vona_weight,
            "vona_only": False,
            "final_sleeper": False,
            "scenario_bench": True,
            "replacement_aware": bool(replacement_scenario_match),
            "starter_deferral": starter_deferral or bench_rule == "n",
            "total_team_bench_weight": total_team_bench_weight,
            "post_starter_vona_weight": int(match.group(2 + offset)) / 100.0,
            "upside_weight": int(match.group(3 + offset)) / 100.0,
            "turn_aware": turn_aware,
            "turn_aware_shadow": horizon_guard,
        }
    calibrated_weights = {"calibrated": 7.5, "calibrated_safe": 3.0}
    if policy in calibrated_weights:
        return {
            "first_round_vols": True,
            "bench_before_starters": 1,
            "late_round_plan": False,
            "vona_weight": calibrated_weights[policy],
            "vona_only": False,
            "final_sleeper": False,
        }
    if policy == "fs_vona":
        return {
            "first_round_vols": True,
            "bench_before_starters": 1,
            "late_round_plan": False,
            "vona_weight": None,
            "vona_only": True,
            "final_sleeper": False,
        }
    match = re.fullmatch(r"(none|[fslu]+)_w(\d+)", policy)
    if match:
        flags = set() if match.group(1) == "none" else set(match.group(1))
        return {
            "first_round_vols": "f" in flags,
            "bench_before_starters": 1 if "s" in flags else None,
            "late_round_plan": "l" in flags,
            "vona_weight": int(match.group(2)) / 100.0,
            "vona_only": False,
            "final_sleeper": "u" in flags,
        }
    hybrid_match = re.fullmatch(r"hybrid_(\d+)", policy)
    if hybrid_match:
        return {
            "first_round_vols": True,
            "bench_before_starters": 1,
            "late_round_plan": True,
            "vona_weight": int(hybrid_match.group(1)) / 100.0,
            "vona_only": False,
            "final_sleeper": True,
        }
    if policy == "constructed_vorp":
        return {
            "first_round_vols": False,
            "bench_before_starters": 1,
            "late_round_plan": True,
            "vona_weight": 0.0,
            "vona_only": False,
            "final_sleeper": True,
        }
    return None


def _consensus_candidate_band(policy: str, round_no: int) -> int | None:
    """Keep the model inside an expert-defined best-available neighborhood."""
    if policy in {"standard_consensus_anchored", "half_ppr_consensus_anchored"}:
        return 1 if round_no == 1 else 12
    match = re.fullmatch(
        r"(?:standard|half_ppr)_consensus_band(4|6|8|12)", policy
    )
    if match:
        return 1 if round_no == 1 else int(match.group(1))
    return None


def _near_tie_scarcity_config(policy: str) -> dict[str, float] | None:
    """Return the opt-in top-two sequence reorder thresholds."""

    match = re.fullmatch(
        r"half_ppr_reconciled_tol05_scarcity(05|10|20)_surv(10|15|20)",
        policy,
    )
    if not match:
        return None
    return {
        "maximum_score_gap": int(match.group(1)) / 10.0,
        "minimum_survival_gap": int(match.group(2)) / 100.0,
    }


def _reconciled_pick_policy(policy: str) -> tuple[str, float, bool] | None:
    configured = {
        "half_ppr_reconciled": ("half_ppr_total_team", 0.5, True),
        "half_ppr_reconciled_turn_aware": (
            "half_ppr_total_team_turn_aware",
            0.5,
            True,
        ),
        "half_ppr_reconciled_horizon_guard": (
            "half_ppr_total_team_horizon_guard",
            0.5,
            True,
        ),
        "half_ppr_reconciled_w10": ("half_ppr_team_w10", 0.5, True),
        "half_ppr_reconciled_w20": ("half_ppr_team_w20", 0.5, True),
        "half_ppr_reconciled_w30": ("half_ppr_team_w30", 0.5, True),
        "half_ppr_reconciled_full": ("half_ppr_total_team", 1.0, True),
        "half_ppr_expert_ordered_raw": ("half_ppr_total_team", 0.0, False),
        "half_ppr_expert_ordered_curve": ("half_ppr_total_team", 0.0, False),
        "standard_reconciled": ("standard_total_team", 0.5, True),
        "standard_reconciled_full": ("standard_total_team", 1.0, True),
        "standard_expert_ordered_raw": ("standard_total_team", 0.0, False),
        "standard_expert_ordered_curve": ("standard_total_team", 0.0, False),
        "half_ppr_reconciled_tol05": (
            "half_ppr_team_w20_reserve_cap",
            0.5,
            True,
        ),
        "half_ppr_reconciled_tol05_no_sequence": ("half_ppr_team_w20", 0.5, True),
        "half_ppr_reconciled_tol05_elite_te05": ("half_ppr_team_w20", 0.5, True),
        "half_ppr_reconciled_tol05_elite_te10": ("half_ppr_team_w20", 0.5, True),
        "half_ppr_reconciled_tol05_elite_te15": ("half_ppr_team_w20", 0.5, True),
        "half_ppr_reconciled_tol05_reserve_cap": (
            "half_ppr_team_w20_reserve_cap",
            0.5,
            True,
        ),
        "half_ppr_reconciled_tol10": ("half_ppr_total_team", 0.5, True),
        "half_ppr_reconciled_tol20": ("half_ppr_total_team", 0.5, True),
        "half_ppr_reconciled_ballot50": ("half_ppr_total_team", 0.5, True),
        "half_ppr_reconciled_ballot60": ("half_ppr_total_team", 0.5, True),
        "half_ppr_reconciled_koerner_rb": ("half_ppr_total_team", 0.5, True),
        "half_ppr_reconciled_qb1": ("half_ppr_total_team", 0.5, True),
        "half_ppr_reconciled_te1": ("half_ppr_total_team", 0.5, True),
        "half_ppr_reconciled_onesie1": ("half_ppr_total_team", 0.5, True),
        "half_ppr_reconciled_locked10": ("half_ppr_total_team", 0.5, True),
        "half_ppr_reconciled_koerner_qb": ("half_ppr_total_team", 0.5, True),
        "half_ppr_reconciled_koerner_te": ("half_ppr_total_team", 0.5, True),
        "half_ppr_reconciled_koerner_onesie": ("half_ppr_total_team", 0.5, True),
        "half_ppr_reconciled_koerner_full": ("half_ppr_total_team", 0.5, True),
    }.get(policy)
    if configured is not None:
        return configured
    reserve_weight_match = re.fullmatch(
        r"half_ppr_reconciled_w(10|20|30|40|50|60)(_reserve_cap)?",
        policy,
    )
    if reserve_weight_match:
        suffix = "_reserve_cap" if reserve_weight_match.group(2) else ""
        return (
            f"half_ppr_team_w{reserve_weight_match.group(1)}{suffix}",
            0.5,
            True,
        )
    if policy in {
        "half_ppr_reconciled_rb3_by6",
        "half_ppr_reconciled_wr3_by6",
        "half_ppr_reconciled_rb4_by8",
        "half_ppr_reconciled_wr4_by8",
        "half_ppr_reconciled_special_k14_dst15",
        "half_ppr_reconciled_special_dst14_k15",
        "half_ppr_reconciled_special_k13_dst14_flier15",
        "half_ppr_reconciled_special_dst13_k14_flier15",
    }:
        return "half_ppr_total_team", 0.5, True
    if re.fullmatch(r"half_ppr_reconciled_wr4_by8_gap(?:05|10|20)", policy):
        return "half_ppr_total_team", 0.5, True
    if re.fullmatch(r"half_ppr_reconciled_wr1_by3_gap(?:5|10|15)", policy):
        return "half_ppr_total_team", 0.5, True
    if _near_tie_scarcity_config(policy) is not None:
        return "half_ppr_team_w20_reserve_cap", 0.5, True
    weighted_live_match = re.fullmatch(
        r"half_ppr_reconciled_tol05_w(10|20|30|40|50|60)", policy
    )
    if weighted_live_match:
        return f"half_ppr_team_w{weighted_live_match.group(1)}", 0.5, True
    if re.fullmatch(
        r"half_ppr_reconciled_tol05_w20_qb_floor(?:05|10|15)", policy
    ):
        return "half_ppr_team_w20", 0.5, True
    upside_match = re.fullmatch(
        r"half_ppr_reconciled_(?:tol05_)?w(10|20|30|40|50|60)_upside(25|50|100)",
        policy,
    )
    if upside_match:
        return (
            f"half_ppr_team_w{upside_match.group(1)}_u{upside_match.group(2)}",
            0.5,
            True,
        )
    if policy == "half_ppr_reconciled_tol05_w20_endgame":
        return "half_ppr_team_w20", 0.5, True
    if re.fullmatch(
        r"half_ppr_reconciled_(?:qb|te)_r(?:[4-9]|1[0-2])", policy
    ):
        return "half_ppr_total_team", 0.5, True
    return None


def _forced_first_qb_round(policy: str) -> int | None:
    match = re.fullmatch(r"half_ppr_reconciled_qb_r([4-9]|1[0-2])", policy)
    return int(match.group(1)) if match else None


def _forced_first_te_round(policy: str) -> int | None:
    match = re.fullmatch(r"half_ppr_reconciled_te_r([4-9]|1[0-2])", policy)
    return int(match.group(1)) if match else None


def _construction_policy_config(policy: str) -> dict[str, Any]:
    """Return opt-in shadow construction constraints, never player values."""

    return {
        "half_ppr_reconciled_koerner_rb": {
            "avoid_rb_13_30_after_anchor_through_round": 8,
        },
        "half_ppr_reconciled_qb1": {"maximum_qb": 1},
        "half_ppr_reconciled_te1": {"maximum_te": 1},
        "half_ppr_reconciled_onesie1": {
            "maximum_qb": 1,
            "maximum_te": 1,
        },
        "half_ppr_reconciled_locked10": {
            "maximum_qb": 1,
            "maximum_te": 1,
        },
        "half_ppr_reconciled_koerner_qb": {
            "punt_qb_through_round": 8,
            "maximum_qb": 1,
        },
        "half_ppr_reconciled_koerner_te": {
            "punt_non_elite_te_through_round": 8,
            "maximum_te": 1,
        },
        "half_ppr_reconciled_koerner_onesie": {
            "punt_qb_through_round": 8,
            "punt_non_elite_te_through_round": 8,
            "maximum_qb": 1,
            "maximum_te": 1,
        },
        "half_ppr_reconciled_koerner_full": {
            "avoid_rb_13_30_after_anchor_through_round": 8,
            "punt_qb_through_round": 8,
            "punt_non_elite_te_through_round": 8,
            "maximum_qb": 1,
            "maximum_te": 1,
        },
        "half_ppr_reconciled_rb3_by6": {
            "minimum_position_by_round": ("RB", 3, 6),
        },
        "half_ppr_reconciled_wr3_by6": {
            "minimum_position_by_round": ("WR", 3, 6),
        },
        "half_ppr_reconciled_rb4_by8": {
            "minimum_position_by_round": ("RB", 4, 8),
        },
        "half_ppr_reconciled_wr4_by8": {
            "minimum_position_by_round": ("WR", 4, 8),
        },
        "half_ppr_reconciled_wr4_by8_gap05": {
            "minimum_position_if_close_by_round": ("WR", 4, 8, 0.5),
        },
        "half_ppr_reconciled_wr4_by8_gap10": {
            "minimum_position_if_close_by_round": ("WR", 4, 8, 1.0),
        },
        "half_ppr_reconciled_wr4_by8_gap20": {
            "minimum_position_if_close_by_round": ("WR", 4, 8, 2.0),
        },
        "half_ppr_reconciled_wr1_by3_gap5": {
            "minimum_position_if_close_by_round": ("WR", 1, 3, 5.0),
        },
        "half_ppr_reconciled_wr1_by3_gap10": {
            "minimum_position_if_close_by_round": ("WR", 1, 3, 10.0),
        },
        "half_ppr_reconciled_wr1_by3_gap15": {
            "minimum_position_if_close_by_round": ("WR", 1, 3, 15.0),
        },
    }.get(policy, {})


def _construction_filtered_available(
    available: list[Player],
    roster: list[Player],
    round_no: int,
    config: Mapping[str, Any],
) -> list[Player]:
    """Apply a shadow roster-construction screen without changing any scores."""

    if not config:
        return available
    counts = Counter(player.position for player in roster)
    minimum_position = config.get("minimum_position_by_round")
    forced_position = None
    if minimum_position:
        position, minimum_count, deadline_round = minimum_position
        deficit = max(0, int(minimum_count) - counts[str(position)])
        remaining_picks = max(0, int(deadline_round) - round_no + 1)
        if deficit > 0 and deficit >= remaining_picks:
            forced_position = str(position)
    anchored_rb = any(
        player.position == "RB" and player.rank_score <= 12.0
        for player in roster
    )
    filtered = []
    for player in available:
        if forced_position is not None and player.position != forced_position:
            continue
        if (
            player.position == "RB"
            and anchored_rb
            and round_no
            <= int(config.get("avoid_rb_13_30_after_anchor_through_round") or 0)
            and 12.0 < player.rank_score <= 30.0
        ):
            continue
        if (
            player.position == "QB"
            and round_no <= int(config.get("punt_qb_through_round") or 0)
        ):
            continue
        if (
            player.position == "TE"
            and round_no
            <= int(config.get("punt_non_elite_te_through_round") or 0)
            and player.rank_score > 2.0
        ):
            continue
        position_maximum = config.get(f"maximum_{player.position.lower()}")
        if position_maximum is not None and counts[player.position] >= int(position_maximum):
            continue
        filtered.append(player)
    return filtered or available


def _promote_close_construction_candidate(
    ranked: list[dict[str, Any]],
    roster: Iterable[Player],
    round_no: int,
    config: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Promote a construction target at its deadline only when value is close."""

    close_minimum = config.get("minimum_position_if_close_by_round")
    if not close_minimum or not ranked:
        return ranked
    position, minimum_count, deadline_round, maximum_score_gap = close_minimum
    counts = Counter(player.position for player in roster)
    deficit = max(0, int(minimum_count) - counts[str(position)])
    remaining_picks = max(0, int(deadline_round) - round_no + 1)
    if deficit <= 0 or deficit < remaining_picks:
        return ranked
    candidate = next(
        (row for row in ranked if row["_player"].position == str(position)),
        None,
    )
    if candidate is None or candidate is ranked[0]:
        return ranked
    score_gap = float(ranked[0]["final_score"]) - float(candidate["final_score"])
    if score_gap > float(maximum_score_gap):
        return ranked
    candidate["construction_close_promoted"] = True
    candidate["construction_close_score_gap"] = round(score_gap, 3)
    candidate["construction_close_maximum_gap"] = float(maximum_score_gap)
    return [candidate, *(row for row in ranked if row is not candidate)]


def _position_guardrail_config(policy: str) -> dict[str, Any]:
    if _near_tie_scarcity_config(policy) is not None:
        return {
            "method": "position_rank_tolerance",
            "tolerance": 0.5,
        }
    if re.fullmatch(
        r"half_ppr_reconciled_tol05_w(?:10|20|30|40|50|60)"
        r"(?:_qb_floor(?:05|10|15)|_upside(?:25|50|100)|_endgame)?",
        policy,
    ):
        return {
            "method": "position_rank_tolerance",
            "tolerance": 0.5,
        }
    return {
        "half_ppr_reconciled_tol05": {
            "method": "position_rank_tolerance",
            "tolerance": 0.5,
        },
        "half_ppr_reconciled_tol05_no_sequence": {
            "method": "position_rank_tolerance",
            "tolerance": 0.5,
        },
        "half_ppr_reconciled_tol05_elite_te05": {
            "method": "position_rank_tolerance",
            "tolerance": 0.5,
        },
        "half_ppr_reconciled_tol05_elite_te10": {
            "method": "position_rank_tolerance",
            "tolerance": 0.5,
        },
        "half_ppr_reconciled_tol05_elite_te15": {
            "method": "position_rank_tolerance",
            "tolerance": 0.5,
        },
        "half_ppr_reconciled_tol05_reserve_cap": {
            "method": "position_rank_tolerance",
            "tolerance": 0.5,
        },
        "half_ppr_reconciled_tol10": {
            "method": "position_rank_tolerance",
            "tolerance": 1.0,
        },
        "half_ppr_reconciled_tol20": {
            "method": "position_rank_tolerance",
            "tolerance": 2.0,
        },
        "half_ppr_reconciled_ballot50": {
            "method": "direct_weighted_ballot",
            "threshold": 0.5,
        },
        "half_ppr_reconciled_ballot60": {
            "method": "direct_weighted_ballot",
            "threshold": 0.6,
        },
        "half_ppr_reconciled_locked10": {
            "method": "position_rank_tolerance",
            "tolerance": 0.5,
        },
    }.get(policy, {"method": "strict_position_rank", "tolerance": 0.0})


def _elite_te_sequence_score_gap(policy: str) -> float | None:
    if _near_tie_scarcity_config(policy) is not None or policy in {
        "half_ppr_reconciled_tol05",
        "half_ppr_reconciled_tol05_reserve_cap",
    } or re.fullmatch(
        r"half_ppr_reconciled_tol05_w(?:10|20|30|40|50|60)"
        r"(?:_qb_floor(?:05|10|15)|_upside(?:25|50|100)|_endgame)?",
        policy,
    ):
        return 15.0
    match = re.fullmatch(r"half_ppr_reconciled_tol05_elite_te(05|10|15)", policy)
    return float(int(match.group(1))) if match else None


def _qb_streaming_floor_threshold(policy: str) -> float | None:
    """Return the allowed next-pick QB drop for a dynamic wait challenger."""

    match = re.fullmatch(
        r"half_ppr_reconciled_tol05_w20_qb_floor(05|10|15)", policy
    )
    return float(int(match.group(1))) if match else None


def _promote_elite_te_sequence_candidate(
    ranked: list[dict[str, Any]],
    roster: Iterable[Player],
    round_no: int,
    maximum_score_gap: float | None,
    *,
    teams: int,
    draft_slot: int,
    roster_positions: Iterable[str],
) -> list[dict[str, Any]]:
    """Apply the bounded option-value rule for a close top-two TE in rounds 2-4."""

    positions = tuple(roster_positions)
    calibrated_context = (
        teams == 10
        and draft_slot == 4
        and positions.count("QB") == 1
        and positions.count("RB") == 2
        and positions.count("WR") == 2
        and positions.count("TE") == 1
        and positions.count("WRRB_FLEX") == 1
        and positions.count("FLEX") == 0
        and positions.count("REC_FLEX") == 0
        and positions.count("SUPER_FLEX") == 0
    )
    if (
        maximum_score_gap is None
        or not calibrated_context
        or not 2 <= round_no <= 4
        or any(player.position == "TE" for player in roster)
        or not ranked
    ):
        return ranked
    elite_te = next(
        (
            row
            for row in ranked
            if row["_player"].position == "TE"
            and row["_player"].rank_score <= 2.0
        ),
        None,
    )
    if elite_te is None or elite_te is ranked[0]:
        return ranked
    score_gap = float(ranked[0]["final_score"]) - float(elite_te["final_score"])
    if score_gap > maximum_score_gap:
        return ranked
    elite_te["sequence_option_promoted"] = True
    elite_te["sequence_option_score_gap"] = round(score_gap, 3)
    elite_te["sequence_option_max_gap"] = maximum_score_gap
    return [elite_te, *(row for row in ranked if row is not elite_te)]


def _promote_near_tie_scarcity_candidate(
    ranked: list[dict[str, Any]],
    maximum_score_gap: float | None,
    minimum_survival_gap: float | None,
    *,
    teams: int,
    draft_slot: int,
    roster_positions: Iterable[str],
) -> list[dict[str, Any]]:
    """Prefer the scarcer half of a reciprocal, near-tied top-two sequence."""

    positions = tuple(roster_positions)
    calibrated_context = (
        teams == 10
        and draft_slot == 4
        and positions.count("QB") == 1
        and positions.count("RB") == 2
        and positions.count("WR") == 2
        and positions.count("TE") == 1
        and positions.count("WRRB_FLEX") == 1
        and positions.count("FLEX") == 0
        and positions.count("REC_FLEX") == 0
        and positions.count("SUPER_FLEX") == 0
    )
    if (
        maximum_score_gap is None
        or minimum_survival_gap is None
        or not calibrated_context
        or len(ranked) < 2
    ):
        return ranked
    leader, challenger = ranked[:2]
    if (
        leader.get("two_pick_path_value") is None
        or challenger.get("two_pick_path_value") is None
        or leader.get("roster_need") == "bench_depth"
        or challenger.get("roster_need") == "bench_depth"
        or leader.get("expected_next_path_player") != challenger.get("player_name")
        or challenger.get("expected_next_path_player") != leader.get("player_name")
    ):
        return ranked
    score_gap = float(leader["final_score"]) - float(challenger["final_score"])
    survival_gap = float(leader["next_pick_survival"]) - float(
        challenger["next_pick_survival"]
    )
    if score_gap > maximum_score_gap or survival_gap < minimum_survival_gap:
        return ranked
    challenger["near_tie_scarcity_promoted"] = True
    challenger["near_tie_scarcity_score_gap"] = round(score_gap, 3)
    challenger["near_tie_scarcity_survival_gap"] = round(survival_gap, 6)
    challenger["near_tie_scarcity_maximum_score_gap"] = maximum_score_gap
    challenger["near_tie_scarcity_minimum_survival_gap"] = minimum_survival_gap
    leader["near_tie_scarcity_displaced"] = True
    return [challenger, leader, *ranked[2:]]


def _promote_turn_aware_qb_deferral(
    ranked: list[dict[str, Any]],
    roster: list[Player],
    *,
    teams: int,
    draft_slot: int,
    roster_positions: Iterable[str],
    maximum_score_gap: float = 1.0,
    minimum_qb_survival: float = 0.65,
) -> list[dict[str, Any]]:
    """Defer a replaceable QB when a near-tied turn package preserves access.

    This is deliberately scoped to League Beta's calibrated slot and roster. It is
    not a forced late-QB rule: the ordinary leader remains in place unless a
    non-QB package is within one point, takes no QB on the adjacent turn, and
    explicitly expects the same QB at the next opponent-contested pick.
    """

    positions = tuple(roster_positions)
    calibrated_context = (
        teams == 12
        and draft_slot == 1
        and positions.count("QB") == 1
        and positions.count("RB") == 2
        and positions.count("WR") == 2
        and positions.count("TE") == 1
        and positions.count("FLEX") == 2
        and positions.count("SUPER_FLEX") == 0
    )
    if (
        not calibrated_context
        or any(player.position == "QB" for player in roster)
        or len(ranked) < 2
        or ranked[0]["_player"].position != "QB"
        or ranked[0].get("continuation_pick") is None
    ):
        return ranked
    leader = ranked[0]
    leader_survival = float(leader.get("contested_pick_survival") or 0.0)
    if leader_survival < minimum_qb_survival:
        return ranked
    challenger = next(
        (
            row
            for row in ranked[1:]
            if row["_player"].position != "QB"
            and row.get("turn_aware_next_path_player")
            and row.get("turn_aware_next_path_player") != leader["player_name"]
            and row.get("turn_aware_continuation_path_player")
            == leader["player_name"]
            and float(leader.get("turn_aware_path_value") or leader["final_score"])
            - float(row.get("turn_aware_path_value") or row["final_score"])
            <= maximum_score_gap
        ),
        None,
    )
    if challenger is None:
        return ranked
    score_gap = float(
        leader.get("turn_aware_path_value") or leader["final_score"]
    ) - float(challenger.get("turn_aware_path_value") or challenger["final_score"])
    challenger["turn_aware_qb_deferred"] = True
    challenger["turn_aware_qb_name"] = leader["player_name"]
    challenger["turn_aware_qb_survival"] = round(leader_survival, 6)
    challenger["turn_aware_qb_score_gap"] = round(score_gap, 3)
    challenger["turn_aware_qb_maximum_score_gap"] = maximum_score_gap
    challenger["turn_aware_qb_minimum_survival"] = minimum_qb_survival
    leader["turn_aware_qb_displaced"] = True
    return [challenger, *(row for row in ranked if row is not challenger)]


def _expert_order_constrained_candidates(
    ranked: Iterable[dict[str, Any]],
    *,
    position_rank_tolerance: float = 0.0,
    ballot_preferences: Mapping[tuple[str, str], float] | None = None,
    ballot_threshold: float = 0.5,
) -> list[dict[str, Any]]:
    """Apply a same-position guardrail while preserving cross-position scoring."""
    by_position: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in ranked:
        by_position[row["_player"].position].append(row)
    if ballot_preferences is None and position_rank_tolerance <= 0.0:
        for rows in by_position.values():
            rows.sort(
                key=lambda row: (
                    row["_player"].rank_score,
                    row["_player"].overall_rank_score,
                    row["_player"].adp,
                )
            )
        ordered = []
        while by_position:
            frontiers = [rows[0] for rows in by_position.values() if rows]
            choice = min(
                frontiers,
                key=lambda row: (
                    -float(row["final_score"]),
                    row["_player"].overall_rank_score,
                    row["_player"].adp,
                ),
            )
            ordered.append(choice)
            position = choice["_player"].position
            by_position[position].pop(0)
            if not by_position[position]:
                del by_position[position]
        return ordered
    ordered: list[dict[str, Any]] = []
    while by_position:
        frontiers = []
        for rows in by_position.values():
            eligible = []
            for candidate in rows:
                player = candidate["_player"]
                blocked = False
                for other in rows:
                    if other is candidate:
                        continue
                    other_player = other["_player"]
                    if ballot_preferences is not None:
                        preference = ballot_preferences.get(
                            (other_player.key, player.key)
                        )
                        blocked = bool(
                            preference is not None
                            and float(preference) > ballot_threshold
                        )
                    else:
                        blocked = (
                            other_player.rank_score + position_rank_tolerance
                            < player.rank_score
                        )
                    if blocked:
                        break
                if not blocked:
                    eligible.append(candidate)
            # A weighted-majority cycle can block every player. Preserve model
            # score as the deterministic fallback instead of inventing an order.
            frontiers.extend(eligible or rows)
        choice = min(
            frontiers,
            key=lambda row: (
                -float(row["final_score"]),
                row["_player"].overall_rank_score,
                row["_player"].adp,
            ),
        )
        ordered.append(choice)
        position = choice["_player"].position
        by_position[position].remove(choice)
        if not by_position[position]:
            del by_position[position]
    return ordered


def _can_draft(player: Player, roster: list[Player]) -> bool:
    return Counter(item.position for item in roster)[player.position] < POSITION_CAPS.get(player.position, 99)


def market_replacement_baselines(
    players: Iterable[Player], teams: int, skill_rounds: int
) -> dict[str, float]:
    """Estimate the best post-draft waiver option after the market-drafted pool."""
    ordered = sorted(players, key=lambda player: (player.adp, player.rank_score))
    cutoff = teams * skill_rounds
    drafted = ordered[:cutoff]
    undrafted = ordered[cutoff:]
    by_position: dict[str, list[Player]] = defaultdict(list)
    for player in undrafted:
        by_position[player.position].append(player)
    baselines = {
        position: max(values, key=lambda player: player.projected_points).projected_points
        for position, values in by_position.items()
        if values
    }
    # A shallow synthetic board may leave no undrafted player at a position.
    drafted_by_position: dict[str, list[Player]] = defaultdict(list)
    for player in drafted:
        drafted_by_position[player.position].append(player)
    for position, values in drafted_by_position.items():
        baselines.setdefault(
            position,
            min(values, key=lambda player: player.projected_points).projected_points,
        )
    return baselines


@lru_cache(maxsize=64)
def _starter_eligibility_cached(
    roster_positions: tuple[str, ...],
) -> tuple[tuple[str, ...], ...]:
    flex = {
        "FLEX": ("RB", "WR", "TE"),
        "WRRB_FLEX": ("RB", "WR"),
        "REC_FLEX": ("WR", "TE"),
        "SUPER_FLEX": ("QB", "RB", "WR", "TE"),
    }
    slots: list[tuple[str, ...]] = []
    for roster_position in roster_positions:
        if roster_position in SKILL_POSITIONS:
            slots.append((roster_position,))
        elif roster_position in flex:
            slots.append(flex[roster_position])
    return tuple(slots)


def _starter_eligibility(roster_positions: Iterable[str]) -> list[tuple[str, ...]]:
    return list(_starter_eligibility_cached(tuple(roster_positions)))


@lru_cache(maxsize=512)
def _filled_starter_position_count(
    roster_position_counts: tuple[tuple[str, int], ...],
    roster_positions: tuple[str, ...],
) -> int:
    slots = _starter_eligibility_cached(roster_positions)
    player_positions = [
        position
        for position, count in roster_position_counts
        for _ in range(count)
    ]
    matches: dict[int, int] = {}

    def place(player_index: int, seen: set[int]) -> bool:
        position = player_positions[player_index]
        for slot_index, eligible in enumerate(slots):
            if slot_index in seen or position not in eligible:
                continue
            seen.add(slot_index)
            previous = matches.get(slot_index)
            if previous is None or place(previous, seen):
                matches[slot_index] = player_index
                return True
        return False

    for index in range(len(player_positions)):
        place(index, set())
    return len(matches)


def _filled_starter_slots(roster: Iterable[Player], roster_positions: Iterable[str]) -> int:
    counts = Counter(
        player.position for player in roster if player.position in SKILL_POSITIONS
    )
    return _filled_starter_position_count(
        tuple(sorted(counts.items())), tuple(roster_positions)
    )


def _preserves_starter_path(
    player: Player,
    roster: list[Player],
    roster_positions: Iterable[str],
    total_user_picks: int,
) -> bool:
    after = [*roster, player]
    skill_players_after = sum(item.position in SKILL_POSITIONS for item in after)
    remaining_picks = total_user_picks - skill_players_after
    starter_slots = len(_starter_eligibility(roster_positions))
    missing_starters = starter_slots - _filled_starter_slots(after, roster_positions)
    return missing_starters <= remaining_picks


def _bench_players_before_starters(
    roster: Iterable[Player], roster_positions: Iterable[str]
) -> int:
    skill_roster = [player for player in roster if player.position in SKILL_POSITIONS]
    return len(skill_roster) - _filled_starter_slots(skill_roster, roster_positions)


def _optimal_lineup(
    roster: Iterable[Player], roster_positions: Iterable[str]
) -> tuple[float, list[Player]]:
    """Return the maximum legal skill-position lineup and its selected players."""
    slots = _starter_eligibility(roster_positions)
    eligible_capacity = {
        position: sum(position in eligible for eligible in slots)
        for position in SKILL_POSITIONS
    }
    roster_list = list(roster)
    by_position: dict[str, list[tuple[int, Player]]] = defaultdict(list)
    for original_index, player in enumerate(roster_list):
        if player.position in SKILL_POSITIONS:
            by_position[player.position].append((original_index, player))
    # A lower-scoring player beyond a position's maximum legal capacity can
    # never enter an optimal lineup. Removing those dominated rows sharply
    # reduces the live two-pick search without changing the answer.
    retained_indexes = {
        original_index
        for position, position_players in by_position.items()
        for original_index, _ in sorted(
            position_players,
            key=lambda item: (-item[1].projected_points, item[0]),
        )[: eligible_capacity.get(position, 0)]
    }
    players = [
        player
        for original_index, player in enumerate(roster_list)
        if original_index in retained_indexes
    ]
    # When every flexible skill slot has the same eligibility, the optimum is
    # exactly the best players in every dedicated slot plus the best eligible
    # leftovers for those flexes. This covers both the real one-flex league and
    # Sleeper mocks accidentally configured with two identical FLEX slots.
    # Avoiding the generic bitmask search matters because two-pick timing
    # evaluates this path hundreds of times while the user is on the clock.
    flexible_slots = [eligible for eligible in slots if len(eligible) > 1]
    if not flexible_slots or all(
        eligible == flexible_slots[0] for eligible in flexible_slots
    ):
        dedicated = Counter(
            eligible[0] for eligible in slots if len(eligible) == 1
        )
        indexed_by_position: dict[str, list[tuple[int, Player]]] = defaultdict(list)
        for index, player in enumerate(players):
            if player.projected_points > 0.0:
                indexed_by_position[player.position].append((index, player))
        selected_indexes: set[int] = set()
        for position, count in dedicated.items():
            selected_indexes.update(
                index
                for index, _ in sorted(
                    indexed_by_position.get(position, ()),
                    key=lambda item: (-item[1].projected_points, item[0]),
                )[:count]
            )
        if flexible_slots:
            flex_eligible = flexible_slots[0]
            flex_candidates = [
                (index, player)
                for position in flex_eligible
                for index, player in indexed_by_position.get(position, ())
                if index not in selected_indexes
            ]
            selected_indexes.update(
                index
                for index, _ in sorted(
                    flex_candidates,
                    key=lambda item: (-item[1].projected_points, item[0]),
                )[: len(flexible_slots)]
            )
        selected = [
            player for index, player in enumerate(players) if index in selected_indexes
        ]
        return sum(player.projected_points for player in selected), selected
    states: dict[int, tuple[float, tuple[int, ...]]] = {0: (0.0, ())}
    for player_index, player in enumerate(players):
        updated = dict(states)
        for mask, (score, selected) in states.items():
            for slot_index, eligible in enumerate(slots):
                bit = 1 << slot_index
                if mask & bit or player.position not in eligible:
                    continue
                candidate = (score + player.projected_points, (*selected, player_index))
                existing = updated.get(mask | bit)
                if existing is None or candidate[0] > existing[0]:
                    updated[mask | bit] = candidate
        states = updated
    score, selected = max(states.values(), key=lambda value: value[0])
    return score, [players[index] for index in selected]


def _replacement_players(
    roster_positions: Iterable[str], replacement_baselines: Mapping[str, float]
) -> list[Player]:
    slots = _starter_eligibility(roster_positions)
    players: list[Player] = []
    for position in SKILL_POSITIONS:
        count = sum(position in eligible for eligible in slots)
        projected_points = float(replacement_baselines.get(position) or 0.0)
        for index in range(count):
            players.append(
                Player(
                    key=f"__replacement__:{position}:{index}",
                    name=f"{position} waiver replacement {index + 1}",
                    position=position,
                    projected_points=projected_points,
                    adp=999.0,
                    vbd=0.0,
                    rank_score=999.0,
                )
            )
    return players


def _lineup_with_replacements(
    roster: Iterable[Player],
    roster_positions: Iterable[str],
    replacement_baselines: Mapping[str, float] | None,
) -> tuple[float, list[Player]]:
    players = list(roster)
    if replacement_baselines:
        players.extend(_replacement_players(roster_positions, replacement_baselines))
    score, selected = _optimal_lineup(players, roster_positions)
    return score, [
        player for player in selected if not player.key.startswith("__replacement__:")
    ]


def roster_score(
    roster: Iterable[Player],
    roster_positions: Iterable[str],
    replacement_baselines: Mapping[str, float] | None = None,
) -> float:
    """Projected score of the best legal lineup; bench receives no flat credit."""
    return _lineup_with_replacements(
        roster, roster_positions, replacement_baselines
    )[0]


def deterministic_roster_strength(
    roster: Iterable[Player],
    roster_positions: Iterable[str],
    replacement_baselines: Mapping[str, float],
    bye_weeks: Mapping[str, int] = NFL_BYE_WEEKS_2026,
    active_games: int = 17,
) -> dict[str, float]:
    """Score lineup, known-bye coverage, and reserve talent without randomness."""
    players = [player for player in roster if player.position in SKILL_POSITIONS]
    positions = tuple(roster_positions)
    base_lineup_score, base_starters = _optimal_lineup(players, positions)
    starter_keys = {player.key for player in base_starters}
    bye_coverage = 0.0
    for week in sorted(set(bye_weeks.values())):
        active_players = [
            player
            for player in players
            if not player.team or bye_weeks.get(player.team) != week
        ]
        active_base_starter_score = sum(
            player.projected_points
            for player in base_starters
            if not player.team or bye_weeks.get(player.team) != week
        )
        covered_score = roster_score(
            active_players,
            positions,
            replacement_baselines,
        )
        bye_coverage += max(0.0, covered_score - active_base_starter_score) / active_games

    bench_players = [player for player in players if player.key not in starter_keys]
    bench_vorp = sum(
        max(
            0.0,
            player.projected_points
            - float(replacement_baselines.get(player.position) or 0.0),
        )
        for player in bench_players
    )
    usable_bench_vorp = sum(
        max(
            0.0,
            player.projected_points
            - float(replacement_baselines.get(player.position) or 0.0),
        )
        * _reserve_slot_utility(player.position, positions)
        for player in bench_players
    )
    total_roster_vorp = sum(
        max(
            0.0,
            player.projected_points
            - float(replacement_baselines.get(player.position) or 0.0),
        )
        for player in players
    )
    return {
        "base_lineup_score": base_lineup_score,
        "bye_coverage_points": bye_coverage,
        "bye_adjusted_lineup_score": base_lineup_score + bye_coverage,
        "bench_vorp": bench_vorp,
        "usable_bench_vorp": usable_bench_vorp,
        "total_roster_vorp": total_roster_vorp,
    }


def weekly_use_roster_strength(
    roster: Iterable[Player],
    roster_positions: Iterable[str],
    replacement_baselines: Mapping[str, float],
    *,
    projection_miss_multiplier: float = 0.50,
) -> dict[str, Any]:
    """Evaluate reserves only when common no-bye shocks put them in the lineup.

    The four stress levels are disclosed sensitivities rather than asserted injury
    probabilities.  Each level applies the same exhaustive slot pattern to every
    roster: no shock; one affected starter; two affected starters; or three
    affected starters.  For an affected set, the evaluator includes the all-absent
    case and every case where one affected starter posts a material projection
    miss while the others are absent.

    A reserve receives credit only when it enters the legal optimal lineup.  The
    exact reserve lift is the full-roster score minus the score available from the
    original starters plus waiver replacements under the same shock.  Bye weeks
    never enter this evaluator.
    """
    if not 0.0 <= projection_miss_multiplier < 1.0:
        raise ValueError("Projection-miss multiplier must be between 0 and 1")
    players = [player for player in roster if player.position in SKILL_POSITIONS]
    positions = tuple(roster_positions)
    _, base_starters = _optimal_lineup(players, positions)
    starter_keys = tuple(player.key for player in base_starters)
    starter_key_set = set(starter_keys)

    def shock_patterns(size: int) -> list[tuple[frozenset[str], frozenset[str]]]:
        if size == 0:
            return [(frozenset(), frozenset())]
        patterns: list[tuple[frozenset[str], frozenset[str]]] = []
        for affected in combinations(starter_keys, size):
            affected_set = frozenset(affected)
            patterns.append((affected_set, frozenset()))
            for missed in affected:
                patterns.append(
                    (affected_set - {missed}, frozenset((missed,)))
                )
        return patterns

    def apply_shock(
        source: Iterable[Player],
        absent: frozenset[str],
        missed: frozenset[str],
    ) -> list[Player]:
        shocked = []
        for player in source:
            if player.key in absent:
                continue
            if player.key in missed:
                shocked.append(
                    replace(
                        player,
                        projected_points=(
                            player.projected_points * projection_miss_multiplier
                        ),
                    )
                )
            else:
                shocked.append(player)
        return shocked

    levels = {"no_absence": 0, "light": 1, "moderate": 2, "heavy": 3}
    results: dict[str, Any] = {}
    for label, affected_count in levels.items():
        patterns = shock_patterns(affected_count)
        full_scores: list[float] = []
        floor_scores: list[float] = []
        reserve_lifts: list[float] = []
        reserve_counts: list[int] = []
        reserve_entries: Counter[str] = Counter()
        for absent, missed in patterns:
            shocked_full = apply_shock(players, absent, missed)
            shocked_starters = apply_shock(base_starters, absent, missed)
            full_score, selected = _lineup_with_replacements(
                shocked_full, positions, replacement_baselines
            )
            floor_score, _ = _lineup_with_replacements(
                shocked_starters, positions, replacement_baselines
            )
            used_reserves = [
                player for player in selected if player.key not in starter_key_set
            ]
            full_scores.append(full_score)
            floor_scores.append(floor_score)
            reserve_lifts.append(max(0.0, full_score - floor_score))
            reserve_counts.append(len(used_reserves))
            reserve_entries.update(player.key for player in used_reserves)
        results[label] = {
            "affected_starter_count": affected_count,
            "scenario_count": len(patterns),
            "mean_full_lineup_score": fmean(full_scores),
            "mean_starter_waiver_floor_score": fmean(floor_scores),
            "mean_reserve_lift_above_waivers": fmean(reserve_lifts),
            "mean_reserve_starters_used": fmean(reserve_counts),
            "reserve_entry_rates": {
                key: reserve_entries[key] / len(patterns)
                for key in sorted(reserve_entries)
            },
        }
    return {
        "method": "no_bye_common_absence_and_projection_miss",
        "projection_miss_multiplier": projection_miss_multiplier,
        "base_starter_keys": list(starter_keys),
        "stress_levels": results,
    }


def _reserve_slot_utility(
    position: str, roster_positions: Iterable[str]
) -> float:
    """Discount reserve value by how much of the legal lineup it can cover.

    This is a deterministic roster-structure adjustment, not an injury estimate.
    In a 1-QB, 2-RB, 2-WR, 1-TE, 1-FLEX league the factors are QB 1/3,
    RB 3/3, WR 3/3, and TE 2/3.
    """
    slots = _starter_eligibility(roster_positions)
    coverage = {
        skill_position: sum(skill_position in eligible for eligible in slots)
        for skill_position in SKILL_POSITIONS
    }
    maximum = max(coverage.values(), default=0)
    return coverage.get(position, 0) / maximum if maximum else 0.0


def _deterministic_pick_roster_value_uncached(
    roster: Iterable[Player],
    roster_positions: Iterable[str],
    replacement_baselines: Mapping[str, float],
    bench_weight: float,
    reserve_redundancy_cap: bool = False,
) -> tuple[float, float, float]:
    """Fast lineup-plus-reserve proxy used while the draft clock is running."""
    players = [player for player in roster if player.position in SKILL_POSITIONS]
    positions = tuple(roster_positions)
    lineup_score, starters = _lineup_with_replacements(
        players, positions, replacement_baselines
    )
    starter_keys = {player.key for player in starters}
    bench_values: dict[str, list[float]] = defaultdict(list)
    for player in players:
        if player.key in starter_keys:
            continue
        bench_values[player.position].append(
            max(
                0.0,
                player.projected_points
                - float(replacement_baselines.get(player.position) or 0.0),
            )
            * _reserve_slot_utility(player.position, positions)
        )
    if reserve_redundancy_cap:
        eligible_slots = _starter_eligibility(positions)
        reserve_capacities = {
            position: sum(position in eligible for eligible in eligible_slots)
            for position in SKILL_POSITIONS
        }
        usable_bench_vorp = sum(
            sum(sorted(values, reverse=True)[: reserve_capacities.get(position, 0)])
            for position, values in bench_values.items()
        )
    else:
        usable_bench_vorp = sum(sum(values) for values in bench_values.values())
    return (
        lineup_score + bench_weight * usable_bench_vorp,
        lineup_score,
        usable_bench_vorp,
    )


@lru_cache(maxsize=50_000)
def _deterministic_pick_roster_value_cached(
    players: tuple[Player, ...],
    roster_positions: tuple[str, ...],
    replacement_baselines: tuple[tuple[str, float], ...],
    bench_weight: float,
    reserve_redundancy_cap: bool,
) -> tuple[float, float, float]:
    return _deterministic_pick_roster_value_uncached(
        players,
        roster_positions,
        dict(replacement_baselines),
        bench_weight,
        reserve_redundancy_cap,
    )


def _deterministic_pick_roster_value(
    roster: Iterable[Player],
    roster_positions: Iterable[str],
    replacement_baselines: Mapping[str, float],
    bench_weight: float,
    reserve_redundancy_cap: bool = False,
) -> tuple[float, float, float]:
    players = tuple(
        sorted(
            (player for player in roster if player.position in SKILL_POSITIONS),
            key=lambda player: (
                player.key,
                player.position,
                player.projected_points,
                player.rank_score,
            ),
        )
    )
    baselines = tuple(
        sorted((position, float(value)) for position, value in replacement_baselines.items())
    )
    return _deterministic_pick_roster_value_cached(
        players,
        tuple(roster_positions),
        baselines,
        float(bench_weight),
        bool(reserve_redundancy_cap),
    )


def _relative_z_score(value: float, field: Iterable[float]) -> float:
    values = tuple(float(item) for item in field)
    spread = pstdev(values) if len(values) > 1 else 0.0
    return (value - fmean(values)) / spread if spread > 1e-9 else 0.0


def expected_roster_score(
    roster: Iterable[Player],
    roster_positions: Iterable[str],
    *,
    availability_rates: Iterable[float] = (0.05, 0.10, 0.15),
    samples_per_rate: int = 48,
    scenario_seed: int = 2026,
    replacement_baselines: Mapping[str, float] | None = None,
) -> tuple[float, dict[str, float]]:
    """Expected optimal lineup under deterministic, common availability scenarios.

    The rates are sensitivity cases, not asserted injury probabilities. Player-keyed
    hashes ensure every strategy sees the same availability outcome for a player.
    """
    players = list(roster)
    rates = tuple(float(rate) for rate in availability_rates)
    if not rates or samples_per_rate <= 0:
        base = roster_score(players, roster_positions, replacement_baselines)
        return base, {"base": base}
    by_rate: dict[str, float] = {}
    for rate in rates:
        if not 0.0 <= rate < 1.0:
            raise ValueError("Availability sensitivity rates must be between 0 and 1")
        threshold = int(rate * (1 << 64))
        scores: list[float] = []
        for sample in range(samples_per_rate):
            available_players = []
            for player in players:
                token = f"{scenario_seed}:{rate:.6f}:{sample}:{player.key}".encode("utf-8")
                unavailable = int.from_bytes(sha256(token).digest()[:8], "big") < threshold
                if not unavailable:
                    available_players.append(player)
            scores.append(
                roster_score(
                    available_players, roster_positions, replacement_baselines
                )
            )
        by_rate[f"{rate:.2f}"] = fmean(scores)
    return fmean(by_rate.values()), by_rate


def _scenario_marginal_context(
    roster: list[Player],
    roster_positions: Iterable[str],
    availability_rates: Iterable[float],
    replacement_baselines: Mapping[str, float] | None = None,
) -> dict[str, Any]:
    base_score, starters = _lineup_with_replacements(
        roster, roster_positions, replacement_baselines
    )
    rates = tuple(availability_rates)
    no_absence_weight = fmean(
        (1.0 - rate) ** (len(starters) + 1) for rate in rates
    ) if rates else 1.0
    one_absence_weight = fmean(
        rate * ((1.0 - rate) ** len(starters)) for rate in rates
    ) if rates else 0.0
    absences = []
    for absent in starters:
        before_absence = [player for player in roster if player.key != absent.key]
        absences.append(
            (
                before_absence,
                roster_score(
                    before_absence, roster_positions, replacement_baselines
                ),
            )
        )
    return {
        "base_score": base_score,
        "no_absence_weight": no_absence_weight,
        "one_absence_weight": one_absence_weight,
        "absences": absences,
    }


def _scenario_marginal_value(
    roster: list[Player],
    candidate: Player,
    roster_positions: Iterable[str],
    availability_rates: Iterable[float],
    context: Mapping[str, Any] | None = None,
    replacement_baselines: Mapping[str, float] | None = None,
) -> float:
    """Single-absence approximation of a candidate's expected lineup contribution."""
    marginal_context = context or _scenario_marginal_context(
        roster, roster_positions, availability_rates, replacement_baselines
    )
    after = [*roster, candidate]
    upgraded_score = roster_score(after, roster_positions, replacement_baselines)
    value = max(
        0.0, upgraded_score - float(marginal_context["base_score"])
    ) * float(marginal_context["no_absence_weight"])
    for before_absence, before_score in marginal_context["absences"]:
        value += max(
            0.0,
            roster_score(
                [*before_absence, candidate],
                roster_positions,
                replacement_baselines,
            )
            - before_score,
        ) * float(marginal_context["one_absence_weight"])
    return value


def _upside_signals(players: Iterable[Player]) -> dict[str, dict[str, float]]:
    """Create bounded, auditable bench-upside signals from independent board inputs."""
    by_position: dict[str, list[Player]] = defaultdict(list)
    for player in players:
        by_position[player.position].append(player)
    projection_ranks: dict[str, int] = {}
    for position_players in by_position.values():
        for rank, player in enumerate(
            sorted(position_players, key=lambda item: (-item.projected_points, item.rank_score)),
            start=1,
        ):
            projection_ranks[player.key] = rank
    signals: dict[str, dict[str, float]] = {}
    for player in players:
        projection_rank = float(projection_ranks[player.key])
        cohort_disagreement = min(
            1.0,
            abs(player.ecr - player.grouped_rank) / max(1.0, player.ecr),
        )
        cohort_edge = min(
            1.0,
            max(0.0, player.ecr - player.grouped_rank) / max(1.0, player.ecr),
        )
        projection_edge = min(
            1.0,
            max(0.0, projection_rank - player.rank_score) / max(1.0, projection_rank),
        )
        market_edge = min(
            1.0,
            max(0.0, player.adp - player.board_order) / max(1.0, player.adp),
        )
        # Ten projected-point units is the maximum bonus before the policy weight.
        upside = 10.0 * (
            0.20 * cohort_disagreement
            + 0.25 * cohort_edge
            + 0.35 * projection_edge
            + 0.20 * market_edge
        )
        signals[player.key] = {
            "upside": upside,
            "cohort_disagreement": cohort_disagreement,
            "cohort_edge": cohort_edge,
            "projection_edge": projection_edge,
            "market_edge": market_edge,
        }
    return signals


def _within_precompletion_bench_cap(
    player: Player,
    roster: list[Player],
    roster_positions: Iterable[str],
    bench_cap: int,
) -> bool:
    after = [*roster, player]
    starter_count = len(_starter_eligibility(roster_positions))
    if _filled_starter_slots(after, roster_positions) == starter_count:
        return True
    return _bench_players_before_starters(after, roster_positions) <= bench_cap


def _roster_need_label(player: Player, roster: list[Player], roster_positions: Iterable[str]) -> str:
    dedicated = Counter(position for position in roster_positions if position in SKILL_POSITIONS)
    counts = Counter(item.position for item in roster)
    if counts[player.position] < dedicated[player.position]:
        return f"open_{player.position.lower()}_starter"
    before = _filled_starter_slots(roster, roster_positions)
    after = _filled_starter_slots([*roster, player], roster_positions)
    return "open_flex_starter" if after > before else "bench_depth"


def _expected_next_by_position(
    available: Iterable[Player],
    current_pick: int,
    target_pick: int,
    replacement_baselines: Mapping[str, float] | None = None,
    survival_overrides: Mapping[str, float] | None = None,
) -> dict[str, dict[str, Any]]:
    by_position: dict[str, list[Player]] = defaultdict(list)
    for player in available:
        if player.projected_points > 0.0:
            by_position[player.position].append(player)
    result: dict[str, dict[str, Any]] = {}
    for position, players in by_position.items():
        remaining_probability = 1.0
        expected_projected_points = 0.0
        most_likely: tuple[float, Player] | None = None
        for player in sorted(
            players, key=lambda item: (-item.projected_points, item.rank_score)
        ):
            survive = (
                float(survival_overrides[player.key])
                if survival_overrides and player.key in survival_overrides
                else survival_probability(
                    player.acquisition_pick, current_pick, target_pick
                )
            )
            probability_best = remaining_probability * survive
            expected_projected_points += probability_best * player.projected_points
            if most_likely is None or probability_best > most_likely[0]:
                most_likely = (probability_best, player)
            remaining_probability *= 1.0 - survive
        expected_projected_points += remaining_probability * float(
            (replacement_baselines or {}).get(position) or 0.0
        )
        result[position] = {
            "expected_projected_points": expected_projected_points,
            "player": most_likely[1] if most_likely is not None else None,
            "no_player_probability": remaining_probability,
        }
    return result


def _replacement_adjusted_roster_score(
    roster: Iterable[Player],
    roster_positions: Iterable[str],
    replacement_baselines: Mapping[str, float],
) -> float:
    adjusted = [
        Player(
            key=player.key,
            name=player.name,
            position=player.position,
            projected_points=max(
                0.0,
                player.projected_points - float(replacement_baselines.get(player.position) or 0.0),
            ),
            adp=player.adp,
            vbd=player.vbd,
            rank_score=player.rank_score,
        )
        for player in roster
    ]
    return roster_score(adjusted, roster_positions)


def _two_pick_path_value(
    candidate: Player,
    available: Iterable[Player],
    roster: list[Player],
    roster_positions: Iterable[str],
    total_user_picks: int,
    current_pick: int,
    next_pick: int,
    availability_rates: Iterable[float],
    replacement_baselines: Mapping[str, float],
    survival_overrides: Mapping[str, float] | None = None,
    deterministic_bench_weight: float | None = None,
    continuation_pick: int | None = None,
    continuation_survival_overrides: Mapping[str, float] | None = None,
    path_details: dict[str, Any] | None = None,
) -> tuple[float, float, str, float]:
    """Expected replacement-aware contribution across this and the next user pick.

    The next-pick choices are mutually exclusive alternatives ordered by their
    marginal roster contribution. Their conditional ADP survival probabilities
    create controlled run/no-run states without assuming the draft is append-only.
    """
    rates = tuple(availability_rates)
    average_absence_rate = fmean(rates) if rates else 0.0

    def path_roster_value(path_roster: list[Player]) -> float:
        if deterministic_bench_weight is not None:
            return _deterministic_pick_roster_value(
                path_roster,
                roster_positions,
                replacement_baselines,
                deterministic_bench_weight,
            )[0]
        lineup_score, starters = _lineup_with_replacements(
            path_roster, roster_positions, replacement_baselines
        )
        starter_keys = {player.key for player in starters}
        depth_edges = sorted(
            (
                max(
                    0.0,
                    player.projected_points
                    - float(replacement_baselines.get(player.position) or 0.0),
                )
                for player in path_roster
                if player.key not in starter_keys
            ),
            reverse=True,
        )
        # Pick-time proxy for the same availability cases used by final scoring:
        # only the best two legal depth edges receive expected absence credit.
        return lineup_score + average_absence_rate * sum(depth_edges[:2])

    base_value = path_roster_value(roster)
    after = [*roster, candidate]
    after_value = path_roster_value(after)
    current_value = after_value - base_value
    raw_options: list[tuple[float, Player]] = []
    after_counts = Counter(player.position for player in after)
    after_skill_count = sum(after_counts.get(position, 0) for position in SKILL_POSITIONS)
    remaining_after_next = total_user_picks - after_skill_count - 1
    starter_slots = len(_starter_eligibility(roster_positions))
    preserves_path_by_position = {
        position: (
            starter_slots
            - _filled_starter_slots(
                [
                    *after,
                    Player(
                        key=f"__path_check__:{position}",
                        name="path check",
                        position=position,
                        projected_points=0.0,
                        adp=999.0,
                        vbd=0.0,
                        rank_score=999.0,
                    ),
                ],
                roster_positions,
            )
            <= remaining_after_next
        )
        for position in SKILL_POSITIONS
    }
    for player in available:
        if (
            player.key == candidate.key
            or after_counts[player.position] >= POSITION_CAPS.get(player.position, 99)
        ):
            continue
        if not preserves_path_by_position.get(player.position, True):
            continue
        survival = (
            float(survival_overrides[player.key])
            if survival_overrides and player.key in survival_overrides
            else survival_probability(
                player.acquisition_pick, current_pick, next_pick
            )
        )
        raw_options.append((max(0.0, min(1.0, survival)), player))

    # Only a bounded set can be the best available next pick. Preselect by
    # projection above waivers and survival before the more expensive scenario
    # marginal calculation.
    preselected: list[tuple[float, Player]] = []
    by_position: dict[str, list[tuple[float, Player]]] = defaultdict(list)
    for option in raw_options:
        by_position[option[1].position].append(option)
    for position_options in by_position.values():
        preselected.extend(
            sorted(
                position_options,
                key=lambda option: (
                    -(
                        option[1].projected_points
                        - float(replacement_baselines.get(option[1].position) or 0.0)
                    ),
                    option[1].rank_score,
                ),
            )[:4]
        )
        preselected.extend(
            sorted(position_options, key=lambda option: (-option[0], option[1].rank_score))[:1]
        )
    unique_preselected = {option[1].key: option for option in preselected}
    options = []
    use_continuation = bool(
        continuation_pick is not None
        and next_pick == current_pick + 1
        and continuation_pick > next_pick
    )
    for survival, player in unique_preselected.values():
        next_value = path_roster_value([*after, player]) - after_value
        continuation_name = None
        continuation_value = None
        if use_continuation:
            nested_available = [
                option
                for option in available
                if option.key not in {candidate.key, player.key}
            ]
            (
                turn_value,
                immediate_value,
                continuation_name,
                continuation_value,
            ) = _two_pick_path_value(
                player,
                nested_available,
                after,
                roster_positions,
                total_user_picks,
                next_pick,
                int(continuation_pick),
                availability_rates,
                replacement_baselines,
                continuation_survival_overrides,
                deterministic_bench_weight,
            )
            next_value = turn_value
        else:
            immediate_value = next_value
        options.append(
            (
                next_value,
                player,
                survival,
                immediate_value,
                continuation_name,
                continuation_value,
            )
        )
    unique = {option[1].key: option for option in options}
    ordered = sorted(unique.values(), key=lambda option: (-option[0], option[1].rank_score))
    remaining_probability = 1.0
    expected_next_value = 0.0
    expected_name = "replacement"
    best_probability = -1.0
    selected_details = None
    for (
        next_value,
        player,
        survival,
        immediate_value,
        continuation_name,
        continuation_value,
    ) in ordered:
        chosen_probability = remaining_probability * survival
        expected_next_value += chosen_probability * next_value
        if chosen_probability > best_probability:
            best_probability = chosen_probability
            expected_name = player.name
            selected_details = {
                "planned_second_player": player.name,
                "planned_second_player_key": player.key,
                "planned_second_value": immediate_value,
                "continuation_pick": continuation_pick if use_continuation else None,
                "expected_continuation_player": continuation_name,
                "expected_continuation_value": continuation_value,
            }
        remaining_probability *= 1.0 - survival
    if path_details is not None:
        path_details.update(selected_details or {})
    return current_value + expected_next_value, current_value, expected_name, expected_next_value


def rank_user_candidates(
    available: list[Player],
    roster: list[Player],
    policy: str,
    pick_no: int,
    round_no: int,
    teams: int,
    draft_slot: int,
    roster_positions: Iterable[str],
    total_user_picks: int,
    replacement_baselines: Mapping[str, float],
    bench_before_starters: int | None = None,
    availability_rates: Iterable[float] = (0.05, 0.10, 0.15),
    upside_signals: Mapping[str, Mapping[str, float]] | None = None,
    next_pick_survival_overrides: Mapping[str, float] | None = None,
    rank_vorp_curve: RankVorpCurve | None = None,
    reconciliation_baselines: Mapping[float, Mapping[str, float]] | None = None,
    ballot_preferences: Mapping[tuple[str, str], float] | None = None,
    reconciliation_players: Mapping[float, Mapping[str, Player]] | None = None,
    continuation_survival_overrides: Mapping[str, float] | None = None,
) -> list[dict[str, Any]]:
    reconciled_policy = _reconciled_pick_policy(policy)
    if reconciled_policy is not None:
        base_policy, rank_weight, strict_first_round = reconciled_policy
        forced_first_qb_round = _forced_first_qb_round(policy)
        forced_first_te_round = _forced_first_te_round(policy)
        construction_config = _construction_policy_config(policy)
        curve = rank_vorp_curve or fit_rank_vorp_curve(
            [*available, *roster], replacement_baselines
        )
        timing_available = _construction_filtered_available(
            available, roster, round_no, construction_config
        )
        if forced_first_qb_round is not None and not any(
            player.position == "QB" for player in roster
        ):
            if round_no < forced_first_qb_round:
                timing_available = [
                    player for player in available if player.position != "QB"
                ]
            else:
                timing_available = [
                    player for player in available if player.position == "QB"
                ] or available
        if forced_first_te_round is not None and not any(
            player.position == "TE" for player in roster
        ):
            if round_no < forced_first_te_round:
                timing_available = [
                    player for player in timing_available if player.position != "TE"
                ]
            else:
                timing_available = [
                    player for player in timing_available if player.position == "TE"
                ] or timing_available
        original_by_key = {player.key: player for player in timing_available}
        adjusted_lookup = (reconciliation_players or {}).get(rank_weight) or {}
        adjusted_available = [
            adjusted_lookup.get(player.key)
            or rank_adjusted_player(
                player, curve, rank_weight, replacement_baselines
            )
            for player in timing_available
        ]
        adjusted_roster = [
            adjusted_lookup.get(player.key)
            or rank_adjusted_player(
                player, curve, rank_weight, replacement_baselines
            )
            for player in roster
        ]
        adjusted_baselines = (
            dict((reconciliation_baselines or {}).get(rank_weight) or {})
            or market_replacement_baselines(
                adjusted_available,
                teams,
                total_user_picks,
            )
        )
        ranked = rank_user_candidates(
            adjusted_available,
            adjusted_roster,
            base_policy,
            pick_no,
            round_no,
            teams,
            draft_slot,
            roster_positions,
            total_user_picks,
            adjusted_baselines,
            bench_before_starters,
            availability_rates,
            upside_signals,
            next_pick_survival_overrides,
            ballot_preferences=ballot_preferences,
            continuation_survival_overrides=continuation_survival_overrides,
        )
        for row in ranked:
            adjusted_player = row["_player"]
            row["_player"] = original_by_key[adjusted_player.key]
            row["selection_basis"] = (
                "expert_ordered_positional_curve_with_selected_rank_blend"
                if rank_weight > 0.0
                else "expert_ordered_positional_projection_curve"
            )
            row["rank_reconciliation_weight"] = rank_weight
            row["forced_first_qb_round"] = forced_first_qb_round
            row["forced_first_te_round"] = forced_first_te_round
            row["construction_policy"] = dict(construction_config)
            row["raw_projected_points"] = round(
                original_by_key[adjusted_player.key].source_projected_points, 3
            )
            row["position_curve_projected_points"] = round(
                original_by_key[adjusted_player.key].projected_points, 3
            )
            row["adjusted_projected_points"] = round(
                adjusted_player.projected_points, 3
            )
            row["projection_value_position_rank"] = original_by_key[
                adjusted_player.key
            ].projection_value_position_rank
        qb_floor_threshold = _qb_streaming_floor_threshold(policy)
        qb_wait_drop = max(
            (
                float(row["vona"])
                for row in ranked
                if row["position"] == "QB"
            ),
            default=None,
        )
        defer_qb = bool(
            qb_floor_threshold is not None
            and not any(player.position == "QB" for player in roster)
            and len(roster) < total_user_picks - 1
            and qb_wait_drop is not None
            and qb_wait_drop <= qb_floor_threshold
            and any(row["position"] != "QB" for row in ranked)
        )
        if defer_qb:
            ranked = [row for row in ranked if row["position"] != "QB"]
        for row in ranked:
            row["qb_streaming_floor_threshold"] = qb_floor_threshold
            row["qb_expected_next_pick_drop"] = (
                round(qb_wait_drop, 3) if qb_wait_drop is not None else None
            )
            row["qb_streaming_floor_deferred"] = defer_qb
        if strict_first_round and round_no == 1:
            return sorted(
                ranked,
                key=lambda row: (
                    row["_player"].overall_rank_score,
                    row["_player"].adp,
                    -float(row["final_score"]),
                ),
            )
        guardrail = _position_guardrail_config(policy)
        if guardrail["method"] == "direct_weighted_ballot":
            if not ballot_preferences:
                raise ValueError(
                    f"{policy} requires direct weighted ballot preferences"
                )
            constrained = _expert_order_constrained_candidates(
                ranked,
                ballot_preferences=ballot_preferences,
                ballot_threshold=float(guardrail["threshold"]),
            )
        else:
            constrained = _expert_order_constrained_candidates(
                ranked,
                position_rank_tolerance=float(guardrail["tolerance"]),
            )
        scarcity_config = _near_tie_scarcity_config(policy) or {}
        constrained = _promote_near_tie_scarcity_candidate(
            constrained,
            scarcity_config.get("maximum_score_gap"),
            scarcity_config.get("minimum_survival_gap"),
            teams=teams,
            draft_slot=draft_slot,
            roster_positions=roster_positions,
        )
        if policy in {
            "half_ppr_reconciled_turn_aware",
            "half_ppr_reconciled_horizon_guard",
        }:
            constrained = _promote_turn_aware_qb_deferral(
                constrained,
                roster,
                teams=teams,
                draft_slot=draft_slot,
                roster_positions=roster_positions,
            )
        constrained = _promote_elite_te_sequence_candidate(
            constrained,
            roster,
            round_no,
            _elite_te_sequence_score_gap(policy),
            teams=teams,
            draft_slot=draft_slot,
            roster_positions=roster_positions,
        )
        constrained = _promote_close_construction_candidate(
            constrained,
            roster,
            round_no,
            construction_config,
        )
        for row in constrained:
            row["positional_guardrail"] = dict(guardrail)
            row["near_tie_scarcity_config"] = dict(scarcity_config)
        return constrained
    candidates = [
        player
        for player in available
        if _can_draft(player, roster)
        and _preserves_starter_path(player, roster, roster_positions, total_user_picks)
        and (
            bench_before_starters is None
            or _within_precompletion_bench_cap(
                player,
                roster,
                roster_positions,
                bench_before_starters,
            )
        )
    ]
    if not candidates:
        candidates = [player for player in available if _can_draft(player, roster)] or available
    consensus_band = _consensus_candidate_band(policy, round_no)
    if consensus_band is not None:
        expert_ranked = sorted(
            (player for player in candidates if player.overall_rank_score < 999.0),
            key=lambda player: (player.overall_rank_score, player.adp),
        )
        if expert_ranked:
            candidates = expert_ranked[:consensus_band]
    next_pick = next_pick_for_slot(pick_no, draft_slot, teams) or pick_no + teams
    fallbacks = _expected_next_by_position(
        available,
        pick_no,
        next_pick,
        replacement_baselines,
        next_pick_survival_overrides,
    )
    normalized_policy = "vols" if policy == "vbd" else policy
    experimental_profile = _experimental_profile(normalized_policy, draft_slot)
    starter_count = len(_starter_eligibility(roster_positions))
    starters_complete = _filled_starter_slots(roster, roster_positions) == starter_count
    deferral_candidate_keys: set[str] | None = None
    if (
        experimental_profile
        and experimental_profile.get("starter_deferral")
        and not starters_complete
        and round_no > 1
    ):
        by_position_proxy: dict[str, list[tuple[float, Player]]] = defaultdict(list)
        for candidate in candidates:
            fallback = fallbacks.get(candidate.position, {})
            expected_points = float(
                fallback.get("expected_projected_points")
                or replacement_baselines.get(candidate.position)
                or 0.0
            )
            vona = candidate.projected_points - expected_points
            vorp = candidate.projected_points - float(
                replacement_baselines.get(candidate.position) or 0.0
            )
            proxy = vorp + float(experimental_profile["vona_weight"]) * vona
            by_position_proxy[candidate.position].append((proxy, candidate))
        deferral_candidate_keys = {
            player.key
            for position_candidates in by_position_proxy.values()
            for _, player in sorted(
                position_candidates, key=lambda item: (-item[0], item[1].rank_score)
            )[:6]
        }
    scenario_context: Mapping[str, Any] | None = None
    scenario_candidate_keys: set[str] | None = None
    deterministic_team_context: tuple[float, float, float] | None = None
    if (
        experimental_profile
        and experimental_profile.get("total_team_bench_weight") is not None
        and starters_complete
    ):
        deterministic_team_context = _deterministic_pick_roster_value(
            roster,
            roster_positions,
            replacement_baselines,
            float(experimental_profile["total_team_bench_weight"]),
            bool(experimental_profile.get("reserve_redundancy_cap")),
        )
    if experimental_profile and experimental_profile.get("scenario_bench") and starters_complete:
        scenario_replacement_baselines = (
            replacement_baselines
            if experimental_profile.get("replacement_aware")
            else None
        )
        scenario_context = _scenario_marginal_context(
            roster,
            roster_positions,
            availability_rates,
            scenario_replacement_baselines,
        )
        by_position: dict[str, list[tuple[float, Player]]] = defaultdict(list)
        for candidate in candidates:
            candidate_fallback = fallbacks.get(candidate.position, {})
            candidate_vona = candidate.projected_points - float(
                candidate_fallback.get("expected_projected_points")
                or replacement_baselines.get(candidate.position)
                or 0.0
            )
            candidate_vorp = candidate.projected_points - float(
                replacement_baselines.get(candidate.position) or 0.0
            )
            candidate_upside = float(
                (upside_signals or {}).get(candidate.key, {}).get("upside") or 0.0
            )
            proxy = (
                candidate_vorp
                + float(experimental_profile["post_starter_vona_weight"])
                * candidate_vona
                + float(experimental_profile["upside_weight"]) * candidate_upside
            )
            by_position[candidate.position].append((proxy, candidate))
        scenario_candidate_keys = set()
        for position_candidates in by_position.values():
            scenario_candidate_keys.update(
                player.key
                for _, player in sorted(
                    position_candidates, key=lambda item: (-item[0], item[1].rank_score)
                )[:12]
            )
            scenario_candidate_keys.update(
                player.key
                for _, player in sorted(
                    position_candidates,
                    key=lambda item: (-item[1].projected_points, item[1].rank_score),
                )[:4]
            )
    needs_marginal_vorp = normalized_policy in {"market_aware", "dynamic"}
    current_roster_value = (
        _replacement_adjusted_roster_score(
            roster,
            roster_positions,
            replacement_baselines,
        )
        if needs_marginal_vorp
        else 0.0
    )
    ranked: list[dict[str, Any]] = []
    for player in candidates:
        survival = (
            float(next_pick_survival_overrides[player.key])
            if next_pick_survival_overrides
            and player.key in next_pick_survival_overrides
            else survival_probability(player.acquisition_pick, pick_no, next_pick)
        )
        fallback = fallbacks.get(player.position, {})
        expected_fallback_points = float(
            fallback.get("expected_projected_points")
            or replacement_baselines.get(player.position)
            or 0.0
        )
        vona = player.projected_points - expected_fallback_points
        expected_fallback = player.vbd - vona
        replacement = float(replacement_baselines.get(player.position) or 0.0)
        vorp = player.projected_points - replacement
        marginal_vorp = (
            _replacement_adjusted_roster_score(
                [*roster, player],
                roster_positions,
                replacement_baselines,
            )
            - current_roster_value
            if needs_marginal_vorp
            else None
        )
        scenario_marginal = None
        scenario_marginal_evaluated = None
        signal = (upside_signals or {}).get(player.key, {})
        upside = float(signal.get("upside") or 0.0)
        soft_bench_penalty = 0.0
        two_pick_path_value = None
        current_pick_path_value = None
        expected_next_path_value = None
        expected_next_path_player = None
        expected_continuation_path_value = None
        expected_continuation_path_player = None
        turn_aware_path_value = None
        turn_aware_next_path_player = None
        turn_aware_next_path_player_key = None
        turn_aware_continuation_path_value = None
        turn_aware_continuation_path_player = None
        continuation_pick = None
        contested_pick_survival = None
        starter_deferral_evaluated = False
        deterministic_team_marginal = None
        deterministic_bench_marginal = None
        if normalized_policy in {
            "standard_expert_consensus",
            "half_ppr_expert_consensus",
            "expert_consensus",
        }:
            score = -player.overall_rank_score
        elif normalized_policy == "vols":
            score = player.vbd
        elif normalized_policy == "vorp":
            score = vorp
        elif normalized_policy == "vona":
            score = vona
        elif normalized_policy in {"market_aware", "dynamic"}:
            assert marginal_vorp is not None
            score = 0.5 * marginal_vorp + 0.5 * vona
        elif experimental_profile is not None:
            if experimental_profile["first_round_vols"] and round_no == 1:
                score = player.vbd
            elif (
                experimental_profile.get("starter_deferral")
                and not starters_complete
            ):
                starter_deferral_evaluated = bool(
                    deferral_candidate_keys is None or player.key in deferral_candidate_keys
                )
                if starter_deferral_evaluated:
                    use_turn_aware = bool(experimental_profile.get("turn_aware"))
                    use_turn_aware_shadow = bool(
                        experimental_profile.get("turn_aware_shadow")
                    )
                    if (
                        (use_turn_aware or use_turn_aware_shadow)
                        and next_pick == pick_no + 1
                    ):
                        continuation_pick = next_pick_for_slot(
                            next_pick, draft_slot, teams
                        )
                    path_details: dict[str, Any] = {}
                    (
                        two_pick_path_value,
                        current_pick_path_value,
                        expected_next_path_player,
                        expected_next_path_value,
                    ) = _two_pick_path_value(
                        player,
                        available,
                        roster,
                        roster_positions,
                        total_user_picks,
                        pick_no,
                        next_pick,
                        availability_rates,
                        replacement_baselines,
                        next_pick_survival_overrides,
                        experimental_profile.get("total_team_bench_weight"),
                        continuation_pick if use_turn_aware else None,
                        (
                            continuation_survival_overrides
                            if use_turn_aware
                            else None
                        ),
                        path_details if use_turn_aware else None,
                    )
                    if use_turn_aware:
                        expected_continuation_path_player = path_details.get(
                            "expected_continuation_player"
                        )
                        expected_continuation_path_value = path_details.get(
                            "expected_continuation_value"
                        )
                        turn_aware_path_value = two_pick_path_value
                        turn_aware_next_path_player = expected_next_path_player
                        turn_aware_next_path_player_key = path_details.get(
                            "planned_second_player_key"
                        )
                        turn_aware_continuation_path_player = (
                            expected_continuation_path_player
                        )
                        turn_aware_continuation_path_value = (
                            expected_continuation_path_value
                        )
                    elif use_turn_aware_shadow and continuation_pick is not None:
                        shadow_details: dict[str, Any] = {}
                        (
                            turn_aware_path_value,
                            _,
                            turn_aware_next_path_player,
                            _,
                        ) = _two_pick_path_value(
                            player,
                            available,
                            roster,
                            roster_positions,
                            total_user_picks,
                            pick_no,
                            next_pick,
                            availability_rates,
                            replacement_baselines,
                            next_pick_survival_overrides,
                            experimental_profile.get("total_team_bench_weight"),
                            continuation_pick,
                            continuation_survival_overrides,
                            shadow_details,
                        )
                        turn_aware_continuation_path_player = shadow_details.get(
                            "expected_continuation_player"
                        )
                        turn_aware_next_path_player_key = shadow_details.get(
                            "planned_second_player_key"
                        )
                        turn_aware_continuation_path_value = shadow_details.get(
                            "expected_continuation_value"
                        )
                    if continuation_pick is not None:
                        contested_pick_survival = (
                            float(continuation_survival_overrides[player.key])
                            if continuation_survival_overrides
                            and player.key in continuation_survival_overrides
                            else survival_probability(
                                player.acquisition_pick,
                                next_pick,
                                continuation_pick,
                            )
                        )
                    score = two_pick_path_value
                else:
                    score = -10000.0
            elif experimental_profile.get("total_team_bench_weight") is not None:
                assert deterministic_team_context is not None
                after_team_context = _deterministic_pick_roster_value(
                    [*roster, player],
                    roster_positions,
                    replacement_baselines,
                    float(experimental_profile["total_team_bench_weight"]),
                    bool(experimental_profile.get("reserve_redundancy_cap")),
                )
                deterministic_team_marginal = (
                    after_team_context[0] - deterministic_team_context[0]
                )
                deterministic_bench_marginal = (
                    after_team_context[2] - deterministic_team_context[2]
                )
                score = (
                    deterministic_team_marginal
                    + float(experimental_profile["post_starter_vona_weight"]) * vona
                    + float(experimental_profile["upside_weight"])
                    * (upside if player.position in ("RB", "WR") else 0.0)
                )
            elif experimental_profile.get("scenario_bench") and starters_complete:
                scenario_marginal_evaluated = (
                    scenario_candidate_keys is None or player.key in scenario_candidate_keys
                )
                scenario_marginal = (
                    _scenario_marginal_value(
                        roster,
                        player,
                        roster_positions,
                        availability_rates,
                        scenario_context,
                        scenario_replacement_baselines,
                    )
                    if scenario_marginal_evaluated
                    else 0.0
                )
                score = (
                    scenario_marginal
                    + float(experimental_profile["post_starter_vona_weight"]) * vona
                    + float(experimental_profile["upside_weight"]) * upside
                )
            elif experimental_profile["vona_only"]:
                score = vona
            else:
                score = vorp + float(experimental_profile["vona_weight"]) * vona
                if experimental_profile.get("soft_bench_penalty"):
                    after = [*roster, player]
                    if _filled_starter_slots(after, roster_positions) < starter_count:
                        surplus = _bench_players_before_starters(after, roster_positions)
                        soft_bench_penalty = (
                            float(experimental_profile["soft_bench_penalty"]) * surplus
                        )
                        score -= soft_bench_penalty
            if experimental_profile.get("scenario_bench") and player.projected_points <= 0.0:
                score -= 1000.0
        else:
            score = player.vbd + _strategy_modifier(policy, player.position, round_no, roster)
        fallback_player = fallback.get("player")
        ranked.append(
            {
                "_player": player,
                "player_key": player.key,
                "player_name": player.name,
                "position": player.position,
                "overall_expert_rank": round(player.overall_rank_score, 3),
                "position_expert_rank": round(player.rank_score, 3),
                "overall_rank_stddev": player.overall_rank_stddev,
                "overall_rank_min": player.overall_rank_min,
                "overall_rank_max": player.overall_rank_max,
                "overall_rank_experts": player.overall_rank_experts,
                "overall_rank_weight_coverage": player.overall_rank_weight_coverage,
                "position_rank_stddev": player.position_rank_stddev,
                "position_rank_min": player.position_rank_min,
                "position_rank_max": player.position_rank_max,
                "position_rank_experts": player.position_rank_experts,
                "position_rank_weight_coverage": player.position_rank_weight_coverage,
                "general_ecr_rank": round(player.overall_ecr_rank, 3),
                "projected_points": round(player.projected_points, 3),
                "adp": round(player.adp, 3),
                "acquisition_adp": round(player.acquisition_pick, 3),
                "acquisition_position_slot": player.acquisition_position_slot,
                "vols": round(player.vbd, 3),
                "vorp": round(vorp, 3),
                "marginal_vorp": round(marginal_vorp, 3) if marginal_vorp is not None else None,
                "scenario_marginal_value": (
                    round(scenario_marginal, 3) if scenario_marginal is not None else None
                ),
                "scenario_marginal_evaluated": scenario_marginal_evaluated,
                "replacement_aware_marginal": bool(
                    experimental_profile
                    and experimental_profile.get("replacement_aware")
                    and scenario_marginal is not None
                ),
                "upside_bonus_base": round(upside, 3),
                "cohort_disagreement": round(
                    float(signal.get("cohort_disagreement") or 0.0), 4
                ),
                "projection_edge": round(float(signal.get("projection_edge") or 0.0), 4),
                "market_edge": round(float(signal.get("market_edge") or 0.0), 4),
                "soft_bench_penalty": round(soft_bench_penalty, 3),
                "two_pick_path_value": (
                    round(two_pick_path_value, 3) if two_pick_path_value is not None else None
                ),
                "current_pick_path_value": (
                    round(current_pick_path_value, 3)
                    if current_pick_path_value is not None
                    else None
                ),
                "expected_next_path_value": (
                    round(expected_next_path_value, 3)
                    if expected_next_path_value is not None
                    else None
                ),
                "expected_next_path_player": expected_next_path_player,
                "continuation_pick": continuation_pick,
                "contested_pick_survival": (
                    round(contested_pick_survival, 6)
                    if contested_pick_survival is not None
                    else None
                ),
                "expected_continuation_path_value": (
                    round(expected_continuation_path_value, 3)
                    if expected_continuation_path_value is not None
                    else None
                ),
                "expected_continuation_path_player": expected_continuation_path_player,
                "turn_aware_path_value": (
                    round(turn_aware_path_value, 3)
                    if turn_aware_path_value is not None
                    else None
                ),
                "turn_aware_next_path_player": turn_aware_next_path_player,
                "turn_aware_next_path_player_key": turn_aware_next_path_player_key,
                "turn_aware_continuation_path_value": (
                    round(turn_aware_continuation_path_value, 3)
                    if turn_aware_continuation_path_value is not None
                    else None
                ),
                "turn_aware_continuation_path_player": (
                    turn_aware_continuation_path_player
                ),
                "starter_deferral_evaluated": starter_deferral_evaluated,
                "deterministic_team_marginal": (
                    round(deterministic_team_marginal, 3)
                    if deterministic_team_marginal is not None
                    else None
                ),
                "deterministic_bench_marginal": (
                    round(deterministic_bench_marginal, 3)
                    if deterministic_bench_marginal is not None
                    else None
                ),
                "reserve_redundancy_cap": bool(
                    experimental_profile
                    and experimental_profile.get("reserve_redundancy_cap")
                ),
                "next_pick": next_pick,
                "next_pick_survival": round(survival, 6),
                "expected_fallback_player": fallback_player.name if fallback_player else "replacement",
                "expected_fallback_projected_points": round(
                    expected_fallback_points, 3
                ),
                "expected_fallback_vols": round(expected_fallback, 3),
                "vona": round(vona, 3),
                "roster_need": _roster_need_label(player, roster, roster_positions),
                "selection_basis": (
                    "selected_expert_overall_consensus"
                    if normalized_policy in {
                        "standard_expert_consensus",
                        "half_ppr_expert_consensus",
                        "expert_consensus",
                    }
                    else "consensus_anchored_team_model"
                    if consensus_band is not None
                    else "projection_team_model"
                ),
                "consensus_candidate_band": consensus_band,
                "final_score": round(score, 3),
            }
        )
    immediate_starter_paths = [
        float(row["two_pick_path_value"])
        for row in ranked
        if row["two_pick_path_value"] is not None
        and row["roster_need"] != "bench_depth"
    ]
    best_immediate_starter_path = max(immediate_starter_paths, default=None)
    for row in ranked:
        is_deferral = bool(
            row["two_pick_path_value"] is not None
            and row["roster_need"] == "bench_depth"
        )
        row["starter_deferred"] = is_deferral
        row["starter_deferral_effect"] = (
            round(float(row["two_pick_path_value"]) - best_immediate_starter_path, 3)
            if is_deferral and best_immediate_starter_path is not None
            else None
        )
    return sorted(
        ranked,
        key=lambda row: (
            -float(row["final_score"]),
            float(row["_player"].rank_score),
            float(row["adp"]),
        ),
    )


def _opponent_pick(
    available: list[Player],
    roster: list[Player],
    pick_no: int,
    round_no: int,
    rng: random.Random,
    round_position_rates: Mapping[int, Mapping[str, float]] | None = None,
    market_noise: float = 2.5,
) -> Player:
    candidates = [player for player in available if _can_draft(player, roster)] or available
    # Always keep the best available market values in view. Sorting by distance
    # from the current pick allowed an elite player who slipped to become less
    # likely to be drafted on every subsequent pick.
    candidates = sorted(
        candidates,
        key=lambda player: (player.acquisition_pick, player.rank_score),
    )[:24]
    best: tuple[float, Player] | None = None
    counts = Counter(player.position for player in roster)
    for player in candidates:
        # Conditional draft hazard given that the player is still available.
        # This preserves normal ADP variance while making overdue players more,
        # not less, urgent to the market.
        one_pick_survival = survival_probability(
            player.acquisition_pick, pick_no - 1, pick_no
        )
        hazard = max(1e-9, 1.0 - one_pick_survival)
        market_fit = 10.0 * math.log(hazard) + rng.gauss(0.0, market_noise)
        need = 0.0
        if player.position in ("RB", "WR") and counts[player.position] < 2:
            need += 5.0
        if player.position in ("QB", "TE") and counts[player.position] == 0 and round_no >= 7:
            need += 4.0
        tendency = 0.0
        rates = (round_position_rates or {}).get(round_no)
        if rates and player.position in MARKET_POSITION_PRIOR:
            observed_rate = max(0.01, float(rates.get(player.position, MARKET_POSITION_PRIOR[player.position])))
            tendency = 8.0 * math.log(observed_rate / MARKET_POSITION_PRIOR[player.position])
        score = market_fit + need + tendency
        if best is None or score > best[0]:
            best = (score, player)
    assert best is not None
    return best[1]


def _rollout_room_survival_probabilities(
    players: Iterable[Player],
    rosters: Mapping[int, list[Player]],
    roster_positions: Iterable[str],
    current_pick: int,
    next_user_pick: int | None,
    teams: int,
    position_pace_multipliers: Mapping[str, float] | None = None,
) -> dict[str, float]:
    opponent_picks = (
        list(range(current_pick + 1, next_user_pick))
        if next_user_pick is not None
        else []
    )
    player_list = list(players)
    if not opponent_picks:
        return {player.key: 1.0 for player in player_list}
    positions = tuple(roster_positions)
    dedicated = Counter(
        position for position in positions if position in SKILL_POSITIONS
    )

    def seat_factor(player: Player, roster: list[Player], round_no: int) -> float:
        counts = Counter(item.position for item in roster)
        if counts[player.position] >= POSITION_CAPS.get(player.position, 99):
            return 0.0
        if counts[player.position] < dedicated[player.position]:
            if player.position in {"QB", "TE"}:
                return 0.90 if round_no < 6 else 1.25
            return 1.20
        before = _filled_starter_slots(roster, positions)
        after = _filled_starter_slots([*roster, player], positions)
        if after > before:
            return 1.10
        return 0.85 if player.position in {"RB", "WR"} else 0.55

    result: dict[str, float] = {}
    for player in player_list:
        baseline = survival_probability(
            player.acquisition_pick,
            current_pick,
            int(next_user_pick),
        )
        one_pick_hazard = 1.0 - baseline ** (1.0 / len(opponent_picks))
        survival = 1.0
        for pick_no in opponent_picks:
            slot = snake_slot(pick_no, teams)
            round_no = ((pick_no - 1) // teams) + 1
            hazard = min(
                0.95,
                one_pick_hazard
                * seat_factor(player, list(rosters.get(slot) or []), round_no)
                * float((position_pace_multipliers or {}).get(player.position, 1.0)),
            )
            survival *= 1.0 - hazard
        result[player.key] = max(0.0, min(1.0, survival))
    return result


def bounded_multi_turn_rollout(
    available: Iterable[Player],
    rosters: Mapping[int, Iterable[Player]],
    forced_candidates: Iterable[Player],
    *,
    policy: str,
    current_pick: int,
    teams: int,
    draft_slot: int,
    roster_positions: Iterable[str],
    total_user_picks: int,
    replacement_baselines: Mapping[str, float],
    scenarios: int = 8,
    beam_width: int = 3,
    branch_width: int = 2,
    future_user_picks: int = 5,
    seed: int = 2026,
    market_noise: float = 2.5,
    position_run_sigma: float = 0.18,
    round_position_rates: Mapping[int, Mapping[str, float]] | None = None,
    position_pace_multipliers: Mapping[str, float] | None = None,
    rank_vorp_curve: RankVorpCurve | None = None,
    reconciliation_baselines: Mapping[float, Mapping[str, float]] | None = None,
    reconciliation_players: Mapping[float, Mapping[str, Player]] | None = None,
    evaluation_players_by_channel: Mapping[
        str, Mapping[str, Player]
    ] | None = None,
    evaluation_baselines_by_channel: Mapping[
        str, Mapping[str, float]
    ] | None = None,
) -> dict[str, Any]:
    """Shadow leading picks through two bounded opponent-contested intervals.

    Each forced candidate sees the same scenario seed. User decisions branch
    only over the leading policy rows and the beam is pruned after every user
    selection. The function is intentionally independent of live ordering.
    """

    if scenarios < 1 or beam_width < 1 or branch_width < 1:
        raise ValueError("Rollout scenarios, beam width, and branch width must be positive")
    if future_user_picks < 0:
        raise ValueError("Rollout future user picks cannot be negative")
    if position_run_sigma < 0:
        raise ValueError("Rollout position-run sigma cannot be negative")
    positions = tuple(roster_positions)
    initial_available = [
        player for player in available if player.position in SKILL_POSITIONS
    ]
    initial_rosters = {
        slot: list(rosters.get(slot) or []) for slot in range(1, teams + 1)
    }
    candidates = [
        player
        for player in forced_candidates
        if player in initial_available
        and _can_draft(player, initial_rosters[draft_slot])
    ]
    remaining_after_forced = max(
        0,
        total_user_picks - len(initial_rosters[draft_slot]) - 1,
    )
    user_picks_to_simulate = min(future_user_picks, remaining_after_forced)
    target_pick = current_pick
    for _ in range(user_picks_to_simulate):
        next_pick = next_pick_for_slot(target_pick, draft_slot, teams)
        if next_pick is None:
            break
        target_pick = next_pick

    channel_players = dict(evaluation_players_by_channel or {})
    if not channel_players:
        channel_players = {
            "primary": {player.key: player for player in initial_available}
        }
    channel_baselines = dict(evaluation_baselines_by_channel or {})
    if not channel_baselines:
        channel_baselines = {"primary": dict(replacement_baselines)}
    channels = tuple(channel_players)
    if "primary" not in channels:
        raise ValueError("Rollout evaluation channels must include primary")
    if any(channel not in channel_baselines for channel in channels):
        raise ValueError("Every rollout evaluation channel requires replacement baselines")

    def endpoint_scores(user_roster: Iterable[Player]) -> dict[str, float]:
        values: dict[str, float] = {}
        for channel in channels:
            lookup = channel_players[channel]
            evaluated = [lookup.get(player.key, player) for player in user_roster]
            values[channel] = _deterministic_pick_roster_value(
                evaluated,
                positions,
                channel_baselines[channel],
                0.30,
            )[0]
        return values

    by_candidate: dict[str, list[dict[str, Any]]] = {
        candidate.key: [] for candidate in candidates
    }
    pruned_path_count = 0
    for scenario in range(scenarios):
        scenario_seed = seed + scenario
        run_rng = random.Random(scenario_seed ^ 0x5A17)
        position_shocks = {
            position: math.exp(run_rng.gauss(0.0, position_run_sigma))
            for position in SKILL_POSITIONS
        }
        scenario_round_rates: dict[int, dict[str, float]] = {}
        for round_no in range(1, ((target_pick - 1) // teams) + 2):
            base_rates = (round_position_rates or {}).get(
                round_no,
                MARKET_POSITION_PRIOR,
            )
            raw_rates = {
                position: max(
                    0.001,
                    float(base_rates.get(position, MARKET_POSITION_PRIOR[position]))
                    * position_shocks[position],
                )
                for position in SKILL_POSITIONS
            }
            total_rate = sum(raw_rates.values())
            scenario_round_rates[round_no] = {
                position: rate / total_rate
                for position, rate in raw_rates.items()
            }
        for candidate in candidates:
            available_after = list(initial_available)
            available_after.remove(candidate)
            rosters_after = {
                slot: list(players) for slot, players in initial_rosters.items()
            }
            rosters_after[draft_slot].append(candidate)
            rng = random.Random(scenario_seed)
            beams = [
                {
                    "available": available_after,
                    "rosters": rosters_after,
                    "path": [candidate.name],
                    "path_positions": [candidate.position],
                    "rng_state": rng.getstate(),
                }
            ]
            for pick_no in range(current_pick + 1, target_pick + 1):
                slot = snake_slot(pick_no, teams)
                round_no = ((pick_no - 1) // teams) + 1
                advanced: list[dict[str, Any]] = []
                for beam in beams:
                    beam_available = list(beam["available"])
                    beam_rosters = {
                        seat: list(players)
                        for seat, players in beam["rosters"].items()
                    }
                    if not beam_available:
                        advanced.append(beam)
                        continue
                    if slot == draft_slot:
                        next_user_pick = next_pick_for_slot(
                            pick_no,
                            draft_slot,
                            teams,
                        )
                        survival_overrides = _rollout_room_survival_probabilities(
                            beam_available,
                            beam_rosters,
                            positions,
                            pick_no,
                            next_user_pick,
                            teams,
                            position_pace_multipliers,
                        )
                        ranked = rank_user_candidates(
                            beam_available,
                            beam_rosters[slot],
                            policy,
                            pick_no,
                            round_no,
                            teams,
                            draft_slot,
                            positions,
                            total_user_picks,
                            replacement_baselines,
                            next_pick_survival_overrides=survival_overrides,
                            rank_vorp_curve=rank_vorp_curve,
                            reconciliation_baselines=reconciliation_baselines,
                            reconciliation_players=reconciliation_players,
                        )
                        for row in ranked[:branch_width]:
                            chosen = row["_player"]
                            next_available = list(beam_available)
                            next_available.remove(chosen)
                            next_rosters = {
                                seat: list(players)
                                for seat, players in beam_rosters.items()
                            }
                            next_rosters[slot].append(chosen)
                            advanced.append(
                                {
                                    "available": next_available,
                                    "rosters": next_rosters,
                                    "path": [*beam["path"], chosen.name],
                                    "path_positions": [
                                        *beam["path_positions"],
                                        chosen.position,
                                    ],
                                    "rng_state": beam["rng_state"],
                                }
                            )
                    else:
                        branch_rng = random.Random()
                        branch_rng.setstate(beam["rng_state"])
                        chosen = _opponent_pick(
                            beam_available,
                            beam_rosters[slot],
                            pick_no,
                            round_no,
                            branch_rng,
                            round_position_rates=scenario_round_rates,
                            market_noise=market_noise,
                        )
                        beam_available.remove(chosen)
                        beam_rosters[slot].append(chosen)
                        advanced.append(
                            {
                                "available": beam_available,
                                "rosters": beam_rosters,
                                "path": list(beam["path"]),
                                "path_positions": list(beam["path_positions"]),
                                "rng_state": branch_rng.getstate(),
                            }
                        )
                if slot == draft_slot and len(advanced) > beam_width:
                    pruned_path_count += len(advanced) - beam_width
                    advanced.sort(
                        key=lambda beam: (
                            -endpoint_scores(beam["rosters"][draft_slot])["primary"],
                            tuple(beam["path"]),
                        )
                    )
                    advanced = advanced[:beam_width]
                beams = advanced
            best = max(
                beams,
                key=lambda beam: (
                    endpoint_scores(beam["rosters"][draft_slot])["primary"],
                    tuple(reversed(beam["path"])),
                ),
            )
            by_candidate[candidate.key].append(
                {
                    "scenario": scenario,
                    "scores": endpoint_scores(best["rosters"][draft_slot]),
                    "path": list(best["path"]),
                    "position_counts": dict(
                        Counter(
                            player.position
                            for player in best["rosters"][draft_slot]
                        )
                    ),
                }
            )

    scenario_best = {
        (scenario, channel): max(
            by_candidate[candidate.key][scenario]["scores"][channel]
            for candidate in candidates
        )
        for scenario in range(scenarios)
        for channel in channels
    } if candidates else {}
    summaries = []
    for candidate in candidates:
        records = by_candidate[candidate.key]
        channel_summary = {}
        for channel in channels:
            scores = [record["scores"][channel] for record in records]
            ordered = sorted(scores)
            regrets = [
                scenario_best[(record["scenario"], channel)]
                - record["scores"][channel]
                for record in records
            ]
            channel_summary[channel] = {
                "mean": round(fmean(scores), 3),
                "p10": round(ordered[int(0.10 * (len(ordered) - 1))], 3),
                "mean_regret": round(fmean(regrets), 3),
            }
        representative = max(
            records,
            key=lambda record: record["scores"]["primary"],
        )
        summaries.append(
            {
                "player_key": candidate.key,
                "player_name": candidate.name,
                "position": candidate.position,
                "channels": channel_summary,
                "representative_path": representative["path"],
                "representative_position_counts": dict(
                    sorted(representative["position_counts"].items())
                ),
            }
        )
    summaries.sort(
        key=lambda row: (
            -float(row["channels"]["primary"]["mean"]),
            row["player_name"],
        )
    )
    return {
        "status": "shadow_only",
        "method": "bounded_common_random_number_beam_rollout",
        "current_pick": current_pick,
        "target_pick": target_pick,
        "scenarios": scenarios,
        "beam_width": beam_width,
        "branch_width": branch_width,
        "forced_candidate_count": len(candidates),
        "future_user_picks": user_picks_to_simulate,
        "seed": seed,
        "position_run_sigma": position_run_sigma,
        "pruned_path_count": pruned_path_count,
        "position_caps": dict(POSITION_CAPS),
        "channels": list(channels),
        "candidates": summaries,
    }


def opponent_position_stress_rates(
    profile: str,
) -> dict[int, dict[str, float]]:
    """Return explicit, synthetic position-demand rates for acquisition stress tests.

    These profiles change only simulated opponent acquisition timing. They are
    not league history and must never be passed to the live watcher.
    """

    if profile not in OPPONENT_POSITION_STRESS_PROFILES:
        raise ValueError(
            f"Unknown opponent position profile {profile!r}; expected one of "
            f"{', '.join(OPPONENT_POSITION_STRESS_PROFILES)}"
        )
    if profile == "raw":
        return {}
    if profile == "early_rb":
        rates = {"QB": 0.10, "RB": 0.55, "WR": 0.27, "TE": 0.08}
        return {round_no: dict(rates) for round_no in range(1, 6)}
    if profile == "early_wr":
        rates = {"QB": 0.10, "RB": 0.27, "WR": 0.55, "TE": 0.08}
        return {round_no: dict(rates) for round_no in range(1, 6)}
    rates = {"QB": 0.25, "RB": 0.25, "WR": 0.25, "TE": 0.25}
    return {round_no: dict(rates) for round_no in range(5, 10)}


def _user_pick(
    available: list[Player],
    roster: list[Player],
    strategy: str,
    pick_no: int,
    round_no: int,
    teams: int,
    *,
    draft_slot: int | None = None,
    roster_positions: Iterable[str] = (),
    total_user_picks: int = 30,
    replacement_baselines: Mapping[str, float] | None = None,
    bench_before_starters: int | None = None,
) -> Player:
    slot = draft_slot or snake_slot(pick_no, teams)
    ranked = rank_user_candidates(
        available,
        roster,
        strategy,
        pick_no,
        round_no,
        teams,
        slot,
        roster_positions,
        total_user_picks,
        replacement_baselines or {},
        bench_before_starters,
    )
    return ranked[0]["_player"]


def compare_strategies(
    board: Iterable[Mapping[str, Any]],
    teams: int,
    draft_slot: int,
    roster_positions: Iterable[str],
    rounds: int,
    trials: int = 1000,
    seed: int = 2026,
    strategies: Iterable[str] = ("scenario_safe", "scenario_calibrated"),
    round_position_rates: Mapping[int, Mapping[str, float]] | None = None,
    include_trace: bool = False,
    include_special_teams: bool = False,
    availability_rates: Iterable[float] = (0.05, 0.10, 0.15),
    availability_samples: int = 48,
    replacement_aware_evaluation: bool = False,
    bench_weights: Iterable[float] = (0.10, 0.20, 0.30),
    rank_weights: Iterable[float] = (0.0, 0.5, 1.0),
    acquisition_history: HistoricalPositionCurves | None = None,
    history_weight: float | None = None,
    ballot_preferences: Mapping[tuple[str, str], float] | None = None,
    include_trial_records: bool = False,
    include_draft_pick_records: bool = False,
    opponent_market_noise: float = 2.5,
    opponent_position_profile: str = "raw",
) -> list[dict[str, Any]]:
    strategies = tuple(strategies)
    bench_weights = tuple(float(weight) for weight in bench_weights)
    if not bench_weights:
        raise ValueError("At least one bench weight is required")
    if any(not 0.0 <= weight <= 1.0 for weight in bench_weights):
        raise ValueError("Bench weights must be between 0 and 1")
    rank_weights = tuple(dict.fromkeys(float(weight) for weight in rank_weights))
    if not rank_weights:
        raise ValueError("At least one rank-reconciliation weight is required")
    if any(not 0.0 <= weight <= 1.0 for weight in rank_weights):
        raise ValueError("Rank-reconciliation weights must be between 0 and 1")
    if 0.0 not in rank_weights:
        rank_weights = (0.0, *rank_weights)
    if history_weight is not None and not 0.0 <= history_weight <= 1.0:
        raise ValueError("Acquisition-history weight must be between 0 and 1")
    if not math.isfinite(opponent_market_noise) or opponent_market_noise < 0.0:
        raise ValueError("Opponent market noise must be a finite non-negative number")
    profile_rates = opponent_position_stress_rates(opponent_position_profile)
    if history_weight is not None and profile_rates:
        raise ValueError(
            "Opponent position stress cannot be combined with acquisition history"
        )
    acquisition_metadata = acquisition_adp_metadata(
        acquisition_history, history_weight
    )
    effective_round_position_rates = (
        None
        if history_weight is not None
        else profile_rates or round_position_rates
    )
    acquisition_metadata["round_position_rates_applied"] = bool(
        effective_round_position_rates
    )
    acquisition_metadata["opponent_market_noise"] = float(opponent_market_noise)
    acquisition_metadata["opponent_position_profile"] = opponent_position_profile
    acquisition_metadata["opponent_position_rates"] = {
        str(round_no): {
            position: float(rate)
            for position, rate in sorted(rates.items())
        }
        for round_no, rates in sorted((effective_round_position_rates or {}).items())
    }
    replacement_aware_evaluation = replacement_aware_evaluation or any(
        bool(
            (profile := _experimental_profile(strategy, draft_slot))
            and profile.get("replacement_aware")
        )
        for strategy in strategies
    )
    raw_players = [
        Player.from_mapping(row)
        for row in board
        if str(row.get("position")).upper() in (*DRAFT_POSITIONS, "DEF")
    ]
    acquisition_players = (
        apply_acquisition_adp(
            raw_players,
            acquisition_history,
            float(history_weight),
        )
        if history_weight is not None
        else raw_players
    )
    all_players = expert_ordered_projection_players(acquisition_players)
    skill_players = [player for player in all_players if player.position in SKILL_POSITIONS]
    if len(skill_players) < teams * min(rounds, 8):
        raise ValueError("The board does not contain enough players for a meaningful simulation")
    special_rounds = sum(1 for position in roster_positions if position in ("K", "DEF", "DST"))
    skill_rounds = max(1, rounds - special_rounds)
    simulation_rounds = rounds if include_special_teams else skill_rounds
    players = all_players if include_special_teams else skill_players
    replacement_baselines = market_replacement_baselines(skill_players, teams, skill_rounds)
    rank_vorp_curve = fit_rank_vorp_curve(
        skill_players,
        replacement_baselines,
        maximum_rank=teams * skill_rounds,
    )
    adjusted_players_by_rank_weight = {
        rank_weight: {
            player.key: player
            for player in rank_adjusted_players(
                players,
                rank_vorp_curve,
                rank_weight,
                replacement_baselines,
            )
        }
        for rank_weight in rank_weights
    }
    adjusted_replacement_baselines = {
        rank_weight: market_replacement_baselines(
            [
                adjusted_players_by_rank_weight[rank_weight][player.key]
                for player in skill_players
            ],
            teams,
            skill_rounds,
        )
        for rank_weight in rank_weights
    }
    upside_signals = _upside_signals(skill_players)
    availability_rates = tuple(float(rate) for rate in availability_rates)
    results: list[SimulationResult] = []
    for strategy in strategies:
        result = SimulationResult(strategy)
        strategy_profile = _experimental_profile(strategy, draft_slot)
        construction_bench_cap = (
            strategy_profile.get("bench_before_starters")
            if strategy_profile
            else None
        )
        use_late_round_plan = bool(
            strategy_profile and strategy_profile.get("late_round_plan")
        )
        use_final_sleeper = bool(
            strategy_profile and strategy_profile.get("final_sleeper")
        )
        specialist_plan = dict(
            (strategy_profile or {}).get("specialist_plan") or {}
        )
        offline_specialist_gate = dict(
            (strategy_profile or {}).get("offline_specialist_gate") or {}
        )
        for trial in range(trials):
            # Common random numbers: every policy faces the same opponent-randomness stream.
            rng = random.Random(seed + trial)
            available = list(players)
            rosters: dict[int, list[Player]] = defaultdict(list)
            picks: list[dict[str, Any]] = []
            decisions: list[dict[str, Any]] = []
            trial_user_picks: list[dict[str, Any]] = []
            for pick_no in range(1, teams * simulation_rounds + 1):
                slot = snake_slot(pick_no, teams)
                round_no = ((pick_no - 1) // teams) + 1
                if slot == draft_slot:
                    special_position = None
                    special_candidate_keys: set[str] | None = None
                    pick_role = "value"
                    qb_availability = None
                    missing_specials = [
                        position
                        for position in ("DST", "K")
                        if not any(player.position == position for player in rosters[slot])
                    ]
                    if include_special_teams and special_rounds >= 2 and specialist_plan:
                        planned_role = specialist_plan.get(round_no)
                        if planned_role in {"K", "DST"}:
                            special_position = planned_role
                            pick_role = (
                                "defense" if special_position == "DST" else "kicker"
                            )
                        elif planned_role == "sleeper":
                            pick_role = "sleeper"
                    elif include_special_teams and special_rounds >= 2 and use_late_round_plan:
                        if round_no == rounds - 2:
                            special_position = "DST"
                            pick_role = "defense"
                        elif round_no == rounds - 1:
                            special_position = "K"
                            pick_role = "kicker"
                        elif round_no == rounds:
                            pick_role = "sleeper"
                    elif include_special_teams and special_rounds >= 2 and missing_specials:
                        gate_mode = str(offline_specialist_gate.get("mode") or "")
                        if (
                            gate_mode == "top3_dst_guard"
                            and "DST" in missing_specials
                        ):
                            eligible_defenses = _top3_dst_guard_candidates(
                                available,
                                rosters[slot],
                                pick_no=pick_no,
                                round_no=round_no,
                                teams=teams,
                                draft_slot=draft_slot,
                                simulation_rounds=simulation_rounds,
                                roster_positions=roster_positions,
                                minimum_round=int(
                                    offline_specialist_gate["minimum_round"]
                                ),
                                maximum_next_turn_survival=float(
                                    offline_specialist_gate[
                                        "maximum_next_turn_survival"
                                    ]
                                ),
                                maximum_user_dst_rank=int(
                                    offline_specialist_gate["maximum_user_dst_rank"]
                                ),
                            )
                            if eligible_defenses:
                                special_position = "DST"
                                special_candidate_keys = {
                                    player.key for player in eligible_defenses
                                }
                                pick_role = "defense_top3_guard"

                        remaining_user_picks = simulation_rounds - round_no + 1
                        must_take_special = remaining_user_picks <= len(missing_specials)
                        if special_position is None:
                            market_options: list[tuple[float, str]] = []
                            for position in missing_specials:
                                position_players = [
                                    player
                                    for player in available
                                    if player.position == position
                                    and _can_draft(player, rosters[slot])
                                ]
                                if position_players:
                                    market_options.append(
                                        (
                                            min(
                                                player.acquisition_pick
                                                for player in position_players
                                            ),
                                            position,
                                        )
                                    )
                            if gate_mode in {
                                "live_specialist_gate",
                                "top3_dst_guard",
                            }:
                                if must_take_special and market_options:
                                    if set(missing_specials) == {"DST", "K"}:
                                        best_user_dst_rank = min(
                                            (
                                                defense_draft_rank(player.team)
                                                for player in available
                                                if player.position == "DST"
                                                and defense_draft_rank(player.team)
                                                is not None
                                            ),
                                            default=999,
                                        )
                                        special_position = (
                                            "DST"
                                            if best_user_dst_rank <= 3
                                            else "K"
                                        )
                                    else:
                                        special_position = missing_specials[0]
                            else:
                                overdue = [
                                    option
                                    for option in market_options
                                    if option[0] <= pick_no
                                ]
                                if market_options and (must_take_special or overdue):
                                    special_position = min(
                                        overdue or market_options,
                                        key=lambda option: option[0],
                                    )[1]
                            if special_position is not None:
                                pick_role = (
                                    "defense"
                                    if special_position == "DST"
                                    else "kicker"
                                )
                    elif not include_special_teams and use_final_sleeper and round_no == simulation_rounds:
                        pick_role = "sleeper"

                    if special_position:
                        special_candidates = sorted(
                            (
                                player
                                for player in available
                                if player.position == special_position
                                and _can_draft(player, rosters[slot])
                                and (
                                    special_candidate_keys is None
                                    or player.key in special_candidate_keys
                                )
                            ),
                            key=(
                                defense_draft_sort_key
                                if special_position == "DST"
                                else lambda player: (player.rank_score, player.adp)
                            ),
                        )
                        if not special_candidates:
                            raise ValueError(f"No {special_position} candidate remained for the late-round plan")
                        chosen = special_candidates[0]
                        ranked = [
                            {
                                "_player": player,
                                "player_name": player.name,
                                "position": player.position,
                                "adp": round(player.adp, 3),
                                "expert_rank": round(player.rank_score, 3),
                                "user_dst_rank": (
                                    defense_draft_rank(player.team)
                                    if player.position == "DST"
                                    else None
                                ),
                                "roster_need": f"open_{special_position.lower()}_starter",
                                "final_score": round(
                                    -float(
                                        defense_draft_rank(player.team)
                                        if player.position == "DST"
                                        and defense_draft_rank(player.team) is not None
                                        else player.rank_score
                                    ),
                                    3,
                                ),
                            }
                            for player in special_candidates[:5]
                        ]
                    else:
                        skill_available = [
                            player for player in available if player.position in SKILL_POSITIONS
                        ]
                        if include_trace and trial == 0:
                            next_user_pick = (
                                next_pick_for_slot(
                                    pick_no, draft_slot, teams, simulation_rounds
                                )
                                or pick_no + teams
                            )
                            current_qbs = sorted(
                                (
                                    player
                                    for player in skill_available
                                    if player.position == "QB"
                                    and player.projected_points > 0.0
                                ),
                                key=lambda player: (
                                    player.acquisition_pick,
                                    player.rank_score,
                                ),
                            )
                            expected_qb = _expected_next_by_position(
                                skill_available,
                                pick_no,
                                next_user_pick,
                                replacement_baselines,
                            ).get("QB", {})
                            expected_qb_player = expected_qb.get("player")
                            qb_availability = {
                                "current_pick": pick_no,
                                "next_pick": next_user_pick,
                                "current_market_qbs": [
                                    {
                                        "player_name": player.name,
                                        "position_slot": player.acquisition_position_slot,
                                        "raw_adp": round(player.adp, 3),
                                        "acquisition_adp": round(
                                            player.acquisition_pick, 3
                                        ),
                                    }
                                    for player in current_qbs[:5]
                                ],
                                "expected_next_qb": (
                                    {
                                        "player_name": expected_qb_player.name,
                                        "position_slot": (
                                            expected_qb_player.acquisition_position_slot
                                        ),
                                        "raw_adp": round(
                                            expected_qb_player.adp, 3
                                        ),
                                        "acquisition_adp": round(
                                            expected_qb_player.acquisition_pick, 3
                                        ),
                                    }
                                    if expected_qb_player is not None
                                    else None
                                ),
                                "no_draftable_qb_probability": round(
                                    float(expected_qb.get("no_player_probability") or 0.0),
                                    6,
                                ),
                            }
                        if pick_role == "sleeper":
                            projected = [
                                player
                                for player in skill_available
                                if player.position in ("RB", "WR")
                                and player.projected_points > 0.0
                            ]
                            if projected:
                                skill_available = projected
                        selection_strategy = (
                            "vorp"
                            if pick_role == "sleeper"
                            else "half_ppr_reconciled_horizon_guard"
                            if offline_specialist_gate
                            else strategy
                        )
                        ranked = rank_user_candidates(
                            skill_available,
                            rosters[slot],
                            selection_strategy,
                            pick_no,
                            round_no,
                            teams,
                            draft_slot,
                            roster_positions,
                            skill_rounds,
                            replacement_baselines,
                            construction_bench_cap,
                            availability_rates,
                            upside_signals,
                            rank_vorp_curve=rank_vorp_curve,
                            reconciliation_baselines=adjusted_replacement_baselines,
                            ballot_preferences=ballot_preferences,
                            reconciliation_players=adjusted_players_by_rank_weight,
                        )
                        chosen = ranked[0]["_player"]
                        if ranked[0].get("near_tie_scarcity_promoted"):
                            result.near_tie_scarcity_promotions += 1
                    if include_trial_records:
                        trial_user_picks.append(
                            {
                                "pick_no": pick_no,
                                "round": round_no,
                                "player_name": chosen.name,
                                "position": chosen.position,
                                "adp": round(chosen.adp, 3),
                                "acquisition_adp": round(
                                    chosen.acquisition_pick, 3
                                ),
                                "user_dst_rank": (
                                    defense_draft_rank(chosen.team)
                                    if chosen.position == "DST"
                                    else None
                                ),
                                "pick_role": pick_role,
                                "final_score": (
                                    round(float(ranked[0]["final_score"]), 3)
                                    if ranked and ranked[0].get("final_score") is not None
                                    else None
                                ),
                            }
                        )
                    if include_trace and trial == 0:
                        decisions.append(
                            {
                                "pick_no": pick_no,
                                "round": round_no,
                                "pick_role": pick_role,
                                "selected": {
                                    key: value for key, value in ranked[0].items() if key != "_player"
                                },
                                "top_candidates": [
                                    {key: value for key, value in row.items() if key != "_player"}
                                    for row in ranked[:5]
                                ],
                                "qb_availability": qb_availability,
                            }
                        )
                else:
                    chosen = _opponent_pick(
                        available,
                        rosters[slot],
                        pick_no,
                        round_no,
                        rng,
                        round_position_rates=effective_round_position_rates,
                        market_noise=opponent_market_noise,
                    )
                rosters[slot].append(chosen)
                available.remove(chosen)
                if include_draft_pick_records or (include_trace and trial == 0):
                    picks.append(
                        {
                            "pick_no": pick_no,
                            "round": round_no,
                            "draft_slot": slot,
                            "is_user_pick": slot == draft_slot,
                            "player_key": chosen.key,
                            "player_name": chosen.name,
                            "position": chosen.position,
                            "adp": round(chosen.adp, 3),
                            "acquisition_adp": round(chosen.acquisition_pick, 3),
                            "acquisition_position_slot": (
                                chosen.acquisition_position_slot
                            ),
                        }
                    )
            user_roster = rosters[draft_slot]
            first_qb = next(
                (
                    (round_index, player)
                    for round_index, player in enumerate(user_roster, start=1)
                    if player.position == "QB"
                ),
                None,
            )
            if first_qb is not None:
                first_qb_round, first_qb_player = first_qb
                result.first_qb_selections.append(
                    {
                        "round": first_qb_round,
                        "player_name": first_qb_player.name,
                        "position_slot": first_qb_player.acquisition_position_slot,
                        "raw_adp": first_qb_player.adp,
                        "acquisition_adp": first_qb_player.acquisition_pick,
                    }
                )
            room_strength_by_rank_weight: dict[
                float, dict[int, dict[str, float]]
            ] = {}
            draft_scores_by_rank_weight: dict[float, dict[float, float]] = {}
            weekly_use_by_rank_weight: dict[float, dict[str, Any]] = {}
            for rank_weight in rank_weights:
                adjusted_lookup = adjusted_players_by_rank_weight[rank_weight]
                rank_baselines = adjusted_replacement_baselines[rank_weight]
                room_strength = {
                    slot: deterministic_roster_strength(
                        [
                            adjusted_lookup.get(player.key, player)
                            for player in slot_roster
                        ],
                        roster_positions,
                        rank_baselines,
                    )
                    for slot, slot_roster in rosters.items()
                }
                room_strength_by_rank_weight[rank_weight] = room_strength
                adjusted_user_strength = room_strength[draft_slot]
                weekly_use = weekly_use_roster_strength(
                    [
                        adjusted_lookup.get(player.key, player)
                        for player in user_roster
                    ],
                    roster_positions,
                    rank_baselines,
                )
                weekly_use_by_rank_weight[rank_weight] = weekly_use
                for level, stress in weekly_use["stress_levels"].items():
                    result.weekly_use_scores.setdefault(
                        rank_weight, {}
                    ).setdefault(level, []).append(
                        float(stress["mean_full_lineup_score"])
                    )
                    result.weekly_use_reserve_lifts.setdefault(
                        rank_weight, {}
                    ).setdefault(level, []).append(
                        float(stress["mean_reserve_lift_above_waivers"])
                    )
                lineup_z = _relative_z_score(
                    adjusted_user_strength["bye_adjusted_lineup_score"],
                    (
                        strength["bye_adjusted_lineup_score"]
                        for strength in room_strength.values()
                    ),
                )
                bench_z = _relative_z_score(
                    adjusted_user_strength["usable_bench_vorp"],
                    (
                        strength["usable_bench_vorp"]
                        for strength in room_strength.values()
                    ),
                )
                rank_draft_scores = {
                    weight: (1.0 - weight) * lineup_z + weight * bench_z
                    for weight in bench_weights
                }
                draft_scores_by_rank_weight[rank_weight] = rank_draft_scores
                result.reconciled_lineup_scores.setdefault(rank_weight, []).append(
                    adjusted_user_strength["bye_adjusted_lineup_score"]
                )
                result.reconciled_usable_bench_scores.setdefault(
                    rank_weight, []
                ).append(
                    adjusted_user_strength["usable_bench_vorp"]
                )
                for bench_weight, draft_score in rank_draft_scores.items():
                    result.reconciled_draft_scores.setdefault(
                        rank_weight, {}
                    ).setdefault(bench_weight, []).append(draft_score)

            room_strength = room_strength_by_rank_weight[0.0]
            user_strength = room_strength[draft_slot]
            draft_scores = draft_scores_by_rank_weight[0.0]
            result.bye_adjusted_scores.append(
                user_strength["bye_adjusted_lineup_score"]
            )
            result.base_lineup_scores.append(user_strength["base_lineup_score"])
            result.bye_coverage_scores.append(user_strength["bye_coverage_points"])
            result.bench_vorp_scores.append(user_strength["bench_vorp"])
            result.usable_bench_vorp_scores.append(
                user_strength["usable_bench_vorp"]
            )
            result.total_roster_vorp_scores.append(user_strength["total_roster_vorp"])
            for weight, draft_score in draft_scores.items():
                result.draft_scores_by_bench_weight.setdefault(weight, []).append(draft_score)
            scenario_score, scenario_scores = expected_roster_score(
                user_roster,
                roster_positions,
                availability_rates=availability_rates,
                samples_per_rate=availability_samples,
                scenario_seed=seed + trial,
                replacement_baselines=(
                    replacement_baselines if replacement_aware_evaluation else None
                ),
            )
            result.scores.append(scenario_score)
            result.roster_records.append(
                {
                    "score": round(scenario_score, 3),
                    "seed": seed + trial,
                    "base_starter_score": round(roster_score(user_roster, roster_positions), 3),
                    "replacement_aware_base_score": round(
                        roster_score(
                            user_roster,
                            roster_positions,
                            replacement_baselines,
                        ),
                        3,
                    ),
                    "bye_adjusted_lineup_score": round(
                        user_strength["bye_adjusted_lineup_score"], 3
                    ),
                    "bye_coverage_points": round(
                        user_strength["bye_coverage_points"], 3
                    ),
                    "bench_vorp": round(user_strength["bench_vorp"], 3),
                    "usable_bench_vorp": round(
                        user_strength["usable_bench_vorp"], 3
                    ),
                    "total_roster_vorp": round(
                        user_strength["total_roster_vorp"], 3
                    ),
                    "draft_scores": {
                        f"{weight:.2f}": round(score, 4)
                        for weight, score in draft_scores.items()
                    },
                    "rank_reconciled_strength": {
                        f"{rank_weight:.2f}": {
                            "bye_adjusted_lineup_score": round(
                                room_strength_by_rank_weight[rank_weight][draft_slot][
                                    "bye_adjusted_lineup_score"
                                ],
                                3,
                            ),
                            "bench_vorp": round(
                                room_strength_by_rank_weight[rank_weight][draft_slot][
                                    "bench_vorp"
                                ],
                                3,
                            ),
                            "usable_bench_vorp": round(
                                room_strength_by_rank_weight[rank_weight][draft_slot][
                                    "usable_bench_vorp"
                                ],
                                3,
                            ),
                            "draft_scores": {
                                f"{bench_weight:.2f}": round(score, 4)
                                for bench_weight, score in draft_scores_by_rank_weight[
                                    rank_weight
                                ].items()
                            },
                        }
                        for rank_weight in rank_weights
                    },
                    "weekly_use": {
                        f"{rank_weight:.2f}": weekly_use_by_rank_weight[rank_weight]
                        for rank_weight in rank_weights
                    },
                    "players": [
                        {
                            "player_name": player.name,
                            "position": player.position,
                            "raw_projected_points": round(
                                player.source_projected_points, 3
                            ),
                            "projected_points": round(
                                player.source_projected_points, 3
                            ),
                            "position_curve_projected_points": round(
                                player.projected_points, 3
                            ),
                            "rank_adjusted_projected_points": {
                                f"{rank_weight:.2f}": round(
                                    adjusted_players_by_rank_weight[rank_weight]
                                    .get(player.key, player)
                                    .projected_points,
                                    3,
                                )
                                for rank_weight in rank_weights
                            },
                            "adp": round(player.adp, 3),
                            "acquisition_adp": round(player.acquisition_pick, 3),
                            "acquisition_position_slot": (
                                player.acquisition_position_slot
                            ),
                        }
                        for player in user_roster
                    ],
                    "user_picks": trial_user_picks,
                    "draft_picks": picks if include_draft_pick_records else [],
                }
            )
            result.position_counts.update(player.position for player in user_roster)
            result.special_rank_totals.update(
                {
                    player.position: player.rank_score
                    for player in user_roster
                    if player.position in ("K", "DST")
                }
            )
            if user_roster:
                result.first_picks.update([user_roster[0].name])
            if include_trace and trial == 0:
                result.trace = {
                    "seed": seed,
                    "draft_slot": draft_slot,
                    "acquisition_adp": acquisition_metadata,
                    "replacement_baselines": {
                        position: round(value, 3) for position, value in replacement_baselines.items()
                    },
                    "projection_value_model": {
                        "method": "expert_ordered_positional_projection_curve",
                        "raw_projections_preserved": True,
                        "player_identity_used_for_projection_order": False,
                    },
                    "picks": picks,
                    "user_decisions": decisions,
                    "final_roster": [
                        {
                            "player_name": player.name,
                            "position": player.position,
                            "raw_projected_points": round(
                                player.source_projected_points, 3
                            ),
                            "projected_points": round(
                                player.source_projected_points, 3
                            ),
                            "position_curve_projected_points": round(
                                player.projected_points, 3
                            ),
                            "adp": round(player.adp, 3),
                            "acquisition_adp": round(player.acquisition_pick, 3),
                            "acquisition_position_slot": (
                                player.acquisition_position_slot
                            ),
                            "vols": round(player.vbd, 3),
                            "vorp": round(
                                player.projected_points
                                - float(replacement_baselines.get(player.position) or 0.0),
                                3,
                            ),
                        }
                        for player in user_roster
                    ],
                    "roster_score": round(result.scores[-1], 3),
                    "base_starter_score": round(
                        roster_score(user_roster, roster_positions), 3
                    ),
                    "replacement_aware_base_score": round(
                        roster_score(
                            user_roster,
                            roster_positions,
                            replacement_baselines,
                        ),
                        3,
                    ),
                    "availability_sensitivity_scores": {
                        rate: round(value, 3) for rate, value in scenario_scores.items()
                    },
                    "availability_samples_per_rate": availability_samples,
                    "replacement_aware_evaluation": replacement_aware_evaluation,
                    "deterministic_roster_strength": {
                        key: round(value, 3) for key, value in user_strength.items()
                    },
                    "draft_scores": {
                        f"{weight:.2f}": round(score, 4)
                        for weight, score in draft_scores.items()
                    },
                    "rank_reconciliation": {
                        "weights": list(rank_weights),
                        "curve": {
                            "observation_count": rank_vorp_curve.observation_count,
                            "block_count": rank_vorp_curve.block_count,
                            "sample_values": {
                                str(rank): round(rank_vorp_curve.value(rank), 3)
                                for rank in (1, 12, 24, 60, 120, 180)
                            },
                        },
                        "strengths": {
                            f"{rank_weight:.2f}": {
                                key: round(value, 3)
                                for key, value in room_strength_by_rank_weight[
                                    rank_weight
                                ][draft_slot].items()
                            }
                            for rank_weight in rank_weights
                        },
                        "draft_scores": {
                            f"{rank_weight:.2f}": {
                                f"{bench_weight:.2f}": round(score, 4)
                                for bench_weight, score in draft_scores_by_rank_weight[
                                    rank_weight
                                ].items()
                            }
                            for rank_weight in rank_weights
                        },
                    },
                    "bench_weights": list(bench_weights),
                    "starter_slots_filled": _filled_starter_slots(user_roster, roster_positions),
                    "starter_slot_count": len(_starter_eligibility(roster_positions)),
                    "strategy_profile": strategy_profile or {
                        "first_round_vols": False,
                        "bench_before_starters": None,
                        "late_round_plan": False,
                        "vona_weight": None,
                        "vona_only": False,
                        "final_sleeper": False,
                    },
                    "specialist_plan": specialist_plan,
                    "special_teams_complete": (
                        any(player.position == "DST" for player in user_roster)
                        and any(player.position == "K" for player in user_roster)
                    ),
                    "late_round_plan_complete": (
                        use_late_round_plan
                        and any(player.position == "DST" for player in user_roster)
                        and any(player.position == "K" for player in user_roster)
                        and user_roster[-1].position in ("RB", "WR")
                        and user_roster[-1].projected_points > 0.0
                    ),
                    "specialist_plan_complete": (
                        bool(specialist_plan)
                        and all(
                            any(player.position == role for player in user_roster)
                            for role in specialist_plan.values()
                            if role in {"K", "DST"}
                        )
                        and (
                            "sleeper" not in specialist_plan.values()
                            or user_roster[-1].position in ("RB", "WR")
                        )
                    ),
                    "max_bench_before_starters": max(
                        (
                            _bench_players_before_starters(
                                user_roster[:index],
                                roster_positions,
                            )
                            for index in range(1, len(user_roster) + 1)
                            if _filled_starter_slots(
                                user_roster[:index],
                                roster_positions,
                            )
                            < len(_starter_eligibility(roster_positions))
                        ),
                        default=0,
                    ),
                }
        results.append(result)

    best_scores = [max(result.scores[index] for result in results) for index in range(trials)]
    summaries: list[dict[str, Any]] = []
    for result in results:
        summary = result.summary()
        if include_trial_records:
            summary["trial_records"] = result.roster_records
        summary["score_type"] = "availability_robustness_diagnostic"
        summary["replacement_aware_evaluation"] = replacement_aware_evaluation
        summary["acquisition_adp"] = dict(acquisition_metadata)
        wins = sum(
            math.isclose(score, best_scores[index], abs_tol=1e-9)
            for index, score in enumerate(result.scores)
        )
        summary["paired_win_rate"] = round(wins / trials, 4) if trials else 0.0
        summary["paired_mean_regret"] = round(
            fmean(best_scores[index] - score for index, score in enumerate(result.scores)), 3
        ) if trials else 0.0
        summary["deterministic_draft_scores"] = {}
        for weight in bench_weights:
            values = result.draft_scores_by_bench_weight.get(weight, [])
            ordered_values = sorted(values)
            if not ordered_values:
                continue
            best_weight_scores = [
                max(
                    item.draft_scores_by_bench_weight[weight][index]
                    for item in results
                )
                for index in range(trials)
            ]
            weight_wins = sum(
                math.isclose(score, best_weight_scores[index], abs_tol=1e-9)
                for index, score in enumerate(values)
            )
            summary["deterministic_draft_scores"][f"{weight:.2f}"] = {
                "mean": round(fmean(values), 4),
                "p10": round(ordered_values[round((len(ordered_values) - 1) * 0.10)], 4),
                "p90": round(ordered_values[round((len(ordered_values) - 1) * 0.90)], 4),
                "paired_win_rate": round(weight_wins / trials, 4) if trials else 0.0,
                "paired_mean_regret": round(
                    fmean(
                        best_weight_scores[index] - score
                        for index, score in enumerate(values)
                    ),
                    4,
                ) if trials else 0.0,
            }
        summary["rank_reconciliation"] = {
            "method": "absolute_selected_rank_vorp_blend",
            "curve_observations": rank_vorp_curve.observation_count,
            "curve_blocks": rank_vorp_curve.block_count,
            "rank_weights": list(rank_weights),
            "projection_conditioned": True,
        }
        summary["rank_reconciled_draft_scores"] = {}
        default_bench_weight = 0.20 if 0.20 in bench_weights else bench_weights[0]
        channel_default_metrics: list[dict[str, float | bool]] = []
        for rank_weight in rank_weights:
            channel = {
                "mean_bye_adjusted_lineup_score": round(
                    fmean(result.reconciled_lineup_scores[rank_weight]), 3
                ),
                "mean_usable_bench_vorp": round(
                    fmean(result.reconciled_usable_bench_scores[rank_weight]), 3
                ),
                "bench_weight_scores": {},
            }
            for bench_weight in bench_weights:
                values = result.reconciled_draft_scores[rank_weight][bench_weight]
                ordered_values = sorted(values)
                best_channel_scores = [
                    max(
                        item.reconciled_draft_scores[rank_weight][bench_weight][index]
                        for item in results
                    )
                    for index in range(trials)
                ]
                wins = sum(
                    math.isclose(score, best_channel_scores[index], abs_tol=1e-9)
                    for index, score in enumerate(values)
                )
                metrics = {
                    "mean": round(fmean(values), 4),
                    "p10": round(
                        ordered_values[round((len(ordered_values) - 1) * 0.10)], 4
                    ),
                    "p90": round(
                        ordered_values[round((len(ordered_values) - 1) * 0.90)], 4
                    ),
                    "paired_win_rate": round(wins / trials, 4) if trials else 0.0,
                    "paired_mean_regret": round(
                        fmean(
                            best_channel_scores[index] - score
                            for index, score in enumerate(values)
                        ),
                        4,
                    ) if trials else 0.0,
                }
                channel["bench_weight_scores"][f"{bench_weight:.2f}"] = metrics
                if bench_weight == default_bench_weight:
                    best_mean = max(
                        fmean(
                            item.reconciled_draft_scores[rank_weight][bench_weight]
                        )
                        for item in results
                    )
                    channel_default_metrics.append(
                        {
                            "mean": float(metrics["mean"]),
                            "paired_win_rate": float(metrics["paired_win_rate"]),
                            "paired_mean_regret": float(metrics["paired_mean_regret"]),
                            "mean_leader": math.isclose(
                                fmean(values), best_mean, abs_tol=1e-9
                            ),
                        }
                    )
            summary["rank_reconciled_draft_scores"][f"{rank_weight:.2f}"] = channel
        summary["cross_channel_robustness"] = {
            "bench_weight": default_bench_weight,
            "minimum_channel_mean": round(
                min(float(item["mean"]) for item in channel_default_metrics), 4
            ),
            "minimum_paired_win_rate": round(
                min(float(item["paired_win_rate"]) for item in channel_default_metrics), 4
            ),
            "maximum_paired_mean_regret": round(
                max(float(item["paired_mean_regret"]) for item in channel_default_metrics), 4
            ),
            "mean_leader_in_every_channel": all(
                bool(item["mean_leader"]) for item in channel_default_metrics
            ),
        }
        summary["weekly_use"] = {
            "method": "no_bye_common_absence_and_projection_miss",
            "stress_levels_are_separate_sensitivities": True,
            "rank_channels": {},
        }
        for rank_weight in rank_weights:
            channel = {}
            for level in ("no_absence", "light", "moderate", "heavy"):
                values = result.weekly_use_scores[rank_weight][level]
                reserve_lifts = result.weekly_use_reserve_lifts[rank_weight][level]
                best_scores = [
                    max(
                        item.weekly_use_scores[rank_weight][level][index]
                        for item in results
                    )
                    for index in range(trials)
                ]
                wins = sum(
                    math.isclose(score, best_scores[index], abs_tol=1e-9)
                    for index, score in enumerate(values)
                )
                channel[level] = {
                    "mean_full_lineup_score": round(fmean(values), 4),
                    "p10_full_lineup_score": round(
                        sorted(values)[round((len(values) - 1) * 0.10)], 4
                    ),
                    "mean_reserve_lift_above_waivers": round(
                        fmean(reserve_lifts), 4
                    ),
                    "paired_win_rate": round(wins / trials, 4) if trials else 0.0,
                    "paired_mean_regret": round(
                        fmean(
                            best_scores[index] - score
                            for index, score in enumerate(values)
                        ),
                        4,
                    ) if trials else 0.0,
                }
            summary["weekly_use"]["rank_channels"][f"{rank_weight:.2f}"] = channel
        summaries.append(summary)
    return sorted(
        summaries,
        key=lambda item: -float(
            item.get("cross_channel_robustness", {}).get(
                "minimum_channel_mean", -math.inf
            )
        ),
    )
