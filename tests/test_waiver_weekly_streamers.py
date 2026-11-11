import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from roster_theory.core.provenance import stable_hash
from roster_theory.providers.fantasypros import normalize_scored_projections
from roster_theory.waiver.evaluation import load_waiver_evaluation_inputs, save_waiver_evaluation_inputs
from roster_theory.waiver.policy import load_waiver_policy
from roster_theory.waiver.legality import DropLegality
from roster_theory.waiver.replay import replay_waiver_manifest
from roster_theory.waiver.search import search_waiver_candidates, waiver_readiness
from roster_theory.waiver.service import WaiverRefreshResult, format_waiver_search, search_waivers, waiver_refresh_plan
from roster_theory.waiver.service import _news_freshness
from roster_theory.waiver.snapshot import _capacity
from roster_theory.waiver.streamers import evaluate_weekly_streamers
from roster_theory.waiver.weekly import WeeklyPlanPolicy
from roster_theory.waiver_inputs import build_waiver_inputs
from tests.test_waiver_evaluation import CAPTURED, NOW, legality, weeks
from tests.test_waiver_search import POLICY_PATH, complete_projections, complete_search_snapshot, complete_values, news


def arguments():
    return dict(snapshot=complete_search_snapshot(), weeks=weeks(),
                projections=tuple(replace(p, league_points=18) if p.player_id == "fa_rb" else p
                                  for p in complete_projections()),
                values=tuple(replace(v, rest_of_season_position_rank=10) for v in complete_values()),
                drop_legality=legality(), news_fresh=news(), weekly_position_ranks={"fa_rb": 8})


def run_search(args, **kwargs):
    return search_waiver_candidates(**args, policy=load_waiver_policy(POLICY_PATH), now=NOW,
                                    input_bundle_hash="synthetic-weekly", availability_source="fixture", **kwargs)


