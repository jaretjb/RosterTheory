"""Waiver-owned, bounded planning of actual weekly roster transformations.

Point forecasts, ownership value, replacement floors and decision policy retain
their separate units. This module has no provider or platform write surface.
"""
from __future__ import annotations

import itertools
import json
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta
from math import isfinite
from pathlib import Path

from roster_theory.core.errors import CoverageIncomplete, RosterIllegal
from roster_theory.core.lineup import LineupPlayer, optimize_lineup
from roster_theory.core.specialists import fixed_specialist_swap
from roster_theory.core.provenance import stable_hash
from roster_theory.inseason.evaluation import (
    InSeasonContext, build_weekly_projection_matrix, depth_above_waiver, risk_impact,
)
from roster_theory.waiver.policy import evaluation_options_for_policy
from roster_theory.providers.sleeper_membership import reserve_eligibility
from roster_theory.waiver.evaluation import value_coverage_is_usable, _one_qb_format, qb_streaming_coverage_usable
from roster_theory.waiver.plans import hypothetical_claim
from roster_theory.waiver.priority import league_replacement_ranks
from roster_theory.waiver.snapshot import ACQUIRABLE_STATES, _capacity

SKILL = frozenset({'QB', 'RB', 'WR', 'TE'})


@dataclass(frozen=True)
class WeeklyPlanPolicy:
    league_key: str
    version: str = 'wa-032-weekly-plan-v1'
    weekly_close_margin: float = 1.0
    season_close_margin: float = 3.0
    maximum_season_loss: float = 3.0
    maximum_selected_value_loss: float = 6.0
    maximum_market_value_loss: float = 6.0
    candidate_limit: int = 16
    drop_limit: int = 6
    beam_width: int = 12
    maximum_skill_moves: int = 2
    maximum_comparisons: int = 600
    near_replacement_margin: int = 1

    def __post_init__(self):
        if not self.league_key:
            raise ValueError('Weekly planning policy requires league scope')
        for name in ('weekly_close_margin', 'season_close_margin', 'maximum_season_loss',
                     'maximum_selected_value_loss', 'maximum_market_value_loss'):
            value = getattr(self, name)
            if isinstance(value, bool) or not isfinite(value) or value < 0:
                raise ValueError(f'Invalid planning setting {name}')
        if self.weekly_close_margin == 0 or self.season_close_margin == 0:
            raise ValueError('Materiality margins must be positive')
        for name in ('candidate_limit', 'drop_limit', 'beam_width', 'maximum_skill_moves',
                     'maximum_comparisons', 'near_replacement_margin'):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f'Invalid planning limit {name}')
        if self.maximum_skill_moves > 3:
            raise ValueError('Weekly planning supports at most three skill acquisitions')


def load_plan_policy(path, league_key):
    if path is None:
        return WeeklyPlanPolicy(league_key)
    policy = WeeklyPlanPolicy(**json.loads(Path(path).read_text(encoding='utf-8')))
    if policy.league_key != league_key:
        raise ValueError('Weekly planning policy belongs to another league')
    return policy


def load_availability(path, snapshot, *, now):
    """Accept explicit current-week scenarios without changing platform facts."""
    if path is None:
        return ()
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    if (data.get('league_key') != snapshot.league_key
            or data.get('season') != snapshot.league.season
            or data.get('week') != snapshot.manifest.current_week):
        raise ValueError('Availability scenario must match this league, season and week')
    ids = {p.player_id for p in snapshot.players}
    seen = set()
    rows = []
    for row in data.get('players', ()):
        pid = str(row['player_id'])
        observed = datetime.fromisoformat(row['observed_at'])
        expires = datetime.fromisoformat(row['expires_at'])
        if (pid not in ids or pid in seen or row.get('status') not in {'ACTIVE', 'INACTIVE'}
                or not str(row.get('source', '')).strip()
                or row.get('authority') not in {'USER_SCENARIO', 'PROVIDER_REPORT'}):
            raise ValueError('Invalid, duplicate or ungrounded availability scenario')
        if (observed.tzinfo is None or expires.tzinfo is None or observed > now
                or expires <= now or expires <= observed
                or now - observed > timedelta(hours=72)):
            raise ValueError('Availability scenario is stale, future-dated or expired')
        seen.add(pid)
        rows.append(dict(row, player_id=pid))
    if not rows:
        raise ValueError('Availability scenario contains no players')
    return tuple(rows)


@dataclass(frozen=True)
class PlanStep:
    kind: str
    player_id: str
    drop_player_id: str | None = None
    basis: str = ''
    alternatives: tuple[str, ...] = ()


