import unittest

from roster_theory.mock_analysis import (
    build_draft_board_replay_reports,
    evaluate_mock_rosters,
)


class MockAnalysisTests(unittest.TestCase):
    def test_builds_snake_turn_reports_from_board_columns(self) -> None:
        board = [
            {
                "player_name": name,
                "player_key": name,
                "sleeper_id": name,
                "position": "RB",
            }
            for name in ("A", "B", "C", "D")
        ]

        reports = build_draft_board_replay_reports(
            [["A", "B"], ["C", "D"]], board, draft_slot=1
        )

        self.assertEqual([report["current_pick"] for report in reports[:-1]], [1, 4])
        final = reports[-1]
        self.assertEqual(
            [(pick["pick_no"], pick["draft_slot"], pick["player_id"]) for pick in final["picks"]],
            [(1, 1, "A"), (2, 2, "B"), (3, 2, "D"), (4, 1, "C")],
        )
        self.assertEqual(len(reports[1]["picks"]), 3)

    def test_evaluates_every_roster_across_rank_channels(self) -> None:
        board = [
            {
                "player_key": f"sleeper_id:{index}",
                "sleeper_id": str(index),
                "player_name": f"Player {index}",
                "position": position,
                "team": "BUF",
                "projected_points": 300 - index,
                "adp": index,
                "vbd": 100 - index,
                "rank_score": index,
                "overall_rank_score": index,
            }
            for index, position in enumerate(
                ("QB", "RB", "WR", "TE", "QB", "RB", "WR", "TE"), start=1
            )
        ]
        rosters = {
            1: [self.pick(number, 1, str(number), position) for number, position in enumerate(("QB", "RB", "WR", "TE"), start=1)],
            2: [self.pick(number + 4, 2, str(number + 4), position) for number, position in enumerate(("QB", "RB", "WR", "TE"), start=1)],
        }
        report = {
            "teams": 2,
            "rounds": 4,
            "draft_slot": 1,
            "rosters": rosters,
        }
        draft = {
            "settings": {
                "teams": 2,
                "rounds": 4,
                "slots_qb": 1,
                "slots_rb": 1,
                "slots_wr": 1,
                "slots_te": 1,
            }
        }

        result = evaluate_mock_rosters(report, board, draft)

        self.assertEqual(result["unmatched_skill_picks"], [])
        self.assertEqual(set(result["channels"]), {"0.00", "0.50", "1.00"})
        self.assertEqual(result["channels"]["0.50"]["team_count"], 2)
        self.assertEqual(result["channels"]["0.50"]["user_rank"], 1)
        self.assertEqual(
            result["projection_value_method"],
            "expert_ordered_positional_projection_curve",
        )
        self.assertTrue(result["raw_projections_preserved"])
        self.assertEqual(
            result["primary_objective_method"],
            "no_bye_common_absence_and_projection_miss",
        )
        self.assertIn(
            "moderate", result["channels"]["0.50"]["weekly_use"]["1"]["stress_levels"]
        )

    @staticmethod
    def pick(number: int, slot: int, player_id: str, position: str) -> dict:
        return {
            "pick_no": number,
            "draft_slot": slot,
            "player_id": player_id,
            "metadata": {
                "first_name": "Player",
                "last_name": player_id,
                "position": position,
            },
        }


if __name__ == "__main__":
    unittest.main()
