from __future__ import annotations

import math
import statistics
import time
from typing import Any, Iterable, Mapping


SKILL_POSITIONS = frozenset({"QB", "RB", "WR", "TE"})
SCORING_FIELDS = {
    "standard": "adp_std",
    "half_ppr": "adp_half_ppr",
    "ppr": "adp_ppr",
}


def scoring_adp_field(scoring: str) -> str:
    try:
        return SCORING_FIELDS[scoring]
    except KeyError as exc:
        raise ValueError(f"Unsupported Sleeper ADP scoring: {scoring}") from exc


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def build_sleeper_adp_snapshot(
    projections: Iterable[Mapping[str, Any]],
    season: int,
    scoring: str,
    captured_at: int | None = None,
) -> dict[str, Any]:
    """Create a compact, dated snapshot of Sleeper's scoring-specific ADP."""

    field = scoring_adp_field(scoring)
    players = []
    source_rows = 0
    missing_or_sentinel = 0
    for row in projections:
        source_rows += 1
        player = row.get("player") or {}
        position = str(player.get("position") or "").upper().replace("DEF", "DST")
        if position not in SKILL_POSITIONS:
            continue
        adp = _number((row.get("stats") or {}).get(field))
        if adp is None or not 0.0 < adp < 999.0:
            missing_or_sentinel += 1
            continue
        name = " ".join(
            part
            for part in (
                str(player.get("first_name") or "").strip(),
                str(player.get("last_name") or "").strip(),
            )
            if part
        )
        players.append(
            {
                "player_id": str(row.get("player_id") or ""),
                "player_name": name,
                "position": position,
                "team": str(row.get("team") or player.get("team") or ""),
                "sleeper_adp": round(adp, 3),
                "updated_at": int(row.get("updated_at") or 0),
                "last_modified": int(row.get("last_modified") or 0),
            }
        )
    players.sort(key=lambda row: (row["sleeper_adp"], row["player_id"]))
    captured = int(captured_at if captured_at is not None else time.time())
    update_times = [int(row["updated_at"]) for row in players if row["updated_at"]]
    return {
        "schema_version": 1,
        "captured_at": captured,
        "season": int(season),
        "season_type": "regular",
        "scoring": scoring,
        "adp_field": field,
        "source": {
            "endpoint": f"https://api.sleeper.com/projections/nfl/{int(season)}",
            "public_api_documented": False,
            "public_web_client_field_verified": True,
            "visual_draft_room_verified": False,
        },
        "source_rows": source_rows,
        "usable_skill_players": len(players),
        "missing_or_sentinel_skill_rows": missing_or_sentinel,
        "record_updated_at_range": {
            "minimum": min(update_times) if update_times else None,
            "maximum": max(update_times) if update_times else None,
        },
        "players": players,
    }


def _pearson(left: list[float], right: list[float]) -> float | None:
    if len(left) < 2 or len(left) != len(right):
        return None
    left_mean = statistics.fmean(left)
    right_mean = statistics.fmean(right)
    numerator = sum(
        (left_value - left_mean) * (right_value - right_mean)
        for left_value, right_value in zip(left, right)
    )
    left_ss = sum((value - left_mean) ** 2 for value in left)
    right_ss = sum((value - right_mean) ** 2 for value in right)
    denominator = math.sqrt(left_ss * right_ss)
    return numerator / denominator if denominator else None


def audit_board_against_sleeper_adp(
    board: Iterable[Mapping[str, Any]],
    adp_snapshot: Mapping[str, Any],
    comparison_limit: int = 240,
) -> dict[str, Any]:
    by_id = {
        str(row.get("player_id") or ""): row
        for row in adp_snapshot.get("players") or []
    }
    pairs: list[tuple[float, float]] = []
    compared = []
    eligible = 0
    for row in board:
        position = str(row.get("position") or "").upper().replace("DEF", "DST")
        if position not in SKILL_POSITIONS:
            continue
        market_adp = _number(row.get("adp"))
        if market_adp is None or not 0.0 < market_adp < 999.0:
            continue
        eligible += 1
        sleeper = by_id.get(str(row.get("sleeper_id") or ""))
        if not sleeper:
            continue
        sleeper_adp = float(sleeper["sleeper_adp"])
        pairs.append((market_adp, sleeper_adp))
        if min(market_adp, sleeper_adp) <= comparison_limit:
            compared.append(
                {
                    "player_id": str(row.get("sleeper_id") or ""),
                    "player_name": str(row.get("player_name") or ""),
                    "position": position,
                    "market_adp": round(market_adp, 3),
                    "sleeper_adp": round(sleeper_adp, 3),
                    "sleeper_minus_market": round(sleeper_adp - market_adp, 3),
                }
            )
    absolute_gaps = [abs(left - right) for left, right in pairs]
    compared.sort(
        key=lambda row: (-abs(float(row["sleeper_minus_market"])), row["player_name"])
    )
    correlation = _pearson(
        [left for left, _ in pairs], [right for _, right in pairs]
    )
    return {
        "eligible_board_players": eligible,
        "matched_players": len(pairs),
        "coverage": round(len(pairs) / eligible, 6) if eligible else 0.0,
        "market_sleeper_adp_correlation": (
            round(correlation, 6) if correlation is not None else None
        ),
        "median_absolute_adp_gap": (
            round(statistics.median(absolute_gaps), 3) if absolute_gaps else None
        ),
        "largest_disagreements": compared[:25],
    }


