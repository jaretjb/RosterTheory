"""Waiver-owned historical selection, contributor reconciliation and ranking."""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
from math import isfinite
from pathlib import Path
from typing import Any, Mapping, Sequence

from roster_theory.application.value_preparation import ExpertPoolMember, ExpertPoolResolution
from roster_theory.core.call_plan import PlannedCall
from roster_theory.core.errors import CoverageIncomplete
from roster_theory.core.models import RankObservation
from roster_theory.core.provenance import stable_hash
from roster_theory.inseason.boards import SelectedRank
from roster_theory.inseason.horizons import filter_ros_ballots
from roster_theory.providers.cache import atomic_write_json, cache_key
from roster_theory.providers.expert_accuracy import (
    annual_accuracy_from_directory, load_weekly_accuracy_history, write_weekly_accuracy_history,
)
from roster_theory.providers.fantasypros import normalize_rankings
from roster_theory.providers.formats import validate_provider_scope
from roster_theory.providers.inseason_experts import normalize_current_experts
from roster_theory.storage.request_gate import pace_request, reserve_requests
from roster_theory.waiver.ww_evidence import _provider_updated_at, _provider_update_is_date


HISTORY_SHARES = (0.08, 0.15, 0.21, 0.26, 0.30)
PREFERRED_SIZE = 3
MINIMUM_SIZE = 2
MAXIMUM_SOURCE_COUNT = 2


def historical_scores(rows, years):
    shares = dict(zip(years, HISTORY_SHARES))
    grouped = defaultdict(list)
    for row in rows:
        if row.year in shares:
            grouped[row.expert_id].append(row)
    result = {}
    for expert_id, observations in grouped.items():
        observations.sort(key=lambda row: row.year)
        coverage = 0.80 + 0.20 * len(observations) / 5
        total = sum(shares[row.year] for row in observations)
        percentile = sum(shares[row.year] * (1 - (row.overall_rank - 1) /
                         (row.field_size - 1)) for row in observations) / total
        result[expert_id] = {"score": percentile * coverage,
            "historical_expert_name": observations[-1].expert_name,
            "historical_source_name": observations[-1].source_name,
            "historical_coverage": coverage, "seasons": len(observations),
            "annual_ranks": [[row.year, row.overall_rank] for row in observations],
            "eligible": len(observations) >= 2 and percentile > 0}
    return result


def publication_issue(expert, position, now, maximum_age):
    update = dict(expert.position_updates).get(position)
    if not update:
        return "missing_position_update"
    try:
        stamp = _provider_updated_at(update, now)
        if stamp is None:
            return "invalid_position_update"
        age = now - stamp
    except (ValueError, TypeError):
        return "invalid_position_update"
    # Provider date-only publications describe a calendar day, not midnight.
    if _provider_update_is_date(update):
        age = timedelta(days=(now.date() - stamp.date()).days)
    return "future_position_update" if age < timedelta(0) else (
        "stale_position_update" if age > maximum_age else None)


def select_position_panel(*, experts, scores, published_ids, position, now,
                          horizon, advertised_ids=(), failure_reasons=None):
    by_id = {}
    for expert in experts:
        if expert.expert_id in by_id:
            raise CoverageIncomplete("Expert directory contains duplicate identities")
        by_id[expert.expert_id] = expert
    audit, eligible = [], []
    for expert_id in sorted(set(by_id) | set(advertised_ids) | set(scores)):
        expert, history = by_id.get(expert_id), scores.get(expert_id)
        reason = "missing_current_expert_directory_identity" if expert is None else (
            "insufficient_historical_accuracy" if not history or not history["eligible"] else
            publication_issue(expert, position, now,
                              timedelta(days=14) if horizon == "ROS" else timedelta(days=7)))
        if not reason and expert_id not in published_ids:
            reason = (failure_reasons or {}).get(expert_id, "missing_position_ballot")
        elif reason == "missing_position_update" and expert_id in (failure_reasons or {}):
            reason = failure_reasons[expert_id]
        row = {"expert_id": expert_id, "expert_name": expert.name if expert else
               (history or {}).get("historical_expert_name"),
               "source_name": expert.source_name if expert else None,
               "position": position, "horizon": horizon,
               "position_update": dict(expert.position_updates).get(position) if expert else None,
               "advertised": expert_id in set(advertised_ids),
               "ballot_available": expert_id in published_ids,
               **(history or {}), "status": "excluded" if reason else "eligible",
               "reason": reason or "eligible"}
        audit.append(row)
        if not reason:
            eligible.append((float(history["score"]), expert, row))
    selected, source_counts = [], defaultdict(int)
    for score, expert, row in sorted(eligible, key=lambda item: (-item[0], item[1].expert_id)):
        source = expert.source_name.casefold()
        if len(selected) >= PREFERRED_SIZE:
            row.update(status="excluded", reason="below_selection_cutoff")
        elif source_counts[source] >= MAXIMUM_SOURCE_COUNT:
            row.update(status="excluded", reason="source_concentration_limit")
        else:
            selected.append((score, expert, row))
            source_counts[source] += 1
    total = sum(score for score, _, _ in selected)
    members = tuple(ExpertPoolMember(expert.expert_id, expert.name, expert.source_name,
                                    score / total) for score, expert, _ in selected)
    for member in members:
        next(row for row in audit if row["expert_id"] == member.expert_id).update(
            status="selected", reason="historical_accuracy_selection", weight=member.weight)
    return members, {"horizon": horizon, "position": position,
                     "status": "READY" if len(members) == PREFERRED_SIZE else
                     "DEGRADED" if len(members) >= MINIMUM_SIZE else "UNAVAILABLE",
                     "members": [asdict(member) for member in members], "candidates": audit}


