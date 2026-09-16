import argparse
import json
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from roster_theory.cli import build_parser, command_trade_refresh
from roster_theory.core.errors import (
    IdentityIncomplete,
    RequestBudgetExceeded,
    ScheduleIncomplete,
    StaleData,
    ProviderCapabilityMissing,
)
from roster_theory.core.models import Player
from roster_theory.providers.cache import DailyRequestBudget
from roster_theory.providers.fantasypros import (
    FantasyProsAdapter,
    normalize_news,
    normalize_player_points,
    normalize_projections,
    normalize_rankings,
)
from roster_theory.providers.sleeper import SleeperAdapter
from roster_theory.trade.call_plan import PlannedCall, build_call_plan, execute_call_plan
from roster_theory.trade.schedule import ScheduleConfig, build_evaluation_weeks, load_schedule
from roster_theory.trade.snapshot import (
    assert_current,
    build_trade_snapshot,
    load_trade_snapshot,
    save_trade_snapshot,
)


class FakeSleeperClient:
    def __init__(self, *, duplicate=False, incomplete_matchup=False):
        self.players_calls = 0
        self.duplicate = duplicate
        self.incomplete_matchup = incomplete_matchup

    def state(self, _sport="nfl"):
        return {"season": "2026", "week": 1}

    def league(self, league_id):
        return {
            "league_id": league_id,
            "season": "2026",
            "total_rosters": 2,
            "roster_positions": ["QB", "RB", "WR", "WRRB_FLEX", "BN"],
            "scoring_settings": {"pass_yd": 0.04, "rec": 0.5},
            "settings": {
                "playoff_week_start": 2,
                "reserve_slots": 0,
                "trade_deadline": 99,
                "waiver_type": 2,
                "waiver_budget": 100,
            },
        }

    def league_users(self, _league_id):
        return [
            {"user_id": "u1", "display_name": "One"},
            {"user_id": "u2", "metadata": {"team_name": "Two Team"}},
        ]

    def league_rosters(self, _league_id):
        second = ["p1", "p2"] if self.duplicate else ["p2"]
        return [
            {
                "roster_id": 1,
                "owner_id": "u1",
                "players": ["p1"],
                "starters": ["p1"],
                "settings": {"waiver_position": 3, "waiver_budget_used": 17},
            },
            {
                "roster_id": 2,
                "owner_id": "u2",
                "players": second,
                "starters": ["p2"],
                "settings": {"waiver_position": 1, "waiver_budget_used": 0},
            },
        ]

    def league_winners_bracket(self, _league_id):
        return [{"r": 1, "m": 1}]

    def league_losers_bracket(self, _league_id):
        return []

    def players(self, _sport="nfl"):
        self.players_calls += 1
        return {
            "p1": {
                "player_id": "p1",
                "full_name": "Quarter Back",
                "fantasy_positions": ["QB"],
                "team": "CIN",
                "active": True,
                "yahoo_id": "y1",
            },
            "p2": {
                "player_id": "p2",
                "full_name": "Runner",
                "fantasy_positions": ["RB"],
                "team": "SEA",
                "active": True,
                "yahoo_id": "y2",
            },
            "fa": {
                "player_id": "fa",
                "full_name": "Free Agent",
                "fantasy_positions": ["WR"],
                "team": "LAR",
                "active": True,
            },
            "retired": {
                "player_id": "retired",
                "full_name": "Retired",
                "fantasy_positions": ["WR"],
                "team": None,
                "active": False,
            },
        }

    def league_matchups(self, _league_id, _week):
        if self.incomplete_matchup:
            return [{"roster_id": 1, "matchup_id": 1}]
        return [
            {"roster_id": 1, "matchup_id": 1},
            {"roster_id": 2, "matchup_id": 1},
        ]

    def league_transactions(self, _league_id, week):
        return (
            [
                {
                    "transaction_id": f"t{week}",
                    "type": "trade",
                    "status": "complete",
                    "roster_ids": [1, 2],
                    "adds": {"p1": 2},
                    "drops": {"p2": 2},
                    "created": 1_000,
                    "status_updated": 2_000,
                    "creator": "u1",
                    "settings": {"waiver_bid": 23},
                    "metadata": {"notes": "fixture"},
                }
            ]
            if week == 1
            else []
        )


