import unittest
from datetime import datetime, timezone
from types import SimpleNamespace

from roster_theory.core.errors import CoverageIncomplete
from roster_theory.waiver.expert_panel import select_waiver_ros_panel


NOW = datetime(2026, 9, 22, 12, tzinfo=timezone.utc)


def expert(expert_id, latest, prior):
    return SimpleNamespace(
        expert_id=str(expert_id),
        name=f"Expert {expert_id}",
        source_name=f"Source {expert_id}",
        position_updates=tuple(
            (position, "2026-09-22T10:00:00+00:00")
            for position in ("QB", "RB", "WR", "TE")
        ),
        latest_weekly_accuracy=(("ALL", latest),),
        prior_weekly_accuracy=(("ALL", prior),),
    )


def inputs(experts):
    contributor_ids = tuple(row.expert_id for row in experts)
    rankings = tuple(
        SimpleNamespace(
            contributor_ids=contributor_ids,
            observations=(SimpleNamespace(position=position),),
        )
        for position in ("QB", "RB", "WR", "TE")
    )
    return SimpleNamespace(ros_rankings=rankings, current_experts=tuple(experts))


class WaiverRosPanelTests(unittest.TestCase):
    def test_selects_three_best_current_contributors_and_excludes_poor(self):
        result = select_waiver_ros_panel(
            inputs(
                (
                    expert("1", 10, 20),
                    expert("2", 20, 30),
                    expert("3", 30, 40),
                    expert("4", 110, 120),
                )
            ),
            NOW,
            league_key="league_alpha",
        )
        self.assertEqual(tuple(row.expert_id for row in result.members), ("1", "2", "3"))
        self.assertEqual(result.evidence["status"], "READY")
        poor = next(
            row for row in result.evidence["candidates"] if row["expert_id"] == "4"
        )
        self.assertEqual(poor["reason"], "poor_accuracy_both_seasons")

    def test_two_experts_is_degraded_but_usable(self):
        result = select_waiver_ros_panel(
            inputs((expert("1", 10, 20), expert("2", 20, 30))),
            NOW,
            league_key="league_alpha",
        )
        self.assertEqual(len(result.members), 2)
        self.assertEqual(result.evidence["status"], "DEGRADED")

    def test_fewer_than_two_experts_fails_closed(self):
        with self.assertRaisesRegex(CoverageIncomplete, "at least 2"):
            select_waiver_ros_panel(
                inputs((expert("1", 10, 20),)),
                NOW,
                league_key="league_alpha",
            )


if __name__ == "__main__":
    unittest.main()
