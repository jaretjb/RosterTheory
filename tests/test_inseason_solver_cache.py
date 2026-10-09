import random
import unittest

from roster_theory.core.lineup import LineupPlayer, optimize_lineup
from roster_theory.inseason.evaluation import WeeklyProjectionMatrix, _solve_cached


class ExactSolverCacheTests(unittest.TestCase):
    def test_reduced_solver_matches_original_across_overlapping_slots_and_ties(self):
        rng = random.Random(1315)
        positions = (("QB",), ("RB",), ("WR",), ("TE",), ("RB", "WR"), ("WR", "TE"), ("K",))
        for _ in range(300):
            slots = tuple(rng.choice(("QB", "RB", "WR", "TE", "FLEX", "SUPER_FLEX")) for _ in range(rng.randint(1, 5)))
            players = tuple(LineupPlayer(str(i), rng.choice(positions)) for i in range(rng.randint(0, 11)))
            points = {p.player_id: float(rng.randint(-3, 8)) for p in players}
            matrix = WeeklyProjectionMatrix((), (), (), True, ())
            self.assertEqual(_solve_cached(matrix, players, slots, points),
                             optimize_lineup(players, slots, points))

    def test_bench_variants_share_solve_but_keep_all_unused_ids(self):
        matrix = WeeklyProjectionMatrix((), (), (), True, ())
        base = (LineupPlayer("starter", ("RB",)),)
        first = (*base, LineupPlayer("bench-A", ("RB",)))
        second = (*base, LineupPlayer("bench-B", ("RB",)))
        points = {"starter": 10, "bench-A": 1, "bench-B": 2}
        a = _solve_cached(matrix, first, ("RB",), points)
        b = _solve_cached(matrix, second, ("RB",), points)
        self.assertEqual(len(matrix.solver_cache), 1)
        self.assertEqual(a.assignments, b.assignments)
        self.assertEqual(a.unused_player_ids, ("bench-A",))
        self.assertEqual(b.unused_player_ids, ("bench-B",))
