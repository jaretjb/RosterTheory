from __future__ import annotations

import csv
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from roster_theory.rankings import (
    AccuracyRecord,
    SKILL_POSITIONS,
    add_vbd,
    normalize_name,
    score_projection,
    starter_baselines,
    weighted_consensus,
)


TEAM_CODES = {
    "ARI", "ATL", "BAL", "BUF", "CAR", "CHI", "CIN", "CLE", "DAL", "DEN", "DET",
    "GB", "HOU", "IND", "JAC", "JAX", "KC", "LAC", "LAR", "LV", "MIA", "MIN",
    "NE", "NO", "NYG", "NYJ", "PHI", "PIT", "SEA", "SF", "TB", "TEN", "WAS",
}
RESERVED_RANKING_COLUMNS = {
    "adp", "adpvsecr", "ecrvsadp", "avg", "avgdiff", "avgrank", "best", "bestrank", "bye", "byeweek", "ecr",
    "notes", "numexperts", "player", "playername", "pos", "position", "rank", "rk", "sd",
    "sos", "stddev", "team", "tier", "tiers", "upside", "worst", "worstrank", "wsid",
}
SELECTED_ECR_EXPERT = "FantasyPros selected draft-accuracy ECR"


@dataclass(slots=True)
class ManualImportResult:
    players: list[dict[str, Any]]
    metadata: dict[str, Any]
    match_report: list[dict[str, Any]]
    issues: list[dict[str, Any]]


def _header_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").lower())


def _as_float(value: Any) -> float | None:
    if value in (None, "", "-"):
        return None
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _read_table(path: str | Path) -> list[list[str]]:
    source = Path(path)
    text = source.read_text(encoding="utf-8-sig")
    if not text.strip():
        raise ValueError(f"{source} is empty")
    try:
        dialect = csv.Sniffer().sniff(text[:8192], delimiters=",\t;")
        delimiter = dialect.delimiter
    except csv.Error:
        delimiter = "\t" if source.suffix.lower() == ".tsv" else ","
    return [
        [cell.strip() for cell in row]
        for row in csv.reader(text.splitlines(), delimiter=delimiter)
        if any(cell.strip() for cell in row)
    ]


def _column_index(headers: Sequence[str], *names: str) -> int | None:
    wanted = {_header_key(name) for name in names}
    for index, header in enumerate(headers):
        if _header_key(header) in wanted:
            return index
    return None


def _position(value: Any) -> str | None:
    match = re.search(r"\b(QB|RB|WR|TE)\d*\b", str(value or "").upper())
    return match.group(1) if match else None


def _excluded_ranking_position(value: Any) -> str | None:
    match = re.search(r"\b(K|DST|DEF)\d*\b", str(value or "").upper())
    if not match:
        return None
    return "DST" if match.group(1) == "DEF" else match.group(1)


def _parse_player_cell(value: str, position: str | None = None) -> tuple[str, str | None, str | None]:
    original = re.sub(r"\s+", " ", value).strip()
    parsed_position = position or _position(original)
    team: str | None = None
    name = original

    parenthetical = re.search(
        r"\s*\(([A-Z]{2,3})(?:\s*[-,]\s*(QB|RB|WR|TE)\d*)?(?:\s*[-,]\s*\d+)?\)\s*$",
        name,
    )
    if parenthetical:
        team = parenthetical.group(1)
        parsed_position = parsed_position or parenthetical.group(2)
        name = name[: parenthetical.start()].strip()

    suffix = re.search(r"\s+([A-Z]{2,3})(?:\s+(QB|RB|WR|TE)\d*)?(?:\s+\(\d+\))?\s*$", name)
    if suffix and suffix.group(1) in TEAM_CODES:
        team = team or suffix.group(1)
        parsed_position = parsed_position or suffix.group(2)
        name = name[: suffix.start()].strip()

    # Copying the rendered expert table can include an abbreviated name before
    # the full name. Prefer the final full-name segment when it is duplicated.
    tokens = name.split()
    if len(tokens) >= 4:
        for split_at in range(1, len(tokens) - 1):
            trailing = " ".join(tokens[split_at:])
            if normalize_name(trailing).endswith(normalize_name(" ".join(tokens[:split_at]))):
                name = trailing
                break
    return name.strip(), team, parsed_position


