"""Offline, non-actionable finder benchmark from an existing Trade manifest."""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path
from time import perf_counter

from roster_theory.core.models import Projection
from roster_theory.core.run_contract import evaluate_at, load_run_manifest, restore_record
from roster_theory.trade.boards import ValueBoard
from roster_theory.trade.evaluation import EvaluationOptions
from roster_theory.trade.execution import FinderExecutionPolicy
from roster_theory.trade.finder import find_trade_packages, resolve_scope
from roster_theory.trade.market import TradeMarketEvidence
from roster_theory.trade.snapshot import TradeSnapshot
from roster_theory.trade.target_optimizer import TargetOptimizerConfig
from roster_theory.trade.targets import TargetDiscoveryResult
from roster_theory.trade.target_workflow import load_target_workflow_evidence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("evidence", type=Path)
    parser.add_argument("--opponent")
    parser.add_argument("--seconds", type=float)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    started = perf_counter()
    manifest = load_run_manifest(args.manifest, require_same_build=False)
    replay = manifest["replay"]
    snapshot = restore_record(TradeSnapshot, replay["snapshot"])
    inputs = replay["inputs"]
    projections = restore_record(tuple[Projection, ...], inputs["projections"])
    selected = restore_record(ValueBoard, inputs["selected_board"])
    market_ecr = restore_record(ValueBoard, inputs["market_board"])
    market = restore_record(TradeMarketEvidence, inputs["trade_market"])
    options = restore_record(EvaluationOptions, replay["policy"]["options"])
    evidence = load_target_workflow_evidence(args.evidence)
    targets = restore_record(TargetDiscoveryResult, evidence["targets"])
    config = restore_record(TargetOptimizerConfig, evidence["packages"]["config"])
    scope = resolve_scope(snapshot, args.opponent)
    preparation = perf_counter() - started
    from datetime import datetime
    result = evaluate_at(datetime.fromisoformat(manifest["as_of"]), find_trade_packages, snapshot,
        projections=projections, selected_board=selected, market_ecr_board=market_ecr,
        trade_market=market, target_result=targets, config=config, options=options,
        scope=scope, execution_policy=FinderExecutionPolicy(), time_budget_seconds=args.seconds)
    payload = {"status": "OFFLINE / NON-ACTIONABLE", "source_manifest_hash": manifest["manifest_hash"],
               "restoration_seconds": round(preparation, 3), "result": asdict(result)}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, default=str, indent=2), encoding="utf-8")
    print(json.dumps({"status": payload["status"], "scope": asdict(scope), "timing": result.timing,
        "termination": result.termination, "evaluated": len(result.evaluated_decisions),
        "ideas": [{"status": i.status, "sent": i.decision.sent_player_ids,
                   "received": i.decision.received_player_ids, "strict": i.decision.package_verdict,
                   "user_gain": i.decision.user_weighted_lineup_delta,
                   "partner_gain": i.decision.partner_weighted_lineup_delta,
                   "failed": i.failed_checks} for i in result.ideas],
        "coverage": [asdict(c) for c in result.shape_coverage]}, indent=2))


if __name__ == "__main__":
    main()
