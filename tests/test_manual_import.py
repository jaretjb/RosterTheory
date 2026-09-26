import tempfile
import unittest
from pathlib import Path

from roster_theory.cli import _validate_rankings_scoring
from roster_theory.manual_import import (
    _match_sleeper_player,
    _sleeper_candidates,
    build_manual_board,
    load_fantasypros_rankings,
    load_fantasypros_rankings_matrix,
    load_fantasypros_projections,
)
from roster_theory.rankings import AccuracyRecord


EXPERTS = ["Expert Alpha", "Expert Bravo", "Expert Charlie", "Expert Delta", "Expert Echo"]


def accuracy_records() -> dict[str, AccuracyRecord]:
    return {
        name.lower().replace(" ", ""): AccuracyRecord(name, index, {position: index for position in ("QB", "RB", "WR", "TE")})
        for index, name in enumerate(EXPERTS, start=1)
    }


class ManualImportTests(unittest.TestCase):
    def test_rankings_scoring_must_match_sleeper_receptions(self) -> None:
        _validate_rankings_scoring("standard_league", 0.0, "standard")
        _validate_rankings_scoring("half_league", 0.5, "half-ppr")
        with self.assertRaisesRegex(ValueError, "use standard rankings"):
            _validate_rankings_scoring("standard_league", 0.0, "half-ppr")

    def test_accepts_selected_expert_consensus_export(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "selected_ecr.csv"
            path.write_text(
                "RK,TIERS,PLAYER NAME,TEAM,POS,BYE WEEK,ECR VS. ADP,AVG. DIFF\n"
                "1,1,One Player,SEA,QB1,8,+2,+1.2\n"
                "2,1,Two Player,DET,RB1,6,-1,-0.5\n"
                "3,2,Seattle Seahawks,SEA,DST1,8,+4,+0.2\n",
                encoding="utf-8",
            )
            master = accuracy_records()
            current_pool = {
                key: record
                for key, record in master.items()
                if record.expert_name in EXPERTS[:2]
            }
            rows, metadata, issues = load_fantasypros_rankings(
                path, master, selected_experts=current_pool
            )

        self.assertEqual(len(rows), 2)
        self.assertEqual(metadata["aggregation_mode"], "fantasypros_selected_ecr")
        self.assertEqual(metadata["matched_experts"], sorted(EXPERTS[:2]))
        self.assertFalse(metadata["selection_embedded_in_export"])
        self.assertEqual(metadata["skipped_rows"], 1)
        self.assertEqual([issue["reason"] for issue in issues], ["excluded_non_skill_position"])

    def test_builds_and_audits_small_fantasypros_export(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            rankings = root / "rankings.csv"
            rankings.write_text(
                "RK,PLAYER," + ",".join(f"{name} 08/23/26" for name in EXPERTS) + "\n"
                "1,Alpha Quarterback SEA QB,1,2,3,4,5\n"
                "2,Bravo Running Back DET RB,2,1,4,3,5\n"
                "3,Charlie Wide Receiver LAR WR,3,4,1,2,5\n"
                "4,Delta Tight End LV TE,4,3,2,1,5\n",
                encoding="utf-8",
            )
            (root / "qb_projections.csv").write_text(
                "PLAYER,ATT,CMP,YDS,TDS,INTS,ATT,YDS,TDS,FL,FPTS\n"
                "Alpha Quarterback SEA,500,350,4000,30,10,40,200,2,1,0\n",
                encoding="utf-8",
            )
            (root / "rb_projections.csv").write_text(
                "PLAYER,ATT,YDS,TDS,REC,YDS,TDS,FL,FPTS\n"
                "Bravo Running Back DET,250,1200,10,50,400,3,1,0\n",
                encoding="utf-8",
            )
            (root / "wr_projections.csv").write_text(
                "PLAYER,REC,YDS,TDS,ATT,YDS,TDS,FL,FPTS\n"
                "Charlie Wide Receiver LAR,90,1300,9,5,30,0,1,0\n",
                encoding="utf-8",
            )
            (root / "te_projections.csv").write_text(
                "PLAYER,REC,YDS,TDS,FL,FPTS\n"
                "Delta Tight End LV,70,800,6,1,0\n",
                encoding="utf-8",
            )
            adp = root / "adp.csv"
            adp.write_text(
                "PLAYER (BYE),POS,SLEEPER,RTSPORTS,AVG\n"
                "Alpha Quarterback SEA (9),QB1,10,12,11\n"
                "Bravo Running Back DET (8),RB1,1,2,1.5\n"
                "Charlie Wide Receiver LAR (11),WR1,2,3,2.5\n"
                "Delta Tight End LV (8),TE1,20,22,21\n",
                encoding="utf-8",
            )
            sleeper = {
                str(index): {
                    "full_name": name,
                    "position": position,
                    "fantasy_positions": [position],
                    "team": team,
                }
                for index, (name, position, team) in enumerate(
                    [
                        ("Alpha Quarterback", "QB", "SEA"),
                        ("Bravo Running Back", "RB", "DET"),
                        ("Charlie Wide Receiver", "WR", "LAR"),
                        ("Delta Tight End", "TE", "LV"),
                    ],
                    start=1,
                )
            }
            result = build_manual_board(
                rankings_path=rankings,
                projection_paths=[
                    root / "qb_projections.csv",
                    root / "rb_projections.csv",
                    root / "wr_projections.csv",
                    root / "te_projections.csv",
                ],
                adp_path=adp,
                scoring_settings={
                    "pass_yd": 0.04,
                    "pass_td": 4,
                    "pass_int": -2,
                    "rush_yd": 0.1,
                    "rush_td": 6,
                    "rec": 0.5,
                    "rec_yd": 0.1,
                    "rec_td": 6,
                    "fum_lost": -2,
                },
                league_id="synthetic-draft-league",
                season=2026,
                roster_positions=["QB", "RB", "WR", "TE"],
                team_count=1,
                historical_accuracy=accuracy_records(),
                sleeper_players=sleeper,
            )

        by_name = {player["player_name"]: player for player in result.players}
        self.assertIsNone(by_name["Alpha Quarterback"]["projected_points"])
        self.assertEqual(by_name["Bravo Running Back"]["adp"], 1.5)
        self.assertTrue(all(row["match_status"] == "matched" for row in result.match_report))
        self.assertEqual(result.metadata["replacement_baselines"], {})
        self.assertEqual(result.metadata["projections"]["complete_scoring_player_count"], 0)
        self.assertEqual(result.metadata["coverage"]["projection"], 0.0)
        self.assertFalse(result.metadata["checks"]["top_180_projection_coverage_at_least_90_percent"])
        self.assertEqual(
            {issue["reason"] for issue in result.issues if "scoring" in issue["reason"]},
            {"scoring_incomplete_v1"},
        )
        self.assertFalse(result.metadata["draft_ready"])
        self.assertTrue(result.metadata["sample_only"])
        self.assertFalse(result.metadata["checks"]["at_least_150_ranked_skill_players"])

    def test_projection_import_distinguishes_explicit_zero_missing_and_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "qb_projections.csv"
            path.write_text(
                "PLAYER,YDS,TDS\n"
                "Complete Passer SEA,250,0\n"
                "Blank Passer SEA,250,\n"
                "Invalid Passer SEA,250,unknown\n"
                "Nonfinite Passer SEA,250,nan\n",
                encoding="utf-8",
            )
            rows, metadata, issues = load_fantasypros_projections(
                [path], {"pass_yd": 0.04, "pass_td": 6},
                league_id="synthetic-draft-league", season=2026,
            )
        by_name = {row["player_name"]: row for row in rows.values()}
        self.assertEqual(by_name["Complete Passer"]["projected_points"], 10.0)
        self.assertIsNone(by_name["Blank Passer"]["projected_points"])
        self.assertIsNone(by_name["Invalid Passer"]["projected_points"])
        self.assertIsNone(by_name["Nonfinite Passer"]["projected_points"])
        self.assertEqual(metadata["complete_scoring_player_count"], 1)
        self.assertEqual(metadata["league_id"], "synthetic-draft-league")
        self.assertEqual(metadata["season"], 2026)
        details = {issue["row"]: issue["detail"] for issue in issues}
        self.assertIn("missing_statistic=pass_td", details[3])
        self.assertIn("invalid_statistic=pass_td", details[4])
        self.assertIn("invalid_statistic=pass_td", details[5])

    def test_missing_off_role_stat_and_unknown_rule_do_not_count_as_projections(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rb_projections.csv"
            path.write_text("PLAYER,YDS,TDS\nRunner DET,100,1\n", encoding="utf-8")
            rows, _, issues = load_fantasypros_projections(
                [path], {"rush_yd": 0.1, "rush_td": 6, "pass_td": 4,
                         "bonus_unknown": 1},
                league_id="synthetic-draft-league", season=2026,
            )
        self.assertIsNone(next(iter(rows.values()))["projected_points"])
        self.assertIn("missing_statistic=pass_td", issues[0]["detail"])
        self.assertIn("unsupported_rule=bonus_unknown", issues[0]["detail"])

    def test_reports_unknown_expert_columns_and_unusable_players(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rankings.csv"
            path.write_text(
                "RK,PLAYER,Expert Alpha 08/23/26,Mystery Analyst\n"
                "1,One Player SEA QB,1,2\n"
                "2,Two Player DET RB,2,1\n"
                "3,Three Player LAR WR,3,3\n"
                "4,Team Defense SEA DST,4,4\n",
                encoding="utf-8",
            )
            rows, metadata, issues = load_fantasypros_rankings_matrix(path, accuracy_records())

        self.assertEqual(len(rows), 3)
        self.assertEqual(metadata["unmatched_expert_columns"], ["Mystery Analyst"])
        self.assertEqual({issue["reason"] for issue in issues}, {"unmatched_expert_column", "unusable_ranking_player"})

    def test_reports_ambiguous_sleeper_players(self) -> None:
        sleeper = {
            "one": {"full_name": "Same Name", "position": "WR", "fantasy_positions": ["WR"]},
            "two": {"full_name": "Same Name", "position": "WR", "fantasy_positions": ["WR"]},
        }
        sleeper_id, status, candidates = _match_sleeper_player(
            "Same Name", "WR", None, _sleeper_candidates(sleeper), {}
        )
        self.assertIsNone(sleeper_id)
        self.assertEqual(status, "ambiguous")
        self.assertEqual({candidate["sleeper_id"] for candidate in candidates}, {"one", "two"})


if __name__ == "__main__":
    unittest.main()
