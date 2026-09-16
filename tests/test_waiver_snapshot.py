import argparse
import json
import tempfile
import unittest
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from roster_theory.cli import build_parser, command_waiver_refresh
from roster_theory.core.errors import IdentityIncomplete, RosterIllegal, StaleData
from roster_theory.providers.sleeper import SleeperAdapter, SleeperTransaction
from roster_theory.waiver.service import (
    refresh_waiver_snapshot,
    waiver_refresh_report,
    waiver_refresh_plan,
)
from roster_theory.waiver.snapshot import (
    AcquisitionState,
    assert_current,
    build_waiver_snapshot,
    classify_acquisition_state,
    load_waiver_snapshot,
    resolve_player_acquisition,
    save_waiver_snapshot,
)


class FakeSleeperClient:
    def __init__(self):
        self.calls = []
        self.players_calls = 0

    def state(self, _sport="nfl"):
        self.calls.append("state")
        return {"season": "2026", "week": 1, "season_type": "regular"}

    def league(self, league_id):
        self.calls.append("league")
        return {
            "league_id": league_id,
            "season": "2026",
            "total_rosters": 2,
            "roster_positions": ["QB", "RB", "WR", "BN"],
            "scoring_settings": {"pass_yd": 0.04, "rec": 0.5},
            "settings": {
                "reserve_slots": 1,
                "waiver_type": 2,
                "waiver_budget": 100,
            },
        }

    def league_users(self, _league_id):
        self.calls.append("users")
        return [
            {"user_id": "u1", "display_name": "One"},
            {"user_id": "u2", "display_name": "Two"},
        ]

    def league_rosters(self, _league_id):
        self.calls.append("rosters")
        return [
            {
                "roster_id": 1,
                "owner_id": "u1",
                "players": ["p1", "ir"],
                "starters": ["p1"],
                "reserve": ["ir"],
                "settings": {"waiver_position": 2, "waiver_budget_used": 11},
            },
            {
                "roster_id": 2,
                "owner_id": "u2",
                "players": ["p2"],
                "starters": ["p2"],
                "reserve": [],
                "settings": {"waiver_position": 1, "waiver_budget_used": 0},
            },
        ]

    def players(self, _sport="nfl"):
        self.calls.append("players")
        self.players_calls += 1
        return {
            "p1": {
                "player_id": "p1",
                "full_name": "Owned Quarterback",
                "fantasy_positions": ["QB"],
                "team": "SEA",
                "active": True,
            },
            "p2": {
                "player_id": "p2",
                "full_name": "Owned Runner",
                "fantasy_positions": ["RB"],
                "team": "LAR",
                "active": True,
            },
            "ir": {
                "player_id": "ir",
                "full_name": "Reserve Receiver",
                "fantasy_positions": ["WR"],
                "team": "ARI",
                "active": True,
                "injury_status": "IR",
            },
            "pending": {
                "player_id": "pending",
                "full_name": "Pending Receiver",
                "fantasy_positions": ["WR"],
                "team": "SF",
                "active": True,
            },
            "target": {
                "player_id": "target",
                "full_name": "Target Quarterback",
                "fantasy_positions": ["QB"],
                "team": "ARI",
                "active": True,
            },
            "fa": {
                "player_id": "fa",
                "full_name": "Free Agent",
                "fantasy_positions": ["WR"],
                "team": "GB",
                "active": True,
            },
            "waivers": {
                "player_id": "waivers",
                "full_name": "Waiver Player",
                "fantasy_positions": ["TE"],
                "team": "MIN",
                "active": True,
            },
            "retired": {
                "player_id": "retired",
                "full_name": "Retired Player",
                "fantasy_positions": ["WR"],
                "team": None,
                "active": False,
            },
        }

    def league_transactions(self, _league_id, week):
        self.calls.append(f"transactions:{week}")
        return [
            {
                "transaction_id": "t-pending",
                "type": "waiver",
                "status": "pending",
                "roster_ids": [1],
                "adds": {"pending": 1},
                "drops": None,
                "created": 1_000,
                "status_updated": 2_000,
                "creator": "u1",
                "settings": {"waiver_bid": 7},
                "metadata": {"notes": "fixture"},
            }
        ]


