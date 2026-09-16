import tempfile
import unittest
from pathlib import Path

from roster_theory.rankings import (
    AccuracyRecord,
    add_vbd,
    load_accuracy,
    load_expert_pool,
    score_projection,
    starter_baselines,
    weighted_consensus,
)

FIXTURES = Path(__file__).parent / "fixtures" / "provider"


class RankingsTests(unittest.TestCase):
    def test_synthetic_master_is_independent_of_current_export_pool(self) -> None:
        master = load_accuracy(FIXTURES / "expert_accuracy.synthetic.csv")
        current = load_expert_pool(FIXTURES / "expert_pool.synthetic.csv", master)

        self.assertIn("expert01", master)
        self.assertIn("expert25", master)
        self.assertEqual(len(master), 25)
        self.assertAlmostEqual(master["expert01"].overall_percentile, 1.0)
        self.assertEqual(set(current), {"expert01", "expert02"})

    def test_synthetic_export_pool_is_balanced_and_auditable(self) -> None:
        master = load_accuracy(FIXTURES / "expert_accuracy.synthetic.csv")

        for scoring in ("standard", "half_ppr"):
            pool = load_expert_pool(
                FIXTURES / "expert_pool.synthetic.csv", master
            )
            self.assertEqual(set(pool), {"expert01", "expert02"}, scoring)

    def test_loads_five_year_percentiles_and_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "accuracy.csv"
            path.write_text(
                "expert_name,overall_rank,overall_percentile,RB,RB_percentile,RB_years,DST,DST_percentile,DST_years\n"
                "Accurate Expert,120,0.90,100,0.95,5,10,0.88,3\n",
                encoding="utf-8",
            )
            record = load_accuracy(path)["accurateexpert"]

        self.assertEqual(record.position_ranks["DST"], 10)
        self.assertEqual(record.position_percentiles["RB"], 0.95)
        self.assertEqual(record.years_by_position["DST"], 3)
        self.assertGreater(record.weight("RB"), 0.75)

    def test_two_year_history_receives_88_percent_coverage_factor(self) -> None:
        record = AccuracyRecord(
            "Two Year Expert",
            1,
            {"RB": 1},
            overall_percentile=1.0,
            position_percentiles={"RB": 1.0},
            years_by_position={"RB": 2},
        )

        self.assertAlmostEqual(record.weight("RB"), 0.88**2)

    def test_weighting_changes_by_position(self) -> None:
        accuracy = {
            "rbexpert": AccuracyRecord("RB Expert", 10, {"RB": 1, "WR": 80}),
            "wrexpert": AccuracyRecord("WR Expert", 10, {"RB": 80, "WR": 1}),
        }
        rows = [
            {"expert_name": "RB Expert", "player_name": "Back A", "position": "RB", "expert_rank": 1},
            {"expert_name": "WR Expert", "player_name": "Back A", "position": "RB", "expert_rank": 10},
            {"expert_name": "RB Expert", "player_name": "Back B", "position": "RB", "expert_rank": 10},
            {"expert_name": "WR Expert", "player_name": "Back B", "position": "RB", "expert_rank": 1},
        ]
        board = weighted_consensus(rows, accuracy, shrink_to_ecr=0)
        self.assertEqual(board[0]["player_name"], "Back A")

    def test_scores_sleeper_settings(self) -> None:
        stats = {"pass_yds": 4000, "pass_tds": 30, "pass_ints": 10, "rush_yds": 200, "rush_tds": 2}
        scoring = {"pass_yd": 0.04, "pass_td": 4, "pass_int": -2, "rush_yd": 0.1, "rush_td": 6}
        self.assertEqual(score_projection(stats, scoring), 292.0)

    def test_assigns_flex_and_vbd(self) -> None:
        players = [
            {"player_name": "RB1", "position": "RB", "projected_points": 200, "rank_score": 1},
            {"player_name": "RB2", "position": "RB", "projected_points": 150, "rank_score": 2},
            {"player_name": "WR1", "position": "WR", "projected_points": 190, "rank_score": 1},
            {"player_name": "WR2", "position": "WR", "projected_points": 170, "rank_score": 2},
        ]
        baselines = starter_baselines(players, ["RB", "WR", "FLEX"], 1)
        self.assertEqual(baselines, {"RB": 200.0, "WR": 170.0})
        board = add_vbd(players, baselines)
        self.assertEqual(board[0]["player_name"], "WR1")
        self.assertEqual(board[0]["vbd"], 20.0)


if __name__ == "__main__":
    unittest.main()
