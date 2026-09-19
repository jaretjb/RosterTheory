from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Mapping, Sequence

from roster_theory.core.provenance import stable_hash
from roster_theory.fantasypros import FantasyProsClient
from roster_theory.providers.cache import atomic_write_json
from roster_theory.sleeper import resolve_league_policy_path
from roster_theory.trade.board_service import BoardRefreshResult, refresh_value_boards
from roster_theory.trade.evaluation import (
    EvaluationOptions,
    TradeEvaluation,
    build_entered_package,
    build_weekly_projection_matrix,
    evaluate_trade,
)
from roster_theory.trade.evaluation_service import _options_from_policy
from roster_theory.trade.search import LeagueSearchResult, SearchConfig, search_league


@dataclass(frozen=True, slots=True)
class GapRow:
    player_id: str
    player_name: str
    position: str
    owner_roster_id: str | None
    ownership: str
    signal: str
    selected_rank: int
    market_rank: int
    selected_value: float
    market_value: float
    value_gap: float


@dataclass(frozen=True, slots=True)
class GapReport:
    schema_version: int
    manifest_id: str
    league_key: str
    horizon: str
    rows: tuple[GapRow, ...]
    evidence_hash: str


@dataclass(frozen=True, slots=True)
class SearchRunResult:
    search: LeagueSearchResult
    board_refresh: BoardRefreshResult
    output_path: Path
    csv_path: Path | None


@dataclass(frozen=True, slots=True)
class GapRunResult:
    gaps: GapReport
    board_refresh: BoardRefreshResult
    output_path: Path
    csv_path: Path | None


@dataclass(frozen=True, slots=True)
class CompareRunResult:
    evaluations: tuple[TradeEvaluation, ...]
    board_refresh: BoardRefreshResult
    output_path: Path
    evidence_hash: str


def _refresh(
    league_key: str,
    *,
    config_path: str | Path | None,
    expert_pool_path: str | Path | None,
    cache_dir: str | Path,
    budget_path: str | Path,
    fantasypros_client: FantasyProsClient | None,
) -> BoardRefreshResult:
    return refresh_value_boards(
        league_key,
        config_path=config_path,
        expert_pool_path=expert_pool_path,
        cache_dir=cache_dir,
        budget_path=budget_path,
        fantasypros_client=fantasypros_client,
    )


def _config_from_policy(
    config: SearchConfig,
    policy_path: str | Path,
) -> SearchConfig:
    policy = json.loads(Path(policy_path).read_text(encoding="utf-8"))
    target = policy["target"]
    return replace(
        config,
        search_policy_version=str(policy["version"]),
        target_market_value_floor=float(target["market_value_floor"]),
        target_raw_projection_floor=float(target["raw_projection_floor"]),
        target_material_gap_floor=float(target["material_gap_floor"]),
        max_partner_lineup_loss=float(target["max_partner_lineup_loss"]),
        near_waiver_need_margin=float(
            target.get("near_waiver_need_margin", config.near_waiver_need_margin)
        ),
        reject_received_asset_drop=bool(target["reject_received_asset_drop"]),
        max_one_starter_reserves=int(target["max_one_starter_reserves"]),
    )


def _atomic_write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = tuple(dict.fromkeys(key for row in rows for key in row))
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def _gap_report(board_refresh: BoardRefreshResult) -> GapReport:
    snapshot = board_refresh.refresh.snapshot
    players = {row.player_id: row for row in snapshot.players}
    owners = dict(snapshot.owner_by_player)
    rows = tuple(
        GapRow(
            player_id=row.player_id,
            player_name=players[row.player_id].name,
            position=row.position,
            owner_roster_id=owners.get(row.player_id),
            ownership=(
                "USER"
                if owners.get(row.player_id) == snapshot.user_roster_id
                else "OPPONENT"
                if owners.get(row.player_id) is not None
                else "WAIVER"
            ),
            signal=row.signal,
            selected_rank=row.selected_rank,
            market_rank=row.market_rank,
            selected_value=round(row.selected_vorp, 3),
            market_value=round(row.market_vorp, 3),
            value_gap=round(row.value_gap, 3),
        )
        for row in sorted(
            board_refresh.gaps,
            key=lambda item: (-abs(item.value_gap), item.player_id),
        )
    )
    base = GapReport(
        schema_version=1,
        manifest_id=snapshot.manifest.analysis_id,
        league_key=snapshot.league_key,
        horizon=snapshot.ranking_horizon,
        rows=rows,
        evidence_hash="",
    )
    return replace(base, evidence_hash=stable_hash(asdict(base)))


