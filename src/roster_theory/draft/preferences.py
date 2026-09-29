from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping

from roster_theory.draft.simulation import Player


@dataclass(frozen=True, slots=True)
class DraftPreference:
    player_key: str
    player_name: str
    position: str
    stance: str
    category: str
    take_at_or_after: int | None
    condition: str
    linked_player: str
    source: str
    league_scope: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DraftPreferenceBook:
    league_key: str
    source_path: str
    sha256: str
    entries: tuple[DraftPreference, ...]

    def evidence_metadata(self) -> dict[str, Any]:
        return {
            "league_key": self.league_key,
            "source_path": self.source_path,
            "sha256": self.sha256,
            "entries": [asdict(entry) for entry in self.entries],
        }


def _condition_is_active(
    condition: str,
    scoring_settings: Mapping[str, Any],
) -> bool:
    if not condition:
        return True
    if condition == "six_point_passing_td_preferred":
        try:
            return float(scoring_settings.get("pass_td") or 0.0) >= 6.0
        except (TypeError, ValueError):
            return False
    if condition == "value_near_picks_85_to_90":
        return True
    return False


def evaluate_draft_preferences(
    book: DraftPreferenceBook,
    raw_players: Mapping[str, Player],
    adjusted_players: Mapping[str, Player],
    available_keys: set[str],
    market_survival: Mapping[str, float],
    league_survival: Mapping[str, float],
    current_pick: int,
    recommendations: Mapping[str, list[Mapping[str, Any]]],
    candidate_rows: Mapping[str, Mapping[str, Any]] | None = None,
    scoring_settings: Mapping[str, Any] | None = None,
    display_limit: int = 3,
    caution_depth: int = 3,
    survival_threshold: float = 0.50,
    last_skill_pick: bool = False,
) -> dict[str, Any]:
    """Evaluate targets without changing recommendation scores or ordering."""

    settings = scoring_settings or {}
    target_entries = [entry for entry in book.entries if entry.stance == "target"]
    caution_entries = [entry for entry in book.entries if entry.stance == "caution"]
    target_floors = {
        entry.player_key: entry.take_at_or_after
        for entry in target_entries
        if entry.take_at_or_after is not None
    }
    inactive_targets: list[dict[str, Any]] = []
    targets: list[dict[str, Any]] = []
    for entry in target_entries:
        if entry.player_key not in available_keys:
            continue
        if candidate_rows is not None and entry.player_key not in candidate_rows:
            inactive_targets.append(
                {
                    "player_key": entry.player_key,
                    "player_name": entry.player_name,
                    "condition": "roster_construction",
                    "reason": "not eligible under current roster construction",
                }
            )
            continue
        if not _condition_is_active(entry.condition, settings):
            inactive_targets.append(
                {
                    "player_key": entry.player_key,
                    "player_name": entry.player_name,
                    "condition": entry.condition,
                    "reason": "league scoring condition not met",
                }
            )
            continue
        raw_player = raw_players[entry.player_key]
        adjusted_player = adjusted_players[entry.player_key]
        market_value = float(market_survival.get(entry.player_key, 1.0))
        league_value = float(league_survival.get(entry.player_key, 1.0))
        before_floor = bool(
            entry.take_at_or_after is not None
            and current_pick < entry.take_at_or_after
        )
        if before_floor:
            call = "WAIT"
            note = f"after {entry.take_at_or_after}"
        elif last_skill_pick:
            call = "NOW"
            note = "last skill pick"
        else:
            market_now = market_value < survival_threshold
            league_now = league_value < survival_threshold
            call = "NOW" if market_now and league_now else "WAIT"
            if market_now != league_now:
                call = "SPLIT"
            note = ""
        targets.append(
            {
                "player_key": entry.player_key,
                "player_name": entry.player_name,
                "position": entry.position,
                "call": call,
                "market_survival": round(market_value, 6),
                "league_survival": round(league_value, 6),
                "market_adp": round(raw_player.adp, 3),
                "league_expected_pick": round(adjusted_player.acquisition_pick, 3),
                "take_at_or_after": entry.take_at_or_after,
                "note": note,
                "category": entry.category,
                "linked_player": entry.linked_player,
                "source": entry.source,
                "roster_need": str(
                    ((candidate_rows or {}).get(entry.player_key) or {}).get(
                        "roster_need"
                    )
                    or ""
                ),
                "candidate_rank": (
                    ((candidate_rows or {}).get(entry.player_key) or {}).get(
                        "candidate_rank"
                    )
                ),
                "primary_score_gap": (
                    ((candidate_rows or {}).get(entry.player_key) or {}).get(
                        "primary_score_gap"
                    )
                ),
            }
        )

    call_priority = {"NOW": 0, "SPLIT": 1, "WAIT": 2}

    def target_order(row: Mapping[str, Any]) -> tuple[float, ...]:
        decision_pick = max(
            float(row.get("take_at_or_after") or 0.0),
            min(
                float(row.get("market_adp") or 999.0),
                float(row.get("league_expected_pick") or 999.0),
            ),
        )
        return (
            float(call_priority[str(row["call"])]),
            decision_pick,
            min(
                float(row.get("market_survival") or 0.0),
                float(row.get("league_survival") or 0.0),
            ),
        )

    targets.sort(key=target_order)

    displayed_keys: set[str] = set()
    table_keys: set[str] = set()
    for rows in recommendations.values():
        visible_rows = list(rows)
        for row in visible_rows:
            table_keys.add(str(row.get("player_key") or ""))
        for row in visible_rows[: max(0, caution_depth)]:
            displayed_keys.add(str(row.get("player_key") or ""))
    cautions: list[dict[str, Any]] = []
    table_cautions: list[dict[str, Any]] = []
    for entry in caution_entries:
        if entry.player_key not in table_keys or entry.player_key not in available_keys:
            continue
        raw_player = raw_players[entry.player_key]
        adjusted_player = adjusted_players[entry.player_key]
        floor = target_floors.get(entry.player_key)
        reason = ""
        if entry.category == "unavailable":
            reason = "currently unavailable"
        elif floor is not None and current_pick < floor:
            reason = f"before pick {floor}"
        elif (
            entry.category == "fade_at_te5_cost"
            and floor is None
            and (adjusted_player.acquisition_position_slot or 999) <= 5
        ):
            reason = "TE5 price"
        elif entry.category == "fade_at_cost" and current_pick <= max(
            raw_player.adp, adjusted_player.acquisition_pick
        ):
            reason = "at/above cost"
        if reason:
            row = {
                "player_key": entry.player_key,
                "player_name": entry.player_name,
                "position": entry.position,
                "reason": reason,
                "category": entry.category,
                "source": entry.source,
            }
            table_cautions.append(row)
            if entry.player_key in displayed_keys:
                cautions.append(row)

    return {
        "active": True,
        "league_key": book.league_key,
        "source_path": book.source_path,
        "sha256": book.sha256,
        "survival_threshold": survival_threshold,
        "display_limit": display_limit,
        "targets": targets,
        "display_targets": targets[: max(0, display_limit)],
        "inactive_targets": inactive_targets,
        "cautions": cautions,
        "table_cautions": table_cautions,
        "recommendations_changed": False,
    }
