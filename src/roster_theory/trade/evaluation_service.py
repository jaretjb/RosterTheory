from __future__ import annotations

import json
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Sequence

from roster_theory.core.provenance import stable_hash
from roster_theory.fantasypros import FantasyProsClient
from roster_theory.providers.cache import atomic_write_json
from roster_theory.sleeper import resolve_league_policy_path
from roster_theory.trade.board_service import BoardRefreshResult, refresh_value_boards
from roster_theory.trade.evaluation import (
    EvaluationOptions,
    RosterDiagnosis,
    TradeEvaluation,
    build_entered_package,
    evaluate_trade,
    diagnose_roster,
    resolve_player,
    save_trade_evaluation,
)


@dataclass(frozen=True, slots=True)
class EnteredEvaluationResult:
    evaluation: TradeEvaluation
    board_refresh: BoardRefreshResult
    output_path: Path


@dataclass(frozen=True, slots=True)
class RosterDiagnosisResult:
    diagnosis: RosterDiagnosis
    board_refresh: BoardRefreshResult
    output_path: Path
    evidence_hash: str


def _options_from_policy(
    options: EvaluationOptions,
    policy_path: str | Path,
) -> EvaluationOptions:
    policy = json.loads(Path(policy_path).read_text(encoding="utf-8"))
    posture = options.risk_posture.upper()
    posture_policy = policy["decision"]["postures"].get(posture)
    if posture_policy is None:
        raise ValueError("risk_posture must be CONSERVATIVE, BALANCED, or CEILING")
    return replace(
        options,
        risk_posture=posture,
        risk_policy_version=str(policy["version"]),
        offense_downside_multiplier=float(policy["scenario"]["offense_downside_multiplier"]),
        offense_upside_multiplier=float(policy["scenario"]["offense_upside_multiplier"]),
        user_selected_floor=float(policy["decision"]["user_selected_floor"]),
        partner_market_floor=float(policy["decision"]["partner_market_floor"]),
        max_depth_loss=float(posture_policy["max_depth_loss"]),
        max_downside_increase=float(posture_policy["max_downside_increase"]),
    )


def evaluate_entered_trade(
    league_key: str,
    *,
    send: Sequence[str],
    receive: Sequence[str],
    options: EvaluationOptions = EvaluationOptions(),
    output_path: str | Path | None = None,
    expert_pool_path: str | Path | None = None,
    cache_dir: str | Path = "data/cache/trade/fantasypros/2026",
    budget_path: str | Path = "data/cache/trade/fantasypros/daily_budget.json",
    policy_path: str | Path | None = None,
    config_path: str | Path | None = None,
    fantasypros_client: FantasyProsClient | None = None,
) -> EnteredEvaluationResult:
    resolved_policy = resolve_league_policy_path(
        league_key,
        "trade_decision",
        config_path=config_path,
        explicit_path=policy_path,
    )
    board_refresh = refresh_value_boards(
        league_key,
        config_path=config_path,
        expert_pool_path=expert_pool_path,
        cache_dir=cache_dir,
        budget_path=budget_path,
        fantasypros_client=fantasypros_client,
    )
    snapshot = board_refresh.refresh.snapshot
    package = build_entered_package(snapshot, send=send, receive=receive)
    normalized_options = _options_from_policy(options, resolved_policy)
    drop_queries = tuple(options.drop_overrides)
    if options.drop_override and options.drop_override not in drop_queries:
        drop_queries = (*drop_queries, options.drop_override)
    add_queries = tuple(options.add_overrides)
    if options.add_override and options.add_override not in add_queries:
        add_queries = (*add_queries, options.add_override)
    if drop_queries:
        drops = tuple(resolve_player(snapshot, query).player_id for query in drop_queries)
        normalized_options = replace(
            normalized_options,
            drop_override=None,
            drop_overrides=drops,
        )
    if add_queries:
        adds = tuple(
            resolve_player(snapshot, query, require_unrostered=True).player_id
            for query in add_queries
        )
        normalized_options = replace(
            normalized_options,
            add_override=None,
            add_overrides=adds,
        )
    evaluation = evaluate_trade(
        snapshot,
        package,
        projections=board_refresh.weekly_projections,
        selected_board=board_refresh.selected_final,
        market_board=board_refresh.market,
        options=normalized_options,
    )
    target = Path(
        output_path
        or board_refresh.output_path.with_name(
            f"trade_evaluation_{evaluation.evidence_hash[:16]}.json"
        )
    )
    save_trade_evaluation(evaluation, target)
    return EnteredEvaluationResult(evaluation, board_refresh, target)


