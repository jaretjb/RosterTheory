import unittest
from pathlib import Path
from unittest.mock import patch

from roster_theory.simulation import Player
from roster_theory.specialist_preferences import (
    defense_draft_rank,
    defense_draft_sort_key,
    load_defense_draft_order,
)

FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "provider"
    / "defense_draft_order.synthetic.csv"
)


class SpecialistPreferenceTests(unittest.TestCase):
    def test_loads_synthetic_defense_order(self) -> None:
        order = load_defense_draft_order(FIXTURE)

        self.assertEqual(
            [(entry.rank, entry.team) for entry in order],
            [(1, "AAA"), (2, "BBB")],
        )
        self.assertEqual(defense_draft_rank("AAA", order), 1)

    def test_user_defense_order_overrides_but_preserves_expert_rank(self) -> None:
        alpha = Player(
            "AAA",
            "Alpha Defense",
            "DST",
            0.0,
            122.0,
            0.0,
            5.0,
            team="AAA",
        )
        bravo = Player(
            "BBB",
            "Bravo Defense",
            "DST",
            0.0,
            121.0,
            0.0,
            1.5,
            team="BBB",
        )

        order = load_defense_draft_order(FIXTURE)
        with patch(
            "roster_theory.specialist_preferences.load_defense_draft_order",
            return_value=order,
        ):
            ordered = sorted([bravo, alpha], key=defense_draft_sort_key)

        self.assertEqual(
            [player.name for player in ordered], ["Alpha Defense", "Bravo Defense"]
        )
        self.assertEqual(ordered[0].rank_score, 5.0)
