"""Reproducible, synthetic AC-008 search measurements; never contacts providers."""

from __future__ import annotations

import argparse
import json
import statistics
import time
import tracemalloc
from dataclasses import asdict, replace
from datetime import datetime, timezone
from unittest.mock import patch

from roster_theory.core.run_contract import evaluation_as_of
from roster_theory.trade.boards import valuation_gaps
from roster_theory.trade.search import SearchConfig, search_league
from roster_theory.trade.target_optimizer import optimize_target_packages
from roster_theory.trade.targets import discover_trade_targets
from tests import test_trade_evaluation, test_trade_targets
from tests.test_trade_target_optimizer import optimizer_config, permissive_options
from tests.test_waiver_search import search as waiver_search


AS_OF = datetime(2026, 9, 25, 12, tzinfo=timezone.utc)


def _fixture(module, function):
    with patch.object(module, "datetime", wraps=datetime) as fixture_clock:
        fixture_clock.now.return_value = AS_OF
        return function()


def _measure(function, repeat):
    rows = []
    for _ in range(repeat):
        metrics = {}
        tracemalloc.start()
        started = time.perf_counter()
        with evaluation_as_of(AS_OF):
            result = function(metrics)
        elapsed = time.perf_counter() - started
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        rows.append({
            "seconds": round(elapsed, 4),
            "peak_bytes": peak,
            "evidence_bytes": len(json.dumps(asdict(result), default=str, separators=(",", ":"))),
            "evidence_hash": result.evidence_hash,
            "coverage": metrics["coverage"],
            "cache": metrics["cache"],
        })
    if len({row["evidence_hash"] for row in rows}) != 1:
        raise AssertionError("Synthetic replay changed its evidence hash")
    return {
        "median_seconds": statistics.median(row["seconds"] for row in rows),
        "median_peak_bytes": statistics.median(row["peak_bytes"] for row in rows),
        "runs": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeat", type=int, default=3)
    args = parser.parse_args()
    if args.repeat < 1:
        parser.error("--repeat must be positive")

    with evaluation_as_of(AS_OF):
        snapshot, projections, selected, market_ecr, market = _fixture(
            test_trade_targets, test_trade_targets.fixture,
        )
        targets = discover_trade_targets(
            snapshot,
            projections=projections,
            selected_board=selected,
            market_ecr_board=market_ecr,
            trade_market=market,
            config=test_trade_targets.config(),
        )
        broad_snapshot = _fixture(
            test_trade_evaluation, test_trade_evaluation.snapshot_fixture,
        )
    broad_selected = test_trade_evaluation.board_fixture(broad_snapshot, "selected_final")
    broad_market = test_trade_evaluation.board_fixture(broad_snapshot, "market")
    broad_gaps = valuation_gaps(broad_selected, broad_market)
    common = {
        "projections": projections,
        "selected_board": selected,
        "market_ecr_board": market_ecr,
        "trade_market": market,
        "target_result": targets,
        "options": permissive_options(),
    }
    normal = optimizer_config()
    strict = replace(
        normal,
        construction_market_band_ratio=0.0,
        construction_market_band_floor=0.0,
        fair_market_band_ratio=0.0,
        fair_market_band_floor=0.0,
    )
    results = {
        "trade_target": _measure(
            lambda metrics: optimize_target_packages(
                snapshot, config=normal, metrics=metrics, **common,
            ), args.repeat,
        ),
        "trade_strict": _measure(
            lambda metrics: optimize_target_packages(
                snapshot, config=strict, metrics=metrics, **common,
            ), args.repeat,
        ),
        "trade_broad": _measure(
            lambda metrics: search_league(
                broad_snapshot,
                projections=test_trade_evaluation.projection_fixture(),
                selected_board=broad_selected,
                market_board=broad_market,
                gaps=broad_gaps,
                config=SearchConfig(),
                metrics=metrics,
            ), args.repeat,
        ),
        "waiver": _measure(lambda metrics: waiver_search(metrics=metrics), args.repeat),
    }
    print(json.dumps({"as_of": AS_OF.isoformat(), "repeat": args.repeat, "fixtures": results}, indent=2))


if __name__ == "__main__":
    main()
