"""Timed, opponent-fair baseline package search with unchanged exact gates."""
from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections import deque
from dataclasses import asdict, dataclass, replace
from itertools import combinations
from time import perf_counter

from roster_theory.core.errors import CoverageIncomplete, RosterIllegal
from roster_theory.core.provenance import stable_hash
from roster_theory.inseason.evaluation import build_weekly_projection_matrix, weighted_lineup_score
from roster_theory.trade.consolidation import analyze_consolidation, _final_roster
from roster_theory.trade.coverage import comparison_roster, roster_projection_exclusions
from roster_theory.trade.evaluation import (
    PlayerAsset, TradePackage, TradeEvaluation, diagnose_roster, evaluate_trade, _team_impact,
)
from roster_theory.trade.execution import (
    FinderExecutionPolicy, SearchDeadline, SearchExecution, cached, checkpoint, search_execution,
)
from roster_theory.trade.snapshot import assert_current
from roster_theory.trade.target_optimizer import (
    TargetPackageSearchResult, TargetPackageOpportunity, TargetPackageStatus,
    EvaluatedPackageDecision, _Candidate, _context, _eligible_players, _price_map,
    _fairness, _exact_decision,
)


SHAPES = tuple((a, b) for a in range(1, 4) for b in range(1, 4))
weighted_lineup_score = cached(weighted_lineup_score)


@dataclass(frozen=True, slots=True)
class FinderScope:
    mode: str
    opponent_roster_ids: tuple[str, ...]
    opponent_team_names: tuple[str, ...]


def resolve_scope(snapshot, opponent: str | None) -> FinderScope:
    teams = sorted(snapshot.teams, key=lambda t: t.roster_id)
    choices = ", ".join(f"{t.roster_id}: {t.display_name}" for t in teams
                        if t.roster_id != snapshot.user_roster_id)
    if opponent is None:
        selected = [t for t in teams if t.roster_id != snapshot.user_roster_id]
        mode = "LEAGUE"
    else:
        # An exact roster ID takes precedence over a display name.
        selected = [t for t in teams if t.roster_id == opponent]
        if not selected:
            selected = [t for t in teams if t.display_name == opponent]
        if len(selected) != 1 or selected[0].roster_id == snapshot.user_roster_id:
            raise ValueError(f"Opponent must be one other roster ID or an unambiguous exact team name. Valid opponents: {choices}")
        mode = "OPPONENT"
    return FinderScope(mode, tuple(t.roster_id for t in selected),
                       tuple(t.display_name for t in selected))


@dataclass(frozen=True, slots=True)
class FinderCoverage:
    opponent_roster_id: str
    package_size: str
    enumerated: int = 0
    price_pruned: int = 0
    eligible: int = 0
    attempted: int = 0
    evaluated: int = 0
    unevaluated: int = 0
    errors: int = 0
    execution_cap: int | None = None
    pool_limited: bool = False
    construction_complete: bool = False
    status: str = "UNEVALUATED"
    unconstructed: int = 0
    repair_attempted: int = 0
    repair_evaluated: int = 0


@dataclass(frozen=True, slots=True)
class CounterRepair:
    sent_player_ids: tuple[str, ...]
    received_player_ids: tuple[str, ...]
    status: str
    package_verdict: str | None
    failed_checks: tuple[str, ...]
    evaluation_hash: str


@dataclass(frozen=True, slots=True)
class TradeIdea:
    status: str
    decision: EvaluatedPackageDecision
    failed_checks: tuple[str, ...]
    evaluation: TradeEvaluation
    repairs: tuple[CounterRepair, ...] = ()
    repair_search_status: str = "NOT_NEEDED"


@dataclass(frozen=True, slots=True)
class FinderResult(TargetPackageSearchResult):
    ideas: tuple[TradeIdea, ...] = ()
    scope: FinderScope | None = None
    execution_profile: dict | None = None
    shape_coverage: tuple[FinderCoverage, ...] = ()
    timing: dict | None = None
    termination: str = "EXHAUSTED"
    repair_attempted: int = 0
    repair_evaluated: int = 0


