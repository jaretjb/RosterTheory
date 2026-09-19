from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

from roster_theory.core.call_plan import CallPlan, PlannedCall, build_call_plan
from roster_theory.core.errors import StaleData
from roster_theory.core.provenance import canonical_json
from roster_theory.providers.cache import DailyRequestBudget, is_fresh
from roster_theory.providers.sleeper import SleeperAdapter
from roster_theory.sleeper import (
    SleeperClient,
    find_league_config,
    load_owner_config,
    resolve_league_policy_path,
)
from roster_theory.waiver.evaluation import (
    WaiverEvaluation,
    evaluate_waiver,
    load_waiver_evaluation_inputs,
    save_waiver_evaluation,
)
from roster_theory.waiver.policy import (
    apply_waiver_policy,
    emerging_role_signal_strength,
    evaluation_options_for_policy,
    load_waiver_policy,
)
from roster_theory.waiver.search import (
    WaiverSearch,
    save_waiver_search,
    search_waiver_candidates,
)
from roster_theory.waiver.snapshot import (
    WaiverSnapshot,
    build_waiver_snapshot,
    save_waiver_snapshot,
)


@dataclass(frozen=True, slots=True)
class WaiverRefreshResult:
    snapshot: WaiverSnapshot
    call_plan: CallPlan
    output_path: Path


@dataclass(frozen=True, slots=True)
class EnteredWaiverEvaluationResult:
    evaluation: WaiverEvaluation
    refresh: WaiverRefreshResult
    output_path: Path
    input_path: Path


@dataclass(frozen=True, slots=True)
class WaiverSearchResult:
    search: WaiverSearch
    refresh: WaiverRefreshResult
    output_path: Path
    input_path: Path


def _load_policy_for_league(
    league_key: str,
    policy_path: str | Path | None,
    config_path: str | Path | None = None,
):
    return load_waiver_policy(
        resolve_league_policy_path(
            league_key,
            "waiver_decision",
            config_path=config_path,
            explicit_path=policy_path,
        )
    )


def _player_cache_fresh(path: Path, now: datetime) -> bool:
    if not path.exists():
        return False
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        captured_at = datetime.fromisoformat(str(value["captured_at"]))
        return is_fresh(captured_at, timedelta(minutes=5), now=now)
    except (KeyError, TypeError, ValueError):
        return False


def waiver_refresh_plan(
    league_id: str,
    current_week: int,
    *,
    player_cache_hit: bool,
) -> CallPlan:
    return build_call_plan(
        [
            PlannedCall("nfl_state", "Sleeper", "/state/nfl"),
            PlannedCall("league", "Sleeper", f"/league/{league_id}"),
            PlannedCall("users", "Sleeper", f"/league/{league_id}/users"),
            PlannedCall("rosters", "Sleeper", f"/league/{league_id}/rosters"),
            PlannedCall(
                "players",
                "Sleeper",
                "/players/nfl",
                fresh_cache_hit=player_cache_hit,
            ),
            PlannedCall(
                "transactions",
                "Sleeper",
                f"/league/{league_id}/transactions/{current_week}",
            ),
        ],
        DailyRequestBudget(),
    )


def refresh_waiver_snapshot(
    league_key: str,
    *,
    config_path: str | Path | None = None,
    player_cache_path: str | Path = "data/cache/waiver/sleeper/players_nfl.json",
    output_path: str | Path | None = None,
    client: SleeperClient | None = None,
    availability_by_player: dict[str, str] | None = None,
) -> WaiverRefreshResult:
    league_config = find_league_config(league_key, config_path)
    owner = load_owner_config(config_path)
    league_id = str(league_config["league_id"])
    user_id = str(owner.get("sleeper_user_id") or "")
    if not user_id:
        raise ValueError("Configured Sleeper user ID is required")
    now = datetime.now(timezone.utc)
    cache_path = Path(player_cache_path)
    cache_hit = _player_cache_fresh(cache_path, now)
    bundle = SleeperAdapter(
        client or SleeperClient(), player_cache_path=cache_path
    ).fetch_waiver(league_id)
    snapshot = build_waiver_snapshot(
        league_key=league_key,
        user_id=user_id,
        sleeper=bundle,
        expected_user_roster_id=str(league_config["user_roster_id"]),
        availability_by_player=availability_by_player,
    )
    plan = waiver_refresh_plan(
        league_id,
        snapshot.manifest.current_week,
        player_cache_hit=cache_hit,
    )
    target = Path(
        output_path
        or Path("data/exports/waiver")
        / league_key
        / snapshot.manifest.analysis_id
        / "snapshot.json"
    )
    save_waiver_snapshot(snapshot, target)
    return WaiverRefreshResult(snapshot=snapshot, call_plan=plan, output_path=target)