def diagnose_current_roster(
    league_key: str,
    *,
    options: EvaluationOptions = EvaluationOptions(),
    output_path: str | Path | None = None,
    expert_pool_path: str | Path | None = None,
    cache_dir: str | Path = "data/cache/trade/fantasypros/2026",
    budget_path: str | Path = "data/cache/trade/fantasypros/daily_budget.json",
    policy_path: str | Path | None = None,
    config_path: str | Path | None = None,
    fantasypros_client: FantasyProsClient | None = None,
) -> RosterDiagnosisResult:
    resolved_policy = resolve_league_policy_path(
        league_key,
        "trade_decision",
        config_path=config_path,
        explicit_path=policy_path,
    )
    board_refresh = refresh_value_boards(
        league_key,
        config_path=config_path,
        expert_pool_path=expert_pool_path,
        cache_dir=cache_dir,
        budget_path=budget_path,
        fantasypros_client=fantasypros_client,
    )
    normalized_options = _options_from_policy(options, resolved_policy)
    diagnosis = diagnose_roster(
        board_refresh.refresh.snapshot,
        board_refresh.weekly_projections,
        options=normalized_options,
    )
    payload = {
        "schema_version": 1,
        "product": "TRADE ASSISTANT",
        "operation": "ROSTER DIAGNOSIS",
        "manifest_id": board_refresh.refresh.snapshot.manifest.analysis_id,
        "league_key": league_key,
        "risk_policy_version": normalized_options.risk_policy_version,
        "risk_posture": normalized_options.risk_posture,
        "diagnosis": asdict(diagnosis),
    }
    evidence_hash = stable_hash(payload)
    target = Path(
        output_path
        or board_refresh.output_path.with_name(
            f"roster_diagnosis_{evidence_hash[:16]}.json"
        )
    )
    atomic_write_json(target, {**payload, "evidence_hash": evidence_hash})
    return RosterDiagnosisResult(diagnosis, board_refresh, target, evidence_hash)


def format_roster_diagnosis(result: RosterDiagnosisResult) -> str:
    diagnosis = result.diagnosis
    names = {
        player.player_id: player.name
        for player in result.board_refresh.refresh.snapshot.players
    }
    lines = [
        f"TRADE ASSISTANT - {result.board_refresh.refresh.snapshot.league_key} - ROSTER DIAGNOSIS",
        f"Roster {diagnosis.roster_id}: {diagnosis.smallest_useful_change}",
        "Weekly optimal points: "
        + ", ".join(f"W{week} {points:.2f}" for week, points in diagnosis.weekly_optimal_points),
        "Bye gaps: " + (", ".join(map(str, diagnosis.bye_gap_weeks)) or "none"),
    ]
    for row in diagnosis.positions:
        lines.append(
            f"{row.position}: starters {', '.join(names.get(pid, pid) for pid in row.starter_player_ids) or 'none'}; "
            f"usable surplus {', '.join(names.get(pid, pid) for pid in row.usable_surplus_player_ids) or 'none'}; "
            f"waiver {names.get(row.waiver_player_id, row.waiver_player_id) if row.waiver_player_id else 'none'} "
            f"({row.waiver_average_points:.2f}); need {row.need_above_waiver:.2f}"
        )
    lines.append(
        f"Risk: max offense {diagnosis.risk.max_offense_team or 'none'} "
        f"{diagnosis.risk.max_offense_share:.1%}; worst offense downside "
        f"{diagnosis.risk.offense_downside_team or 'none'} {diagnosis.risk.offense_downside_loss:.2f}; "
        f"best offense upside {diagnosis.risk.offense_upside_team or 'none'} "
        f"{diagnosis.risk.offense_upside_gain:.2f}"
    )
    return "\n".join(lines)


def evaluation_report(result: EnteredEvaluationResult) -> dict[str, Any]:
    value = asdict(result.evaluation)
    value["output_path"] = str(result.output_path)
    value["fantasypros_call_plan"] = asdict(result.board_refresh.call_plan)
    return value


