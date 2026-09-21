from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Collection, Mapping

from roster_theory.core.errors import (
    CoverageIncomplete,
    IdentityIncomplete,
    ProviderCapabilityMissing,
    SourceUnavailable,
    StaleData,
)
from roster_theory.core.models import LeagueRules
from roster_theory.core.provenance import DataStamp, stable_hash
from roster_theory.providers.base import TradeMarketSource
from roster_theory.providers.cache import atomic_write_json, is_fresh
from roster_theory.stats_guy_fantasy import StatsGuyFantasyError


STATS_GUY_PROVIDER = "Stats Guy Fantasy"
STATS_GUY_SOURCE_URL = "https://api.statsguyfantasy.com/api/v1/players"
STATS_GUY_TERMS_URL = "https://statsguyfantasy.com/terms"
STATS_GUY_ATTRIBUTION = (
    "Trade values by Stats Guy Fantasy (https://statsguyfantasy.com)"
)
SUPPORTED_TRADE_MARKET_FORMATS = frozenset({"non_sf_redraft", "sf_redraft"})
SKILL_POSITIONS = frozenset({"QB", "RB", "WR", "TE"})


@dataclass(frozen=True, slots=True)
class TradeMarketPrice:
    player_id: str
    position: str
    overall_rank: int
    position_rank: int
    value: float
    provider_change_7d: float | None = None
    provider_change_30d: float | None = None
    previous_board_change: float | None = None


@dataclass(frozen=True, slots=True)
class TradeMarketBoard:
    schema_version: int
    mode: str
    provider: str
    format: str
    as_of: datetime
    captured_at: datetime
    season: int
    week: int | None
    scoring_variant: str
    te_premium_variant: str
    league_format_compatible: bool
    league_scoring_exact: bool
    prices: tuple[TradeMarketPrice, ...]
    source_total: int
    normalized_count: int
    complete: bool
    source_url: str
    attribution: str
    authorization_basis: str
    warnings: tuple[str, ...]
    stamp: DataStamp
    evidence_hash: str


@dataclass(frozen=True, slots=True)
class TradeMarketEvidence:
    mode: str
    board: TradeMarketBoard | None
    chart_price_available: bool
    chart_change_available: bool
    chart_fairness_available: bool
    consolidation_premium_available: bool
    warnings: tuple[str, ...]
    prior_board: TradeMarketBoard | None = None


def trade_market_format(league: LeagueRules) -> str:
    slots = tuple(slot.upper() for slot in league.roster_positions)
    if (
        "SUPER_FLEX" in slots
        or "SUPERFLEX" in slots
        or "2QB" in slots
        or slots.count("QB") >= 2
    ):
        return "sf_redraft"
    return "non_sf_redraft"