def schedule_fixture() -> ScheduleConfig:
    teams = (
        "ARI", "ATL", "BAL", "BUF", "CAR", "CHI", "CIN", "CLE",
        "DAL", "DEN", "DET", "GB", "HOU", "IND", "JAX", "KC",
        "LAC", "LAR", "LV", "MIA", "MIN", "NE", "NO", "NYG",
        "NYJ", "PHI", "PIT", "SEA", "SF", "TB", "TEN", "WAS",
    )
    return ScheduleConfig(
        season=2026,
        weeks=(1, 2),
        teams=teams,
        bye_weeks=tuple((team, 2) for team in teams),
        source="fixture",
        source_url="https://example.test/schedule",
        verified_at="2026-09-04",
        payload_hash="schedule-hash",
    )


class SleeperAdapterTests(unittest.TestCase):
    def test_adapter_normalizes_and_reuses_daily_player_cache(self) -> None:
        client = FakeSleeperClient()
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / "players.json"
            first = SleeperAdapter(client, player_cache_path=cache).fetch("league-1", [1, 2])
            second = SleeperAdapter(client, player_cache_path=cache).fetch("league-1", [1, 2])

        self.assertEqual(client.players_calls, 1)
        self.assertEqual(first.player_directory_cache_status, "miss")
        self.assertEqual(second.player_directory_cache_status, "hit")
        self.assertEqual(first.league.championship_week, 2)
        self.assertIn(("waiver_budget", 100), first.league.platform_settings)
        self.assertEqual(first.teams[1].display_name, "Two Team")
        self.assertEqual(first.teams[0].waiver_position, 3)
        self.assertEqual(first.teams[0].waiver_budget_used, 17)
        self.assertEqual(first.players[0].external_ids, ())
        self.assertEqual(len(first.matchups), 2)
        self.assertEqual(first.transactions[0].transaction_id, "t1")
        self.assertEqual(first.transactions[0].created_at_ms, 1_000)
        self.assertEqual(first.transactions[0].status_updated_at_ms, 2_000)
        self.assertEqual(first.transactions[0].creator_id, "u1")
        self.assertEqual(first.transactions[0].waiver_bid, 23)
        self.assertEqual(first.transactions[0].metadata, (("notes", "fixture"),))

    def test_malformed_league_stops_normalization(self) -> None:
        client = FakeSleeperClient()
        client.league = lambda _league_id: {"league_id": "league-1"}
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "required identity"):
                SleeperAdapter(client, player_cache_path=Path(directory) / "p.json").fetch(
                    "league-1", [1]
                )


