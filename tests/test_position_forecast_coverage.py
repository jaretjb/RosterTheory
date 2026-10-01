"""Independent position-stat oracles and three-assistant forecast regressions."""
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from roster_theory.core.forecast_scoring import FORECAST_COVERAGE_VERSION
from roster_theory.core.provenance import canonical_json, stable_hash
from roster_theory.core.run_contract import restore_record
from roster_theory.core.scoring_contract import ScoredEvidence, ScoringScope, assess_scoring_rules
from roster_theory.inseason.evaluation import InSeasonWeek
from roster_theory.manual_import import load_fantasypros_projections
from roster_theory.providers.fantasypros import normalize_scored_projections
from roster_theory.providers.projection_scoring import WEEKLY_RULES, score_draft_projection_row, score_projection_row
from roster_theory.providers.sleeper_historical_scoring import assess_historical_rules, score_historical_stats
from roster_theory.trade.targets import discover_trade_targets
from roster_theory.trade.target_optimizer import optimize_target_packages, uniform_exact_budgets
from roster_theory.waiver.search import search_waiver_candidates
from tests.ma001_fixtures import AS_OF, PROFILES, policy, reference_fixture, rules
from tests.test_fantasypros_import import SyntheticDraftClient, draft_board
from tests.test_trade_targets import config as target_config, fixture as target_fixture
from tests.test_trade_target_optimizer import optimizer_config, permissive_options


# Same core line under both reference maps. Only QB interception scoring differs.
LINES = {
    "QB": {"pass_yd": 250, "pass_td": 2, "pass_int": 1, "rush_yd": 20, "rush_td": 0, "fum_lost": 1},
    "RB": {"rush_yd": 80, "rush_td": 1, "rec": 4, "rec_yd": 30, "rec_td": 0, "fum_lost": 1},
    "WR": {"rec": 6, "rec_yd": 90, "rec_td": 1, "fum_lost": 1},
    "TE": {"rec": 5, "rec_yd": 50, "rec_td": 1, "fum_lost": 0},
}


def assessment(scoring, *, horizon="WEEKLY", week=1):
    return assess_scoring_rules(scoring, scope=ScoringScope("synthetic", 2026, "test", horizon, week),
                               catalogue=WEEKLY_RULES, catalogue_version="position-test-v1")


def weekly(rows, scoring, week=1):
    payload = {"season": 2026, "week": week, "scoring": "HALF", "players": rows}
    return normalize_scored_projections(payload, scoring_settings=scoring, season=2026,
                                       week=week, captured_at=AS_OF, league_id="synthetic")