class IndependentWeeklyStreamerTests(unittest.TestCase):
    def target(self, rows, pid="fa_rb"):
        return next(row for row in rows if row.add_player_id == pid)

    def test_ros_unranked_and_future_missing_starter_survives_search(self):
        args = arguments()
        args["values"] = tuple(v for v in args["values"] if v.player_id != "fa_rb")
        args["projections"] = tuple(p for p in args["projections"] if p.player_id != "fa_rb" or p.week == 1)
        result = run_search(args, exact_candidate_budget=1)
        row = self.target(result.weekly_streamers)
        self.assertEqual((row.projected_points, row.current_week_lineup_gain), (18, 8))
        self.assertEqual(row.drop_player_id, "bench")
        self.assertEqual(row.ros_decision_label, "NOT EVALUATED")
        self.assertIn("rest-of-season acquisition value is unavailable", row.retention_warnings)
        self.assertNotIn("fa_rb", {e.add_player_id for e in result.exact_evaluations})
        self.assertNotIn("fa_rb", {c.add_player_id for c in result.claim_plan})

    def test_missing_ros_ranks_and_future_projections_are_independent(self):
        for missing in ("ranks", "future"):
            with self.subTest(missing=missing):
                args = arguments()
                if missing == "ranks":
                    args["values"] = tuple(replace(v, rest_of_season_position_rank=None,
                                                  selected_rest_of_season_position_rank=None)
                                           if v.player_id == "fa_rb" else v for v in args["values"])
                else:
                    args["projections"] = tuple(p for p in args["projections"]
                                                if p.player_id != "fa_rb" or p.week == 1)
                self.assertEqual(self.target(run_search(args).weekly_streamers).current_week_lineup_gain, 8)

    def test_ros_policy_rejection_keeps_the_weekly_starter_visible(self):
        args = arguments()
        args["values"] = tuple(replace(v, selected_value=-100, market_value=-100)
                               if v.player_id == "fa_rb" else v for v in args["values"])
        result = run_search(args)
        row = self.target(result.weekly_streamers)
        self.assertIn(row.ros_decision_label, {"WATCH", "PASS"})
        self.assertEqual(row.current_week_lineup_gain, 8)
        self.assertNotIn("fa_rb", {c.add_player_id for c in result.claim_plan})

    def test_current_evidence_and_legality_failures_are_audited(self):
        for failure in ("projection", "partial", "rank", "news", "drop", "owned_projection"):
            with self.subTest(failure=failure):
                args = arguments()
                if failure == "projection":
                    args["projections"] = tuple(p for p in args["projections"] if (p.player_id, p.week) != ("fa_rb", 1))
                elif failure == "partial":
                    args["projections"] = tuple(replace(p, coverage_status="scoring_incomplete_v1:missing_statistic=rush_td")
                                                if (p.player_id, p.week) == ("fa_rb", 1) else p for p in args["projections"])
                elif failure == "rank":
                    args["weekly_position_ranks"] = {}
                elif failure == "news":
                    args["news_fresh"] = {}
                elif failure == "drop":
                    args["drop_legality"] = {pid: None for pid in legality()}
                else:
                    args["projections"] = tuple(p for p in args["projections"] if (p.player_id, p.week) != ("bench", 1))
                rows, omissions = evaluate_weekly_streamers(**args)
                self.assertFalse(rows)
                self.assertIn("fa_rb", {r.player_id for r in omissions})

    def test_inactive_and_bye_candidates_are_excluded(self):
        for status in ("Out", "IR", "PUP", "Suspended", "bye", "inactive"):
            with self.subTest(status=status):
                args = arguments()
                args["snapshot"] = replace(args["snapshot"], players=tuple(
                    replace(p, injury_status=None if status in {"bye", "inactive"} else status,
                            active=status != "inactive") if p.player_id == "fa_rb" else p
                    for p in args["snapshot"].players))
                if status == "bye":
                    args["weeks"] = (replace(args["weeks"][0], bye_teams=("HHH",)), *args["weeks"][1:])
                rows, omissions = evaluate_weekly_streamers(**args)
                self.assertFalse(rows)
                self.assertTrue(any(r.player_id == "fa_rb" and ("INACTIVE" in r.reason or "BYE" in r.reason)
                                    for r in omissions))

    def test_locked_and_owned_targets_are_excluded(self):
        for state in ("LOCKED", "owned"):
            with self.subTest(state=state):
                args = arguments()
                snapshot = args["snapshot"]
                args["snapshot"] = replace(snapshot, acquisitions=tuple(
                    replace(a, state="LOCKED" if state == "LOCKED" else "FREE_AGENT",
                            owner_roster_id="2" if state == "owned" else None)
                    if a.player_id == "fa_rb" else a for a in snapshot.acquisitions))
                self.assertFalse(evaluate_weekly_streamers(**args)[0])

    def test_available_player_scenario_stays_explicit(self):
        args = arguments()
        snapshot = args["snapshot"]
        args["snapshot"] = replace(snapshot, players=tuple(
            replace(p, injury_status="Out") if p.player_id == "fa_rb" else p for p in snapshot.players))
        row = self.target(evaluate_weekly_streamers(**args, availability=(
            {"player_id": "fa_rb", "status": "ACTIVE"},))[0])
        self.assertIn("the weekly lineup follows supplied availability assumptions", row.retention_warnings)

    def test_open_slot_preserves_all_rostered_players(self):
        args = arguments()
        args["snapshot"] = complete_search_snapshot(open_slot=True)
        args["drop_legality"] = {}
        row = self.target(evaluate_weekly_streamers(**args)[0])
        self.assertIsNone(row.drop_player_id)
        self.assertIsNone(row.drop_projected_points)
        self.assertEqual(row.current_week_lineup_gain, 8)

    def test_available_stat_estimates_stay_labeled(self):
        args = arguments()
        args["projections"] = tuple(replace(p, raw_stats=(("rush_yd", 90),),
                                            coverage_status="estimated_missing_stats_v1:missing_statistic=fum_lost")
                                    if (p.player_id, p.week) == ("fa_rb", 1) else p for p in args["projections"])
        result = run_search(args)
        report = format_waiver_search(SimpleNamespace(search=result, refresh=SimpleNamespace(snapshot=args["snapshot"])))
        self.assertIn("18.00 pts (estimate)", report)

    def test_league_scoring_is_kept_separate_for_weekly_mentions(self):
        stats = {"rush_yds": 100, "rush_tds": 0, "rec_rec": 5, "rec_yds": 40, "rec_tds": 0}
        for reception_points, expected in ((.5, 16.5), (1, 19)):
            with self.subTest(reception_points=reception_points):
                args = arguments()
                scoring = {"rush_yd": .1, "rush_td": 6, "rec": reception_points, "rec_yd": .1, "rec_td": 6}
                dataset = normalize_scored_projections(
                    {"season": 2026, "week": 1, "scoring": "HALF" if reception_points == .5 else "PPR",
                     "players": [{"fpid": "fa_rb", "position_id": "RB", "stats": stats}]},
                    scoring_settings=scoring, season=2026, week=1, league_id=str(reception_points))
                args["projections"] = tuple(p for p in args["projections"] if (p.player_id, p.week) != ("fa_rb", 1)) + dataset.projections
                row = self.target(evaluate_weekly_streamers(**args)[0])
                self.assertEqual(row.projected_points, expected)
                self.assertEqual(row.current_week_lineup_gain, expected - 10)

    def test_protected_drop_and_bench_opportunity_cost_stay_visible(self):
        args = arguments()
        args["snapshot"] = replace(args["snapshot"], players=tuple(
            replace(p, injury_status="Out") if p.player_id == "bench" else p for p in args["snapshot"].players))
        args["values"] = tuple(replace(v, rest_of_season_position_rank=1)
                               if v.player_id == "bench" else v for v in args["values"])
        args["drop_legality"] = {"bench": True}
        row = self.target(evaluate_weekly_streamers(**args)[0])
        self.assertIn("the drop is protected for retention", row.retention_warnings)
        self.assertEqual(row.drop_rest_of_season_rank, 1)
        self.assertEqual(row.drop_projected_points, 0)

    def test_backup_qb_needs_a_real_start_and_superflex_accepts_him(self):
        args = arguments()
        args["weekly_position_ranks"] = {"add": 10}
        args["projections"] = tuple(replace(p, league_points=14) if p.player_id == "add" else p for p in args["projections"])
        self.assertNotIn("add", {r.add_player_id for r in evaluate_weekly_streamers(**args)[0]})
        snapshot = args["snapshot"]
        league = replace(snapshot.league, roster_positions=("QB", "RB", "WR", "SUPER_FLEX", "BN"))
        args["snapshot"] = replace(snapshot, league=league,
                                   roster_capacity=tuple(_capacity(league, t, snapshot.players) for t in snapshot.teams))
        row = self.target(evaluate_weekly_streamers(**args)[0], "add")
        self.assertEqual(row.current_week_lineup_gain, 9)

    def test_multiple_positions_can_start_in_flex(self):
        args = arguments()
        snapshot = args["snapshot"]
        players = tuple(replace(p, positions=("WR", "TE")) if p.player_id == "fa_rb" else p for p in snapshot.players)
        league = replace(snapshot.league, roster_positions=("QB", "RB", "WR", "FLEX", "BN"))
        args["snapshot"] = replace(snapshot, league=league, players=players,
                                   roster_capacity=tuple(_capacity(league, t, players) for t in snapshot.teams))
        row = self.target(evaluate_weekly_streamers(**args)[0])
        self.assertEqual(row.current_week_lineup_gain, 13)

    def test_weekly_plan_report_includes_independent_streamers(self):
        args = arguments()
        args["values"] = tuple(v for v in args["values"] if v.player_id != "fa_rb")
        result = run_search(args, planning_policy=WeeklyPlanPolicy("league_alpha"))
        self.assertIsNotNone(result.weekly_plan)
        report = format_waiver_search(SimpleNamespace(search=result, refresh=SimpleNamespace(snapshot=args["snapshot"])))
        self.assertIn("WEEKLY SKILL STREAMERS", report)
        self.assertIn("Free Runner", report)
        self.assertIn("drop projects 5.00 points", report)
        self.assertIn("Combined claims require revalidation", report)

    def test_future_owned_gap_limits_the_plan_without_erasing_weekly_starter(self):
        args = arguments()
        args["projections"] = tuple(p for p in args["projections"] if (p.player_id, p.week) != ("qb", 2))
        result = run_search(args, planning_policy=WeeklyPlanPolicy("league_alpha"))
        self.assertIsNone(result.weekly_plan)
        self.assertIn("Week 2", result.weekly_plan_limitation)
        self.assertEqual(self.target(result.weekly_streamers).current_week_lineup_gain, 8)
        self.assertFalse(waiver_readiness(result)["inputs_complete"])

    def test_changed_roster_failure_is_audited_without_losing_streamers(self):
        args = arguments()
        args["projections"] = tuple(p for p in args["projections"] if (p.player_id, p.week) != ("bench", 2))
        result = run_search(args, planning_policy=WeeklyPlanPolicy("league_alpha"))
        self.assertIsNotNone(result.weekly_plan)
        self.assertTrue(any("droppable" in failure for failure in result.weekly_plan.evidence_failures))
        self.assertEqual(self.target(result.weekly_streamers).current_week_lineup_gain, 8)

    def test_empty_weekly_ranks_cannot_reenter_through_report_fallback(self):
        args = arguments()
        args["weekly_position_ranks"] = {}
        result = run_search(args)
        report = format_waiver_search(SimpleNamespace(search=result, refresh=SimpleNamespace(snapshot=args["snapshot"])))
        self.assertNotIn("WEEKLY SKILL STREAMERS", report)

    def test_global_news_feed_freshness_covers_weekly_only_players(self):
        inputs = SimpleNamespace(values=(), weekly_position_ranks=(("fa_rb", 8),),
                                 news_coverage={"scope": "FINITE_GLOBAL_FEED", "captured_at": CAPTURED.isoformat()})
        self.assertTrue(_news_freshness(inputs, NOW)["fa_rb"])

    def test_input_roundtrip_legacy_support_and_rank_validation(self):
        args = arguments()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "inputs.json"
            save_waiver_evaluation_inputs(path, league_key="league_alpha", captured_at=CAPTURED,
                availability_source="fixture", availability_by_player={},
                **{key: args[key] for key in ("weeks", "projections", "values", "drop_legality", "news_fresh", "weekly_position_ranks")})
            self.assertEqual(load_waiver_evaluation_inputs(path).weekly_position_ranks, (("fa_rb", 8),))
            payload = json.loads(path.read_text(encoding="utf-8"))
            for rank in (True, 0, -1, "8", 8.5):
                payload["weekly_position_ranks"] = {"fa_rb": rank}
                payload["input_hash"] = stable_hash({k: v for k, v in payload.items() if k != "input_hash"})
                path.write_text(json.dumps(payload), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "positive integers"):
                    load_waiver_evaluation_inputs(path)
            payload.pop("weekly_position_ranks")
            payload["schema_version"] = 10
            payload["input_hash"] = stable_hash({k: v for k, v in payload.items() if k != "input_hash"})
            path.write_text(json.dumps(payload), encoding="utf-8")
            self.assertEqual(load_waiver_evaluation_inputs(path).weekly_position_ranks, ())

    def test_input_preparation_retains_weekly_forecasts_outside_value_boards(self):
        args = arguments()
        snapshot = args["snapshot"]
        board = SimpleNamespace(
            refresh=SimpleNamespace(snapshot=SimpleNamespace(
                league=snapshot.league, players=snapshot.players, weeks=weeks()), schedule_path="fixture"),
            selected_final=SimpleNamespace(players=()), market=SimpleNamespace(players=()),
            weekly_rankings=(SimpleNamespace(player_id="fa_rb", position_rank=8),), ros_rankings=(),
            weekly_projections=args["projections"], current_experts=(), stage=SimpleNamespace(mode="ROS"),
            source_evidence=(), expert_pool_evidence={}, missing_rostered_player_ids=(),
            news_coverage={"scope": "FINITE_GLOBAL_FEED", "captured_at": CAPTURED.isoformat()},
        )
        waiver_wire = SimpleNamespace(evidence=SimpleNamespace(
            players=(), captured_at=CAPTURED, evidence_hash="synthetic", maximum_age_hours=24))
        legality_evidence = {pid: DropLegality(True, "synthetic") for pid in legality()}
        with (
            patch("roster_theory.waiver_inputs.resolve_league_policy_path", return_value=POLICY_PATH),
            patch("roster_theory.waiver_inputs.refresh_waiver_snapshot", return_value=SimpleNamespace(snapshot=snapshot)),
            patch("roster_theory.waiver_inputs.load_waiver_wire_config", return_value=SimpleNamespace(scoring="HALF")),
            patch("roster_theory.waiver_inputs.refresh_value_boards", return_value=board),
            patch("roster_theory.waiver_inputs.refresh_waiver_wire_evidence", return_value=waiver_wire),
            patch("roster_theory.waiver_inputs._performance_evidence", return_value=({}, ())),
            patch("roster_theory.waiver_inputs.SleeperClient"),
            patch("roster_theory.waiver_inputs.load_contingency_inputs", return_value=()),
            patch("roster_theory.waiver_inputs.revalidate_snapshot") as revalidate,
            patch("roster_theory.waiver_inputs.load_schedule"),
            patch("roster_theory.waiver_inputs.sleeper_drop_rules", return_value={"league_moves_locked": False}),
            patch("roster_theory.waiver_inputs.build_drop_legality_evidence", return_value=legality_evidence),
            patch("roster_theory.waiver_inputs.save_waiver_evaluation_inputs", side_effect=RuntimeError("captured")) as save,
        ):
            with self.assertRaisesRegex(RuntimeError, "captured"):
                build_waiver_inputs("league_alpha")
        saved = save.call_args.kwargs
        self.assertEqual(saved["weekly_position_ranks"], {"fa_rb": 8})
        self.assertIn("fa_rb", {p.player_id for p in saved["projections"]})
        self.assertEqual(saved["values"], ())
        self.assertIn("fa_rb", revalidate.call_args.kwargs["relevant_player_ids"])

    def test_normal_service_and_offline_replay_preserve_weekly_only_candidate(self):
        args = arguments()
        args["values"] = tuple(v for v in args["values"] if v.player_id != "fa_rb")
        args["projections"] = tuple(p for p in args["projections"] if p.player_id != "fa_rb" or p.week == 1)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "inputs.json"
            save_waiver_evaluation_inputs(path, league_key="league_alpha", captured_at=CAPTURED,
                availability_source="fixture", availability_by_player={},
                **{key: args[key] for key in ("weeks", "projections", "values", "drop_legality", "news_fresh", "weekly_position_ranks")})
            refresh = WaiverRefreshResult(args["snapshot"], waiver_refresh_plan("league-1", 1, player_cache_hit=True), root / "snapshot.json")
            with patch("roster_theory.waiver.service.refresh_waiver_snapshot", return_value=refresh), \
                    patch("roster_theory.waiver.service.revalidate_snapshot", return_value={"verified_at": NOW.isoformat(), "status": "UNCHANGED"}):
                result = search_waivers("league_alpha", inputs_path=path, output_path=root / "search.json",
                                        policy_path=POLICY_PATH, now=NOW, clock=lambda: NOW)
            self.assertIn("fa_rb", {r.add_player_id for r in result.search.weekly_streamers})
            replay = replay_waiver_manifest(root / "search.manifest.json")
            self.assertEqual(replay["result"]["evidence_hash"], result.search.evidence_hash)
