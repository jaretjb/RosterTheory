"""League-local, point-in-time calibration study for target-first trade search.

The input is an explicit evidence export, never a live-provider client. Market
labels describe independent contemporaneous fairness judgments, not acceptance.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, stdev
from typing import Any

from roster_theory.core.provenance import stable_hash
from roster_theory.providers.cache import atomic_write_json
from roster_theory.trade.target_optimizer import PACKAGE_SIZE_LABELS
from roster_theory.trade.targets import TARGET_KINDS


def _time(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("Calibration timestamps must include a timezone")
    return result.astimezone(timezone.utc)


def _number(value: Any, name: str, *, minimum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be numeric")
    result = float(value)
    if not math.isfinite(result) or (minimum is not None and result < minimum):
        raise ValueError(f"{name} must be finite and at least {minimum}")
    return result


def _interval(successes: int, count: int) -> list[float] | None:
    if count == 0:
        return None
    z = 1.96
    p = successes / count
    denominator = 1 + z * z / count
    center = (p + z * z / (2 * count)) / denominator
    radius = z * math.sqrt(p * (1 - p) / count + z * z / (4 * count * count)) / denominator
    return [round(max(0.0, center - radius), 6), round(min(1.0, center + radius), 6)]


def _mean_interval(values: list[float]) -> list[float] | None:
    if len(values) < 2:
        return None
    center = mean(values)
    radius = 1.96 * stdev(values) / math.sqrt(len(values))
    return [round(center - radius, 6), round(center + radius, 6)]


def _validate(data: dict[str, Any]) -> tuple[list[tuple[str, datetime]], dict[str, datetime]]:
    if data.get("schema_version") != 1:
        raise ValueError("Unsupported calibration evidence schema")
    if not data.get("league_key") or not data.get("scoring_fingerprint"):
        raise ValueError("League key and scoring fingerprint are required")
    origin_rows = data["origins"]
    origins = [(row["id"], _time(row["decision_at"])) for row in origin_rows]
    if len(origins) != len(set(key for key, _ in origins)) or len(origins) < 3:
        raise ValueError("At least three distinct decision origins are required")
    if origins != sorted(origins, key=lambda row: row[1]) or len({t for _, t in origins}) != len(origins):
        raise ValueError("Decision origins must be strictly chronological")
    weeks = [(row["season"], row["week"]) for row in origin_rows]
    if any(not isinstance(season, int) or not isinstance(week, int) or season < 2000 or not 1 <= week <= 18
           for season, week in weeks) or len(set(weeks)) != len(weeks) or weeks != sorted(weeks):
        raise ValueError("Decision origins must represent distinct chronological league weeks")
    cutoffs = dict(origins)
    for axis in ("intrinsic", "market", "performance", "search"):
        row_keys = set()
        for row in data.get(axis, []):
            if not isinstance(row.get("source_hash"), str) or not row["source_hash"].strip():
                raise ValueError(f"{axis} row requires a source evidence hash")
            if row.get("origin_id") not in cutoffs:
                raise ValueError(f"{axis} row references an unknown origin")
            if row.get("league_key") != data["league_key"]:
                raise ValueError(f"{axis} row crosses the study league boundary")
            if row.get("scoring_fingerprint") != data["scoring_fingerprint"]:
                raise ValueError(f"{axis} row has incompatible league scoring")
            cutoff = cutoffs[row["origin_id"]]
            if axis in ("intrinsic", "performance"):
                if _time(row["feature_available_at"]) > cutoff:
                    raise ValueError(f"{axis} feature was not available at decision time")
                if _time(row["outcome_available_at"]) <= cutoff:
                    raise ValueError(f"{axis} outcome must follow decision time")
            if axis == "intrinsic":
                row_key = (row["origin_id"], row["candidate_id"])
                _number(row["projected_gain"], "projected_gain")
                _number(row["projected_downside"], "projected_downside", minimum=0)
                _number(row["realized_gain"], "realized_gain")
                if row["lane"] not in TARGET_KINDS or row["package_size"] not in PACKAGE_SIZE_LABELS:
                    raise ValueError("Invalid intrinsic lane or package size")
            elif axis == "market":
                row_key = (row["origin_id"], row["candidate_id"])
                if _time(row["market_published_at"]) > cutoff or _time(row["reference_published_at"]) > cutoff:
                    raise ValueError("Market or reference judgment is later than decision time")
                if not row.get("market_source") or not row.get("reference_source") or row["market_source"] == row["reference_source"]:
                    raise ValueError("Market fairness requires an independent reference source")
                if type(row.get("reference_fair")) is not bool:
                    raise ValueError("Reference fairness must be a boolean judgment, not acceptance")
                if row.get("reference_kind") != "COMMUNITY_FAIRNESS_ASSESSMENT":
                    raise ValueError("Acceptance or transaction outcomes cannot label market fairness")
                _number(row["market_sent"], "market_sent", minimum=0)
                _number(row["market_received"], "market_received", minimum=0)
                if row["package_size"] not in PACKAGE_SIZE_LABELS:
                    raise ValueError("Invalid market package size")
            elif axis == "performance":
                row_key = (row["origin_id"], row["player_id"], row["window_weeks"])
                if row["signal"] not in (-1, 0, 1) or row["future_direction"] not in (-1, 1):
                    raise ValueError("Performance signs must be -1, 0, or 1")
                if not isinstance(row["window_weeks"], int) or row["window_weeks"] <= 0:
                    raise ValueError("Performance window must be positive")
            else:
                row_key = (row["origin_id"], row["lane"], row["package_size"])
                if not row.get("complete"):
                    raise ValueError("Search evidence must be a controlled exhaustive group")
                if row["lane"] not in TARGET_KINDS or row["package_size"] not in PACKAGE_SIZE_LABELS:
                    raise ValueError("Invalid search lane or package size")
                if _time(row["feature_available_at"]) > cutoff:
                    raise ValueError("Search input was not available at decision time")
                candidates = row["candidates"]
                ranks = sorted(candidate["heuristic_rank"] for candidate in candidates)
                if not candidates or ranks != list(range(1, len(candidates) + 1)):
                    raise ValueError("Exhaustive search ranks must be contiguous from one")
                if len({candidate["id"] for candidate in candidates}) != len(candidates):
                    raise ValueError("Duplicate search candidate")
                for candidate in candidates:
                    _number(candidate["exact_gain"], "exact_gain")
                    _number(candidate["runtime_ms"], "runtime_ms", minimum=0)
                    _number(candidate["candidate_lineup_gain"], "candidate_lineup_gain")
                    _number(candidate["lane_signal_gap"], "lane_signal_gap", minimum=0)
            if row_key in row_keys:
                raise ValueError(f"Duplicate {axis} evidence row")
            row_keys.add(row_key)
    return origins, cutoffs


def _grids(data: dict[str, Any]) -> dict[str, list[Any]]:
    grids = data["grids"]
    result: dict[str, list[Any]] = {}
    for axis in ("intrinsic", "market", "performance", "search"):
        values = grids[axis]
        if not values:
            raise ValueError(f"{axis} grid cannot be empty")
        result[axis] = values
    for setting in result["intrinsic"]:
        _number(setting["edge"], "edge", minimum=0)
        _number(setting["downside"], "downside", minimum=0)
    for setting in result["market"]:
        _number(setting["ratio"], "ratio", minimum=0)
        _number(setting["floor"], "floor", minimum=0)
        premium = _number(setting["premium"], "premium", minimum=0)
        if premium > 1:
            raise ValueError("Market consolidation premium cannot exceed one")
    for value in result["performance"]:
        if not isinstance(value, int) or value <= 0:
            raise ValueError("Invalid performance window")
    for setting in result["search"]:
        if not isinstance(setting["budget"], int) or setting["budget"] < 0:
            raise ValueError("Invalid exact evaluation budget")
        _number(setting["minimum_candidate_gain"], "minimum_candidate_gain", minimum=0)
        _number(setting["minimum_lane_signal_gap"], "minimum_lane_signal_gap", minimum=0)
    return result


def _intrinsic(rows: list[dict[str, Any]], setting: dict[str, float]) -> dict[str, Any]:
    selected = [row for row in rows if row["projected_gain"] >= setting["edge"] and row["projected_downside"] <= setting["downside"]]
    gains = [float(row["realized_gain"]) for row in selected]
    wins = sum(gain > 0 for gain in gains)
    return {"eligible": len(rows), "selected": len(selected), "rejected": len(rows) - len(selected),
            "realized_gain_mean": round(mean(gains), 6) if gains else None,
            "realized_gain_95_interval": _mean_interval(gains),
            "positive_outcomes": wins, "positive_rate_95_interval": _interval(wins, len(gains)),
            "utility_per_candidate": round(sum(gains) / len(rows), 6) if rows else None}


def _market(rows: list[dict[str, Any]], setting: dict[str, float]) -> dict[str, Any]:
    confusion: Counter[str] = Counter()
    for row in rows:
        received = row["market_received"] * (1 + setting["premium"] if row["package_size"] == "2-for-1" else 1)
        sent = row["market_sent"]
        band = max(setting["floor"], setting["ratio"] * max(sent, received))
        predicted = abs(sent - received) <= band
        label = "TP" if predicted and row["reference_fair"] else "TN" if not predicted and not row["reference_fair"] else "FP" if predicted else "FN"
        confusion[label] += 1
    hits = confusion["TP"] + confusion["TN"]
    positives = confusion["TP"] + confusion["FN"]
    negatives = confusion["TN"] + confusion["FP"]
    balanced = (confusion["TP"] / positives + confusion["TN"] / negatives) / 2 if positives and negatives else None
    return {"eligible": len(rows), "confusion": dict(sorted(confusion.items())),
            "agreement": round(hits / len(rows), 6) if rows else None,
            "agreement_95_interval": _interval(hits, len(rows)),
            "balanced_agreement": round(balanced, 6) if balanced is not None else None,
            "reference_positive": positives, "reference_negative": negatives}


def _performance(rows: list[dict[str, Any]], window: int) -> dict[str, Any]:
    matched = [row for row in rows if row["window_weeks"] == window]
    signaled = [row for row in matched if row["signal"] != 0]
    correct = sum(row["signal"] == row["future_direction"] for row in signaled)
    return {"eligible": len(matched), "signaled": len(signaled),
            "abstained": len(matched) - len(signaled), "correct": correct,
            "directional_accuracy": round(correct / len(signaled), 6) if signaled else None,
            "accuracy_95_interval": _interval(correct, len(signaled)),
            "utility_per_player": round((2 * correct - len(signaled)) / len(matched), 6) if matched else None}


def _search(rows: list[dict[str, Any]], setting: dict[str, float]) -> dict[str, Any]:
    recalled = 0
    coverage: list[float] = []
    regrets: list[float] = []
    runtime = 0.0
    gated_out = 0
    for row in rows:
        ordered = sorted(row["candidates"], key=lambda candidate: candidate["heuristic_rank"])
        eligible = [candidate for candidate in ordered
                    if candidate["candidate_lineup_gain"] >= setting["minimum_candidate_gain"]
                    and candidate["lane_signal_gap"] >= setting["minimum_lane_signal_gap"]]
        gated_out += len(ordered) - len(eligible)
        exact = eligible[:setting["budget"]]
        oracle = max(candidate["exact_gain"] for candidate in ordered)
        best = max((candidate["exact_gain"] for candidate in exact), default=None)
        recalled += best is not None and best >= oracle - 1e-9
        coverage.append(len(exact) / len(ordered))
        if best is not None:
            regrets.append(oracle - best)
        runtime += sum(candidate["runtime_ms"] for candidate in exact)
    return {"groups": len(rows), "best_recalled": recalled,
            "recall": round(recalled / len(rows), 6) if rows else None,
            "recall_95_interval": _interval(recalled, len(rows)),
            "gated_out_candidates": gated_out,
            "candidate_coverage": round(mean(coverage), 6) if coverage else None,
            "mean_regret": round(mean(regrets), 6) if regrets else None,
            "runtime_ms": round(runtime, 3)}


def run_calibration_study(data: dict[str, Any], *, minimum_train_origins: int = 2) -> dict[str, Any]:
    """Select on earlier available evidence; score each subsequent origin once."""
    origins, _ = _validate(data)
    grids = _grids(data)
    if minimum_train_origins < 2 or len(origins) <= minimum_train_origins:
        raise ValueError("At least two training and one holdout origin are required")
    report: dict[str, Any] = {"schema_version": 1, "league_key": data["league_key"],
        "scoring_fingerprint": data["scoring_fingerprint"], "input_hash": stable_hash(data),
        "status": "NOT_PROMOTED", "axes": {}, "warnings": []}
    for axis in ("intrinsic", "market", "performance", "search"):
        groups = [None] if axis != "search" else [(lane, size) for lane in TARGET_KINDS for size in PACKAGE_SIZE_LABELS]
        axis_results: list[dict[str, Any]] = []
        for group in groups:
            rows = [row for row in data.get(axis, []) if group is None or (row["lane"], row["package_size"]) == group]
            holdouts = []
            rejection_counts: Counter[str] = Counter()
            for index in range(minimum_train_origins, len(origins)):
                origin_id, cutoff = origins[index]
                prior_ids = {name for name, _ in origins[:index]}
                training = [row for row in rows if row["origin_id"] in prior_ids and
                            (axis not in ("intrinsic", "performance") or _time(row["outcome_available_at"]) < cutoff)]
                held = [row for row in rows if row["origin_id"] == origin_id]
                if not training or not held or len({row["origin_id"] for row in training}) < minimum_train_origins:
                    rejection_counts["INSUFFICIENT_TIME_ORDERED_EVIDENCE"] += 1
                    continue
                scorer = {"intrinsic": _intrinsic, "market": _market,
                          "performance": _performance, "search": _search}[axis]
                scored = []
                training_grid = []
                for setting in grids[axis]:
                    metric = scorer(training, setting)
                    reason = None
                    if axis == "intrinsic" and metric["selected"] < 2:
                        reason = "TOO_FEW_SELECTED"
                    elif axis == "market" and metric["balanced_agreement"] is None:
                        reason = "ONE_REFERENCE_CLASS"
                    elif axis == "performance" and metric["signaled"] < 2:
                        reason = "TOO_FEW_PERFORMANCE_SIGNALS"
                    elif axis == "search" and metric["groups"] < 2:
                        reason = "TOO_FEW_EXHAUSTIVE_GROUPS"
                    training_grid.append({"setting": setting, "metric": metric,
                                          "status": "REJECTED" if reason else "SUPPORTED",
                                          "reason": reason})
                    if reason:
                        rejection_counts[reason] += 1
                        continue
                    score = {"intrinsic": metric.get("utility_per_candidate"),
                             "market": metric.get("balanced_agreement"),
                             "performance": metric.get("utility_per_player"),
                             "search": metric.get("recall")}[axis]
                    scored.append((score, setting, metric))
                if not scored:
                    rejection_counts["NO_SUPPORTED_GRID_SETTING"] += 1
                    continue
                if axis == "search":
                    scored.sort(key=lambda item: (
                        -item[0], item[2]["runtime_ms"],
                        json.dumps(item[1], sort_keys=True)))
                else:
                    scored.sort(key=lambda item: (-item[0], json.dumps(item[1], sort_keys=True)))
                _, setting, train_metric = scored[0]
                holdouts.append({"origin_id": origin_id, "decision_at": cutoff.isoformat(),
                                 "selected_setting": setting, "training": train_metric,
                                 "holdout": scorer(held, setting),
                                 "training_grid": training_grid,
                                 "holdout_grid": [
                                     {"setting": candidate, "metric": scorer(held, candidate)}
                                     for candidate in grids[axis]
                                 ],
                                 "rejected_grid_settings": len(grids[axis]) - len(scored)})
            result = {"group": list(group) if group else None, "grid": grids[axis],
                      "evidence_rows": len(rows), "holdouts": holdouts,
                      "rejection_counts": dict(sorted(rejection_counts.items())),
                      "status": "EVALUATED" if holdouts else "UNAVAILABLE"}
            axis_results.append(result)
        report["axes"][axis] = axis_results
    if any(result["status"] == "UNAVAILABLE" for results in report["axes"].values() for result in results):
        report["warnings"].append("At least one axis or lane/size lacks rolling-origin evidence; no league policy may be promoted")
    else:
        report["warnings"].append("Holdout estimates are descriptive; policy promotion requires explicit league review and uncertainty assessment")
    report["evidence_hash"] = stable_hash({key: value for key, value in report.items() if key != "evidence_hash"})
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one league's read-only trade calibration study")
    parser.add_argument("evidence", type=Path)
    parser.add_argument("report", type=Path)
    args = parser.parse_args()
    data = json.loads(args.evidence.read_text(encoding="utf-8"))
    result = run_calibration_study(data)
    atomic_write_json(args.report, result)
    print(json.dumps({"league_key": result["league_key"], "status": result["status"],
                      "report": str(args.report), "evidence_hash": result["evidence_hash"]}))


if __name__ == "__main__":
    main()
