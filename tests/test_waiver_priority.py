import unittest
from datetime import datetime, timezone

from roster_theory.core.models import Player
from roster_theory.providers.fantasypros import normalize_rankings
from roster_theory.waiver.evaluation import PlayerValueInput
from roster_theory.waiver.priority import (
    build_waiver_priority_scores,
    compare_waiver_values,
)
from roster_theory.waiver.ww_evidence import (
    WaiverWireConfig,
    build_waiver_wire_evidence,
)


NOW = datetime(2026, 9, 22, 12, tzinfo=timezone.utc)


def waiver_evidence():
    market = normalize_rankings(
        {
            "year": 2026,
            "week": 3,
            "scoring": "HALF",
            "ranking_type_name": "Waiver Wire",
            "last_updated": NOW.isoformat(),
            "expert_names": {"1": "One", "2": "Two"},
            "players": [
                {
                    "player_id": "101",
                    "player_name": "Available Runner",
                    "player_position_id": "RB",
                    "rank_ecr": 1,
                    "pos_rank": "RB1",
                },
                {
                    "player_id": "102",
                    "player_name": "Bye Runner",
                    "player_position_id": "RB",
                    "rank_ecr": 2,
                    "pos_rank": "RB2",
                },
            ],
        },
        requested_horizon="WAIVER",
        board_source="market",
        captured_at=NOW,
    )
    return build_waiver_wire_evidence(
        config=WaiverWireConfig(
            league_key="league_alpha",
            scoring="HALF",
            position="ALL",
            maximum_age_hours=24,
            trusted_expert_ids=(),
            config_hash="fixture",
        ),
        players=(
            Player(
                "add", "Available Runner", ("RB",), fantasypros_id="101", nfl_team="AAA"
            ),
            Player(
                "bye", "Bye Runner", ("RB",), fantasypros_id="102", nfl_team="BYE"
            ),
        ),
        market=market,
        selected={},
        now=NOW,
    )


class WaiverPriorityTests(unittest.TestCase):
    def setUp(self):
        self.players = (
            Player("add", "Available Runner", ("RB",), nfl_team="AAA"),
            Player("bye", "Bye Runner", ("RB",), nfl_team="BYE"),
            Player("owned", "Owned Receiver", ("WR",), nfl_team="CCC"),
        )
        self.values = (
            PlayerValueInput(
                "add",
                0,
                0,
                0,
                current_week_position_rank=1,
                selected_rest_of_season_position_rank=3,
            ),
            PlayerValueInput(
                "bye",
                0,
                0,
                0,
                selected_rest_of_season_position_rank=2,
            ),
            PlayerValueInput(
                "owned",
                0,
                0,
                0,
                current_week_position_rank=2,
                selected_rest_of_season_position_rank=1,
            ),
        )

    def test_missing_signals_are_neutral_and_weights_renormalize(self):
        scores = build_waiver_priority_scores(
            players=self.players,
            values=self.values,
            waiver_wire_evidence=waiver_evidence(),
            owner_by_player={"owned": "1"},
            current_bye_teams=("BYE",),
        )
        add_weights = {row.signal: row.applied_weight for row in scores["add"].components}
        self.assertEqual(add_weights, {"WEEKLY": 0.5, "WAIVER": 0.3, "ROS": 0.2})

        bye_weights = {row.signal: row.applied_weight for row in scores["bye"].components}
        self.assertEqual(bye_weights, {"WAIVER": 0.6, "ROS": 0.4})
        self.assertIn(("WEEKLY", "BYE_WEEK"), scores["bye"].missing_signals)

        owned_weights = {
            row.signal: row.applied_weight for row in scores["owned"].components
        }
        self.assertEqual(owned_weights, {"WEEKLY": 0.714286, "ROS": 0.285714})
        self.assertIn(
            ("WAIVER", "NOT_LISTED_OR_ABOVE_WW_OWNERSHIP_SCOPE"),
            scores["owned"].missing_signals,
        )

    def test_add_drop_delta_uses_the_two_composite_values(self):
        scores = build_waiver_priority_scores(
            players=self.players,
            values=self.values,
            waiver_wire_evidence=waiver_evidence(),
            owner_by_player={"owned": "1"},
            current_bye_teams=("BYE",),
        )
        comparison = compare_waiver_values(
            scores, add_player_id="add", drop_player_id="owned"
        )
        self.assertTrue(comparison.comparable)
        self.assertAlmostEqual(
            comparison.value_delta,
            scores["add"].composite_score - scores["owned"].composite_score,
            places=5,
        )
        open_slot = compare_waiver_values(
            scores, add_player_id="add", drop_player_id=None
        )
        self.assertEqual(open_slot.value_delta, scores["add"].composite_score)


if __name__ == "__main__":
    unittest.main()
