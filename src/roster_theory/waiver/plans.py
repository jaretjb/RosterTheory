"""Conditional, read-only validation of a canonical claim sequence.

Single-move approvals are alternatives until tested against the changed roster.
This module validates one deterministic branch, not every possible claim outcome.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Callable, Sequence

from roster_theory.core.errors import CoverageIncomplete, RosterIllegal
from roster_theory.inseason.evaluation import (
    InSeasonContext,
    WeeklyProjectionMatrix,
    risk_impact,
    team_impact,
)
from roster_theory.waiver.evaluation import WaiverEvaluation, WaiverEvaluationOptions
from roster_theory.waiver.policy import WaiverDecisionPolicy
from roster_theory.waiver.snapshot import WaiverSnapshot


@dataclass(frozen=True, slots=True)
class ClaimBranchCheck:
    priorities: tuple[int, ...]
    accepted: bool
    reason: str
    cumulative_lineup_delta: float | None = None
    cumulative_current_week_delta: float | None = None
    cumulative_depth_delta: float | None = None
    cumulative_downside_delta: float | None = None


def hypothetical_claim(snapshot: WaiverSnapshot, add: str, drop: str | None) -> WaiverSnapshot:
    """Update all roster/ownership views; never make a drop an instant free agent."""
    team = next(row for row in snapshot.teams if row.roster_id == snapshot.user_roster_id)
    capacity = next(row for row in snapshot.roster_capacity if row.roster_id == team.roster_id)
    if add in dict(snapshot.owner_by_player):
        raise RosterIllegal("Target already owned on this branch")
    if drop is None and capacity.open_active_slots < 1:
        raise RosterIllegal("Open slot already consumed on this branch")
    if drop is not None and (drop not in team.player_ids or drop in team.reserve_ids):
        raise RosterIllegal("Drop is no longer active on this branch")
    owners = dict(snapshot.owner_by_player)
    if drop is not None:
        owners.pop(drop, None)
    owners[add] = team.roster_id
    updated_team = replace(
        team,
        player_ids=tuple(sorted((set(team.player_ids) - {drop}) | {add})),
        starter_ids=tuple(pid for pid in team.starter_ids if pid != drop),
    )
    used = int(drop is None)
    return replace(
        snapshot,
        teams=tuple(
            updated_team if row.roster_id == team.roster_id else row for row in snapshot.teams
        ),
        owner_by_player=tuple(sorted(owners.items())),
        roster_capacity=tuple(
            replace(
                row,
                active_count=row.active_count + used,
                open_active_slots=row.open_active_slots - used,
            )
            if row.roster_id == team.roster_id
            else row
            for row in snapshot.roster_capacity
        ),
        acquisitions=tuple(
            replace(
                row,
                state="LOCKED",
                owner_roster_id=owners.get(row.player_id),
                evidence=("Conditional hypothetical claim; availability requires refresh",),
            )
            if row.player_id in {add, drop}
            else row
            for row in snapshot.acquisitions
        ),
    )


def validate_claim_branch(
    snapshot: WaiverSnapshot,
    evaluations: Sequence[WaiverEvaluation],
    *,
    evaluate_pair: Callable[[WaiverSnapshot, str, str | None], WaiverEvaluation],
    context: InSeasonContext,
    matrix: WeeklyProjectionMatrix,
    roster_player_ids: set[str],
    options: WaiverEvaluationOptions,
    policy: WaiverDecisionPolicy,
) -> tuple[ClaimBranchCheck, ...]:
    """Try approved pairs in canonical order, retaining only safe cumulative prefixes.

    Each attempted sequence explicitly records its prerequisite successful claims.
    Other combinations/outcomes remain unvalidated and require a new report.
    """
    current = snapshot
    before = set(roster_player_ids)
    after = set(before)
    added: set[str] = set()
    prefix: tuple[int, ...] = ()
    checks: list[ClaimBranchCheck] = []
    skills = {
        row.player_id
        for row in snapshot.players
        if set(row.positions).intersection({"QB", "RB", "WR", "TE"})
    }
    for priority, original in enumerate(evaluations, 1):
        add, drop = original.add_player_id, original.selected_drop_player_id
        sequence = (*prefix, priority)
        try:
            proposed = hypothetical_claim(current, add, drop)
            # The first pair already has exact evidence; later pairs must be re-run.
            evaluation = evaluate_pair(current, add, drop) if prefix else original
            if evaluation.selected_drop_player_id != drop:
                raise RosterIllegal("Re-evaluation changed the required drop")
            if evaluation.decision_label not in {"ADD NOW", "CLAIM", "ACQUIRE"}:
                checks.append(
                    ClaimBranchCheck(
                        sequence,
                        False,
                        f"Changed-roster evaluation is {evaluation.decision_label}: {evaluation.strongest_uncertainty}",
                    )
                )
                continue
            proposed_roster = (after - {drop}) | {add}
            impact = team_impact(
                context,
                matrix,
                snapshot.user_roster_id,
                before,
                proposed_roster,
                options,
                replacement_exclusions=tuple(sorted(added | {add})),
            )
            risk = risk_impact(
                context,
                matrix,
                snapshot.user_roster_id,
                before & skills,
                proposed_roster & skills,
                options,
            )
            current_week = next(
                row.delta for row in impact.weeks if row.week == context.current_week
            )
            # Never accumulate multiple individually allowed losses beyond one
            # policy's total risk budget. Same-specialist streaming can be seasonal
            # negative, but that exception does not authorize a multi-claim loss.
            failed = []
            if prefix:
                if impact.weighted_delta < policy.priority_minimum_lineup_gain:
                    failed.append("cumulative lineup loss")
                if current_week < -policy.maximum_current_week_loss:
                    failed.append("cumulative current-week loss")
                if impact.depth_delta < -policy.maximum_depth_loss:
                    failed.append("cumulative depth loss")
                if risk.offense_downside_loss_delta > policy.maximum_downside_increase:
                    failed.append("cumulative downside increase")
            accepted = not failed
            checks.append(
                ClaimBranchCheck(
                    sequence,
                    accepted,
                    "; ".join(failed)
                    if failed
                    else "Validated only after exactly this successful claim prefix",
                    impact.weighted_delta,
                    current_week,
                    impact.depth_delta,
                    risk.offense_downside_loss_delta,
                )
            )
            if accepted:
                current, after = proposed, proposed_roster
                added.add(add)
                prefix = sequence
        except (CoverageIncomplete, RosterIllegal) as exc:
            checks.append(ClaimBranchCheck(sequence, False, str(exc)))
    return tuple(checks)