def format_trade_evaluation(evaluation: TradeEvaluation) -> str:
    names = dict(evaluation.resolved_players)
    package = evaluation.package
    sent = ", ".join(names.get(row.player_id, row.player_id) for row in package.from_a)
    received = ", ".join(names.get(row.player_id, row.player_id) for row in package.from_b)
    source_groups: dict[str, list[str]] = {}
    for source, captured_at in evaluation.source_times:
        source_groups.setdefault(source.split(":", 1)[0], []).append(captured_at)
    source_summary = " | ".join(
        f"{source} latest {max(captured_times)}"
        for source, captured_times in sorted(source_groups.items())
    )
    decision_banner = (
        f"DECISION: {evaluation.decision.label} - {evaluation.decision.posture} - "
        f"{evaluation.decision.policy_version}"
        if evaluation.decision is not None
        else "NO DECISION LABEL — required evidence is unavailable"
    )
    lines = [
        f"TRADE ASSISTANT - {evaluation.league_key} - Weeks "
        f"{evaluation.horizon[0]}-{evaluation.horizon[-1]}",
        decision_banner,
        f"Package: send {sent} | receive {received}",
        evaluation.summary,
        "Data: " + source_summary,
    ]
    for impact in evaluation.team_impacts:
        lines.append(
            f"Roster {impact.roster_id}: starter {impact.weighted_delta:+.2f}, "
            f"depth {impact.depth_delta:+.2f}, playoffs {impact.playoff_delta:+.2f}; "
            f"best W{impact.best_week} {impact.best_week_delta:+.2f}, "
            f"worst W{impact.worst_week} {impact.worst_week_delta:+.2f}"
        )
        replacement_weeks = tuple(
            row
            for row in impact.weeks
            if row.before_replacements or row.after_replacements
        )
        if replacement_weeks:
            lines.append(
                f"Roster {impact.roster_id} bye/inactive waiver floor: "
                + "; ".join(
                    f"W{row.week} before "
                    + (
                        ", ".join(
                            names.get(player_id, player_id)
                            for player_id in row.before_replacements
                        )
                        or "none"
                    )
                    + ", after "
                    + (
                        ", ".join(
                            names.get(player_id, player_id)
                            for player_id in row.after_replacements
                        )
                        or "none"
                    )
                    for row in replacement_weeks
                )
            )
    for move in evaluation.secondary_moves:
        if move.kind != "NONE":
            chosen = ", ".join(
                names.get(player_id, player_id) for player_id in move.chosen_player_ids
            )
            next_best = (
                ", ".join(
                    names.get(player_id, player_id)
                    for player_id in move.next_best_player_ids
                )
                or "none"
            )
            lines.append(
                f"Roster {move.roster_id} {move.kind.lower()} set: {chosen}; "
                f"next {next_best}; {move.combinations_considered} combinations from "
                f"{move.candidate_pool_size} of {move.eligible_player_count} candidates"
                + (" (bounded search)" if move.search_truncated else "")
            )
    for value in evaluation.ownership_impacts:
        selected = (
            f"sent {value.selected_sent:.2f}, received {value.selected_received:.2f}, "
            f"secondary {value.selected_secondary_delta:+.2f}"
            if value.selected_sent is not None
            and value.selected_received is not None
            and value.selected_secondary_delta is not None
            else "unavailable (ECR-ONLY)"
        )
        lines.extend(
            (
                f"Roster {value.roster_id} selected ownership: {selected}",
                f"Roster {value.roster_id} market ownership: sent {value.market_sent:.2f}, "
                f"received {value.market_received:.2f}, secondary {value.market_secondary_delta:+.2f}",
                f"Roster {value.roster_id} raw projection: sent {value.raw_projection_sent:.2f}, "
                f"received {value.raw_projection_received:.2f}, secondary "
                f"{value.raw_projection_secondary_delta:+.2f}",
            )
        )
    for risk in evaluation.risk_impacts:
        lines.append(
            f"Roster {risk.roster_id} risk: max offense share "
            f"{risk.before.max_offense_share:.1%}->{risk.after.max_offense_share:.1%} "
            f"({risk.max_offense_share_delta:+.1%}); downside loss "
            f"{risk.before.offense_downside_loss:.2f}->{risk.after.offense_downside_loss:.2f} "
            f"({risk.offense_downside_loss_delta:+.2f}); upside gain "
            f"{risk.before.offense_upside_gain:.2f}->{risk.after.offense_upside_gain:.2f} "
            f"({risk.offense_upside_gain_delta:+.2f})"
        )
    if evaluation.decision is not None:
        failed = tuple(gate for gate in evaluation.decision.gates if not gate.passed)
        lines.append(
            "Decision gates: "
            + "; ".join(
                f"{gate.name} {'PASS' if gate.passed else 'FAIL'} "
                f"(actual {gate.actual}, requires {gate.comparison} {gate.threshold})"
                for gate in evaluation.decision.gates
            )
        )
        if failed:
            lines.append("Strongest failed gate: " + failed[0].explanation)
    coverage = evaluation.projection_coverage
    if coverage.missing_player_count:
        if coverage.relevant_player_count:
            lines.append(
                "Projection coverage: "
                f"{coverage.relevant_player_count} evaluated players missing "
                f"{coverage.relevant_player_week_count} player-weeks; "
                f"{coverage.outside_player_count} outside-evaluation players missing "
                f"{coverage.outside_player_week_count} player-weeks"
            )
        else:
            lines.append(
                "Projection coverage: all evaluated/package players covered; "
                f"{coverage.outside_player_count} outside-evaluation players with "
                f"{coverage.outside_player_week_count} missing player-weeks omitted from warnings"
            )
    lines.append("Modes: " + ", ".join(evaluation.modes))
    if evaluation.provisional_reversal_conditions:
        lines.append(
            "Strongest reversal condition: "
            + evaluation.provisional_reversal_conditions[0].condition
        )
    if evaluation.warnings:
        lines.append("Warnings: " + " | ".join(evaluation.warnings))
    return "\n".join(lines)