@dataclass(frozen=True)
class OwnedWeek:
    week: int
    points: float
    filled: int
    required: int
    starters: tuple[tuple[str, str, float], ...]


@dataclass(frozen=True)
class PlanAlternative:
    steps: tuple[PlanStep, ...]
    current: OwnedWeek
    season_delta: float
    selected_value_delta: float
    market_value_delta: float
    depth_delta: float
    risk_delta: float
    future_gaps: tuple[tuple[int, int], ...]
    return_drop_player_ids: tuple[str, ...]
    accepted: bool
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class WeeklyRosterPlan:
    schema_version: int
    league_key: str
    policy: WeeklyPlanPolicy
    policy_hash: str
    input_hash: str
    objective: str
    baseline: OwnedWeek
    selected: PlanAlternative
    alternatives: tuple[PlanAlternative, ...]
    evaluated_plans: int
    coverage: str
    omitted_candidate_ids: tuple[str, ...]
    availability: tuple[dict, ...]
    fallback: PlanAlternative | None
    evidence_notes: tuple[str, ...]
    evidence_failures: tuple[str, ...] = ()
    failed_claim_branches: tuple[dict, ...] = ()
    evidence_hash: str = ''


def build_weekly_plan(snapshot, *, weeks, projections, values, evaluations, policy,
                      planning_policy, drop_legality, news_fresh, input_hash,
                      availability=(), exact_pair=None, include_failure_branches=True):
    """Compare owned-roster plans; never promise future waiver availability.

Search is explicitly bounded by candidate, drop, beam and comparison limits.
Every limit and omitted candidate survives in the saved result.
"""
    if planning_policy.league_key != snapshot.league_key:
        raise ValueError('Weekly planning policy belongs to another league')
    original = snapshot
    if availability:
        overrides = {row['player_id']:row['status'] for row in availability}
        snapshot = replace(snapshot, players=tuple(
            replace(p, active=True, injury_status=None if overrides[p.player_id] == 'ACTIVE'
                    else 'Out') if p.player_id in overrides else p for p in snapshot.players))
    players = {p.player_id:p for p in snapshot.players}
    value_map = {v.player_id:v for v in values}
    team = next(t for t in snapshot.teams if t.roster_id == snapshot.user_roster_id)
    capacity = next(c for c in snapshot.roster_capacity if c.roster_id == team.roster_id)
    one_qb = _one_qb_format(snapshot.league.roster_positions)
    if not capacity.capacity_legal or not capacity.reserve_legal or not capacity.reserve_legality_known:
        raise CoverageIncomplete('Weekly plan requires known legal roster capacity and reserves')
    ctx = InSeasonContext(players=tuple(p for p in snapshot.players if p.player_id in value_map
                                        or p.player_id in team.player_ids),
        roster_positions=snapshot.league.roster_positions, weeks=tuple(weeks),
        unowned_player_ids=(), evaluation_positions=tuple(sorted(SKILL)),
        current_week=snapshot.manifest.current_week, allow_estimated_projections=True)
    matrix = build_weekly_projection_matrix(ctx, projections)
    skill_slots = tuple(slot for slot in snapshot.league.roster_positions
                        if slot not in {'BN', 'K', 'DEF', 'DST'})
    lineups = {}

    def solve(ids, week):
        key = (tuple(sorted(ids)), week)
        if key in lineups:
            return lineups[key]
        applicable = [pid for pid in ids if pid in players and SKILL.intersection(players[pid].positions)]
        if any((cell := matrix.cell(pid, week)) is None or cell.points is None for pid in applicable):
            raise CoverageIncomplete(f'Actual weekly roster forecast incomplete for Week {week}')
        active = [pid for pid in applicable if matrix.cell(pid, week).availability == 'ACTIVE']
        result = optimize_lineup(tuple(LineupPlayer(pid, players[pid].positions) for pid in active),
            skill_slots, {pid:matrix.cell(pid, week).points for pid in active})
        row = OwnedWeek(week, round(result.score, 3), result.filled_slots, result.total_slots,
                       tuple((a.slot, a.player_id, a.points) for a in result.assignments))
        lineups[key] = row
        return row

    active_before = set(team.player_ids) - set(team.reserve_ids)
    week0 = snapshot.manifest.current_week
    baseline = solve(active_before, week0)
    # IR return is a forecast scenario, not sixteen permanent active holdings.
    def future_ids(ids, reserves):
        combined = set(ids) | set(reserves)
        removed = []
        while len(combined) > capacity.active_limit:
            choices = [pid for pid in combined if pid in value_map
                       and SKILL.intersection(players[pid].positions)]
            safe = [pid for pid in choices if not outgoing_qb_gap({pid}, combined - {pid})]
            if not safe:
                raise CoverageIncomplete('IR reactivation cost cannot be established')
            drop = min(safe, key=lambda pid:(value_map[pid].selected_value, pid))
            combined.remove(drop)
            removed.append(drop)
        return combined, tuple(removed)

    def outgoing_qb_gap(drops, after):
        if not any('QB' in players[pid].positions for pid in drops):
            return False
        for week in weeks[:3]:
            before_qb = [pid for pid in active_before if 'QB' in players[pid].positions
                         and matrix.cell(pid, week.week).availability == 'ACTIVE']
            after_qb = [pid for pid in after if 'QB' in players[pid].positions
                        and matrix.cell(pid, week.week).availability == 'ACTIVE']
            if before_qb and not after_qb:
                return True
        return False

    before_future, _ = future_ids(active_before, team.reserve_ids)
    before_weeks = tuple(solve(before_future if w.week != week0 else active_before, w.week)
                         for w in weeks)
    baseline_score = sum(w.points for w in before_weeks)
    replacement_ranks = league_replacement_ranks(snapshot.players, dict(snapshot.owner_by_player))
    by_add = {e.add_player_id:e for e in evaluations if e.add_position in SKILL}
    supported = {a.player_id for a in snapshot.acquisitions if a.state in ACQUIRABLE_STATES
                 and a.owner_roster_id is None and a.player_id not in dict(snapshot.owner_by_player)}
    admitted = []
    for pid, e in by_add.items():
        cell = matrix.cell(pid, week0)
        if (pid in supported and e.value_inputs_complete and e.material_news_fresh
                and news_fresh.get(pid, False) and cell and cell.availability == 'ACTIVE'
                and cell.points is not None and cell.points > 0
                and any(c.projection_inputs_complete for c in e.candidates)):
            admitted.append(pid)
    ordered = sorted(admitted, key=lambda pid:(-matrix.cell(pid, week0).points, pid))
    ros_order = sorted(admitted, key=lambda pid:(-value_map[pid].selected_value, pid))
    shortlist = list(dict.fromkeys(itertools.chain.from_iterable(zip(ordered, ros_order))))
    shortlist = shortlist[:planning_policy.candidate_limit]
    omitted = tuple(sorted(set(admitted) - set(shortlist)))
    preparations = [(snapshot, ())]
    free_ir = max(0, int(capacity.reserve_limit or 0) - capacity.reserve_count)
    if free_ir:
        eligible = []
        for pid in sorted(active_before):
            if not SKILL.intersection(players[pid].positions):
                continue
            proposed = replace(team, reserve_ids=(*team.reserve_ids, pid))
            if not reserve_eligibility(snapshot.league, proposed, snapshot.players):
                eligible.append(pid)
        for combo_size in range(1, min(free_ir, 2) + 1):
            for combo in itertools.islice(itertools.combinations(eligible, combo_size), 6):
                proposed = replace(team, reserve_ids=(*team.reserve_ids, *combo))
                caps = _capacity(snapshot.league, proposed, snapshot.players)
                if caps.capacity_legal and caps.reserve_legal:
                    preparations.append((replace(snapshot,
                        teams=tuple(proposed if t.roster_id == team.roster_id else t for t in snapshot.teams),
                        roster_capacity=tuple(caps if c.roster_id == team.roster_id else c for c in snapshot.roster_capacity)),
                        tuple(PlanStep('IR', pid, basis='Eligible empty reserve slot; reassess on reactivation') for pid in combo)))

    comparisons = []
    evidence_failures = []
    seen = set()
    exhausted = False

    def assess(branch, steps):
        nonlocal exhausted
        bt = next(t for t in branch.teams if t.roster_id == team.roster_id)
        active = set(bt.player_ids) - set(bt.reserve_ids)
        key = (tuple(sorted(active)), tuple(sorted(bt.reserve_ids)))
        if key in seen:
            return None
        if len(comparisons) >= planning_policy.maximum_comparisons:
            exhausted = True
            return None
        seen.add(key)
        adds = {step.player_id for step in steps if step.kind == 'ADD'}
        drops = {step.drop_player_id for step in steps if step.drop_player_id}
        reasons = []
        try:
            current = solve(active, week0)
            future, return_drops = future_ids(active, bt.reserve_ids)
            after_weeks = tuple(solve(future if w.week != week0 else active, w.week) for w in weeks)
        except CoverageIncomplete as exc:
            evidence_failures.append(str(exc) + ': ' + ','.join(sorted(active)))
            return None
        season_delta = round(sum(w.points for w in after_weeks) - baseline_score, 3)
        selected_delta = round(sum(value_map[pid].selected_value for pid in adds)
                               - sum(value_map[pid].selected_value for pid in drops), 3)
        market_delta = round(sum(value_map[pid].market_value for pid in adds)
                             - sum(value_map[pid].market_value for pid in drops), 3)
        repair_steps = [step for step in steps if step.kind == 'ADD' and any(
            c.coverage_repair is not None and c.coverage_repair.safe_drop
            for c in by_add[step.player_id].candidates if c.drop_player_id == step.drop_player_id)]
        # Charge optional moves normally. A coverage repair must not provide
        # a blanket exemption for an unrelated second acquisition.
        repair_selected_loss = sum(min(0, value_map[s.player_id].selected_value
            - (value_map[s.drop_player_id].selected_value if s.drop_player_id else 0)) for s in repair_steps)
        repair_market_loss = sum(min(0, value_map[s.player_id].market_value
            - (value_map[s.drop_player_id].market_value if s.drop_player_id else 0)) for s in repair_steps)
        gap_weeks = tuple((after.week, after.required - after.filled) for before, after in
                         zip(before_weeks, after_weeks) if after.filled < before.filled)
        if current.filled < baseline.filled:
            reasons.append('CURRENT_COVERAGE_LOSS')
        for role in ('QB', 'RB', 'WR', 'TE'):
            if sum(slot.startswith(role + ':') for slot, _, _ in current.starters) < sum(
                    slot.startswith(role + ':') for slot, _, _ in baseline.starters):
                reasons.append('FIXED_STARTER_COVERAGE_LOSS')
        if current.points < baseline.points - policy.maximum_current_week_loss:
            reasons.append('CURRENT_POINT_LOSS')
        if season_delta < -planning_policy.maximum_season_loss:
            reasons.append('SEASON_LOSS')
        if selected_delta-repair_selected_loss < -planning_policy.maximum_selected_value_loss:
            reasons.append('ROS_OWNERSHIP_LOSS')
        if market_delta-repair_market_loss < -planning_policy.maximum_market_value_loss:
            reasons.append('CONSENSUS_ROS_LOSS')
        if outgoing_qb_gap(drops, active):
            reasons.append('OUTGOING_QB_COVERAGE')
        depth_delta = 0.0
        risk_delta = 0.0
        for add in adds:
            original_e = by_add[add]
            requested_drop = next(step.drop_player_id for step in steps
                                  if step.kind == 'ADD' and step.player_id == add)
            matching = [c for c in original_e.candidates if c.drop_player_id == requested_drop]
            # Open spots created by IR have no displaced player's cost. Exact
            # after-preparation evaluation is deferred to the winning sequence.
            if matching:
                c = min(matching, key=lambda c: (c.drop_player_id or ''))
                depth_delta += c.lineup.depth_delta
                risk_delta = max(risk_delta, c.risk.offense_downside_loss_delta)
            if original_e.add_position == 'QB' and one_qb:
                qbs = [pid for pid in active_before if 'QB' in players[pid].positions]
                meaningful = any(matrix.cell(add, w.week).availability == 'ACTIVE'
                    and (not any(matrix.cell(pid, w.week).availability == 'ACTIVE' for pid in qbs)
                         or matrix.cell(add, w.week).points >= max(
                             (matrix.cell(pid, w.week).points for pid in qbs
                              if matrix.cell(pid, w.week).availability == 'ACTIVE'), default=0)
                         + policy.qb_starter_decision_margin) for w in weeks)
                if qbs and not meaningful:
                    reasons.append('REDUNDANT_QB_HOLD')
        # Singleton safety deltas are explanatory screens only. Joint safety
        # is recomputed before the selected package can be recommended.
        for drop in drops:
            for add in adds:
                candidate = next((c for c in by_add[add].candidates if c.drop_player_id == drop), None)
                if candidate is None:
                    continue
                if not candidate.projection_inputs_complete:
                    reasons.append('DROP_EVIDENCE_INCOMPLETE')
                if not candidate.contingency.incremental_gate_passed:
                    reasons.append('PROTECTED_CONTINGENT_UPSIDE')
            v = value_map[drop]
            p = players[drop]
            if p.injury_status and str(p.injury_status).upper() in {'Q', 'QUESTIONABLE','DOUBTFUL','OUT','IR','PUP'}:
                rank = v.selected_rest_of_season_position_rank or v.rest_of_season_position_rank
                pos = next((p for p in p.positions if p in SKILL), None)
                distance = replacement_ranks.get(pos, 0) - (rank or 10000)
                if distance > planning_policy.near_replacement_margin:
                    reasons.append('INJURED_ABOVE_REPLACEMENT_HOLD')
                elif distance >= 0 and (selected_delta < 0 or market_delta < 0 or gap_weeks):
                    reasons.append('UNCERTAIN_NEAR_REPLACEMENT_DROP')
        if steps and current.filled <= baseline.filled and current.points <= baseline.points:
            if season_delta < planning_policy.season_close_margin:
                reasons.append('NO_MATERIAL_ROSTER_BENEFIT')
        result = PlanAlternative(steps, current, season_delta, selected_delta, market_delta,
            round(depth_delta, 3), round(risk_delta, 3), gap_weeks, return_drops,
            not reasons, tuple(sorted(set(reasons))))
        comparisons.append(result)
        return result

    no_action = assess(snapshot, ())
    if no_action is None:
        raise CoverageIncomplete('Weekly plan cannot establish an actual-roster baseline')

    def quality(row):
        # Within a weekly forecast margin prefer durable ownership/depth;
        # ownership units never get added to fantasy points.
        best_points = max((other.current.points for other in comparisons
                           if other.accepted and other.current.filled == row.current.filled),
                          default=row.current.points)
        return (not row.accepted, -row.current.filled,
                int(max(0, best_points - row.current.points) / planning_policy.weekly_close_margin),
                max(0, sum(step.kind == 'ADD' for step in row.steps) - 1),
                -row.selected_value_delta,
                -int(row.season_delta / planning_policy.season_close_margin),
                -row.depth_delta, row.risk_delta,
                len(row.steps), tuple((s.kind, s.player_id, s.drop_player_id or '') for s in row.steps))

    preparations.sort(key=lambda row:(not bool(row[1]),
        -sum(value_map[step.player_id].selected_value for step in row[1])))
    for prepared, prep_steps in preparations:
        frontier = [(prepared, prep_steps)]
        for _ in range(planning_policy.maximum_skill_moves):
            children = []
            for branch, steps in frontier:
                bt = next(t for t in branch.teams if t.roster_id == team.roster_id)
                cap = next(c for c in branch.roster_capacity if c.roster_id == team.roster_id)
                prior_adds = {s.player_id for s in steps if s.kind == 'ADD'}
                drops = sorted((pid for pid in set(bt.player_ids) - set(bt.reserve_ids) - prior_adds
                                if drop_legality.get(pid) is True and pid in value_map
                                and value_coverage_is_usable(value_map[pid].coverage_status)
                                and SKILL.intersection(players[pid].positions)),
                               key=lambda pid:(value_map[pid].selected_value, pid))[:planning_policy.drop_limit]
                choices = (None,) if cap.open_active_slots else tuple(drops)
                for add, drop in itertools.product(shortlist, choices):
                    if add in bt.player_ids:
                        continue
                    proposed = hypothetical_claim(branch, add, drop)
                    new_steps = (*steps, PlanStep('ADD', add, drop, 'Actual weekly roster comparison'))
                    candidate = assess(proposed, new_steps)
                    if candidate is not None:
                        parent_ids = set(bt.player_ids) - set(bt.reserve_ids)
                        parent_current = solve(parent_ids, week0)
                        parent_future, _ = future_ids(parent_ids, bt.reserve_ids)
                        parent_total = sum(solve(parent_ids if w.week == week0 else parent_future, w.week).points
                                           for w in weeks)
                        child_total = candidate.season_delta + baseline_score
                        if (candidate.current.filled <= parent_current.filled
                                and candidate.current.points-parent_current.points < (
                                    policy.qb_starter_decision_margin if one_qb and by_add[add].add_position == 'QB'
                                    else planning_policy.weekly_close_margin)
                                and child_total-parent_total < planning_policy.season_close_margin):
                            candidate = replace(candidate, accepted=False,
                                reasons=tuple(sorted(set((*candidate.reasons, 'NO_INCREMENTAL_MATERIAL_BENEFIT')))))
                            comparisons[-1] = candidate
                        children.append((candidate, proposed, new_steps))
                    if exhausted:
                        break
                if exhausted:
                    break
            # Keep rejected prefixes too: a second move may repair coverage.
            children.sort(key=lambda row: quality(row[0]))
            frontier = [(s, steps) for _, s, steps in children[:planning_policy.beam_width]]
            if not frontier or exhausted:
                break
        if exhausted:
            break
    ranked = sorted(comparisons, key=quality)
    selected = next((row for row in ranked if row.accepted), no_action)
    # Exact changed-roster revalidation protects dependencies that cheap plan
    # comparisons cannot establish, while allowing documented weekly tradeoffs.
    notes = ['Bounded weekly plan; best across every combination is not established.',
             'Planning defaults use controlled fixtures, not empirical outcome calibration.',
             'Owned-player points are separate from assumed waiver replacement floors.']
    if exact_pair is not None:
        joint_context = replace(ctx, unowned_player_ids=tuple(supported))
        joint_options = evaluation_options_for_policy(policy)
        for row in ranked:
            if not row.accepted:
                continue
            branch = snapshot
            checks = []
            for step in row.steps:
                if step.kind == 'IR':
                    bt = next(t for t in branch.teams if t.roster_id == team.roster_id)
                    bt = replace(bt, reserve_ids=(*bt.reserve_ids, step.player_id))
                    branch = replace(branch, teams=tuple(bt if t.roster_id == team.roster_id else t for t in branch.teams),
                        roster_capacity=tuple(_capacity(branch.league, bt, branch.players) if c.roster_id == team.roster_id else c for c in branch.roster_capacity))
                else:
                    e = exact_pair(branch, step.player_id, step.drop_player_id)
                    c = next((c for c in e.candidates if c.drop_player_id == step.drop_player_id), None)
                    if (c is None or not e.value_inputs_complete or not e.material_news_fresh
                            or not c.projection_inputs_complete or not e.add_currently_active
                            or not c.contingency.incremental_gate_passed):
                        checks.append('CHANGED_ROSTER_EVIDENCE_UNAVAILABLE')
                        break
                    if (e.add_position == 'QB' and c.holding.applicable
                            and not (c.coverage_repair and c.coverage_repair.safe_drop)
                            and (not qb_streaming_coverage_usable(c.holding) or (
                                c.holding.net_hold_value < policy.qb_net_hold_value_floor
                                and not (c.holding.injury_insurance_value >= policy.qb_insurance_advantage_floor
                                    and c.holding.bench_slot_opportunity_cost <= policy.qb_maximum_bench_slot_opportunity_cost)))):
                        checks.append('CHANGED_ROSTER_QB_HOLD')
                        break
                    branch = hypothetical_claim(branch, step.player_id, step.drop_player_id)
            if not checks:
                bt = next(t for t in branch.teams if t.roster_id == team.roster_id)
                final_ids, _ = future_ids(set(bt.player_ids) - set(bt.reserve_ids), bt.reserve_ids)
                risk_context = replace(joint_context, unowned_player_ids=tuple(
                    pid for pid in supported if pid not in final_ids))
                before_safety = {pid for pid in before_future if SKILL.intersection(players[pid].positions)}
                after_safety = {pid for pid in final_ids if SKILL.intersection(players[pid].positions)}
                depth = depth_above_waiver(risk_context, matrix, after_safety, joint_options) - depth_above_waiver(
                    risk_context, matrix, before_safety, joint_options)
                risk = risk_impact(risk_context, matrix, team.roster_id,
                                   before_safety, after_safety, joint_options)
                if depth < -policy.maximum_depth_loss or risk.offense_downside_loss_delta > policy.maximum_downside_increase:
                    evidence_failures.append('Joint depth/risk bounds failed: ' + ','.join(sorted(final_ids)))
                    continue
                selected = replace(row, depth_delta=round(depth, 3),
                                   risk_delta=risk.offense_downside_loss_delta)
                break
        else:
            selected = no_action
            notes.append('No complete changed-roster sequence passed required evidence checks.')
    # Specialist slots stay independent; exact re-evaluation on the chosen
    # branch is mandatory, and every requested drop must remain present.
    if exact_pair is not None:
        branch = snapshot
        for step in selected.steps:
            if step.kind == 'IR':
                bt = next(t for t in branch.teams if t.roster_id == team.roster_id)
                bt = replace(bt, reserve_ids=(*bt.reserve_ids, step.player_id))
                branch = replace(branch, teams=tuple(bt if t.roster_id == team.roster_id else t for t in branch.teams),
                    roster_capacity=tuple(_capacity(branch.league, bt, branch.players) if c.roster_id == team.roster_id else c for c in branch.roster_capacity))
            else:
                branch = hypothetical_claim(branch, step.player_id, step.drop_player_id)
        extra = []
        for position in ('DST', 'K'):
            bt = next(t for t in branch.teams if t.roster_id == team.roster_id)
            incumbents = [pid for pid in set(bt.player_ids) - set(bt.reserve_ids)
                          if position in players[pid].positions]
            if len(incumbents) != 1:
                continue
            candidates = [e for e in evaluations if e.add_position == position
                          and e.add_player_id in supported]
            checked = []
            for candidate in candidates:
                try:
                    e = exact_pair(branch, candidate.add_player_id, incumbents[0])
                except (CoverageIncomplete, RosterIllegal) as exc:
                    evidence_failures.append(f'Specialist {candidate.add_player_id}: {exc}')
                    continue
                if e.decision_label in {'ACQUIRE', 'CLAIM', 'ADD NOW'}:
                    c = next(c for c in e.candidates if c.drop_player_id == e.selected_drop_player_id)
                    if c.same_position and fixed_specialist_swap(branch.players,
                            branch.league.roster_positions, bt.player_ids,
                            e.add_player_id, e.selected_drop_player_id) == position:
                        checked.append(e)
            if checked:
                e = min(checked, key=lambda e: (-(e.decision.priority_score or 0),e.add_player_id))
                extra.append(PlanStep('ADD', e.add_player_id, e.selected_drop_player_id,
                    'Independent specialist comparison; point forecast may be unavailable'))
                branch = hypothetical_claim(branch, e.add_player_id, e.selected_drop_player_id)
        selected = replace(selected, steps=(*selected.steps, *extra))
    alternatives = tuple(row for row in ranked if row.steps != selected.steps)[:6]
    # Backups for a single request preserve all other requested roster changes.
    decorated = []
    for step in selected.steps:
        backups = []
        if step.kind == 'ADD' and SKILL.intersection(players[step.player_id].positions):
            for row in ranked:
                if not row.accepted or row.current.filled < selected.current.filled:
                    continue
                wanted = [s for s in row.steps if s.kind == 'ADD'
                          and s.drop_player_id == step.drop_player_id and s.player_id != step.player_id]
                others = {(s.kind,s.player_id,s.drop_player_id) for s in selected.steps
                          if s != step and SKILL.intersection(players[s.player_id].positions)}
                actual = {(s.kind,s.player_id,s.drop_player_id) for s in row.steps
                          if s not in wanted and SKILL.intersection(players[s.player_id].positions)}
                if actual == others:
                    backups.extend(s.player_id for s in wanted)
        # Complete failed-claim branches below are revalidated. Single-request
        # substitutions from screening remain comparisons, not executable
        # backup promises that could hide changed-roster safety dependencies.
        decorated.append(replace(step, alternatives=()))
    selected = replace(selected, steps=tuple(decorated))
    failure_branches = []
    if include_failure_branches and exact_pair is not None:
        branch = snapshot
        prerequisites = []
        for index, step in enumerate(selected.steps, 1):
            if step.kind == 'IR':
                bt = next(t for t in branch.teams if t.roster_id == team.roster_id)
                bt = replace(bt, reserve_ids=(*bt.reserve_ids, step.player_id))
                branch = replace(branch, teams=tuple(bt if t.roster_id == team.roster_id else t for t in branch.teams),
                    roster_capacity=tuple(_capacity(branch.league, bt, branch.players) if c.roster_id == team.roster_id else c for c in branch.roster_capacity))
            else:
                if SKILL.union({'K','DST','DEF'}).intersection(players[step.player_id].positions):
                    failed = replace(branch, acquisitions=tuple(replace(a, state='LOCKED',
                        evidence=(*a.evidence,'Conditional failed claim; excluded from this branch'))
                        if a.player_id == step.player_id else a for a in branch.acquisitions))
                    alternate = build_weekly_plan(failed, weeks=weeks, projections=projections, values=values,
                        evaluations=evaluations, policy=policy, planning_policy=planning_policy,
                        drop_legality=drop_legality, news_fresh=news_fresh, input_hash=input_hash,
                        exact_pair=exact_pair, include_failure_branches=False)
                    failure_branches.append({'failed_request':index, 'failed_player_id':step.player_id,
                        'excluded_player_ids': (step.player_id,),
                        'successful_prerequisites':tuple(prerequisites), 'replacement_plan':alternate.selected,
                        'coverage':alternate.coverage})
                branch = hypothetical_claim(branch, step.player_id, step.drop_player_id)
            prerequisites.append(step)
    fallback = None
    if availability:
        fallback_plan = build_weekly_plan(original, weeks=weeks, projections=projections, values=values,
            evaluations=evaluations, policy=policy, planning_policy=planning_policy,
            drop_legality=drop_legality, news_fresh=news_fresh, input_hash=input_hash,
            exact_pair=exact_pair, include_failure_branches=False)
        fallback = fallback_plan.selected
        notes.append('Availability is conditional; a platform-status fallback plan is retained.')
    result = WeeklyRosterPlan(1, snapshot.league_key, planning_policy, stable_hash(planning_policy),
        input_hash, 'WEEKLY_COVERAGE_WITH_ROS_GUARDS', baseline, selected, alternatives,
        len(comparisons), 'BOUNDED_LIMIT_REACHED' if exhausted else 'BOUNDED_COMPLETE', omitted,
        tuple(availability), fallback, tuple(notes), tuple(sorted(set(evidence_failures))), tuple(failure_branches))
    return replace(result, evidence_hash=stable_hash(asdict(result)))