def waiver_refresh_report(result: WaiverRefreshResult) -> dict[str, Any]:
    snapshot = result.snapshot
    acquisition_counts = Counter(item.state for item in snapshot.acquisitions)
    user_capacity = next(
        item for item in snapshot.roster_capacity if item.roster_id == snapshot.user_roster_id
    )
    return {
        "product": snapshot.product,
        "operation": "DATA-ONLY REFRESH",
        "league": snapshot.league_key,
        "season": snapshot.league.season,
        "current_week": snapshot.manifest.current_week,
        "current": snapshot.current,
        "roster_snapshot_complete": snapshot.completeness.roster_snapshot_complete,
        "snapshot_complete": snapshot.completeness.snapshot_complete,
        "acquisition_state_complete": snapshot.completeness.acquisition_state_complete,
        "teams": len(snapshot.teams),
        "owned_players": len(snapshot.owner_by_player),
        "supported_players": len(snapshot.players),
        "user_roster_id": snapshot.user_roster_id,
        "user_open_active_slots": user_capacity.open_active_slots,
        "user_reserve_legal": user_capacity.reserve_legal,
        "acquisition_state_counts": dict(sorted(acquisition_counts.items())),
        "manifest_id": snapshot.manifest.analysis_id,
        "call_plan": {
            "provider": "Sleeper",
            "http_methods": ["GET"],
            "total_inputs": len(result.call_plan.calls),
            "network_gets": len(result.call_plan.calls) - result.call_plan.cache_hits,
            "cache_hits": result.call_plan.cache_hits,
            "fantasypros_calls": result.call_plan.fantasypros_calls,
        },
        "capabilities": dict(snapshot.capabilities),
        "warnings": list(snapshot.warnings),
        "snapshot_path": str(result.output_path),
        "recommendation_generated": snapshot.recommendation_generated,
        "sleeper_write_performed": snapshot.sleeper_write_performed,
    }


def evaluate_entered_waiver(
    league_key: str,
    *,
    add: str,
    inputs_path: str | Path,
    drop: str | None = None,
    output_path: str | Path | None = None,
    player_cache_path: str | Path = "data/cache/waiver/sleeper/players_nfl.json",
    policy_path: str | Path | None = None,
    config_path: str | Path | None = None,
    client: SleeperClient | None = None,
    now: datetime | None = None,
) -> EnteredWaiverEvaluationResult:
    input_check_time = now or datetime.now(timezone.utc)
    input_path = Path(inputs_path)
    inputs = load_waiver_evaluation_inputs(input_path)
    if inputs.league_key != league_key:
        raise ValueError("Waiver evaluation inputs are for a different league")
    if not is_fresh(inputs.captured_at, timedelta(minutes=5), now=input_check_time):
        raise StaleData("Waiver value/legality inputs exceed the five-minute freshness gate")
    policy = _load_policy_for_league(league_key, policy_path, config_path)
    refresh = refresh_waiver_snapshot(
        league_key,
        config_path=config_path,
        player_cache_path=player_cache_path,
        client=client,
        availability_by_player=dict(inputs.availability_by_player),
    )
    evaluation = apply_waiver_policy(
        evaluate_waiver(
            refresh.snapshot,
            add=add,
            drop=drop,
            weeks=inputs.weeks,
            projections=inputs.projections,
            values=inputs.values,
            drop_legality=dict(inputs.drop_legality),
            news_fresh=dict(inputs.news_fresh),
            contingencies=inputs.contingencies,
            waiver_wire_evidence=inputs.waiver_wire_evidence,
            emergence_evidence=inputs.emergence_evidence,
            input_bundle_hash=inputs.input_hash,
            availability_source=inputs.availability_source,
            options=evaluation_options_for_policy(policy),
            now=now,
        ),
        policy,
    )
    final_check_time = now or datetime.now(timezone.utc)
    if not is_fresh(inputs.captured_at, timedelta(minutes=5), now=final_check_time):
        raise StaleData("Waiver value/legality inputs expired during evaluation")
    target = Path(
        output_path
        or refresh.output_path.with_name(
            f"waiver_evaluation_{evaluation.evidence_hash[:16]}.json"
        )
    )
    save_waiver_evaluation(evaluation, target)
    return EnteredWaiverEvaluationResult(evaluation, refresh, target, input_path)


