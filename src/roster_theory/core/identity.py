from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping


@dataclass(frozen=True, slots=True)
class IdentityMatch:
    source_id: str
    target_id: str
    method: str
    evidence_field: str | None = None


@dataclass(frozen=True, slots=True)
class IdentityIssue:
    source_id: str
    candidate_target_ids: tuple[str, ...]
    reason: str


@dataclass(frozen=True, slots=True)
class IdentityReport:
    matches: tuple[IdentityMatch, ...]
    unmatched: tuple[IdentityIssue, ...]
    ambiguous: tuple[IdentityIssue, ...]

    @property
    def complete(self) -> bool:
        return not self.unmatched and not self.ambiguous


def _text(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


def reconcile_identities(
    source_rows: Iterable[Mapping[str, Any]],
    target_rows: Iterable[Mapping[str, Any]],
    *,
    source_id_field: str,
    target_id_field: str,
    shared_id_fields: tuple[str, ...],
    aliases: Mapping[str, str] | None = None,
) -> IdentityReport:
    """Reconcile exact IDs, then shared provider IDs, then explicit aliases.

    Names are deliberately not used. Similar or even identical names cannot
    create an implicit cross-provider identity.
    """
    sources = [dict(row) for row in source_rows]
    targets = [dict(row) for row in target_rows]
    target_by_id = {
        value: row
        for row in targets
        if (value := _text(row.get(target_id_field))) is not None
    }
    matches: list[IdentityMatch] = []
    unmatched: list[IdentityIssue] = []
    ambiguous: list[IdentityIssue] = []
    claimed_targets: dict[str, str] = {}

    for source in sorted(sources, key=lambda row: _text(row.get(source_id_field)) or ""):
        source_id = _text(source.get(source_id_field))
        if source_id is None:
            unmatched.append(IdentityIssue("", (), "missing_source_id"))
            continue

        candidates: dict[str, tuple[str, str | None]] = {}
        if source_id in target_by_id:
            candidates[source_id] = ("exact_id", target_id_field)
        else:
            for field in shared_id_fields:
                source_value = _text(source.get(field))
                if source_value is None:
                    continue
                for target_id, target in target_by_id.items():
                    if _text(target.get(field)) == source_value:
                        candidates[target_id] = ("external_id", field)
            alias_target = _text((aliases or {}).get(source_id))
            if not candidates and alias_target in target_by_id:
                candidates[alias_target] = ("explicit_alias", None)

        candidate_ids = tuple(sorted(candidates))
        if not candidate_ids:
            unmatched.append(IdentityIssue(source_id, (), "no_exact_identity"))
            continue
        if len(candidate_ids) > 1:
            ambiguous.append(
                IdentityIssue(source_id, candidate_ids, "multiple_exact_candidates")
            )
            continue
        target_id = candidate_ids[0]
        previous_source = claimed_targets.get(target_id)
        if previous_source is not None and previous_source != source_id:
            ambiguous.append(
                IdentityIssue(
                    source_id,
                    (target_id,),
                    f"target_already_claimed_by:{previous_source}",
                )
            )
            continue
        method, evidence_field = candidates[target_id]
        claimed_targets[target_id] = source_id
        matches.append(IdentityMatch(source_id, target_id, method, evidence_field))

    return IdentityReport(tuple(matches), tuple(unmatched), tuple(ambiguous))