def failed_checks(decision: EvaluatedPackageDecision, minimum_gain: float | None = None) -> tuple[str, ...]:
    failures = [g.name for g in decision.decision_axes.gates if not g.passed] if decision.decision_axes else ["decision_unavailable"]
    if not decision.market_fairness.within_band:
        failures.append("chart_fairness")
    if decision.market_fairness.mode == "PRIOR_WEEK_MARKET":
        failures.append("current_market_unavailable")
    if not decision.partner_plausible:
        failures.append("partner_plausibility")
    if decision.received_asset_dropped:
        failures.append("received_asset_dropped")
    if decision.consolidation is not None and not decision.consolidation.passes:
        failures.append("consolidation_usefulness")
    if decision.reason == "SEARCH_MINIMUM_LINEUP_GAIN" or (minimum_gain is not None and decision.user_weighted_lineup_delta < minimum_gain):
        failures.append("minimum_lineup_gain")
    return tuple(dict.fromkeys(failures))


def idea_status(decision: EvaluatedPackageDecision, *, minimum_gain: float,
                partner_assets_used: bool = True) -> str | None:
    if (not decision.complete_and_legal or decision.package_verdict not in {"ACCEPTABLE", "COUNTER"}
            or decision.market_fairness.mode in {"PRIOR_WEEK_MARKET", "ECR-PROXY"}
            or decision.intrinsic_outcome == "CONDITIONAL"):
        return None
    if decision.accepted:
        return "RECOMMENDED"
    if decision.package_verdict != "COUNTER" or decision.user_weighted_lineup_delta <= 0:
        return None
    failures = failed_checks(decision, minimum_gain)
    if (failures == ("partner_market_delta",)
            and decision.user_weighted_lineup_delta >= minimum_gain
            and decision.partner_weighted_lineup_delta > 0
            and decision.intrinsic_outcome == "WIN"
            and decision.market_fairness.status == "FAIR"
            and partner_assets_used):
        return "NEGOTIATION_CANDIDATE"
    return "COUNTEROFFER_IDEA"


def idea_sort_key(idea: TradeIdea):
    row = idea.decision
    return ({"RECOMMENDED": 0, "NEGOTIATION_CANDIDATE": 1, "COUNTEROFFER_IDEA": 2}[idea.status],
            -row.user_weighted_lineup_delta, -row.partner_weighted_lineup_delta,
            row.user_downside_delta, abs(row.market_fairness.user_price_delta),
            len(row.sent_player_ids) + len(row.received_player_ids), row.opponent_roster_id,
            row.sent_player_ids, row.received_player_ids)


def rank_ideas(ideas, scope: FinderScope, limit: int) -> tuple[TradeIdea, ...]:
    ordered = sorted(ideas, key=idea_sort_key)
    if scope.mode == "OPPONENT":
        return tuple(ordered[:limit])
    # Choose a representative for each opponent, but keep verdict tiers ordered.
    representatives = {}
    for idea in ordered:
        representatives.setdefault(idea.decision.opponent_roster_id, idea)
    selected = sorted(representatives.values(), key=idea_sort_key)[:limit]
    selected.extend(i for i in ordered if i not in selected and len(selected) < limit)
    return tuple(sorted(selected, key=idea_sort_key))


def _bundles(ids, prices):
    return {size: tuple(sorted((sum(prices[p] for p in group), tuple(group))
                              for group in combinations(sorted(ids), size)))
            for size in range(1, 4)}


def _price_range(sent_value, ratio, floor, premium):
    if ratio >= 1:
        return float("-inf"), float("inf")
    allowance = ratio * max(sent_value, 1.0)
    # ECR proxy prices can be negative; the fairness denominator floors at 1.
    epsilon = 0.000001 / (1 - ratio)
    return ((min(sent_value - floor, sent_value - allowance) - epsilon) / premium,
            (max(sent_value + floor, sent_value + allowance, sent_value / (1 - ratio)) + epsilon) / premium)


