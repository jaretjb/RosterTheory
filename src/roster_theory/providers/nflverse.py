from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from roster_theory.core.errors import SourceUnavailable


NFLVERSE_RELEASE_URL = "https://github.com/nflverse/nflverse-data/releases/tag/schedules"
NFLVERSE_SCHEDULE_URL = (
    "https://github.com/nflverse/nflverse-data/releases/download/schedules/games.csv"
)
NFLVERSE_LICENSE = "CC-BY-4.0"
NFLVERSE_USE_RESTRICTION = "Attribution and indication of changes required."
NFLVERSE_RELEASE_ID = "schedules"
NFLVERSE_ASSET_ID = "games.csv"
EVIDENCE_SCHEMA = "roster-theory.nflverse-schedule-evidence/v1"


@dataclass(frozen=True, slots=True)
class NflverseScheduleEvidence:
    schema_version: str
    source: str
    source_url: str
    endpoint: str
    upstream_release: str
    upstream_asset: str
    captured_at: str
    response_hash: str
    license: str
    use_restriction: str
    content: str


def _hash_bytes(value: bytes) -> str:
    return sha256(value).hexdigest()


def fetch_nflverse_schedule(
    *,
    url: str = NFLVERSE_SCHEDULE_URL,
    timeout: float = 30.0,
    opener: Any = urlopen,
    now: datetime | None = None,
) -> NflverseScheduleEvidence:
    """Fetch the public release asset without interpreting schedule rows."""

    request = Request(url, headers={"User-Agent": "RosterTheory/OS-016"})
    try:
        with opener(request, timeout=timeout) as response:
            body = response.read()
    except (HTTPError, URLError, OSError, TimeoutError) as exc:
        raise SourceUnavailable(f"nflverse schedule source unavailable: {exc}") from exc
    try:
        content = body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SourceUnavailable("nflverse schedule response was not UTF-8 CSV") from exc
    captured = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    return NflverseScheduleEvidence(
        schema_version=EVIDENCE_SCHEMA,
        source="nflverse nflverse-data schedules release",
        source_url=NFLVERSE_RELEASE_URL,
        endpoint=url,
        upstream_release=NFLVERSE_RELEASE_ID,
        upstream_asset=NFLVERSE_ASSET_ID,
        captured_at=captured.isoformat(),
        response_hash=_hash_bytes(body),
        license=NFLVERSE_LICENSE,
        use_restriction=NFLVERSE_USE_RESTRICTION,
        content=content,
    )


def import_schedule_csv(
    path: str | Path,
    *,
    source: str,
    source_url: str,
    license_name: str,
    captured_at: str,
    use_restriction: str = "User-authorized local source; redistribution not assumed.",
) -> NflverseScheduleEvidence:
    source_path = Path(path)
    body = source_path.read_bytes()
    try:
        content = body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SourceUnavailable(f"Schedule import is not UTF-8 CSV: {source_path}") from exc
    return NflverseScheduleEvidence(
        schema_version=EVIDENCE_SCHEMA,
        source=source,
        source_url=source_url,
        endpoint=str(source_path.resolve()),
        upstream_release="user-authorized-import",
        upstream_asset=source_path.name,
        captured_at=captured_at,
        response_hash=_hash_bytes(body),
        license=license_name,
        use_restriction=use_restriction,
        content=content,
    )


def save_schedule_evidence(
    evidence: NflverseScheduleEvidence, path: str | Path
) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(asdict(evidence), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return target


def load_schedule_evidence(path: str | Path) -> NflverseScheduleEvidence:
    source = Path(path)
    value = json.loads(source.read_text(encoding="utf-8"))
    if value.get("schema_version") != EVIDENCE_SCHEMA:
        raise SourceUnavailable(f"Unsupported schedule evidence schema: {source}")
    try:
        evidence = NflverseScheduleEvidence(**value)
    except (TypeError, KeyError) as exc:
        raise SourceUnavailable(f"Incomplete schedule evidence: {source}") from exc
    if _hash_bytes(evidence.content.encode("utf-8")) != evidence.response_hash:
        raise SourceUnavailable(f"Schedule evidence hash mismatch: {source}")
    return evidence
