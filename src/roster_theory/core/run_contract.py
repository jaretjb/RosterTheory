"""Factual run contracts shared by assistants, not decision policies.

An as-of scope freezes evaluation, never wall-clock publication validation.
Saved manifests are offline evidence, not authorization to act on old results.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import fields, is_dataclass, replace
from datetime import datetime, timedelta, timezone
from functools import lru_cache
import json
from pathlib import Path
from typing import Any, get_args, get_origin, get_type_hints, Union
from types import UnionType
from collections.abc import Mapping, Sequence

from roster_theory.core.errors import StaleData
from roster_theory.core.provenance import canonical_json, stable_hash
from roster_theory.providers.cache import atomic_write_json, is_fresh

_AS_OF: ContextVar[datetime | None] = ContextVar('assistant_as_of', default=None)


def evaluation_time() -> datetime:
    return _AS_OF.get() or datetime.now(timezone.utc)


def evaluate_at(as_of, function, *args, **kwargs):
    with evaluation_as_of(as_of):
        return function(*args, **kwargs)


@contextmanager
def evaluation_as_of(as_of: datetime):
    if as_of.tzinfo is None:
        raise ValueError('Evaluation as-of must be timezone-aware')
    token = _AS_OF.set(as_of)
    try:
        yield as_of
    finally:
        _AS_OF.reset(token)


def _volatile(snapshot: Any, *, week: int) -> dict[str, Any]:
    # Championship is derived from brackets in Trade, not a platform rule.
    league = replace(snapshot.league, championship_week=None)
    return {
        'league': league,
        'week': week,
        'teams': sorted((
            replace(team, display_name='', platform_settings=(),
                    player_ids=tuple(sorted(team.player_ids)),
                    starter_ids=tuple(sorted(team.starter_ids)),
                    reserve_ids=tuple(sorted(team.reserve_ids)))
            for team in snapshot.teams
        ), key=lambda row: row.roster_id),
    }


def revalidate_snapshot(snapshot: Any, *, client=None, bundle=None,
                        clock=None) -> dict[str, Any]:
    """Re-read ownership, settings, status and transactions before publication.

    A fresh directory is intentional: a cache hit cannot detect an intervening
    injury change. No writes to Sleeper are performed. Callers may inject a
    bundle/clock for fixture tests, never to skip the comparison.
    """
    from roster_theory.providers.sleeper import SleeperAdapter
    from roster_theory.sleeper import SleeperClient

    wall_clock = clock or (lambda: datetime.now(timezone.utc))
    if bundle is None:
        bundle = SleeperAdapter(client or SleeperClient()).fetch_waiver(
            snapshot.league.league_id, force_players=True)
    verified_at = wall_clock()
    if not is_fresh(bundle.captured_at, timedelta(minutes=5), now=verified_at):
        raise StaleData('Publication revalidation expired; refresh and rerun')
    week = snapshot.manifest.current_week
    if int(dict(bundle.state).get('season') or 0) != snapshot.league.season:
        raise StaleData('NFL season changed during analysis; rerun')
    before = _volatile(snapshot, week=week)
    after = _volatile(bundle, week=int(dict(bundle.state).get('week') or 0))
    if stable_hash(before) != stable_hash(after):
        raise StaleData('Ownership, lineup, week or league settings changed during analysis; rerun')
    current_players = {row.player_id: row for row in bundle.players}
    def status(player):
        return (player.positions, player.nfl_team, player.active, player.injury_status) if player else None
    changed = tuple(row.player_id for row in snapshot.players
                    if status(current_players.get(row.player_id)) != status(row))
    if changed:
        raise StaleData('Player availability or eligibility changed during analysis: ' + ', '.join(changed))
    endpoint = f'/league/{snapshot.league.league_id}/transactions/{week}'
    old_stamp = next((row for row in snapshot.stamps if row.endpoint == endpoint), None)
    new_stamp = next((row for row in bundle.stamps if row.endpoint == endpoint), None)
    if old_stamp and old_stamp.payload_hash and new_stamp and old_stamp.payload_hash != new_stamp.payload_hash:
        raise StaleData('Transactions changed during analysis; rerun')
    if hasattr(snapshot, 'transactions') and snapshot.transactions != bundle.transactions:
        raise StaleData('Transactions changed during analysis; rerun')
    return {
        'status': 'UNCHANGED', 'verified_at': verified_at.isoformat(),
        'volatile_hash': stable_hash(after), 'sources': json.loads(canonical_json(bundle.stamps)),
        'limitation': 'Observed unchanged, not atomic; recheck before acting. No platform action performed.',
    }


@lru_cache(maxsize=1)
def build_hash() -> str:
    root = Path(__file__).resolve().parents[1]
    return stable_hash({str(path.relative_to(root)).replace('\\', '/'): path.read_text(encoding='utf-8')
                        for path in sorted(root.rglob('*.py'))})


def build_run_manifest(*, as_of, verified_at, snapshot, inputs, policy,
                       sources, scoring, readiness, revalidation,
                       source_provenance_status=None) -> dict[str, Any]:
    replay = json.loads(canonical_json({'snapshot': snapshot, 'inputs': inputs, 'policy': policy}))
    value = json.loads(canonical_json({
        'schema_version': 1, 'build_hash': build_hash(),
        'as_of': as_of, 'verified_at': verified_at,
        'source_stamps': sources, 'scoring_hash': stable_hash(scoring),
        'source_provenance_status': source_provenance_status or ('RECORDED' if sources else 'LEGACY_UNAVAILABLE'),
        'policy_hash': stable_hash(policy), 'replay_hash': stable_hash(replay),
        'replay': replay, 'readiness': readiness, 'revalidation': revalidation,
        'calibration': 'Policy evidence is not a calibrated probability or cross-league validation.',
        'manifest_hash': '',
    }))
    value['manifest_hash'] = stable_hash(value)
    return value


def save_run_manifest(output_path, manifest) -> Path:
    return atomic_write_json(Path(output_path).with_suffix('.manifest.json'), manifest)


def load_run_manifest(path, *, require_same_build=True) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding='utf-8'))
    expected = value.get('manifest_hash')
    if value.get('schema_version') != 1 or stable_hash({**value, 'manifest_hash': ''}) != expected:
        raise ValueError('Run manifest schema/hash is invalid')
    if stable_hash(value['replay']) != value['replay_hash']:
        raise ValueError('Run replay hash is invalid')
    if require_same_build and value['build_hash'] != build_hash():
        raise ValueError('Replay requires the recorded source build')
    return {**value, 'current': False, 'replay_status': 'OFFLINE / NON-ACTIONABLE'}


def manifest_summary(manifest):
    return {key: value for key, value in manifest.items() if key != 'replay'} if manifest else None


def run_footer(manifest):
    if not manifest:
        return ()
    inputs = manifest.get('replay', {}).get('inputs', {})
    news = inputs.get('news_coverage') or inputs.get('bundle', {}).get('news_coverage')
    description = ('hourly limited global feed, not complete per-player coverage'
                   if news else 'legacy/unspecified scope, not a per-player all-clear')
    return (f"Evidence as of {manifest['as_of']}; league facts rechecked {manifest['verified_at']}.",
            f'News: {description}. Recheck before acting.')


def restore_record(record_type, value):
    """Restore code-selected record types, never a type supplied by a manifest."""
    if value is None or record_type is Any:
        return value
    if record_type is datetime:
        return datetime.fromisoformat(value)
    if record_type is Path:
        return Path(value)
    if is_dataclass(record_type):
        for field in fields(record_type):
            if field.metadata.get('require_in_artifact') and field.name not in value:
                raise ValueError(f'Legacy {record_type.__name__} lacks {field.name}; refresh source evidence or replay with its original build')
        hints = get_type_hints(record_type)
        return record_type(**{field.name: restore_record(hints[field.name], value[field.name])
                              for field in fields(record_type) if field.name in value})
    origin, args = get_origin(record_type), get_args(record_type)
    if origin in (UnionType, Union):
        choices = [item for item in args if item is not type(None)]
        if len(choices) != 1:
            raise ValueError('Ambiguous replay record type')
        return restore_record(choices[0], value)
    if origin is tuple:
        if not isinstance(value, (list, tuple)):
            raise ValueError('Saved tuple field must be an array; refresh source evidence')
        if len(args) == 2 and args[1] is Ellipsis:
            return tuple(restore_record(args[0], row) for row in value)
        return tuple(restore_record(kind, row) for kind, row in zip(args, value, strict=True))
    if origin in (list, Sequence):
        return [restore_record(args[0], row) for row in value]
    if origin in (dict, Mapping):
        return {restore_record(args[0], key): restore_record(args[1], row) for key, row in value.items()}
    return value


def record_run(output_path, *, snapshot, inputs, policy, revalidation, readiness, sources=(), as_of=None):
    manifest = build_run_manifest(
        as_of=as_of or snapshot.captured_at,
        verified_at=datetime.fromisoformat(revalidation['verified_at']),
        snapshot=snapshot, inputs=inputs, policy=policy,
        sources=(*snapshot.stamps, *sources), scoring=snapshot.league.scoring,
        readiness=readiness, revalidation=revalidation,
        source_provenance_status='RECORDED' if sources else 'LEGACY_VALUATION_UNAVAILABLE',
    )
    save_run_manifest(output_path, manifest)
    return manifest


def validate_sources(sources, *, now):
    for source in sources:
        if not is_fresh(datetime.fromisoformat(source['captured_at']),
                        timedelta(seconds=source['maximum_age_seconds']), now=now):
            raise StaleData(f"Source {source.get('name', source.get('endpoint'))} expired during analysis; refresh and rerun")