def one_edit_packages(sent, received, outgoing, incoming):
    """Finite direct neighbors only; repairs never generate further repairs."""
    seen = set()
    for side, original, pool in ((0, sent, outgoing), (1, received, incoming)):
        variants = []
        if len(original) < 3:
            variants.extend(tuple(sorted((*original, p))) for p in pool if p not in original)
        if len(original) > 1:
            variants.extend(tuple(p for p in original if p != old) for old in original)
        variants.extend(tuple(sorted((*[p for p in original if p != old], new)))
                        for old in original for new in pool if new not in original)
        for variant in variants:
            pair = (variant, received) if side == 0 else (sent, variant)
            if pair != (sent, received) and pair not in seen:
                seen.add(pair)
                yield pair


def find_trade_packages(snapshot, *, projections, selected_board, market_ecr_board,
                        trade_market, target_result, config, options, scope: FinderScope,
                        execution_policy: FinderExecutionPolicy = FinderExecutionPolicy(),
                        execution: SearchExecution | None = None, time_budget_seconds=None,
                        max_exact=None, max_large_exact=None, max_results=None,
                        metrics=None) -> FinderResult:
    """Build baseline candidates independently of target lanes, then evaluate fairly."""
    assert_current(snapshot)
    if (target_result.manifest_id != snapshot.manifest.analysis_id
            or target_result.horizon != snapshot.ranking_horizon
            or selected_board.horizon != snapshot.ranking_horizon
            or market_ecr_board.horizon != snapshot.ranking_horizon):
        raise CoverageIncomplete("Finder inputs do not share a snapshot and horizon")
    if not selected_board.complete or not market_ecr_board.complete:
        raise CoverageIncomplete("Finder requires complete value boards")
    if set(scope.opponent_roster_ids) - {t.roster_id for t in snapshot.teams} or snapshot.user_roster_id in scope.opponent_roster_ids:
        raise ValueError("Invalid finder scope")
    for cap in (max_exact, max_large_exact):
        if cap is not None and cap < 0:
            raise ValueError("Exact evaluation caps cannot be negative")
    if max_results is not None and not 1 <= max_results <= 10:
        raise ValueError("--max-results must be between 1 and 10")
    seconds = time_budget_seconds if time_budget_seconds is not None else (
        execution_policy.opponent_seconds if scope.mode == "OPPONENT" else execution_policy.league_seconds)
    execution = execution or SearchExecution(seconds, stable_hash((snapshot, projections,
        selected_board, market_ecr_board, trade_market, config, options, snapshot.ranking_horizon)))
    with search_execution(execution):
        return _find(snapshot, projections, selected_board, market_ecr_board, trade_market,
                     target_result, config, options, scope, execution_policy, execution,
                     max_exact, max_large_exact, max_results, metrics)