def strict_selected_ranks(market, ballots, weights, *, horizon, minimum_size=MINIMUM_SIZE):
    """Use only selected ballots; missing players never receive a market anchor."""
    grouped = defaultdict(dict)
    for row in ballots:
        weight = weights.get(row.position, {}).get(str(row.expert_id))
        rank = row.position_rank
        if (weight and row.horizon == horizon and isinstance(rank, (int, float))
                and not isinstance(rank, bool) and isfinite(rank) and rank > 0):
            key = str(row.expert_id)
            prior = grouped[(row.position, row.player_id)].get(key)
            if prior is not None and prior != rank:
                raise CoverageIncomplete("Conflicting individual expert player ballots")
            grouped[(row.position, row.player_id)][key] = float(rank)
    result = []
    for position in sorted({row.position for row in market}):
        observations = []
        panel = weights.get(position, {})
        for row in market:
            if row.position != position:
                continue
            ranks = grouped[(position, row.player_id)]
            if len(ranks) < minimum_size:
                continue
            present = sum(panel[expert_id] for expert_id in ranks)
            average = sum(panel[expert_id] * rank for expert_id, rank in ranks.items()) / present
            observations.append((average, row.player_id, row, ranks, present))
        for ordinal, (average, player_id, row, ranks, present) in enumerate(
                sorted(observations, key=lambda item: (item[0], item[1])), 1):
            result.append(SelectedRank(player_id=player_id, position=position,
                raw_position_rank=average, raw_overall_rank=None,
                final_position_rank=ordinal, final_overall_rank=None,
                market_position_rank=int(row.position_rank), market_overall_rank=None,
                dispersion=(sum(panel[e] * (rank - average) ** 2 for e, rank in ranks.items())
                            / present) ** 0.5,
                contributor_weight=present,
                contributions=tuple((e, ranks[e], panel[e]) for e in sorted(ranks)),
                omissions=tuple((e, "missing_player_ballot") for e in sorted(panel) if e not in ranks),
                shrinkage_to_ecr=0.0))
    return tuple(sorted(result, key=lambda row: row.player_id))