def audit_pick_sequence_against_sleeper_adp(
    picks: Iterable[Mapping[str, Any]],
    adp_snapshot: Mapping[str, Any],
    excluded_draft_slot: int | None = None,
) -> dict[str, Any]:
    adp_by_id = {
        str(row.get("player_id") or ""): float(row["sleeper_adp"])
        for row in adp_snapshot.get("players") or []
    }
    skill_picks = [
        pick
        for pick in picks
        if str((pick.get("metadata") or {}).get("position") or "").upper()
        in SKILL_POSITIONS
        and (
            excluded_draft_slot is None
            or int(pick.get("draft_slot") or 0) != excluded_draft_slot
        )
    ]
    matched = [
        (int(pick.get("pick_no") or 0), adp_by_id[str(pick.get("player_id"))])
        for pick in skill_picks
        if str(pick.get("player_id")) in adp_by_id
    ]
    pick_numbers = [float(pick_no) for pick_no, _ in matched]
    sleeper_adps = [adp for _, adp in matched]
    gaps = [abs(pick_no - adp) for pick_no, adp in matched]
    correlation = _pearson(pick_numbers, sleeper_adps)
    return {
        "skill_picks": len(skill_picks),
        "matched_picks": len(matched),
        "coverage": (
            round(len(matched) / len(skill_picks), 6) if skill_picks else 0.0
        ),
        "pick_adp_correlation": (
            round(correlation, 6) if correlation is not None else None
        ),
        "median_absolute_pick_gap": (
            round(statistics.median(gaps), 3) if gaps else None
        ),
        "within_12_picks": (
            round(sum(gap <= 12.0 for gap in gaps) / len(gaps), 6)
            if gaps
            else None
        ),
        "within_24_picks": (
            round(sum(gap <= 24.0 for gap in gaps) / len(gaps), 6)
            if gaps
            else None
        ),
    }


def audit_historical_drafts_against_archived_adp(
    league_snapshot: Mapping[str, Any],
    archived_adp_snapshot: Mapping[str, Any],
) -> dict[str, Any]:
    """Exploratory only: archived ADP has no preserved draft-day timestamp."""

    drafts = []
    skipped_other_seasons = 0
    archived_season = str(archived_adp_snapshot.get("season") or "")
    for bundle in league_snapshot.get("history") or []:
        league = bundle.get("league") or {}
        for draft_bundle in bundle.get("drafts") or []:
            draft = draft_bundle.get("draft") or {}
            if str(draft.get("status") or "") != "complete":
                continue
            draft_season = str(draft.get("season") or league.get("season") or "")
            if draft_season != archived_season:
                skipped_other_seasons += 1
                continue
            metrics = audit_pick_sequence_against_sleeper_adp(
                draft_bundle.get("picks") or [], archived_adp_snapshot
            )
            drafts.append(
                {
                    "league_id": str(league.get("league_id") or ""),
                    "draft_id": str(draft.get("draft_id") or ""),
                    "draft_start_time": int(draft.get("start_time") or 0),
                    **metrics,
                }
            )
    return {
        "status": "exploratory_proxy_only",
        "can_validate_draft_day_order": False,
        "limitation": (
            "No dated 2025 draft-day Sleeper ADP snapshot was preserved. The "
            "archived season endpoint has an unknown effective date, so these "
            "statistics cannot establish what managers saw during either draft."
        ),
        "archived_season": int(archived_season) if archived_season else None,
        "skipped_complete_drafts_from_other_seasons": skipped_other_seasons,
        "drafts": drafts,
    }
