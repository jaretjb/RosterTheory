from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def _local_env_value(name: str, path: str = ".env") -> str | None:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            for line in handle:
                stripped = line.strip()
                if not stripped or stripped.startswith("#") or "=" not in stripped:
                    continue
                key, value = stripped.split("=", 1)
                if key.strip() == name:
                    return value.strip().strip('"').strip("'") or None
    except FileNotFoundError:
        return None
    return None


class FantasyProsError(RuntimeError):
    """Raised when the FantasyPros API cannot satisfy a request."""


@dataclass(slots=True)
class FantasyProsClient:
    api_key: str | None = None
    base_url: str = "https://api.fantasypros.com/public/v2/json"
    timeout_seconds: float = 20.0
    retries: int = 1
    request_count: int = field(default=0, init=False)
    last_get_metadata: dict[str, Any] = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        if self.api_key is None:
            self.api_key = os.environ.get("FANTASYPROS_API_KEY") or _local_env_value("FANTASYPROS_API_KEY")

    def get(self, path: str, params: Mapping[str, Any] | None = None) -> dict[str, Any]:
        if not self.api_key:
            raise FantasyProsError(
                "Set FANTASYPROS_API_KEY in your environment; never add the key to a project file."
            )
        query = urlencode({key: value for key, value in (params or {}).items() if value is not None})
        url = f"{self.base_url.rstrip('/')}/{path.lstrip('/')}"
        if query:
            url = f"{url}?{query}"
        request = Request(
            url,
            headers={"x-api-key": self.api_key, "Accept": "application/json", "User-Agent": "RosterTheory/0.1"},
        )
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                self.request_count += 1
                with urlopen(request, timeout=self.timeout_seconds) as response:
                    value = json.loads(response.read().decode("utf-8"))
                    response_headers = getattr(response, "headers", {})
                    safe_rate_headers = {
                        str(key).lower(): str(header_value)
                        for key, header_value in response_headers.items()
                        if "ratelimit" in str(key).lower()
                        or "rate-limit" in str(key).lower()
                    }
                    self.last_get_metadata = {
                        "path": path,
                        "parameters": sorted((params or {}).keys()),
                        "rate_limit_headers": safe_rate_headers,
                    }
                if not isinstance(value, dict):
                    raise FantasyProsError(f"FantasyPros returned an unexpected response for {path}")
                return value
            except HTTPError as exc:
                self.last_get_metadata = {
                    "path": path,
                    "parameters": sorted((params or {}).keys()),
                    "http_status": exc.code,
                    "rate_limit_headers": {},
                }
                details = exc.read().decode("utf-8", errors="replace")
                raise FantasyProsError(f"FantasyPros returned HTTP {exc.code}: {details}") from exc
            except (URLError, TimeoutError, json.JSONDecodeError) as exc:
                last_error = exc
                if attempt < self.retries:
                    time.sleep(0.5 * (attempt + 1))
        raise FantasyProsError(f"Unable to retrieve {path}: {last_error}")

    def players(self, sport: str = "nfl", **params: Any) -> dict[str, Any]:
        return self.get(f"{sport}/players", params)

    def rankings(self, season: int = 2026, sport: str = "nfl", **params: Any) -> dict[str, Any]:
        return self.get(f"{sport}/{season}/rankings", params)

    def consensus_rankings(self, season: int = 2026, sport: str = "nfl", **params: Any) -> dict[str, Any]:
        return self.get(f"{sport}/{season}/consensus-rankings", params)

    def ranking_experts(self, season: int = 2026, sport: str = "nfl", **params: Any) -> dict[str, Any]:
        return self.get(f"{sport}/{season}/rankings/experts", params)

    def projections(self, season: int = 2026, **params: Any) -> dict[str, Any]:
        return self.get(f"nfl/{season}/projections", params)

    def news(self, sport: str = "nfl", **params: Any) -> dict[str, Any]:
        return self.get(f"{sport}/news", params)

    def player_points(self, season: int, **params: Any) -> dict[str, Any]:
        return self.get(f"nfl/{season}/player-points", params)

    def compare_players(self, **params: Any) -> dict[str, Any]:
        return self.get("nfl/compare-players", params)


def describe_shape(value: Any, depth: int = 0) -> Any:
    """Return keys and container types without printing licensed/sample player data."""
    if depth >= 3:
        return type(value).__name__
    if isinstance(value, dict):
        return {key: describe_shape(child, depth + 1) for key, child in list(value.items())[:20]}
    if isinstance(value, list):
        return {"type": "list", "count": len(value), "item": describe_shape(value[0], depth + 1) if value else None}
    return type(value).__name__