def waiver_evaluation_report(result: EnteredWaiverEvaluationResult) -> dict[str, Any]:
    value = json.loads(canonical_json(result.evaluation))
    value["output_path"] = str(result.output_path)
    value["input_path"] = str(result.input_path)
    value["refresh_call_plan"] = waiver_refresh_report(result.refresh)["call_plan"]
    return value


def search_waivers(
    league_key: str,
    *,
    inputs_path: str | Path,
    output_path: str | Path | None = None,
    player_cache_path: str | Path = "data/cache/waiver/sleeper/players_nfl.json",
    policy_path: str | Path | None = None,
    config_path: str | Path | None = None,
    client: SleeperClient | None = None,
    now: datetime | None = None,
    enable_pruning: bool = True,
) -> WaiverSearchResult:
    input_check_time = now or datetime.now(timezone.utc)
    input_path = Path(inputs_path)
    inputs = load_waiver_evaluation_inputs(input_path)
    if inputs.league_key != league_key:
        raise ValueError("Waiver search inputs are for a different league")
    if not is_fresh(inputs.captured_at, timedelta(minutes=5), now=input_check_time):
        raise StaleData("Waiver search inputs exceed the five-minute freshness gate")
    policy = _load_policy_for_league(league_key, policy_path, config_path)
    refresh = refresh_waiver_snapshot(
        league_key,
        config_path=config_path,
        player_cache_path=player_cache_path,
        client=client,
        availability_by_player=dict(inputs.availability_by_player),
    )
    evaluation_time = now or datetime.now(timezone.utc)
    search = search_waiver_candidates(
        refresh.snapshot,
        weeks=inputs.weeks,
        projections=inputs.projections,
        values=inputs.values,
        drop_legality=dict(inputs.drop_legality),
        news_fresh=dict(inputs.news_fresh),
        contingencies=inputs.contingencies,
        waiver_wire_evidence=inputs.waiver_wire_evidence,
        emergence_evidence=inputs.emergence_evidence,
        input_bundle_hash=inputs.input_hash,
        availability_source=inputs.availability_source,
        policy=policy,
        enable_pruning=enable_pruning,
        # Evaluate the immutable bundle and refreshed league snapshot at the
        # point when they passed the admission gate. Exhaustive search may run
        # for several minutes, so individual candidates must not acquire
        # different effective timestamps while the search is in progress.
        now=evaluation_time,
    )
    final_check_time = now or datetime.now(timezone.utc)
    if not is_fresh(inputs.captured_at, timedelta(minutes=10), now=final_check_time):
        raise StaleData("Waiver search inputs exceeded the ten-minute completion gate")
    target = Path(
        output_path
        or refresh.output_path.with_name(
            f"waiver_search_{search.evidence_hash[:16]}.json"
        )
    )
    save_waiver_search(search, target)
    return WaiverSearchResult(search, refresh, target, input_path)


def waiver_search_report(result: WaiverSearchResult) -> dict[str, Any]:
    value = json.loads(canonical_json(result.search))
    value["output_path"] = str(result.output_path)
    value["input_path"] = str(result.input_path)
    value["refresh_call_plan"] = waiver_refresh_report(result.refresh)["call_plan"]
    return value


def waiver_search_action_summary(result: WaiverSearchResult) -> str:
    search = result.search
    if search.recommended_action == "NO ACTION" or search.best_add_player_id is None:
        return "NO ACTION"
    names = {
        player.player_id: player.name for player in result.refresh.snapshot.players
    }
    drop = (
        names.get(search.best_drop_player_id, search.best_drop_player_id)
        if search.best_drop_player_id
        else "open roster slot"
    )
    return (
        f"{search.best_decision_label}: add "
        f"{names.get(search.best_add_player_id, search.best_add_player_id)}; drop {drop}"
    )


