import unittest

from roster_theory.core.lineup import LineupPlayer, lineup_slots, optimize_lineup


def exhaustive_assignment(players, positions, points):
    """Small independent oracle: try every legal player/empty assignment."""
    slots = lineup_slots(positions)
    best = None

    def visit(index, used, assignments, score):
        nonlocal best
        if index == len(slots):
            key = (-len(assignments), -score, assignments)
            if best is None or key < best[0]:
                best = (key, assignments, score)
            return
        visit(index + 1, used, assignments, score)
        for player in players:
            if player.player_id in used or not set(player.positions).intersection(slots[index][1]):
                continue
            visit(index + 1, used | {player.player_id},
                  (*assignments, (index, player.player_id)), score + points[player.player_id])

    visit(0, set(), (), 0.0)
    return best[1], round(best[2], 3)


class PartialLineupSearchTests(unittest.TestCase):
    def test_partial_flex_lineups_match_all_legal_assignments(self):
        players = (
            LineupPlayer("a", ("QB",)), LineupPlayer("b", ("RB",)),
            LineupPlayer("c", ("RB",)), LineupPlayer("d", ("WR",)),
            LineupPlayer("e", ("TE",)),
        )
        for positions in (
            ("QB", "RB", "WR", "FLEX", "DST"),
            ("QB", "RB", "RB", "WR", "FLEX", "K"),
            ("QB", "SUPER_FLEX", "REC_FLEX", "DST", "K"),
        ):
            for scores in (
                (10.0, 8.0, 7.0, 6.0, 5.0),
                (0.0, 0.0, 0.0, 0.0, 0.0),
                (-10.0, -8.0, -7.0, -6.0, -5.0),
            ):
                with self.subTest(positions=positions, scores=scores):
                    points = dict(zip((row.player_id for row in players), scores))
                    expected, score = exhaustive_assignment(players, positions, points)
                    result = optimize_lineup(players, positions, points)
                    slots = lineup_slots(positions)
                    self.assertEqual(tuple((row.slot, row.player_id) for row in result.assignments),
                                     tuple((slots[index][0], player_id) for index, player_id in expected))
                    self.assertEqual(result.score, score)
                    self.assertEqual(result.filled_slots, len(expected))
                    self.assertEqual(result.unused_player_ids, tuple(sorted(
                        {row.player_id for row in players} - {player_id for _, player_id in expected})))
