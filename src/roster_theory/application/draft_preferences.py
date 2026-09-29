from __future__ import annotations

import csv
import hashlib
from pathlib import Path
from typing import Any, Iterable, Mapping

from roster_theory.draft.preferences import DraftPreference, DraftPreferenceBook
from roster_theory.rankings import normalize_name


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