def _plain_waiver_reason(reason: str) -> str:
    lower = reason.lower()
    if "selected-expert ownership value" in lower:
        return "Trusted experts still value the proposed drop more highly."
    if "market ownership value" in lower:
        return "The broader market still values the proposed drop more highly."
    if "current-week" in lower and "gain" in lower:
        return "The projected improvement this week is too small."
    if "material-news" in lower:
        return "The latest player-news evidence is not complete enough to act."
    return reason.rstrip(".") + "."


def _best_waiver_reason(evaluation: Any, selected: Any) -> str:
    decision = evaluation.decision
    if decision is None:
        return _plain_waiver_reason(evaluation.strongest_uncertainty)
    path = decision.decision_path
    if path == "FRESH_RANK_DOMINANCE":
        return "The add ranks higher this week and for the rest of the season without losing projected value."
    if path == "DST_ROLLING_STREAM":
        return "This defense clears both the current-week and four-week attainable-streamer baselines."
    if path == "DST_STREAM":
        return "This defense supplies the strongest approved current-week streaming gain."
    if path == "K_STREAM":
        return "This kicker supplies the strongest approved current-week streaming gain."
    if path == "IMMEDIATE":
        return "The move improves the usable lineup now and clears the value and safety checks."
    if path in {"INSURANCE", "QB_HOLD", "QB_INJURY_INSURANCE"}:
        return "The move adds useful roster insurance without giving up too much value."
    if path in {"CONTINGENT_UPSIDE", "EMERGING_UPSIDE"}:
        return "The upside case is strong enough to justify the roster change."
    return _plain_waiver_reason(evaluation.strongest_uncertainty)


def _special_team_lines(
    evaluations: Any, names: Mapping[str, str], position: str, limit: int = 3
) -> list[str]:
    ranked = sorted(
        (
            row
            for row in evaluations
            if row.add_position == position and row.candidates
        ),
        key=lambda row: (
            row.candidates[0].ownership.current_week_add_rank or 10_000,
            -(
                row.candidates[0].dst_streaming.current_week_advantage
                if position == "DST" and row.candidates[0].dst_streaming.applicable
                else row.candidates[0].current_week_delta
            ),
            row.add_player_id,
        ),
    )[:limit]
    lines: list[str] = []
    for evaluation in ranked:
        selected = evaluation.candidates[0]
        drop_id = evaluation.selected_drop_player_id
        drop_name = names.get(drop_id, drop_id) if drop_id else "open slot"
        rank = selected.ownership.current_week_add_rank
        label = evaluation.decision_label or "PASS"
        rolling = (
            f" | 4W {selected.dst_streaming.weighted_advantage:+.2f}"
            if position == "DST" and selected.dst_streaming.applicable
            else ""
        )
        lines.append(
            f"- {names.get(evaluation.add_player_id, evaluation.add_player_id)}: "
            f"{position}{rank if rank is not None else '?'} | "
            f"{selected.current_week_add_points:.2f} pts | "
            f"{selected.current_week_delta:+.2f} vs {drop_name}{rolling} | {label}"
        )
    return lines


