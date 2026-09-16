from __future__ import annotations

import csv
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from roster_theory.core.errors import Uncalibrated


class SleeperError(RuntimeError):
    """Raised when Sleeper data cannot be retrieved or validated."""


JsonValue = dict[str, Any] | list[Any]


@dataclass(slots=True)
class SleeperClient:
    base_url: str = "https://api.sleeper.app/v1"
    projections_base_url: str = "https://api.sleeper.com"
    timeout_seconds: float = 15.0
    retries: int = 2
    transport: Callable[[str], JsonValue] | None = None
    last_get_metadata: dict[str, Any] = field(default_factory=dict, init=False)

    def _get(self, path: str, *, fresh: bool = False) -> JsonValue:
        url = f"{self.base_url.rstrip('/')}/{path.lstrip('/')}"
        cache_busted = False
        if fresh:
            # Cloudflare can ignore request revalidation headers for Sleeper's
            # public picks endpoint. A unique, semantically inert query value
            # gives every clock-sensitive poll a fresh cache key.
            separator = "&" if "?" in url else "?"
            url = f"{url}{separator}{urlencode({'roster_theory_fresh': time.time_ns()})}"
            cache_busted = True
        if self.transport is not None:
            started = time.perf_counter()
            value = self.transport(url)
            self.last_get_metadata = {
                "fresh": fresh,
                "cache_busted": cache_busted,
                "cache_status": None,
                "cache_age_seconds": None,
                "elapsed_ms": round((time.perf_counter() - started) * 1000.0, 2),
            }
            return value

        headers = {"User-Agent": "RosterTheory/0.1"}
        if fresh:
            # Sleeper's draft-picks endpoint is otherwise eligible for a
            # 15-second shared-cache response. Revalidate it so the watcher
            # sees picks on a draft clock instead of waiting for CDN expiry.
            headers.update(
                {
                    "Cache-Control": "no-cache",
                    "Pragma": "no-cache",
                }
            )
        request = Request(url, headers=headers)
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                started = time.perf_counter()
                with urlopen(request, timeout=self.timeout_seconds) as response:
                    value = json.loads(response.read().decode("utf-8"))
                    response_headers = getattr(response, "headers", {})
                    cache_age = response_headers.get("Age") if response_headers else None
                    try:
                        parsed_cache_age = (
                            float(cache_age) if cache_age not in (None, "") else None
                        )
                    except (TypeError, ValueError):
                        parsed_cache_age = None
                    self.last_get_metadata = {
                        "fresh": fresh,
                        "cache_busted": cache_busted,
                        "cache_status": (
                            response_headers.get("CF-Cache-Status")
                            if response_headers
                            else None
                        ),
                        "cache_age_seconds": parsed_cache_age,
                        "elapsed_ms": round(
                            (time.perf_counter() - started) * 1000.0, 2
                        ),
                    }
                    return value
            except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
                last_error = exc
                if attempt < self.retries:
                    time.sleep(0.4 * (attempt + 1))
        raise SleeperError(f"Unable to retrieve {url}: {last_error}")

    def league(self, league_id: str) -> dict[str, Any]:
        value = self._get(f"league/{league_id}")
        if not isinstance(value, dict) or not value.get("league_id"):
            raise SleeperError(f"League {league_id} was not found")
        return value

    def league_drafts(self, league_id: str) -> list[dict[str, Any]]:
        value = self._get(f"league/{league_id}/drafts")
        return value if isinstance(value, list) else []

    def league_users(self, league_id: str) -> list[dict[str, Any]]:
        value = self._get(f"league/{league_id}/users")
        return value if isinstance(value, list) else []

    def league_rosters(self, league_id: str) -> list[dict[str, Any]]:
        value = self._get(f"league/{league_id}/rosters")
        return value if isinstance(value, list) else []

    def state(self, sport: str = "nfl") -> dict[str, Any]:
        value = self._get(f"state/{sport}")
        return value if isinstance(value, dict) else {}

    def league_matchups(self, league_id: str, week: int) -> list[dict[str, Any]]:
        value = self._get(f"league/{league_id}/matchups/{int(week)}")
        return value if isinstance(value, list) else []

    def league_transactions(
        self, league_id: str, week: int
    ) -> list[dict[str, Any]]:
        value = self._get(f"league/{league_id}/transactions/{int(week)}")
        return value if isinstance(value, list) else []

    def league_winners_bracket(self, league_id: str) -> list[dict[str, Any]]:
        value = self._get(f"league/{league_id}/winners_bracket")
        return value if isinstance(value, list) else []

    def league_losers_bracket(self, league_id: str) -> list[dict[str, Any]]:
        value = self._get(f"league/{league_id}/losers_bracket")
        return value if isinstance(value, list) else []

    def trending_players(
        self,
        sport: str = "nfl",
        trend_type: str = "add",
        *,
        lookback_hours: int = 24,
        limit: int = 25,
    ) -> list[dict[str, Any]]:
        if trend_type not in {"add", "drop"}:
            raise ValueError("Sleeper trend_type must be 'add' or 'drop'")
        query = urlencode(
            {"lookback_hours": int(lookback_hours), "limit": int(limit)}
        )
        value = self._get(f"players/{sport}/trending/{trend_type}?{query}")
        return value if isinstance(value, list) else []

    def draft(self, draft_id: str) -> dict[str, Any]:
        value = self._get(f"draft/{draft_id}")
        if not isinstance(value, dict) or not value.get("draft_id"):
            raise SleeperError(f"Draft {draft_id} was not found")
        return value

    def draft_picks(self, draft_id: str) -> list[dict[str, Any]]:
        value = self._get(f"draft/{draft_id}/picks", fresh=True)
        return value if isinstance(value, list) else []

    def user_leagues(self, user_id: str, season: str) -> list[dict[str, Any]]:
        value = self._get(f"user/{user_id}/leagues/nfl/{season}")
        return value if isinstance(value, list) else []

    def players(self, sport: str = "nfl") -> dict[str, dict[str, Any]]:
        value = self._get(f"players/{sport}")
        return value if isinstance(value, dict) else {}

    def season_projections(
        self,
        season: int,
        order_by: str,
        season_type: str = "regular",
    ) -> list[dict[str, Any]]:
        query = urlencode({"season_type": season_type, "order_by": order_by})
        url = (
            f"{self.projections_base_url.rstrip('/')}/projections/nfl/"
            f"{int(season)}?{query}"
        )
        if self.transport is not None:
            value = self.transport(url)
        else:
            request = Request(url, headers={"User-Agent": "RosterTheory/0.1"})
            last_error: Exception | None = None
            value: JsonValue | None = None
            for attempt in range(self.retries + 1):
                try:
                    with urlopen(request, timeout=self.timeout_seconds) as response:
                        value = json.loads(response.read().decode("utf-8"))
                    break
                except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
                    last_error = exc
                    if attempt < self.retries:
                        time.sleep(0.4 * (attempt + 1))
            if value is None:
                raise SleeperError(f"Unable to retrieve {url}: {last_error}")
        if not isinstance(value, list):
            raise SleeperError(
                f"Sleeper projections for {season} did not return a list"
            )
        return [row for row in value if isinstance(row, dict)]