def _match_expert_header(
    header: str, accuracy: Mapping[str, AccuracyRecord]
) -> tuple[str, AccuracyRecord] | None:
    key = _header_key(header)
    matches = [
        (accuracy_key, record)
        for accuracy_key, record in accuracy.items()
        if accuracy_key and accuracy_key in key
    ]
    if not matches:
        return None
    matches.sort(key=lambda item: len(item[0]), reverse=True)
    if len(matches) > 1 and len(matches[0][0]) == len(matches[1][0]):
        return None
    return matches[0]


def load_fantasypros_rankings_matrix(
    path: str | Path, accuracy: Mapping[str, AccuracyRecord]
) -> tuple[list[dict[str, Any]], dict[str, Any], list[dict[str, Any]]]:
    """Convert a FantasyPros expert matrix export into the internal long form."""
    table = _read_table(path)
    header_index: int | None = None
    headers: list[str] = []
    expert_columns: dict[int, AccuracyRecord] = {}
    for index, row in enumerate(table[:12]):
        if _column_index(row, "player", "player name") is None:
            continue
        candidates = {column: _match_expert_header(value, accuracy) for column, value in enumerate(row)}
        matches = {column: match[1] for column, match in candidates.items() if match is not None}
        combined = row
        if not matches and index + 1 < len(table):
            following = table[index + 1]
            combined = [
                f"{value} {following[column] if column < len(following) else ''}".strip()
                for column, value in enumerate(row)
            ]
            candidates = {column: _match_expert_header(value, accuracy) for column, value in enumerate(combined)}
            matches = {column: match[1] for column, match in candidates.items() if match is not None}
        if matches:
            header_index = index
            headers = combined
            expert_columns = matches
            break
    if header_index is None:
        raise ValueError(
            f"{path} does not look like a FantasyPros expert-ranking matrix; "
            "expected a Player column and at least one seeded expert column"
        )

    player_column = _column_index(headers, "player", "player name")
    assert player_column is not None
    position_column = _column_index(headers, "pos", "position")
    team_column = _column_index(headers, "team")
    consensus_column = _column_index(headers, "rk", "rank", "ecr", "avg", "avg rank")

    issues: list[dict[str, Any]] = []
    unmatched_columns: list[str] = []
    data_rows = table[header_index + 1 :]
    for column, header in enumerate(headers):
        key = _header_key(header)
        if column in expert_columns or not key or key in RESERVED_RANKING_COLUMNS:
            continue
        numeric = sum(
            _as_float(row[column]) is not None for row in data_rows[:50] if column < len(row)
        )
        if numeric >= 3:
            unmatched_columns.append(header)
            issues.append(
                {
                    "source": str(path),
                    "row": "header",
                    "reason": "unmatched_expert_column",
                    "detail": header,
                }
            )

    long_rows: list[dict[str, Any]] = []
    skipped = 0
    for row_number, row in enumerate(data_rows, start=header_index + 2):
        if player_column >= len(row) or not row[player_column].strip():
            continue
        explicit_position = _position(row[position_column]) if position_column is not None and position_column < len(row) else None
        player_name, parsed_team, parsed_position = _parse_player_cell(row[player_column], explicit_position)
        team = row[team_column].strip() if team_column is not None and team_column < len(row) else parsed_team
        if parsed_position not in SKILL_POSITIONS or not player_name:
            skipped += 1
            issues.append(
                {
                    "source": str(path),
                    "row": row_number,
                    "reason": "unusable_ranking_player",
                    "detail": row[player_column],
                }
            )
            continue
        ecr = (
            _as_float(row[consensus_column])
            if consensus_column is not None and consensus_column < len(row)
            else None
        )
        found_rank = False
        for column, record in expert_columns.items():
            rank = _as_float(row[column]) if column < len(row) else None
            if rank is None:
                continue
            found_rank = True
            long_rows.append(
                {
                    "expert_name": record.expert_name,
                    "player_name": player_name,
                    "team": team,
                    "position": parsed_position,
                    "expert_rank": rank,
                    "ecr": ecr,
                }
            )
        if not found_rank:
            skipped += 1
            issues.append(
                {
                    "source": str(path),
                    "row": row_number,
                    "reason": "missing_expert_ranks",
                    "detail": player_name,
                }
            )
    if not long_rows:
        raise ValueError(f"{path} did not contain any usable expert/player rankings")

    expert_counts = Counter(str(row["expert_name"]) for row in long_rows)
    return long_rows, {
        "path": str(path),
        "matched_experts": sorted(expert_counts),
        "rankings_per_expert": dict(sorted(expert_counts.items())),
        "unmatched_expert_columns": unmatched_columns,
        "skipped_rows": skipped,
    }, issues