def format_waiver_search(result: WaiverSearchResult) -> str:
    search = result.search
    names = {
        player.player_id: player.name for player in result.refresh.snapshot.players
    }
    best_evaluation = next(
        (
            row
            for row in search.exact_evaluations
            if row.add_player_id == search.best_add_player_id
            and row.selected_drop_player_id == search.best_drop_player_id
        ),
        None,
    )
    if best_evaluation is None:
        lines = [
            "BEST IDEA",
            "No safe add/drop move was proved.",
            "Why: " + _plain_waiver_reason(search.strongest_uncertainty),
        ]
    else:
        selected = best_evaluation.candidates[0]
        add_name = names.get(best_evaluation.add_player_id, best_evaluation.add_player_id)
        drop_id = best_evaluation.selected_drop_player_id
        drop_name = names.get(drop_id, drop_id) if drop_id else "open roster slot"
        heading = "BEST MOVE" if search.recommended_action != "NO ACTION" else "BEST IDEA — HOLD FOR NOW"
        lines = [
            heading,
            f"{best_evaluation.decision_label}: add {add_name} -> drop {drop_name}",
            "Why: " + _best_waiver_reason(best_evaluation, selected),
            f"This week: projected lineup change {selected.current_week_delta:+.2f} points.",
        ]

    dst_lines = _special_team_lines(search.exact_evaluations, names, "DST")
    if dst_lines:
        lines.extend(("", "DEFENSE STREAMERS", *dst_lines))
    kicker_lines = _special_team_lines(search.exact_evaluations, names, "K")
    if kicker_lines:
        lines.extend(("", "KICKER STREAMERS", *kicker_lines))
    if search.notable_candidates:
        lines.extend(("", "OTHER PLAYERS TO WATCH"))
        for candidate in search.notable_candidates:
            rank_details = []
            if candidate.waiver_wire_position_rank is not None:
                rank_details.append(f"WW {candidate.position}{candidate.waiver_wire_position_rank:g}")
            if candidate.current_week_position_rank is not None:
                rank_details.append(f"W{search.current_week} {candidate.position}{candidate.current_week_position_rank}")
            if candidate.rest_of_season_position_rank is not None:
                rank_details.append(f"ROS {candidate.position}{candidate.rest_of_season_position_rank}")
            team = f" {candidate.nfl_team}" if candidate.nfl_team else ""
            reason = (
                "incomplete value coverage; monitor only"
                if candidate.category == "MISSING_EVIDENCE"
                else "not enough of an upgrade after accounting for the drop"
                if candidate.category == "BELOW_THRESHOLD"
                else "not available in this league"
            )
            lines.append(
                f"- {names.get(candidate.player_id, candidate.player_id)}: "
                f"{candidate.position}{team} | {' | '.join(rank_details) or 'partial ranks'} | {reason}"
            )
    lines.extend(
        (
            "",
            "BEFORE YOU ACT",
            "Confirm free-agent versus waiver status in Sleeper. No bid or claim-success probability is predicted.",
        )
    )
    return "\n".join(lines)


