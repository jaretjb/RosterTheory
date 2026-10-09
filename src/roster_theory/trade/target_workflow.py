from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Mapping
from time import perf_counter

from roster_theory.core.errors import Uncalibrated
from roster_theory.core.provenance import stable_hash
from roster_theory.core.run_contract import evaluate_at, manifest_summary, run_footer
from roster_theory.providers.base import TradeMarketSource
from roster_theory.providers.cache import atomic_write_json
from roster_theory.sleeper import resolve_league_policy_path
from roster_theory.stats_guy_fantasy import StatsGuyFantasyClient
from roster_theory.trade.board_service import BoardRefreshResult, refresh_value_boards
from roster_theory.trade.evaluation import EvaluationOptions
from roster_theory.trade.execution import FinderExecutionPolicy, SearchDeadline, SearchExecution, search_execution
from roster_theory.trade.finder import find_trade_packages, resolve_scope, FinderResult
from roster_theory.trade.evaluation_service import _options_from_policy, finish_trade_run
from roster_theory.trade.market import (
    TradeMarketEvidence,
    resolve_trade_market_evidence,
)
from roster_theory.trade.performance import PerformancePolicy
from roster_theory.trade.performance_history import (
    PerformanceHistoryResult,
    update_performance_history,
)
from roster_theory.trade.target_optimizer import (
    ExactEvaluationBudget,
    TargetOptimizerConfig,
    TargetPackageSearchResult,
    optimize_target_packages,
    uniform_exact_budgets,
)
from roster_theory.trade.targets import (
    TARGET_KINDS,
    TargetDiscoveryConfig,
    TargetDiscoveryResult,
    TargetExclusion,
    discover_trade_targets,
)


