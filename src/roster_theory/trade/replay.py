"""Provider-free reproduction from verified Trade run manifests."""
from datetime import datetime
import json

from roster_theory.core.models import Projection
from roster_theory.core.provenance import canonical_json
from roster_theory.core.run_contract import evaluation_as_of, load_run_manifest, restore_record
from roster_theory.trade.boards import ValueBoard, ValuationGap
from roster_theory.trade.evaluation import EvaluationOptions, TradePackage, build_entered_package, evaluate_trade
from roster_theory.trade.market import TradeMarketEvidence
from roster_theory.trade.performance import TargetPerformanceContext
from roster_theory.trade.search import SearchConfig, search_league
from roster_theory.trade.snapshot import TradeSnapshot
from roster_theory.trade.targets import discover_trade_targets
from roster_theory.trade.target_optimizer import optimize_target_packages
from roster_theory.trade.target_workflow import _TargetPolicyBundle


def replay_trade_manifest(path):
    manifest = load_run_manifest(path)
    replay = manifest['replay']
    inputs, policy = replay['inputs'], replay['policy']
    snapshot = restore_record(TradeSnapshot, replay['snapshot'])
    common = dict(projections=restore_record(tuple[Projection, ...], inputs['projections']),
        selected_board=restore_record(ValueBoard, inputs['selected_board']),
        market_board=restore_record(ValueBoard, inputs['market_board']))
    operation = inputs['operation']
    with evaluation_as_of(datetime.fromisoformat(manifest['as_of'])):
        if operation == 'exact':
            result = evaluate_trade(snapshot, restore_record(TradePackage, inputs['package']),
                **common, options=restore_record(EvaluationOptions, policy))
            expected, actual = inputs['result_hash'], result.evidence_hash
        elif operation == 'compare':
            result = tuple(evaluate_trade(snapshot, build_entered_package(snapshot,
                send=row.get('send', ()), receive=row.get('receive', ())),
                **common, options=restore_record(EvaluationOptions, policy)) for row in inputs['packages'])
            expected = sorted(inputs['result_hashes'])
            actual = sorted(row.evidence_hash for row in result)
        elif operation == 'search':
            result = search_league(snapshot, **common,
                gaps=restore_record(tuple[ValuationGap, ...], inputs['gaps']),
                options=restore_record(EvaluationOptions, policy['options']),
                config=restore_record(SearchConfig, policy['search']))
            expected, actual = inputs['result_hash'], result.evidence_hash
        elif operation in ('targets', 'target_search'):
            settings = restore_record(_TargetPolicyBundle, policy['target_policy'])
            options = restore_record(EvaluationOptions, policy['options'])
            common['market_ecr_board'] = common.pop('market_board')
            market = restore_record(TradeMarketEvidence, inputs['trade_market'])
            targets = discover_trade_targets(snapshot, **common, trade_market=market,
                options=options, config=settings.discovery,
                performance_context=restore_record(tuple[TargetPerformanceContext, ...], inputs['performance_context']))
            packages = optimize_target_packages(snapshot, **common, trade_market=market,
                target_result=targets, config=settings.optimizer, options=options) if operation == 'target_search' else None
            result = {'targets': targets, 'packages': packages}
            expected = (inputs['target_hash'], inputs['package_hash'])
            actual = (targets.evidence_hash, packages.evidence_hash if packages else None)
        else:
            raise ValueError('Unsupported Trade replay operation')
    if actual != expected:
        raise ValueError('Replayed result hash differs from the recorded decision')
    return {'current': False, 'status': 'OFFLINE / NON-ACTIONABLE',
            'result': json.loads(canonical_json(result)), 'manifest_hash': manifest['manifest_hash']}