def format_weekly_plan(plan, names):
    row = plan.selected
    lines = ['THIS WEEK - RECOMMENDED MOVES']
    if not row.steps:
        lines.append('Keep the roster; no supported material weekly improvement was established.')
    for index, step in enumerate(row.steps, 1):
        name = names.get(step.player_id, step.player_id)
        if step.kind == 'IR':
            lines.append(f'{index}. Move {name} to IR before the following claims.')
        else:
            drop = names.get(step.drop_player_id, step.drop_player_id) if step.drop_player_id else None
            lines.append(f'{index}. Add {name}' + (f' -> drop {drop}.' if drop else ' -> no drop; use the open spot.'))
            if step.alternatives:
                lines.append('   Backups for this request: ' + ', '.join(names.get(pid,pid) for pid in step.alternatives) + '.')
    lines.extend(['', f'Offensive coverage: {plan.baseline.filled}/{plan.baseline.required} -> {row.current.filled}/{row.current.required}.',
        f'Owned-player offense: {plan.baseline.points:.2f} -> {row.current.points:.2f} projected points this week; K/DST excluded.',
        f'Remaining-horizon owned-lineup change: {row.season_delta:+.2f} points.',
        f'Expert ROS ownership change: {row.selected_value_delta:+.2f}; consensus {row.market_value_delta:+.2f} (value units).'])
    if row.future_gaps:
        lines.append('Later coverage to address: ' + ', '.join(f'Week {week}: {gap} opening(s)' for week,gap in row.future_gaps) + '.')
    if row.return_drop_player_ids:
        lines.append('IR return requires a new roster decision; the forecast comparison assumes releasing ' + ', '.join(names.get(pid,pid) for pid in row.return_drop_player_ids) + '. Reassess when eligibility changes.')
    if plan.availability:
        lines.append('Conditional availability: ' + '; '.join(f"{names.get(r['player_id'],r['player_id'])} {r['status']} ({r['source']})" for r in plan.availability) + '.')
        if plan.fallback:
            lines.append('If those availability assumptions fail: ' + '; '.join(
                ('IR ' if s.kind=='IR' else 'add ') + names.get(s.player_id,s.player_id)
                + (f" / drop {names.get(s.drop_player_id,s.drop_player_id)}" if s.drop_player_id else '') for s in plan.fallback.steps) + '.')
    if plan.alternatives:
        lines.extend(['', 'MEANINGFUL ALTERNATIVES'])
        for other in plan.alternatives[:3]:
            description = '; '.join(('IR ' if s.kind=='IR' else 'add ') + names.get(s.player_id,s.player_id)
                + (f" / drop {names.get(s.drop_player_id,s.drop_player_id)}" if s.drop_player_id else '') for s in other.steps) or 'Keep roster'
            close = abs(other.current.points-row.current.points) <= plan.policy.weekly_close_margin
            lines.append(f'- {description}: {other.current.points:.2f} this week, {other.season_delta:+.2f} season; '
                         + ('close call. ' if close else '') + ('screened tradeoff; changed-roster verification required.' if other.accepted else ', '.join(other.reasons) + '.'))
    if plan.failed_claim_branches:
        lines.extend(['', 'IF A CLAIM FAILS'])
        for branch in plan.failed_claim_branches:
            replacement = branch['replacement_plan']
            revised = '; '.join(('IR ' if s.kind == 'IR' else 'add ') + names.get(s.player_id,s.player_id)
                + (f" / drop {names.get(s.drop_player_id,s.drop_player_id)}" if s.drop_player_id else '') for s in replacement.steps)
            lines.append(f"- If request {branch['failed_request']} fails after its prerequisites succeed: " + (revised or 'keep the remaining roster; no supported repair was found') + '.')
    lines.extend(['', 'Plan search: ' + plan.coverage + f'; {plan.evaluated_plans} roster comparisons.',
                  'Backup claims for the same request are alternatives; reassess after failed claims.',
                  *plan.evidence_notes])
    return '\n'.join(lines)
