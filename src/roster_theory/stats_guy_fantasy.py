from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class StatsGuyFantasyError(RuntimeError):
    """Raised when the public Stats Guy Fantasy API cannot satisfy a request."""


@dataclass(slots=True)
class StatsGuyFantasyClient:
    """Small read-only client for documented Stats Guy Fantasy GET endpoints."""

    base_url: str = "https://api.statsguyfantasy.com/api/v1"
    timeout_seconds: float = 20.0
    retries: int = 1
    transport: Callable[[str], Mapping[str, Any]] | None = None
    request_count: int = field(default=0, init=False)
    last_get_metadata: dict[str, Any] = field(default_factory=dict, init=False)

    def get(self, path: str, params: Mapping[str, Any] | None = None) -> dict[str, Any]:
        query = urlencode(
            {key: value for key, value in (params or {}).items() if value is not None}
        )
        url = f"{self.base_url.rstrip('/')}/{path.lstrip('/')}"
        if query:
            url = f"{url}?{query}"
        if self.transport is not None:
            self.request_count += 1
            value = self.transport(url)
            if not isinstance(value, Mapping):
                raise StatsGuyFantasyError(
                    f"Stats Guy Fantasy returned an unexpected response for {path}"
                )
            self.last_get_metadata = {
                "path": path,
                "parameters": tuple(sorted((params or {}).keys())),
                "rate_limit_headers": {},
            }
            return dict(value)

        request = Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": "RosterTheory/0.1",
            },
            method="GET",
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
                        "parameters": tuple(sorted((params or {}).keys())),
                        "rate_limit_headers": safe_rate_headers,
                    }
                if not isinstance(value, dict):
                    raise StatsGuyFantasyError(
                        f"Stats Guy Fantasy returned an unexpected response for {path}"
                    )
                return value
            except HTTPError as exc:
                self.last_get_metadata = {
                    "path": path,
                    "parameters": tuple(sorted((params or {}).keys())),
                    "http_status": exc.code,
                    "rate_limit_headers": {},
                }
                details = exc.read().decode("utf-8", errors="replace")[:240]
                raise StatsGuyFantasyError(
                    f"Stats Guy Fantasy returned HTTP {exc.code}: {details}"
                ) from exc
            except (URLError, TimeoutError, json.JSONDecodeError) as exc:
                last_error = exc
                if attempt < self.retries:
                    time.sleep(0.5 * (attempt + 1))
        raise StatsGuyFantasyError(
            f"Unable to retrieve Stats Guy Fantasy {path}: {last_error}"
        )

    def players(self) -> dict[str, Any]:
        """Retrieve the documented bulk player/value payload in one GET."""

        return self.get("players")