def run_gap_report(
    league_key: str,
    *,
    config_path: str | Path | None = None,
    output_path: str | Path | None = None,
    csv_path: str | Path | None = None,
    expert_pool_path: str | Path | None = None,
    cache_dir: str | Path = "data/cache/trade/fantasypros/2026",
    budget_path: str | Path = "data/cache/trade/fantasypros/daily_budget.json",
    fantasypros_client: FantasyProsClient | None = None,
) -> GapRunResult:
    refresh = _refresh(
        league_key,
        config_path=config_path,
        expert_pool_path=expert_pool_path,
        cache_dir=cache_dir,
        budget_path=budget_path,
        fantasypros_client=fantasypros_client,
    )
    report = _gap_report(refresh)
    target = Path(
        output_path
        or refresh.output_path.with_name(f"trade_gaps_{report.evidence_hash[:16]}.json")
    )
    atomic_write_json(target, asdict(report))
    csv_target = Path(csv_path) if csv_path else None
    if csv_target:
        _atomic_write_csv(csv_target, tuple(asdict(row) for row in report.rows))
    return GapRunResult(report, refresh, target, csv_target)


def run_league_search(
    league_key: str,
    *,
    config_path: str | Path | None = None,
    options: EvaluationOptions = EvaluationOptions(),
    config: SearchConfig = SearchConfig(),
    output_path: str | Path | None = None,
    csv_path: str | Path | None = None,
    expert_pool_path: str | Path | None = None,
    cache_dir: str | Path = "data/cache/trade/fantasypros/2026",
    budget_path: str | Path = "data/cache/trade/fantasypros/daily_budget.json",
    policy_path: str | Path | None = None,
    search_policy_path: str | Path | None = None,
    fantasypros_client: FantasyProsClient | None = None,
) -> SearchRunResult:
    resolved_policy = resolve_league_policy_path(
        league_key,
        "trade_decision",
        config_path=config_path,
        explicit_path=policy_path,
    )
    resolved_search_policy = resolve_league_policy_path(
        league_key,
        "trade_search",
        config_path=config_path,
        explicit_path=search_policy_path,
    )
    refresh = _refresh(
        league_key,
        config_path=config_path,
        expert_pool_path=expert_pool_path,
        cache_dir=cache_dir,
        budget_path=budget_path,
        fantasypros_client=fantasypros_client,
    )
    normalized_options = _options_from_policy(options, resolved_policy)
    normalized_config = _config_from_policy(config, resolved_search_policy)
    result = search_league(
        refresh.refresh.snapshot,
        projections=refresh.weekly_projections,
        selected_board=refresh.selected_final,
        market_board=refresh.market,
        gaps=refresh.gaps,
        options=normalized_options,
        config=normalized_config,
    )
    target = Path(
        output_path
        or refresh.output_path.with_name(f"trade_search_{result.evidence_hash[:16]}.json")
    )
    atomic_write_json(target, asdict(result))
    csv_target = Path(csv_path) if csv_path else None
    if csv_target:
        names = {row.player_id: row.name for row in refresh.refresh.snapshot.players}
        _atomic_write_csv(
            csv_target,
            tuple(
                {
                    "label": row.label,
                    "opponent_roster_id": row.opponent_roster_id,
                    "package_size": row.package_size,
                    "send": "; ".join(names.get(pid, pid) for pid in row.sent_player_ids),
                    "receive": "; ".join(names.get(pid, pid) for pid in row.received_player_ids),
                    "user_lineup_delta": row.user_lineup_delta,
                    "user_selected_delta": row.user_selected_delta,
                    "user_market_delta": row.user_market_delta,
                    "user_raw_projection_delta": row.user_raw_projection_delta,
                    "partner_market_delta": row.partner_market_delta,
                    "user_rationale": row.user_rationale,
                    "partner_rationale": row.partner_rationale,
                    "objectives": "; ".join(row.objective_tags),
                    "incoming_asset_usage": "; ".join(
                        f"{names.get(usage.player_id, usage.player_id)} starts W{','.join(str(week) for week in usage.starter_weeks) or 'none'}"
                        for usage in row.incoming_asset_usage
                    ),
                }
                for row in result.opportunities
            ),
        )
    return SearchRunResult(result, refresh, target, csv_target)