class WaiverExpertPreparation:
    """Prepare a history-weighted panel per horizon/position for one immutable run."""

    def __init__(self, league_key, *, history_path=None):
        self.league_key, self.history_path = league_key, history_path
        self.panels = {}
        self.evidence = {}
        self.calls, self.sources = [], []
        self.current_week = None
        self.current_identities = {}
        self.scores = {}

    def _request(self, client, season, endpoint, params, cache_dir, budget_path, now):
        path = cache_dir / f"{cache_key(endpoint, params)}.json"
        record = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None
        captured = datetime.fromisoformat(record["captured_at"]) if record else None
        fresh = bool(captured and timedelta(0) <= now - captured <= timedelta(hours=2))
        if not fresh:
            reserve_requests(budget_path, 1)
            pace_request(budget_path)
            payload = client.get(endpoint, params)
            record = {"captured_at": now.isoformat(), "payload": payload}
            atomic_write_json(path, record)
        self.calls.append(PlannedCall(name=f"waiver_experts_{len(self.calls)}", provider="FantasyPros",
                          endpoint=endpoint, parameters=tuple(sorted(params.items())), fresh_cache_hit=fresh))
        self.sources.append({"name": f"Waiver expert source {len(self.sources)}", "endpoint": endpoint,
            "parameters": params, "captured_at": record["captured_at"],
            "payload_hash": stable_hash(record["payload"]), "maximum_age_seconds": 7200})
        return record["payload"]

    def prepare_inputs(self, inputs, snapshot, client, cache_dir, budget_path, now):
        season, week = snapshot.league.season, snapshot.manifest.current_week
        self.current_week = week
        years = tuple(range(season - 5, season))
        path = self.history_path or Path(f"data/manual/fantasypros/inseason_accuracy_{years[0]}_{years[-1]}.csv")
        evidence_dir = Path(f"data/cache/fantasypros/{season}/expert_evidence")
        try:
            rows, history_evidence = load_weekly_accuracy_history(path, years, evidence_dir=evidence_dir)
        except CoverageIncomplete as original:
            history = []
            for year in reversed(years):
                endpoint = f"/nfl/{year}/rankings/experts"
                payload = self._request(client, year, endpoint,
                    {"ranking_type": "weekly", "details": "experts", "include_overall": "true"},
                    cache_dir, budget_path, now)
                try:
                    history.extend(annual_accuracy_from_directory(payload, year,
                        source_url=f"https://api.fantasypros.com/public/v2/json{endpoint}",
                        public_evidence=evidence_dir / f"inseason_accuracy_{year}.json"))
                except CoverageIncomplete as failure:
                    audit = Path("data/exports/waiver") / self.league_key / "expert_history_unavailable.json"
                    atomic_write_json(audit, {"status": "UNAVAILABLE", "local_issue": str(original),
                        "provider_issue": str(failure), "sources": self.sources, "years": list(years)})
                    raise CoverageIncomplete(f"{failure}; history audit: {audit}") from failure
            write_weekly_accuracy_history(path, history)
            rows, history_evidence = load_weekly_accuracy_history(path, years, evidence_dir=evidence_dir)
        scores = historical_scores(rows, years)
        self.scores = scores
        self.evidence = {"schema_version": "roster-theory.waiver-expert-selection/v2",
            "product": "WAIVER ASSISTANT", "league_key": self.league_key,
            "selected_at": now.isoformat(), "selection_method": "five_season_recency_weighted_accuracy",
            "accuracy_weights": {str(year): share for year, share in zip(years, HISTORY_SHARES)},
            "accuracy_authority": "weekly_inseason", "ros_accuracy_is_proxy": True,
            "weighting_method": "historical_percentile_with_coverage_and_source_cap",
            "history": history_evidence, "preferred_size": PREFERRED_SIZE,
            "minimum_size": MINIMUM_SIZE, "panels": {}, "sleeper_write_performed": False}
        prepared = {}
        ros_experts = inputs.current_experts
        for horizon, datasets in (("WEEKLY", inputs.weekly_rankings), ("ROS", inputs.ros_rankings)):
            params = {"ranking_type": "weekly" if horizon == "WEEKLY" else "ros",
                      "details": "experts", "include_overall": "true"}
            payload = self._request(client, season, f"/nfl/{season}/rankings/experts", params,
                                    cache_dir, budget_path, now)
            if int(payload.get("season", season)) != season:
                raise CoverageIncomplete("Expert directory returned a different season")
            experts = normalize_current_experts(payload)
            if horizon == "WEEKLY":
                self.current_identities = {e.expert_id: e for e in experts}
            else:
                # Directory membership can differ by horizon. Reuse only known
                # current identity/source facts, never another horizon's dates
                # or votes. A missing ROS contributor needs a verified ROS
                # individual response before its position becomes eligible.
                current = {e.expert_id: e for e in experts}
                absent = sorted(set(self.current_identities) - set(current))
                current.update({i: replace(self.current_identities[i], position_updates=()) for i in absent})
                experts = tuple(current.values())
                self.evidence["ros_identity_reconciliation"] = {"additional_identity_ids": absent,
                    "publication_inferred": False}
            if horizon == "ROS":
                ros_experts = experts
            augmented = []
            effective_updates = {(e.expert_id, p): value for e in experts for p, value in e.position_updates}
            for dataset in datasets:
                positions = {row.position for row in dataset.observations}
                if len(positions) != 1:
                    raise CoverageIncomplete("Waiver position feed must declare exactly one position")
                position = next(iter(positions))
                # K/DST keep their separate forecast/production decision rules,
                # but their rank evidence uses the same historical authority.
                advertised = set(dataset.contributor_ids)
                ballots = list(dataset.contributor_observations) if dataset.complete_horizon else []
                published = {str(row.expert_id) for row in ballots if row.position == position
                             and row.horizon == horizon and row.position_rank is not None}
                failures = {}
                # Reconcile directory contributors against actual ballots. Fetch
                # missing historical candidates in score order; do not fetch the
                # whole directory or interpret advertised membership as a vote.
                potential = sorted((e for e in experts if scores.get(e.expert_id, {}).get("eligible")
                    and publication_issue(e, position, now,
                        timedelta(days=14) if horizon == "ROS" else timedelta(days=7))
                        in {None, "missing_position_update"}),
                    key=lambda e: (-scores[e.expert_id]["score"], e.expert_id))
                for expert in potential:
                    provisional, _ = select_position_panel(experts=experts, scores=scores,
                        published_ids=published, position=position, now=now, horizon=horizon,
                        advertised_ids=advertised, failure_reasons=failures)
                    threshold = min((scores[m.expert_id]["score"] for m in provisional), default=-1)
                    if len(provisional) >= PREFERRED_SIZE and scores[expert.expert_id]["score"] < threshold:
                        break
                    if expert.expert_id in published:
                        continue
                    request = {"position": position, "scoring": dataset.scoring,
                               "filters": expert.expert_id, "experts": "show"}
                    request.update({"type": "ROS"} if horizon == "ROS" else {"week": week})
                    raw = self._request(client, season, f"/nfl/{season}/consensus-rankings", request,
                                        cache_dir, budget_path, now)
                    validate_provider_scope(raw, season=season, scoring=dataset.scoring)
                    single = normalize_rankings(raw, requested_horizon=horizon, board_source="selected",
                        expert_id=expert.expert_id, captured_at=now, parameters=request)
                    actual_ids = set(single.contributor_ids)
                    if not single.observations and not actual_ids:
                        failures[expert.expert_id] = "missing_position_ballot"
                    elif actual_ids != {expert.expert_id}:
                        failures[expert.expert_id] = "expert_filter_not_honored"
                    elif not single.complete_horizon or (horizon == "WEEKLY" and single.week != week):
                        failures[expert.expert_id] = "wrong_or_partial_ballot_horizon"
                    else:
                        update = single.updated_at or dict(expert.position_updates).get(position)
                        stamp = _provider_updated_at(update, now)
                        if stamp is not None:
                            update = stamp.date().isoformat() if _provider_update_is_date(update) else stamp.isoformat()
                        if not update:
                            failures[expert.expert_id] = "missing_individual_ballot_update"
                        elif publication_issue(replace(expert, position_updates=((position, update),)),
                                position, now, timedelta(days=14) if horizon == "ROS" else timedelta(days=7)):
                            failures[expert.expert_id] = "stale_individual_ballot"
                        else:
                            admitted = [replace(row, board_source="expert_ballot") for row in single.observations
                                        if row.position == position and row.position_rank is not None]
                            if admitted:
                                ballots.extend(admitted)
                                published.add(expert.expert_id)
                                if update:
                                    effective_updates[(expert.expert_id, position)] = update
                                    revised = dict(expert.position_updates)
                                    revised[position] = update
                                    experts = tuple(replace(e, position_updates=tuple(sorted(revised.items())))
                                                    if e.expert_id == expert.expert_id else e for e in experts)
                                dataset = replace(dataset, identities=(*dataset.identities, *single.identities))
                            else:
                                failures[expert.expert_id] = "missing_position_ballot"
                members, evidence = select_position_panel(experts=experts, scores=scores,
                    published_ids=published, position=position, now=now, horizon=horizon,
                    advertised_ids=advertised, failure_reasons=failures)
                self.panels[(horizon, position)] = members
                self.evidence["panels"][f"{horizon}:{position}"] = evidence
                selected_ids = {m.expert_id for m in members}
                selected_ballots = tuple(row for row in ballots if str(row.expert_id) in selected_ids)
                freshness = filter_ros_ballots(selected_ballots, effective_updates, inputs.news,
                    now=now, maximum_age=timedelta(days=14) if horizon == "ROS" else timedelta(days=7),
                    expected_horizon=horizon)
                evidence["ballot_exclusions"] = [asdict(row) for row in freshness.exclusions]
                augmented.append(replace(dataset, contributor_observations=freshness.eligible))
            prepared[horizon] = tuple(augmented)
            if horizon == "ROS":
                ros_experts = tuple(replace(e, position_updates=tuple((p, effective_updates[(e.expert_id, p)])
                    for p, _ in e.position_updates)) for e in experts)
        self.evidence["status"] = "READY" if all(p["status"] == "READY" for p in
                self.evidence["panels"].values()) and history_evidence["population_complete"] else "DEGRADED"
        for horizon in prepared:
            if horizon == "ROS" and week < 2:
                self.evidence["ros_availability"] = "UNPUBLISHED_IN_WEEK_ONE"
                continue
            for position in ("QB", "RB", "WR", "TE"):
                if len(self.panels.get((horizon, position), ())) < MINIMUM_SIZE:
                    audit_path = Path("data/exports/waiver") / self.league_key / "expert_selection_unavailable.json"
                    atomic_write_json(audit_path, self.evidence)
                    raise CoverageIncomplete(f"{horizon} {position} has fewer than {MINIMUM_SIZE} historically "
                        f"qualified published experts; audit: {audit_path}")
        history_stamp = {"name": "Waiver historical weekly accuracy", "captured_at": now.isoformat(),
                         "payload_hash": history_evidence["payload_hash"], "maximum_age_seconds": 86400}
        paid = sum(not call.fresh_cache_hit for call in self.calls)
        return replace(inputs, weekly_rankings=prepared["WEEKLY"], ros_rankings=prepared["ROS"],
            current_experts=ros_experts, source_evidence=(*inputs.source_evidence, history_stamp, *self.sources),
            call_plan=replace(inputs.call_plan, calls=(*inputs.call_plan.calls, *self.calls),
                fantasypros_calls=inputs.call_plan.fantasypros_calls + paid,
                required_calls=inputs.call_plan.required_calls + len(self.calls),
                cache_hits=inputs.call_plan.cache_hits + len(self.calls) - paid,
                fantasypros_remaining_after_plan=inputs.call_plan.fantasypros_remaining_after_plan - paid))

    def __call__(self, inputs, now):
        horizon_scope = "ROS" if self.current_week is None or self.current_week >= 2 else "WEEKLY"
        union = {m.expert_id: m for (horizon, _), members in self.panels.items()
                 if horizon == horizon_scope for m in members}
        total = sum(self.scores[m.expert_id]["score"] for m in union.values())
        members = tuple(replace(m, weight=self.scores[m.expert_id]["score"] / total)
                        for m in union.values())
        self.evidence["members"] = [asdict(m) for m in members]
        self.evidence["member_weight_scope"] = "union_identity_list; rank weights are recorded per panel"
        return ExpertPoolResolution(members, self.evidence)

    def aggregate_ros(self, market, ballots, weights, *, horizon):
        position_weights = {p: {m.expert_id: m.weight for m in members}
                            for (h, p), members in self.panels.items() if h == "ROS"}
        selected = strict_selected_ranks(market, ballots, position_weights, horizon=horizon)
        self.evidence["ros_player_exclusions"] = sorted(
            {row.player_id for row in market} - {row.player_id for row in selected})
        return selected

    def aggregate_weekly(self, market, ballots):
        weights = {p: {m.expert_id: m.weight for m in members}
                   for (h, p), members in self.panels.items() if h == "WEEKLY"}
        # Shared preparation retags canonical weekly observations WEEKLY-PROXY;
        # this is still the active-week ballot, never a ROS ranking.
        horizon = market[0].horizon if market else "WEEKLY"
        selected = strict_selected_ranks(market, ballots, weights, horizon=horizon)
        market_by_id = {row.player_id: row for row in market}
        self.evidence["weekly_player_exclusions"] = sorted(set(market_by_id) - {r.player_id for r in selected})
        return tuple(replace(market_by_id[row.player_id], position_rank=row.final_position_rank,
                             overall_rank=None, tier=None,
                             rank_min=min(rank for _, rank, _ in row.contributions),
                             rank_max=max(rank for _, rank, _ in row.contributions), rank_std=row.dispersion,
                             board_source="historical_selected_experts") for row in selected)