def load_fantasypros_selected_ecr(
    path: str | Path, selected_experts: Mapping[str, AccuracyRecord]
) -> tuple[list[dict[str, Any]], dict[str, Any], list[dict[str, Any]]]:
    """Load the CSV produced by a FantasyPros custom selected-expert consensus."""
    table = _read_table(path)
    header_index = next(
        (
            index
            for index, row in enumerate(table[:12])
            if _column_index(row, "player", "player name") is not None
        ),
        None,
    )
    if header_index is None:
        raise ValueError(f"{path} is missing a Player column")
    headers = table[header_index]
    player_column = _column_index(headers, "player", "player name")
    rank_column = _column_index(headers, "ecr", "rk", "rank", "avg rank")
    if rank_column is None:
        raise ValueError(f"{path} is missing an ECR, RK, or Rank column")
    assert player_column is not None
    position_column = _column_index(headers, "pos", "position")
    team_column = _column_index(headers, "team")
    data_rows = table[header_index + 1 :]

    issues: list[dict[str, Any]] = []
    unexpected_numeric_columns: list[str] = []
    for column, header in enumerate(headers):
        key = _header_key(header)
        if column in {player_column, rank_column, position_column, team_column} or not key:
            continue
        if key in RESERVED_RANKING_COLUMNS:
            continue
        numeric = sum(
            _as_float(row[column]) is not None for row in data_rows[:50] if column < len(row)
        )
        if numeric >= 3:
            unexpected_numeric_columns.append(header)
            issues.append(
                {
                    "source": str(path),
                    "row": "header",
                    "reason": "unmatched_numeric_ranking_column",
                    "detail": header,
                }
            )

    rows: list[dict[str, Any]] = []
    skipped = 0
    for row_number, row in enumerate(data_rows, start=header_index + 2):
        if player_column >= len(row) or not row[player_column].strip():
            continue
        explicit_position = (
            _position(row[position_column])
            if position_column is not None and position_column < len(row)
            else None
        )
        player_name, parsed_team, parsed_position = _parse_player_cell(
            row[player_column], explicit_position
        )
        team = (
            row[team_column].strip()
            if team_column is not None and team_column < len(row)
            else parsed_team
        )
        rank = _as_float(row[rank_column]) if rank_column < len(row) else None
        if parsed_position not in SKILL_POSITIONS or not player_name or rank is None:
            skipped += 1
            excluded_position = (
                _excluded_ranking_position(row[position_column])
                if position_column is not None and position_column < len(row)
                else _excluded_ranking_position(row[player_column])
            )
            issues.append(
                {
                    "source": str(path),
                    "row": row_number,
                    "reason": (
                        "excluded_non_skill_position"
                        if excluded_position
                        else "unusable_ranking_player"
                    ),
                    "detail": (
                        f"{row[player_column]} ({excluded_position})"
                        if excluded_position
                        else row[player_column]
                    ),
                }
            )
            continue
        rows.append(
            {
                "expert_name": SELECTED_ECR_EXPERT,
                "player_name": player_name,
                "team": team,
                "position": parsed_position,
                "expert_rank": rank,
            }
        )
    if not rows:
        raise ValueError(f"{path} did not contain any usable selected-consensus rankings")
    expert_names = sorted(record.expert_name for record in selected_experts.values())
    return rows, {
        "path": str(path),
        "aggregation_mode": "fantasypros_selected_ecr",
        "matched_experts": expert_names,
        "rankings_per_expert": {SELECTED_ECR_EXPERT: len(rows)},
        "unmatched_expert_columns": unexpected_numeric_columns,
        "skipped_rows": skipped,
        "selection_embedded_in_export": False,
        "selection_note": (
            "FantasyPros' selected-consensus CSV does not list its contributing experts; "
            "matched_experts are declared by the separate current export-pool file."
        ),
    }, issues