def run_package_comparison(
    league_key: str,
    *,
    config_path: str | Path | None = None,
    packages: Sequence[Mapping[str, Sequence[str]]],
    options: EvaluationOptions = EvaluationOptions(),
    output_path: str | Path | None = None,
    expert_pool_path: str | Path | None = None,
    cache_dir: str | Path = "data/cache/trade/fantasypros/2026",
    budget_path: str | Path = "data/cache/trade/fantasypros/daily_budget.json",
    policy_path: str | Path | None = None,
    fantasypros_client: FantasyProsClient | None = None,
) -> CompareRunResult:
    if not packages:
        raise ValueError("Comparison requires at least one package")
    resolved_policy = resolve_league_policy_path(
        league_key,
        "trade_decision",
        config_path=config_path,
        explicit_path=policy_path,
    )
    refresh = _refresh(
        league_key,
        config_path=config_path,
        expert_pool_path=expert_pool_path,
        cache_dir=cache_dir,
        budget_path=budget_path,
        fantasypros_client=fantasypros_client,
    )
    options = _options_from_policy(options, resolved_policy)
    projection_matrix = build_weekly_projection_matrix(
        refresh.refresh.snapshot, refresh.weekly_projections
    )
    evaluations = tuple(
        evaluate_trade(
            refresh.refresh.snapshot,
            build_entered_package(
                refresh.refresh.snapshot,
                send=tuple(package.get("send", ())),
                receive=tuple(package.get("receive", ())),
            ),
            projections=refresh.weekly_projections,
            selected_board=refresh.selected_final,
            market_board=refresh.market,
            options=options,
            projection_matrix=projection_matrix,
        )
        for package in packages
    )
    label_order = {"TARGET": 0, "ACCEPTABLE": 1, "COUNTER": 2, "DECLINE": 3}
    evaluations = tuple(
        sorted(
            evaluations,
            key=lambda row: (
                label_order.get(row.decision_label, 9),
                -row.team_impacts[0].weighted_delta,
                row.evidence_hash,
            ),
        )
    )
    payload = {
        "schema_version": 1,
        "operation": "TRADE PACKAGE COMPARISON",
        "manifest_id": refresh.refresh.snapshot.manifest.analysis_id,
        "league_key": league_key,
        "evaluations": tuple(asdict(row) for row in evaluations),
    }
    evidence_hash = stable_hash(payload)
    target = Path(
        output_path
        or refresh.output_path.with_name(f"trade_compare_{evidence_hash[:16]}.json")
    )
    atomic_write_json(target, {**payload, "evidence_hash": evidence_hash})
    return CompareRunResult(evaluations, refresh, target, evidence_hash)


