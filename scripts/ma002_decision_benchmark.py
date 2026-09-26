"""Time unchanged MA-001 search scopes offline against either source checkout."""
import argparse
import json
from pathlib import Path
from statistics import median
import sys
from time import perf_counter


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    root = args.source_root.resolve()
    sys.path[:0] = [str(root / 'src'), str(root)]
    from scripts.ma001_baseline import evidence, offline, workloads
    from tests.ma001_fixtures import PROFILES, ROOT
    goldens = json.loads((ROOT / 'semantics.json').read_text())['profiles']
    results = {}
    with offline():
        for profile in PROFILES:
            results[profile] = {}
            for name in ('trade_search', 'waiver_search'):
                function = workloads(profile)[name]
                expected = goldens[profile][name]
                assert evidence(function()) == expected, (profile, name)
                seconds = []
                for _ in range(5):
                    start = perf_counter()
                    result = function()
                    seconds.append(round(perf_counter() - start, 6))
                    assert evidence(result) == expected, (profile, name)
                results[profile][name] = {'seconds': seconds, 'median_seconds': median(seconds)}
                print(profile, name, results[profile][name]['median_seconds'], flush=True)
    args.output.write_text(json.dumps({'repeats_after_warmup': 5, 'results': results}, indent=2) + '\n')


if __name__ == '__main__':
    main()