LEAGUE_CONFIG_ENV = "ROSTER_THEORY_CONFIG"


def default_league_config_path() -> Path:
    """Return the per-user config path without depending on the repository CWD."""

    configured = os.environ.get(LEAGUE_CONFIG_ENV)
    if configured:
        return Path(configured).expanduser()
    appdata = os.environ.get("APPDATA")
    if os.name == "nt" and appdata:
        return Path(appdata) / "RosterTheory" / "leagues.json"
    xdg_home = os.environ.get("XDG_CONFIG_HOME")
    root = Path(xdg_home).expanduser() if xdg_home else Path.home() / ".config"
    return root / "roster-theory" / "leagues.json"


def resolve_league_config_path(path: str | Path | None = None) -> Path:
    return Path(path).expanduser() if path is not None else default_league_config_path()


def _load_local_config(path: str | Path | None = None) -> dict[str, Any]:
    config_path = resolve_league_config_path(path)
    if not config_path.is_file():
        raise FileNotFoundError(
            f"League config not found: {config_path}. Run 'roster-theory "
            "setup init', import an existing config with 'roster-theory setup "
            "import --input PATH', or pass --config PATH before setup. "
            "'roster-theory example-config' remains available as a synthetic reference."
        )
    with config_path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{config_path} must contain a JSON object")
    return data


def load_league_config(path: str | Path | None = None) -> list[dict[str, Any]]:
    data = _load_local_config(path)
    leagues = data.get("leagues", [])
    if not isinstance(leagues, list):
        raise ValueError(f"{path} must contain a leagues array")
    return leagues


