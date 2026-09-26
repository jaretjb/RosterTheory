import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from roster_theory.core.errors import CoverageIncomplete, UnsupportedScoring
from roster_theory.core.scoring import score_stats
from roster_theory.providers.formats import ranking_format, validate_provider_scope
from roster_theory.providers.cache import DailyRequestBudget
from roster_theory.trade.board_service import (
    _input_calls,
    _fetch_value_inputs,
    resolve_draft_anchor,
    refresh_value_boards,
)
from roster_theory.trade.horizons import load_draft_anchor
from roster_theory.core.lineup import optimize_lineup
from roster_theory.core.models import Player
from roster_theory.waiver_inputs import build_waiver_inputs
from roster_theory.providers.fantasypros import FantasyProsAdapter


class InseasonFormatTests(unittest.TestCase):
    def test_qb_superflex_and_reception_flex_keep_actual_projected_points(self):
        players = (
            Player("q1", "QB1", ("QB",)),
            Player("q2", "QB2", ("QB",)),
            Player("te", "TE", ("TE",)),
            Player("wr", "WR", ("WR",)),
        )
        scores = {
            "q1": score_stats({"pass_tds": 4}, {"pass_td": 6}, position="QB").points,
            "q2": score_stats({"pass_tds": 3}, {"pass_td": 6}, position="QB").points,
            "te": score_stats({"rec_rec": 5}, {"rec": 1, "bonus_rec_te": 1}, position="TE").points,
            "wr": score_stats({"rec_rec": 8}, {"rec": 1, "bonus_rec_te": 1}, position="WR").points,
        }
        for slots in (("QB", "SUPER_FLEX", "REC_FLEX"), ("QB", "QB", "FLEX")):
            lineup = optimize_lineup(players, slots, scores)
            self.assertEqual(lineup.score, 52)
            capability = ranking_format({"rec": 1}, slots)
            self.assertFalse(capability.league_exact)
            self.assertIn("not league-exact", " ".join(capability.warnings))

    def test_missing_premium_stat_is_not_a_complete_projection(self):
        class Provider:
            def projections(self, season, **params):
                return {
                    "season": season,
                    "scoring": params["scoring"],
                    "week": params["week"],
                    "players": [{"fpid": "one", "position_id": "TE", "stats": {"rec_yds": 40}}],
                }

        result = FantasyProsAdapter(Provider()).weekly_projections(
            2027, 1, "TE", {"rec": 1, "rec_yd": 0.1, "bonus_rec_te": 1}
        )
        self.assertEqual(result.projections[0].coverage_status,
                         "scoring_incomplete_v1:missing_statistic=bonus_rec_te;missing_statistic=rec")

    def test_default_anchor_requires_season_and_does_not_use_previous_year(self):
        with self.assertRaisesRegex(ValueError, "Season is required"):
            resolve_draft_anchor("new_name", "id")
        with patch("roster_theory.trade.board_service.Path.exists", return_value=False):
            with self.assertRaisesRegex(CoverageIncomplete, "league_boards_2027"):
                resolve_draft_anchor("new_name", "id", season=2027)

    def test_actual_retrieval_uses_format_and_projection_identity_is_not_rank_order(self):
        class Provider:
            reverse = False

            def consensus_rankings(self, season, **params):
                ids = ("2", "1") if self.reverse else ("1", "2")
                return {
                    "year": season,
                    "week": params["week"],
                    "scoring": params["scoring"],
                    "ranking_type_name": "Weekly",
                    "players": [
                        {
                            "player_id": pid,
                            "player_name": pid,
                            "player_position_id": "TE",
                            "rank_ecr": i,
                            "pos_rank": f"TE{i}",
                        }
                        for i, pid in enumerate(ids, 1)
                    ],
                }

            def projections(self, season, **params):
                return {
                    "season": season,
                    "week": params["week"],
                    "scoring": params["scoring"],
                    "players": [
                        {
                            "fpid": "1",
                            "name": "1",
                            "position_id": "TE",
                            "stats": {"rec_rec": 4, "rec_yds": 20},
                        },
                        {
                            "fpid": "2",
                            "name": "2",
                            "position_id": "TE",
                            "stats": {"rec_rec": 2, "rec_yds": 80},
                        },
                    ],
                }

            def news(self, **params):
                return {"items": []}

        for season, rec, expected in ((2026, 0, "STD"), (2026, 0.5, "HALF"), (2027, 1, "PPR")):
            result_points = []
            for reverse in (False, True):
                provider = Provider()
                provider.reverse = reverse
                snapshot = SimpleNamespace(
                    league=SimpleNamespace(
                        league_id="synthetic", season=season,
                        scoring=(("rec", rec), ("rec_yd", 0.1), ("bonus_rec_te", 1))
                    ),
                    manifest=SimpleNamespace(current_week=1),
                    weeks=(SimpleNamespace(week=1),),
                )
                with (
                    tempfile.TemporaryDirectory() as directory,
                    patch("roster_theory.trade.board_service.time.sleep"),
                ):
                    result = _fetch_value_inputs(
                        SimpleNamespace(snapshot=snapshot),
                        client=provider,
                        cache_dir=Path(directory),
                        budget_path=Path(directory) / "budget.json",
                        ranking_positions=("TE",),
                    )
                self.assertEqual(result.weekly_rankings[0].scoring, expected)
                self.assertEqual(result.projection_sets[0].stamp.season, season)
                result_points.append(
                    {
                        row.player_id: row.league_points
                        for row in result.projection_sets[0].projections
                    }
                )
            self.assertEqual(result_points[0], result_points[1])
            self.assertEqual(result_points[0], {"1": 6 + 4 * rec, "2": 10 + 2 * rec})

    def test_trade_rescores_mismatched_projection_label_from_raw_stats(self):
        class Provider:
            def consensus_rankings(self, season, **params):
                return {
                    "year": season, "week": params["week"],
                    "scoring": params["scoring"], "ranking_type_name": "Weekly",
                    "players": [],
                }

            def projections(self, season, **params):
                self.requested_scoring = params["scoring"]
                return {
                    "season": season, "week": params["week"], "scoring": "STD",
                    "players": [
                        {"fpid": "complete", "position_id": "TE",
                         "stats": {"rec_rec": 4, "rec_yds": 20, "points": 2}},
                        {"fpid": "no_receptions", "position_id": "TE",
                         "stats": {"rec_yds": 40, "points": 4}},
                        {"fpid": "points_only", "position_id": "TE",
                         "stats": {"points": 10}},
                    ],
                }

            def news(self, **params):
                return {"items": []}

        provider = Provider()
        snapshot = SimpleNamespace(
            league=SimpleNamespace(league_id="synthetic", season=2027,
                                   scoring=(("rec", 0.5), ("rec_yd", 0.1))),
            manifest=SimpleNamespace(current_week=1),
            weeks=(SimpleNamespace(week=1),),
        )
        with tempfile.TemporaryDirectory() as directory:
            result = _fetch_value_inputs(
                SimpleNamespace(snapshot=snapshot), client=provider,
                cache_dir=Path(directory), budget_path=Path(directory) / "budget.json",
                ranking_positions=("TE",),
            )
        rows = {row.player_id: row for row in result.projection_sets[0].projections}
        self.assertEqual(provider.requested_scoring, "HALF")
        self.assertEqual(result.projection_sets[0].scoring, "STD")
        self.assertEqual(result.projection_sets[0].stamp.scoring_label, "STD")
        self.assertEqual(rows["complete"].league_points, 4.0)
        self.assertEqual(rows["complete"].coverage_status, "complete")
        self.assertEqual(rows["no_receptions"].coverage_status,
                         "scoring_incomplete_v1:missing_statistic=rec")
        self.assertEqual(rows["points_only"].coverage_status,
                         "scoring_incomplete_v1:missing_statistic=rec;missing_statistic=rec_yd")
        source = next(row for row in result.source_evidence if row["name"] == "projections_1")
        self.assertEqual(source["parameters"]["scoring"], "HALF")
        self.assertEqual(source["declared_scoring"], "STD")
        self.assertEqual(source["projection_points_method"], "RAW_STATS_LEAGUE_SCORED")
        self.assertEqual(source["projection_scoring_contract"], "fantasypros-weekly-v1")

    def test_trade_rejects_unknown_or_wrong_season_projection_scope(self):
        class Provider:
            def __init__(self, declared_scoring, returned_season):
                self.declared_scoring = declared_scoring
                self.returned_season = returned_season

            def consensus_rankings(self, season, **params):
                return {
                    "year": season, "week": params["week"],
                    "scoring": params["scoring"], "ranking_type_name": "Weekly",
                    "players": [],
                }

            def projections(self, season, **params):
                return {
                    "season": self.returned_season, "week": params["week"],
                    "scoring": self.declared_scoring, "players": [],
                }

            def news(self, **params):
                return {"items": []}

        snapshot = SimpleNamespace(
            league=SimpleNamespace(league_id="synthetic", season=2027, scoring=(("rec", 0.5),)),
            manifest=SimpleNamespace(current_week=1),
            weeks=(SimpleNamespace(week=1),),
        )
        for declared, returned_season in (("UNKNOWN", 2027), ("STD", 2026)):
            with self.subTest(declared=declared, returned_season=returned_season):
                with tempfile.TemporaryDirectory() as directory:
                    with self.assertRaises(CoverageIncomplete):
                        _fetch_value_inputs(
                            SimpleNamespace(snapshot=snapshot),
                            client=Provider(declared, returned_season),
                            cache_dir=Path(directory),
                            budget_path=Path(directory) / "budget.json",
                            ranking_positions=("TE",),
                        )

    def test_new_named_league_uses_snapshot_season_for_default_cache(self):
        snapshot = SimpleNamespace(league=SimpleNamespace(season=2027, scoring=(("rec", 1),)))
        with (
            patch(
                "roster_theory.trade.board_service.refresh_trade_snapshot",
                return_value=SimpleNamespace(snapshot=snapshot),
            ),
            patch(
                "roster_theory.trade.board_service._fetch_value_inputs",
                side_effect=RuntimeError("captured"),
            ) as fetch,
        ):
            with self.assertRaisesRegex(RuntimeError, "captured"):
                refresh_value_boards("newly_named_league")
            self.assertEqual(
                fetch.call_args.kwargs["cache_dir"], Path("data/cache/trade/fantasypros/2027")
            )

    def test_mismatched_waiver_config_stops_before_paid_board_refresh(self):
        snapshot = SimpleNamespace(league=SimpleNamespace(scoring=(("rec", 1),)))
        with (
            patch("roster_theory.waiver_inputs.resolve_league_policy_path", return_value="fixture"),
            patch("roster_theory.waiver_inputs.load_waiver_policy"),
            patch(
                "roster_theory.waiver_inputs.refresh_waiver_snapshot",
                return_value=SimpleNamespace(snapshot=snapshot),
            ),
            patch(
                "roster_theory.waiver_inputs.load_waiver_wire_config",
                return_value=SimpleNamespace(scoring="HALF"),
            ),
            patch("roster_theory.waiver_inputs.refresh_value_boards") as board,
        ):
            with self.assertRaisesRegex(ValueError, "does not match"):
                build_waiver_inputs("newly_named_league")
            board.assert_not_called()

    def test_anchor_reads_each_declared_format_and_rejects_wrong_label(self):
        for scoring, scope in (
            ("STD", "skills_standard"),
            ("HALF", "skills_half_ppr"),
            ("PPR", "skills_ppr"),
        ):
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "anchor.csv"
                path.write_text(
                    "scope,scoring,sleeper_id,position,weighted_position_rank,ecr\n"
                    f"{scope},{scoring},one,RB,1,1\n"
                )
                selected, _ = load_draft_anchor(
                    path, updated_at="2027-09-01T00:00:00+00:00", scope=scope, scoring=scoring
                )
                self.assertEqual(selected[0].scoring, scoring)
                with self.assertRaises(CoverageIncomplete):
                    load_draft_anchor(
                        path,
                        updated_at="2027-09-01T00:00:00+00:00",
                        scope=scope,
                        scoring="PPR" if scoring != "PPR" else "HALF",
                    )

    def test_reception_format_mapping_and_custom_visibility(self):
        for reception, expected in ((0, "STD"), (0.5, "HALF"), (1, "PPR")):
            self.assertEqual(ranking_format({"rec": reception}).scoring, expected)
        for reception in (0.75, -1, float("nan"), float("inf"), None, "invalid"):
            with self.assertRaises(UnsupportedScoring):
                ranking_format({"rec": reception})
        for settings in ({"rec": 1, "pass_td": 6}, {"rec": 1, "bonus_rec_te": 1}):
            result = ranking_format(settings)
            self.assertFalse(result.league_exact)
            self.assertTrue(result.warnings)

    def test_request_and_cache_scope_change_with_format_and_season(self):
        now = datetime(2026, 9, 25, tzinfo=timezone.utc)
        paths_by_scope = []
        with tempfile.TemporaryDirectory() as directory:
            for season, scoring in ((2026, "STD"), (2026, "HALF"), (2026, "PPR"), (2027, "PPR")):
                plan, paths, _ = _input_calls(
                    season,
                    3,
                    (3,),
                    Path(directory),
                    now,
                    DailyRequestBudget(),
                    ("RB",),
                    scoring=scoring,
                )
                ranking = next(row for row in plan.calls if row.name == "rankings_rb")
                self.assertEqual(dict(ranking.parameters)["scoring"], scoring)
                self.assertIn(str(season), ranking.endpoint)
                paths_by_scope.append(paths["rankings_rb"])
        self.assertEqual(len(set(paths_by_scope)), 4)

    def test_provider_mismatches_cannot_be_relabelled(self):
        validate_provider_scope({"year": 2027, "scoring": "PPR"}, season=2027, scoring="PPR")
        for payload in ({"year": 2026, "scoring": "PPR"}, {"year": 2027, "scoring": "HALF"}, {}):
            with self.assertRaises(CoverageIncomplete):
                validate_provider_scope(payload, season=2027, scoring="PPR")

    def test_qb_and_position_premium_points_use_stats_not_rank_identity(self):
        stats = {"pass_tds": 2, "rec_rec": 4, "rec_yds": 50}
        scoring = {"pass_td": 6, "rec": 1, "rec_yd": 0.1, "bonus_rec_te": 1}
        self.assertEqual(score_stats(stats, scoring, position="TE").points, 25)
        self.assertEqual(score_stats(stats, scoring, position="WR").points, 21)
        self.assertEqual(score_stats(stats, scoring, position="QB").points, 21)
        self.assertFalse(score_stats(stats, scoring).complete)

    def test_next_season_anchor_rejects_stale_even_with_explicit_timestamp(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "new_name_board.csv"
            path.write_text("scope,scoring\nskills_half_ppr,HALF\n")
            meta = path.with_name("new_name_metadata.json")
            meta.write_text(
                json.dumps(
                    {
                        "league_key": "new_name",
                        "league_id": "new-id",
                        "season": 2026,
                        "generated_at": "2026-09-01T00:00:00+00:00",
                    }
                )
            )
            with self.assertRaises(CoverageIncomplete):
                resolve_draft_anchor(
                    "new_name",
                    "new-id",
                    season=2027,
                    path=path,
                    updated_at="2027-09-01T00:00:00+00:00",
                )
            meta.write_text(
                json.dumps(
                    {
                        "league_key": "new_name",
                        "league_id": "new-id",
                        "season": 2027,
                        "generated_at": "2027-09-01T00:00:00+00:00",
                    }
                )
            )
            target, _ = resolve_draft_anchor("new_name", "new-id", season=2027, path=path)
            self.assertEqual(target, path)
