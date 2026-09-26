"""Offline MA-002b preparation cost; synthetic stats are not provider evidence."""
from datetime import datetime, timezone
import json
from statistics import median
from time import perf_counter

from roster_theory.core.scoring import score_stats
from roster_theory.providers.fantasypros import normalize_projections, normalize_scored_projections
from roster_theory.providers.projection_scoring import WEEKLY_RULES
from tests.ma001_fixtures import PROFILES, rules


def benchmark(repeats=5, player_count=400):
    results = {}
    captured = datetime(2026, 9, 1, tzinfo=timezone.utc)
    for profile in PROFILES:
        scoring = rules(profile)['scoring_settings']
        payload = {'season': 2026, 'week': 1, 'scoring': 'HALF', 'players': [
            {'fpid': f'synthetic-{i}', 'position_id': ('QB', 'RB', 'WR', 'TE', 'K', 'DST')[i % 6],
             'stats': {rule.statistic: 0.0 for rule in WEEKLY_RULES}}
            for i in range(player_count)
        ]}

        def legacy():
            # Reproduce the old same-format preparation, including its flawed
            # completeness default, only as a timing comparator.
            points = {row['fpid']: score_stats(row['stats'], scoring,
                      position=row['position_id']).points for row in payload['players']}
            return normalize_projections(payload, horizon='WEEKLY', league_points=points,
                coverage_by_player={row['fpid']: 'complete' for row in payload['players']},
                captured_at=captured)

        def strict():
            return normalize_scored_projections(payload, scoring_settings=scoring,
                season=2026, week=1, league_id=profile, captured_at=captured)

        timings = {}
        for name, function in (('legacy', legacy), ('strict', strict)):
            function()
            elapsed = []
            for _ in range(repeats):
                start = perf_counter()
                function()
                elapsed.append(round((perf_counter() - start) * 1000, 3))
            timings[name] = {'milliseconds': elapsed, 'median_ms': median(elapsed)}
        results[profile] = timings
    return {'players_per_week': player_count, 'repeats_after_warmup': repeats,
            'source': 'synthetic explicit zeros; not a coverage/readiness claim', 'results': results}


if __name__ == '__main__':
    print(json.dumps(benchmark(), indent=2))
