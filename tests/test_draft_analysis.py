import unittest

from roster_theory.draft_analysis import (
    analyze_draft,
    detect_position_runs,
    historical_position_pick_curves,
    simulation_round_tendencies,
)


def make_pick(pick_no: int, position: str, manager: str = "1") -> dict:
    return {
        "pick_no": pick_no,
        "round": ((pick_no - 1) // 4) + 1,
        "picked_by": manager,
        "metadata": {"position": position, "first_name": position, "last_name": str(pick_no)},
    }


class DraftAnalysisTests(unittest.TestCase):
    def test_detects_position_run(self) -> None:
        picks = [make_pick(index + 1, pos) for index, pos in enumerate(["RB", "WR", "RB", "RB", "QB"])]
        runs = detect_position_runs(picks)
        self.assertEqual(runs[0]["position"], "RB")
        self.assertEqual(runs[0]["count"], 3)

    def test_summarizes_rounds_and_managers(self) -> None:
        picks = [
            make_pick(1, "RB", "a"),
            make_pick(2, "WR", "b"),
            make_pick(3, "RB", "a"),
            make_pick(4, "QB", "b"),
            make_pick(5, "WR", "a"),
        ]
        result = analyze_draft(picks, [{"user_id": "a", "display_name": "Alice"}])
        self.assertEqual(result["pick_count"], 5)
        self.assertEqual(result["position_counts"]["RB"], 2)
        self.assertEqual(result["position_by_round"]["1"]["QB"], 1)
        self.assertEqual(result["managers"][0]["manager"], "Alice")

    def test_simulation_tendencies_include_kicker_and_defense(self) -> None:
        snapshot = {
            "history": [
                {
                    "league": {"league_id": "league"},
                    "drafts": [
                        {
                            "draft": {"draft_id": "draft", "settings": {"teams": 2}},
                            "picks": [
                                make_pick(1, "RB"),
                                make_pick(2, "WR"),
                                make_pick(57, "K"),
                                make_pick(58, "DEF"),
                            ],
                        }
                    ],
                }
            ]
        }
        tendencies = simulation_round_tendencies(snapshot)
        self.assertIn("K", tendencies[15])
        self.assertIn("DST", tendencies[15])
        self.assertGreater(tendencies[15]["DST"], tendencies[1]["DST"])

    def test_historical_position_curves_follow_overall_pick_order(self) -> None:
        snapshot = {
            "history": [
                {
                    "drafts": [
                        {
                            "draft": {
                                "draft_id": "history-2025",
                                "season": "2025",
                                "settings": {"teams": 2, "rounds": 3},
                            },
                            "picks": [
                                make_pick(4, "QB"),
                                make_pick(1, "RB"),
                                make_pick(2, "QB"),
                                make_pick(3, "WR"),
                            ],
                        }
                    ]
                }
            ]
        }
        curves = historical_position_pick_curves(snapshot)

        self.assertTrue(curves.available)
        self.assertEqual(curves.position_picks["QB"], (2, 4))
        self.assertEqual(curves.position_picks["RB"], (1,))
        self.assertEqual(curves.draft_end_pick, 6)
        self.assertIn("history-2025", curves.source)

    def test_historical_slot_mapping_ignores_player_names_and_reports_no_history(self) -> None:
        first = make_pick(1, "QB")
        second = make_pick(2, "QB")
        first["metadata"].update({"first_name": "Old", "last_name": "Starter"})
        second["metadata"].update({"first_name": "Old", "last_name": "Backup"})
        snapshot = {
            "history": [
                {
                    "drafts": [
                        {
                            "draft": {
                                "draft_id": "old-names",
                                "season": "2024",
                                "settings": {"teams": 2, "rounds": 2},
                            },
                            "picks": [second, first],
                        }
                    ]
                }
            ]
        }

        self.assertEqual(
            historical_position_pick_curves(snapshot).position_picks["QB"],
            (1, 2),
        )
        unavailable = historical_position_pick_curves({})
        self.assertFalse(unavailable.available)
        self.assertIn("raw ADP", unavailable.issues[0])

    def test_2025_qb_slot_pick_regression_fixture(self) -> None:
        qb_picks = (19, 26, 35, 44, 52, 56, 63, 79, 88, 118, 120, 131, 133, 136, 143, 152, 156, 169, 172, 178)
        snapshot = {
            "history": [
                {
                    "drafts": [
                        {
                            "draft": {
                                "draft_id": "synthetic-history-draft",
                                "season": "2025",
                                "settings": {"teams": 12, "rounds": 15},
                            },
                            "picks": [make_pick(pick_no, "QB") for pick_no in reversed(qb_picks)],
                        }
                    ]
                }
            ]
        }

        curves = historical_position_pick_curves(snapshot)
        self.assertEqual(curves.position_picks["QB"], qb_picks)
        self.assertEqual(curves.draft_end_pick + 1, 181)

    def test_combines_linked_drafts_equally_by_position_slot_with_censoring(self) -> None:
        def draft_bundle(draft_id: str, qb_picks: tuple[int, ...]) -> dict:
            return {
                "drafts": [
                    {
                        "draft": {
                            "draft_id": draft_id,
                            "season": "2025",
                            "settings": {"teams": 2, "rounds": 3},
                        },
                        "picks": [make_pick(pick_no, "QB") for pick_no in qb_picks],
                    }
                ]
            }

        curves = historical_position_pick_curves(
            {
                "history": [
                    draft_bundle("league-a", (2, 5)),
                    draft_bundle("league-b", (4,)),
                ]
            }
        )

        self.assertEqual(curves.position_picks["QB"], (3.0, 6.0))
        self.assertEqual(curves.draft_end_pick, 6.0)
        self.assertEqual(len(curves.sources), 2)
        self.assertEqual(curves.metadata()["draft_count"], 2)
        self.assertIn("Equal-weight", curves.source)

    def test_excludes_complete_managers_and_renumbers_retained_picks(self) -> None:
        picks = [
            make_pick(1, "QB", "a"),
            make_pick(2, "RB", "b"),
            make_pick(3, "WR", "c"),
            make_pick(4, "TE", "d"),
            make_pick(5, "RB", "d"),
            make_pick(6, "QB", "c"),
            make_pick(7, "WR", "b"),
            make_pick(8, "TE", "a"),
        ]
        snapshot = {
            "history": [
                {
                    "league": {"league_id": "league-a"},
                    "users": [
                        {"user_id": "b", "display_name": "Absent B"},
                        {"user_id": "d", "display_name": "Absent D"},
                    ],
                    "drafts": [
                        {
                            "draft": {
                                "draft_id": "draft-a",
                                "season": "2025",
                                "settings": {"teams": 4, "rounds": 2},
                            },
                            "picks": picks,
                        }
                    ],
                }
            ]
        }

        curves = historical_position_pick_curves(
            snapshot,
            excluded_user_ids=("b", "d"),
        )

        self.assertTrue(curves.available)
        self.assertEqual(curves.position_picks["QB"], (1, 3))
        self.assertEqual(curves.position_picks["WR"], (2,))
        self.assertEqual(curves.position_picks["TE"], (4,))
        self.assertEqual(curves.draft_end_pick, 4)
        self.assertEqual(curves.excluded_user_ids, ("b", "d"))
        audit = curves.metadata()["exclusion_audit"][0]
        self.assertEqual(audit["original_team_count"], 4)
        self.assertEqual(audit["effective_team_count"], 2)
        self.assertEqual(audit["excluded_pick_count"], 4)
        self.assertEqual(audit["excluded_manager_names"], ["Absent B", "Absent D"])
        self.assertTrue(audit["renumbered_in_original_order"])
        self.assertIn("Absent B", curves.sources[0])

    def test_manager_exclusion_requires_a_complete_pick_set_per_draft(self) -> None:
        snapshot = {
            "history": [
                {
                    "drafts": [
                        {
                            "draft": {
                                "draft_id": "complete-exclusion",
                                "season": "2025",
                                "settings": {"teams": 2, "rounds": 2},
                            },
                            "picks": [
                                make_pick(1, "QB", "absent"),
                                make_pick(2, "RB", "returning"),
                                make_pick(3, "WR", "returning"),
                                make_pick(4, "TE", "absent"),
                            ],
                        }
                    ]
                },
                {
                    "drafts": [
                        {
                            "draft": {
                                "draft_id": "incomplete-exclusion",
                                "season": "2025",
                                "settings": {"teams": 2, "rounds": 2},
                            },
                            "picks": [
                                make_pick(1, "QB", "absent"),
                                make_pick(2, "RB", "returning"),
                                make_pick(3, "WR", "returning"),
                                make_pick(4, "TE", "returning"),
                            ],
                        }
                    ]
                }
            ]
        }

        curves = historical_position_pick_curves(
            snapshot,
            excluded_user_ids=("absent",),
        )

        self.assertFalse(curves.available)
        self.assertTrue(
            any("1/2 picks" in issue for issue in curves.issues),
            curves.issues,
        )


if __name__ == "__main__":
    unittest.main()
