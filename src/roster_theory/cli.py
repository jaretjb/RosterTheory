from __future__ import annotations

import argparse
import csv
import io
import json
import sys
import time
from importlib import resources
from contextlib import redirect_stdout
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from roster_theory.draft_analysis import (
    analyze_snapshot,
    historical_position_pick_curves,
    simulation_round_tendencies,
)
from roster_theory.draft_preferences import load_draft_preferences
from roster_theory.doctor import audit_setup, format_doctor
from roster_theory.assistant import recommend_available
from roster_theory.fantasypros import FantasyProsClient, FantasyProsError, describe_shape
from roster_theory.fantasypros_import import build_fantasypros_board
from roster_theory.expert_accuracy_history import (
    fetch_accuracy_history,
    write_accuracy_history,
)
from roster_theory.expert_inputs import (
    ARTIFACTS as EXPERT_INPUT_ARTIFACTS,
    inspect_expert_inputs,
    refresh_expert_inputs,
)
from roster_theory.schedule_inputs import inspect_schedule_input, prepare_schedule_input
from roster_theory.season_prepare import inspect_season_inputs, prepare_season_inputs
from roster_theory.private_setup import (
    ARTIFACTS as SETUP_ARTIFACTS,
    add_league,
    explain_private_setup,
    import_private_runtime,
    initialize_private_runtime,
    inspect_private_setup,
    scaffold_private_inputs,
    set_owner,
    show_redacted_setup,
    update_override,
)
from roster_theory.expert_rank_consistency import (
    audit_expert_rank_consistency,
    build_weighted_ballot_preferences,
    enrich_ranked_csv_with_dispersion,
)
from roster_theory.grouped_rankings import export_grouped_rankings
from roster_theory.league_boards import (
    build_league_board,
    fetch_board_sources,
    write_board,
    write_csv as write_league_csv,
)
from roster_theory.manual_import import (
    build_manual_board,
    load_player_overrides,
    load_sleeper_players_file,
)
from roster_theory.mock_evidence import (
    MockEvidenceRecorder,
    audit_mock_evidence,
    evidence_paths,
    load_mock_evidence,
)
from roster_theory.mock_watcher import (
    ACQUISITION_MODES,
    MockDraftWatcher,
    format_mock_report,
    parse_draft_id,
)
from roster_theory.rankings import (
    add_vbd,
    load_accuracy,
    load_expert_pool,
    load_long_rankings_csv,
    starter_baselines,
    weighted_consensus,
)
from roster_theory.simulation import (
    OPPONENT_POSITION_STRESS_PROFILES,
    compare_strategies,
)
from roster_theory.sleeper import (
    SleeperClient,
    SleeperError,
    build_snapshot,
    find_league_config,
    load_league_config,
    load_owner_config,
    resolve_league_policy_path,
    save_snapshot,
)
from roster_theory.sleeper_adp import (
    audit_board_against_sleeper_adp,
    audit_historical_drafts_against_archived_adp,
    build_sleeper_adp_snapshot,
    scoring_adp_field,
)
from roster_theory.trade_provider_probe import (
    probe_fantasypros,
    probe_sleeper,
    save_probe,
)
from roster_theory.core.errors import (
    CoverageIncomplete,
    IdentityIncomplete,
    ProviderCapabilityMissing,
    RosterTheoryError,
    ScheduleIncomplete,
    SourceUnavailable,
    StaleData,
    Uncalibrated,
)
from roster_theory.terminal import (
    detect_stdout,
    render_banner,
    render_command_masthead,
)
from roster_theory.reporting import ReportFrame, interactive_progress, render_report
from roster_theory.trade.service import refresh_report, refresh_trade_snapshot
from roster_theory.waiver.service import (
    evaluate_entered_waiver,
    format_waiver_evaluation,
    format_waiver_search,
    refresh_waiver_snapshot,
    search_waivers,
    waiver_evaluation_report,
    waiver_refresh_report,
    waiver_search_action_summary,
    waiver_search_report,
)
from roster_theory.waiver_inputs import main as waiver_inputs_main
from roster_theory.waiver.evaluation import load_waiver_evaluation
from roster_theory.waiver.search import load_waiver_search
from roster_theory.trade.board_service import board_refresh_report, refresh_value_boards
from roster_theory.trade.evaluation import EvaluationOptions, load_trade_evaluation
from roster_theory.trade.evaluation_service import (
    diagnose_current_roster,
    evaluate_entered_trade,
    evaluation_report,
    format_roster_diagnosis,
    format_trade_evaluation,
)
from roster_theory.trade.search import SearchConfig
from roster_theory.trade.search_service import (
    format_gap_report,
    format_package_comparison,
    format_search_result,
    load_search_evidence,
    run_gap_report,
    run_league_search,
    run_package_comparison,
)


def _print_json(value: Any) -> None:
    print(json.dumps(value, indent=2, sort_keys=True, allow_nan=False))


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"Non-JSON constant: {value}")


def _config_path(args: argparse.Namespace) -> str | None:
    return getattr(args, "config", None)


def _failure_status(error: Exception) -> str:
    if isinstance(error, Uncalibrated):
        return "uncalibrated"
    if isinstance(error, (SourceUnavailable, ProviderCapabilityMissing)):
        return "unavailable"
    if isinstance(error, (CoverageIncomplete, IdentityIncomplete, ScheduleIncomplete)):
        return "incomplete"
    if isinstance(error, StaleData):
        return "stale"
    return "error"


def _failure_payload(product: str, args: argparse.Namespace, error: Exception) -> dict[str, Any]:
    return {
        "error_type": type(error).__name__,
        "league": getattr(args, "league", None),
        "product": product,
        "reason": str(error),
        "status": _failure_status(error),
    }


def _print_product_failure(
    product: str, args: argparse.Namespace, error: Exception
) -> None:
    payload = _failure_payload(product, args, error)
    if getattr(args, "json", False):
        _print_json(payload)
        return
    if isinstance(error, Uncalibrated):
        print(json.dumps(payload, sort_keys=True), file=sys.stderr)
        return
    print(f"{product} readiness: UNAVAILABLE; no recommendation available", file=sys.stderr)
    print(f"{product} failed: {error}", file=sys.stderr)


def _saved_notice(message: str, args: argparse.Namespace) -> None:
    print(message, file=sys.stderr if getattr(args, "json", False) else sys.stdout)


def _print_human_report(
    args: argparse.Namespace, report: str, frame: ReportFrame | None = None
) -> None:
    if not getattr(args, "json", False) and not getattr(args, "_masthead_printed", False):
        print(
            render_command_masthead(
                detect_stdout(sys.stdout),
                frame.product if frame is not None else "Report",
                suppressed=getattr(args, "no_banner", False),
            ),
            end="",
        )
    print(render_report(frame, report, detect_stdout(sys.stdout)) if frame else report)


def _command_title(args: argparse.Namespace) -> str:
    parts = (
        getattr(args, "command", None),
        getattr(args, "inputs_group", None),
        getattr(args, "expert_input_command", None),
        getattr(args, "trade_command", None),
        getattr(args, "waiver_command", None),
    )
    return " ".join(
        str(part).replace("-", " ").title() for part in parts if part
    )


def _print_command_identity(args: argparse.Namespace) -> None:
    rendered = render_command_masthead(
        detect_stdout(sys.stdout),
        _command_title(args),
        suppressed=getattr(args, "no_banner", False),
    )
    if rendered:
        print(rendered, end="")
        setattr(args, "_masthead_printed", True)


def _product_frame(
    product: str,
    league: str,
    horizon: Any,
    result: str,
    *,
    warnings: Any = (),
    complete: bool = True,
    paths: Any = (),
    limitations: Any = (),
) -> ReportFrame:
    weeks = (
        "weeks " + ", ".join(str(week) for week in horizon)
        if isinstance(horizon, (tuple, list)) else str(horizon)
    )
    warning_lines = tuple(str(item) for item in warnings if item)
    return ReportFrame(
        product=product,
        league=league,
        horizon=weeks,
        readiness="INCOMPLETE" if not complete else "DEGRADED" if warning_lines else "READY",
        result=result,
        warnings=warning_lines,
        limitations=tuple(str(item) for item in limitations if item),
        saved_paths=tuple(str(path) for path in paths if path),
    )


def command_leagues(args: argparse.Namespace) -> None:
    _print_json(load_league_config(_config_path(args)))


def command_snapshot(args: argparse.Namespace) -> None:
    config = find_league_config(args.league, _config_path(args))
    snapshot = build_snapshot(SleeperClient(), config)
    output = Path(args.output or f"data/cache/{args.league}.json")
    save_snapshot(snapshot, output)
    print(f"Saved {output}")


def command_analyze(args: argparse.Namespace) -> None:
    path = Path(args.snapshot or f"data/cache/{args.league}.json")
    snapshot = json.loads(path.read_text(encoding="utf-8"))
    analysis = analyze_snapshot(snapshot)
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(analysis, indent=2, sort_keys=True), encoding="utf-8")
        print(f"Saved {output}")
    else:
        _print_json(analysis)


def command_sleeper_adp_audit(args: argparse.Namespace) -> None:
    captured_at = int(time.time())
    capture_date = datetime.fromtimestamp(captured_at, timezone.utc).strftime("%Y-%m-%d")
    field = scoring_adp_field(args.scoring)
    client = SleeperClient()
    current = build_sleeper_adp_snapshot(
        client.season_projections(args.season, field),
        args.season,
        args.scoring,
        captured_at,
    )
    historical_season = args.season - 1
    archived = build_sleeper_adp_snapshot(
        client.season_projections(historical_season, field),
        historical_season,
        args.scoring,
        captured_at,
    )
    league_snapshot = _load_snapshot(args.league, args.snapshot)
    board = _load_board(args.board)
    report = {
        "schema_version": 1,
        "captured_at": captured_at,
        "league": args.league,
        "scoring": args.scoring,
        "active_recommendation_use": False,
        "current_board_comparison": audit_board_against_sleeper_adp(
            board, current
        ),
        "historical_proxy": audit_historical_drafts_against_archived_adp(
            league_snapshot, archived
        ),
        "forward_validation": {
            "snapshot_date": capture_date,
            "instruction": (
                "After each 2026 draft, compare its authoritative picks with this "
                "dated snapshot before considering any Sleeper ADP model weight."
            ),
        },
    }
    cache_dir = Path(args.cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    current_path = (
        cache_dir
        / f"season-{args.season}-captured-{capture_date}-{args.scoring}.json"
    )
    archived_path = (
        cache_dir
        / f"archive-{historical_season}-captured-{capture_date}-{args.scoring}.json"
    )
    current_path.write_text(
        json.dumps(current, indent=2, sort_keys=True), encoding="utf-8"
    )
    archived_path.write_text(
        json.dumps(archived, indent=2, sort_keys=True), encoding="utf-8"
    )
    output = Path(
        args.output
        or f"data/exports/sleeper_adp_audit_{args.league}_{capture_date}.json"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(f"Saved current Sleeper ADP snapshot to {current_path}")
    print(f"Saved archived-season proxy snapshot to {archived_path}")
    print(f"Saved audit to {output}")
    print("Sleeper ADP remains audit-only; recommendations were not changed")


def _write_csv(rows: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields and key != "experts":
                fields.append(key)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key) for key in fields})


def _load_board(path: str | Path) -> list[dict[str, Any]]:
    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(
            f"Draft board not found: {source}. Build a league-scored board "
            "from authorized expert inputs, or pass --board PATH."
        )
    with source.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _load_snapshot(league_key: str, explicit_path: str | None = None) -> dict[str, Any]:
    path = Path(explicit_path or f"data/cache/{league_key}.json")
    if not path.is_file():
        raise FileNotFoundError(
            f"Sleeper snapshot not found: {path}. Pass --snapshot PATH, or "
            f"run roster-theory snapshot {league_key} for a read-only refresh."
        )
    return json.loads(path.read_text(encoding="utf-8"))


def command_build_board(args: argparse.Namespace) -> None:
    snapshot = _load_snapshot(args.league, args.snapshot)
    accuracy = load_accuracy(args.accuracy)
    rows = load_long_rankings_csv(args.input)
    board = weighted_consensus(
        rows,
        accuracy,
        shrink_to_ecr=args.ecr_shrinkage,
        max_expert_share=args.max_expert_share,
    )
    league = snapshot["current"]["league"]
    if any(player.get("projected_points") is not None for player in board):
        baselines = starter_baselines(
            board,
            league.get("roster_positions", []),
            int(league.get("total_rosters") or league.get("settings", {}).get("num_teams") or 0),
        )
        board = add_vbd(board, baselines)
    output = Path(args.output or f"data/exports/{args.league}_board.csv")
    _write_csv(board, output)
    print(f"Saved {output} ({len(board)} players)")


def command_fantasypros_probe(args: argparse.Namespace) -> None:
    client = FantasyProsClient()
    params = {"position": args.position, "scoring": args.scoring}
    calls = {
        "experts": lambda: client.ranking_experts(args.season),
        "rankings": lambda: client.rankings(args.season, **params),
        "consensus": lambda: client.consensus_rankings(args.season, **params),
        "projections": lambda: client.projections(args.season, **params),
        "players": lambda: client.players(),
    }
    selected = calls[args.endpoint]()
    _print_json(describe_shape(selected))