def load_fantasypros_rankings(
    path: str | Path,
    accuracy: Mapping[str, AccuracyRecord],
    mode: str = "auto",
    selected_experts: Mapping[str, AccuracyRecord] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any], list[dict[str, Any]]]:
    if mode not in {"auto", "matrix", "selected-ecr"}:
        raise ValueError("rankings mode must be auto, matrix, or selected-ecr")
    if mode in {"auto", "matrix"}:
        try:
            rows, metadata, issues = load_fantasypros_rankings_matrix(path, accuracy)
            metadata["aggregation_mode"] = "roster_theory_weighted_matrix"
            metadata["selection_embedded_in_export"] = True
            return rows, metadata, issues
        except ValueError as error:
            if mode == "matrix" or "does not look like" not in str(error):
                raise
    return load_fantasypros_selected_ecr(path, selected_experts or accuracy)


def _projection_position(path: str | Path, headers: Sequence[str], rows: Sequence[Sequence[str]]) -> str:
    position_column = _column_index(headers, "pos", "position")
    if position_column is not None:
        for row in rows[:10]:
            if position_column < len(row) and (position := _position(row[position_column])):
                return position
    filename = Path(path).stem.lower()
    for position in SKILL_POSITIONS:
        if re.search(rf"(?:^|[^a-z]){position.lower()}(?:[^a-z]|$)", filename):
            return position
    raise ValueError(f"Cannot infer projection position from {path}; include QB, RB, WR, or TE in the filename")


def _indices(headers: Sequence[str], *names: str) -> list[int]:
    wanted = {_header_key(name) for name in names}
    return [index for index, value in enumerate(headers) if _header_key(value) in wanted]


def _value(row: Sequence[str], indices: Sequence[int], occurrence: int = 0) -> float:
    if occurrence >= len(indices) or indices[occurrence] >= len(row):
        return 0.0
    return _as_float(row[indices[occurrence]]) or 0.0


def _projection_stats(position: str, headers: Sequence[str], row: Sequence[str]) -> dict[str, float]:
    attempts = _indices(headers, "att", "attempts")
    yards = _indices(headers, "yds", "yards")
    touchdowns = _indices(headers, "td", "tds", "touchdowns")
    interceptions = _indices(headers, "int", "ints", "interceptions")
    receptions = _indices(headers, "rec", "receptions")
    fumbles = _indices(headers, "fl", "fumbles lost", "fumbles_lost")
    stats: dict[str, float] = {"fum_lost": _value(row, fumbles)}
    if position == "QB":
        stats.update(
            pass_yd=_value(row, yards, 0),
            pass_td=_value(row, touchdowns, 0),
            pass_int=_value(row, interceptions, 0),
            rush_yd=_value(row, yards, 1),
            rush_td=_value(row, touchdowns, 1),
        )
    elif position == "RB":
        stats.update(
            rush_yd=_value(row, yards, 0),
            rush_td=_value(row, touchdowns, 0),
            rec=_value(row, receptions, 0),
            rec_yd=_value(row, yards, 1),
            rec_td=_value(row, touchdowns, 1),
        )
    elif position == "WR":
        stats.update(
            rec=_value(row, receptions, 0),
            rec_yd=_value(row, yards, 0),
            rec_td=_value(row, touchdowns, 0),
            rush_yd=_value(row, yards, 1),
            rush_td=_value(row, touchdowns, 1),
        )
    else:
        stats.update(
            rec=_value(row, receptions, 0),
            rec_yd=_value(row, yards, 0),
            rec_td=_value(row, touchdowns, 0),
        )
    return stats


