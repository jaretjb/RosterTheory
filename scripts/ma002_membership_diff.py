"""Audit complete before/after workload payloads for the membership schema change.

This never changes hashes, strips output fields, or writes a semantic baseline.
Runtime readers and current-version golden tests still validate complete hashes.
"""
import argparse
from collections import Counter
import json
from pathlib import Path


def differences(before, after, path=""):
    if isinstance(before, dict) and isinstance(after, dict):
        for key in sorted(before.keys() | after.keys()):
            child = path + '/' + key
            if key not in before or key not in after:
                yield {'path': child, 'kind': 'ADDED' if key not in before else 'REMOVED',
                       'before': before.get(key), 'after': after.get(key)}
            else:
                yield from differences(before[key], after[key], child)
    elif isinstance(before, list) and isinstance(after, list) and len(before) == len(after):
        for index, (left, right) in enumerate(zip(before, after)):
            yield from differences(left, right, path + '/' + str(index))
    elif before != after:
        yield {'path': path, 'kind': 'CHANGED', 'before': before, 'after': after}


def audit(before, after):
    changes = list(differences(before, after))
    for row in changes:
        name = row['path'].rsplit('/', 1)[-1]
        if row['kind'] == 'ADDED' and ((name == 'taxi_ids' and row['after'] == [])
                                     or (name == 'taxi_slots' and row['after'] == 0)):
            continue
        if row['kind'] == 'CHANGED' and name in {'manifest_id', 'evidence_hash', 'replay_hash', 'snapshot_hash'}:
            if all(isinstance(row[key], str) and len(row[key]) == 64 for key in ('before', 'after')):
                continue
        raise AssertionError(f"Unreviewed semantic change: {row['path']}")
    return {'scope': 'MA-002d membership additions and derived hashes only',
            'counts': dict(Counter(row['path'].rsplit('/', 1)[-1] for row in changes)),
            'changes': changes}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('before', type=Path)
    parser.add_argument('after', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = audit(json.loads(args.before.read_text()), json.loads(args.after.read_text()))
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(result['counts'])
