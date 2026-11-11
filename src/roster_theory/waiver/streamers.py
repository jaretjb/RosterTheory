"""Current-week skill comparisons independent of long-term acquisition gates."""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Mapping, Sequence

from roster_theory.inseason.evaluation import (
    InSeasonContext, build_weekly_projection_matrix, lineup,
)
from roster_theory.waiver.evaluation import PlayerValueInput, WaiverEvaluation, value_coverage_is_usable
from roster_theory.waiver.priority import build_waiver_priority_scores, league_replacement_ranks
from roster_theory.waiver.snapshot import ACQUIRABLE_STATES, WaiverSnapshot, _capacity


SKILL = frozenset({"QB", "RB", "WR", "TE"})
_DROP_CAUTIONS = {
    "drop_retention_protection": "the drop is protected for retention",
    "protected_upside_incremental_value": "the drop has protected bench upside",
    "protected_contingency_drop": "the drop has a protected contingency role",
    "depth_delta": "the drop creates replacement exposure",
    "offense_downside_increase": "the move increases roster downside risk",
}


@dataclass(frozen=True, slots=True)
class WeeklySkillStreamer:
    add_player_id: str
    drop_player_id: str | None
    position: str
    projected_points: float
    current_week_lineup_gain: float
    displaced_starter_ids: tuple[str, ...]
    ros_decision_label: str
    ros_tradeoff: str
    weekly_position_rank: int | None = None
    drop_projected_points: float | None = None
    drop_rest_of_season_rank: int | None = None
    retention_warnings: tuple[str, ...] = ()
    projection_coverage: str = "complete"


@dataclass(frozen=True, slots=True)
class WeeklyStreamerOmission:
    player_id: str
    reason: str