class WaiverSnapshotTests(unittest.TestCase):
    def _bundle(self, client=None):
        client = client or FakeSleeperClient()
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        bundle = SleeperAdapter(
            client,
            player_cache_path=Path(directory.name) / "players.json",
        ).fetch_waiver("league-1")
        return replace(
            bundle,
            captured_at=datetime(2026, 9, 9, 12, tzinfo=timezone.utc),
        )

    def _snapshot(self, **kwargs):
        return build_waiver_snapshot(
            league_key="fixture",
            user_id="u1",
            sleeper=self._bundle(),
            expected_user_roster_id="1",
            now=datetime(2026, 9, 9, 12, 1, tzinfo=timezone.utc),
            **kwargs,
        )

    def test_waiver_fetch_is_bounded_and_reuses_fresh_player_cache(self):
        client = FakeSleeperClient()
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / "players.json"
            first = SleeperAdapter(client, player_cache_path=cache).fetch_waiver("league-1")
            second = SleeperAdapter(client, player_cache_path=cache).fetch_waiver("league-1")
        self.assertEqual(client.players_calls, 1)
        self.assertEqual(first.player_directory_cache_status, "miss")
        self.assertEqual(second.player_directory_cache_status, "hit")
        self.assertEqual(
            client.calls[:6],
            ["state", "league", "users", "rosters", "players", "transactions:1"],
        )
        self.assertEqual(len(first.stamps), 6)
        self.assertEqual(first.transactions[0].waiver_bid, 7)

    def test_waiver_fetch_refreshes_player_status_older_than_five_minutes(self):
        client = FakeSleeperClient()
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / "players.json"
            adapter = SleeperAdapter(client, player_cache_path=cache)
            adapter.fetch_waiver("league-1")
            cached = json.loads(cache.read_text(encoding="utf-8"))
            cached["captured_at"] = (
                datetime.now(timezone.utc) - timedelta(minutes=6)
            ).isoformat()
            cache.write_text(json.dumps(cached), encoding="utf-8")
            refreshed = adapter.fetch_waiver("league-1")
        self.assertEqual(client.players_calls, 2)
        self.assertEqual(refreshed.player_directory_cache_status, "miss")

    def test_snapshot_universe_includes_active_kickers_and_defenses(self):
        class SpecialTeamClient(FakeSleeperClient):
            def players(self, sport="nfl"):
                values = super().players(sport)
                values.update(
                    {
                        "k1": {
                            "player_id": "k1",
                            "full_name": "Fixture Kicker",
                            "fantasy_positions": ["K"],
                            "team": "SEA",
                            "active": True,
                        },
                        "dst1": {
                            "player_id": "dst1",
                            "full_name": "Fixture Defense",
                            "fantasy_positions": ["DEF"],
                            "team": "SEA",
                            "active": True,
                        },
                    }
                )
                return values

        snapshot = build_waiver_snapshot(
            league_key="fixture",
            user_id="u1",
            sleeper=self._bundle(SpecialTeamClient()),
            expected_user_roster_id="1",
            availability_by_player={"k1": "FREE_AGENT", "dst1": "WAIVERS"},
            now=datetime(2026, 9, 9, 12, 1, tzinfo=timezone.utc),
        )
        self.assertTrue({"k1", "dst1"}.issubset({row.player_id for row in snapshot.players}))
        states = {row.player_id: row.state for row in snapshot.acquisitions}
        self.assertEqual(states["k1"], "FREE_AGENT")
        self.assertEqual(states["dst1"], "WAIVERS")

    def test_classifier_covers_all_five_states_from_proved_inputs(self):
        pending = SleeperTransaction(
            transaction_id="t1",
            week=1,
            transaction_type="waiver",
            status="pending",
            roster_ids=("1",),
            adds=(("pending", "1"),),
            drops=(),
        )
        cases = (
            ("owned", {"owned": "1"}, (), None, AcquisitionState.LOCKED),
            ("pending", {}, (pending,), None, AcquisitionState.PENDING),
            ("free", {}, (), "free_agent", AcquisitionState.FREE_AGENT),
            ("waivers", {}, (), "waivers", AcquisitionState.WAIVERS),
            ("unknown", {}, (), None, AcquisitionState.UNROSTERED),
        )
        for player_id, owners, transactions, explicit, expected in cases:
            with self.subTest(state=expected.value):
                result = classify_acquisition_state(
                    player_id,
                    owner_by_player=owners,
                    transactions=transactions,
                    explicit_status=explicit,
                )
                self.assertEqual(result.state, expected.value)

    def test_snapshot_is_immutable_deterministic_and_fail_closed(self):
        bundle = self._bundle()
        arguments = {
            "league_key": "fixture",
            "user_id": "u1",
            "sleeper": bundle,
            "expected_user_roster_id": "1",
            "now": datetime(2026, 9, 9, 12, 1, tzinfo=timezone.utc),
        }
        first = build_waiver_snapshot(**arguments)
        second = build_waiver_snapshot(**arguments)
        self.assertEqual(first.manifest.analysis_id, second.manifest.analysis_id)
        self.assertTrue(first.completeness.roster_snapshot_complete)
        self.assertTrue(first.completeness.acquisition_state_complete)
        self.assertTrue(first.completeness.snapshot_complete)
        self.assertEqual(
            resolve_player_acquisition(first, "target quarterback").state,
            "UNROSTERED",
        )
        self.assertFalse(first.recommendation_generated)
        self.assertFalse(first.sleeper_write_performed)
        with self.assertRaises(FrozenInstanceError):
            first.current = False

    def test_explicit_availability_can_complete_the_acquisition_view(self):
        snapshot = self._snapshot(
            availability_by_player={
                "pending": "free_agent",
                "target": "waivers",
                "fa": "free_agent",
                "waivers": "waivers",
            }
        )
        states = {item.player_id: item.state for item in snapshot.acquisitions}
        self.assertEqual(states["pending"], "PENDING")
        self.assertEqual(states["target"], "WAIVERS")
        self.assertTrue(snapshot.completeness.acquisition_state_complete)
        self.assertTrue(snapshot.completeness.snapshot_complete)

    def test_roster_capacity_and_reserve_membership_are_validated(self):
        snapshot = self._snapshot()
        user = next(item for item in snapshot.roster_capacity if item.roster_id == "1")
        self.assertEqual(user.active_limit, 4)
        self.assertEqual(user.active_count, 1)
        self.assertEqual(user.open_active_slots, 3)
        self.assertTrue(user.reserve_legal)

        bundle = self._bundle()
        bad_team = replace(bundle.teams[0], reserve_ids=("not-on-roster",))
        with self.assertRaisesRegex(RosterIllegal, "reserve outside"):
            build_waiver_snapshot(
                league_key="fixture",
                user_id="u1",
                sleeper=replace(bundle, teams=(bad_team, bundle.teams[1])),
                now=datetime(2026, 9, 9, 12, 1, tzinfo=timezone.utc),
            )

    def test_identity_roster_count_and_freshness_fail_visibly(self):
        bundle = self._bundle()
        duplicate = replace(bundle.teams[1], player_ids=("p1",))
        with self.assertRaisesRegex(IdentityIncomplete, "Duplicate"):
            build_waiver_snapshot(
                league_key="fixture",
                user_id="u1",
                sleeper=replace(bundle, teams=(bundle.teams[0], duplicate)),
                now=datetime(2026, 9, 9, 12, 1, tzinfo=timezone.utc),
            )
        with self.assertRaisesRegex(IdentityIncomplete, "roster count"):
            build_waiver_snapshot(
                league_key="fixture",
                user_id="u1",
                sleeper=replace(bundle, teams=(bundle.teams[0],)),
                now=datetime(2026, 9, 9, 12, 1, tzinfo=timezone.utc),
            )
        with self.assertRaises(StaleData):
            build_waiver_snapshot(
                league_key="fixture",
                user_id="u1",
                sleeper=bundle,
                now=datetime(2026, 9, 9, 13, tzinfo=timezone.utc),
            )

    def test_missing_rostered_identity_and_wrong_user_roster_fail(self):
        bundle = self._bundle()
        with self.assertRaisesRegex(IdentityIncomplete, "missing from Sleeper"):
            build_waiver_snapshot(
                league_key="fixture",
                user_id="u1",
                sleeper=replace(
                    bundle,
                    players=tuple(player for player in bundle.players if player.player_id != "p1"),
                ),
                now=datetime(2026, 9, 9, 12, 1, tzinfo=timezone.utc),
            )
        with self.assertRaisesRegex(IdentityIncomplete, "roster ID"):
            build_waiver_snapshot(
                league_key="fixture",
                user_id="u1",
                sleeper=bundle,
                expected_user_roster_id="2",
                now=datetime(2026, 9, 9, 12, 1, tzinfo=timezone.utc),
            )

    def test_snapshot_save_load_is_offline_and_preserves_write_guard(self):
        snapshot = self._snapshot()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "snapshot.json"
            save_waiver_snapshot(snapshot, path)
            raw = json.loads(path.read_text(encoding="utf-8"))
            offline = load_waiver_snapshot(path)
        self.assertFalse(raw["sleeper_write_performed"])
        self.assertFalse(raw["recommendation_generated"])
        self.assertFalse(offline.current)
        self.assertEqual(offline.manifest.analysis_id, snapshot.manifest.analysis_id)
        self.assertEqual(offline.acquisitions, snapshot.acquisitions)
        self.assertEqual(offline.transactions, snapshot.transactions)
        with self.assertRaises(StaleData):
            assert_current(offline)

    def test_resolver_rejects_missing_and_ambiguous_names(self):
        snapshot = self._snapshot()
        with self.assertRaisesRegex(IdentityIncomplete, "did not resolve"):
            resolve_player_acquisition(snapshot, "Not A Player")
        duplicate = replace(
            snapshot.players[-1],
            player_id="duplicate",
            name="Target Quarterback",
        )
        ambiguous = replace(snapshot, players=(*snapshot.players, duplicate))
        with self.assertRaisesRegex(IdentityIncomplete, "ambiguous"):
            resolve_player_acquisition(ambiguous, "Target Quarterback")


