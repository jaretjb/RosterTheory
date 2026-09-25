import unittest
from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace

from roster_theory.waiver.legality import assess_drop_legality, sleeper_drop_rules
from roster_theory.waiver_inputs import build_drop_legality_evidence
from tests.test_waiver_evaluation import waiver_snapshot


class DropLegalityTests(unittest.TestCase):
    def assess(self, **changes):
        inputs = dict(
            nfl_team="SEA", starter=True, week=3,
            games=({"week": 3, "away_team": "SEA", "home_team": "SF",
                    "kickoff_at": "2026-09-25T00:15:00+00:00"},),
            bye_week=None, now=datetime(2026, 9, 25, 0, 15, tzinfo=timezone.utc),
            league_moves_locked=False,
        )
        return assess_drop_legality(**(inputs | changes))

    def test_zero_point_starter_is_locked_at_kickoff(self):
        self.assertIs(self.assess().legal, False)

    def test_live_input_adapter_uses_rules_and_schedule_not_scored_points(self):
        snapshot = waiver_snapshot()
        snapshot = replace(snapshot, league=replace(snapshot.league,
                           platform_settings=(("disable_adds", 0), ("bench_lock", 1))),
                           players=tuple(replace(row, nfl_team="SEA") for row in snapshot.players))
        schedule = SimpleNamespace(source="nflverse nflverse-data schedules release", bye_weeks=(),
                                   games=({"week": snapshot.manifest.current_week, "away_team": "SEA",
                                           "home_team": "SF", "gameday": "2026-09-24", "gametime": "20:15"},))
        matchups = ({"roster_id": snapshot.user_roster_id, "starters": ["qb"],
                     "players_points": {"qb": 0.0, "bench": 0.0}},)
        now = datetime(2026, 9, 25, 0, 15, tzinfo=timezone.utc)
        result = build_drop_legality_evidence(snapshot, schedule, matchups, {"qb", "bench", "missing"}, now=now)
        self.assertIs(result["qb"].legal, False)
        self.assertIs(result["bench"].legal, False)
        self.assertIsNone(result["missing"].legal)
        unlocked = replace(snapshot, league=replace(snapshot.league,
                           platform_settings=(("disable_adds", 0), ("bench_lock", 0))))
        result = build_drop_legality_evidence(unlocked, schedule, matchups, {"qb", "bench"}, now=now)
        self.assertIs(result["qb"].legal, False)
        self.assertIs(result["bench"].legal, True)

    def test_before_kickoff_is_legal(self):
        self.assertIs(self.assess(now=datetime(2026, 9, 24, tzinfo=timezone.utc)).legal, True)

    def test_unknown_game_and_ambiguous_games_are_not_legal(self):
        self.assertIsNone(self.assess(games=()).legal)
        self.assertIsNone(self.assess(starter=None).legal)
        self.assertIsNone(self.assess(games=({"week": 3, "away_team": "SEA"},)).legal)

    def test_bench_requires_verified_rule_after_kickoff(self):
        self.assertIsNone(self.assess(starter=False).legal)
        self.assertIs(self.assess(starter=False, prevent_started_bench_drop=True).legal, False)
        self.assertIs(self.assess(starter=False, prevent_started_bench_drop=False).legal, True)

    def test_audited_bye_has_no_game_lock(self):
        self.assertIs(self.assess(games=(), bye_week=3).legal, True)

    def test_league_lock_overrides_bye_and_pregame_and_missing_rule_is_unknown(self):
        self.assertIs(self.assess(league_moves_locked=True, games=(), bye_week=3).legal, False)
        self.assertIsNone(self.assess(league_moves_locked=None).legal)
        self.assertEqual(sleeper_drop_rules({"disable_adds": 0, "bench_lock": 1}),
                         {"league_moves_locked": False, "prevent_started_bench_drop": True})
        self.assertIsNone(sleeper_drop_rules({"disable_adds": "0"})["league_moves_locked"])

    def test_postponed_and_conflicting_schedule_are_unknown(self):
        game = {"week": 3, "away_team": "SEA", "home_team": "SF",
                "kickoff_at": "2026-09-25T00:15:00+00:00"}
        self.assertIsNone(self.assess(games=(game | {"status": "POSTPONED"},)).legal)
        self.assertIsNone(self.assess(games=(game, game)).legal)

    def test_winter_and_transition_times(self):
        game = {"week": 3, "away_team": "SEA", "home_team": "SF",
                "gameday": "2026-11-08", "gametime": "13:00", "gametime_zone": "US/Eastern"}
        self.assertIs(self.assess(games=(game,), now=datetime(2026, 11, 8, 17, tzinfo=timezone.utc)).legal, True)
        self.assertIs(self.assess(games=(game,), now=datetime(2026, 11, 8, 18, tzinfo=timezone.utc)).legal, False)
        self.assertIsNone(self.assess(games=(game | {"gameday": "2026-11-01", "gametime": "01:30"},)).legal)

    def test_eastern_kickoff_is_portable_without_system_timezone_database(self):
        game = {"week": 3, "away_team": "SEA", "home_team": "SF",
                "gameday": "2026-09-24", "gametime": "20:15", "gametime_zone": "US/Eastern"}
        self.assertIs(self.assess(games=(game,)).legal, False)
        self.assertIs(self.assess(games=(game | {"gametime_zone": ""},)).legal, None)
