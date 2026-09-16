import unittest

from roster_theory.sleeper import SleeperClient
from roster_theory.sleeper_adp import (
    audit_board_against_sleeper_adp,
    audit_historical_drafts_against_archived_adp,
    build_sleeper_adp_snapshot,
    scoring_adp_field,
)


class SleeperAdpTests(unittest.TestCase):
    @staticmethod
    def projections() -> list[dict]:
        return [
            {
                "player_id": "1",
                "player": {
                    "first_name": "First",
                    "last_name": "Runner",
                    "position": "RB",
                    "team": "AAA",
                },
                "stats": {"adp_half_ppr": 10.0},
                "updated_at": 100,
                "last_modified": 90,
            },
            {
                "player_id": "2",
                "player": {
                    "first_name": "Second",
                    "last_name": "Receiver",
                    "position": "WR",
                },
                "team": "BBB",
                "stats": {"adp_half_ppr": 20.0},
            },
            {
                "player_id": "3",
                "player": {
                    "first_name": "Kicker",
                    "last_name": "Only",
                    "position": "K",
                },
                "stats": {"adp_half_ppr": 1.0},
            },
            {
                "player_id": "4",
                "player": {
                    "first_name": "Missing",
                    "last_name": "Quarterback",
                    "position": "QB",
                },
                "stats": {"adp_half_ppr": 999.0},
            },
        ]

    def test_scoring_field_and_projection_endpoint_are_explicit(self) -> None:
        urls = []

        def transport(url: str):
            urls.append(url)
            return self.projections()

        rows = SleeperClient(transport=transport).season_projections(
            2026, scoring_adp_field("half_ppr")
        )

        self.assertEqual(len(rows), 4)
        self.assertIn("/projections/nfl/2026?", urls[0])
        self.assertIn("order_by=adp_half_ppr", urls[0])

    def test_snapshot_preserves_dated_adp_without_claiming_visual_verification(self) -> None:
        snapshot = build_sleeper_adp_snapshot(
            self.projections(), 2026, "half_ppr", captured_at=12345
        )

        self.assertEqual(snapshot["captured_at"], 12345)
        self.assertEqual(snapshot["adp_field"], "adp_half_ppr")
        self.assertEqual(snapshot["usable_skill_players"], 2)
        self.assertEqual(
            [row["player_id"] for row in snapshot["players"]], ["1", "2"]
        )
        self.assertTrue(snapshot["source"]["public_web_client_field_verified"])
        self.assertFalse(snapshot["source"]["visual_draft_room_verified"])

    def test_current_board_comparison_is_audit_only_data(self) -> None:
        snapshot = build_sleeper_adp_snapshot(
            self.projections(), 2026, "half_ppr", captured_at=12345
        )
        board = [
            {
                "sleeper_id": "1",
                "player_name": "First Runner",
                "position": "RB",
                "adp": 12,
            },
            {
                "sleeper_id": "2",
                "player_name": "Second Receiver",
                "position": "WR",
                "adp": 50,
            },
            {
                "sleeper_id": "missing",
                "player_name": "Unmatched Tight End",
                "position": "TE",
                "adp": 60,
            },
        ]

        audit = audit_board_against_sleeper_adp(board, snapshot)

        self.assertEqual(audit["eligible_board_players"], 3)
        self.assertEqual(audit["matched_players"], 2)
        self.assertEqual(audit["median_absolute_adp_gap"], 16.0)
        self.assertEqual(
            audit["largest_disagreements"][0]["player_name"],
            "Second Receiver",
        )

    def test_historical_audit_is_labeled_an_unvalidated_proxy(self) -> None:
        archived = build_sleeper_adp_snapshot(
            self.projections(), 2025, "half_ppr", captured_at=12345
        )
        league_snapshot = {
            "history": [
                {
                    "league": {"league_id": "league", "season": "2025"},
                    "drafts": [
                        {
                            "draft": {
                                "draft_id": "draft",
                                "status": "complete",
                                "start_time": 1000,
                            },
                            "picks": [
                                {
                                    "pick_no": 9,
                                    "player_id": "1",
                                    "metadata": {"position": "RB"},
                                },
                                {
                                    "pick_no": 30,
                                    "player_id": "2",
                                    "metadata": {"position": "WR"},
                                },
                                {
                                    "pick_no": 31,
                                    "player_id": "missing",
                                    "metadata": {"position": "TE"},
                                },
                            ],
                        }
                    ],
                }
            ]
        }

        audit = audit_historical_drafts_against_archived_adp(
            league_snapshot, archived
        )

        self.assertEqual(audit["status"], "exploratory_proxy_only")
        self.assertFalse(audit["can_validate_draft_day_order"])
        self.assertEqual(audit["drafts"][0]["matched_picks"], 2)
        self.assertEqual(audit["drafts"][0]["median_absolute_pick_gap"], 5.5)
        self.assertEqual(audit["drafts"][0]["within_12_picks"], 1.0)


if __name__ == "__main__":
    unittest.main()