def load_owner_config(path: str | Path | None = None) -> dict[str, Any]:
    data = _load_local_config(path)
    owner = data.get("owner", {})
    if not isinstance(owner, dict):
        raise ValueError(f"{path} must contain an owner object")
    return owner


def find_league_config(
    key: str, path: str | Path | None = None
) -> dict[str, Any]:
    for league in load_league_config(path):
        if league.get("key") == key:
            return league
    raise KeyError(f"Unknown league key: {key}")


def resolve_league_policy_path(
    league_key: str,
    policy_name: str,
    *,
    config_path: str | Path | None = None,
    explicit_path: str | Path | None = None,
) -> Path:
    """Resolve and verify one policy without borrowing another league's evidence."""

    resolved_config = resolve_league_config_path(config_path)
    configured = None
    if explicit_path is None:
        league = find_league_config(league_key, resolved_config)
        policies = league.get("policies") or {}
        if not isinstance(policies, dict):
            raise ValueError(f"League {league_key!r} policies must be an object")
        configured = policies.get(policy_name)
    raw_path = explicit_path or configured
    if not raw_path:
        raise Uncalibrated(
            f"uncalibrated: league {league_key!r} has no {policy_name!r} policy; "
            f"run roster-theory setup scaffold {league_key} --artifact "
            f"{policy_name.replace('_', '-')} --update-config, then supply "
            "separately supported league thresholds"
        )
    policy_path = Path(raw_path).expanduser()
    if explicit_path is None and not policy_path.is_absolute():
        policy_path = resolved_config.parent / policy_path
    if not policy_path.is_file():
        raise Uncalibrated(
            f"uncalibrated: {policy_name!r} policy for league {league_key!r} "
            f"was not found at {policy_path}"
        )

    if policy_path.suffix.lower() == ".json":
        value = json.loads(policy_path.read_text(encoding="utf-8"))
        policy_league = str(value.get("league_key") or "")
        if policy_league != league_key:
            raise Uncalibrated(
                f"uncalibrated: {policy_name!r} policy is scoped to "
                f"{policy_league or 'no league'}, not {league_key!r}"
            )
        if str(value.get("status") or "").upper() == "UNCALIBRATED":
            raise Uncalibrated(
                f"uncalibrated: {policy_name!r} scaffold for league "
                f"{league_key!r} still requires separately supported thresholds; "
                f"run roster-theory setup explain {policy_name.replace('_', '-')}"
            )
    elif policy_name == "draft_preferences":
        with policy_path.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = tuple(csv.DictReader(handle))
        scoped = any(
            league_key
            in {
                part.strip()
                for part in str(row.get("league_scope") or "").split("|")
                if part.strip()
            }
            for row in rows
        )
        if any(str(row.get("status") or "").upper() == "UNCALIBRATED" for row in rows):
            raise Uncalibrated(
                f"uncalibrated: {policy_name!r} scaffold for league "
                f"{league_key!r} needs explicit preferences with evidence"
            )
        if not scoped:
            raise Uncalibrated(
                f"uncalibrated: draft preferences at {policy_path} do not "
                f"declare league {league_key!r}"
            )
    return policy_path


def _draft_bundle(client: SleeperClient, league_id: str) -> dict[str, Any]:
    league = client.league(league_id)
    drafts = client.league_drafts(league_id)
    return {
        "league": league,
        "users": client.league_users(league_id),
        "rosters": client.league_rosters(league_id),
        "drafts": [
            {"draft": draft, "picks": client.draft_picks(str(draft["draft_id"]))}
            for draft in drafts
        ],
    }


def build_snapshot(client: SleeperClient, config: dict[str, Any]) -> dict[str, Any]:
    current_id = str(config["league_id"])
    current = _draft_bundle(client, current_id)
    history_ids = [str(value) for value in config.get("history_league_ids", [])]

    linked_previous = current["league"].get("previous_league_id")
    if linked_previous and str(linked_previous) not in history_ids:
        history_ids.append(str(linked_previous))

    history = [_draft_bundle(client, league_id) for league_id in history_ids]
    return {
        "schema_version": 1,
        "captured_at": int(time.time()),
        "config": config,
        "current": current,
        "history": history,
    }


def save_snapshot(snapshot: dict[str, Any], path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(snapshot, indent=2, sort_keys=True), encoding="utf-8")
    return target
