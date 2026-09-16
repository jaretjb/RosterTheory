from __future__ import annotations

import unittest
from datetime import datetime, timezone

from roster_theory.sleeper import SleeperClient
from roster_theory.trade_provider_probe import (
    describe_schema,
    probe_fantasypros,
    probe_sleeper,
)


class TradeProviderProbeTests(unittest.TestCase):
    def test_fantasypros_probe_is_bounded_and_retains_no_rows(self) -> None:
        class FakeClient:
            request_count = 0
            last_get_metadata = {"rate_limit_headers": {"x-ratelimit-limit": "500"}}

            def response(self, **metadata):
                self.request_count += 1
                return {
                    **metadata,
                    "count": 2,
                    "players": [
                        {"player_id": 11, "rank_ecr": 1, "stats": {"rush_yds": 10}},
                        {"player_id": 12, "rank_ecr": 2, "stats": {"rush_yds": 9}},
                    ],
                    "expert_names": {"22": "Expert"},
                }

            def consensus_rankings(self, season, **params):
                return self.response(
                    season=str(season),
                    week=str(params.get("week", 0)),
                    ranking_type_name=(
                        "weekly" if "week" in params else "draft"
                    ),
                    fallback_for=("ROS" if params.get("type") == "ROS" else None),
                )

            def ranking_experts(self, season, **params):
                return self.response(season=str(season))

            def projections(self, season, **params):
                return self.response(season=str(season), week=str(params.get("week", 1)))

            def news(self, **params):
                return self.response(items=[{"id": 1, "created": "now"}])

            def players(self):
                return self.response()

            def player_points(self, season, **params):
                return self.response(season=str(season), scoring=params["scoring"])

            def compare_players(self, **params):
                return self.response(type=params["ranking_type"])

        waits: list[float] = []
        report = probe_fantasypros(
            FakeClient(),
            season=2026,
            week=1,
            historical_season=2025,
            sleep=waits.append,
            captured_at=datetime(2026, 9, 4, tzinfo=timezone.utc),
        )
        self.assertEqual(report["requests_attempted"], 10)
        self.assertEqual(len(waits), 9)
        self.assertFalse(report["raw_rows_saved"])
        self.assertEqual(report["datasets"]["ros_ecr"]["coverage"]["row_count"], 2)
        self.assertNotIn("players", report["datasets"]["ros_ecr"])
        self.assertTrue(report["capability_assessment"]["weekly_ecr"])
        self.assertFalse(report["capability_assessment"]["current_ros_ecr"])

    def test_schema_description_does_not_retain_object_map_ids_or_values(self) -> None:
        players = {
            str(index): {"player_id": str(index), "full_name": f"Player {index}"}
            for index in range(60)
        }
        shape = describe_schema(players)
        rendered = repr(shape)
        self.assertEqual(shape["type"], "object_map")
        self.assertEqual(shape["count"], 60)
        self.assertNotIn("Player 1", rendered)
        self.assertNotIn("'59':", rendered)
        points_shape = describe_schema({"10222": 1.5, "SEA": 4.0})
        self.assertEqual(points_shape["type"], "object_map")
        self.assertEqual(points_shape["count"], 2)

    def test_probe_records_only_get_schema_evidence(self) -> None:
        urls: list[str] = []

        def transport(url: str):
            urls.append(url)
            if url.endswith("state/nfl"):
                return {"season": "2026", "week": 1}
            if "/league/league-1" in url and url.endswith("league-1"):
                return {"league_id": "league-1", "settings": {"playoff_week_start": 15}}
            if url.endswith("/players/nfl"):
                return {str(index): {"player_id": str(index)} for index in range(60)}
            if url.endswith("/rosters"):
                return [
                    {
                        "roster_id": 1,
                        "owner_id": "owner-1",
                        "players": ["101", "102"],
                        "starters": ["101"],
                    }
                ]
            if "winners_bracket" in url:
                return [{"r": 2, "m": 1}]
            return [{"roster_id": 1, "matchup_id": 1}]

        report = probe_sleeper(
            SleeperClient(transport=transport),
            "league-1",
            user_id="owner-1",
            weeks=[1, 15],
            include_trends=True,
            captured_at=datetime(2026, 9, 4, tzinfo=timezone.utc),
        )

        self.assertTrue(report["read_only"])
        self.assertFalse(report["raw_rows_saved"])
        self.assertEqual(report["datasets"]["players"]["count"], 60)
        self.assertEqual(report["league_audit"]["user_roster_id"], 1)
        self.assertEqual(report["league_audit"]["derived_championship_week"], 16)
        self.assertEqual(
            report["league_audit"]["duplicate_player_ownership_count"], 0
        )
        self.assertEqual(
            set(report["datasets"]),
            {
                "nfl_state",
                "league",
                "users",
                "rosters",
                "winners_bracket",
                "losers_bracket",
                "matchups_week_1",
                "transactions_week_1",
                "matchups_week_15",
                "transactions_week_15",
                "players",
                "trending_adds",
                "trending_drops",
            },
        )
        self.assertTrue(all(item["method"] == "GET" for item in report["datasets"].values()))
        self.assertTrue(all(url.startswith("https://api.sleeper.app/v1/") for url in urls))


if __name__ == "__main__":
    unittest.main()