def format_waiver_evaluation(result: EnteredWaiverEvaluationResult) -> str:
    evaluation = result.evaluation
    names = {
        player.player_id: player.name for player in result.refresh.snapshot.players
    }
    selected = evaluation.candidates[0]
    emergence = next(
        (
            row
            for row in (
                evaluation.emergence_evidence.players
                if evaluation.emergence_evidence is not None
                else ()
            )
            if row.player_id == evaluation.add_player_id
        ),
        None,
    )
    drop_name = (
        names.get(evaluation.selected_drop_player_id, evaluation.selected_drop_player_id)
        if evaluation.selected_drop_player_id
        else "no drop (open slot)"
    )
    emerging_gate = (
        next(
            (
                gate
                for gate in evaluation.decision.gates
                if gate.name == "waiver_wire_support"
            ),
            None,
        )
        if evaluation.decision is not None
        else None
    )
    emerging_value = selected.emerging_upside
    lines = [
        f"WAIVER ASSISTANT - {evaluation.league_key} - Weeks "
        f"{evaluation.horizon[0]}-{evaluation.horizon[-1]}",
        f"Decision: {evaluation.decision_label or 'NO LABEL'} "
        f"({evaluation.policy_version or 'no policy'})",
        f"Add: {names.get(evaluation.add_player_id, evaluation.add_player_id)} "
        f"({evaluation.acquisition_state}); drop: {drop_name}",
        f"Lineup {selected.lineup.weighted_delta:+.2f}; current week "
        f"{selected.current_week_delta:+.2f}; depth {selected.lineup.depth_delta:+.2f}; "
        f"playoffs {selected.lineup.playoff_delta:+.2f}",
        f"Selected ownership {selected.ownership.selected_delta:+.2f}; market "
        f"{selected.ownership.market_delta:+.2f}; raw projection "
        f"{selected.ownership.raw_projection_delta:+.2f}",
        "FantasyPros Waiver Wire market overall rank (acquisition only): "
        + (
            str(selected.ownership.waiver_wire_market_add_rank)
            if selected.ownership.waiver_wire_market_add_rank is not None
            else "unavailable (not blended)"
        ),
        "FantasyPros Waiver Wire trusted-expert ranks (acquisition only): "
        + (
            ", ".join(
                f"{row.expert_id}=overall {row.overall_rank if row.overall_rank is not None else 'unavailable'}"
                f"/position {row.position_rank if row.position_rank is not None else 'unavailable'}"
                for row in selected.ownership.waiver_wire_selected_add_ranks
            )
            or "unavailable (not blended)"
        ),
        "Role/volume emergence evidence: "
        + (
            f"{emergence.classification}; normalized signal strength "
            f"{emerging_role_signal_strength(emergence):.3f}; affirmative eligible "
            f"{str(emergence.affirmative_eligible).lower()}"
            if emergence is not None
            else "unavailable"
        ),
        "Emerging Waiver Wire support: "
        + (
            f"{'passed' if emerging_gate.passed else 'failed'}; "
            f"{emerging_gate.explanation}"
            if emerging_gate is not None
            else "not the selected decision path; market and selected-expert ranks remain separate above"
        ),
        "Emerging-upside valuation: "
        + (
            f"breakout {emerging_value.breakout_gain:+.2f}; "
            f"useful role {emerging_value.useful_role_gain:+.2f}; "
            f"miss loss {emerging_value.miss_case_loss:+.2f}; "
            f"acquisition ceiling {emerging_value.acquisition_option_ceiling:.2f}; "
            f"retained-drop ceiling {emerging_value.retained_option_ceiling:.2f}; "
            f"incremental option {emerging_value.incremental_option_value:+.2f}; "
            "break-even "
            + (
                f"{emerging_value.break_even.hit_rate:.1%}"
                if emerging_value.break_even.hit_rate is not None
                else emerging_value.break_even.status
            )
            if emerging_value.status == "COMPLETE"
            else emerging_value.status
        ),
        f"Policy path: {evaluation.decision.decision_path if evaluation.decision else 'none'}; "
        f"gates passed: "
        f"{sum(gate.passed for gate in evaluation.decision.gates) if evaluation.decision else 0}/"
        f"{len(evaluation.decision.gates) if evaluation.decision else 0}",
        "Waiver context: priority "
        f"{evaluation.user_waiver_position if evaluation.user_waiver_position is not None else 'unavailable'}; "
        "budget used "
        f"{evaluation.user_waiver_budget_used if evaluation.user_waiver_budget_used is not None else 'unavailable'}"
        f"/{evaluation.user_waiver_budget_total if evaluation.user_waiver_budget_total is not None else 'unavailable'} "
        "(no bid or claim probability generated)",
        "Added player starts: "
        + (", ".join(f"W{week}" for week in selected.added_start_weeks) or "no projected weeks"),
        f"Drop candidates evaluated: {len(evaluation.candidates)}; exclusions: "
        f"{len(evaluation.exclusions)}",
        "Strongest uncertainty: " + evaluation.strongest_uncertainty,
        f"Saved evidence: {result.output_path}",
    ]
    replacement_weeks = tuple(
        row
        for row in selected.lineup.weeks
        if row.before_replacements or row.after_replacements
    )
    if replacement_weeks:
        lines.insert(
            3,
            "Bye/inactive waiver floor (evaluated add excluded from its own baseline): "
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
            ),
        )
    if emerging_value.status == "COMPLETE":
        scenario_lines = []
        for comparison in emerging_value.scenario_comparisons:
            starts = ", ".join(
                f"W{week}" for week in comparison.act_now.starter_weeks
            ) or "none"
            scenario_lines.append(
                f"Emerging state {comparison.state}: ACT_NOW minus RETAIN_DROP "
                f"{comparison.act_now_minus_retain_drop:+.2f}; add starts {starts}; "
                f"replacement exposure {comparison.act_now.replacement_exposure:.2f}"
            )
        lines[11:11] = scenario_lines
        lines.insert(
            11 + len(scenario_lines),
            "Emerging break-even interpretation: "
            + emerging_value.break_even.explanation,
        )
    if evaluation.decision and evaluation.decision.reversal_conditions:
        lines.insert(
            -2,
            "Reversal conditions: "
            + " | ".join(evaluation.decision.reversal_conditions),
        )
    if evaluation.add_position in {"K", "DST"}:
        drop_id = evaluation.selected_drop_player_id
        drop_name = names.get(drop_id, drop_id) if drop_id else "open roster slot"
        lines.insert(
            6,
            "Special-team ranks: Week "
            + (
                str(selected.ownership.current_week_add_rank)
                if selected.ownership.current_week_add_rank is not None
                else "unavailable"
            )
            + "; ROS "
            + (
                str(selected.ownership.rest_of_season_add_rank)
                if selected.ownership.rest_of_season_add_rank is not None
                else "unavailable"
            )
            + "; rolling DST guard "
            + ("active" if evaluation.add_position == "DST" else "not applicable"),
        )
        if evaluation.add_position == "DST":
            drop_points = (
                f"{selected.current_week_drop_points:.2f} projected points"
                if selected.current_week_drop_points is not None
                else "no incumbent projection"
            )
            lines.insert(
                7,
                f"DST stream: {names.get(evaluation.add_player_id, evaluation.add_player_id)} "
                f"{selected.current_week_add_points:.2f} projected points "
                f"(DST{selected.ownership.current_week_add_rank or '?'}) vs "
                f"{drop_name} {drop_points} "
                f"(DST{selected.ownership.current_week_drop_rank or '?'}); "
                f"lineup gain {selected.current_week_delta:+.2f}",
            )
            if selected.dst_streaming.applicable:
                lines.insert(
                    8,
                    "DST rolling value: weighted target "
                    f"{selected.dst_streaming.weighted_target_points:.2f} vs attainable "
                    f"baseline {selected.dst_streaming.weighted_baseline_points:.2f}; "
                    f"advantage {selected.dst_streaming.weighted_advantage:+.2f}; "
                    "weeks "
                    + ", ".join(
                        f"W{row.week} {row.target_advantage:+.2f}×{row.weight:g}"
                        for row in selected.dst_streaming.weeks
                    ),
                )
    if selected.holding.applicable:
        lines.insert(
            6,
            "QB hold: streamer replacement "
            f"{selected.holding.streaming_replacement_value:.2f}; holding period "
            f"{selected.holding.holding_period} weeks; bench cost "
            f"{selected.holding.bench_slot_opportunity_cost:.2f}; net hold "
            f"{selected.holding.net_hold_value:+.2f}",
        )
        lines.insert(
            7,
            "QB hold roles: bye coverage "
            f"{selected.holding.required_bye_coverage_value:+.2f} "
            f"({', '.join(f'W{week}' for week in selected.holding.required_bye_weeks) or 'none'}); "
            f"discretionary {selected.holding.discretionary_start_value:+.2f}; "
            f"injury-insurance scenario {selected.holding.injury_insurance_value:+.2f}; "
            f"unused {len(selected.holding.unused_weeks)} weeks",
        )
    contingency = selected.contingency
    if (
        contingency.add.evidence_status != "NOT_PROVIDED"
        or contingency.drop is not None
        and contingency.drop.evidence_status != "NOT_PROVIDED"
    ):
        lines.insert(
            6,
            "Contingent option: retained "
            f"{contingency.retained_option_ceiling:.2f}; acquisition "
            f"{contingency.acquisition_option_ceiling:.2f}; incremental "
            f"{contingency.incremental_option_value:+.2f}; gate "
            f"{'passed' if contingency.incremental_gate_passed else 'failed'}; "
            f"add protected {str(contingency.add_protected).lower()}; drop protected "
            f"{str(contingency.drop_protected).lower()}",
        )
        for label, evidence in (
            ("add", contingency.add),
            ("drop", contingency.drop),
        ):
            if evidence is not None and evidence.evidence_status != "NOT_PROVIDED":
                lines.insert(
                    7,
                    f"Contingency {label}: {evidence.evidence_status}; role expansion "
                    f"{evidence.role_expansion_weighted_points:+.2f}; lineup ceiling "
                    f"{evidence.lineup_ceiling_gain:+.2f}; scenario depth "
                    f"{evidence.scenario_depth_above_waiver:.2f}; replacement exposure "
                    f"{evidence.replacement_exposure:.2f}",
                )
    return "\n".join(lines)