def _aware_datetime(value: Any, label: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        raw = str(value or "").strip()
        if not raw:
            raise ValueError(f"{label} is required")
        if raw.endswith("Z"):
            raw = f"{raw[:-1]}+00:00"
        parsed = datetime.fromisoformat(raw)
    if parsed.tzinfo is None:
        raise ValueError(f"{label} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _publication_datetime(value: Any) -> datetime:
    raw = str(value or "").strip()
    if len(raw) == 10:
        try:
            return datetime.fromisoformat(raw).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return _aware_datetime(value, "publication_at")


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")
    return value


def _optional_number(value: Any, label: str) -> float | None:
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        raise ValueError(f"{label} must be numeric")
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be numeric") from exc
    if not math.isfinite(parsed):
        raise ValueError(f"{label} must be finite")
    return parsed


def _number(value: Any, label: str) -> float:
    parsed = _optional_number(value, label)
    if parsed is None:
        raise ValueError(f"{label} is required")
    return parsed


def _positive_integer(value: Any, label: str) -> int:
    parsed = _number(value, label)
    integer = int(parsed)
    if parsed != integer or integer < 1:
        raise ValueError(f"{label} must be a positive integer")
    return integer


def _format_field(row: Mapping[str, Any], field: str, format_name: str) -> Any:
    values = row.get(field)
    if values is None:
        return None
    return _mapping(values, field).get(format_name)


def _provider_change(
    row: Mapping[str, Any], format_name: str, window: str, player_id: str
) -> float | None:
    value = _format_field(row, "valueChange", format_name)
    if value is None:
        return None
    return _optional_number(
        _mapping(value, f"valueChange.{format_name}").get(window),
        f"{player_id} valueChange.{format_name}.{window}",
    )


def _validate_freshness(
    as_of: datetime,
    *,
    now: datetime,
    maximum_age: timedelta,
) -> int:
    if maximum_age <= timedelta(0):
        raise ValueError("Trade-market maximum age must be positive")
    if not is_fresh(as_of, maximum_age, now=now):
        raise StaleData(
            "Trade-market provider calculation is stale or future-dated: "
            f"{as_of.isoformat()}"
        )
    return int((now - as_of).total_seconds())


def _required_coverage(
    prices: Collection[TradeMarketPrice], required_player_ids: Collection[str]
) -> None:
    available = {row.player_id for row in prices}
    missing = sorted({str(player_id) for player_id in required_player_ids} - available)
    if missing:
        raise CoverageIncomplete(
            "Trade-market board is missing required Sleeper IDs: " + ", ".join(missing)
        )


def _previous_values(
    previous_board: TradeMarketBoard | None,
    *,
    format_name: str,
    as_of: datetime,
) -> dict[str, float]:
    if previous_board is None:
        return {}
    if previous_board.format != format_name:
        raise CoverageIncomplete("Prior trade-market board uses a different format")
    if previous_board.as_of >= as_of:
        raise CoverageIncomplete(
            "Prior trade-market board must precede the current provider calculation"
        )
    return {row.player_id: row.value for row in previous_board.prices}


def _board_hash_payload(board: TradeMarketBoard) -> dict[str, Any]:
    payload = asdict(board)
    payload.pop("evidence_hash", None)
    return payload


def _sign_board(board: TradeMarketBoard) -> TradeMarketBoard:
    return replace(board, evidence_hash=stable_hash(_board_hash_payload(board)))


def _evidence(board: TradeMarketBoard) -> TradeMarketEvidence:
    return TradeMarketEvidence(
        mode=board.mode,
        board=board,
        chart_price_available=True,
        chart_change_available=any(
            row.provider_change_7d is not None
            or row.provider_change_30d is not None
            or row.previous_board_change is not None
            for row in board.prices
        ),
        chart_fairness_available=True,
        consolidation_premium_available=True,
        warnings=board.warnings,
    )


def normalize_stats_guy_players(
    value: Mapping[str, Any],
    *,
    league: LeagueRules,
    required_player_ids: Collection[str] = (),
    current_week: int | None = None,
    captured_at: datetime | None = None,
    now: datetime | None = None,
    maximum_age: timedelta = timedelta(hours=36),
    previous_board: TradeMarketBoard | None = None,
) -> TradeMarketBoard:
    captured = captured_at or datetime.now(timezone.utc)
    current = now or captured
    if captured.tzinfo is None or current.tzinfo is None:
        raise ValueError("Trade-market timestamps must be timezone-aware")
    captured = captured.astimezone(timezone.utc)
    current = current.astimezone(timezone.utc)
    format_name = trade_market_format(league)
    as_of_values = _mapping(value.get("valuesAsOf"), "valuesAsOf")
    as_of = _aware_datetime(as_of_values.get(format_name), f"valuesAsOf.{format_name}")
    freshness_seconds = _validate_freshness(
        as_of,
        now=current,
        maximum_age=maximum_age,
    )
    rows = value.get("players")
    if not isinstance(rows, list):
        raise ValueError("Stats Guy Fantasy players must be a list")
    source_total = _positive_integer(value.get("total"), "Stats Guy Fantasy total")
    if source_total != len(rows):
        raise CoverageIncomplete(
            "Stats Guy Fantasy bulk response is partial: "
            f"declared {source_total}, received {len(rows)}"
        )
    prior = _previous_values(previous_board, format_name=format_name, as_of=as_of)
    seen_ids: set[str] = set()
    prices: list[TradeMarketPrice] = []
    for item in rows:
        row = _mapping(item, "Stats Guy Fantasy player")
        player_id = str(row.get("id") or "").strip()
        if not player_id:
            raise IdentityIncomplete("Stats Guy Fantasy row is missing a Sleeper ID")
        if player_id in seen_ids:
            raise IdentityIncomplete(
                f"Duplicate Stats Guy Fantasy Sleeper ID: {player_id}"
            )
        seen_ids.add(player_id)
        raw_value = _format_field(row, "value", format_name)
        if raw_value is None:
            continue
        position = str(row.get("position") or "").upper()
        if position not in SKILL_POSITIONS:
            raise CoverageIncomplete(
                f"Trade-market value for {player_id} has unsupported position {position or 'NONE'}"
            )
        market_value = _number(raw_value, f"{player_id} {format_name} value")
        if market_value < 0:
            raise ValueError(f"{player_id} {format_name} value cannot be negative")
        previous_value = prior.get(player_id)
        prices.append(
            TradeMarketPrice(
                player_id=player_id,
                position=position,
                overall_rank=_positive_integer(
                    _format_field(row, "rank", format_name),
                    f"{player_id} {format_name} rank",
                ),
                position_rank=_positive_integer(
                    _format_field(row, "positionRank", format_name),
                    f"{player_id} {format_name} position rank",
                ),
                value=market_value,
                provider_change_7d=_provider_change(
                    row, format_name, "days7", player_id
                ),
                provider_change_30d=_provider_change(
                    row, format_name, "days30", player_id
                ),
                previous_board_change=(
                    market_value - previous_value
                    if previous_value is not None
                    else None
                ),
            )
        )
    if not prices:
        raise CoverageIncomplete(
            f"Stats Guy Fantasy returned no {format_name} trade values"
        )
    _required_coverage(prices, required_player_ids)
    ordered = tuple(sorted(prices, key=lambda row: (row.overall_rank, row.player_id)))
    warnings = (
        "TRADE-MARKET RECEPTION BLEND: provider values are not league-exact PPR, half-PPR, or standard prices",
        "TRADE-MARKET TEP BLEND: provider values do not expose a league-exact tight-end premium variant",
    )
    stamp = DataStamp(
        source="stats_guy_fantasy",
        endpoint=STATS_GUY_SOURCE_URL,
        captured_at=captured,
        season=league.season,
        week=current_week,
        scoring_label=format_name,
        parameter_hash=stable_hash({"format": format_name}),
        payload_hash=stable_hash(value),
        cache_status="provider_bulk_sync",
        freshness_seconds=freshness_seconds,
        fresh=True,
        export_restriction=STATS_GUY_TERMS_URL,
        warnings=warnings,
    )
    board = TradeMarketBoard(
        schema_version=1,
        mode="STATS_GUY_FANTASY_API",
        provider=STATS_GUY_PROVIDER,
        format=format_name,
        as_of=as_of,
        captured_at=captured,
        season=league.season,
        week=current_week,
        scoring_variant="RECEPTION_MARKET_BLEND",
        te_premium_variant="TEP_MARKET_BLEND",
        league_format_compatible=True,
        league_scoring_exact=False,
        prices=ordered,
        source_total=source_total,
        normalized_count=len(ordered),
        complete=True,
        source_url=STATS_GUY_SOURCE_URL,
        attribution=STATS_GUY_ATTRIBUTION,
        authorization_basis=STATS_GUY_TERMS_URL,
        warnings=warnings,
        stamp=stamp,
        evidence_hash="",
    )
    return _sign_board(board)


def _import_prices(
    rows: Any,
    *,
    previous_board: TradeMarketBoard | None,
    format_name: str,
    as_of: datetime,
) -> tuple[TradeMarketPrice, ...]:
    if not isinstance(rows, list):
        raise ValueError("Authorized trade-market import rows must be a list")
    prior = _previous_values(previous_board, format_name=format_name, as_of=as_of)
    seen: set[str] = set()
    prices: list[TradeMarketPrice] = []
    for item in rows:
        row = _mapping(item, "Authorized trade-market import row")
        player_id = str(row.get("player_id") or "").strip()
        if not player_id:
            raise IdentityIncomplete(
                "Authorized trade-market import row is missing a Sleeper player_id"
            )
        if player_id in seen:
            raise IdentityIncomplete(
                f"Duplicate authorized trade-market Sleeper ID: {player_id}"
            )
        seen.add(player_id)
        position = str(row.get("position") or "").upper()
        if position not in SKILL_POSITIONS:
            raise CoverageIncomplete(
                f"Authorized trade-market row for {player_id} has unsupported position"
            )
        market_value = _number(row.get("value"), f"{player_id} value")
        if market_value < 0:
            raise ValueError(f"{player_id} value cannot be negative")
        previous_value = prior.get(player_id)
        prices.append(
            TradeMarketPrice(
                player_id=player_id,
                position=position,
                overall_rank=_positive_integer(
                    row.get("overall_rank"), f"{player_id} overall_rank"
                ),
                position_rank=_positive_integer(
                    row.get("position_rank"), f"{player_id} position_rank"
                ),
                value=market_value,
                provider_change_7d=_optional_number(
                    row.get("provider_change_7d"),
                    f"{player_id} provider_change_7d",
                ),
                provider_change_30d=_optional_number(
                    row.get("provider_change_30d"),
                    f"{player_id} provider_change_30d",
                ),
                previous_board_change=(
                    _optional_number(
                        row.get("previous_board_change"),
                        f"{player_id} previous_board_change",
                    )
                    if previous_value is None
                    else market_value - previous_value
                ),
            )
        )
    return tuple(sorted(prices, key=lambda row: (row.overall_rank, row.player_id)))


def normalize_authorized_import(
    value: Mapping[str, Any],
    *,
    league: LeagueRules,
    required_player_ids: Collection[str] = (),
    current_week: int | None = None,
    now: datetime | None = None,
    maximum_age: timedelta = timedelta(hours=36),
    previous_board: TradeMarketBoard | None = None,
) -> TradeMarketBoard:
    provider = str(value.get("provider") or "").strip()
    authorization_basis = str(value.get("authorization_basis") or "").strip()
    source_url = str(value.get("source_url") or "authorized-local-import").strip()
    attribution = str(value.get("attribution") or f"Trade values by {provider}").strip()
    for label, raw in (
        ("provider", provider),
        ("authorization_basis", authorization_basis),
    ):
        if not raw:
            raise ProviderCapabilityMissing(
                f"Authorized trade-market import requires {label} provenance"
            )
    season = _positive_integer(value.get("season"), "import season")
    if season != league.season:
        raise ProviderCapabilityMissing(
            f"Trade-market import season {season} does not match league {league.season}"
        )
    format_name = str(value.get("format") or "").strip()
    if format_name not in SUPPORTED_TRADE_MARKET_FORMATS:
        raise ProviderCapabilityMissing("Authorized import has an unsupported format")
    expected_format = trade_market_format(league)
    if format_name != expected_format:
        raise ProviderCapabilityMissing(
            f"Trade-market import format {format_name} does not match {expected_format}"
        )
    scoring_variant = str(value.get("scoring_variant") or "UNSPECIFIED").strip()
    te_premium_variant = str(value.get("te_premium_variant") or "UNSPECIFIED").strip()
    as_of = _publication_datetime(
        value.get("publication_at") or value.get("publication_date")
    )
    captured_at = _aware_datetime(value.get("exported_at"), "exported_at")
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("Trade-market now timestamp must be timezone-aware")
    current = current.astimezone(timezone.utc)
    if captured_at < as_of:
        raise ValueError("Authorized import exported_at precedes publication_at")
    if captured_at > current:
        raise StaleData("Authorized import exported_at is future-dated")
    week_raw = value.get("week")
    week = _positive_integer(week_raw, "import week") if week_raw is not None else None
    if current_week is not None and week is not None and week != current_week:
        raise StaleData(
            f"Trade-market import week {week} does not match current week {current_week}"
        )
    freshness_seconds = _validate_freshness(
        as_of,
        now=current,
        maximum_age=maximum_age,
    )
    prices = _import_prices(
        value.get("rows"),
        previous_board=previous_board,
        format_name=format_name,
        as_of=as_of,
    )
    if not prices:
        raise CoverageIncomplete("Authorized trade-market import has no rows")
    declared_count = _positive_integer(
        value.get("declared_count"), "import declared_count"
    )
    if declared_count != len(prices):
        raise CoverageIncomplete(
            "Authorized trade-market import is partial: "
            f"declared {declared_count}, received {len(prices)}"
        )
    _required_coverage(prices, required_player_ids)
    warnings = (
        f"AUTHORIZED LOCAL IMPORT: {provider}; authorization retained in provenance",
        f"TRADE-MARKET RECEPTION VARIANT: {scoring_variant}",
        f"TRADE-MARKET TEP VARIANT: {te_premium_variant}",
    )
    stamp = DataStamp(
        source=provider,
        endpoint=source_url,
        captured_at=captured_at,
        season=season,
        week=week,
        scoring_label=format_name,
        parameter_hash=stable_hash(
            {
                "format": format_name,
                "scoring_variant": scoring_variant,
                "te_premium_variant": te_premium_variant,
            }
        ),
        payload_hash=stable_hash(value),
        cache_status="authorized_local_import",
        freshness_seconds=freshness_seconds,
        fresh=True,
        export_restriction=authorization_basis,
        warnings=warnings,
    )
    board = TradeMarketBoard(
        schema_version=1,
        mode="AUTHORIZED_LOCAL_IMPORT",
        provider=provider,
        format=format_name,
        as_of=as_of,
        captured_at=captured_at,
        season=season,
        week=week,
        scoring_variant=scoring_variant,
        te_premium_variant=te_premium_variant,
        league_format_compatible=True,
        league_scoring_exact=bool(value.get("league_scoring_exact", False)),
        prices=prices,
        source_total=declared_count,
        normalized_count=len(prices),
        complete=True,
        source_url=source_url,
        attribution=attribution,
        authorization_basis=authorization_basis,
        warnings=warnings,
        stamp=stamp,
        evidence_hash="",
    )
    return _sign_board(board)


def save_trade_market_board(
    board: TradeMarketBoard, path: str | Path
) -> Path:
    """Save normalized provider evidence to a caller-selected ignored location."""

    return atomic_write_json(path, board)


def _stamp_from_dict(value: Mapping[str, Any]) -> DataStamp:
    return DataStamp(
        source=str(value["source"]),
        endpoint=str(value["endpoint"]),
        captured_at=_aware_datetime(value["captured_at"], "stamp captured_at"),
        season=value.get("season"),
        week=value.get("week"),
        horizon_start=value.get("horizon_start"),
        horizon_end=value.get("horizon_end"),
        scoring_label=value.get("scoring_label"),
        scoring_hash=value.get("scoring_hash"),
        parameter_hash=value.get("parameter_hash"),
        payload_hash=value.get("payload_hash"),
        cache_status=str(value.get("cache_status") or "miss"),
        freshness_seconds=value.get("freshness_seconds"),
        fresh=value.get("fresh"),
        export_restriction=value.get("export_restriction"),
        warnings=tuple(value.get("warnings") or ()),
    )


def load_trade_market_board(path: str | Path) -> TradeMarketBoard:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise ValueError("Trade-market board must be a JSON object")
    if int(value.get("schema_version") or 0) != 1:
        raise ValueError("Unsupported trade-market board schema version")
    prices = tuple(
        TradeMarketPrice(
            player_id=str(row["player_id"]),
            position=str(row["position"]),
            overall_rank=int(row["overall_rank"]),
            position_rank=int(row["position_rank"]),
            value=float(row["value"]),
            provider_change_7d=(
                float(row["provider_change_7d"])
                if row.get("provider_change_7d") is not None
                else None
            ),
            provider_change_30d=(
                float(row["provider_change_30d"])
                if row.get("provider_change_30d") is not None
                else None
            ),
            previous_board_change=(
                float(row["previous_board_change"])
                if row.get("previous_board_change") is not None
                else None
            ),
        )
        for row in value.get("prices") or ()
    )
    board = TradeMarketBoard(
        schema_version=1,
        mode=str(value["mode"]),
        provider=str(value["provider"]),
        format=str(value["format"]),
        as_of=_aware_datetime(value["as_of"], "as_of"),
        captured_at=_aware_datetime(value["captured_at"], "captured_at"),
        season=int(value["season"]),
        week=(int(value["week"]) if value.get("week") is not None else None),
        scoring_variant=str(value["scoring_variant"]),
        te_premium_variant=str(value["te_premium_variant"]),
        league_format_compatible=bool(value["league_format_compatible"]),
        league_scoring_exact=bool(value["league_scoring_exact"]),
        prices=prices,
        source_total=int(value["source_total"]),
        normalized_count=int(value["normalized_count"]),
        complete=bool(value["complete"]),
        source_url=str(value["source_url"]),
        attribution=str(value["attribution"]),
        authorization_basis=str(value["authorization_basis"]),
        warnings=tuple(value.get("warnings") or ()),
        stamp=_stamp_from_dict(_mapping(value.get("stamp"), "stamp")),
        evidence_hash=str(value.get("evidence_hash") or ""),
    )
    expected_hash = stable_hash(_board_hash_payload(board))
    if not board.evidence_hash or board.evidence_hash != expected_hash:
        raise ValueError("Trade-market board evidence hash mismatch")
    if board.normalized_count != len(board.prices):
        raise CoverageIncomplete("Trade-market replay count does not match its rows")
    return board


def ecr_proxy(reason: str | None = None) -> TradeMarketEvidence:
    warning = "ECR-PROXY: chart prices, changes, fairness, and consolidation premium disabled"
    if reason:
        warning = f"{warning}; {reason}"
    return TradeMarketEvidence(
        mode="ECR-PROXY",
        board=None,
        chart_price_available=False,
        chart_change_available=False,
        chart_fairness_available=False,
        consolidation_premium_available=False,
        warnings=(warning,),
    )


def _archive_board(board: TradeMarketBoard, archive_dir: str | Path | None) -> None:
    if archive_dir is None:
        return
    target = Path(archive_dir) / board.format / f"{board.as_of.date().isoformat()}.json"
    save_trade_market_board(board, target)


def _prior_market_evidence(
    archive_dir: str | Path | None,
    *,
    league: LeagueRules,
    required_player_ids: Collection[str],
    current_week: int | None,
    now: datetime,
    maximum_age: timedelta,
    failures: list[str],
    prior_only: bool = False,
) -> TradeMarketEvidence | None:
    if archive_dir is None:
        return None
    folder = Path(archive_dir) / trade_market_format(league)
    if not folder.is_dir():
        return None
    candidates: list[TradeMarketBoard] = []
    for path in folder.glob("*.json"):
        try:
            board = load_trade_market_board(path)
        except (OSError, ValueError, CoverageIncomplete) as exc:
            failures.append(f"Archived trade chart invalid: {type(exc).__name__}")
            continue
        age = now - board.as_of
        if (
            board.season != league.season
            or board.format != trade_market_format(league)
            or not board.complete
            or not board.league_format_compatible
            or age < timedelta(0)
            or (prior_only and age <= maximum_age)
            or age > timedelta(days=8)
            or (current_week is not None and board.week is not None and board.week > current_week)
        ):
            continue
        if set(required_player_ids) - {row.player_id for row in board.prices}:
            continue
        candidates.append(board)
    if not candidates:
        return None
    source = max(candidates, key=lambda board: (board.as_of, board.captured_at))
    age = now - source.as_of
    if age <= maximum_age:
        warning = (
            f"CACHED_CURRENT_MARKET: live chart unavailable; reused chart from "
            f"{source.as_of.isoformat()}"
        )
        board = _sign_board(replace(
            source,
            warnings=tuple(dict.fromkeys((*source.warnings, warning))),
            stamp=replace(
                source.stamp,
                cache_status="current_archive_hit",
                freshness_seconds=int(age.total_seconds()),
                fresh=True,
                warnings=tuple(dict.fromkeys((*source.stamp.warnings, warning))),
            ),
            evidence_hash="",
        ))
        current = _evidence(board)
        return replace(
            current,
            warnings=tuple(dict.fromkeys((*failures, *current.warnings))),
        )
    warning = (
        f"PRIOR_WEEK_MARKET: indicative chart from {source.as_of.date().isoformat()} "
        "is not current; fairness verdicts and consolidation premium disabled"
    )
    board = _sign_board(replace(
        source,
        mode="PRIOR_WEEK_MARKET",
        prices=tuple(replace(
            price,
            provider_change_7d=None,
            provider_change_30d=None,
            previous_board_change=None,
        ) for price in source.prices),
        warnings=tuple(dict.fromkeys((*source.warnings, warning))),
        stamp=replace(
            source.stamp,
            cache_status="prior_week_archive",
            freshness_seconds=int((now - source.as_of).total_seconds()),
            fresh=False,
            warnings=tuple(dict.fromkeys((*source.stamp.warnings, warning))),
        ),
        evidence_hash="",
    ))
    return TradeMarketEvidence(
        mode="PRIOR_WEEK_MARKET",
        board=board,
        chart_price_available=True,
        chart_change_available=False,
        chart_fairness_available=False,
        consolidation_premium_available=False,
        warnings=tuple(dict.fromkeys((*failures, warning))),
    )


def resolve_trade_market_evidence(
    *,
    league: LeagueRules,
    required_player_ids: Collection[str] = (),
    current_week: int | None = None,
    source: TradeMarketSource | None = None,
    authorized_import_path: str | Path | None = None,
    previous_board: TradeMarketBoard | None = None,
    cache_path: str | Path | None = None,
    archive_dir: str | Path | None = None,
    now: datetime | None = None,
    maximum_age: timedelta = timedelta(hours=36),
    allow_ecr_proxy: bool = True,
) -> TradeMarketEvidence:
    current = now or datetime.now(timezone.utc)
    failures: list[str] = []
    expected_failures = (
        StatsGuyFantasyError,
        SourceUnavailable,
        StaleData,
        IdentityIncomplete,
        CoverageIncomplete,
        ProviderCapabilityMissing,
        OSError,
        json.JSONDecodeError,
        ValueError,
    )
    if source is not None:
        try:
            board = normalize_stats_guy_players(
                source.players(),
                league=league,
                required_player_ids=required_player_ids,
                current_week=current_week,
                captured_at=current,
                now=current,
                maximum_age=maximum_age,
                previous_board=previous_board,
            )
            if cache_path is not None:
                save_trade_market_board(board, cache_path)
            _archive_board(board, archive_dir)
            prior = _prior_market_evidence(
                archive_dir, league=league, required_player_ids=(),
                current_week=current_week, now=current,
                maximum_age=maximum_age, failures=[], prior_only=True,
            )
            return replace(_evidence(board), prior_board=prior.board if prior else None)
        except expected_failures as exc:
            failures.append(f"Stats Guy Fantasy unavailable: {exc}")
    if authorized_import_path is not None:
        try:
            raw = json.loads(Path(authorized_import_path).read_text(encoding="utf-8"))
            board = normalize_authorized_import(
                _mapping(raw, "Authorized trade-market import"),
                league=league,
                required_player_ids=required_player_ids,
                current_week=current_week,
                now=current,
                maximum_age=maximum_age,
                previous_board=previous_board,
            )
            if cache_path is not None:
                save_trade_market_board(board, cache_path)
            _archive_board(board, archive_dir)
            prior = _prior_market_evidence(
                archive_dir, league=league, required_player_ids=(),
                current_week=current_week, now=current,
                maximum_age=maximum_age, failures=[], prior_only=True,
            )
            return replace(_evidence(board), prior_board=prior.board if prior else None)
        except expected_failures as exc:
            failures.append(f"Authorized local import unavailable: {exc}")
    prior = _prior_market_evidence(
        archive_dir,
        league=league,
        required_player_ids=required_player_ids,
        current_week=current_week,
        now=current,
        maximum_age=maximum_age,
        failures=failures,
    )
    if prior is not None:
        return prior
    reason = " | ".join(failures) if failures else "no supported chart source configured"
    if allow_ecr_proxy:
        return ecr_proxy(reason)
    raise ProviderCapabilityMissing(reason)