def command_trade_sleeper_probe(args: argparse.Namespace) -> None:
    config_path = _config_path(args)
    config = find_league_config(args.league, config_path)
    report = probe_sleeper(
        SleeperClient(),
        str(config["league_id"]),
        user_id=str(load_owner_config(config_path).get("sleeper_user_id") or "") or None,
        weeks=list(args.weeks),
        include_players=not args.skip_players,
        include_trends=args.include_trends,
    )
    output = Path(
        args.output or f"data/exports/trade/sleeper_probe_{args.league}.json"
    )
    save_probe(report, output)
    print(f"Saved schema-only Trade Assistant probe to {output}")


def command_trade_fantasypros_probe(args: argparse.Namespace) -> None:
    report = probe_fantasypros(
        FantasyProsClient(),
        season=args.season,
        week=args.week,
        historical_season=args.historical_season,
        sleep=time.sleep,
    )
    output = Path(
        args.output or "data/exports/trade/fantasypros_capability_probe.json"
    )
    save_probe(report, output)
    print(
        "Saved schema-only Trade Assistant FantasyPros probe to "
        f"{output} ({report['requests_attempted']} requests)"
    )


def command_trade_refresh(args: argparse.Namespace) -> None:
    try:
        result = refresh_trade_snapshot(
            args.league,
            config_path=_config_path(args),
            ranking_horizon=args.ranking_horizon,
            schedule_path=args.schedule,
            player_cache_path=args.player_cache,
            output_path=args.output,
        )
    except (RosterTheoryError, SleeperError, ValueError) as exc:
        print(f"TRADE ASSISTANT refresh failed: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    _print_json(refresh_report(result))


def command_waiver_refresh(args: argparse.Namespace) -> None:
    try:
        result = refresh_waiver_snapshot(
            args.league,
            config_path=_config_path(args),
            player_cache_path=args.player_cache,
            output_path=args.output,
        )
    except (RosterTheoryError, SleeperError, KeyError, ValueError) as exc:
        print(f"WAIVER ASSISTANT refresh failed: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    _print_json(waiver_refresh_report(result))


def command_waiver_inputs(args: argparse.Namespace) -> None:
    """Build the installed Waiver input bundle without requiring a source script."""

    argv = [args.league]
    for option, value in (
        ("--output", args.output),
        ("--config", _config_path(args)),
        ("--policy", args.policy),
        ("--waiver-wire-policy", args.waiver_wire_policy),
        ("--contingency-file", args.contingency_file),
    ):
        if value is not None:
            argv.extend((option, str(value)))
    waiver_inputs_main(argv)


def command_waiver_evaluate(args: argparse.Namespace) -> None:
    try:
        if args.snapshot:
            _print_json(load_waiver_evaluation(args.snapshot))
            return
        if not args.add or not args.inputs:
            raise ValueError("waiver evaluate requires --add and --inputs")
        result = evaluate_entered_waiver(
            args.league,
            add=args.add,
            drop=args.drop,
            inputs_path=args.inputs,
            output_path=args.save_evidence,
            player_cache_path=args.player_cache,
            policy_path=args.policy,
            config_path=_config_path(args),
        )
    except (RosterTheoryError, SleeperError, KeyError, ValueError) as exc:
        _print_product_failure("WAIVER ASSISTANT evaluation", args, exc)
        raise SystemExit(2) from exc
    if args.json:
        _print_json(waiver_evaluation_report(result))
    else:
        evaluation = result.evaluation
        _print_human_report(args, format_waiver_evaluation(result), _product_frame(
            "Waiver evaluation", evaluation.league_key, evaluation.horizon,
            evaluation.decision_label or "No authoritative recommendation",
            warnings=evaluation.warnings,
            complete=evaluation.recommendation_generated,
            limitations=(evaluation.strongest_uncertainty,), paths=(result.output_path,),
        ))


def command_waiver_search(args: argparse.Namespace) -> None:
    try:
        if args.snapshot:
            _print_json(load_waiver_search(args.snapshot))
            return
        if not args.inputs:
            raise ValueError("waiver search requires --inputs")
        result = search_waivers(
            args.league,
            inputs_path=args.inputs,
            output_path=args.save_evidence,
            player_cache_path=args.player_cache,
            policy_path=args.policy,
            config_path=_config_path(args),
        )
    except (RosterTheoryError, SleeperError, KeyError, ValueError) as exc:
        _print_product_failure("WAIVER ASSISTANT search", args, exc)
        raise SystemExit(2) from exc
    if args.json:
        _print_json(waiver_search_report(result))
    else:
        search = result.search
        _print_human_report(
            args,
            format_waiver_search(result),
            ReportFrame(
                product="Waiver search",
                league=search.league_key,
                horizon="weeks " + ", ".join(str(week) for week in search.horizon),
                readiness=(
                    "INCOMPLETE"
                    if not search.exact_evaluations
                    else "DEGRADED"
                    if search.warnings
                    else "READY"
                ),
                result=waiver_search_action_summary(result),
                saved_paths=(str(result.output_path),),
                compact=True,
            ),
        )


def command_trade_values(args: argparse.Namespace) -> None:
    try:
        result = refresh_value_boards(
            args.league,
            config_path=_config_path(args),
            expert_pool_path=args.expert_pool,
            cache_dir=args.fantasypros_cache,
            budget_path=args.budget,
            output_path=args.output,
        )
    except (RosterTheoryError, SleeperError, FantasyProsError, ValueError) as exc:
        print(f"TRADE ASSISTANT value refresh failed: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    _print_json(board_refresh_report(result))


def command_trade_evaluate(args: argparse.Namespace) -> None:
    try:
        if args.snapshot:
            _print_json(load_trade_evaluation(args.snapshot))
            return
        if not args.send or not args.receive:
            raise ValueError("trade evaluate requires --send and --receive")
        result = evaluate_entered_trade(
            args.league,
            config_path=_config_path(args),
            send=args.send,
            receive=args.receive,
            options=EvaluationOptions(
                playoff_weight=args.playoff_weight,
                allow_partial_schedule=args.allow_partial,
                allow_rank_only=args.allow_rank_only,
                drop_overrides=tuple(args.drop),
                add_overrides=tuple(args.add),
                risk_posture=args.risk_posture.upper(),
            ),
            output_path=args.save_evidence,
            expert_pool_path=args.expert_pool,
            cache_dir=args.fantasypros_cache,
            budget_path=args.budget,
            policy_path=args.policy,
        )
    except (RosterTheoryError, SleeperError, FantasyProsError, ValueError) as exc:
        _print_product_failure("TRADE ASSISTANT evaluation", args, exc)
        raise SystemExit(2) from exc
    if args.json:
        _print_json(evaluation_report(result))
        _saved_notice(f"Saved evidence: {result.output_path}", args)
    else:
        evaluation = result.evaluation
        _print_human_report(args, format_trade_evaluation(evaluation), _product_frame(
            "Trade evaluation", evaluation.league_key, evaluation.horizon,
            evaluation.summary, warnings=evaluation.warnings,
            complete=evaluation.decision is not None, paths=(result.output_path,),
            limitations=("Expert ranks apply only to their declared horizon.",),
        ))


def command_trade_diagnose(args: argparse.Namespace) -> None:
    try:
        result = diagnose_current_roster(
            args.league,
            config_path=_config_path(args),
            options=EvaluationOptions(risk_posture=args.risk_posture.upper()),
            output_path=args.output,
            expert_pool_path=args.expert_pool,
            cache_dir=args.fantasypros_cache,
            budget_path=args.budget,
            policy_path=args.policy,
        )
    except (RosterTheoryError, SleeperError, FantasyProsError, ValueError) as exc:
        _print_product_failure("TRADE ASSISTANT diagnosis", args, exc)
        raise SystemExit(2) from exc
    if args.json:
        _print_json(
            {
                "diagnosis": asdict(result.diagnosis),
                "evidence_hash": result.evidence_hash,
                "output_path": str(result.output_path),
            }
        )
    else:
        _print_human_report(args, format_roster_diagnosis(result), _product_frame(
            "Trade roster diagnosis", args.league,
            tuple(week for week, _ in result.diagnosis.weekly_optimal_points),
            "Roster gaps and trade fit", paths=(result.output_path,),
            limitations=("Diagnosis is not an offer recommendation.",),
        ))


def command_trade_gaps(args: argparse.Namespace) -> None:
    try:
        result = run_gap_report(
            args.league,
            config_path=_config_path(args),
            output_path=args.output,
            csv_path=args.csv,
            expert_pool_path=args.expert_pool,
            cache_dir=args.fantasypros_cache,
            budget_path=args.budget,
        )
    except (RosterTheoryError, SleeperError, FantasyProsError, ValueError) as exc:
        _print_product_failure("TRADE ASSISTANT gap report", args, exc)
        raise SystemExit(2) from exc
    if args.json:
        _print_json(asdict(result.gaps))
        _saved_notice(f"Saved evidence: {result.output_path}", args)
        if result.csv_path:
            _saved_notice(f"Saved CSV: {result.csv_path}", args)
    else:
        _print_human_report(args, format_gap_report(result), _product_frame(
            "Trade gaps", result.gaps.league_key, result.gaps.horizon,
            "Position gaps and surplus", paths=(result.output_path, result.csv_path),
            limitations=("Gap report is not an offer recommendation.",),
        ))


def command_trade_search(args: argparse.Namespace) -> None:
    try:
        if args.snapshot:
            _print_json(load_search_evidence(args.snapshot))
            return
        result = run_league_search(
            args.league,
            config_path=_config_path(args),
            options=EvaluationOptions(risk_posture=args.risk_posture.upper()),
            config=SearchConfig(
                small_pool_per_team=args.small_pool,
                large_pool_per_team=args.large_pool,
                max_exact_per_opponent=args.max_exact,
                max_large_exact_per_opponent=args.max_large_exact,
                max_results=args.max_results,
            ),
            output_path=args.output,
            csv_path=args.csv,
            expert_pool_path=args.expert_pool,
            cache_dir=args.fantasypros_cache,
            budget_path=args.budget,
            policy_path=args.policy,
            search_policy_path=args.search_policy,
        )
    except (RosterTheoryError, SleeperError, FantasyProsError, ValueError) as exc:
        _print_product_failure("TRADE ASSISTANT search", args, exc)
        raise SystemExit(2) from exc
    if args.json:
        _print_json(asdict(result.search))
        _saved_notice(f"Saved evidence: {result.output_path}", args)
        if result.csv_path:
            _saved_notice(f"Saved CSV: {result.csv_path}", args)
    else:
        search = result.search
        _print_human_report(args, format_search_result(result), _product_frame(
            "Trade search", search.league_key, search.horizon,
            "Bounded package candidates", paths=(result.output_path, result.csv_path),
            limitations=("Search is bounded; omitted packages are not evaluated.",),
        ))


def command_trade_compare(args: argparse.Namespace) -> None:
    try:
        payload = json.loads(Path(args.packages).read_text(encoding="utf-8"))
        packages = payload.get("packages") if isinstance(payload, dict) else payload
        if not isinstance(packages, list):
            raise ValueError("Package file must be a JSON list or contain a 'packages' list")
        result = run_package_comparison(
            args.league,
            config_path=_config_path(args),
            packages=packages,
            options=EvaluationOptions(risk_posture=args.risk_posture.upper()),
            output_path=args.output,
            expert_pool_path=args.expert_pool,
            cache_dir=args.fantasypros_cache,
            budget_path=args.budget,
            policy_path=args.policy,
        )
    except (OSError, json.JSONDecodeError, RosterTheoryError, SleeperError, FantasyProsError, ValueError) as exc:
        _print_product_failure("TRADE ASSISTANT comparison", args, exc)
        raise SystemExit(2) from exc
    if args.json:
        _print_json(
            {
                "evaluations": [asdict(row) for row in result.evaluations],
                "evidence_hash": result.evidence_hash,
            }
        )
        _saved_notice(f"Saved evidence: {result.output_path}", args)
    else:
        _print_human_report(args, format_package_comparison(result), _product_frame(
            "Trade package comparison", args.league,
            result.evaluations[0].horizon if result.evaluations else "unavailable",
            f"Compared {len(result.evaluations)} packages", paths=(result.output_path,),
            complete=bool(result.evaluations),
            limitations=("Comparison is read-only and does not submit an offer.",),
        ))


def command_fantasypros_board(args: argparse.Namespace) -> None:
    snapshot = _load_snapshot(args.league, args.snapshot)
    league = snapshot["current"]["league"]
    with interactive_progress("Refreshing Draft board"):
        result = build_fantasypros_board(
            FantasyProsClient(),
            season=int(league.get("season") or 2026),
            scoring_settings=league.get("scoring_settings", {}),
            roster_positions=league.get("roster_positions", []),
            team_count=int(league.get("total_rosters") or league.get("settings", {}).get("num_teams") or 0),
            historical_accuracy=load_accuracy(args.accuracy),
            expert_limit=args.experts,
            sleeper_players=SleeperClient().players(),
            shrink_to_ecr=args.ecr_shrinkage,
            max_expert_share=args.max_expert_share,
        )
    output = Path(args.output or f"data/exports/{args.league}_board.csv")
    _write_csv(result.players, output)
    metadata_output = output.with_suffix(".metadata.json")
    metadata_output.write_text(json.dumps(result.metadata, indent=2, sort_keys=True), encoding="utf-8")
    limited = bool(result.metadata["public_api_limited"])
    _print_human_report(args, "FantasyPros board import complete.", ReportFrame(
        product="Draft FantasyPros board", league=args.league, horizon="preseason draft",
        readiness="INCOMPLETE" if limited else "READY",
        result=f"{len(result.players)} players; {'sample only' if limited else 'board built'}",
        warnings=("Free-tier sample mode; this board is not draft-ready.",) if limited else (),
        limitations=("Expert rankings apply only to their declared draft horizon.",),
        saved_paths=(str(output), str(metadata_output)),
    ))


def command_fantasypros_grouped_rankings(args: argparse.Namespace) -> None:
    result = export_grouped_rankings(
        FantasyProsClient(),
        season=args.season,
        accuracy_path=args.accuracy,
        annual_accuracy_path=args.annual_accuracy,
        output_dir=args.output_dir,
        expert_limit=args.experts,
        specialist_expert_limit=args.specialist_experts,
        cohort_size=args.cohort_size,
        ecr_shrinkage=args.ecr_shrinkage,
        specialist_ecr_shrinkage=args.specialist_ecr_shrinkage,
        expert_overrides_path=args.expert_overrides,
        max_skill_ranking_age_days=args.max_skill_ranking_age_days,
    )
    print(
        f"Saved grouped expert pools and rankings to {result.output_dir} "
        f"({result.request_count} API requests, {result.issue_count} issues)"
    )


def command_fantasypros_accuracy_history(args: argparse.Namespace) -> None:
    rows = fetch_accuracy_history(minimum_interval_seconds=args.minimum_interval)
    write_accuracy_history(rows, args.output)
    counts: dict[int, int] = {}
    for row in rows:
        counts[row.year] = counts.get(row.year, 0) + 1
    print(f"Saved annual FantasyPros draft accuracy to {args.output}")
    print(" | ".join(f"{year}: {count} experts" for year, count in sorted(counts.items())))


def _expert_input_options(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "config_path": _config_path(args),
        "season": args.season,
        "artifact": args.artifact,
        "data_dir": args.data_dir,
        "draft_category": args.draft_category_output,
        "draft_annual": args.draft_annual_output,
        "inseason_accuracy": args.inseason_accuracy_output,
        "inseason_pool": args.pool_output,
        "audit": args.audit_output,
        "evidence_dir": getattr(args, "evidence_dir", None),
        "budget": getattr(args, "budget", None),
    }


def _print_expert_input_result(args: argparse.Namespace, result: Mapping[str, Any]) -> None:
    if args.json:
        _print_json(result)
        return
    print(
        f"Expert inputs: {str(result['status']).upper()} | "
        f"league {result['league']} | season {result['season']}"
    )
    for artifact in result["artifacts"]:
        print(
            f"- {artifact['id']}: {artifact['status']} — {artifact['reason']} "
            f"({artifact['path']})"
        )
    for error in result["errors"]:
        print(f"  Next: {error['next_command']}")


def command_inputs_experts_inspect(args: argparse.Namespace) -> None:
    result = inspect_expert_inputs(args.league, **_expert_input_options(args))
    _print_expert_input_result(args, result)


def command_inputs_experts_validate(args: argparse.Namespace) -> None:
    result = inspect_expert_inputs(args.league, **_expert_input_options(args))
    result["operation"] = "validate"
    _print_expert_input_result(args, result)
    if result["status"] != "ready":
        raise SystemExit(2)


def command_inputs_experts_refresh(args: argparse.Namespace) -> None:
    options = {
        **_expert_input_options(args),
        "replay_dir": args.replay_dir,
        "dry_run": args.dry_run,
        "minimum_interval": args.minimum_interval,
        "pool_size": args.pool_size,
        "maximum_source_count": args.maximum_source_count,
        "freshness_hours": args.freshness_hours,
    }
    if not args.json and not args.dry_run:
        preview = refresh_expert_inputs(args.league, **{**options, "dry_run": True})
        call = preview["provider_calls"][0]
        print(
            f"Plan: {call['budget_cost']} FantasyPros request(s); "
            f"{len(preview['writes'])} local artifact write(s).",
            file=sys.stderr,
        )
    result = refresh_expert_inputs(args.league, **options)
    _print_expert_input_result(args, result)


def command_inputs_experts_import(args: argparse.Namespace) -> None:
    options = {
        **_expert_input_options(args),
        "replay_dir": args.input,
        "dry_run": args.dry_run,
        "minimum_interval": 1.0,
        "pool_size": args.pool_size,
        "maximum_source_count": args.maximum_source_count,
        "freshness_hours": args.freshness_hours,
    }
    result = refresh_expert_inputs(args.league, **options)
    result["operation"] = "import"
    _print_expert_input_result(args, result)


def _print_schedule_input_result(args: argparse.Namespace, result: Mapping[str, Any]) -> None:
    if args.json:
        _print_json(result)
        return
    print(
        f"NFL schedule: {str(result['status']).upper()} | "
        f"league {result['league']} | season {result['season']}"
    )
    print(f"- schedule: {result['schedule_path']}")
    if result.get("source"):
        print(f"- source: {result['source']} ({result['source_url']})")
    if result.get("validation"):
        validation = result["validation"]
        print(
            f"- coverage: {validation['teams']} teams, "
            f"{validation['weeks']} weeks, {validation['games']} games"
        )
    if result.get("reason"):
        print(f"- reason: {result['reason']}")
    if result.get("next_command"):
        print(f"  Next: {result['next_command']}")


def command_inputs_schedule_inspect(args: argparse.Namespace) -> None:
    result = inspect_schedule_input(
        args.league, config_path=_config_path(args), season=args.season, path=args.output
    )
    _print_schedule_input_result(args, result)


def command_inputs_schedule_validate(args: argparse.Namespace) -> None:
    result = inspect_schedule_input(
        args.league, config_path=_config_path(args), season=args.season, path=args.output
    )
    result["operation"] = "validate"
    _print_schedule_input_result(args, result)
    if result["status"] != "ready":
        raise SystemExit(2)


def command_inputs_schedule_refresh(args: argparse.Namespace) -> None:
    try:
        result = prepare_schedule_input(
            args.league,
            config_path=_config_path(args),
            season=args.season,
            output_path=args.output,
            evidence_output_path=args.evidence_output,
            replay_path=args.replay,
            dry_run=args.dry_run,
        )
    except (RosterTheoryError, OSError, ValueError) as exc:
        print(f"NFL schedule refresh failed: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    _print_schedule_input_result(args, result)


def command_inputs_schedule_import(args: argparse.Namespace) -> None:
    try:
        result = prepare_schedule_input(
            args.league,
            config_path=_config_path(args),
            season=args.season,
            output_path=args.output,
            evidence_output_path=args.evidence_output,
            import_path=args.input,
            source=args.source,
            source_url=args.source_url,
            license_name=args.license,
            captured_at=args.captured_at,
            use_restriction=args.use_restriction,
            dry_run=args.dry_run,
        )
    except (RosterTheoryError, OSError, ValueError) as exc:
        print(f"NFL schedule import failed: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    _print_schedule_input_result(args, result)


def _print_season_input_result(args: argparse.Namespace, result: Mapping[str, Any]) -> None:
    if args.json:
        _print_json(result)
        return
    print(
        f"Season inputs: {str(result['status']).upper()} | "
        f"assistant {result['assistant']}"
    )
    if result.get("preflight"):
        print(
            f"- preflight: {result['provider_calls']} provider request(s), "
            f"{len(result['preflight'])} operation(s)"
        )
    for league in result["leagues"]:
        print(f"- {league['league']} ({league['season']}): {league['status']}")
        for artifact in league["artifacts"]:
            if artifact["status"] not in {"ready", "optional"}:
                print(f"  {artifact['artifact']}: {artifact['status']} — {artifact.get('reason', '')}")
                print(f"  Next: {artifact['next_command']}")
    for error in result.get("errors", []):
        print(f"- {error['type']}: {error['reason']}")
        print(f"  Next: {error['next_command']}")
    print("- recommendations: none; Sleeper writes: 0")


def command_inputs_status(args: argparse.Namespace) -> None:
    result = inspect_season_inputs(
        args.league, all_leagues=args.all_leagues, assistant=args.assistant,
        config_path=_config_path(args), data_dir=args.data_dir,
    )
    _print_season_input_result(args, result)


def command_inputs_prepare(args: argparse.Namespace) -> None:
    result = prepare_season_inputs(
        args.league, all_leagues=args.all_leagues, assistant=args.assistant,
        config_path=_config_path(args), data_dir=args.data_dir,
        refresh=args.refresh, offline=args.offline, dry_run=args.dry_run,
    )
    _print_season_input_result(args, result)


def _print_setup_result(args: argparse.Namespace, result: Mapping[str, Any]) -> None:
    if args.json:
        _print_json(result)
        return
    print(f"Private setup: {str(result['status']).upper()} | {result['operation']}")
    for path in result.get("writes", ()):
        print(f"- write: {path}")
    for path in result.get("backups", ()):
        print(f"- backup: {path}")
    for league in result.get("leagues", ()):
        print(f"- {league['league']} ({league['season']})")
        for artifact in league["artifacts"]:
            print(f"  {artifact['artifact']}: {artifact['status']} — {artifact['path']}")
    if result.get("config") is not None:
        print(json.dumps(result["config"], indent=2, sort_keys=True))
    if result.get("artifact_report") is not None:
        print(json.dumps(result["artifact_report"], indent=2, sort_keys=True))
    for name, explanation in result.get("artifacts", {}).items():
        print(f"- {name}: {explanation}")
    if result.get("reason"):
        print(f"- reason: {result['reason']}")
    if result.get("next_command"):
        print(f"  Next: {result['next_command']}")


def _setup_result(
    args: argparse.Namespace, function: Any, /, *call_args: Any, **kwargs: Any
) -> None:
    try:
        result = function(*call_args, **kwargs)
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        print(f"Private setup failed: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    _print_setup_result(args, result)


def command_setup_init(args: argparse.Namespace) -> None:
    _setup_result(
        args, initialize_private_runtime, config_path=_config_path(args),
        replace=args.replace, dry_run=args.dry_run,
    )


def command_setup_import(args: argparse.Namespace) -> None:
    _setup_result(
        args, import_private_runtime, args.input, config_path=_config_path(args),
        replace=args.replace, dry_run=args.dry_run,
    )


def command_setup_owner(args: argparse.Namespace) -> None:
    _setup_result(
        args, set_owner, sleeper_username=args.sleeper_username,
        sleeper_user_id=args.sleeper_user_id, config_path=_config_path(args),
        update=args.update, dry_run=args.dry_run,
    )


def command_setup_add_league(args: argparse.Namespace) -> None:
    _setup_result(
        args, add_league, args.league, season=args.season, name=args.name,
        league_id=args.league_id, user_roster_id=args.user_roster_id,
        draft_id=args.draft_id, user_draft_slot=args.user_draft_slot,
        team_count=args.team_count, config_path=_config_path(args),
        update=args.update, dry_run=args.dry_run,
    )


def command_setup_scaffold(args: argparse.Namespace) -> None:
    _setup_result(
        args, scaffold_private_inputs, args.league, artifact=args.artifact,
        config_path=_config_path(args), season=args.season, replace=args.replace,
        update_config=args.update_config, dry_run=args.dry_run,
    )


def command_setup_list(args: argparse.Namespace) -> None:
    _setup_result(
        args, inspect_private_setup, operation="list", config_path=_config_path(args),
        league_key=args.league,
    )


def command_setup_validate(args: argparse.Namespace) -> None:
    try:
        result = inspect_private_setup(
            operation="validate", config_path=_config_path(args), league_key=args.league
        )
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        print(f"Private setup failed: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    _print_setup_result(args, result)
    if result["status"] != "ready":
        raise SystemExit(2)


def command_setup_show(args: argparse.Namespace) -> None:
    _setup_result(
        args, show_redacted_setup, config_path=_config_path(args),
        league_key=args.league, artifact=args.artifact,
    )


def command_setup_explain(args: argparse.Namespace) -> None:
    _setup_result(args, explain_private_setup, args.artifact)


def command_setup_override(args: argparse.Namespace) -> None:
    _setup_result(
        args, update_override, args.league, operation=args.override_operation,
        kind=args.kind, scope=args.scope, subject=args.subject, action=args.action,
        reason=args.reason, evidence_date=args.evidence_date, source=args.source,
        value=args.value, fantasypros_id=args.fantasypros_id,
        sleeper_id=args.sleeper_id, team=args.team, position=args.position,
        config_path=_config_path(args), season=args.season, update=args.update,
        dry_run=args.dry_run,
    )


def command_fantasypros_rank_consistency(args: argparse.Namespace) -> None:
    result = audit_expert_rank_consistency(
        FantasyProsClient(),
        season=args.season,
        expert_pool_path=args.expert_pool,
        scope=args.scope,
        scoring=args.scoring,
        minimum_interval=args.minimum_interval,
        weighted_rankings_path=args.weighted_rankings,
    )
    result["rank_dispersion_export"] = enrich_ranked_csv_with_dispersion(
        args.weighted_rankings,
        result["individual_rankings"],
        scope=args.scope,
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    print(f"Saved FantasyPros rank-consistency audit to {output}")
    summary = result["summary"]
    print(
        f"{result['expert_count']} experts | {result['request_count']} requests | "
        f"{summary['inversion_count']}/{summary['comparable_pairs']} inversions "
        f"({100 * float(summary['inversion_rate'] or 0.0):.2f}%)"
    )
    if result["issues"]:
        print(f"Filter/response issues: {len(result['issues'])}")
    weighted = result.get("weighted_export") or {}
    if weighted:
        print(
            f"Weighted export: {weighted['inversion_count']}/"
            f"{weighted['comparable_pairs']} composite inversions "
            f"({100 * float(weighted['inversion_rate'] or 0.0):.2f}%)"
        )


def command_fantasypros_league_boards(args: argparse.Namespace) -> None:
    client = SleeperClient()
    snapshots: dict[str, dict[str, Any]] = {}
    configs = load_league_config(_config_path(args))
    requested_leagues = set(args.league or [])
    known_leagues = {str(config["key"]) for config in configs}
    unknown_leagues = sorted(requested_leagues - known_leagues)
    if unknown_leagues:
        raise ValueError("Unknown league key(s): " + ", ".join(unknown_leagues))
    if requested_leagues:
        configs = [
            config for config in configs if str(config["key"]) in requested_leagues
        ]
    configs_by_key = {str(config["key"]): config for config in configs}
    for config in configs:
        league_key = str(config["key"])
        snapshot = build_snapshot(client, config)
        save_snapshot(snapshot, Path(args.snapshot_dir) / f"{league_key}.json")
        snapshots[league_key] = snapshot
        print(f"Refreshed Sleeper snapshot for {league_key}")

    sleeper_players = client.players()
    sleeper_path = Path(args.snapshot_dir) / "sleeper_players.json"
    sleeper_path.write_text(json.dumps(sleeper_players, indent=2, sort_keys=True), encoding="utf-8")
    with interactive_progress("Refreshing Draft board sources"):
        projections, adp, source_metadata = fetch_board_sources(
            FantasyProsClient(), season=args.season
        )
    source_dir = Path(args.source_dir)
    projection_rows = [
        {
            "fantasypros_id": row.get("fpid"),
            "player_name": row.get("name"),
            "team": row.get("team_id"),
            "position": position,
            **(row.get("stats") or {}),
        }
        for position, rows in projections.items()
        for row in rows
    ]
    write_league_csv(projection_rows, source_dir / "projections.csv")
    for scoring, rows in adp.items():
        write_league_csv(rows, source_dir / f"adp_{scoring.lower()}.csv")
    (source_dir / "board_sources.metadata.json").write_text(
        json.dumps(source_metadata, indent=2, sort_keys=True), encoding="utf-8"
    )

    ready = True
    for league_key, snapshot in snapshots.items():
        scoring_assumption = dict(
            configs_by_key[league_key].get("scoring_assumption") or {}
        )
        user_approved = bool(scoring_assumption.pop("user_approved", False))
        result = build_league_board(
            league_key=league_key,
            snapshot=snapshot,
            ranking_path=args.rankings,
            projections=projections,
            adp_rows=adp,
            sleeper_players=sleeper_players,
            source_metadata=source_metadata,
            scoring_settings_override=scoring_assumption or None,
            approved_scoring_override=user_approved,
        )
        paths = write_board(result, args.output_dir, league_key)
        ready = ready and result.metadata["draft_ready"]
        status = "DRAFT-READY" if result.metadata["draft_ready"] else "NOT DRAFT-READY"
        failed = [check for check, passed in result.metadata["checks"].items() if not passed]
        _print_human_report(args, f"Built {league_key}: {len(result.players)} players, {status}", ReportFrame(
            product="Draft league board", league=league_key, horizon="preseason draft",
            readiness="READY" if result.metadata["draft_ready"] else "INCOMPLETE",
            result=f"{len(result.players)} players; {status}",
            warnings=tuple(f"Failed completeness check: {check}" for check in failed),
            limitations=("League scoring and expert ranking horizon are league-local.",),
            saved_paths=tuple(str(path) for path in paths),
        ))
    if not ready:
        print("At least one board is not draft-ready; inspect metadata and issues before proceeding.")


def command_fantasypros_scenario_board(args: argparse.Namespace) -> None:
    """Build a labeled scoring scenario from cached Premium board sources."""
    snapshot = _load_snapshot(args.league, args.snapshot)
    source_dir = Path(args.source_dir)
    raw_projections = _load_board(source_dir / "projections.csv")
    identity_fields = {"fantasypros_id", "player_name", "team", "position"}
    projections: dict[str, list[dict[str, Any]]] = {}
    for row in raw_projections:
        position = str(row.get("position") or "").upper()
        projections.setdefault(position, []).append(
            {
                "fpid": row.get("fantasypros_id"),
                "name": row.get("player_name"),
                "team_id": row.get("team"),
                "stats": {
                    key: value
                    for key, value in row.items()
                    if key not in identity_fields and value not in (None, "")
                },
            }
        )
    adp = {
        "STD": _load_board(source_dir / "adp_std.csv"),
        "HALF": _load_board(source_dir / "adp_half.csv"),
    }
    source_metadata = json.loads(
        (source_dir / "board_sources.metadata.json").read_text(encoding="utf-8")
    )
    sleeper_players = load_sleeper_players_file(Path(args.sleeper_players))
    result = build_league_board(
        league_key=args.league,
        snapshot=snapshot,
        ranking_path=args.rankings,
        projections=projections,
        adp_rows=adp,
        sleeper_players=sleeper_players,
        source_metadata=source_metadata,
        scoring_settings_override={"rec": args.reception_points},
    )
    output_key = args.output_key or (
        f"{args.league}_half_ppr_scenario"
        if args.reception_points == 0.5
        else f"{args.league}_rec_{str(args.reception_points).replace('.', '_')}_scenario"
    )
    result.metadata["scenario_label"] = output_key
    paths = write_board(result, args.output_dir, output_key)
    status = "SIMULATION-READY" if result.metadata["simulation_ready"] else "NOT READY"
    print(
        f"Built hypothetical {args.league} board at {args.reception_points:g} PPR: "
        f"{len(result.players)} players, {status}, draft_ready=false"
    )
    for path in paths:
        print(f"Saved {path}")
    for check, passed in result.metadata["checks"].items():
        if not passed:
            print(f"- failed: {check}")


def _manual_sleeper_players(path: Path, refresh: bool) -> dict[str, dict[str, Any]]:
    if path.exists() and not refresh:
        return load_sleeper_players_file(path)
    players = SleeperClient().players()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(players, indent=2, sort_keys=True), encoding="utf-8")
    print(f"Saved {path} ({len(players)} Sleeper players)")
    return players


def _validate_rankings_scoring(
    league_key: str, reception_points: float, declared_scoring: str
) -> None:
    expected = (
        "ppr" if reception_points >= 0.75 else "half-ppr" if reception_points >= 0.25 else "standard"
    )
    if declared_scoring != expected:
        raise ValueError(
            f"Rankings scoring mismatch: {league_key} currently awards {reception_points:g} "
            f"points per reception, so use {expected} rankings instead of {declared_scoring}. "
            "Refresh the Sleeper snapshot if league settings changed."
        )


def command_manual_board(args: argparse.Namespace) -> None:
    snapshot = _load_snapshot(args.league, args.snapshot)
    league = snapshot["current"]["league"]
    reception_points = float(league.get("scoring_settings", {}).get("rec") or 0.0)
    _validate_rankings_scoring(args.league, reception_points, args.rankings_scoring)
    sleeper_cache = Path(args.sleeper_players)
    historical_accuracy = load_accuracy(args.accuracy)
    result = build_manual_board(
        rankings_path=args.rankings,
        projection_paths=args.projections,
        adp_path=args.adp,
        scoring_settings=league.get("scoring_settings", {}),
        roster_positions=league.get("roster_positions", []),
        team_count=int(league.get("total_rosters") or league.get("settings", {}).get("num_teams") or 0),
        historical_accuracy=historical_accuracy,
        selected_experts=load_expert_pool(args.expert_pool, historical_accuracy),
        sleeper_players=_manual_sleeper_players(sleeper_cache, args.refresh_sleeper_players),
        player_overrides=load_player_overrides(args.player_overrides),
        rankings_mode=args.rankings_mode,
        shrink_to_ecr=args.ecr_shrinkage,
        max_expert_share=args.max_expert_share,
    )
    result.metadata["rankings"]["declared_scoring"] = args.rankings_scoring
    result.metadata["league_reception_points"] = reception_points
    output = Path(args.output or f"data/exports/{args.league}_manual_board.csv")
    _write_csv(result.players, output)
    metadata_output = output.with_suffix(".metadata.json")
    metadata_output.write_text(json.dumps(result.metadata, indent=2, sort_keys=True), encoding="utf-8")
    match_output = output.with_name(f"{output.stem}.matches.csv")
    _write_csv(result.match_report, match_output)
    issues_output = output.with_name(f"{output.stem}.issues.csv")
    _write_csv(result.issues, issues_output)
    status = "DRAFT-READY" if result.metadata["draft_ready"] else "NOT DRAFT-READY"
    failed = [name for name, passed in result.metadata["checks"].items() if not passed]
    _print_human_report(args, "Manual import status: " + status, ReportFrame(
        product="Draft manual board",
        league=args.league,
        horizon="preseason draft",
        readiness="READY" if result.metadata["draft_ready"] else "INCOMPLETE",
        result=f"{len(result.players)} players; {status}",
        warnings=tuple(f"Failed completeness check: {name}" for name in failed),
        limitations=("Expert rankings are authoritative only for their declared draft horizon.",),
        saved_paths=tuple(str(path) for path in (output, metadata_output, match_output, issues_output)),
    ))


def command_simulate(args: argparse.Namespace) -> None:
    config = find_league_config(args.league, _config_path(args))
    snapshot = _load_snapshot(args.league, args.snapshot)
    league = snapshot["current"]["league"]
    drafts = snapshot["current"].get("drafts", [])
    draft = drafts[0]["draft"] if drafts else {}
    teams = int(league.get("total_rosters") or draft.get("settings", {}).get("teams") or 0)
    rounds = int(draft.get("settings", {}).get("rounds") or len(league.get("roster_positions", [])))
    board = _load_board(args.board)
    acquisition_history = (
        historical_position_pick_curves(snapshot)
        if args.history_weight is not None
        else None
    )
    configured_slot = config.get("user_draft_slot")
    selected_slot = args.slot if args.slot is not None else configured_slot
    if not args.all_slots and selected_slot is None:
        raise ValueError(
            f"No draft slot is configured for {args.league}; pass --slot explicitly"
        )
    if selected_slot is not None and not 1 <= int(selected_slot) <= teams:
        raise ValueError(
            f"Draft slot {selected_slot} is outside the {teams}-team league"
        )
    slots = range(1, teams + 1) if args.all_slots else [int(selected_slot)]
    with interactive_progress("Running Draft simulation", machine_output=not bool(args.output)):
        result = {
            str(slot): compare_strategies(
                board,
                teams=teams,
                draft_slot=slot,
                roster_positions=league.get("roster_positions", []),
                rounds=rounds,
                trials=args.trials,
                seed=args.seed,
                strategies=args.strategies or ("scenario_safe", "scenario_calibrated"),
                round_position_rates=simulation_round_tendencies(snapshot),
                include_trace=args.trace,
                include_special_teams=args.include_special_teams,
                replacement_aware_evaluation=args.replacement_aware_evaluation,
                bench_weights=args.bench_weights,
                rank_weights=args.rank_weights,
                acquisition_history=acquisition_history,
                history_weight=args.history_weight,
                opponent_market_noise=args.opponent_market_noise,
                opponent_position_profile=args.opponent_position_profile,
            )
            for slot in slots
        }
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
        _print_human_report(args, "Simulation results saved without changing strategy scores.", ReportFrame(
            product="Draft simulation", league=args.league, horizon="preseason draft",
            readiness="READY", result=f"{len(result)} draft slot(s), {args.trials} trials each",
            limitations=("Simulation is advisory; it does not place a pick.",),
            saved_paths=(str(output),),
        ))
    else:
        _print_json(result)


def command_recommend(args: argparse.Namespace) -> None:
    config = find_league_config(args.league, _config_path(args))
    client = SleeperClient()
    draft = client.draft(str(config["draft_id"]))
    picks = client.draft_picks(str(config["draft_id"]))
    board = _load_board(args.board)
    teams = int(draft.get("settings", {}).get("teams") or 0)
    current_pick = len(picks) + 1
    result = {
        "draft_id": draft.get("draft_id"),
        "draft_status": draft.get("status"),
        "current_pick": current_pick,
        "draft_slot": args.slot,
        "recommendations": recommend_available(
            board,
            picks,
            current_pick=current_pick,
            teams=teams,
            draft_slot=args.slot,
            limit=args.limit,
        ),
    }
    _print_json(result)


def command_audit_mock_evidence(args: argparse.Namespace) -> None:
    audit = audit_mock_evidence(args.log)
    if args.external_grade is not None:
        audit["roster_construction"]["external_grade"] = {
            "source": "FantasyPros Draft Wizard",
            "score": args.external_grade,
            "maximum": 100,
        }
    output = Path(args.output or Path(args.log).with_suffix(".summary.json"))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(audit, indent=2, sort_keys=True), encoding="utf-8")
    print(f"Saved mock evidence audit to {output}")


def command_watch_mock(args: argparse.Namespace) -> None:
    acquisition_mode = getattr(args, "acquisition_mode", "human_league")
    sleeper_adp_snapshot_path = getattr(args, "sleeper_adp_snapshot", None)
    configured_league = getattr(args, "league", None)
    preference_league = args.preference_league or configured_league
    if configured_league and args.preference_league not in (None, configured_league):
        raise ValueError("--league and --preference-league must name the same league")
    preference_path = args.preferences
    if configured_league and preference_path is None:
        league_config = find_league_config(configured_league, _config_path(args))
        policies = league_config.get("policies") or {}
        if isinstance(policies, dict) and policies.get("draft_preferences"):
            preference_path = str(
                resolve_league_policy_path(
                    configured_league,
                    "draft_preferences",
                    config_path=_config_path(args),
                )
            )
    if acquisition_mode == "sleeper_cpu":
        if args.history_league is not None or args.history_weight is not None:
            raise ValueError(
                "--acquisition-mode sleeper_cpu cannot be combined with "
                "--history-league or --history-weight"
            )
        if args.exclude_history_user_id:
            raise ValueError(
                "--acquisition-mode sleeper_cpu cannot use historical manager exclusions"
            )
        if not sleeper_adp_snapshot_path:
            raise ValueError(
                "--acquisition-mode sleeper_cpu requires --sleeper-adp-snapshot"
            )
    if (args.history_league is None) != (args.history_weight is None):
        raise ValueError(
            "--history-league and --history-weight must be provided together"
        )
    if args.history_weight is not None and not 0.0 <= args.history_weight <= 1.0:
        raise ValueError("--history-weight must be between 0 and 1")
    if args.exclude_history_user_id and args.history_league is None:
        raise ValueError(
            "--exclude-history-user-id requires --history-league"
        )
    if bool(preference_path) != bool(preference_league):
        raise ValueError(
            "Draft preferences require --league or --preference-league"
        )
    if args.preference_limit < 0:
        raise ValueError("--preference-limit must be nonnegative")
    history_exclusions = list(args.exclude_history_user_id)
    if args.history_league is not None and not history_exclusions:
        history_exclusions = list(
            find_league_config(
                args.history_league, _config_path(args)
            ).get("history_excluded_user_ids")
            or []
        )
    board = _load_board(args.board)
    sleeper_adp_snapshot = None
    if acquisition_mode == "sleeper_cpu":
        sleeper_adp_snapshot = json.loads(
            Path(sleeper_adp_snapshot_path).read_text(encoding="utf-8")
        )
    acquisition_history = None
    if args.history_league is not None:
        acquisition_history = historical_position_pick_curves(
            _load_snapshot(args.history_league, args.history_snapshot),
            excluded_user_ids=history_exclusions,
        )
        if history_exclusions and not acquisition_history.available:
            raise ValueError(
                "Historical manager exclusions failed: "
                + " ".join(acquisition_history.issues)
            )
    draft_preferences = None
    preference_scoring_settings: dict[str, Any] = {}
    if preference_path:
        draft_preferences = load_draft_preferences(
            preference_path,
            board,
            preference_league,
        )
        preference_snapshot = _load_snapshot(
            preference_league,
            args.preference_snapshot,
        )
        preference_scoring_settings = dict(
            (((preference_snapshot.get("current") or {}).get("league") or {}).get(
                "scoring_settings"
            ))
            or {}
        )
    watcher = MockDraftWatcher(
        client=SleeperClient(),
        draft_reference=args.draft,
        board=board,
        claimed_slot=args.slot,
        user_id=args.user_id,
        recommendation_limit=args.limit,
        poll_interval_seconds=args.poll_seconds,
        scoring_override=args.scoring_override,
        acquisition_history=acquisition_history,
        history_weight=args.history_weight,
        acquisition_mode=acquisition_mode,
        sleeper_adp_snapshot=sleeper_adp_snapshot,
        draft_preferences=draft_preferences,
        preference_scoring_settings=preference_scoring_settings,
        preference_display_limit=args.preference_limit,
    )
    recorder = None
    if args.record_evidence:
        if not args.sleeper_adp_snapshot:
            raise ValueError(
                "--record-evidence requires --sleeper-adp-snapshot"
            )
        draft_id = parse_draft_id(args.draft)
        log_path, summary_path = evidence_paths(args.evidence_dir, draft_id)
        recorder = MockEvidenceRecorder.create(
            log_path,
            summary_path,
            args.sleeper_adp_snapshot,
            {
                "draft_id": draft_id,
                "draft_reference": args.draft,
                "board_path": args.board,
                "claimed_slot": args.slot,
                "user_id": args.user_id,
                "scoring_override": args.scoring_override,
                "history_league": args.history_league,
                "history_weight": args.history_weight,
                "acquisition_mode": acquisition_mode,
                "excluded_history_user_ids": list(
                    history_exclusions
                ),
                "draft_preferences": (
                    draft_preferences.evidence_metadata()
                    if draft_preferences is not None
                    else None
                ),
                "preference_scoring": {
                    "pass_td": preference_scoring_settings.get("pass_td")
                },
            },
        )
        print(f"Recording mock evidence to {log_path}", file=sys.stderr)
        print(f"Post-mock audit will be saved to {summary_path}", file=sys.stderr)
    polls = 0
    termination = "not_started"
    reports: list[dict[str, Any]] = []
    console_color = detect_stdout(sys.stdout).color_enabled
    try:
        while True:
            report = watcher.poll_once()
            if recorder is not None:
                recorder.record(report)
            if report["transition"] != "duplicate" or args.show_duplicates:
                if args.json:
                    reports.append(report)
                else:
                    print(format_mock_report(report, color=console_color))
            polls += 1
            if report["status"] == "complete":
                termination = "draft_complete"
                break
            if args.once:
                termination = "single_poll"
                break
            if args.max_polls and polls >= args.max_polls:
                termination = "maximum_polls"
                break
            time.sleep(args.poll_seconds)
    except KeyboardInterrupt:
        termination = "user_interrupted"
        if not args.json:
            print("Stopped read-only mock watcher")
    finally:
        if recorder is not None:
            audit = recorder.finalize(termination)
            print(
                f"Saved mock evidence audit to {recorder.summary_path}",
                file=sys.stderr,
            )
            reconciliation = audit.get("reconciliation") or {}
            print(
                "Evidence: "
                f"{reconciliation.get('final_pick_count', 0)} picks | "
                f"{reconciliation.get('missed_turn_reports', 0)} missed turns | "
                f"complete={str(reconciliation.get('complete_board', False)).lower()}",
                file=sys.stderr,
            )

    if args.json:
        watcher_output = {
            "polls": polls,
            "reports": reports,
            "status": "interrupted" if termination == "user_interrupted" else "ok",
            "termination": termination,
        }
        if termination == "user_interrupted":
            watcher_output["error_type"] = "KeyboardInterrupt"
            watcher_output["reason"] = "User interrupted watcher"
        _print_json(watcher_output)
    if termination == "user_interrupted":
        raise SystemExit(130)


WELCOME = """ROSTER THEORY // PLAYER ONE READY

Start here:
  roster-theory help                 Guided paths and input requirements
  roster-theory doctor               Offline setup diagnostics
  roster-theory setup init           Create the private runtime safely
  roster-theory --help               Complete command list

Set up a league with a per-user leagues.json, ROSTER_THEORY_CONFIG, or
--config PATH before a command. Configuration alone does not calibrate a league.
"""


GUIDED_HELP = """ROSTER THEORY // SELECT MODE

League setup
  setup init / owner / add-league Create private league configuration
  setup scaffold / validate       Prepare and check league-scoped inputs
  setup override add / remove     Maintain explicit audited overrides
  leagues                         List configured league keys
  snapshot LEAGUE                 Fetch a Sleeper league and draft snapshot
  Example: roster-theory setup init
  Input: setup commands create valid private shapes atomically. Policy
  scaffolds remain uncalibrated until this league has separate evidence. Use
  ROSTER_THEORY_CONFIG or --config PATH to select a non-default destination.

Season preparation
  inputs status LEAGUE            Inspect freshness and readiness offline
  inputs prepare LEAGUE           Refresh only missing or stale provider facts
  Run: roster-theory inputs prepare LEAGUE --assistant trade
  Input: configured league and, for live refreshes, authorized provider access.
  Use --all-leagues for shared season evidence with isolated league policies.

Draft
  analyze LEAGUE                  Review comparable historical drafts
  build-board / simulate / watch-mock  Prepare a board and follow a draft
  Example: roster-theory snapshot LEAGUE
  Input: configured Sleeper league; analysis needs comparable draft history,
  and board/simulation/watch commands need complete expert data and a board.

Trade
  trade refresh / diagnose / evaluate / search  In-season roster and package work
  Example: roster-theory trade refresh LEAGUE
  Input: configured league, current expert and schedule data; decision commands
  require an approved policy for that league.

Waiver
  waiver refresh / evaluate / search  In-season add/drop analysis
  Example: roster-theory waiver refresh LEAGUE
  Input: configured league and current expert data; decisions also need fresh
  availability and legality evidence and an approved policy for that league.

Diagnostics
  doctor [LEAGUE]                  Check local setup offline, without provider calls
  trade-sleeper-probe / fantasypros-probe  Inspect provider data shapes
  Example: roster-theory trade-sleeper-probe LEAGUE --skip-players
  Input: configured Sleeper league and network access for this GET-only probe;
  FantasyPros probes require your own API key.

LEAGUE is your configured league key. Provider refreshes may write local data.
Recommendations never submit a pick, trade, waiver claim, or lineup change.
Configuration alone does not calibrate a league; missing or mismatched decision
policy reports uncalibrated. Run roster-theory --help for the full command list,
or roster-theory COMMAND --help for options (for example,
roster-theory trade evaluate --help or roster-theory waiver search --help).
"""


def command_help(args: argparse.Namespace) -> None:
    print(
        render_banner(
            detect_stdout(sys.stdout),
            suppressed=(
                getattr(args, "no_banner", False)
                or getattr(args, "help_no_banner", False)
            ),
        ),
        end="",
    )
    print(GUIDED_HELP, end="")


def command_doctor(args: argparse.Namespace) -> None:
    capabilities = detect_stdout(sys.stdout)
    print(
        render_banner(capabilities, suppressed=getattr(args, "no_banner", False)),
        end="",
    )
    print(
        render_command_masthead(
            capabilities,
            "Doctor",
            suppressed=getattr(args, "no_banner", False),
        ),
        end="",
    )
    report = audit_setup(
        config_path=_config_path(args),
        league_key=args.league,
        schedule_path=args.schedule,
        expert_pool_path=args.expert_pool,
        draft_board_path=args.draft_board,
        waiver_inputs_path=args.waiver_inputs,
    )
    if args.json:
        _print_json(report)
    else:
        print(format_doctor(report, details=args.details, capabilities=capabilities))


def command_example_config(args: argparse.Namespace) -> None:
    """Print a bundled synthetic config; never inspect a real league."""

    source = resources.files("roster_theory").joinpath("resources/leagues.example.json")
    _print_json(json.loads(source.read_text(encoding="utf-8")))


class MachineArgumentParser(argparse.ArgumentParser):
    def print_help(self, file: Any = None) -> None:
        file = sys.stdout if file is None else file
        command = self.prog.removeprefix("roster-theory").strip() or "Help"
        print(
            render_command_masthead(
                detect_stdout(file),
                f"{command} help" if command.lower() != "help" else "Help",
                suppressed="--no-banner" in sys.argv[1:],
                small=True,
            ),
            end="",
            file=file,
        )
        super().print_help(file)

    def error(self, message: str) -> None:
        if "--json" in sys.argv[1:]:
            _print_json(
                {
                    "command": self.prog,
                    "error_type": "ArgumentError",
                    "reason": message,
                    "status": "invalid_arguments",
                }
            )
            raise SystemExit(2)
        super().error(message)


def build_parser() -> argparse.ArgumentParser:
    parser = MachineArgumentParser(prog="roster-theory")
    parser.add_argument(
        "--no-banner", action="store_true", help="Suppress interactive terminal artwork"
    )
    parser.add_argument(
        "--config",
        help=(
            "League configuration JSON (otherwise ROSTER_THEORY_CONFIG or the "
            "documented per-user config path is used)"
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    guided_help = subparsers.add_parser("help", help="Guided read-only workflow discovery")
    guided_help.add_argument(
        "--no-banner", action="store_true", dest="help_no_banner",
        help="Suppress interactive terminal artwork",
    )
    guided_help.set_defaults(func=command_help)

    inputs = subparsers.add_parser(
        "inputs", help="Inspect, refresh, import, and validate runtime inputs"
    )
    input_groups = inputs.add_subparsers(dest="inputs_group", required=True)

    def add_season_input_options(command: argparse.ArgumentParser) -> None:
        command.add_argument("league", nargs="?", help="Configured league key")
        command.add_argument(
            "--all-leagues", action="store_true",
            help="Prepare every configured league without sharing league-local policy",
        )
        command.add_argument(
            "--assistant", choices=("draft", "trade", "waiver", "all"),
            default="all", help="Target assistant and only its prerequisites",
        )
        command.add_argument("--data-dir", default="data")
        command.add_argument("--json", action="store_true", help="One stable JSON result")

    input_status = input_groups.add_parser(
        "status", help="Inspect unified season readiness without provider calls"
    )
    add_season_input_options(input_status)
    input_status.set_defaults(func=command_inputs_status)

    input_prepare = input_groups.add_parser(
        "prepare", help="Refresh only missing or stale inputs, then report readiness"
    )
    add_season_input_options(input_prepare)
    input_prepare.add_argument(
        "--refresh", choices=("auto", "force"), default="auto",
        help="Reuse valid fresh artifacts or force provider refresh",
    )
    input_prepare.add_argument(
        "--offline", action="store_true",
        help="Forbid network access and report the exact required refresh",
    )
    input_prepare.add_argument("--dry-run", action="store_true")
    input_prepare.set_defaults(func=command_inputs_prepare)

    input_experts = input_groups.add_parser(
        "experts", help="Prepare Draft and in-season expert evidence"
    )
    expert_commands = input_experts.add_subparsers(
        dest="expert_input_command", required=True
    )

    def add_expert_input_paths(command: argparse.ArgumentParser) -> None:
        command.add_argument("league", help="Configured league key")
        command.add_argument("--season", type=int, help="Must match the configured league season")
        command.add_argument(
            "--artifact",
            choices=EXPERT_INPUT_ARTIFACTS,
            default="all",
            help="Expert artifact family to operate on",
        )
        command.add_argument("--data-dir", default="data")
        command.add_argument("--draft-category-output")
        command.add_argument("--draft-annual-output")
        command.add_argument("--inseason-accuracy-output")
        command.add_argument("--pool-output")
        command.add_argument("--audit-output")
        command.add_argument("--evidence-dir")
        command.add_argument("--budget")
        command.add_argument("--json", action="store_true", help="One redacted JSON result")

    expert_inspect = expert_commands.add_parser(
        "inspect", help="Inspect expert input readiness without provider calls"
    )
    add_expert_input_paths(expert_inspect)
    expert_inspect.set_defaults(func=command_inputs_experts_inspect)

    expert_validate = expert_commands.add_parser(
        "validate", help="Validate expert inputs and fail when any are incomplete"
    )
    add_expert_input_paths(expert_validate)
    expert_validate.set_defaults(func=command_inputs_experts_validate)

    def add_expert_refresh_options(command: argparse.ArgumentParser) -> None:
        add_expert_input_paths(command)
        command.add_argument(
            "--replay-dir",
            help="Build from saved provider-evidence JSON without provider calls",
        )
        command.add_argument("--dry-run", action="store_true")
        command.add_argument("--minimum-interval", type=float, default=1.0)
        command.add_argument("--pool-size", type=int, default=5)
        command.add_argument("--maximum-source-count", type=int, default=2)
        command.add_argument("--freshness-hours", type=float, default=48.0)

    expert_refresh = expert_commands.add_parser(
        "refresh",
        help="Refresh Draft accuracy and/or the auditable in-season expert pool",
    )
    add_expert_refresh_options(expert_refresh)
    expert_refresh.set_defaults(func=command_inputs_experts_refresh)

    expert_import = expert_commands.add_parser(
        "import",
        help="Build expert artifacts from saved authorized provider evidence",
    )
    add_expert_input_paths(expert_import)
    expert_import.add_argument(
        "--input", required=True, help="Directory containing provider-evidence JSON"
    )
    expert_import.add_argument("--dry-run", action="store_true")
    expert_import.add_argument("--pool-size", type=int, default=5)
    expert_import.add_argument("--maximum-source-count", type=int, default=2)
    expert_import.add_argument("--freshness-hours", type=float, default=48.0)
    expert_import.set_defaults(func=command_inputs_experts_import)

    input_schedule = input_groups.add_parser(
        "schedule", help="Prepare season-aware NFL schedule and bye evidence"
    )
    schedule_commands = input_schedule.add_subparsers(
        dest="schedule_input_command", required=True
    )

    def add_schedule_paths(command: argparse.ArgumentParser) -> None:
        command.add_argument("league", help="Configured league key")
        command.add_argument("--season", type=int, help="Must match the configured league season")
        command.add_argument("--output", help="Normalized schedule JSON path")
        command.add_argument("--json", action="store_true", help="One stable JSON result")

    schedule_inspect = schedule_commands.add_parser(
        "inspect", help="Inspect schedule readiness without provider calls"
    )
    add_schedule_paths(schedule_inspect)
    schedule_inspect.set_defaults(func=command_inputs_schedule_inspect)

    schedule_validate = schedule_commands.add_parser(
        "validate", help="Validate the complete normalized schedule and provenance"
    )
    add_schedule_paths(schedule_validate)
    schedule_validate.set_defaults(func=command_inputs_schedule_validate)

    schedule_refresh = schedule_commands.add_parser(
        "refresh", help="Fetch the nflverse release or replay saved source evidence"
    )
    add_schedule_paths(schedule_refresh)
    schedule_refresh.add_argument("--evidence-output", help="Replayable source evidence JSON")
    schedule_refresh.add_argument("--replay", help="Saved source evidence JSON; makes no network call")
    schedule_refresh.add_argument("--dry-run", action="store_true")
    schedule_refresh.set_defaults(func=command_inputs_schedule_refresh)

    schedule_import = schedule_commands.add_parser(
        "import", help="Import an authorized provider-shaped UTF-8 CSV"
    )
    add_schedule_paths(schedule_import)
    schedule_import.add_argument("--input", required=True, help="Authorized schedule CSV")
    schedule_import.add_argument("--source", required=True, help="Human-readable source name")
    schedule_import.add_argument("--source-url", required=True)
    schedule_import.add_argument("--license", required=True)
    schedule_import.add_argument("--captured-at", required=True, help="ISO-8601 retrieval time")
    schedule_import.add_argument("--use-restriction")
    schedule_import.add_argument("--evidence-output", help="Replayable source evidence JSON")
    schedule_import.add_argument("--dry-run", action="store_true")
    schedule_import.set_defaults(func=command_inputs_schedule_import)

    setup = subparsers.add_parser(
        "setup", help="Create and maintain ignored private runtime inputs"
    )
    setup_commands = setup.add_subparsers(dest="setup_command", required=True)

    def add_setup_output(command: argparse.ArgumentParser) -> None:
        command.add_argument("--dry-run", action="store_true")
        command.add_argument("--json", action="store_true", help="One redacted JSON result")

    setup_init = setup_commands.add_parser(
        "init", help="Initialize the private runtime directory and leagues.json"
    )
    setup_init.add_argument("--replace", action="store_true")
    add_setup_output(setup_init)
    setup_init.set_defaults(func=command_setup_init)

    setup_import = setup_commands.add_parser(
        "import", help="Import an existing private leagues.json"
    )
    setup_import.add_argument("--input", required=True)
    setup_import.add_argument("--replace", action="store_true")
    add_setup_output(setup_import)
    setup_import.set_defaults(func=command_setup_import)

    setup_owner = setup_commands.add_parser(
        "owner", help="Set explicit private Sleeper owner identity"
    )
    setup_owner.add_argument("--sleeper-username", required=True)
    setup_owner.add_argument("--sleeper-user-id", required=True)
    setup_owner.add_argument("--update", action="store_true", required=True)
    add_setup_output(setup_owner)
    setup_owner.set_defaults(func=command_setup_owner)

    setup_league = setup_commands.add_parser(
        "add-league", help="Add or explicitly replace one configured league"
    )
    setup_league.add_argument("league", help="Safe configured league key")
    setup_league.add_argument("--season", type=int, required=True)
    setup_league.add_argument("--name", required=True)
    setup_league.add_argument("--league-id", required=True)
    setup_league.add_argument("--user-roster-id", type=int, required=True)
    setup_league.add_argument("--draft-id")
    setup_league.add_argument("--user-draft-slot", type=int)
    setup_league.add_argument("--team-count", type=int)
    setup_league.add_argument("--update", action="store_true", required=True)
    add_setup_output(setup_league)
    setup_league.set_defaults(func=command_setup_add_league)

    setup_scaffold = setup_commands.add_parser(
        "scaffold", help="Create season-aware private policy and override files"
    )
    setup_scaffold.add_argument("league", help="Configured league key")
    setup_scaffold.add_argument("--season", type=int)
    setup_scaffold.add_argument(
        "--artifact", choices=("all", *SETUP_ARTIFACTS), default="all"
    )
    setup_scaffold.add_argument("--update-config", action="store_true")
    setup_scaffold.add_argument("--replace", action="store_true")
    add_setup_output(setup_scaffold)
    setup_scaffold.set_defaults(func=command_setup_scaffold)

    setup_list = setup_commands.add_parser(
        "list", help="List private artifacts and readiness without provider calls"
    )
    setup_list.add_argument("league", nargs="?")
    setup_list.add_argument("--json", action="store_true")
    setup_list.set_defaults(func=command_setup_list)

    setup_validate = setup_commands.add_parser(
        "validate", help="Validate private schemas, league scope, and calibration state"
    )
    setup_validate.add_argument("league", nargs="?")
    setup_validate.add_argument("--json", action="store_true")
    setup_validate.set_defaults(func=command_setup_validate)

    setup_show = setup_commands.add_parser(
        "show-redacted", help="Show config or one artifact with private IDs redacted"
    )
    setup_show.add_argument("league", nargs="?")
    setup_show.add_argument(
        "--artifact", choices=("config", *SETUP_ARTIFACTS), default="config"
    )
    setup_show.add_argument("--json", action="store_true")
    setup_show.set_defaults(func=command_setup_show)

    setup_explain = setup_commands.add_parser(
        "explain", help="Explain authority and calibration requirements"
    )
    setup_explain.add_argument(
        "artifact", nargs="?", choices=("all", "config", *SETUP_ARTIFACTS), default="all"
    )
    setup_explain.add_argument("--json", action="store_true")
    setup_explain.set_defaults(func=command_setup_explain)

    setup_override = setup_commands.add_parser(
        "override", help="Explicitly add or remove an audited expert or identity override"
    )
    override_commands = setup_override.add_subparsers(
        dest="override_operation", required=True
    )

    def add_override_options(command: argparse.ArgumentParser) -> None:
        command.add_argument("league", help="Configured league key")
        command.add_argument("--kind", choices=("expert", "identity"), required=True)
        command.add_argument("--season", type=int)
        command.add_argument("--scope", required=True)
        command.add_argument("--subject", required=True, help="Expert or player name")
        command.add_argument("--action", required=True)
        command.add_argument("--reason", required=True)
        command.add_argument("--evidence-date", required=True)
        command.add_argument("--source", required=True)
        command.add_argument("--value", default="")
        command.add_argument("--fantasypros-id", default="")
        command.add_argument("--sleeper-id", default="")
        command.add_argument("--team", default="")
        command.add_argument("--position", default="")
        command.add_argument("--update", action="store_true")
        add_setup_output(command)

    override_add = override_commands.add_parser("add", help="Add one explicit override")
    add_override_options(override_add)
    override_add.set_defaults(func=command_setup_override)
    override_remove = override_commands.add_parser(
        "remove", help="Remove one exact override and retain an audit event"
    )
    add_override_options(override_remove)
    override_remove.set_defaults(func=command_setup_override)

    doctor = subparsers.add_parser(
        "doctor", help="Diagnose local league setup offline; no provider requests"
    )
    doctor.add_argument("league", nargs="?", help="Optional configured league key")
    doctor.add_argument("--schedule")
    doctor.add_argument(
        "--expert-pool",
    )
    doctor.add_argument("--draft-board", help="Optional local Draft board to check")
    doctor.add_argument("--waiver-inputs", help="Optional fresh Waiver input bundle to check")
    doctor.add_argument(
        "--details", action="store_true", help="Show ready checks as well as findings"
    )
    doctor.add_argument("--json", action="store_true", help="One redacted JSON result")
    doctor.set_defaults(func=command_doctor)

    example_config = subparsers.add_parser(
        "example-config", help="Print a synthetic offline league configuration as JSON"
    )
    example_config.set_defaults(func=command_example_config)

    leagues = subparsers.add_parser("leagues", help="List configured leagues")
    leagues.set_defaults(func=command_leagues)

    snapshot = subparsers.add_parser("snapshot", help="Download a Sleeper league snapshot")
    snapshot.add_argument("league", help="Configured league key")
    snapshot.add_argument("--output")
    snapshot.set_defaults(func=command_snapshot)

    analyze = subparsers.add_parser("analyze", help="Analyze historical Sleeper draft tendencies")
    analyze.add_argument("league", help="Configured league key")
    analyze.add_argument("--snapshot")
    analyze.add_argument("--output")
    analyze.set_defaults(func=command_analyze)

    sleeper_adp = subparsers.add_parser(
        "sleeper-adp-audit",
        help="Capture current Sleeper ADP and produce a non-promoted audit",
    )
    sleeper_adp.add_argument("league", help="Configured league key")
    sleeper_adp.add_argument("--board", required=True)
    sleeper_adp.add_argument("--season", type=int, default=2026)
    sleeper_adp.add_argument(
        "--scoring",
        choices=("standard", "half_ppr", "ppr"),
        default="half_ppr",
    )
    sleeper_adp.add_argument("--snapshot")
    sleeper_adp.add_argument("--cache-dir", default="data/cache/sleeper_adp")
    sleeper_adp.add_argument("--output")
    sleeper_adp.set_defaults(func=command_sleeper_adp_audit)

    board = subparsers.add_parser("build-board", help="Build a weighted expert board from long-form CSV")
    board.add_argument("league", help="Configured league key")
    board.add_argument("--input", required=True, help="Long-form expert rankings CSV")
    board.add_argument("--output")
    board.add_argument("--snapshot")
    board.add_argument("--accuracy", default="data/manual/fantasypros/expert_accuracy_2021_2025.csv")
    board.add_argument("--ecr-shrinkage", type=float, default=0.25)
    board.add_argument("--max-expert-share", type=float, default=0.20)
    board.set_defaults(func=command_build_board)

    probe = subparsers.add_parser("fantasypros-probe", help="Inspect a FantasyPros response shape using your API key")
    probe.add_argument("endpoint", choices=["experts", "rankings", "consensus", "projections", "players"])
    probe.add_argument("--season", type=int, default=2026)
    probe.add_argument("--position", default="RB")
    probe.add_argument("--scoring", default="STD")
    probe.set_defaults(func=command_fantasypros_probe)

    trade_sleeper_probe = subparsers.add_parser(
        "trade-sleeper-probe",
        help="Record GET-only Sleeper field shapes for Trade Assistant feasibility",
    )
    trade_sleeper_probe.add_argument("league", help="Configured league key")
    trade_sleeper_probe.add_argument(
        "--weeks", type=int, nargs="+", default=[1, 15, 16, 17]
    )
    trade_sleeper_probe.add_argument("--skip-players", action="store_true")
    trade_sleeper_probe.add_argument("--include-trends", action="store_true")
    trade_sleeper_probe.add_argument("--output")
    trade_sleeper_probe.set_defaults(func=command_trade_sleeper_probe)

    trade_fantasypros_probe = subparsers.add_parser(
        "trade-fantasypros-probe",
        help="Run a budgeted FantasyPros Trade Assistant capability probe",
    )
    trade_fantasypros_probe.add_argument("--season", type=int, default=2026)
    trade_fantasypros_probe.add_argument("--week", type=int, default=1)
    trade_fantasypros_probe.add_argument(
        "--historical-season", type=int, default=2025
    )
    trade_fantasypros_probe.add_argument("--output")
    trade_fantasypros_probe.set_defaults(func=command_trade_fantasypros_probe)

    trade = subparsers.add_parser(
        "trade", help="Read-only Trade Assistant data and analysis commands"
    )
    trade_commands = trade.add_subparsers(dest="trade_command", required=True)
    trade_refresh = trade_commands.add_parser(
        "refresh", help="Build a complete immutable data snapshot; no recommendation"
    )
    trade_refresh.add_argument("league", help="Configured league key")
    trade_refresh.add_argument(
        "--ranking-horizon",
        choices=("WEEKLY-PROXY", "ROS"),
        default="WEEKLY-PROXY",
    )
    trade_refresh.add_argument(
        "--schedule", help="Override the season-aware generated schedule path"
    )
    trade_refresh.add_argument(
        "--player-cache", default="data/cache/trade/sleeper/players_nfl.json"
    )
    trade_refresh.add_argument("--output")
    trade_refresh.set_defaults(func=command_trade_refresh)

    waiver = subparsers.add_parser(
        "waiver", help="Read-only Waiver Assistant data and analysis commands"
    )
    waiver_commands = waiver.add_subparsers(dest="waiver_command", required=True)
    waiver_refresh = waiver_commands.add_parser(
        "refresh", help="Build an immutable Waiver data snapshot; no recommendation"
    )
    waiver_refresh.add_argument("league", help="Configured Waiver league key")
    waiver_refresh.add_argument(
        "--player-cache", default="data/cache/waiver/sleeper/players_nfl.json"
    )
    waiver_refresh.add_argument("--output")
    waiver_refresh.set_defaults(func=command_waiver_refresh)

    waiver_inputs = waiver_commands.add_parser(
        "inputs",
        help="Build fresh league-scored Waiver evidence from installed commands",
    )
    waiver_inputs.add_argument("league", help="Configured Waiver league key")
    waiver_inputs.add_argument("--output")
    waiver_inputs.add_argument("--policy")
    waiver_inputs.add_argument("--waiver-wire-policy")
    waiver_inputs.add_argument("--contingency-file")
    waiver_inputs.set_defaults(func=command_waiver_inputs)

    waiver_evaluate = waiver_commands.add_parser(
        "evaluate",
        help="Evaluate one read-only entered add/drop with the Waiver policy",
    )
    waiver_evaluate.add_argument("league")
    waiver_evaluate.add_argument("--add", help="Exact QB/RB/WR/TE player name")
    waiver_evaluate.add_argument("--drop", help="Optional exact player name to drop")
    waiver_evaluate.add_argument(
        "--inputs",
        help="Fresh Waiver-scoped projection, value, availability, and legality evidence",
    )
    waiver_evaluate.add_argument(
        "--player-cache", default="data/cache/waiver/sleeper/players_nfl.json"
    )
    waiver_evaluate.add_argument(
        "--policy", help="Override the league's approved Waiver policy"
    )
    waiver_evaluate.add_argument("--snapshot", help="Replay saved evaluation evidence")
    waiver_evaluate.add_argument("--save-evidence")
    waiver_evaluate.add_argument("--json", action="store_true")
    waiver_evaluate.set_defaults(func=command_waiver_evaluate)

    waiver_search = waiver_commands.add_parser(
        "search",
        help="Search every proved-eligible QB/RB/WR/TE from one immutable input bundle",
    )
    waiver_search.add_argument("league")
    waiver_search.add_argument(
        "--inputs",
        help="Fresh complete Waiver projection, value, availability, and legality evidence",
    )
    waiver_search.add_argument(
        "--player-cache", default="data/cache/waiver/sleeper/players_nfl.json"
    )
    waiver_search.add_argument(
        "--policy", help="Override the league's approved Waiver policy"
    )
    waiver_search.add_argument("--snapshot", help="Replay saved search evidence")
    waiver_search.add_argument("--save-evidence")
    waiver_search.add_argument("--json", action="store_true")
    waiver_search.set_defaults(func=command_waiver_search)

    trade_values = trade_commands.add_parser(
        "values",
        help="Build independent selected-expert and market value boards",
    )
    trade_values.add_argument("league", help="Configured league key")
    trade_values.add_argument(
        "--expert-pool",
    )
    trade_values.add_argument(
        "--fantasypros-cache",
        default="data/cache/trade/fantasypros/2026",
    )
    trade_values.add_argument(
        "--budget",
        default="data/cache/trade/fantasypros/daily_budget.json",
    )
    trade_values.add_argument("--output")
    trade_values.set_defaults(func=command_trade_values)

    trade_evaluate = trade_commands.add_parser(
        "evaluate",
        help="Evaluate a read-only entered player package for both rosters",
    )
    trade_evaluate.add_argument("league", help="Configured league key")
    trade_evaluate.add_argument(
        "--send", action="append", default=[], help="Player sent; repeat up to four times"
    )
    trade_evaluate.add_argument(
        "--receive", action="append", default=[], help="Player received; repeat up to four times"
    )
    trade_evaluate.add_argument(
        "--drop", action="append", default=[], help="Explicit required drop; repeat as needed"
    )
    trade_evaluate.add_argument(
        "--add", action="append", default=[], help="Explicit waiver add; repeat as needed"
    )
    trade_evaluate.add_argument("--playoff-weight", type=float, default=1.0)
    trade_evaluate.add_argument(
        "--risk-posture",
        choices=("conservative", "balanced", "ceiling"),
        default="balanced",
    )
    trade_evaluate.add_argument("--allow-partial", action="store_true")
    trade_evaluate.add_argument("--allow-rank-only", action="store_true")
    trade_evaluate.add_argument("--snapshot")
    trade_evaluate.add_argument("--json", action="store_true")
    trade_evaluate.add_argument("--save-evidence")
    trade_evaluate.add_argument(
        "--policy", help="Override the league's approved Trade decision policy"
    )
    trade_evaluate.add_argument(
        "--expert-pool",
    )
    trade_evaluate.add_argument(
        "--fantasypros-cache",
        default="data/cache/trade/fantasypros/2026",
    )
    trade_evaluate.add_argument(
        "--budget",
        default="data/cache/trade/fantasypros/daily_budget.json",
    )
    trade_evaluate.set_defaults(func=command_trade_evaluate)

    trade_diagnose = trade_commands.add_parser(
        "diagnose",
        help="Diagnose the current roster's weekly needs, depth, byes, and offense risk",
    )
    trade_diagnose.add_argument("league", help="Configured league key")
    trade_diagnose.add_argument(
        "--risk-posture",
        choices=("conservative", "balanced", "ceiling"),
        default="balanced",
    )
    trade_diagnose.add_argument("--json", action="store_true")
    trade_diagnose.add_argument("--output")
    trade_diagnose.add_argument(
        "--policy", help="Override the league's approved Trade decision policy"
    )
    trade_diagnose.add_argument(
        "--expert-pool",
    )
    trade_diagnose.add_argument(
        "--fantasypros-cache",
        default="data/cache/trade/fantasypros/2026",
    )
    trade_diagnose.add_argument(
        "--budget",
        default="data/cache/trade/fantasypros/daily_budget.json",
    )
    trade_diagnose.set_defaults(func=command_trade_diagnose)

    trade_gaps = trade_commands.add_parser(
        "gaps",
        help="Show horizon-matched selected-versus-market gaps with ownership",
    )
    trade_gaps.add_argument("league", help="Configured league key")
    trade_gaps.add_argument("--json", action="store_true")
    trade_gaps.add_argument("--output")
    trade_gaps.add_argument("--csv")
    trade_gaps.add_argument("--expert-pool")
    trade_gaps.add_argument(
        "--fantasypros-cache", default="data/cache/trade/fantasypros/2026"
    )
    trade_gaps.add_argument(
        "--budget", default="data/cache/trade/fantasypros/daily_budget.json"
    )
    trade_gaps.set_defaults(func=command_trade_gaps)

    trade_search = trade_commands.add_parser(
        "search",
        help="Find bounded, bilateral league-wide trade opportunities",
    )
    trade_search.add_argument("league", help="Configured league key")
    trade_search.add_argument(
        "--risk-posture",
        choices=("conservative", "balanced", "ceiling"),
        default="balanced",
    )
    trade_search.add_argument("--small-pool", type=int, default=6)
    trade_search.add_argument("--large-pool", type=int, default=4)
    trade_search.add_argument("--max-exact", type=int, default=2)
    trade_search.add_argument("--max-large-exact", type=int, default=1)
    trade_search.add_argument("--max-results", type=int, default=20)
    trade_search.add_argument("--json", action="store_true")
    trade_search.add_argument(
        "--snapshot", help="Replay and verify saved search evidence without live refresh"
    )
    trade_search.add_argument("--output")
    trade_search.add_argument("--csv")
    trade_search.add_argument(
        "--policy", help="Override the league's approved Trade decision policy"
    )
    trade_search.add_argument(
        "--search-policy",
        help="Override the league's approved Trade search policy",
    )
    trade_search.add_argument("--expert-pool")
    trade_search.add_argument(
        "--fantasypros-cache", default="data/cache/trade/fantasypros/2026"
    )
    trade_search.add_argument(
        "--budget", default="data/cache/trade/fantasypros/daily_budget.json"
    )
    trade_search.set_defaults(func=command_trade_search)

    trade_compare = trade_commands.add_parser(
        "compare",
        help="Exactly evaluate and rank packages from a JSON file",
    )
    trade_compare.add_argument("league", help="Configured league key")
    trade_compare.add_argument(
        "--packages",
        required=True,
        help="JSON list of objects with repeatable send and receive player-name lists",
    )
    trade_compare.add_argument(
        "--risk-posture",
        choices=("conservative", "balanced", "ceiling"),
        default="balanced",
    )
    trade_compare.add_argument("--json", action="store_true")
    trade_compare.add_argument("--output")
    trade_compare.add_argument(
        "--policy", help="Override the league's approved Trade decision policy"
    )
    trade_compare.add_argument("--expert-pool")
    trade_compare.add_argument(
        "--fantasypros-cache", default="data/cache/trade/fantasypros/2026"
    )
    trade_compare.add_argument(
        "--budget", default="data/cache/trade/fantasypros/daily_budget.json"
    )
    trade_compare.set_defaults(func=command_trade_compare)

    fp_board = subparsers.add_parser(
        "fantasypros-board", help="Build a league-scored weighted board directly from FantasyPros"
    )
    fp_board.add_argument("league", help="Configured league key")
    fp_board.add_argument("--output")
    fp_board.add_argument("--snapshot")
    fp_board.add_argument("--accuracy", default="data/manual/fantasypros/expert_accuracy_2021_2025.csv")
    fp_board.add_argument("--experts", type=int, default=10)
    fp_board.add_argument("--ecr-shrinkage", type=float, default=0.25)
    fp_board.add_argument("--max-expert-share", type=float, default=0.20)
    fp_board.set_defaults(func=command_fantasypros_board)

    grouped = subparsers.add_parser(
        "fantasypros-grouped-rankings",
        help="Export Premium API rankings using historically weighted five-expert cohorts",
    )
    grouped.add_argument("--season", type=int, default=2026)
    grouped.add_argument("--accuracy", default="data/manual/fantasypros/expert_accuracy_2021_2025.csv")
    grouped.add_argument(
        "--annual-accuracy",
        default="data/manual/fantasypros/expert_accuracy_annual_2021_2025.csv",
    )
    grouped.add_argument("--output-dir", default="data/exports/fantasypros_2026")
    grouped.add_argument("--experts", type=int, default=10)
    grouped.add_argument("--specialist-experts", type=int, default=20)
    grouped.add_argument("--cohort-size", type=int, default=5)
    grouped.add_argument("--ecr-shrinkage", type=float, default=0.15)
    grouped.add_argument("--specialist-ecr-shrinkage", type=float, default=0.25)
    grouped.add_argument(
        "--expert-overrides",
        default="data/manual/fantasypros/expert_pool_overrides_2026.csv",
    )
    grouped.add_argument("--max-skill-ranking-age-days", type=int, default=14)
    grouped.set_defaults(func=command_fantasypros_grouped_rankings)

    accuracy_history = subparsers.add_parser(
        "fantasypros-accuracy-history",
        help="Refresh a local annual draft-accuracy source using your API access",
    )
    accuracy_history.add_argument(
        "--output",
        default="data/manual/fantasypros/expert_accuracy_annual_2021_2025.csv",
    )
    accuracy_history.add_argument("--minimum-interval", type=float, default=1.0)
    accuracy_history.set_defaults(func=command_fantasypros_accuracy_history)

    rank_consistency = subparsers.add_parser(
        "fantasypros-rank-consistency",
        help="Audit individual-expert ALL versus positional ordering",
    )
    rank_consistency.add_argument("--season", type=int, default=2026)
    rank_consistency.add_argument(
        "--expert-pool",
        default="data/exports/fantasypros_2026/expert_pools.csv",
    )
    rank_consistency.add_argument("--scope", default="skills_half_ppr")
    rank_consistency.add_argument("--scoring", default="HALF")
    rank_consistency.add_argument("--minimum-interval", type=float, default=1.0)
    rank_consistency.add_argument(
        "--weighted-rankings",
        default="data/exports/fantasypros_2026/weighted_rankings.csv",
    )
    rank_consistency.add_argument(
        "--output",
        default="data/exports/fantasypros_2026/rank_consistency_half_ppr.json",
    )
    rank_consistency.set_defaults(func=command_fantasypros_rank_consistency)

    league_boards = subparsers.add_parser(
        "fantasypros-league-boards",
        help="Refresh Sleeper and build audited boards from grouped Premium rankings",
    )
    league_boards.add_argument("--season", type=int, default=2026)
    league_boards.add_argument(
        "--rankings", default="data/exports/fantasypros_2026/weighted_rankings.csv"
    )
    league_boards.add_argument("--snapshot-dir", default="data/cache")
    league_boards.add_argument("--source-dir", default="data/exports/fantasypros_2026")
    league_boards.add_argument("--output-dir", default="data/exports/league_boards_2026")
    league_boards.add_argument(
        "--league",
        action="append",
        help="Limit refresh/build to one configured league; repeat for more than one",
    )
    league_boards.set_defaults(func=command_fantasypros_league_boards)

    scenario_board = subparsers.add_parser(
        "fantasypros-scenario-board",
        help="Build a labeled hypothetical board from cached Premium sources",
    )
    scenario_board.add_argument("league", help="Configured league whose roster/settings are the base")
    scenario_board.add_argument("--reception-points", type=float, required=True)
    scenario_board.add_argument("--snapshot")
    scenario_board.add_argument(
        "--rankings", default="data/exports/fantasypros_2026/weighted_rankings.csv"
    )
    scenario_board.add_argument("--source-dir", default="data/exports/fantasypros_2026")
    scenario_board.add_argument("--sleeper-players", default="data/cache/sleeper_players.json")
    scenario_board.add_argument("--output-dir", default="data/exports/league_boards_2026")
    scenario_board.add_argument("--output-key")
    scenario_board.set_defaults(func=command_fantasypros_scenario_board)

    manual_board = subparsers.add_parser(
        "manual-board", help="Build and audit a board from FantasyPros Pro CSV exports"
    )
    manual_board.add_argument("league", help="Configured league key")
    manual_board.add_argument(
        "--rankings",
        required=True,
        help="FantasyPros selected-consensus or expert-matrix CSV/TSV",
    )
    manual_board.add_argument(
        "--projections",
        required=True,
        nargs="+",
        help="QB, RB, WR, and TE full-season projection CSV/TSV files",
    )
    manual_board.add_argument("--adp", required=True, help="FantasyPros overall ADP CSV/TSV")
    manual_board.add_argument("--output")
    manual_board.add_argument("--snapshot")
    manual_board.add_argument("--accuracy", default="data/manual/fantasypros/expert_accuracy_2021_2025.csv")
    manual_board.add_argument(
        "--expert-pool",
        default="data/manual/fantasypros/expert_pool_2026.csv",
        help="Current export pool; separate from the historical master accuracy list",
    )
    manual_board.add_argument(
        "--rankings-mode",
        choices=("auto", "selected-ecr", "matrix"),
        default="auto",
        help="Auto-detect the available Pro consensus export or an individual-expert matrix",
    )
    manual_board.add_argument(
        "--rankings-scoring",
        choices=("standard", "half-ppr", "ppr"),
        required=True,
        help="Scoring used for the rankings export; must match the current Sleeper snapshot",
    )
    manual_board.add_argument("--player-overrides", help="Optional resolved player-name-to-Sleeper-ID CSV")
    manual_board.add_argument("--sleeper-players", default="data/cache/sleeper_players.json")
    manual_board.add_argument("--refresh-sleeper-players", action="store_true")
    manual_board.add_argument("--ecr-shrinkage", type=float, default=0.25)
    manual_board.add_argument("--max-expert-share", type=float, default=0.20)
    manual_board.set_defaults(func=command_manual_board)

    simulate = subparsers.add_parser("simulate", help="Compare draft strategies from one or all slots")
    simulate.add_argument("league", help="Configured league key")
    simulate.add_argument("--board", required=True)
    simulate.add_argument(
        "--slot",
        type=int,
        help="Draft slot override (default: the league's configured user_draft_slot)",
    )
    simulate.add_argument("--all-slots", action="store_true")
    simulate.add_argument("--trials", type=int, default=1000)
    simulate.add_argument("--seed", type=int, default=2026)
    simulate.add_argument(
        "--strategies",
        nargs="+",
        help="Policies to compare (for example: vorp constructed_vorp hybrid_10 hybrid_20)",
    )
    simulate.add_argument("--trace", action="store_true", help="Include one complete audited draft per policy")
    simulate.add_argument(
        "--include-special-teams",
        action="store_true",
        help="Audit full-round K/DST timing; exclude it from winning-formula calibration by default",
    )
    simulate.add_argument(
        "--replacement-aware-evaluation",
        action="store_true",
        help="Score every policy against waiver-replacement lineup floors in availability scenarios",
    )
    simulate.add_argument(
        "--bench-weights",
        nargs="+",
        type=float,
        default=(0.10, 0.20, 0.30),
        help="Deterministic draft-score bench weights (default: 0.10 0.20 0.30)",
    )
    simulate.add_argument(
        "--rank-weights",
        nargs="+",
        type=float,
        default=(0.0, 0.5, 1.0),
        help="Selected-rank projection adjustment weights (default: 0 0.5 1)",
    )
    simulate.add_argument(
        "--history-weight",
        type=float,
        help=(
            "Enable positional-slot acquisition ADP at this historical weight "
            "(0 to 1); this disables the legacy round-position tendency nudge"
        ),
    )
    simulate.add_argument(
        "--opponent-market-noise",
        type=float,
        default=2.5,
        help=(
            "Standard deviation of simulated opponent market-choice noise "
            "(default: 2.5; simulation stress only)"
        ),
    )
    simulate.add_argument(
        "--opponent-position-profile",
        choices=OPPONENT_POSITION_STRESS_PROFILES,
        default="raw",
        help=(
            "Synthetic opponent position-demand stress profile; changes only "
            "simulation acquisition timing"
        ),
    )
    simulate.add_argument("--snapshot")
    simulate.add_argument("--output")
    simulate.set_defaults(func=command_simulate)

    recommend = subparsers.add_parser("recommend", help="Poll a Sleeper draft and rank available choices")
    recommend.add_argument("league", help="Configured league key")
    recommend.add_argument("--board", required=True)
    recommend.add_argument("--slot", type=int, required=True)
    recommend.add_argument("--limit", type=int, default=10)
    recommend.set_defaults(func=command_recommend)

    watch_mock = subparsers.add_parser(
        "watch-mock",
        help="Continuously reconcile and recommend for an arbitrary Sleeper mock draft",
    )
    watch_mock.add_argument("draft", help="Sleeper draft_id or draftboard URL")
    watch_mock.add_argument("--board", required=True)
    watch_mock.add_argument(
        "--league",
        help="Configured league used for league-scoped Draft preferences",
    )
    watch_mock.add_argument("--slot", type=int)
    watch_mock.add_argument("--user-id")
    watch_mock.add_argument("--limit", type=int, default=5)
    watch_mock.add_argument("--poll-seconds", type=float, default=0.5)
    watch_mock.add_argument(
        "--scoring-override",
        choices=("standard", "half_ppr"),
        help="Use an explicitly approved scoring assumption when the mock room is stale",
    )
    watch_mock.add_argument(
        "--history-league",
        help="Configured league whose positional draft history sets acquisition cost",
    )
    watch_mock.add_argument(
        "--acquisition-mode",
        choices=ACQUISITION_MODES,
        default="human_league",
        help=(
            "Acquisition timing source: human_league (default) or the "
            "explicit mock-only sleeper_cpu mode"
        ),
    )
    watch_mock.add_argument(
        "--history-weight",
        type=float,
        help="Approved league-history weight from 0 to 1",
    )
    watch_mock.add_argument(
        "--history-snapshot",
        help="Optional snapshot path for --history-league (default: data/cache/LEAGUE.json)",
    )
    watch_mock.add_argument(
        "--exclude-history-user-id",
        action="append",
        default=[],
        help=(
            "Sleeper user ID to remove from every complete historical draft; "
            "repeat once per confirmed absent manager"
        ),
    )
    watch_mock.add_argument(
        "--preferences",
        help="User-authored target/caution CSV for the compact draft overlay",
    )
    watch_mock.add_argument(
        "--preference-league",
        help="League key used to filter preferences and scoring conditions",
    )
    watch_mock.add_argument(
        "--preference-snapshot",
        help=(
            "Optional league snapshot for preference conditions "
            "(default: data/cache/PREFERENCE_LEAGUE.json)"
        ),
    )
    watch_mock.add_argument(
        "--preference-limit",
        type=int,
        default=3,
        help="Maximum compact upside targets shown per turn (default: 3)",
    )
    watch_mock.add_argument("--max-polls", type=int)
    watch_mock.add_argument("--once", action="store_true")
    watch_mock.add_argument(
        "--json",
        action="store_true",
        help="Print one JSON collection of reports when the watcher stops",
    )
    watch_mock.add_argument(
        "--show-duplicates",
        action="store_true",
        help="Print unchanged polls; default output only reports authoritative changes",
    )
    watch_mock.add_argument(
        "--record-evidence",
        action="store_true",
        help="Write an append-only mock transcript and automatic post-mock audit",
    )
    watch_mock.add_argument(
        "--sleeper-adp-snapshot",
        help=(
            "Dated Sleeper ADP snapshot required by --record-evidence and "
            "--acquisition-mode sleeper_cpu"
        ),
    )
    watch_mock.add_argument(
        "--evidence-dir",
        default="data/exports/mock_evidence",
        help="Ignored output directory for mock transcripts and audits",
    )
    watch_mock.set_defaults(func=command_watch_mock)

    mock_audit = subparsers.add_parser(
        "audit-mock-evidence",
        help="Rebuild a post-mock audit from an append-only evidence log",
    )
    mock_audit.add_argument("log", help="Mock evidence NDJSON path")
    mock_audit.add_argument("--output")
    mock_audit.add_argument(
        "--external-grade",
        type=float,
        help="Optional FantasyPros Draft Wizard score out of 100",
    )
    mock_audit.set_defaults(func=command_audit_mock_evidence)

    return parser


def main() -> None:
    if sys.argv[1:] in ([], ["--no-banner"]):
        print(
            render_banner(
                detect_stdout(sys.stdout),
                suppressed="--no-banner" in sys.argv[1:],
            ),
            end="",
        )
        print(WELCOME, end="")
        return
    args = build_parser().parse_args()
    product = "roster-theory " + " ".join(
        str(value)
        for value in (
            args.command,
            getattr(args, "inputs_group", None),
            getattr(args, "expert_input_command", None),
            getattr(args, "trade_command", None),
            getattr(args, "waiver_command", None),
        )
        if value is not None
    )
    if not getattr(args, "json", False):
        try:
            if args.command not in {"help", "doctor"}:
                _print_command_identity(args)
            args.func(args)
        except (RosterTheoryError, SleeperError, FantasyProsError, ValueError, OSError, KeyError) as exc:
            _print_product_failure(product, args, exc)
            raise SystemExit(2) from exc
        except KeyboardInterrupt:
            print(f"{product} interrupted", file=sys.stderr)
            raise SystemExit(130) from None
        return

    captured_stdout = io.StringIO()
    exit_code = 0
    with redirect_stdout(captured_stdout):
        try:
            args.func(args)
        except SystemExit as exc:
            exit_code = exc.code if isinstance(exc.code, int) else 2
            try:
                json.loads(captured_stdout.getvalue(), parse_constant=_reject_json_constant)
            except (json.JSONDecodeError, ValueError):
                captured_stdout.seek(0)
                captured_stdout.truncate(0)
                if exit_code == 0:
                    exit_code = 2
                cause = exc.__cause__
                if isinstance(cause, Exception):
                    _print_json(_failure_payload(product, args, cause))
                else:
                    _print_json(
                        {
                            "product": product,
                            "reason": f"Command exited with code {exit_code} without a JSON result",
                            "status": "error",
                        }
                    )
        except KeyboardInterrupt:
            exit_code = 130
            captured_stdout.seek(0)
            captured_stdout.truncate(0)
            _print_json(
                {
                    "error_type": "KeyboardInterrupt",
                    "product": product,
                    "reason": "User interrupted command",
                    "status": "interrupted",
                }
            )
        except (RosterTheoryError, SleeperError, FantasyProsError, ValueError, OSError, KeyError) as exc:
            exit_code = 2
            captured_stdout.seek(0)
            captured_stdout.truncate(0)
            _print_json(_failure_payload(product, args, exc))
        except Exception as exc:
            exit_code = 1
            captured_stdout.seek(0)
            captured_stdout.truncate(0)
            payload = _failure_payload(product, args, exc)
            payload["status"] = "internal_error"
            _print_json(payload)

    output = captured_stdout.getvalue()
    try:
        json.loads(
            output,
            parse_constant=_reject_json_constant,
        )
    except (json.JSONDecodeError, ValueError):
        exit_code = 2
        output = json.dumps(
            {
                "product": product,
                "reason": "Command produced no single valid JSON value on stdout",
                "status": "output_error",
            },
            sort_keys=True,
        ) + "\n"
    sys.stdout.write(output)
    if exit_code:
        raise SystemExit(exit_code)
