"""Trade-only bounded screening. Estimates never become exact verdicts."""
from __future__ import annotations

from dataclasses import dataclass, replace

from roster_theory.trade.execution import cached, checkpoint
from roster_theory.inseason.evaluation import lineup_with_replacement_floor


@cached
def score_roster(context, matrix, roster, options):
    return sum(lineup_with_replacement_floor(context, matrix, roster, w.week,
        allow_partial=options.allow_partial_schedule).lineup.score
        * (options.playoff_weight if w.playoff else 1) for w in context.weeks)


def candidate_key(row):
    return (-row.estimated_user_lineup_gain, -row.estimated_partner_lineup_gain,
            row.fair_market_distance, len(row.sent_player_ids) + len(row.received_player_ids),
            row.opponent_roster_id, row.sent_player_ids, row.received_player_ids)


def diverse_prefix(rows, limit):
    """Give promising shapes and opponents a turn, not a whole shape a round."""
    ordered = sorted(rows, key=candidate_key)
    first = {}
    opponents = {}
    for row in ordered:
        first.setdefault(row.package_size, row)
        opponents.setdefault(row.opponent_roster_id, row)
    priority = sorted(set(first.values()) | set(opponents.values()), key=candidate_key)
    selected = priority[:limit]
    seen = set(selected)
    selected.extend(row for row in ordered if row not in seen and len(selected) < limit)
    return selected


@dataclass(frozen=True, slots=True)
class ScreeningResult:
    candidates: tuple
    checked: tuple
    rejected: tuple


def screen_candidates(rows, *, snapshot, context, matrix, bases, scores,
                      config, options, policy, selected, market_ecr):
    """Price first, then joint roster use; no risk scenarios or drop/add search.

    Adding without mandatory drops is an optimistic upper bound. A package
    opening slots receives a loose upper bound from the best free agents,
    keeping possible replacement-dependent gains eligible for final analysis.
    """
    prices_ok, rejected = [], []
    selected_values = {p.player_id: p.reconciled_vorp for p in selected.players}
    for row in rows:
        checkpoint()
        if row.pricing_mode in {'ECR-PROXY', 'PRIOR_WEEK_MARKET'}:
            rejected.append((row, 'current_chart_unavailable'))
        elif not row.fair_within_band:
            rejected.append((row, "chart_fairness"))
        elif len(row.sent_player_ids) == len(row.received_player_ids) and (
            sum(selected_values[p] for p in row.received_player_ids)
            - sum(selected_values[p] for p in row.sent_player_ids) < options.user_selected_floor
        ):
            rejected.append((row, "selected_value"))
        else:
            prices_ok.append(row)
    pool = diverse_prefix(prices_ok, policy.screening_pool_size)
    if not pool:
        return ScreeningResult((), (), tuple(rejected))
    scores = {rid: score_roster(context, matrix, roster, options) for rid, roster in bases.items()}
    upper = {}
    checked, promising = [], []
    # Total projected points is an intentionally loose bound: a waiver player
    # cannot add more lineup points than all of their own points in this horizon.
    available = set(snapshot.free_agent_ids) & selected_values.keys() & {
        p.player_id for p in market_ecr.players}
    waiver_totals = []
    for pid in available:
        cells = [matrix.cell(pid, w.week) for w in snapshot.weeks]
        if all(c is not None and c.points is not None for c in cells):
            waiver_totals.append(sum(c.points * (options.playoff_weight if w.playoff else 1)
                                     for c, w in zip(cells, snapshot.weeks)))
    waiver_totals.sort(reverse=True)
    for row in pool:
        checkpoint()
        gains = []
        for rid, sent, received in (
            (snapshot.user_roster_id, row.sent_player_ids, row.received_player_ids),
            (row.opponent_roster_id, row.received_player_ids, row.sent_player_ids),
        ):
            after = (bases[rid] - set(sent)) | set(received)
            gain = score_roster(context, matrix, after, options) - scores[rid]
            open_slots = max(0, len(sent) - len(received))
            upper[(rid, row.sent_player_ids, row.received_player_ids)] = gain + sum(waiver_totals[:open_slots])
            gains.append(gain)
        checked.append(row)
        if upper[(snapshot.user_roster_id, row.sent_player_ids, row.received_player_ids)] < config.minimum_user_lineup_gain:
            rejected.append((row, "lineup_upper_bound"))
            continue
        if upper[(row.opponent_roster_id, row.sent_player_ids, row.received_player_ids)] < config.partner_lineup_floor:
            rejected.append((row, "partner_lineup_upper_bound"))
            continue
        promising.append(replace(row, estimated_user_lineup_gain=gains[0],
                                 estimated_partner_lineup_gain=gains[1]))
    return ScreeningResult(tuple(diverse_prefix(promising, policy.shortlist_size)),
                           tuple(checked), tuple(rejected))