def load_fantasypros_projections(
    paths: Iterable[str | Path], scoring_settings: Mapping[str, Any]
) -> tuple[dict[tuple[str, str], dict[str, Any]], dict[str, Any], list[dict[str, Any]]]:
    projections: dict[tuple[str, str], dict[str, Any]] = {}
    issues: list[dict[str, Any]] = []
    files: list[dict[str, Any]] = []
    for path in paths:
        table = _read_table(path)
        header_index = next(
            (index for index, row in enumerate(table[:12]) if _column_index(row, "player", "player name") is not None),
            None,
        )
        if header_index is None:
            raise ValueError(f"{path} is missing a Player column")
        headers = table[header_index]
        rows = table[header_index + 1 :]
        position = _projection_position(path, headers, rows)
        player_column = _column_index(headers, "player", "player name")
        assert player_column is not None
        team_column = _column_index(headers, "team")
        loaded = 0
        for row_number, row in enumerate(rows, start=header_index + 2):
            if player_column >= len(row) or not row[player_column].strip():
                continue
            player_name, parsed_team, _ = _parse_player_cell(row[player_column], position)
            team = row[team_column].strip() if team_column is not None and team_column < len(row) else parsed_team
            stats = _projection_stats(position, headers, row)
            if not player_name or not any(stats.values()):
                issues.append(
                    {
                        "source": str(path),
                        "row": row_number,
                        "reason": "unusable_projection_row",
                        "detail": row[player_column],
                    }
                )
                continue
            projections[(normalize_name(player_name), position)] = {
                "player_name": player_name,
                "team": team,
                "position": position,
                "projected_points": score_projection(stats, scoring_settings),
                "stats": stats,
            }
            loaded += 1
        files.append({"path": str(path), "position": position, "players": loaded})
    return projections, {"files": files, "player_count": len(projections)}, issues


def load_fantasypros_adp(
    path: str | Path,
) -> tuple[dict[tuple[str, str | None], dict[str, Any]], dict[str, Any], list[dict[str, Any]]]:
    table = _read_table(path)
    header_index = next(
        (index for index, row in enumerate(table[:12]) if _column_index(row, "player", "player name", "player (bye)") is not None),
        None,
    )
    if header_index is None:
        raise ValueError(f"{path} is missing a Player column")
    headers = table[header_index]
    player_column = _column_index(headers, "player", "player name", "player (bye)")
    position_column = _column_index(headers, "pos", "position")
    team_column = _column_index(headers, "team")
    assert player_column is not None

    adp_column = _column_index(headers, "avg", "average", "adp", "overall adp")
    if adp_column is None:
        raise ValueError(f"{path} is missing an AVG or ADP column with the player's actual average draft position")
    adp: dict[tuple[str, str | None], dict[str, Any]] = {}
    issues: list[dict[str, Any]] = []
    for row_number, row in enumerate(table[header_index + 1 :], start=header_index + 2):
        if player_column >= len(row) or not row[player_column].strip():
            continue
        explicit_position = _position(row[position_column]) if position_column is not None and position_column < len(row) else None
        player_name, parsed_team, parsed_position = _parse_player_cell(row[player_column], explicit_position)
        team = row[team_column].strip() if team_column is not None and team_column < len(row) else parsed_team
        value = _as_float(row[adp_column]) if adp_column < len(row) else None
        if not player_name or value is None:
            issues.append(
                {"source": str(path), "row": row_number, "reason": "unusable_adp_row", "detail": row[player_column]}
            )
            continue
        adp[(normalize_name(player_name), parsed_position)] = {
            "player_name": player_name,
            "team": team,
            "position": parsed_position,
            "adp": value,
        }
    return adp, {"path": str(path), "adp_column": headers[adp_column], "player_count": len(adp)}, issues


def _lookup_join(
    values: Mapping[tuple[str, str | None], Mapping[str, Any]], player_name: str, position: str
) -> Mapping[str, Any] | None:
    exact = values.get((normalize_name(player_name), position))
    if exact is not None:
        return exact
    candidates = [value for (name, _), value in values.items() if name == normalize_name(player_name)]
    return candidates[0] if len(candidates) == 1 else None