class PositionForecastCoverageTests(unittest.TestCase):
    def test_position_core_fields_are_complete_under_both_full_reference_maps(self):
        expected_by_profile = {"reference_a": {"QB": 16, "RB": 17, "WR": 16, "TE": 13.5},
                               "reference_b": {"QB": 17, "RB": 17, "WR": 16, "TE": 13.5}}
        for profile in PROFILES:
            scoring = rules(profile)["scoring_settings"]
            for position, stats in LINES.items():
                for horizon, week, scorer in (("WEEKLY", 1, score_projection_row),
                                              ("SEASON", None, score_draft_projection_row)):
                    with self.subTest(profile=profile, position=position, horizon=horizon):
                        result = scorer({"position_id": position, "stats": stats},
                                        assessment(scoring, horizon=horizon, week=week))
                        self.assertEqual(result.require_points(), expected_by_profile[profile][position])
                        self.assertTrue(result.optional_missing_settings)
                        self.assertEqual(result.coverage_policy, FORECAST_COVERAGE_VERSION)
                        self.assertFalse(result.structural_zero_settings)
                        self.assertEqual({o.statistic for o in result.source_evidence.observations}, set(stats))
                        self.assertEqual(restore_record(ScoredEvidence, json.loads(canonical_json(result))), result)

    def test_supplied_off_role_and_rare_stats_count_but_invalid_values_still_fail(self):
        scoring = {"rec": .5, "pass_td": 4, "rush_yd": .1, "rec_2pt": 2}
        base = {"position_id": "WR", "stats": {"rec": 5}}
        self.assertEqual(score_projection_row(base, assessment(scoring)).require_points(), 2.5)
        supplied = {"rec": 5, "pass_td": 1, "rush_yd": 30, "rec_2pt": .5}
        self.assertEqual(score_projection_row({**base, "stats": supplied}, assessment(scoring)).require_points(), 10.5)
        for value in (None, "bad", True, float("inf")):
            result = score_projection_row({**base, "stats": {"rec": 5, "pass_td": value}}, assessment(scoring))
            self.assertFalse(result.complete)
            self.assertIn("invalid_statistic", {x.category for x in result.issues})
        qb = score_projection_row({"position_id": "QB", "stats": {"rec": 1, "pass_td": 1}},
                                  assessment({"rec": .5, "pass_td": 4}))
        self.assertEqual(qb.require_points(), 4.5)

    def test_required_stats_unknown_rules_and_positions_stay_blocking(self):
        scoring = rules("reference_a")["scoring_settings"]
        for position, stats in LINES.items():
            for field in stats:
                result = score_projection_row({"position_id": position, "stats": {k:v for k,v in stats.items() if k != field}}, assessment(scoring))
                self.assertFalse(result.complete, (position, field))
                self.assertIn(field, {issue.setting for issue in result.issues})
        for position in ("", "UNKNOWN"):
            result = score_projection_row({"position_id": position, "stats": LINES["WR"]}, assessment(scoring))
            self.assertFalse(result.complete)
        result = score_projection_row({"position_id": "WR", "stats": LINES["WR"]},
                                      assessment({**scoring, "unsupported_new_rule": 2}))
        self.assertFalse(result.complete)

    def test_specialists_require_their_own_fields_without_offensive_forecasts(self):
        scoring = {"pass_td": 4, "rec": .5, "xpm": 1, "sack": 2}
        for position, stats, expected in (("K", {"xpm": 3}, 3), ("DST", {"sack": 2}, 4)):
            result = score_projection_row({"position_id": position, "stats": stats}, assessment(scoring))
            self.assertEqual(result.require_points(), expected)
            self.assertFalse(score_projection_row({"position_id": position, "stats": {}}, assessment(scoring)).complete)

    def test_projection_exception_does_not_rewrite_actual_historical_stats(self):
        historical = assess_historical_rules({"pass_td": 4, "rec": .5}, league_id="synthetic", season=2026, week=1)
        result = score_historical_stats({"rec": 4}, historical, position="WR")
        self.assertFalse(result.complete)
        self.assertFalse(result.optional_missing_settings)

    def test_draft_api_and_manual_import_keep_core_projections_with_full_rules(self):
        csvs = {
            "QB": "PLAYER,YDS,TDS,INT,YDS,TDS,FL\nForecast QB SEA,250,2,1,20,0,1\n",
            "RB": "PLAYER,YDS,TDS,REC,YDS,TDS,FL\nForecast RB SEA,80,1,4,30,0,1\n",
            "WR": "PLAYER,REC,YDS,TDS,FL\nForecast WR SEA,6,90,1,1\n",
            "TE": "PLAYER,REC,YDS,TDS,FL\nForecast TE SEA,5,50,1,0\n",
        }
        ranked = {pos: [{"player_id": pos, "player_name": "Forecast " + pos,
                         "player_position_id": pos, "rank_ecr": i}]
                  for i,pos in enumerate(LINES,1)}
        projected = {pos: [{"fpid": pos, "stats": stats}] for pos,stats in LINES.items()}
        for profile in PROFILES:
            scoring = rules(profile)["scoring_settings"]
            api = draft_board(SyntheticDraftClient(ranked, projected), scoring)
            self.assertEqual(api.metadata["players_with_projections"], 4)
            self.assertFalse(api.metadata["projection_issues"])
            with tempfile.TemporaryDirectory() as directory:
                paths = []
                for pos,text in csvs.items():
                    path = Path(directory) / (pos.lower() + ".csv")
                    path.write_text(text, encoding="utf-8")
                    paths.append(path)
                rows,metadata,issues = load_fantasypros_projections(paths, scoring, league_id=profile, season=2026)
            self.assertFalse(issues)
            self.assertEqual(metadata["complete_scoring_player_count"], 4)
            self.assertEqual({r["position"]:r["projected_points"] for r in rows.values()},
                             {r["position"]:r["projected_points"] for r in api.players})

    def test_trade_targets_and_package_search_share_forecast_admission(self):
        snapshot, original, selected, market_ecr, market = target_fixture()
        scoring = {"rec": .5, "pass_td": 4, "pass_2pt": 2, "rec_2pt": 2, "fum_rec_td": 6}
        snapshot = replace(snapshot, league=replace(snapshot.league, scoring=tuple(scoring.items())))
        players = {p.player_id:p for p in snapshot.players}
        projections = tuple(p for week in (1,2,3) for p in weekly([
            {"fpid": r.player_id, "position_id": players[r.player_id].positions[0],
             "stats": {"rec": r.league_points * 2}}
            for r in original if r.week==week], scoring, week).projections)
        targets = discover_trade_targets(snapshot, projections=projections, selected_board=selected,
                                         market_ecr_board=market_ecr, trade_market=market, config=target_config())
        self.assertTrue(targets.targets)
        self.assertFalse(targets.roster_exclusions)
        for estimated in (False, True):
            with self.subTest(estimated=estimated):
                rows = tuple(replace(p,coverage_status="estimated_missing_stats_v1:missing_statistic=fum_lost")
                             if estimated else p for p in projections)
                current = discover_trade_targets(snapshot, projections=rows, selected_board=selected,
                                                market_ecr_board=market_ecr, trade_market=market, config=target_config())
                self.assertTrue(current.targets)
                self.assertFalse(current.roster_exclusions)
                result = optimize_target_packages(snapshot, projections=rows, selected_board=selected,
                    market_ecr_board=market_ecr, trade_market=market, target_result=current,
                    config=optimizer_config(exact_budgets=uniform_exact_budgets(2)), options=permissive_options())
                self.assertTrue(result.evaluated_decisions)
                self.assertFalse(result.roster_exclusions)

    def test_waiver_search_accepts_core_position_forecasts_and_rejects_missing_core(self):
        for profile in PROFILES:
            fixture = reference_fixture(profile)
            snapshot = fixture.waiver()
            scoring = rules(profile)["scoring_settings"]
            rows = [{"fpid": p.player_id, "position_id": p.positions[0], "stats": LINES[p.positions[0]]}
                    for p in fixture.bundle.players if p.positions[0] in LINES]
            # Keep existing synthetic specialist projections; skill rows come through the real adapter.
            skill_ids = {row["fpid"] for row in rows}
            projections = tuple(p for w in (1,2,3) for p in weekly(rows,scoring,w).projections)
            projections += tuple(p for p in fixture.projections if p.player_id not in skill_ids)
            for missing in (False,True):
                supplied = tuple(replace(p,coverage_status="scoring_incomplete_v1:missing_statistic=rush_td")
                                 if missing and p.player_id=="fa_RB" else p for p in projections)
                result = search_waiver_candidates(snapshot, weeks=tuple(InSeasonWeek(w,False) for w in (1,2,3)),
                    projections=supplied, values=fixture.values(),
                    drop_legality={pid:True for pid in fixture.bundle.teams[0].player_ids},
                    news_fresh={p.player_id:True for p in fixture.bundle.players},
                    input_bundle_hash=stable_hash((profile,missing)), availability_source="synthetic forecast",
                    policy=policy(profile), enable_pruning=False, now=AS_OF, exact_candidate_budget=1)
                self.assertEqual("fa_RB" in result.eligible_candidate_ids, not missing)
                self.assertTrue(result.exact_evaluations)
                self.assertFalse(result.sleeper_write_performed)
