from __future__ import annotations

import csv
import hashlib
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from roster_theory.rankings import normalize_name
from roster_theory.simulation import Player


REQUIRED_FIELDS = {
    "player_name",
    "position",
    "stance",
    "category",
    "take_at_or_after",
    "condition",
    "linked_player",
    "source",
    "league_scope",
}
SUPPORTED_STANCES = {"target", "caution"}
SUPPORTED_CONDITIONS = {
    "",
    "six_point_passing_td_preferred",
    "value_near_picks_85_to_90",
}


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


def _board_key(row: Mapping[str, Any]) -> str:
    return str(
        row.get("player_key")
        or row.get("sleeper_id")
        or row.get("player_name")
        or ""
    )


def load_draft_preferences(
    path: str | Path,
    board: Iterable[Mapping[str, Any]],
    league_key: str,
) -> DraftPreferenceBook:
    """Load and strictly match one league's explicit user-authored preferences."""

    source_path = Path(path)
    payload = source_path.read_bytes()
    board_by_name: dict[str, list[dict[str, Any]]] = {}
    for source in board:
        row = dict(source)
        name = normalize_name(str(row.get("player_name") or ""))
        if name:
            board_by_name.setdefault(name, []).append(row)

    errors: list[str] = []
    entries: list[DraftPreference] = []
    seen: set[tuple[str, str]] = set()
    with source_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        missing_fields = sorted(REQUIRED_FIELDS - set(reader.fieldnames or ()))
        if missing_fields:
            raise ValueError(
                "Draft preference file is missing fields: " + ", ".join(missing_fields)
            )
        for line_number, source in enumerate(reader, start=2):
            scopes = tuple(
                part.strip()
                for part in str(source.get("league_scope") or "").split("|")
                if part.strip()
            )
            if league_key not in scopes:
                continue
            player_name = str(source.get("player_name") or "").strip()
            position = str(source.get("position") or "").strip().upper()
            stance = str(source.get("stance") or "").strip().lower()
            condition = str(source.get("condition") or "").strip()
            if stance not in SUPPORTED_STANCES:
                errors.append(f"line {line_number}: unsupported stance {stance!r}")
                continue
            if condition not in SUPPORTED_CONDITIONS:
                errors.append(f"line {line_number}: unsupported condition {condition!r}")
                continue
            matches = board_by_name.get(normalize_name(player_name), [])
            if len(matches) != 1:
                label = "unmatched" if not matches else "ambiguous"
                errors.append(f"line {line_number}: {label} player {player_name!r}")
                continue
            board_row = matches[0]
            board_position = str(board_row.get("position") or "").upper().replace(
                "DEF", "DST"
            )
            if position.replace("DEF", "DST") != board_position:
                errors.append(
                    f"line {line_number}: {player_name!r} position {position!r} "
                    f"does not match board position {board_position!r}"
                )
                continue
            floor_text = str(source.get("take_at_or_after") or "").strip()
            try:
                floor = int(floor_text) if floor_text else None
            except ValueError:
                errors.append(
                    f"line {line_number}: invalid take_at_or_after {floor_text!r}"
                )
                continue
            if floor is not None and floor <= 0:
                errors.append(
                    f"line {line_number}: take_at_or_after must be positive"
                )
                continue
            player_key = _board_key(board_row)
            identity = (player_key, stance)
            if identity in seen:
                errors.append(
                    f"line {line_number}: duplicate {stance} for {player_name!r}"
                )
                continue
            seen.add(identity)
            entries.append(
                DraftPreference(
                    player_key=player_key,
                    player_name=str(board_row.get("player_name") or player_name),
                    position=board_position,
                    stance=stance,
                    category=str(source.get("category") or "").strip(),
                    take_at_or_after=floor,
                    condition=condition,
                    linked_player=str(source.get("linked_player") or "").strip(),
                    source=str(source.get("source") or "").strip(),
                    league_scope=scopes,
                )
            )
    if errors:
        raise ValueError("Draft preference validation failed: " + "; ".join(errors))
    return DraftPreferenceBook(
        league_key=league_key,
        source_path=str(source_path),
        sha256=hashlib.sha256(payload).hexdigest(),
        entries=tuple(entries),
    )


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