def evaluate_weekly_streamers(
    snapshot: WaiverSnapshot, *, weeks, projections,
    weekly_position_ranks: Mapping[str, int], values: Sequence[PlayerValueInput],
    drop_legality: Mapping[str, bool | None], news_fresh: Mapping[str, bool],
    evaluations: Sequence[WaiverEvaluation] = (),
    contingencies=(),
    availability=(),
) -> tuple[tuple[WeeklySkillStreamer, ...], tuple[WeeklyStreamerOmission, ...]]:
    """Score singleton adds against owned starters without inventing future value."""
    overrides = {row['player_id']: row['status'] for row in availability}
    if overrides:
        snapshot = replace(snapshot, players=tuple(
            replace(p, active=True, injury_status=None if overrides[p.player_id] == 'ACTIVE' else 'Out')
            if p.player_id in overrides else p for p in snapshot.players))
    players = {p.player_id: p for p in snapshot.players}
    owners = dict(snapshot.owner_by_player)
    team = next(t for t in snapshot.teams if t.roster_id == snapshot.user_roster_id)
    capacity = next(c for c in snapshot.roster_capacity if c.roster_id == team.roster_id)
    roster = set(team.player_ids) - set(team.reserve_ids)
    owned_skill = {pid for pid in roster if SKILL.intersection(players[pid].positions)}
    current_week = snapshot.manifest.current_week
    current = next(w for w in weeks if w.week == current_week)
    context = InSeasonContext(
        players=tuple(replace(p, active=False) if str(p.injury_status or '').upper() == 'SUSPENDED' else p
                      for p in snapshot.players if SKILL.intersection(p.positions)),
        roster_positions=snapshot.league.roster_positions, weeks=(current,),
        unowned_player_ids=(), evaluation_positions=tuple(sorted(SKILL)),
        current_week=current_week, allow_estimated_projections=True,
    )
    matrix = build_weekly_projection_matrix(context, projections)
    missing_roster = sorted(pid for pid in owned_skill if matrix.cell(pid, current_week).points is None)
    available_roster = {pid for pid in owned_skill
                        if matrix.cell(pid, current_week).availability == "ACTIVE"}
    baseline = None if missing_roster else lineup(
        context, matrix, available_roster, current_week, allow_partial=False)
    values_by_id = {v.player_id: v for v in values}
    retention = build_waiver_priority_scores(
        players=snapshot.players, values=values, owner_by_player=owners,
        waiver_wire_evidence=None,
        current_bye_teams=current.bye_teams,
    )
    by_add = {e.add_player_id: e for e in evaluations}
    replacement_ranks = league_replacement_ranks(snapshot.players, owners)
    protected_roles = {c.beneficiary_player_id for c in contingencies}
    results, omissions = [], []
    for acquisition in snapshot.acquisitions:
        pid = acquisition.player_id
        if not SKILL.intersection(players[pid].positions):
            continue
        if acquisition.state not in ACQUIRABLE_STATES or acquisition.owner_roster_id is not None or pid in owners:
            continue
        cell = matrix.cell(pid, current_week)
        reason = None
        if dict(snapshot.league.platform_settings).get("disable_adds") == 1:
            reason = "LEAGUE_MOVES_LOCKED"
        elif cell.availability in {"BYE", "INACTIVE"}:
            reason = "CURRENT_WEEK_" + cell.availability
        elif cell.points is None:
            reason = "CURRENT_WEEK_FORECAST_UNAVAILABLE"
        elif pid not in weekly_position_ranks:
            reason = "CURRENT_WEEK_EXPERT_RANK_UNAVAILABLE"
        elif news_fresh.get(pid) is not True:
            reason = "MATERIAL_NEWS_NOT_FRESH"
        elif missing_roster:
            reason = "OWNED_CURRENT_WEEK_FORECAST_UNAVAILABLE: " + ", ".join(missing_roster)
        if reason:
            omissions.append(WeeklyStreamerOmission(pid, reason))
            continue
        drops = ([None] if capacity.open_active_slots > 0 else
                 sorted(pid for pid in owned_skill if drop_legality.get(pid) is True))
        if not drops:
            omissions.append(WeeklyStreamerOmission(pid, "NO_PROVED_LEGAL_SKILL_DROP"))
            continue
        alternatives = []
        for drop in drops:
            proposed = replace(team, player_ids=tuple(sorted((set(team.player_ids) - {drop}) | {pid})),
                               starter_ids=tuple(p for p in team.starter_ids if p != drop))
            proposed_capacity = _capacity(snapshot.league, proposed, snapshot.players)
            if not proposed_capacity.capacity_legal or not proposed_capacity.reserve_legal:
                continue
            after = lineup(context, matrix, (available_roster - {drop}) | {pid},
                           current_week, allow_partial=False)
            chosen = {a.player_id for a in after.assignments}
            if pid not in chosen or after.score <= baseline.score:
                continue
            if after.filled_slots < baseline.filled_slots:
                continue
            if any(sum(a.slot.startswith(role + ":") for a in after.assignments)
                   < sum(a.slot.startswith(role + ":") for a in baseline.assignments) for role in SKILL):
                continue
            drop_value = values_by_id.get(drop)
            drop_rank = (drop_value.selected_rest_of_season_position_rank
                         or drop_value.rest_of_season_position_rank) if drop_value else None
            cautions = []
            if overrides:
                cautions.append("the weekly lineup follows supplied availability assumptions")
            if drop is not None:
                if drop_value is None or not value_coverage_is_usable(drop_value.coverage_status):
                    cautions.append("the drop's rest-of-season value is unavailable")
                if drop_rank is None:
                    cautions.append("the drop's rest-of-season rank is unavailable")
                if drop in retention and retention[drop].retention_protected:
                    cautions.append("the drop is protected for retention")
                drop_position = next(p for p in players[drop].positions if p in SKILL)
                if drop_rank is not None and drop_rank < replacement_ranks.get(drop_position, 0):
                    cautions.append("the drop has above-replacement rest-of-season rank")
                if drop in protected_roles:
                    cautions.append("the drop has a documented contingency role")
                if "QB" in players[drop].positions:
                    cautions.append("review backup quarterback and upcoming bye coverage")
            evaluation = by_add.get(pid)
            matching = next((c for c in evaluation.candidates if c.drop_player_id == drop), None) if evaluation else None
            if matching and matching.contingency.drop_protected:
                cautions.append("the drop has protected bench upside")
            if evaluation and evaluation.selected_drop_player_id == drop and evaluation.decision:
                cautions.extend(text for gate, text in _DROP_CAUTIONS.items()
                                if any(g.name == gate and not g.passed for g in evaluation.decision.gates))
            add_value = values_by_id.get(pid)
            if players[pid].injury_status:
                cautions.append("the player's current injury status is " + players[pid].injury_status)
            if add_value is None or not value_coverage_is_usable(add_value.coverage_status):
                cautions.append("rest-of-season acquisition value is unavailable")
            if add_value is None or (add_value.selected_rest_of_season_position_rank is None
                                     and add_value.rest_of_season_position_rank is None):
                cautions.append("rest-of-season acquisition rank is unavailable")
            if not evaluation or not matching or not matching.projection_inputs_complete:
                cautions.append("future lineup, depth and downside effects require review")
            cautions = tuple(dict.fromkeys(cautions))
            label = (evaluation.decision_label if evaluation and evaluation.selected_drop_player_id == drop
                     else "NOT EVALUATED") or "NOT EVALUATED"
            review = "Review this one-week option. " if drop is None else "Review the proposed drop. "
            tradeoff = (review + ". ".join(text[0].upper() + text[1:] for text in cautions) if cautions else
                        "Also passes the rest-of-season acquisition checks" if label in {"ACQUIRE", "ADD NOW", "CLAIM"}
                        else "Short-term starter; review the rest-of-season drop decision")
            alternatives.append(WeeklySkillStreamer(
                pid, drop, "/".join(p for p in players[pid].positions if p in SKILL),
                cell.points, round(after.score - baseline.score, 3),
                tuple(sorted({a.player_id for a in baseline.assignments} - chosen)), label, tradeoff,
                weekly_position_ranks[pid], matrix.cell(drop, current_week).points if drop else None,
                drop_rank, cautions, cell.coverage_status,
            ))
        if alternatives:
            results.append(min(alternatives, key=lambda r: (
                "the drop is protected for retention" in r.retention_warnings,
                len(r.retention_warnings), -r.current_week_lineup_gain,
                values_by_id[r.drop_player_id].selected_value if r.drop_player_id in values_by_id else 0,
                r.drop_player_id or "",
            )))
        else:
            omissions.append(WeeklyStreamerOmission(pid, "NO_CURRENT_WEEK_STARTER_IMPROVEMENT"))
    return (tuple(sorted(results, key=lambda r: (-r.current_week_lineup_gain, r.add_player_id))),
            tuple(sorted(omissions, key=lambda r: (r.reason, r.player_id))))
