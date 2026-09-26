"""Historical Waiver production cannot rank a partial league-points total."""
from datetime import datetime, timezone
from types import SimpleNamespace
import unittest

from roster_theory.core.models import Player
from roster_theory.providers.sleeper_historical_scoring import (
    assess_historical_rules, score_historical_stats,
)
from roster_theory.waiver_inputs import _performance_evidence
from tests.ma001_fixtures import PROFILES, rules


NOW = datetime(2026, 9, 20, tzinfo=timezone.utc)


def player(player_id, position):
    return Player(player_id, player_id, (position,))


class HistoricalWaiverScoringTests(unittest.TestCase):
    def test_missing_touchdown_cannot_rank_above_observed_zero(self):
        players = {pid: player(pid, "QB") for pid in ("partial", "complete", "absent")}
        client = SimpleNamespace(
            season_stats=lambda season: {
                "partial": {"pass_yd": 250, "gp": 2},
                "complete": {"pass_yd": 250, "pass_td": 0, "gp": 2},
            },
            weekly_stats=lambda season, week: {
                "partial": {"pass_yd": 125, "gp": 1, **({"pass_td": 0} if week == 2 else {})},
                "complete": {"pass_yd": 125, "pass_td": 0, "gp": 1},
            },
        )
        evidence, _ = _performance_evidence(
            client=client, league_id="fixture", season=2026, current_week=3, players=players,
            scoring={"pass_yd": 0.04, "pass_td": 4}, as_of=NOW)
        self.assertIsNone(evidence["partial"]["season_points"])
        self.assertIsNone(evidence["partial"]["season_position_rank"])
        self.assertIsNone(evidence["partial"]["recent_points_per_game"])
        self.assertIsNone(evidence["partial"]["recent_position_rank"])
        self.assertEqual(evidence["complete"]["season_points"], 10)
        self.assertEqual(evidence["complete"]["season_position_rank"], 1)
        self.assertEqual(evidence["complete"]["recent_points_per_game"], 5)
        self.assertTrue(any("pass_td" in warning for warning in evidence["partial"]["scoring_warnings"]))
        self.assertIsNone(evidence["absent"]["season_points"])
        self.assertTrue(any("no Sleeper season stat row" in warning
                            for warning in evidence["absent"]["scoring_warnings"]))

    def test_position_irrelevant_rules_do_not_erase_specialists(self):
        players = {"k": player("k", "K"), "dst": player("dst", "DST")}
        client = SimpleNamespace(
            season_stats=lambda season: {
                "k": {"fgm": 3, "gp": 2}, "dst": {"int": 2, "gp": 2}},
            weekly_stats=lambda season, week: {
                "k": {"fgm": 1, "gp": 1}, "dst": {"int": 1, "gp": 1}},
        )
        evidence, _ = _performance_evidence(
            client=client, league_id="fixture", season=2026, current_week=3, players=players,
            scoring={"fgm": 3, "int": 2}, as_of=NOW)
        self.assertEqual(evidence["k"]["season_points"], 9)
        self.assertEqual(evidence["dst"]["season_points"], 4)
        self.assertFalse(evidence["k"]["scoring_warnings"])
        self.assertFalse(evidence["dst"]["scoring_warnings"])

    def test_unknown_and_invalid_rules_are_disclosed_without_false_points(self):
        players = {"qb": player("qb", "QB")}
        client = SimpleNamespace(
            season_stats=lambda season: {"qb": {"pass_yd": 250, "pass_td": 0, "gp": 1}},
            weekly_stats=lambda season, week: {"qb": {"pass_yd": 125, "pass_td": 0, "gp": 1}},
        )
        for scoring, expected in (({"pass_yd": 0.04, "fum_rec": 2}, "fum_rec"),
                                  ({"pass_yd": 0.04, "bonus_pass_300": 3}, "bonus_pass_300")):
            with self.subTest(expected=expected):
                evidence, _ = _performance_evidence(
                    client=client, league_id="fixture", season=2026, current_week=2, players=players,
                    scoring=scoring, as_of=NOW)
                self.assertIsNone(evidence["qb"]["season_points"])
                self.assertTrue(any(expected in warning for warning in evidence["qb"]["scoring_warnings"]))

    def test_invalid_nonfinite_stat_and_separate_league_scoring(self):
        left = assess_historical_rules({"pass_yd": 0.04, "pass_td": 4},
            league_id="alpha", season=2026, week=None)
        right = assess_historical_rules({"pass_yd": 0.04, "pass_td": 6},
            league_id="beta", season=2026, week=None)
        self.assertNotEqual(left.rules_hash, right.rules_hash)
        for bad in (float("nan"), float("inf"), True, "invalid"):
            with self.subTest(bad=bad):
                result = score_historical_stats({"pass_yd": 250, "pass_td": bad}, left, position="QB")
                self.assertFalse(result.complete)
                self.assertTrue(any(issue.category == "invalid_statistic" for issue in result.issues))
        self.assertEqual(score_historical_stats({"pass_yd": 250, "pass_td": 2}, left,
            position="QB").require_points(), 18)
        self.assertEqual(score_historical_stats({"pass_yd": 250, "pass_td": 2}, right,
            position="QB").require_points(), 22)

    def test_reception_premium_requires_observed_receptions_only_for_named_position(self):
        rules = assess_historical_rules({"rec": 0.5, "bonus_rec_wr": 0.5},
            league_id="alpha", season=2026, week=2)
        self.assertEqual(score_historical_stats({"rec": 4}, rules, position="WR").require_points(), 4)
        self.assertEqual(score_historical_stats({"rec": 4}, rules, position="QB").require_points(), 2)
        self.assertFalse(score_historical_stats({}, rules, position="WR").complete)

    def test_reference_rules_remain_limited_independently(self):
        for profile in PROFILES:
            with self.subTest(profile=profile):
                assessment = assess_historical_rules(rules(profile)["scoring_settings"],
                    league_id=profile, season=2026, week=None)
                self.assertNotEqual(assessment.support, "SUPPORTED")
                self.assertIn("fum_rec", {issue.setting for issue in assessment.issues})


if __name__ == "__main__":
    unittest.main()