@dataclass(frozen=True, slots=True)
class TargetWorkflowResult:
    targets: TargetDiscoveryResult
    packages: TargetPackageSearchResult | None
    trade_market: TradeMarketEvidence
    board_refresh: BoardRefreshResult
    output_path: Path
    csv_path: Path | None
    evidence_hash: str
    policy_status: str
    policy_basis: str
    performance_history: PerformanceHistoryResult | None
    feedback_path: Path | None
    run_manifest: Mapping[str, Any] | None = None
    performance: Mapping[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class _TargetPolicyBundle:
    discovery: TargetDiscoveryConfig
    optimizer: TargetOptimizerConfig | None
    status: str
    basis: str
    version: str
    performance: PerformancePolicy | None
    execution: FinderExecutionPolicy | None = None


CSV_FIELDS = (
    "record_type", "lane", "target_player_id", "owner_roster_id", "status",
    "pricing_mode", "intrinsic_percentile", "market_ecr_percentile",
    "trade_price_percentile", "trade_price", "trade_price_change_7d",
    "user_standalone_lineup_gain", "performance_signal", "performance_samples",
    "performance_point_residual", "offer_count", "send_player_ids",
    "receive_player_ids", "intrinsic_outcome", "market_status", "package_verdict", "recommendation_status",
    "market_price_delta", "market_premium", "premium_sensitivity", "user_lineup_delta",
    "user_depth_delta", "partner_lineup_delta", "partner_depth_delta",
    "user_add", "partner_drop",
    "failed_checks", "repair_status", "evaluation_hash",
    "user_selected_delta", "partner_selected_delta", "user_downside_delta",
    "scope", "roster_policy_version", "search_seconds", "execution_profile", "package_size",
    "enumerated", "price_pruned", "roster_pruned", "eligible", "evaluated", "unevaluated",
    "unconstructed", "repair_pruned", "prune_reasons", "starter_weeks",
    "asset_lineup_delta", "asset_depth_delta",
)


def _policy(
    league_key: str,
    *,
    search: bool,
    config_path: str | Path | None,
    target_policy_path: str | Path | None,
    small_pool: int | None,
    large_pool: int | None,
    max_exact: int | None,
    max_large_exact: int | None,
    max_results: int | None,
) -> _TargetPolicyBundle:
    try:
        path = resolve_league_policy_path(
            league_key,
            "trade_target",
            config_path=config_path,
            explicit_path=target_policy_path,
        )
    except Uncalibrated as exc:
        raise Uncalibrated(
            f"Trade search configuration is missing for league {league_key!r}. "
            "This is separate from the chosen expert weights. Configure trade_target or pass "
            "--target-policy PATH"
        ) from exc
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if value.get("league_key") != league_key:
            raise ValueError("Trade target policy is for a different league")
        status = str(value.get("evidence_status", "UNVALIDATED"))
        if status not in {"UNVALIDATED", "PROVISIONAL_HEURISTIC"}:
            raise ValueError("Trade target policy cannot claim empirical calibration here")
        basis = str(value.get("basis", "No empirical calibration supplied"))
        if not basis.strip():
            raise ValueError("Trade target policy basis is required")
        target = TargetDiscoveryConfig(**value["target_discovery"])
        execution = (FinderExecutionPolicy(**value["execution_profile"])
                     if "execution_profile" in value else None)
        performance_data = value.get("performance_policy")
        performance = None
        if performance_data is not None:
            performance_data = dict(performance_data)
            for field in ("point_scales", "rank_scales"):
                performance_data[field] = tuple(tuple(row) for row in performance_data[field])
            performance = PerformancePolicy(**performance_data)
        optimizer = None
        if search:
            optimizer_data = dict(value["target_optimizer"])
            if "exact_budgets" in optimizer_data:
                budgets = tuple(
                    ExactEvaluationBudget(**row) for row in optimizer_data.pop("exact_budgets")
                )
            else:
                budgets = uniform_exact_budgets(int(optimizer_data.pop("uniform_exact_budget")))
            optimizer = TargetOptimizerConfig(**optimizer_data, exact_budgets=budgets)
    except (KeyError, TypeError) as exc:
        raise ValueError(f"Incomplete Trade target policy at {path}: {exc}") from exc
    if optimizer is None:
        return _TargetPolicyBundle(
            target, None, status,
            basis,
            str(value.get("version", "unspecified")), performance, execution,
        )
    if small_pool is not None:
        optimizer = replace(optimizer, outgoing_pool_limit=small_pool)
    if large_pool is not None:
        optimizer = replace(optimizer, incoming_pool_limit=large_pool)
    if max_exact is not None or max_large_exact is not None:
        optimizer = replace(
            optimizer,
            exact_budgets=tuple(
                replace(
                    row,
                    limit=(
                        max_exact if max_exact is not None else row.limit
                    ) if row.package_size in {"1-for-1", "2-for-1"} else (
                        max_large_exact if max_large_exact is not None else row.limit
                    ),
                )
                for row in optimizer.exact_budgets
            ),
        )
    if max_results is not None:
        optimizer = replace(optimizer, max_results_per_lane=max_results)
    return _TargetPolicyBundle(
        target, optimizer, status,
        basis,
        str(value.get("version", "unspecified")), performance, execution,
    )


def _csv_rows(result: TargetWorkflowResult) -> tuple[dict[str, Any], ...]:
    rows: list[dict[str, Any]] = []
    if isinstance(result.packages, FinderResult):
        packages = result.packages
        rows.append({"record_type": "EXECUTION", "status": packages.termination,
            "scope": packages.scope.mode, "roster_policy_version": packages.roster_policy_version,
            "search_seconds": packages.timing["search_seconds"],
            "execution_profile": json.dumps(packages.execution_profile, sort_keys=True)})
        for coverage in packages.shape_coverage:
            rows.append({"record_type": "COVERAGE", "owner_roster_id": coverage.opponent_roster_id,
                "package_size": coverage.package_size, "status": coverage.status,
                "enumerated": coverage.enumerated, "price_pruned": coverage.price_pruned,
                "roster_pruned": coverage.roster_pruned, "eligible": coverage.eligible,
                "evaluated": coverage.evaluated, "unevaluated": coverage.unevaluated,
                "unconstructed": coverage.unconstructed, "repair_pruned": coverage.repair_pruned,
                "prune_reasons": json.dumps(coverage.prune_reasons)})
        for rejection in packages.rejection_samples:
            rows.append({"record_type": "ROSTER_REJECTION_SAMPLE", "owner_roster_id": rejection.opponent_roster_id,
                "send_player_ids": ";".join(rejection.sent_player_ids),
                "receive_player_ids": ";".join(rejection.received_player_ids),
                "status": rejection.stage, "failed_checks": ";".join(rejection.failed_checks)})
        for check in packages.package_checks:
            rows.append({"record_type": "PACKAGE_CHECK", "owner_roster_id": check.opponent_roster_id,
                "send_player_ids": ";".join(check.sent_player_ids),
                "receive_player_ids": ";".join(check.received_player_ids),
                "failed_checks": ";".join(check.failed_checks), "evaluation_hash": check.evaluation_hash})
            for use in check.incoming_usage:
                rows.append({"record_type": "INCOMING_USE", "owner_roster_id": use.roster_id,
                    "target_player_id": use.player_id, "status": "USEFUL" if use.useful else "UNUSED",
                    "starter_weeks": ";".join(str(w) for w in use.starter_weeks),
                    "asset_lineup_delta": use.lineup_delta, "asset_depth_delta": use.depth_delta,
                    "evaluation_hash": check.evaluation_hash})
        for idea in result.packages.ideas:
            d = idea.decision
            rows.append({"record_type": "IDEA", "lane": d.lane,
                "owner_roster_id": d.opponent_roster_id, "status": idea.status,
                "send_player_ids": ";".join(d.sent_player_ids),
                "receive_player_ids": ";".join(d.received_player_ids),
                "package_verdict": d.package_verdict, "recommendation_status": idea.status,
                "intrinsic_outcome": d.intrinsic_outcome,
                "market_status": d.market_fairness.status,
                "user_lineup_delta": d.user_weighted_lineup_delta,
                "partner_lineup_delta": d.partner_weighted_lineup_delta,
                "user_selected_delta": d.user_selected_delta,
                "partner_selected_delta": d.partner_selected_delta,
                "user_depth_delta": d.user_depth_delta,
                "partner_depth_delta": d.partner_depth_delta,
                "user_downside_delta": d.user_downside_delta,
                "market_price_delta": d.market_fairness.user_price_delta,
                "market_premium": d.market_fairness.consolidation_premium_value,
                "pricing_mode": d.market_fairness.mode,
                "user_add": ";".join(p for m in idea.evaluation.secondary_moves if m.kind == "ADD" and m.roster_id == result.board_refresh.refresh.snapshot.user_roster_id for p in m.chosen_player_ids),
                "partner_drop": ";".join(p for m in idea.evaluation.secondary_moves if m.kind == "DROP" and m.roster_id == d.opponent_roster_id for p in m.chosen_player_ids),
                "failed_checks": ";".join(idea.failed_checks),
                "repair_status": idea.repair_search_status, "evaluation_hash": d.evaluation_hash})
            for repair in idea.repairs:
                rows.append({"record_type": "REPAIR", "owner_roster_id": d.opponent_roster_id,
                    "status": repair.status, "send_player_ids": ";".join(repair.sent_player_ids),
                    "receive_player_ids": ";".join(repair.received_player_ids),
                    "package_verdict": repair.package_verdict,
                    "failed_checks": ";".join(repair.failed_checks),
                    "evaluation_hash": repair.evaluation_hash})
    statuses = {
        (row.lane, row.player_id): row
        for row in result.packages.target_statuses
    } if result.packages else {}
    for target in result.targets.targets:
        status = statuses.get((target.kind, target.player_id))
        rows.append({
            "record_type": "TARGET",
            "lane": target.kind,
            "target_player_id": target.player_id,
            "owner_roster_id": target.roster.owner_roster_id,
            "status": status.status if status else target.status,
            "pricing_mode": result.targets.pricing_mode,
            "intrinsic_percentile": target.intrinsic.percentile,
            "market_ecr_percentile": target.market_ecr.percentile,
            "trade_price_percentile": target.trade_price.percentile,
            "trade_price": target.trade_price.raw_value,
            "trade_price_change_7d": target.trade_price.provider_change_7d,
            "user_standalone_lineup_gain": target.roster.user_standalone_lineup_gain,
            "performance_signal": target.performance.signal if target.performance else "UNAVAILABLE",
            "performance_samples": target.performance.sample_size if target.performance else 0,
            "performance_point_residual": (
                target.performance.shrunk_point_residual if target.performance else None
            ),
            "offer_count": status.passing_offer_count if status else 0,
        })
    if result.packages:
        for row in result.packages.opportunities:
            rows.append({
                "record_type": "OFFER",
                "lane": row.lane,
                "target_player_id": row.primary_target_player_id,
                "owner_roster_id": row.opponent_roster_id,
                "status": "CONDITIONAL" if row.intrinsic_outcome == "CONDITIONAL" else "OFFER_FOUND",
                "pricing_mode": result.targets.pricing_mode,
                "send_player_ids": ";".join(row.sent_player_ids),
                "receive_player_ids": ";".join(row.received_player_ids),
                "intrinsic_outcome": row.intrinsic_outcome,
                "package_verdict": row.evaluation.decision_label,
                "recommendation_status": ("CONDITIONAL" if row.intrinsic_outcome == "CONDITIONAL" else
                                          "PROVISIONAL_MARKET" if row.market_fairness.mode == "ECR-PROXY" else "SCREENED_OPPORTUNITY"),
                "market_status": row.market_fairness.status,
                "market_price_delta": row.market_fairness.user_price_delta,
                "market_premium": row.market_fairness.consolidation_premium_value,
                "premium_sensitivity": ";".join(
                    f"{scenario.ratio:.0%}:{scenario.status}"
                    for scenario in row.market_fairness.premium_sensitivity
                ),
                "user_lineup_delta": row.user_weighted_lineup_delta,
                "user_depth_delta": row.user_depth_delta,
                "partner_lineup_delta": row.partner_weighted_lineup_delta,
                "partner_depth_delta": row.partner_depth_delta,
                "user_add": ";".join(p for m in row.evaluation.secondary_moves if m.kind == "ADD" and m.roster_id == row.evaluation.package.roster_a_id for p in m.chosen_player_ids),
                "partner_drop": ";".join(p for m in row.evaluation.secondary_moves if m.kind == "DROP" and m.roster_id == row.opponent_roster_id for p in m.chosen_player_ids),
            })
    return tuple(rows)


def _write_csv(path: Path, rows: tuple[dict[str, Any], ...]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


FEEDBACK_FIELDS = (
    "evidence_hash", "record_type", "lane", "target_player_id", "send_player_ids",
    "receive_player_ids", "intrinsic_outcome", "market_status", "user_assessment",
    "would_propose", "actual_response_if_proposed", "reason", "recorded_at",
)


def _write_feedback_template(path: Path, result: TargetWorkflowResult) -> None:
    # Never overwrite a manager's completed notes on a repeated/replayed run.
    if path.exists():
        return
    rows: list[dict[str, str]] = []
    for target in result.targets.targets:
        rows.append({
            "evidence_hash": result.evidence_hash, "record_type": "TARGET",
            "lane": target.kind, "target_player_id": target.player_id,
        })
    if result.packages:
        for offer in result.packages.opportunities:
            rows.append({
                "evidence_hash": result.evidence_hash, "record_type": "OFFER",
                "lane": offer.lane, "target_player_id": offer.primary_target_player_id,
                "send_player_ids": ";".join(offer.sent_player_ids),
                "receive_player_ids": ";".join(offer.received_player_ids),
                "intrinsic_outcome": offer.intrinsic_outcome,
                "market_status": offer.market_fairness.status,
            })
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FEEDBACK_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def _interrupted_discovery(snapshot, refresh, market, config, scope):
    """Retain input gaps even when discovery cannot finish before the deadline."""
    from roster_theory.trade.coverage import roster_projection_exclusions
    from roster_theory.trade.target_optimizer import _context
    from roster_theory.inseason.evaluation import build_weekly_projection_matrix
    matrix = build_weekly_projection_matrix(_context(snapshot), refresh.weekly_projections)
    included = {snapshot.user_roster_id, *scope.opponent_roster_ids}
    selected = {r.player_id for r in refresh.selected_final.players}
    ecr = {r.player_id for r in refresh.market.players}
    priced = {r.player_id for r in market.board.prices} if market.board else selected & ecr
    owners = dict(snapshot.owner_by_player)
    exclusions = tuple(TargetExclusion(pid, owners.get(pid), None, reason)
        for pid in snapshot.tradeable_player_ids if owners.get(pid) in included
        for reason in (("MISSING_SELECTED_OR_MARKET_ECR_VALUE",) if pid not in selected & ecr
                       else ("MISSING_TRADE_MARKET_PRICE",) if pid not in priced else ()))
    base = TargetDiscoveryResult(1, snapshot.manifest.analysis_id, snapshot.league_key,
        snapshot.ranking_horizon, market.mode if market.board else "ECR-PROXY",
        stable_hash(refresh.selected_final), stable_hash(refresh.market),
        market.board.evidence_hash if market.board else None, config, (), (), exclusions,
        ("Target discovery reached the time budget; unfinished targets were not published.",), "",
        tuple(r for r in roster_projection_exclusions(snapshot, matrix) if r.roster_id in included))
    return replace(base, evidence_hash=stable_hash(asdict(base)))


def run_target_workflow(
    league_key: str,
    *,
    search: bool,
    config_path: str | Path | None = None,
    target_policy_path: str | Path | None = None,
    decision_policy_path: str | Path | None = None,
    options: EvaluationOptions = EvaluationOptions(),
    output_path: str | Path | None = None,
    csv_path: str | Path | None = None,
    expert_pool_path: str | Path | None = None,
    cache_dir: str | Path | None = None,
    budget_path: str | Path = "data/cache/trade/fantasypros/daily_budget.json",
    market_import_path: str | Path | None = None,
    performance_history_path: str | Path | None = None,
    proxy_only: bool = False,
    market_source: TradeMarketSource | None = None,
    small_pool: int | None = None,
    large_pool: int | None = None,
    max_exact: int | None = None,
    max_large_exact: int | None = None,
    max_results: int | None = None,
    opponent: str | None = None,
    time_budget_seconds: float | None = None,
    prior_preparation_seconds: float = 0.0,
) -> TargetWorkflowResult:
    """Prepare one target discovery, then optionally construct exact packages."""

    preparation_started = perf_counter()
    policy = _policy(
        league_key,
        search=search,
        config_path=config_path,
        target_policy_path=target_policy_path,
        small_pool=small_pool,
        large_pool=large_pool,
        max_exact=max_exact,
        max_large_exact=max_large_exact,
        max_results=max_results,
    )
    decision_path = resolve_league_policy_path(
        league_key,
        "trade_decision",
        config_path=config_path,
        explicit_path=decision_policy_path,
    )
    refresh = refresh_value_boards(
        league_key,
        config_path=config_path,
        expert_pool_path=expert_pool_path,
        cache_dir=cache_dir,
        budget_path=budget_path,
    )
    snapshot = refresh.refresh.snapshot
    scope = resolve_scope(snapshot, opponent) if search else None
    performance_history = (
        update_performance_history(
            refresh,
            policy=policy.performance,
            path=performance_history_path,
            collect_outcomes=True,
        ) if policy.performance is not None else None
    )
    market = resolve_trade_market_evidence(
        league=snapshot.league,
        # A bulk chart need not price every free agent. Target and package
        # construction exclude unpriced assets before making fairness claims.
        required_player_ids=(),
        current_week=snapshot.manifest.current_week,
        source=(
            None if proxy_only or (market_import_path and market_source is None)
            else market_source or StatsGuyFantasyClient()
        ),
        authorized_import_path=None if proxy_only else market_import_path,
        archive_dir=(
            None if proxy_only else Path("data/cache/trade/market")
            / league_key / str(snapshot.league.season)
        ),
    )
    normalized_options = _options_from_policy(options, decision_path)
    as_of = datetime.now(timezone.utc)
    preparation_seconds = prior_preparation_seconds + perf_counter() - preparation_started
    finder_enabled = search
    finder_policy = (policy.execution or FinderExecutionPolicy()) if finder_enabled else None
    execution = (SearchExecution(
        time_budget_seconds if time_budget_seconds is not None else (
            finder_policy.opponent_seconds if opponent is not None else finder_policy.league_seconds),
        stable_hash((snapshot, refresh.weekly_projections, refresh.selected_final, refresh.market,
                     market, normalized_options, policy, snapshot.ranking_horizon)),
    ) if finder_enabled else None)
    discovery_started = perf_counter()
    discovery_args = dict(
        projections=refresh.weekly_projections,
        selected_board=refresh.selected_final,
        market_ecr_board=refresh.market,
        trade_market=market,
        config=policy.discovery,
        options=normalized_options,
        performance_context=(
            performance_history.evidence.contexts
            if performance_history and performance_history.evidence else ()
        ),
    )
    if finder_enabled:
        discovery_args['opponent_roster_ids'] = scope.opponent_roster_ids
        try:
            with search_execution(execution):
                targets = evaluate_at(as_of, discover_trade_targets, snapshot, **discovery_args)
        except SearchDeadline:
            targets = _interrupted_discovery(snapshot, refresh, market, policy.discovery, scope)
    else:
        targets = evaluate_at(as_of, discover_trade_targets, snapshot, **discovery_args)
    discovery_seconds = perf_counter() - discovery_started
    if search and policy.optimizer is None:
        raise ValueError("Search requires a league-scoped target optimizer policy")
    performance: dict[str, Any] = {}
    package_function = find_trade_packages if finder_enabled else optimize_target_packages
    finder_args = dict(scope=scope, execution_policy=finder_policy, execution=execution,
                       max_exact=max_exact, max_large_exact=max_large_exact,
                       max_results=max_results) if finder_enabled else {}
    packages = (
        evaluate_at(as_of, package_function,
            snapshot,
            projections=refresh.weekly_projections,
            selected_board=refresh.selected_final,
            market_ecr_board=refresh.market,
            trade_market=market,
            target_result=targets,
            config=policy.optimizer,
            options=normalized_options,
            metrics=performance,
            **finder_args,
        ) if search else None
    )
    performance.update(provider_preparation_seconds=round(preparation_seconds, 3),
                       discovery_seconds=round(discovery_seconds, 3))
    prior_board = market.prior_board or (
        market.board if market.mode == "PRIOR_WEEK_MARKET" else None
    )
    payload: dict[str, Any] = {
        "schema_version": 1,
        "operation": "TRADE TARGET SEARCH" if search else "TRADE TARGETS",
        "manifest_id": snapshot.manifest.analysis_id,
        "league_key": league_key,
        "pricing_mode": targets.pricing_mode,
        "prior_market": (
            {
                "as_of": prior_board.as_of.isoformat(),
                "board_hash": prior_board.evidence_hash,
                "priced_players": len(prior_board.prices),
                "status": "INDICATIVE_ONLY",
            } if prior_board is not None else None
        ),
        "target_policy": {
            "version": policy.version,
            "evidence_status": policy.status,
            "basis": policy.basis,
        },
        "value_coverage": {
            "included_players": len(refresh.selected_final.players),
            "excluded_players": list(refresh.selected_final.excluded_players),
        },
        "performance_history": (
            {
                "path": str(performance_history.path),
                "status": performance_history.status,
                "captured_expectations": performance_history.captured_expectations,
                "total_expectations": performance_history.total_expectations,
                "total_outcomes": performance_history.total_outcomes,
                "compatible_contexts": performance_history.compatible_contexts,
                "history_hash": performance_history.history_hash,
                "outcome_refresh": performance_history.outcome_refresh,
                "evidence": asdict(performance_history.evidence) if performance_history.evidence else None,
            } if performance_history else None
        ),
        "targets": asdict(targets),
        "packages": asdict(packages) if packages else None,
        "performance": performance if search else None,
        "warnings": tuple(dict.fromkeys((*market.warnings, *targets.warnings, *(packages.warnings if packages else ())))),
        "evidence_hash": "",
    }
    evidence_hash = stable_hash(payload)
    payload["evidence_hash"] = evidence_hash
    target = Path(output_path or refresh.output_path.with_name(
        f"trade_{'search' if search else 'targets'}_{evidence_hash[:16]}.json"
    ))
    manifest = finish_trade_run(target, refresh, as_of=as_of,
        inputs={'operation': 'finder_search' if finder_enabled else 'target_search' if search else 'targets', 'trade_market': market,
                'performance_context': performance_history.evidence.contexts if performance_history and performance_history.evidence else (),
                'target_hash': targets.evidence_hash, 'package_hash': packages.evidence_hash if packages else None,
                **({'recorded_result': {'targets': asdict(targets), 'packages': asdict(packages)}} if finder_enabled else {})},
        policy={'options': normalized_options, 'target_policy': policy},
        readiness={'inputs_complete': not targets.roster_exclusions and not any(
                       any(token in row.reason for token in ('MISSING', 'INCOMPLETE', 'UNAVAILABLE'))
                       for row in targets.exclusions),
                   'search_complete': False if search else None,
                   'candidate_confidence': {row.evaluation_hash: row.decision_axes.confidence
                       if row.decision_axes else 'INCOMPLETE'
                       for row in packages.evaluated_decisions} if packages else {},
                   'pricing_mode': targets.pricing_mode, 'informational_warnings': payload['warnings']})
    atomic_write_json(target, payload)
    csv_target = Path(csv_path) if csv_path else None
    feedback_path = target.with_suffix(".feedback.csv")
    result = TargetWorkflowResult(
        targets, packages, market, refresh, target, csv_target, evidence_hash,
        policy.status, policy.basis, performance_history, feedback_path, manifest,
        performance if search else None,
    )
    _write_feedback_template(feedback_path, result)
    if csv_target:
        _write_csv(csv_target, _csv_rows(result))
    return result


def load_target_workflow_evidence(path: str | Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    saved_hash = value.get("evidence_hash")
    unhashed = dict(value)
    unhashed["evidence_hash"] = ""
    if not isinstance(saved_hash, str) or stable_hash(unhashed) != saved_hash:
        raise ValueError("Trade target evidence hash does not match its contents")
    value["replay_mode"] = "OFFLINE/NON-CURRENT"
    return value


def target_workflow_report(result: TargetWorkflowResult) -> dict[str, Any]:
    value = json.loads(result.output_path.read_text(encoding="utf-8"))
    # The saved, hash-verified evidence remains complete. The display report
    # links repeated exact evaluations to their first full occurrence so a
    # multi-lane package does not print the same large proof several times.
    seen_evaluations: set[str] = set()
    for opportunity in (value.get('packages') or {}).get('opportunities', ()):
        evaluation = opportunity.get('evaluation')
        if not isinstance(evaluation, dict):
            continue
        evaluation_hash = evaluation.get('evidence_hash')
        if not isinstance(evaluation_hash, str) or not evaluation_hash:
            continue
        if evaluation_hash in seen_evaluations:
            opportunity['evaluation'] = {'evidence_ref': evaluation_hash}
        else:
            seen_evaluations.add(evaluation_hash)
    value['output_path'] = str(result.output_path)
    value['report_evidence_linking'] = 'Repeated exact evaluations reference the first full occurrence by evidence hash; the saved file is complete.'
    value['run_manifest'] = manifest_summary(result.run_manifest)
    if result.performance is not None:
        value['performance'] = {**result.performance, 'evidence_bytes': result.output_path.stat().st_size}
    return value


def format_target_workflow(result: TargetWorkflowResult) -> str:
    if isinstance(result.packages, FinderResult):
        return _format_finder(result)
    names = {row.player_id: row.name for row in result.board_refresh.refresh.snapshot.players}
    statuses = {
        (row.lane, row.player_id): row for row in result.packages.target_statuses
    } if result.packages else {}
    labels = {"BUY_LOW": "BUY LOW", "SELL_HIGH": "SELL HIGH", "CONSOLIDATE": "CONSOLIDATE", "NEED_FIT": "NEED FIT"}
    lines = [
        f"TRADE ASSISTANT - {result.targets.league_key} - {result.targets.horizon} TARGETS",
        f"Policy: {result.policy_status} — {result.policy_basis}",
        f"Market: {result.targets.pricing_mode}; targets are WATCH until an exact partner-credible offer passes.",
        f"Feedback template: {result.feedback_path} (optional; never overwritten)",
    ]
    if result.targets.coverage_counts:
        lines.append("Coverage: " + "; ".join(f"{key}={value}" for key, value in result.targets.coverage_counts))
    for row in result.targets.roster_exclusions:
        lines.append(f"Protected missing evidence on roster {row.roster_id}: {row.reason}; " + ", ".join(
            f"{names.get(pid, pid)}/W{week}" for pid, week in row.missing_player_weeks
        ))
    missing_values = result.board_refresh.selected_final.excluded_players
    if missing_values:
        lines.append(f"Value coverage exclusions ({len(missing_values)}): " + "; ".join(
            f"{names.get(pid, pid)}: {reason}" for pid, reason in missing_values
        ))
    if result.performance_history:
        history = result.performance_history
        lines.append(
            f"Recent performance: {history.status}; {history.compatible_contexts} compatible "
            f"players, {history.total_outcomes} outcome rows; captured "
            f"{history.captured_expectations} current-week expectations to {history.path}"
        )
        if history.outcome_refresh:
            outcome = history.outcome_refresh
            lines.append(f"Completed results: {outcome['status']}; "
                         f"{outcome['added_outcomes']} new observations; "
                         f"{len(outcome['exclusions'])} player-weeks unavailable")
            lines.extend(f"- {warning}" for warning in outcome['warnings'])
    else:
        lines.append("Recent performance: UNAVAILABLE; no performance policy configured")
    for lane in TARGET_KINDS:
        rows = tuple(row for row in result.targets.targets if row.kind == lane)
        if not rows:
            continue
        lines.append(labels[lane])
        for row in rows:
            status = statuses.get((lane, row.player_id))
            price = (
                (
                    "prior-week indicative chart "
                    if row.trade_price.mode == "PRIOR_WEEK_MARKET"
                    else "chart "
                )
                + f"{row.trade_price.raw_value:.2f}, 7d "
                + (
                    f"{row.trade_price.provider_change_7d:+.2f}"
                    if row.trade_price.provider_change_7d is not None else "unavailable"
                )
                + f", as of {row.trade_price.as_of.isoformat() if row.trade_price.as_of else 'unknown'}"
                + f", {row.trade_price.scoring_variant or 'variant unavailable'}"
                if row.trade_price.raw_value is not None
                else "ECR-PROXY; chart price/change unavailable"
            )
            performance = (
                f"{row.performance_support} ({row.performance.signal}, "
                f"n={row.performance.sample_size}, shrunk points "
                + (
                    f"{row.performance.shrunk_point_residual:+.2f}"
                    if row.performance.shrunk_point_residual is not None else "unavailable"
                ) + ")"
                if row.performance else "UNAVAILABLE"
            )
            lines.append(
                f"  {row.rank_in_lane}. {row.player_name} ({row.position}) — "
                + ("CONDITIONAL ROSTER FIT; " if any("Conditional roster fit" in warning for warning in row.warnings) else "")
                +
                f"{status.status if status else row.status}; owner {row.roster.owner_team_name} "
                f"[{row.roster.owner_roster_id}]; selected p{row.intrinsic.percentile:.2f}, "
                f"market-ECR p{row.market_ecr.percentile:.2f}, {price}; "
                "user standalone lineup "
                + (
                    f"{row.roster.user_standalone_lineup_gain:+.2f}"
                    if row.roster.user_standalone_lineup_gain is not None
                    else "unavailable"
                )
                + "; "
                f"owner disposable {row.roster.owner_disposable}; "
                f"performance {performance}"
            )
    if result.packages:
        lines.append("COMPARISONS — conditional estimates are not recommended offers"
                     if any(row.intrinsic_outcome == "CONDITIONAL" for row in result.packages.opportunities)
                     else "OFFERS — intrinsic outcome and market fairness are separate")
        for lane in TARGET_KINDS:
            for target in (row for row in result.targets.targets if row.kind == lane):
                offers = tuple(
                    row for row in result.packages.opportunities
                    if row.lane == lane and target.player_id in row.generated_by_target_ids
                )
                if not offers:
                    continue
                lines.append(f"  {labels[lane]}: {target.player_name}")
                for offer in offers:
                    sent = ", ".join(names.get(pid, pid) for pid in offer.sent_player_ids)
                    received = ", ".join(names.get(pid, pid) for pid in offer.received_player_ids)
                    lines.append(
                        f"    {offer.intrinsic_outcome} / {offer.market_fairness.status}: "
                        f"send {sent}; receive {received}; user lineup "
                        f"{offer.user_weighted_lineup_delta:+.2f}, depth {offer.user_depth_delta:+.2f}; "
                        f"partner lineup {offer.partner_weighted_lineup_delta:+.2f}, "
                        f"depth {offer.partner_depth_delta:+.2f}; "
                        f"market gap {offer.market_fairness.user_price_delta:+.2f}"
                    )
                    lines.append(
                        f"      Shared exact package verdict: {offer.evaluation.decision_label}; "
                        "target strategy and market screens are additional filters."
                    )
                    if offer.market_fairness.mode == "ECR-PROXY":
                        lines.append("      PROVISIONAL MARKET: ECR proxy is not direct trade-chart fairness.")
                    impact = offer.evaluation.team_impacts[0]
                    risk = offer.evaluation.risk_impacts[0]
                    if "ROSTER-EVIDENCE-PARTIAL" in offer.evaluation.modes:
                        lines.append("      Known-player estimates only; absolute roster forecasts and downside totals are incomplete.")
                    lines.append(
                        f"      Best W{impact.best_week} {impact.best_week_delta:+.2f}; "
                        f"worst W{impact.worst_week} {impact.worst_week_delta:+.2f}; "
                        f"playoffs {impact.playoff_delta:+.2f}; "
                        f"downside {risk.offense_downside_loss_delta:+.2f}; "
                        f"selected {offer.user_selected_delta:+.2f}, "
                        f"market-ECR {offer.user_market_ecr_delta:+.2f}"
                    )
                    moves = ", ".join(
                        f"{move.roster_id} {move.kind.lower()} "
                        + "/".join(names.get(pid, pid) for pid in move.chosen_player_ids)
                        for move in offer.evaluation.secondary_moves if move.kind != "NONE"
                    )
                    if moves:
                        lines.append(f"      Secondary moves: {moves}")
                    if offer.evaluation.provisional_reversal_conditions:
                        reversal = offer.evaluation.provisional_reversal_conditions[0]
                        lines.append(f"      Provisional reversal: {reversal.condition}")
                    if offer.consolidation:
                        evidence = offer.consolidation
                        uses = ", ".join(
                            f"{names.get(use.player_id, use.player_id)} {use.use} "
                            f"lineup {use.marginal_lineup_points:+.2f} depth {use.marginal_depth_above_waiver:+.2f}"
                            for use in evidence.partner_asset_uses
                        )
                        lines.append(
                            f"      Premium {offer.market_fairness.consolidation_premium_value}; "
                            f"target marginal {evidence.target_marginal_lineup_points:+.2f}; "
                            f"partner use: {uses}"
                        )
                        if offer.market_fairness.premium_sensitivity:
                            lines.append(
                                "      Premium sensitivity (market fairness only): "
                                + ", ".join(
                                    f"{scenario.ratio:.0%} {scenario.status} "
                                    f"(gap {scenario.user_price_delta:+.2f})"
                                    for scenario in offer.market_fairness.premium_sensitivity
                                )
                            )
    if not result.targets.targets:
        lines.append("No supported targets; no offer is implied.")
    if result.packages and not result.packages.opportunities:
        lines.append("No offer passed the exact intrinsic, market, partner, and risk gates; targets remain WATCH.")
    for warning in tuple(dict.fromkeys((*result.targets.warnings, *(result.packages.warnings if result.packages else ())))):
        lines.append(f"Warning: {warning}")
    return "\n".join((*lines, *run_footer(result.run_manifest)))


def _format_finder(result: TargetWorkflowResult) -> str:
    packages = result.packages
    snapshot = result.board_refresh.refresh.snapshot
    names = {p.player_id: p.name for p in snapshot.players}
    teams = {t.roster_id: t.display_name for t in snapshot.teams}
    player_list = lambda ids: ", ".join(names.get(p, p) for p in ids)
    labels = {"RECOMMENDED": "Recommended", "NEGOTIATION_CANDIDATE": "Negotiation candidate",
              "COUNTEROFFER_IDEA": "Counteroffer idea"}
    lines = [f"Trade ideas — {snapshot.league_key}",
             f"Scope: {packages.scope.mode.lower()} | {len(packages.ideas)} ideas | {len(packages.evaluated_decisions)} completed evaluations",
             f"Search: {packages.timing['search_seconds']:.1f}s / {packages.execution_profile['time_budget_seconds']:g}s | {packages.termination.lower().replace('_', ' ')}"]
    lines.append(f"Football policy: {result.policy_status}; execution {packages.execution_profile['version']}")
    for idea in packages.ideas:
        d = idea.decision
        lines.extend(("", f"{labels[idea.status]} with {teams[d.opponent_roster_id]}",
            f"Send {player_list(d.sent_player_ids)} → Receive {player_list(d.received_player_ids)}",
            f"ROS lineup: you {d.user_weighted_lineup_delta:+.2f}, opponent {d.partner_weighted_lineup_delta:+.2f} | chart {d.market_fairness.status.lower()} | strict verdict {d.package_verdict}"))
        if idea.failed_checks:
            gates = {g.name: g for g in d.decision_axes.gates} if d.decision_axes else {}
            labels_for_gates = {"partner_market_delta": "Opponent consensus value",
                "user_selected_value_delta": "Your selected-expert value", "user_offense_downside": "Your downside risk",
                "chart_fairness": "Chart price gap", "partner_plausibility": "Opponent roster usefulness",
                "consolidation_usefulness": "Every incoming player's usefulness"}
            for name in idea.failed_checks:
                gate = gates.get(name)
                detail = f" ({gate.actual} {gate.comparison} {gate.threshold} required)" if gate else ""
                lines.append(f"Check to resolve: {labels_for_gates.get(name, name.replace('_', ' '))}{detail}")
        moves = [f"{teams[m.roster_id]} {m.kind.lower()}: {player_list(m.chosen_player_ids)}"
                 for m in idea.evaluation.secondary_moves if m.kind != "NONE"]
        if moves:
            lines.append("Required moves: " + "; ".join(moves))
        if idea.status == 'COUNTEROFFER_IDEA':
            lines.append(f"Repair search: {idea.repair_search_status.lower().replace('_', ' ')}; {len(idea.repairs)} checked")
        for repair in idea.repairs:
            verdict = repair.package_verdict or "not evaluated"
            lines.append(f"Checked repair: send {player_list(repair.sent_player_ids)} → receive {player_list(repair.received_player_ids)}; {labels.get(repair.status, repair.status.lower())}; strict {verdict}")
            if repair.failed_checks:
                lines.append("  Remaining checks: " + ", ".join(repair.failed_checks))
    if not packages.ideas:
        lines.append("No supported ideas in the completed evaluations. Unfinished packages remain unevaluated.")
    lines.append("")
    for rid, name in zip(packages.scope.opponent_roster_ids, packages.scope.opponent_team_names):
        rows = [c for c in packages.shape_coverage if c.opponent_roster_id == rid]
        lines.append(f"{name}: {sum(c.evaluated for c in rows)} evaluated, {sum(c.unevaluated for c in rows)} constructed but unevaluated, {sum(c.roster_pruned for c in rows)} roster-pruned; {sum(c.pool_limited for c in rows)} shapes use limited pools")
    notes = []
    if packages.roster_exclusions:
        notes.append("Protected missing roster projections: " + ", ".join(sorted({r.roster_id for r in packages.roster_exclusions})))
    gaps = [e for e in result.targets.exclusions if any(s in e.reason for s in ("MISSING", "INCOMPLETE", "UNAVAILABLE"))]
    if gaps:
        notes.append(f"{len(gaps)} scoped asset evidence gaps; see saved diagnostics")
    notes.extend(("Negotiation and counteroffer ideas retain their failed checks and are not approved offers.",
                  "Full coverage, timing and evidence are in the saved JSON. No trade is submitted."))
    lines.extend(f"Evidence note: {note}" for note in notes)
    return "\n".join((*lines, *run_footer(result.run_manifest)))