class FantasyProsAdapterTests(unittest.TestCase):
    def test_rankings_preserve_horizon_fallback_contributors_and_ids(self) -> None:
        captured = datetime(2026, 9, 4, tzinfo=timezone.utc)
        value = {
            "year": "2026",
            "week": "0",
            "scoring": "HALF",
            "ranking_type_name": "draft",
            "fallback_for": "ROS",
            "last_updated": "9/04",
            "expert_names": {"17": "Expert"},
            "players": [
                {
                    "player_id": 10,
                    "player_name": "Runner",
                    "player_position_id": "RB",
                    "player_team_id": "SEA",
                    "player_yahoo_id": "y2",
                    "rank_ecr": 4,
                    "pos_rank": "RB2",
                    "tier": 1,
                }
            ],
        }
        dataset = normalize_rankings(
            value,
            requested_horizon="ROS",
            board_source="market",
            captured_at=captured,
        )
        self.assertFalse(dataset.complete_horizon)
        self.assertEqual(dataset.fallback_for, "ROS")
        self.assertEqual(dataset.contributor_ids, ("17",))
        self.assertEqual(dataset.identities[0].external_ids, (("yahoo", "y2"),))
        self.assertEqual(dataset.observations[0].overall_rank, 4)
        self.assertEqual(dataset.observations[0].position_rank, 2)
        self.assertEqual(dataset.stamp.warnings, ("fallback_for:ROS",))

    def test_waiver_horizon_is_canonical_and_preserves_raw_label_and_dispersion(self) -> None:
        dataset = normalize_rankings(
            {
                "year": "2026",
                "week": "2",
                "scoring": "PPR",
                "ranking_type_name": "Waiver Wire",
                "last_updated": "2026-09-14T08:00:00+00:00",
                "players": [
                    {
                        "player_id": 10,
                        "player_name": "Runner",
                        "player_position_id": "RB",
                        "rank_ecr": 3,
                        "rank_min": 1,
                        "rank_max": 9,
                        "rank_std": 2.5,
                        "pos_rank": "RB2",
                    }
                ],
            },
            requested_horizon="WAIVER",
            board_source="market",
        )
        self.assertTrue(dataset.complete_horizon)
        self.assertEqual(dataset.horizon, "WAIVER")
        self.assertEqual(dataset.raw_horizon, "Waiver Wire")
        self.assertEqual(dataset.observations[0].rank_min, 1.0)
        self.assertEqual(dataset.observations[0].rank_max, 9.0)
        self.assertEqual(dataset.observations[0].rank_std, 2.5)

    def test_missing_provider_horizon_is_not_complete(self) -> None:
        dataset = normalize_rankings(
            {"year": "2026", "players": []},
            requested_horizon="WAIVER",
            board_source="market",
        )
        self.assertFalse(dataset.complete_horizon)

    def test_projections_news_and_points_preserve_contract_fields(self) -> None:
        projections = normalize_projections(
            {
                "season": "2026",
                "week": "1",
                "scoring": "HALF",
                "experts": [3, 1],
                "players": [
                    {
                        "fpid": 10,
                        "name": "Runner",
                        "position_id": "RB",
                        "team_id": "SEA",
                        "stats": {"rush_yds": "80", "rush_tds": 1},
                    }
                ],
            },
            horizon="WEEKLY",
            league_points={"10": 14.0},
        )
        self.assertEqual(projections.week, 1)
        self.assertEqual(projections.contributor_ids, ("1", "3"))
        self.assertEqual(projections.projections[0].league_points, 14)
        self.assertEqual(projections.projections[0].raw_stats[0], ("rush_tds", 1.0))

        news = normalize_news({"items": [{"player_id": 10, "title": "Limited", "category": "injury"}]})
        self.assertEqual(news[0].category, "injury")
        points = normalize_player_points(
            {
                "players": [
                    {"player_id": 10, "position_id": "RB", "points": 22, "weeks": {"1": 8, "2": 14}}
                ]
            }
        )
        self.assertEqual(points[0].weekly_points, ((1, 8.0), (2, 14.0)))

    def test_client_adapter_rejects_draft_fallback_and_scores_weekly_stats(self) -> None:
        class Client:
            def consensus_rankings(self, _season, **_params):
                return {
                    "year": "2026",
                    "week": "0",
                    "ranking_type_name": "draft",
                    "fallback_for": "ROS",
                    "players": [],
                }

            def projections(self, _season, **params):
                return {
                    "season": "2026",
                    "week": str(params["week"]),
                    "players": [
                        {"fpid": 10, "name": "Runner", "position_id": "RB", "stats": {"rush_yds": 80}}
                    ],
                }

        adapter = FantasyProsAdapter(Client())
        with self.assertRaises(ProviderCapabilityMissing):
            adapter.rankings(2026, "RB", horizon="ROS")
        projections = adapter.weekly_projections(
            2026, 1, "RB", {"rush_yd": 0.1}
        )
        self.assertEqual(projections.projections[0].league_points, 8.0)

    def test_client_adapter_requests_waiver_horizon_and_selected_expert(self) -> None:
        calls = []

        class Client:
            def consensus_rankings(self, _season, **params):
                calls.append(params)
                return {
                    "year": "2026",
                    "week": "2",
                    "ranking_type_name": "WW",
                    "players": [],
                }

        dataset = FantasyProsAdapter(Client()).rankings(
            2026,
            "ALL",
            horizon="WAIVER",
            scoring="PPR",
            week=2,
            expert_id="17",
        )
        self.assertEqual(dataset.horizon, "WAIVER")
        self.assertEqual(dataset.raw_horizon, "WW")
        self.assertEqual(
            calls,
            [
                {
                    "position": "ALL",
                    "scoring": "PPR",
                    "type": "WW",
                    "week": 2,
                    "filters": "17:17",
                }
            ],
        )


