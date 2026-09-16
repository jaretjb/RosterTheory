from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any, Iterable


CORE_POSITIONS = ("QB", "RB", "WR", "TE", "K", "DST")
MARKET_POSITION_PRIOR = {"QB": 0.13, "RB": 0.31, "WR": 0.33, "TE": 0.10, "K": 0.065, "DST": 0.065}
ACQUISITION_POSITIONS = ("QB", "RB", "WR", "TE")


@dataclass(frozen=True, slots=True)
class HistoricalPositionCurves:
    """Equal-weight positional-slot pick targets from linked historical drafts."""

    position_picks: dict[str, tuple[float, ...]]
    draft_end_pick: float | None
    source: str | None
    issues: tuple[str, ...] = ()
    sources: tuple[str, ...] = ()
    excluded_user_ids: tuple[str, ...] = ()
    exclusion_audit: tuple[dict[str, Any], ...] = ()

    @property
    def available(self) -> bool:
        return self.draft_end_pick is not None and self.source is not None

    def metadata(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "source": self.source,
            "sources": list(self.sources),
            "draft_count": len(self.sources) or int(self.available),
            "draft_end_pick": self.draft_end_pick,
            "position_pick_counts": {
                position: len(self.position_picks.get(position, ()))
                for position in ACQUISITION_POSITIONS
            },
            "issues": list(self.issues),
            "excluded_user_ids": list(self.excluded_user_ids),
            "exclusion_audit": [dict(row) for row in self.exclusion_audit],
        }


def pick_position(pick: dict[str, Any]) -> str:
    metadata = pick.get("metadata") or {}
    position = str(metadata.get("position") or "UNKNOWN").upper()
    return "DST" if position == "DEF" else position


def player_name(pick: dict[str, Any]) -> str:
    metadata = pick.get("metadata") or {}
    name = f"{metadata.get('first_name', '')} {metadata.get('last_name', '')}".strip()
    return name or str(pick.get("player_id") or "Unknown")


def detect_position_runs(
    picks: list[dict[str, Any]], window: int = 5, threshold: int = 3
) -> list[dict[str, Any]]:
    if window < 2 or threshold < 2 or threshold > window:
        raise ValueError("Position-run window and threshold are invalid")
    ordered = sorted(picks, key=lambda pick: int(pick.get("pick_no", 0)))
    runs: list[dict[str, Any]] = []
    seen: set[tuple[int, str]] = set()
    for index in range(0, max(0, len(ordered) - window + 1)):
        segment = ordered[index : index + window]
        counts = Counter(pick_position(pick) for pick in segment)
        for position, count in counts.items():
            if position in CORE_POSITIONS and count >= threshold:
                signature = (int(segment[0].get("pick_no", 0)), position)
                if signature not in seen:
                    seen.add(signature)
                    runs.append(
                        {
                            "position": position,
                            "start_pick": segment[0].get("pick_no"),
                            "end_pick": segment[-1].get("pick_no"),
                            "count": count,
                        }
                    )
    return runs


def analyze_draft(
    picks: Iterable[dict[str, Any]], users: Iterable[dict[str, Any]] = ()
) -> dict[str, Any]:
    ordered = sorted(picks, key=lambda pick: int(pick.get("pick_no", 0)))
    user_names = {
        str(user.get("user_id")): str(user.get("display_name") or user.get("username") or user.get("user_id"))
        for user in users
    }
    by_round: dict[int, Counter[str]] = defaultdict(Counter)
    by_manager: dict[str, Counter[str]] = defaultdict(Counter)
    first_pick: dict[str, int] = {}

    for pick in ordered:
        position = pick_position(pick)
        round_no = int(pick.get("round") or 0)
        pick_no = int(pick.get("pick_no") or 0)
        manager_id = str(pick.get("picked_by") or pick.get("roster_id") or "unknown")
        by_round[round_no][position] += 1
        by_manager[manager_id][position] += 1
        first_pick[position] = min(first_pick.get(position, pick_no), pick_no)

    manager_summary = []
    for manager_id, counts in sorted(by_manager.items()):
        early = Counter(
            pick_position(pick)
            for pick in ordered
            if str(pick.get("picked_by") or pick.get("roster_id") or "unknown") == manager_id
            and int(pick.get("round") or 0) <= 5
        )
        manager_summary.append(
            {
                "manager_id": manager_id,
                "manager": user_names.get(manager_id, manager_id),
                "position_counts": dict(counts),
                "early_round_counts": dict(early),
            }
        )

    return {
        "pick_count": len(ordered),
        "position_counts": dict(Counter(pick_position(pick) for pick in ordered)),
        "position_by_round": {
            str(round_no): dict(counts) for round_no, counts in sorted(by_round.items())
        },
        "first_position_pick": dict(sorted(first_pick.items())),
        "position_runs": detect_position_runs(ordered),
        "managers": manager_summary,
    }


