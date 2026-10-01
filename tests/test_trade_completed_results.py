from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from roster_theory.core.errors import SourceUnavailable
from roster_theory.core.provenance import stable_hash
from roster_theory.providers.cache import atomic_write_json
from roster_theory.providers.nflverse import NflverseScheduleEvidence, save_schedule_evidence
from roster_theory.trade.completed_results import collect_completed_results, SOURCE
from roster_theory.trade.performance import PregameExpectation, build_performance_evidence
from roster_theory.trade.performance_history import update_performance_history
from tests.test_trade_performance_history import policy
from tests.test_trade_targets import fixture


class CompletedResultsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.now = datetime.now(timezone.utc)
        snapshot, projections, selected, _, _ = fixture()
        self.snapshot = replace(snapshot, manifest=replace(snapshot.manifest, current_week=3))
        self.refresh = SimpleNamespace(refresh=SimpleNamespace(snapshot=self.snapshot),
            weekly_projections=projections, selected_final=selected)
        self.scoring = stable_hash(snapshot.league.scoring)
        self.captures = []
        games = ["season,game_type,week,gameday,gametime,home_team,away_team,home_score,away_score"]
        for week, days in ((1, 8), (2, 3)):
            date = (self.now - timedelta(days=days)).strftime("%Y-%m-%d")
            games.append(f"{snapshot.league.season},REG,{week},{date},13:00,BUF,NYJ,20,10")
            self.captures.append(PregameExpectation(snapshot.league_key, snapshot.league.season,
                "o_buy", week, "TE", self.now - timedelta(days=days+1), 12.0, None,
                self.scoring, "test-prospective", "BUF"))
            payload = {"matchups": [{"players": ["o_buy"], "players_points": {"o_buy": 1.25}}],
                       "participation": {"o_buy": {"gp": 1, "pts_half_ppr": 99}}}
            self.write_week(week, payload)
        content = "\n".join(games)
        self.schedule = NflverseScheduleEvidence("roster-theory.nflverse-schedule-evidence/v1",
            "synthetic-final", "https://example.invalid/schedule", "fixture", "fixture", "games.csv",
            (self.now - timedelta(hours=1)).isoformat(), hashlib.sha256(content.encode()).hexdigest(),
            "SYNTHETIC_FIXTURE", "Synthetic", content)
        save_schedule_evidence(self.schedule, self.root / "nflverse-final-scores.json")
        self.client = Mock()
        self.client.league_matchups.side_effect = AssertionError("Unexpected provider call")
        self.client.weekly_stats.side_effect = AssertionError("Unexpected provider call")

    def write_week(self, week, payload, captured=None, league=None):
        scope = (league or self.snapshot.league.league_id, self.snapshot.league.season, week, self.scoring)
        path = self.root / f"{stable_hash(scope)[:24]}.json"
        atomic_write_json(path, {"scope": scope, "payload": payload,
            "captured_at": (captured or self.now).isoformat(), "payload_hash": stable_hash(payload)})

    def collect(self, captures=None, existing=(), **kwargs):
        return collect_completed_results(self.snapshot, captures or self.captures, existing,
            window_weeks=3, client=self.client, cache_root=self.root, archive_root=self.root / "archive",
            now=self.now, **kwargs)

    def test_live_history_uses_league_points_and_is_idempotent(self):
        path = self.root / "history.json"
        atomic_write_json(path, {"schema_version": 1, "league_key": self.snapshot.league_key,
            "season": self.snapshot.league.season, "scoring_fingerprint": self.scoring,
            "pregame_expectations": [asdict(x) for x in self.captures], "completed_outcomes": []})
        result = update_performance_history(self.refresh, policy=policy(), path=path,
            collect_outcomes=True, outcome_client=self.client, outcome_cache_root=self.root,
            archive_root=self.root / "archive")
        self.assertEqual(result.outcome_refresh["added_outcomes"], 2)
        context = next(x for x in result.evidence.contexts if x.player_id == "o_buy")
        self.assertTrue(context.compatible)
        self.assertEqual(context.signal, "UNDERPERFORMING")
        self.assertEqual(result.evidence.residuals[0].actual_points, 1.25)
        self.assertIsNone(result.evidence.residuals[0].actual_position_rank)
        again = update_performance_history(self.refresh, policy=policy(), path=path,
            collect_outcomes=True, outcome_client=self.client, outcome_cache_root=self.root,
            archive_root=self.root / "archive")
        self.assertEqual(again.total_outcomes, 2)
        self.assertEqual(again.outcome_refresh["added_outcomes"], 0)

    def test_postgame_capture_does_not_become_a_pregame_forecast(self):
        late = [replace(self.captures[0], captured_at=self.now), self.captures[1]]
        rows, _ = self.collect(late)
        evidence = build_performance_evidence(self.snapshot.league_key, self.snapshot.league.season,
            2, self.now, expectations=late, outcomes=rows, policy=policy())
        self.assertFalse(evidence.contexts[0].compatible)
        self.assertEqual(evidence.contexts[0].sample_size, 1)
        self.assertIn("W1:POSTGAME_OR_FUTURE_CAPTURE", evidence.contexts[0].exclusions)

    def test_missing_points_participation_and_nonfinal_remain_excluded(self):
        self.write_week(1, {"matchups": [{"players": ["o_buy"], "players_points": {}}],
                            "participation": {"o_buy": {"gp": 1}}})
        self.write_week(2, {"matchups": [{"players": ["o_buy"], "players_points": {"o_buy": 0}}],
                            "participation": {"o_buy": {"gp": 0}}})
        rows, report = self.collect()
        self.assertEqual(rows, ())
        self.assertEqual(set(report["exclusion_counts"]),
            {"PARTICIPATION_UNVERIFIED", "LEAGUE_PLAYER_POINTS_UNAVAILABLE_OR_AMBIGUOUS"})
        content = self.schedule.content.replace(",20,10", ",,")
        save_schedule_evidence(replace(self.schedule, content=content,
            response_hash=hashlib.sha256(content.encode()).hexdigest()), self.root / "nflverse-final-scores.json")
        rows, report = self.collect()
        self.assertEqual(rows, ())
        self.assertEqual(report["exclusion_counts"], {"GAME_NOT_VERIFIED_COMPLETE": 2})

    def test_original_snapshot_recovers_legacy_team_not_current_team(self):
        captures = [replace(x, nfl_team=None) for x in self.captures]
        for i, row in enumerate(captures):
            atomic_write_json(self.root / "archive" / str(i) / "snapshot.json", {
                "league_key": self.snapshot.league_key, "league": asdict(self.snapshot.league),
                "captured_at": row.captured_at.isoformat(),
                "players": [{"player_id": row.player_id, "nfl_team": "BUF"}]})
        rows, _ = self.collect(captures)
        self.assertEqual(len(rows), 2)
        foreign = self.root / "archive" / "0" / "snapshot.json"
        value = json.loads(foreign.read_text()); value["league_key"] = "foreign"
        atomic_write_json(foreign, value)
        rows, report = self.collect(captures)
        self.assertEqual(len(rows), 1)
        self.assertEqual(report["exclusion_counts"], {"HISTORICAL_TEAM_UNAVAILABLE_OR_AMBIGUOUS": 1})

    def test_manual_partial_outcomes_and_offline_snapshots_are_preserved(self):
        rows, _ = self.collect()
        manual = [replace(x, source="verified-manual", availability="PARTIAL") for x in rows]
        collected, report = self.collect(existing=manual)
        self.assertEqual(collected, ())
        self.assertEqual(report["status"], "PRESERVED_IMPORTS")
        self.snapshot = replace(self.snapshot, current=False)
        self.assertEqual(self.collect()[0], ())

    def test_provider_team_aliases_resolve_same_game(self):
        captures = [replace(x, nfl_team="LAR") for x in self.captures]
        content = self.schedule.content.replace(",BUF,", ",LA,")
        save_schedule_evidence(replace(self.schedule, content=content,
            response_hash=hashlib.sha256(content.encode()).hexdigest()), self.root / "nflverse-final-scores.json")
        rows, report = self.collect(captures)
        self.assertEqual(len(rows), 2)
        self.assertEqual(report["exclusions"], [])

    def test_provider_failure_is_visible_and_optional(self):
        with patch('roster_theory.trade.completed_results.load_schedule_evidence',
                   side_effect=SourceUnavailable("fixture source unavailable")):
            rows, report = self.collect()
        self.assertEqual(rows, ())
        self.assertEqual(report["status"], "UNAVAILABLE")
        self.assertIn("fixture source unavailable", report["warnings"][0])

    def test_corrected_results_append_without_cross_league_cache_reuse(self):
        rows, _ = self.collect()
        self.write_week(2, {"matchups": [{"players": ["o_buy"], "players_points": {"o_buy": 2.5}}],
                            "participation": {"o_buy": {"gp": 1}}})
        changed, _ = self.collect(existing=rows)
        self.assertEqual(len(changed), 1)
        self.assertEqual(changed[0].actual_points, 2.5)
        self.assertEqual(changed[0].source, SOURCE)
        self.snapshot = replace(self.snapshot, league=replace(self.snapshot.league, league_id="other"))
        self.client.league_matchups.side_effect = None
        self.client.league_matchups.return_value = [{"players": ["o_buy"], "players_points": {"o_buy": 3.0}}]
        self.client.weekly_stats.side_effect = None
        self.client.weekly_stats.return_value = {"o_buy": {"gp": 1}}
        other, _ = self.collect()
        self.assertEqual([x.actual_points for x in other], [3.0, 3.0])
        self.assertTrue(all(call.args[0] == "other" for call in self.client.league_matchups.call_args_list))


if __name__ == '__main__':
    unittest.main()