def _find(snapshot, projections, selected, market_ecr, market, targets, config, options,
          scope, policy, execution, max_exact, max_large_exact, max_results, metrics):
    started = perf_counter()
    stages = {}
    groups = {(rid, f"{a}-for-{b}"): FinderCoverage(rid, f"{a}-for-{b}",
              execution_cap=max_exact if b == 1 and a <= 2 else max_large_exact)
              for a, b in SHAPES for rid in scope.opponent_roster_ids}
    queues = {key: [] for key in groups}
    decisions, ideas, opportunities = [], [], []
    evaluations = {}
    repairs = {}
    repair_queue = deque()
    repair_status = {}
    repair_caps = set()
    repair_attempted = repair_evaluated = 0
    errors = []
    termination = "EXHAUSTED"
    context = _context(snapshot)
    matrix = build_weekly_projection_matrix(context, projections)
    roster_exclusions = tuple(r for r in roster_projection_exclusions(snapshot, matrix)
                             if r.roster_id in {snapshot.user_roster_id, *scope.opponent_roster_ids})
    teams = {t.roster_id: t for t in snapshot.teams
             if t.roster_id in {snapshot.user_roster_id, *scope.opponent_roster_ids}}
    player_by_id = {p.player_id: p for p in snapshot.players}
    valued = {r.player_id for r in selected.players} & {r.player_id for r in market_ecr.players}
    prices, pricing_mode, price_warnings = _price_map(targets, market, market_ecr, set())
    excluded = set(dict(snapshot.player_exclusions))
    eligible = {rid: tuple(p for p in _eligible_players(snapshot, team, valued)
                         if p in prices and p not in excluded and all(
                             (cell := matrix.cell(p, w.week)) is not None and cell.points is not None
                             for w in snapshot.weeks)) for rid, team in teams.items()}
    diagnoses = {}
    target_tags = {(t.roster.owner_roster_id, t.player_id): t.kind for t in targets.targets}

    def fairness(sent, received, ratio, floor):
        return _fairness(sent, received, prices, pricing_mode, ratio, floor, price_warnings,
                         consolidation=len(sent) > 1 and len(received) == 1,
                         premium_policy_id=config.consolidation_premium_policy_id,
                         premium_ratio=config.consolidation_premium_ratio)

    def candidate(rid, sent, received, user_gain=0.0, partner_gain=0.0):
        fair = fairness(sent, received, config.fair_market_band_ratio, config.fair_market_band_floor)
        return _Candidate("BASELINE", received[0], 0,
            tuple(p for p in (*sent, *received) if (rid, p) in target_tags or (snapshot.user_roster_id, p) in target_tags),
            rid, sent, received, f"{len(sent)}-for-{len(received)}", pricing_mode,
            abs(fair.raw_user_price_delta), abs(fair.user_price_delta), fair.within_band,
            user_gain, partner_gain, 0, True)

    def evaluate(row):
        checkpoint()
        key = (row.opponent_roster_id, row.sent_player_ids, row.received_player_ids)
        if key in evaluations:
            return evaluations[key]
        package = TradePackage(snapshot.user_roster_id, row.opponent_roster_id,
            tuple(PlayerAsset(p) for p in row.sent_player_ids),
            tuple(PlayerAsset(p) for p in row.received_player_ids))
        result = evaluate_trade(snapshot, package, projections=projections,
            selected_board=selected, market_board=market_ecr, options=options, projection_matrix=matrix)
        fair = fairness(row.sent_player_ids, row.received_player_ids,
                        config.fair_market_band_ratio, config.fair_market_band_floor)
        consolidation = analyze_consolidation(snapshot, result, context=context, matrix=matrix,
            options=options, minimum_starter_upgrade=config.minimum_consolidation_starter_upgrade,
            minimum_partner_lineup_use=config.minimum_partner_asset_lineup_use,
            minimum_partner_depth_use=config.minimum_partner_asset_depth_use
        ) if len(row.sent_player_ids) > 1 and len(row.received_player_ids) == 1 else None
        decision = _exact_decision(candidate=row, evaluation=result, fairness=fair,
            consolidation=consolidation, diagnoses=diagnoses, player_by_id=player_by_id,
            config=config, options=options)
        partner_used = True
        if failed_checks(decision) == ("partner_market_delta",):
            final = comparison_roster(snapshot, matrix, _final_roster(snapshot, result, row.opponent_roster_id))
            for pid in row.sent_player_ids:
                checkpoint()
                if pid not in final:
                    partner_used = False
                    break
                impact = _team_impact(snapshot, matrix, row.opponent_roster_id, final - {pid}, final, options)
                if not (impact.weighted_delta > config.minimum_partner_asset_lineup_use
                        or impact.depth_delta > config.minimum_partner_asset_depth_use):
                    partner_used = False
        checkpoint()
        status = idea_status(decision, minimum_gain=config.minimum_user_lineup_gain,
                             partner_assets_used=partner_used)
        failures = failed_checks(decision, config.minimum_user_lineup_gain)
        if not partner_used:
            failures = (*failures, "partner_asset_use")
        evaluations[key] = (decision, result, status, failures)
        decisions.append(decision)
        if status:
            ideas.append(TradeIdea(status, decision, failures, result,
                                  repair_search_status="PENDING" if status == "COUNTEROFFER_IDEA" else "NOT_NEEDED"))
        if decision.accepted:
            opportunities.append(TargetPackageOpportunity(
                row.lane, row.primary_target_player_id, row.generated_by_target_ids,
                row.opponent_roster_id, row.package_size, row.sent_player_ids, row.received_player_ids,
                decision.intrinsic_outcome, fair, consolidation, ("BASELINE",),
                decision.user_weighted_lineup_delta, float(decision.user_selected_delta),
                decision.user_market_ecr_delta, decision.cross_model_agreement,
                decision.user_depth_delta, decision.user_downside_delta,
                decision.partner_weighted_lineup_delta, float(decision.partner_selected_delta),
                decision.partner_depth_delta, decision.forced_add, decision.forced_drop, result))
        return evaluations[key]

    def process_repair(origin, row):
        nonlocal repair_attempted, repair_evaluated
        repair_status[origin] = 'IN_PROGRESS'
        checkpoint()
        group_key = (row.opponent_roster_id, row.package_size)
        coverage = groups[group_key]
        cached_key = (row.opponent_roster_id, row.sent_player_ids, row.received_player_ids)
        if (cached_key not in evaluations and coverage.execution_cap is not None
                and coverage.attempted + coverage.repair_attempted >= coverage.execution_cap):
            repair_status[origin] = 'EXACT_CAP'
            repair_caps.add(origin)
            return
        repair_status[origin] = 'IN_PROGRESS'
        repair_attempted += 1
        groups[group_key] = replace(coverage, repair_attempted=coverage.repair_attempted + 1)
        try:
            decision, evaluation, status, failures = evaluate(row)
        except (CoverageIncomplete, RosterIllegal) as exc:
            errors.append(f"Counter repair: {type(exc).__name__}: {exc}")
        else:
            repair_evaluated += 1
            groups[group_key] = replace(groups[group_key], repair_evaluated=groups[group_key].repair_evaluated + 1)
            repairs.setdefault(origin, []).append(CounterRepair(row.sent_player_ids,
                row.received_player_ids, status or 'FAILED_CHECKS', decision.package_verdict,
                failures, evaluation.evidence_hash))
        if repair_status.get(origin) != 'EXACT_CAP':
            repair_status[origin] = 'CHECKED'

    try:
        for rid in teams:
            checkpoint()
            diagnoses[rid] = diagnose_roster(snapshot, projections, roster_id=rid, options=options,
                                             projection_matrix=matrix, protect_missing=True)
        bases = {rid: comparison_roster(snapshot, matrix, set(t.player_ids) - set(t.reserve_ids))
                 for rid, t in teams.items()}
        scores = {rid: weighted_lineup_score(context, matrix, roster, options) for rid, roster in bases.items()}
        marginal = {}
        for rid in scope.opponent_roster_ids:
            for owner, other in ((snapshot.user_roster_id, rid), (rid, snapshot.user_roster_id)):
                for pid in eligible[owner]:
                    checkpoint()
                    cost = scores[owner] - weighted_lineup_score(context, matrix, bases[owner] - {pid}, options)
                    gain = weighted_lineup_score(context, matrix, bases[other] | {pid}, options) - scores[other]
                    marginal[(rid, pid)] = (cost, gain)
        stages["setup"] = perf_counter() - started
        pools = {}
        for rid in scope.opponent_roster_ids:
            outgoing = eligible[snapshot.user_roster_id]
            incoming = eligible[rid]
            if scope.mode == "LEAGUE":
                outgoing = tuple(sorted(outgoing, key=lambda p: (marginal[(rid, p)][0], -marginal[(rid, p)][1], p)))[:config.outgoing_pool_limit]
                incoming = tuple(sorted(incoming, key=lambda p: (-marginal[(rid, p)][1], marginal[(rid, p)][0], p)))[:config.incoming_pool_limit]
            pools[rid] = (outgoing, incoming)
        full_out = _bundles(eligible[snapshot.user_roster_id], prices)
        out_bundles = {rid: _bundles(pools[rid][0], prices) for rid in scope.opponent_roster_ids}
        in_bundles = {rid: _bundles(pools[rid][1], prices) for rid in scope.opponent_roster_ids}
        full_in = {rid: _bundles(eligible[rid], prices) for rid in scope.opponent_roster_ids}
        # Round-robin construction prevents a large opponent from monopolizing
        # generation. Values are indexed once, before any package lineup work.
        builders = {}
        for key in groups:
            rid, shape = key
            a, b = map(int, shape.split("-for-"))
            outgoing = full_out[a] if a == b == 1 else out_bundles[rid][a]
            incoming = full_in[rid][b] if a == b == 1 else in_bundles[rid][b]
            groups[key] = replace(groups[key], enumerated=len(outgoing) * len(incoming),
                pool_limited=(len(outgoing) != len(full_out[a]) or len(incoming) != len(full_in[rid][b])))
            builders[key] = (iter(outgoing), incoming, tuple(v for v, _ in incoming), a, b)
        active = deque(builders)
        while active:
            checkpoint()
            key = active.popleft()
            rid, shape = key
            iterator, incoming, values, a, b = builders[key]
            try:
                sent_value, sent = next(iterator)
            except StopIteration:
                groups[key] = replace(groups[key], construction_complete=True)
                continue
            premium = 1 + config.consolidation_premium_ratio if a > 1 and b == 1 and pricing_mode not in {"ECR-PROXY", "PRIOR_WEEK_MARKET"} else 1
            low, high = _price_range(sent_value, config.construction_market_band_ratio,
                                    config.construction_market_band_floor, premium)
            left, right = bisect_left(values, low), bisect_right(values, high)
            count = 0
            for _, received in incoming[left:right]:
                checkpoint()
                broad = fairness(sent, received, config.construction_market_band_ratio, config.construction_market_band_floor)
                if not broad.within_band:
                    continue
                user_gain = sum(marginal[(rid, p)][1] for p in received) - sum(marginal[(rid, p)][0] for p in sent)
                partner_gain = sum(marginal[(rid, p)][1] for p in sent) - sum(marginal[(rid, p)][0] for p in received)
                queues[key].append(candidate(rid, sent, received, user_gain, partner_gain))
                count += 1
            groups[key] = replace(groups[key], price_pruned=groups[key].price_pruned + len(incoming) - count,
                                  eligible=groups[key].eligible + count)
            active.append(key)
        stages["construction"] = perf_counter() - started - stages["setup"]
        for key in queues:
            queues[key] = deque(sorted(queues[key], key=lambda c: (
                not (c.fair_within_band and c.estimated_user_lineup_gain > 0 and c.estimated_partner_lineup_gain > 0),
                not c.fair_within_band,
                -c.estimated_user_lineup_gain, -c.estimated_partner_lineup_gain,
                c.fair_market_distance, c.sent_player_ids, c.received_player_ids)))
        active = deque(key for key in groups if queues[key])
        turns = 0
        while active:
            checkpoint()
            key = active.popleft()
            coverage = groups[key]
            if coverage.execution_cap is not None and coverage.attempted + coverage.repair_attempted >= coverage.execution_cap:
                continue
            row = queues[key].popleft()
            groups[key] = replace(coverage, attempted=coverage.attempted + 1)
            try:
                decision, evaluation, status, failures = evaluate(row)
            except (CoverageIncomplete, RosterIllegal) as exc:
                errors.append(f"Roster {key[0]} {key[1]}: {type(exc).__name__}: {exc}")
                groups[key] = replace(groups[key], errors=groups[key].errors + 1)
            else:
                groups[key] = replace(groups[key], evaluated=groups[key].evaluated + 1)
                if status == "COUNTEROFFER_IDEA" and policy.repairs_per_counter:
                    repair_status[evaluation.evidence_hash] = 'PENDING'
                    neighbors = []
                    for sent, received in one_edit_packages(row.sent_player_ids, row.received_player_ids,
                            eligible[snapshot.user_roster_id], eligible[row.opponent_roster_id]):
                        checkpoint()
                        fair = fairness(sent, received, config.fair_market_band_ratio, config.fair_market_band_floor)
                        neighbors.append((not fair.within_band, abs(fair.user_price_delta), sent, received))
                    for _, _, sent, received in sorted(neighbors)[:policy.repairs_per_counter]:
                        repair_queue.append((evaluation.evidence_hash, candidate(row.opponent_roster_id, sent, received)))
            if queues[key]:
                active.append(key)
            turns += 1
            # Primary opponents/shapes receive a full round before repair work.
            if repair_queue and (turns % max(1, len(scope.opponent_roster_ids)) == 0 or not active):
                origin, repair = repair_queue.popleft()
                process_repair(origin, repair)
        while repair_queue:
            checkpoint()
            origin, repair = repair_queue.popleft()
            process_repair(origin, repair)
    except SearchDeadline:
        termination = "TIME_BUDGET"
    stages["exact"] = max(0, perf_counter() - started - sum(stages.values()))
    coverage = tuple(replace(c, unevaluated=c.eligible - c.evaluated,
        unconstructed=max(0, c.enumerated - c.price_pruned - c.eligible),
        status="EXHAUSTED" if c.construction_complete and c.evaluated + c.errors == c.eligible
        else "EXACT_CAP" if c.execution_cap is not None and c.attempted + c.repair_attempted >= c.execution_cap
        else "TIME_BUDGET" if termination == "TIME_BUDGET" else "UNEVALUATED") for c in groups.values())
    if any(c.status == "EXACT_CAP" for c in coverage) and termination != "TIME_BUDGET":
        termination = "EXACT_CAP"
    pending_origins = {origin for origin, _ in repair_queue}
    def final_repair_status(idea):
        if idea.status != 'COUNTEROFFER_IDEA':
            return 'NOT_NEEDED'
        origin = idea.evaluation.evidence_hash
        if origin in pending_origins or repair_status.get(origin) == 'IN_PROGRESS':
            return 'TIME_BUDGET'
        if origin in repair_caps:
            return 'EXACT_CAP'
        return 'BOUNDED_COMPLETE' if origin in repair_status else 'NOT_SEARCHED'
    ideas = [replace(i, repairs=tuple(repairs.get(i.evaluation.evidence_hash, ())),
                     repair_search_status=final_repair_status(i)) for i in ideas]
    chosen = rank_ideas(ideas, scope, max_results or policy.max_ideas)
    statuses = tuple(TargetPackageStatus(t.kind, t.player_id,
        "OFFER_FOUND" if any(d.accepted and t.player_id in (*d.sent_player_ids, *d.received_player_ids) for d in decisions) else "WATCH",
        any(d.accepted and t.player_id in (*d.sent_player_ids, *d.received_player_ids) for d in decisions),
        sum(d.accepted and t.player_id in (*d.sent_player_ids, *d.received_player_ids) for d in decisions), False) for t in targets.targets)
    timing = {"stage_seconds": {k: round(v, 3) for k, v in stages.items()},
              "search_seconds": round(execution.elapsed, 3), "cache_hits": execution.hits,
              "cache_misses": execution.misses}
    warnings = tuple(dict.fromkeys((*targets.warnings, *price_warnings, *errors,
        "Ideas retain strict package verdicts; negotiation and counteroffer ideas are not passing offers.",
        "Coverage is limited by execution time, pools and secondary-move search; unevaluated packages may be better.")))
    base = FinderResult(3, snapshot.manifest.analysis_id, snapshot.league_key,
        snapshot.ranking_horizon, targets.evidence_hash, pricing_mode, config, statuses, (),
        tuple(opportunities), tuple(decisions), (), (), warnings, "", roster_exclusions,
        chosen, scope, {**asdict(policy), "mode": scope.mode, "time_budget_seconds": execution.seconds,
                       "max_exact": max_exact, "max_large_exact": max_large_exact},
        coverage, timing, termination, repair_attempted, repair_evaluated)
    if metrics is not None:
        metrics.update(timing)
        metrics['coverage'] = {'evaluated': len(decisions), 'attempted': sum(c.attempted for c in coverage),
                               'unevaluated': sum(c.unevaluated for c in coverage),
                               'unconstructed': sum(c.unconstructed for c in coverage)}
    return replace(base, evidence_hash=stable_hash(asdict(base)))
