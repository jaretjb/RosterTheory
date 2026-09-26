"""Inspect a saved Sleeper draft's position-limit evidence without provider calls.

This is a scoped rule report, not Draft readiness or a support-matrix promotion.
"""
import argparse
from dataclasses import asdict
import json
from pathlib import Path

from roster_theory.providers.sleeper_draft_rules import assess_draft_position_limits


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('draft', type=Path, help='Raw saved Sleeper draft JSON')
    args = parser.parse_args()
    draft = json.loads(args.draft.read_text(encoding='utf-8'))
    if not isinstance(draft, dict):
        parser.error('Draft must be a JSON object')
    result = assess_draft_position_limits(draft)
    print(json.dumps({**asdict(result), 'status': result.status,
                      'scope_admitted': result.scope_admitted}, indent=2))
    return 0 if result.scope_admitted else 2


if __name__ == '__main__':
    raise SystemExit(main())