def _sleeper_candidates(players: Mapping[str, Mapping[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    by_name: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for sleeper_id, player in players.items():
        positions = [str(value).upper() for value in (player.get("fantasy_positions") or [])]
        primary = str(player.get("position") or "").upper()
        if primary and primary not in positions:
            positions.append(primary)
        if not any(position in SKILL_POSITIONS for position in positions):
            continue
        names = {
            str(player.get("full_name") or "").strip(),
            f"{player.get('first_name', '')} {player.get('last_name', '')}".strip(),
            str(player.get("search_full_name") or "").strip(),
        }
        candidate = {
            "sleeper_id": str(sleeper_id),
            "player_name": str(player.get("full_name") or "").strip(),
            "team": str(player.get("team") or "").upper(),
            "positions": positions,
        }
        for name in names:
            if name:
                by_name[normalize_name(name)].append(candidate)
    return by_name


def _match_sleeper_player(
    player_name: str,
    position: str,
    team: str | None,
    candidates_by_name: Mapping[str, Sequence[Mapping[str, Any]]],
    overrides: Mapping[tuple[str, str], str],
) -> tuple[str | None, str, list[Mapping[str, Any]]]:
    override = overrides.get((normalize_name(player_name), position))
    if override:
        return override, "override", []
    candidates = [
        candidate
        for candidate in candidates_by_name.get(normalize_name(player_name), [])
        if position in candidate.get("positions", [])
    ]
    unique = {str(candidate["sleeper_id"]): candidate for candidate in candidates}
    candidates = list(unique.values())
    if len(candidates) == 1:
        return str(candidates[0]["sleeper_id"]), "matched", candidates
    normalized_team = str(team or "").upper().replace("JAC", "JAX")
    team_matches = [
        candidate
        for candidate in candidates
        if str(candidate.get("team") or "").upper().replace("JAC", "JAX") == normalized_team
    ]
    if normalized_team and len(team_matches) == 1:
        return str(team_matches[0]["sleeper_id"]), "matched_team", candidates
    return None, "ambiguous" if candidates else "unmatched", candidates


def load_player_overrides(path: str | Path | None) -> dict[tuple[str, str], str]:
    if path is None:
        return {}
    with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    required = {"player_name", "position", "sleeper_id"}
    missing = required - set(rows[0] if rows else {})
    if missing:
        raise ValueError(f"Player override CSV is missing columns: {', '.join(sorted(missing))}")
    return {
        (normalize_name(str(row["player_name"])), str(row["position"]).upper()): str(row["sleeper_id"]).strip()
        for row in rows
        if str(row.get("sleeper_id") or "").strip()
    }


def build_manual_board(
    *,
    rankings_path: str | Path,
    projection_paths: Iterable[str | Path],
    adp_path: str | Path,
    scoring_settings: Mapping[str, Any],
    roster_positions: Iterable[str],
    team_count: int,
    historical_accuracy: Mapping[str, AccuracyRecord],
    selected_experts: Mapping[str, AccuracyRecord] | None = None,
    sleeper_players: Mapping[str, Mapping[str, Any]],
    player_overrides: Mapping[tuple[str, str], str] | None = None,
    rankings_mode: str = "auto",
    shrink_to_ecr: float = 0.25,
    max_expert_share: float = 0.20,
) -> ManualImportResult:
    ranking_rows, rankings_metadata, ranking_issues = load_fantasypros_rankings(
        rankings_path, historical_accuracy, rankings_mode, selected_experts
    )
    projections, projections_metadata, projection_issues = load_fantasypros_projections(
        projection_paths, scoring_settings
    )
    adp, adp_metadata, adp_issues = load_fantasypros_adp(adp_path)
    issues = ranking_issues + projection_issues + adp_issues
    candidates_by_name = _sleeper_candidates(sleeper_players)
    overrides = dict(player_overrides or {})

    player_enrichment: dict[tuple[str, str], dict[str, Any]] = {}
    for row in ranking_rows:
        key = (normalize_name(str(row["player_name"])), str(row["position"]))
        if key in player_enrichment:
            continue
        projection = _lookup_join(projections, str(row["player_name"]), str(row["position"]))
        market_adp = _lookup_join(adp, str(row["player_name"]), str(row["position"]))
        sleeper_id, match_status, candidates = _match_sleeper_player(
            str(row["player_name"]),
            str(row["position"]),
            str(row.get("team") or ""),
            candidates_by_name,
            overrides,
        )
        player_enrichment[key] = {
            "projected_points": projection.get("projected_points") if projection else None,
            "adp": market_adp.get("adp") if market_adp else None,
            "sleeper_id": sleeper_id,
            "match_status": match_status,
            "match_candidates": candidates,
        }

    for row in ranking_rows:
        enriched = player_enrichment[(normalize_name(str(row["player_name"])), str(row["position"]))]
        row["projected_points"] = enriched["projected_points"]
        row["adp"] = enriched["adp"]
        row["sleeper_id"] = enriched["sleeper_id"]

    accuracy_for_board = dict(historical_accuracy)
    if rankings_metadata["aggregation_mode"] == "fantasypros_selected_ecr":
        accuracy_for_board[normalize_name(SELECTED_ECR_EXPERT)] = AccuracyRecord(
            SELECTED_ECR_EXPERT, 1.0, {}
        )
    board = weighted_consensus(
        ranking_rows,
        accuracy_for_board,
        shrink_to_ecr=shrink_to_ecr,
        max_expert_share=max_expert_share,
    )
    match_report: list[dict[str, Any]] = []
    for player in board:
        key = (normalize_name(str(player["player_name"])), str(player["position"]))
        enriched = player_enrichment[key]
        player["match_status"] = enriched["match_status"]
        match_report.append(
            {
                "player_name": player["player_name"],
                "team": player.get("team"),
                "position": player["position"],
                "rank_score": player["rank_score"],
                "match_status": enriched["match_status"],
                "sleeper_id": enriched["sleeper_id"],
                "candidate_sleeper_ids": "|".join(
                    str(candidate.get("sleeper_id")) for candidate in enriched["match_candidates"]
                ),
                "candidate_names": "|".join(
                    str(candidate.get("player_name")) for candidate in enriched["match_candidates"]
                ),
            }
        )

    projected_board = [player for player in board if player.get("projected_points") is not None]
    baselines = starter_baselines(projected_board, roster_positions, team_count)
    if baselines:
        board = add_vbd(board, baselines)

    evaluation = sorted(board, key=lambda player: float(player.get("rank_score") or 9999))[:180]
    evaluation_count = len(evaluation)
    projection_coverage = (
        sum(player.get("projected_points") is not None for player in evaluation) / evaluation_count
        if evaluation_count else 0.0
    )
    adp_coverage = (
        sum(player.get("adp") is not None for player in evaluation) / evaluation_count
        if evaluation_count else 0.0
    )
    match_coverage = (
        sum(player.get("sleeper_id") not in (None, "") for player in evaluation) / evaluation_count
        if evaluation_count else 0.0
    )
    experts = rankings_metadata["matched_experts"]
    checks = {
        "at_least_five_current_export_experts": len(experts) >= 5,
        "at_least_150_ranked_skill_players": len(board) >= 150,
        "all_replacement_baselines": set(SKILL_POSITIONS).issubset(baselines),
        "top_180_projection_coverage_at_least_90_percent": projection_coverage >= 0.90,
        "top_180_adp_coverage_at_least_90_percent": adp_coverage >= 0.90,
        "top_180_sleeper_match_coverage_100_percent": match_coverage == 1.0,
        "no_unmatched_expert_columns": not rankings_metadata["unmatched_expert_columns"],
    }
    metadata = {
        "source": "fantasypros_pro_manual_export",
        "sample_only": not all(checks.values()),
        "draft_ready": all(checks.values()),
        "rankings": rankings_metadata,
        "projections": projections_metadata,
        "adp": adp_metadata,
        "player_count": len(board),
        "players_with_projections": len(projected_board),
        "replacement_baselines": baselines,
        "coverage": {
            "evaluated_players": evaluation_count,
            "projection": round(projection_coverage, 4),
            "adp": round(adp_coverage, 4),
            "sleeper_match": round(match_coverage, 4),
        },
        "match_status_counts": dict(sorted(Counter(row["match_status"] for row in match_report).items())),
        "checks": checks,
        "issue_count": len(issues),
    }
    return ManualImportResult(board, metadata, match_report, issues)


def load_sleeper_players_file(path: str | Path) -> dict[str, dict[str, Any]]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object keyed by Sleeper player ID")
    return {str(key): player for key, player in value.items() if isinstance(player, dict)}
