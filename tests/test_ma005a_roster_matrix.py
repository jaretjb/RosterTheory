"""Synthetic half-PPR roster-shape checks; no feature readiness claim."""

from itertools import product
import unittest

from roster_theory.core.lineup import LineupPlayer, optimize_lineup
from roster_theory.core.models import FantasyTeam
from roster_theory.core.roster import assess_membership, draft_roster_fits
from roster_theory.draft.watcher import roster_positions_from_draft
from roster_theory.providers.sleeper import normalize_league
from roster_theory.providers.sleeper_draft_rules import assess_draft_position_limits
from tests.ma001_fixtures import rules


FIXED = ("QB", "RB", "RB", "WR", "WR", "TE", "K", "DEF")
FLEXES = (("WRRB_FLEX",), ("FLEX",), ("FLEX", "FLEX"))
SCORES = (
    ("qb", "QB", 20.0), ("rb1", "RB", 18.0), ("rb2", "RB", 17.0),
    ("wr1", "WR", 14.0), ("wr2", "WR", 13.0),
    ("te1", "TE", 20.0), ("k", "K", 8.0), ("dst", "DST", 7.0),
    ("rb3", "RB", 16.0), ("wr3", "WR", 15.0), ("te2", "TE", 17.0),
)
# Base fixed eight score 117. WR3 (15) replaces WR2 (13), then the best
# eligible remaining flexes contribute RB3 (16) and/or TE2 (17).
EXPECTED_LINEUP = {FLEXES[0]: 135.0, FLEXES[1]: 136.0, FLEXES[2]: 152.0}


def cases():
    return product((10, 12), FLEXES, (5, 6))


def synthetic_shape(teams, flexes, bench):
    slots = (*FIXED, *flexes, *("BN",) * bench)
    settings = dict(rules("reference_a")["settings"])
    settings.update(reserve_slots=0, taxi_slots=0)
    league = normalize_league({
        "league_id": f"synthetic-{teams}-{'-'.join(flexes)}-{bench}",
        "season": "2026", "total_rosters": teams,
        "roster_positions": slots,
        "scoring_settings": rules("reference_a")["scoring_settings"],
        "settings": settings,
    })
    players = [LineupPlayer(pid, (position,)) for pid, position, _ in SCORES]
    points = {pid: score for pid, _, score in SCORES}
    for index in range(len(slots) - len(players)):
        pid = f"bench-{index}"
        players.append(LineupPlayer(pid, ("RB",)))
        points[pid] = 1.0
    return league, players, points


class HalfPprRosterMatrixTests(unittest.TestCase):
    def test_all_twelve_shapes_have_independent_slot_and_lineup_oracles(self):
        seen = set()
        for teams, flexes, bench in cases():
            with self.subTest(teams=teams, flexes=flexes, bench=bench):
                league, players, points = synthetic_shape(teams, flexes, bench)
                seen.add((teams, flexes, bench))
                self.assertEqual(league.team_count, teams)
                self.assertEqual(dict(league.scoring)["rec"], 0.5)
                self.assertEqual(len(players), len(league.roster_positions))
                self.assertTrue(draft_roster_fits(
                    [row.positions[0] for row in players], league.roster_positions))
                self.assertFalse(draft_roster_fits(
                    [row.positions[0] for row in players] + ["RB"], league.roster_positions))
                lineup = optimize_lineup(players, league.roster_positions, points)
                self.assertEqual(lineup.filled_slots, len(FIXED) + len(flexes))
                self.assertEqual(lineup.score, EXPECTED_LINEUP[flexes])
                self.assertEqual(len({row.player_id for row in lineup.assignments}),
                                 lineup.filled_slots)
                owner = FantasyTeam(
                    "1", "synthetic-owner", "Synthetic roster",
                    tuple(row.player_id for row in players),
                    tuple(row.player_id for row in lineup.assignments), (), 1, 0,
                    taxi_ids=(),
                )
                membership = assess_membership(league, (owner,))
                self.assertTrue(membership.complete, membership.issues)
                self.assertEqual(membership.rosters[0].open_active_slots, 0)
                one_open = FantasyTeam(
                    "1", "synthetic-owner", "Synthetic roster",
                    owner.player_ids[:-1], owner.starter_ids, (), 1, 0, taxi_ids=(),
                )
                self.assertEqual(assess_membership(league, (one_open,)).rosters[0].open_active_slots, 1)
        self.assertEqual(len(seen), 12)

    def test_draft_room_slots_match_each_shape_but_source_cap_evidence_stays_limited(self):
        for teams, flexes, bench in cases():
            with self.subTest(teams=teams, flexes=flexes, bench=bench):
                league, _, _ = synthetic_shape(teams, flexes, bench)
                settings = {"teams": teams, "rounds": len(league.roster_positions),
                            "slots_qb": 1, "slots_rb": 2, "slots_wr": 2,
                            "slots_te": 1, "slots_k": 1, "slots_def": 1,
                            "slots_bn": bench}
                if flexes == FLEXES[0]:
                    settings["slots_wrrb_flex"] = 1
                else:
                    settings["slots_flex"] = len(flexes)
                room = {"type": "snake", "settings": settings,
                        "metadata": {"scoring_type": "half_ppr"}}
                self.assertEqual(sorted(roster_positions_from_draft(room)),
                                 sorted(league.roster_positions))
                self.assertEqual(assess_draft_position_limits(room).status, "LIMITED")
                settings["enforce_position_limits"] = 1
                self.assertEqual(assess_draft_position_limits(room).status, "LIMITED")
                settings["enforce_position_limits"] = 0
                self.assertEqual(assess_draft_position_limits(room).status, "SUPPORTED")


if __name__ == "__main__":
    unittest.main()