class ScheduleAndSnapshotTests(unittest.TestCase):
    def _bundle(self, client=None):
        client = client or FakeSleeperClient()
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        return SleeperAdapter(
            client, player_cache_path=Path(directory.name) / "players.json"
        ).fetch("league-1", [1, 2])

    def test_synthetic_schedule_fixture_is_complete(self) -> None:
        path = (
            Path(__file__).parent
            / "fixtures"
            / "provider"
            / "nfl_schedule.synthetic.json"
        )
        schedule = load_schedule(path)
        self.assertEqual(schedule.season, 2099)
        self.assertEqual(len(schedule.teams), 32)
        self.assertEqual(len(schedule.bye_weeks), 32)
        self.assertIn(2, schedule.weeks)
        self.assertEqual(schedule.source, "RosterTheory synthetic fixture")

    def test_schedule_stops_on_missing_horizon_or_matchups(self) -> None:
        bundle = self._bundle(FakeSleeperClient(incomplete_matchup=True))
        with self.assertRaises(ScheduleIncomplete):
            build_trade_snapshot(
                league_key="fixture",
                user_id="u1",
                ranking_horizon="WEEKLY-PROXY",
                sleeper=bundle,
                schedule=schedule_fixture(),
            )
        with self.assertRaises(ScheduleIncomplete):
            build_evaluation_weeks(
                current_week=1,
                championship_week=3,
                playoff_start_week=2,
                team_count=2,
                matchups=bundle.matchups,
                schedule=schedule_fixture(),
            )

    def test_snapshot_is_deterministic_complete_and_offline_is_noncurrent(self) -> None:
        bundle = self._bundle()
        first = build_trade_snapshot(
            league_key="fixture",
            user_id="u1",
            ranking_horizon="WEEKLY-PROXY",
            sleeper=bundle,
            schedule=schedule_fixture(),
        )
        second = build_trade_snapshot(
            league_key="fixture",
            user_id="u1",
            ranking_horizon="WEEKLY-PROXY",
            sleeper=bundle,
            schedule=schedule_fixture(),
        )
        self.assertTrue(first.completeness.snapshot_complete)
        self.assertFalse(first.completeness.valuation_inputs_complete)
        self.assertEqual(first.manifest.analysis_id, second.manifest.analysis_id)
        self.assertEqual(first.free_agent_ids, ("fa",))
        self.assertEqual(first.owner_by_player, (("p1", "1"), ("p2", "2")))
        self.assertEqual(len(first.weeks), 2)

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "snapshot.json"
            save_trade_snapshot(first, path)
            offline = load_trade_snapshot(path)
        self.assertFalse(offline.current)
        self.assertEqual(offline.manifest.analysis_id, first.manifest.analysis_id)
        self.assertEqual(offline.league.platform_settings, first.league.platform_settings)
        self.assertEqual(offline.teams[0].waiver_position, 3)
        self.assertIn("OFFLINE/NON-CURRENT snapshot", offline.warnings)
        with self.assertRaises(StaleData):
            assert_current(offline)
        with self.assertRaises(StaleData):
            assert_current(
                replace(first, captured_at=datetime.now(timezone.utc) - timedelta(hours=1))
            )

    def test_special_team_identity_directory_does_not_expand_tradeable_players(self) -> None:
        bundle = self._bundle()
        bundle = replace(
            bundle,
            players=(
                *bundle.players,
                Player("TB", "Tampa Bay Buccaneers", ("DST",), nfl_team="TB", active=True),
                Player("k1", "Kicker", ("K",), nfl_team="SF", active=True),
            ),
        )

        snapshot = build_trade_snapshot(
            league_key="fixture",
            user_id="u1",
            ranking_horizon="WEEKLY-PROXY",
            sleeper=bundle,
            schedule=schedule_fixture(),
            include_special_team_identities=True,
        )

        self.assertTrue({"TB", "k1"}.issubset({row.player_id for row in snapshot.players}))
        self.assertNotIn("TB", snapshot.tradeable_player_ids)
        self.assertNotIn("k1", snapshot.tradeable_player_ids)

    def test_duplicate_ownership_stops_snapshot(self) -> None:
        with self.assertRaisesRegex(IdentityIncomplete, "Duplicate"):
            build_trade_snapshot(
                league_key="fixture",
                user_id="u1",
                ranking_horizon="WEEKLY-PROXY",
                sleeper=self._bundle(FakeSleeperClient(duplicate=True)),
                schedule=schedule_fixture(),
            )


