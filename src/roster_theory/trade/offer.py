"""Attach the finder's final pricing and roster checks to entered evaluations."""
from __future__ import annotations

from dataclasses import asdict, replace
from pathlib import Path

from roster_theory.core.errors import RosterTheoryError
from roster_theory.core.provenance import stable_hash
from roster_theory.trade.evaluation import diagnose_roster
from roster_theory.trade.finder import assess_trade_offer
from roster_theory.trade.market import resolve_trade_market_evidence
from roster_theory.trade.target_optimizer import _Candidate, _context, _fairness
from roster_theory.inseason.evaluation import build_weekly_projection_matrix


def attach_offer_assessment(evaluation, refresh, options, *, config_path=None,
                            target_policy_path=None, market_import_path=None,
                            matrix=None, shared=None):
    snapshot = refresh.refresh.snapshot
    assessment = {"status": "UNAVAILABLE", "failed_checks": (), "market_fairness": None}
    shared = shared if shared is not None else {}
    try:
        # Lazy import keeps the core exact evaluator independent of finder setup.
        from roster_theory.trade.target_workflow import _policy
        if 'policy' not in shared:
            shared['policy'] = _policy(snapshot.league_key, search=True, config_path=config_path,
                target_policy_path=target_policy_path, small_pool=None, large_pool=None,
                max_exact=None, max_large_exact=None, max_results=None)
        policy = shared['policy']
        if 'market' not in shared:
            shared['market'] = resolve_trade_market_evidence(league=snapshot.league,
                current_week=snapshot.manifest.current_week, authorized_import_path=market_import_path,
                archive_dir=Path('data/cache/trade/market') / snapshot.league_key / str(snapshot.league.season))
        market = shared['market']
        board = market.board
        if board is None or market.mode in {'ECR-PROXY', 'PRIOR_WEEK_MARKET'}:
            assessment.update(failed_checks=('current_chart_unavailable',), warnings=market.warnings)
        else:
            assessment['pricing'] = {'provider': board.provider, 'as_of': board.as_of.isoformat(),
                'format': board.format, 'scoring_variant': board.scoring_variant,
                'league_scoring_exact': board.league_scoring_exact, 'source_url': board.source_url,
                'board_hash': board.evidence_hash, 'warnings': market.warnings}
            sent = tuple(p.player_id for p in evaluation.package.from_a)
            received = tuple(p.player_id for p in evaluation.package.from_b)
            prices = {p.player_id: p.value for p in board.prices}
            missing = sorted(set((*sent, *received)) - prices.keys())
            if missing:
                assessment.update(failed_checks=('missing_chart_prices',), missing_player_ids=missing)
            else:
                config = policy.optimizer
                fair = _fairness(sent, received, prices, market.mode,
                    config.fair_market_band_ratio, config.fair_market_band_floor, market.warnings,
                    consolidation=len(sent) > 1 and len(received) == 1,
                    premium_policy_id=config.consolidation_premium_policy_id,
                    premium_ratio=config.consolidation_premium_ratio)
                context = _context(snapshot)
                matrix = matrix or build_weekly_projection_matrix(context, refresh.weekly_projections)
                diagnoses = shared.setdefault('diagnoses', {})
                for rid in (evaluation.package.roster_a_id, evaluation.package.roster_b_id):
                    if rid not in diagnoses:
                        diagnoses[rid] = diagnose_roster(snapshot, refresh.weekly_projections,
                            roster_id=rid, options=options, projection_matrix=matrix, protect_missing=True)
                row = _Candidate('ENTERED', received[0], 0, (), evaluation.package.roster_b_id,
                    sent, received, f'{len(sent)}-for-{len(received)}', market.mode,
                    abs(fair.raw_user_price_delta), abs(fair.user_price_delta), fair.within_band,
                    0, 0, 0, True)
                decision, status, failures, usage = assess_trade_offer(snapshot, evaluation,
                    row=row, fair=fair, diagnoses=diagnoses, config=config, options=options,
                    context=context, matrix=matrix)
                assessment.update(status=status or 'NOT_RECOMMENDED', failed_checks=failures,
                    market_fairness=asdict(fair), incoming_usage=tuple(asdict(u) for u in usage),
                    strict_verdict=decision.package_verdict)
    except (RosterTheoryError, OSError, ValueError, KeyError, TypeError) as exc:
        assessment.update(status='UNAVAILABLE', failed_checks=('offer_evidence_unavailable',),
                          reason=str(exc))
    result = replace(evaluation, offer_assessment=assessment, evidence_hash='')
    return replace(result, evidence_hash=stable_hash(asdict(result)))