def analyze_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    analyses: list[dict[str, Any]] = []
    for bundle in snapshot.get("history", []):
        users = bundle.get("users", [])
        league = bundle.get("league", {})
        for draft_bundle in bundle.get("drafts", []):
            draft = draft_bundle.get("draft", {})
            analyses.append(
                {
                    "league_id": league.get("league_id"),
                    "league_name": league.get("name"),
                    "season": draft.get("season"),
                    "draft_id": draft.get("draft_id"),
                    "team_count": draft.get("settings", {}).get("teams"),
                    "analysis": analyze_draft(draft_bundle.get("picks", []), users),
                }
            )
    return {"league_key": snapshot.get("config", {}).get("key"), "drafts": analyses}


def historical_position_pick_curves(
    snapshot: dict[str, Any],
    *,
    excluded_user_ids: Iterable[str] = (),
) -> HistoricalPositionCurves:
    """Average positional pick slots across each linked league's newest draft.

    Player identity is deliberately ignored. The current kth player at a
    position maps to the equal-weight mean kth selection across linked drafts.
    If a draft did not select that many players at the position, its draft-end
    plus one is included as a censored observation for that slot.

    When manager IDs are excluded, every selected historical draft must be
    complete and contain exactly one full draft's picks for every excluded
    manager. Their picks are removed and the retained picks are renumbered in
    original order, producing an explicitly counterfactual smaller-room curve.
    """

    normalized_excluded_ids = tuple(
        dict.fromkeys(str(user_id).strip() for user_id in excluded_user_ids)
    )
    if any(not user_id for user_id in normalized_excluded_ids):
        raise ValueError("Excluded historical manager IDs cannot be blank")

    issues: list[str] = []
    bundle_candidates: list[
        list[
            tuple[
                str,
                str,
                dict[str, Any],
                list[dict[str, Any]],
                list[dict[str, Any]],
                list[dict[str, Any]],
                str,
            ]
        ]
    ] = []
    history = snapshot.get("history")
    if not isinstance(history, list) or not history:
        return HistoricalPositionCurves(
            position_picks={},
            draft_end_pick=None,
            source=None,
            issues=("No linked historical drafts are available; raw ADP will be used.",),
            excluded_user_ids=normalized_excluded_ids,
        )

    for bundle_index, bundle in enumerate(history):
        if not isinstance(bundle, dict):
            issues.append(f"Historical bundle {bundle_index + 1} is malformed.")
            continue
        drafts = bundle.get("drafts")
        if not isinstance(drafts, list):
            issues.append(f"Historical bundle {bundle_index + 1} has no valid drafts list.")
            continue
        candidates: list[
            tuple[
                str,
                str,
                dict[str, Any],
                list[dict[str, Any]],
                list[dict[str, Any]],
                list[dict[str, Any]],
                str,
            ]
        ] = []
        users = bundle.get("users") if isinstance(bundle.get("users"), list) else []
        rosters = (
            bundle.get("rosters") if isinstance(bundle.get("rosters"), list) else []
        )
        league = bundle.get("league") if isinstance(bundle.get("league"), dict) else {}
        league_id = str(league.get("league_id") or "")
        for draft_index, draft_bundle in enumerate(drafts):
            if not isinstance(draft_bundle, dict):
                issues.append(
                    f"Historical draft bundle {bundle_index + 1}.{draft_index + 1} is malformed."
                )
                continue
            draft = draft_bundle.get("draft")
            picks = draft_bundle.get("picks")
            if not isinstance(draft, dict) or not isinstance(picks, list):
                issues.append(
                    f"Historical draft bundle {bundle_index + 1}.{draft_index + 1} "
                    "is missing draft metadata or picks."
                )
                continue
            season = str(draft.get("season") or "")
            draft_id = str(draft.get("draft_id") or "")
            candidates.append(
                (season, draft_id, draft, picks, users, rosters, league_id)
            )
        if candidates:
            bundle_candidates.append(candidates)

    if not bundle_candidates:
        issues.append("No valid linked historical draft could be used; raw ADP will be used.")
        return HistoricalPositionCurves(
            {},
            None,
            None,
            tuple(issues),
            excluded_user_ids=normalized_excluded_ids,
        )

    newest_by_bundle = [
        max(candidates, key=lambda item: (item[0], item[1]))
        for candidates in bundle_candidates
    ]
    newest_season = max(candidate[0] for candidate in newest_by_bundle)
    selected = [
        candidate for candidate in newest_by_bundle if candidate[0] == newest_season
    ]
    if len(selected) < len(newest_by_bundle):
        issues.append(
            f"Excluded {len(newest_by_bundle) - len(selected)} linked draft(s) older than "
            f"the newest shared season {newest_season or 'unknown'}."
        )

    valid_curves: list[tuple[dict[str, tuple[int, ...]], int, str]] = []
    exclusion_audit: list[dict[str, Any]] = []
    exclusion_failure = False
    for season, draft_id, draft, picks, users, rosters, league_id in selected:
        settings = draft.get("settings") or {}
        try:
            teams = int(settings.get("teams") or 0)
            rounds = int(settings.get("rounds") or 0)
        except (TypeError, ValueError):
            teams = rounds = 0
        if teams <= 0 or rounds <= 0:
            issues.append(
                f"Historical draft {draft_id or 'unknown'} has invalid team/round settings "
                "and was excluded."
            )
            continue

        draft_end = teams * rounds
        ordered: list[tuple[int, dict[str, Any]]] = []
        malformed_pick_count = 0
        for pick in picks:
            if not isinstance(pick, dict):
                malformed_pick_count += 1
                continue
            try:
                pick_no = int(pick.get("pick_no") or 0)
            except (TypeError, ValueError):
                pick_no = 0
            if not 1 <= pick_no <= draft_end:
                malformed_pick_count += 1
                continue
            ordered.append((pick_no, pick))
        ordered.sort(key=lambda item: item[0])
        if malformed_pick_count:
            issues.append(
                f"Historical draft {draft_id or 'unknown'} has {malformed_pick_count} "
                "malformed or out-of-range picks that were excluded."
            )
        duplicate_count = len(ordered) - len({pick_no for pick_no, _ in ordered})
        if duplicate_count:
            issues.append(
                f"Historical draft {draft_id or 'unknown'} has duplicate overall pick "
                "numbers and was excluded."
            )
            continue

        source_suffix = ""
        if normalized_excluded_ids:
            original_draft_end = draft_end
            if len(ordered) != original_draft_end:
                exclusion_failure = True
                issues.append(
                    f"Historical draft {draft_id or 'unknown'} has {len(ordered)} of "
                    f"{original_draft_end} expected picks, so returning-manager history "
                    "could not be built."
                )
                continue
            if teams <= len(normalized_excluded_ids):
                exclusion_failure = True
                issues.append(
                    f"Historical draft {draft_id or 'unknown'} does not have enough teams "
                    "for the requested manager exclusions."
                )
                continue

            roster_owners = {
                str(roster.get("roster_id")): str(roster.get("owner_id") or "")
                for roster in rosters
                if isinstance(roster, dict) and roster.get("roster_id") is not None
            }

            def pick_owner_id(pick: dict[str, Any]) -> str:
                picked_by = str(pick.get("picked_by") or "")
                if picked_by:
                    return picked_by
                return roster_owners.get(str(pick.get("roster_id") or ""), "")

            excluded_pick_counts = Counter(
                pick_owner_id(pick)
                for _, pick in ordered
                if pick_owner_id(pick) in normalized_excluded_ids
            )
            invalid_exclusions = [
                user_id
                for user_id in normalized_excluded_ids
                if excluded_pick_counts[user_id] != rounds
            ]
            if invalid_exclusions:
                exclusion_failure = True
                details = ", ".join(
                    f"{user_id} ({excluded_pick_counts[user_id]}/{rounds} picks)"
                    for user_id in invalid_exclusions
                )
                issues.append(
                    f"Historical draft {draft_id or 'unknown'} could not apply every "
                    f"manager exclusion exactly: {details}. The draft was excluded."
                )
                continue

            retained = [
                pick
                for _, pick in ordered
                if pick_owner_id(pick) not in normalized_excluded_ids
            ]
            teams -= len(normalized_excluded_ids)
            draft_end = teams * rounds
            if len(retained) != draft_end:
                exclusion_failure = True
                issues.append(
                    f"Historical draft {draft_id or 'unknown'} retained {len(retained)} "
                    f"picks instead of {draft_end}; returning-manager history was excluded."
                )
                continue
            ordered = list(enumerate(retained, start=1))
            display_names = {
                str(user.get("user_id")): str(
                    user.get("display_name")
                    or user.get("username")
                    or user.get("user_id")
                )
                for user in users
                if isinstance(user, dict)
            }
            excluded_names = [
                display_names.get(user_id, user_id)
                for user_id in normalized_excluded_ids
            ]
            exclusion_audit.append(
                {
                    "league_id": league_id or None,
                    "draft_id": draft_id or None,
                    "original_team_count": teams + len(normalized_excluded_ids),
                    "effective_team_count": teams,
                    "rounds": rounds,
                    "excluded_user_ids": list(normalized_excluded_ids),
                    "excluded_manager_names": excluded_names,
                    "excluded_pick_count": sum(excluded_pick_counts.values()),
                    "retained_pick_count": len(retained),
                    "renumbered_in_original_order": True,
                }
            )
            source_suffix = (
                f"; {teams}-manager counterfactual excluding "
                + ", ".join(excluded_names)
            )

        position_picks: dict[str, list[int]] = {
            position: [] for position in ACQUISITION_POSITIONS
        }
        unknown_position_count = 0
        for pick_no, pick in ordered:
            position = pick_position(pick)
            if position in position_picks:
                position_picks[position].append(pick_no)
            elif position not in {"K", "DST"}:
                unknown_position_count += 1
        if unknown_position_count:
            issues.append(
                f"Historical draft {draft_id or 'unknown'} has {unknown_position_count} "
                "picks with an unknown or unsupported position."
            )
        if not ordered or not any(position_picks.values()):
            issues.append(
                f"Historical draft {draft_id or 'unknown'} has no usable QB/RB/WR/TE "
                "picks and was excluded."
            )
            continue
        source = (
            f"Sleeper draft {draft_id or 'unknown'} ({season or 'unknown season'}"
            f"{source_suffix})"
        )
        valid_curves.append(
            (
                {position: tuple(values) for position, values in position_picks.items()},
                draft_end,
                source,
            )
        )

    if normalized_excluded_ids and exclusion_failure:
        issues.append(
            "Returning-manager history requires every selected linked draft to "
            "pass the exclusion completeness gate; raw ADP will be used."
        )
        return HistoricalPositionCurves(
            {},
            None,
            None,
            tuple(issues),
            excluded_user_ids=normalized_excluded_ids,
            exclusion_audit=tuple(exclusion_audit),
        )

    if not valid_curves:
        issues.append("No valid linked historical draft could be used; raw ADP will be used.")
        return HistoricalPositionCurves(
            {},
            None,
            None,
            tuple(issues),
            excluded_user_ids=normalized_excluded_ids,
            exclusion_audit=tuple(exclusion_audit),
        )

    averaged_picks: dict[str, tuple[float, ...]] = {}
    for position in ACQUISITION_POSITIONS:
        maximum_slots = max(len(curve.get(position, ())) for curve, _, _ in valid_curves)
        averaged_picks[position] = tuple(
            sum(
                float(curve[position][slot])
                if slot < len(curve.get(position, ()))
                else float(draft_end + 1)
                for curve, draft_end, _ in valid_curves
            )
            / len(valid_curves)
            for slot in range(maximum_slots)
        )
    average_draft_end = sum(draft_end for _, draft_end, _ in valid_curves) / len(valid_curves)
    sources = tuple(source for _, _, source in valid_curves)
    source = (
        sources[0]
        if len(sources) == 1
        else f"Equal-weight positional slots from {len(sources)} drafts"
    )
    return HistoricalPositionCurves(
        position_picks=averaged_picks,
        draft_end_pick=average_draft_end,
        source=source,
        issues=tuple(issues),
        sources=sources,
        excluded_user_ids=normalized_excluded_ids,
        exclusion_audit=tuple(exclusion_audit),
    )


def simulation_round_tendencies(snapshot: dict[str, Any]) -> dict[int, dict[str, float]]:
    """Build heavily-shrunk position rates from historical drafts for opponent simulations."""
    analysis = analyze_snapshot(snapshot)
    round_counts: dict[int, Counter[str]] = defaultdict(Counter)
    round_totals: Counter[int] = Counter()
    for draft in analysis.get("drafts", []):
        for round_text, counts in draft.get("analysis", {}).get("position_by_round", {}).items():
            round_no = int(round_text)
            for position in CORE_POSITIONS:
                count = int(counts.get(position, 0))
                round_counts[round_no][position] += count
                round_totals[round_no] += count

    result: dict[int, dict[str, float]] = {}
    for round_no, counts in round_counts.items():
        observed_total = round_totals[round_no]
        prior_strength = max(1, observed_total)
        denominator = observed_total + prior_strength
        result[round_no] = {
            position: (counts[position] + prior_strength * MARKET_POSITION_PRIOR[position]) / denominator
            for position in MARKET_POSITION_PRIOR
        }
    return result