class CallPlanAndCliTests(unittest.TestCase):
    def test_call_plan_deduplicates_and_respects_budget(self) -> None:
        call = PlannedCall(
            "weekly",
            "FantasyPros",
            "/rank",
            (("week", 1),),
        )
        plan = build_call_plan([call, call], DailyRequestBudget(limit=2))
        self.assertEqual(plan.fantasypros_calls, 1)
        self.assertEqual(plan.duplicate_calls_removed, 1)
        self.assertEqual(plan.fantasypros_remaining_after_plan, 1)
        with self.assertRaises(RequestBudgetExceeded):
            build_call_plan([call], DailyRequestBudget(limit=0))

    def test_call_execution_uses_cache_skips_optional_and_reserves_paid_budget(self) -> None:
        calls = [
            PlannedCall("cached", "FantasyPros", "/cached", fresh_cache_hit=True),
            PlannedCall("required", "FantasyPros", "/required"),
            PlannedCall("optional", "Sleeper", "/optional", required=False),
        ]
        budget = DailyRequestBudget(limit=2)
        plan = build_call_plan(calls, budget)
        result = execute_call_plan(plan, {"required": lambda: {"ok": True}}, budget)
        self.assertEqual(result, {"required": {"ok": True}})
        self.assertEqual(budget.used, 1)
        self.assertEqual(plan.cache_hits, 1)
        self.assertEqual(plan.optional_calls, 1)

    def test_nested_trade_refresh_parser_is_data_only(self) -> None:
        args = build_parser().parse_args(["trade", "refresh", "league_alpha"])
        self.assertEqual(args.ranking_horizon, "WEEKLY-PROXY")
        self.assertIs(args.func, command_trade_refresh)

    @patch("roster_theory.cli.refresh_trade_snapshot", side_effect=ValueError("bad snapshot"))
    def test_refresh_exits_nonzero_on_required_failure(self, _mocked_refresh) -> None:
        args = argparse.Namespace(
            league="fixture",
            ranking_horizon="WEEKLY-PROXY",
            schedule="missing.json",
            player_cache="players.json",
            output=None,
        )
        with self.assertRaisesRegex(SystemExit, "2"):
            command_trade_refresh(args)


if __name__ == "__main__":
    unittest.main()