def load_search_evidence(path: str | Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    saved_hash = value.get("evidence_hash")
    unhashed = dict(value)
    unhashed["evidence_hash"] = ""
    if not isinstance(saved_hash, str) or stable_hash(unhashed) != saved_hash:
        raise ValueError("Trade search evidence hash does not match its contents")
    value["replay_mode"] = "OFFLINE/NON-CURRENT"
    return value


def format_gap_report(result: GapRunResult) -> str:
    lines = [
        f"TRADE ASSISTANT - {result.gaps.league_key} - {result.gaps.horizon} VALUE GAPS",
        "Positive = market values the player more (sell-high); negative = selected board values the player more (buy-low).",
    ]
    for row in result.gaps.rows[:20]:
        lines.append(
            f"{row.signal:9} {row.player_name} ({row.position}, {row.ownership}"
            f"{':' + row.owner_roster_id if row.owner_roster_id else ''}) "
            f"gap {row.value_gap:+.2f}; selected {row.selected_value:.2f}, market {row.market_value:.2f}"
        )
    return "\n".join(lines)


def format_search_result(result: SearchRunResult) -> str:
    snapshot = result.board_refresh.refresh.snapshot
    names = {row.player_id: row.name for row in snapshot.players}
    lines = [
        f"TRADE ASSISTANT - {result.search.league_key} - {result.search.horizon} OPPORTUNITY SEARCH",
        f"Returned {len(result.search.opportunities)} non-dominated opportunities; large-package search is bounded, not exhaustive.",
        f"Policy {result.search.search_policy_version}: TARGET requires nonnegative selected, market, and raw-projection value; one-starter depth is roster-context limited.",
    ]
    for index, row in enumerate(result.search.opportunities, 1):
        sent = ", ".join(names.get(pid, pid) for pid in row.sent_player_ids)
        received = ", ".join(names.get(pid, pid) for pid in row.received_player_ids)
        lines.extend(
            (
                f"{index}. {row.label} vs roster {row.opponent_roster_id}: send {sent}; receive {received}",
                f"   User lineup {row.user_lineup_delta:+.2f}, selected value {row.user_selected_delta:+.2f}; "
                f"market {row.user_market_delta:+.2f}, raw projection {row.user_raw_projection_delta:+.2f}; "
                f"partner lineup {row.partner_lineup_delta:+.2f}, market value {row.partner_market_delta:+.2f}",
                f"   Why: {row.user_rationale}; partner: {row.partner_rationale}; "
                f"objectives {', '.join(row.objective_tags) or 'frontier alternative'}",
                "   Incoming use: "
                + "; ".join(
                    f"{names.get(usage.player_id, usage.player_id)} starts "
                    f"{len(usage.starter_weeks)} week(s)"
                    f" ({usage.weighted_lineup_delta_in_started_weeks:+.2f} team delta in those weeks)"
                    for usage in row.incoming_asset_usage
                ),
            )
        )
    lines.append("Coverage (enumerated / pruned / exact / accepted):")
    lines.extend(
        f"  {row.package_size}: {row.enumerated} / {row.pruned} / {row.evaluated} / {row.accepted}"
        for row in result.search.coverage
    )
    if result.search.rejection_counts:
        lines.append(
            "Rejections: "
            + ", ".join(
                f"{reason} {count}"
                for reason, count in result.search.rejection_counts
            )
        )
    return "\n".join(lines)


def format_package_comparison(result: CompareRunResult) -> str:
    names = {
        row.player_id: row.name for row in result.board_refresh.refresh.snapshot.players
    }
    lines = ["TRADE ASSISTANT - PACKAGE COMPARISON"]
    for index, evaluation in enumerate(result.evaluations, 1):
        sent = ", ".join(
            names.get(row.player_id, row.player_id) for row in evaluation.package.from_a
        )
        received = ", ".join(
            names.get(row.player_id, row.player_id) for row in evaluation.package.from_b
        )
        lines.append(
            f"{index}. {evaluation.decision_label}: send {sent}; receive {received}; "
            f"lineup {evaluation.team_impacts[0].weighted_delta:+.2f}"
        )
    return "\n".join(lines)
