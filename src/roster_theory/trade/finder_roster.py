"""Trade finder roster plausibility; exact football policy remains unchanged."""
from __future__ import annotations

from dataclasses import dataclass

from roster_theory.core.lineup import lineup_slots
from roster_theory.inseason.evaluation import depth_above_waiver, lineup_with_replacement_floor
from roster_theory.trade.consolidation import _final_roster
from roster_theory.trade.coverage import comparison_roster
from roster_theory.trade.execution import checkpoint
from roster_theory.trade.snapshot import SKILL_POSITIONS


ROSTER_POLICY_VERSION = "trade-finder-roster-v1"
MAX_ONE_STARTER_RESERVES = 1  # Existing Phase 10 Trade roster-context rule.


@dataclass(frozen=True, slots=True)
class IncomingUse:
    roster_id: str
    player_id: str
    starter_weeks: tuple[int, ...]
    lineup_delta: float
    depth_delta: float | None
    useful: bool


class RosterGuard:
    def __init__(self, snapshot, matrix, bases):
        self.snapshot = snapshot
        self.matrix = matrix
        self.bases = bases
        self.players = {p.player_id: p for p in snapshot.players}
        self.positions = tuple(sorted(SKILL_POSITIONS))
        slots = lineup_slots(snapshot.league.roster_positions)
        self.required = {p: sum(eligible == (p,) for _, eligible in slots)
                         for p in self.positions}
        self.capacity = {p: sum(p in eligible for _, eligible in slots)
                         for p in self.positions}
        self.viable = {pid for pid in self.players if any(
            (cell := matrix.cell(pid, w.week)) is not None
            and cell.points is not None and cell.points > 0 and cell.availability == "ACTIVE"
            for w in snapshot.weeks)}
        self.count_cache = {}
        self.before = {rid: self.counts(ids) for rid, ids in bases.items()}

    def counts(self, ids):
        key = tuple(sorted(ids))
        if key not in self.count_cache:
            all_counts = tuple(sum(p in self.players[pid].positions for pid in key
                                   if pid in self.players) for p in self.positions)
            viable_counts = tuple(sum(p in self.players[pid].positions for pid in key
                                      if pid in self.viable) for p in self.positions)
            self.count_cache[key] = all_counts, viable_counts
        return self.count_cache[key]

    def _failures(self, rid, all_after, viable_after, *, available_drops=0):
        all_before, viable_before = self.before[rid]
        failures = []
        for n, position in enumerate(self.positions):
            if viable_after[n] < min(self.required[position], viable_before[n]):
                failures.append(f"starter_coverage:{rid}:{position}")
            if (self.capacity[position] == 1 and all_after[n] > all_before[n]
                    and all_after[n] - available_drops > 1 + MAX_ONE_STARTER_RESERVES):
                failures.append(f"redundant_depth:{rid}:{position}")
        return tuple(failures)

    def exchange_failures(self, opponent, sent, received):
        """Check actual exchanged assets before any assumed free-agent addition."""
        outgoing, incoming = self.counts(sent), self.counts(received)
        failures = []
        for rid, removed, added, drops in ((self.snapshot.user_roster_id, outgoing, incoming,
                                           max(0, len(received) - len(sent))),
                                          (opponent, incoming, outgoing, max(0, len(sent) - len(received)))):
            before = self.before[rid]
            after = tuple(tuple(b - r + a for b, r, a in zip(before[k], removed[k], added[k]))
                          for k in (0, 1))
            # Mandatory drops may remove existing excess depth. Exact checks
            # verify the actual chosen drops; waiver additions never fix coverage.
            failures.extend(self._failures(rid, *after, available_drops=drops))
        return tuple(failures)

    def final_failures(self, evaluation):
        failures = []
        for impact in evaluation.team_impacts:
            rid = impact.roster_id
            final = _final_roster(self.snapshot, evaluation, rid)
            before_adds = set(final)
            for move in evaluation.secondary_moves:
                if move.roster_id == rid and move.kind == "ADD":
                    before_adds.difference_update(move.chosen_player_ids)
            all_after = self.counts(final)[0]
            viable_after = self.counts(before_adds)[1]
            failures.extend(self._failures(rid, all_after, viable_after))
        return tuple(failures)


def incoming_use(snapshot, context, matrix, evaluation, options, config):
    """Measure each acquired asset last, conditional on the complete final roster."""
    rows = []
    incoming = {evaluation.package.roster_a_id: evaluation.package.from_b,
                evaluation.package.roster_b_id: evaluation.package.from_a}
    for impact in evaluation.team_impacts:
        final = comparison_roster(snapshot, matrix, _final_roster(snapshot, evaluation, impact.roster_id))
        for asset in incoming[impact.roster_id]:
            checkpoint()
            pid = asset.player_id
            started = tuple(w.week for w in impact.weeks if pid in w.after_starters)
            delta = 0.0
            if pid in final and started:
                for week in impact.weeks:
                    checkpoint()
                    without = lineup_with_replacement_floor(context, matrix, final - {pid}, week.week,
                        allow_partial=options.allow_partial_schedule).lineup.score
                    delta += (week.after_points - without) * week.weight
            delta = round(delta, 3)
            depth_delta = None
            if pid in final and delta <= config.minimum_partner_asset_lineup_use:
                checkpoint()
                depth_delta = round(impact.after_depth_above_waiver -
                    depth_above_waiver(context, matrix, final - {pid}, options), 3)
            useful = pid in final and (delta > config.minimum_partner_asset_lineup_use
                or (depth_delta is not None and depth_delta > config.minimum_partner_asset_depth_use))
            rows.append(IncomingUse(impact.roster_id, pid, started, delta, depth_delta, useful))
    return tuple(rows)


def qb_bundle_gain(context, matrix, before_qbs, after_qbs, options):
    """Joint QB-slot delta for one-QB formats; no independent duplicate credit."""
    def points(ids, week):
        return max((float(cell.points) for pid in ids
            if (cell := matrix.cell(pid, week)) is not None
            and cell.points is not None), default=0.0)
    return round(sum((points(after_qbs, w.week) - points(before_qbs, w.week))
        * (options.playoff_weight if w.playoff else 1.0) for w in context.weeks), 3)