class WaiverServiceAndCliTests(unittest.TestCase):
    def test_refresh_plan_is_sleeper_only_and_cache_aware(self):
        plan = waiver_refresh_plan("league-1", 1, player_cache_hit=True)
        self.assertEqual(len(plan.calls), 6)
        self.assertEqual(plan.cache_hits, 1)
        self.assertEqual(plan.fantasypros_calls, 0)
        self.assertEqual({item.provider for item in plan.calls}, {"Sleeper"})

    def test_refresh_service_saves_data_only_evidence(self):
        client = FakeSleeperClient()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "snapshot.json"
            cache = Path(directory) / "players.json"
            with (
                patch(
                    "roster_theory.waiver.service.find_league_config",
                    return_value={
                        "league_id": "league-1",
                        "user_roster_id": 1,
                    },
                ),
                patch(
                    "roster_theory.waiver.service.load_owner_config",
                    return_value={"sleeper_user_id": "u1"},
                ),
            ):
                result = refresh_waiver_snapshot(
                    "league_alpha",
                    player_cache_path=cache,
                    output_path=output,
                    client=client,
                )
            report = waiver_refresh_report(result)
            raw = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(report["call_plan"]["http_methods"], ["GET"])
        self.assertEqual(report["call_plan"]["fantasypros_calls"], 0)
        self.assertTrue(report["roster_snapshot_complete"])
        self.assertFalse(report["recommendation_generated"])
        self.assertFalse(report["sleeper_write_performed"])
        self.assertFalse(raw["sleeper_write_performed"])

    def test_service_accepts_any_configured_safe_league_key(self):
        client = FakeSleeperClient()
        with tempfile.TemporaryDirectory() as directory:
            with (
                patch(
                    "roster_theory.waiver.service.find_league_config",
                    return_value={"league_id": "league-1", "user_roster_id": 1},
                ),
                patch(
                    "roster_theory.waiver.service.load_owner_config",
                    return_value={"sleeper_user_id": "u1"},
                ),
            ):
                result = refresh_waiver_snapshot(
                    "league_beta",
                    player_cache_path=Path(directory) / "players.json",
                    output_path=Path(directory) / "snapshot.json",
                    client=client,
                )
        self.assertEqual(result.snapshot.league_key, "league_beta")
        self.assertFalse(result.snapshot.sleeper_write_performed)
        with tempfile.TemporaryDirectory() as directory:
            with (
                patch(
                    "roster_theory.waiver.service.find_league_config",
                    return_value={"league_id": "league-2", "user_roster_id": 1},
                ),
                patch(
                    "roster_theory.waiver.service.load_owner_config",
                    return_value={"sleeper_user_id": "u1"},
                ),
            ):
                other = refresh_waiver_snapshot(
                    "new_league",
                    player_cache_path=Path(directory) / "players-other.json",
                    output_path=Path(directory) / "snapshot-other.json",
                    client=client,
                )
        self.assertEqual(other.snapshot.league_key, "new_league")

    def test_nested_waiver_refresh_parser_is_data_only(self):
        for league_key in ("league_alpha", "league_beta"):
            with self.subTest(league_key=league_key):
                args = build_parser().parse_args(["waiver", "refresh", league_key])
                self.assertIs(args.func, command_waiver_refresh)
                self.assertIn("data/cache/waiver", args.player_cache)

    @patch(
        "roster_theory.cli.refresh_waiver_snapshot",
        side_effect=ValueError("bad snapshot"),
    )
    def test_refresh_command_exits_nonzero_on_required_failure(self, _mocked_refresh):
        args = argparse.Namespace(
            league="league_alpha",
            player_cache="players.json",
            output=None,
        )
        with self.assertRaisesRegex(SystemExit, "2"):
            command_waiver_refresh(args)


if __name__ == "__main__":
    unittest.main()
