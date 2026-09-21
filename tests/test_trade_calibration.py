from __future__ import annotations

import copy
import unittest

from roster_theory.trade.calibration import run_calibration_study


LEAGUE = "league-fixture"
SCORING = "fixture-scoring"


def fixture() -> dict:
    origins = [
        {"id": f"w{week}", "season": 2026, "week": week,
         "decision_at": f"2026-09-{week + 1:02d}T12:00:00Z"}
        for week in range(1, 5)
    ]
    data = {"schema_version": 1, "league_key": LEAGUE,
            "scoring_fingerprint": SCORING, "origins": origins,
            "intrinsic": [], "market": [], "performance": [], "search": [],
            "grids": {
                "intrinsic": [{"edge": 1.0, "downside": 2.0}, {"edge": 3.0, "downside": 1.0}],
                "market": [{"ratio": 0.1, "floor": 0.0, "premium": 0.0},
                           {"ratio": 0.2, "floor": 0.0, "premium": 0.1}],
                "performance": [2, 3], "search": [
                    {"budget": 1, "minimum_candidate_gain": 0.0,
                     "minimum_lane_signal_gap": 0.0},
                    {"budget": 2, "minimum_candidate_gain": 0.0,
                     "minimum_lane_signal_gap": 0.0},
                    {"budget": 2, "minimum_candidate_gain": 2.0,
                     "minimum_lane_signal_gap": 0.1}]}}
    for week in range(1, 5):
        base = {"league_key": LEAGUE, "scoring_fingerprint": SCORING,
                "origin_id": f"w{week}", "source_hash": f"fixture-week-{week}"}
        earlier = f"2026-09-{week + 1:02d}T10:00:00Z"
        later = f"2026-09-{week + 1:02d}T14:00:00Z"
        for index, realized in enumerate((3.0, -2.0)):
            data["intrinsic"].append({**base, "candidate_id": f"c{index}",
                "lane": "BUY_LOW", "package_size": "1-for-1",
                "feature_available_at": earlier, "outcome_available_at": later,
                "projected_gain": 2.0 + index, "projected_downside": float(index),
                "realized_gain": realized})
            data["market"].append({**base, "candidate_id": f"c{index}",
                "package_size": "2-for-1", "market_sent": 110.0 + 30 * index,
                "market_received": 100.0, "market_published_at": earlier,
                "reference_published_at": earlier, "market_source": "chart",
                "reference_source": "independent-panel",
                "reference_kind": "COMMUNITY_FAIRNESS_ASSESSMENT",
                "reference_fair": index == 0})
            for window in (2, 3):
                data["performance"].append({**base, "player_id": f"p{index}",
                    "window_weeks": window, "signal": 1 if window == 2 else -1,
                    "future_direction": 1, "feature_available_at": earlier,
                    "outcome_available_at": later})
        for lane in ("BUY_LOW", "SELL_HIGH", "CONSOLIDATE", "NEED_FIT"):
            for size in ("1-for-1", "2-for-1", "1-for-2", "2-for-2"):
                data["search"].append({**base, "lane": lane, "package_size": size,
                    "feature_available_at": earlier, "complete": True,
                    "candidates": [
                        {"id": "a", "heuristic_rank": 1, "exact_gain": 1.0,
                         "candidate_lineup_gain": 1.0, "lane_signal_gap": 0.1,
                         "runtime_ms": 2.0},
                        {"id": "b", "heuristic_rank": 2, "exact_gain": 3.0,
                         "candidate_lineup_gain": 3.0, "lane_signal_gap": 0.2,
                         "runtime_ms": 4.0}]})
    return data


class TradeCalibrationTests(unittest.TestCase):
    def test_separate_axes_and_rolling_origins(self) -> None:
        result = run_calibration_study(fixture())
        self.assertEqual(result["status"], "NOT_PROMOTED")
        self.assertEqual(set(result["axes"]), {"intrinsic", "market", "performance", "search"})
        self.assertEqual(len(result["axes"]["search"]), 16)
        intrinsic = result["axes"]["intrinsic"][0]
        self.assertEqual([row["origin_id"] for row in intrinsic["holdouts"]], ["w3", "w4"])
        self.assertEqual(intrinsic["holdouts"][0]["selected_setting"], {"edge": 1.0, "downside": 2.0})
        self.assertEqual(result["axes"]["search"][0]["holdouts"][0]["selected_setting"]["budget"], 2)
        self.assertEqual(result["axes"]["search"][0]["holdouts"][0]["selected_setting"]["minimum_candidate_gain"], 2.0)
        self.assertEqual(result["axes"]["search"][0]["holdouts"][0]["holdout"]["gated_out_candidates"], 1)
        self.assertEqual(result["axes"]["performance"][0]["holdouts"][0]["selected_setting"], 2)
        self.assertEqual(result["axes"]["market"][0]["holdouts"][0]["holdout"]["reference_positive"], 1)
        self.assertEqual(len(intrinsic["holdouts"][0]["training_grid"]), 2)
        self.assertEqual(len(intrinsic["holdouts"][0]["holdout_grid"]), 2)
        self.assertTrue(result["evidence_hash"])

    def test_future_feature_and_reference_rejected(self) -> None:
        for axis, field in (("intrinsic", "feature_available_at"),
                            ("market", "reference_published_at"),
                            ("performance", "feature_available_at"),
                            ("search", "feature_available_at")):
            with self.subTest(axis=axis):
                data = fixture()
                data[axis][0][field] = "2026-09-02T13:00:00Z"
                with self.assertRaises(ValueError):
                    run_calibration_study(data)

    def test_future_training_outcome_is_not_used(self) -> None:
        data = fixture()
        for row in data["intrinsic"]:
            if row["origin_id"] in ("w1", "w2"):
                row["outcome_available_at"] = "2026-09-06T00:00:00Z"
        result = run_calibration_study(data)
        self.assertEqual(result["axes"]["intrinsic"][0]["status"], "UNAVAILABLE")
        self.assertGreater(result["axes"]["intrinsic"][0]["rejection_counts"]["INSUFFICIENT_TIME_ORDERED_EVIDENCE"], 0)

    def test_league_scoring_and_source_isolation(self) -> None:
        for axis, key, value in (("intrinsic", "league_key", "other"),
                                 ("performance", "scoring_fingerprint", "other"),
                                 ("market", "reference_source", "chart")):
            with self.subTest(axis=axis):
                data = fixture()
                data[axis][0][key] = value
                with self.assertRaises(ValueError):
                    run_calibration_study(data)

    def test_non_exhaustive_search_rejected(self) -> None:
        data = fixture()
        data["search"][0]["complete"] = False
        with self.assertRaises(ValueError):
            run_calibration_study(data)

    def test_repeated_week_and_acceptance_label_rejected(self) -> None:
        data = fixture()
        data["origins"][1]["week"] = 1
        with self.assertRaises(ValueError):
            run_calibration_study(data)
        data = fixture()
        data["market"][0]["reference_kind"] = "TRADE_ACCEPTED"
        with self.assertRaises(ValueError):
            run_calibration_study(data)

    def test_missing_lane_reports_unavailable_without_promotion(self) -> None:
        data = fixture()
        data["search"] = [row for row in data["search"] if row["lane"] != "CONSOLIDATE"]
        result = run_calibration_study(data)
        self.assertEqual(sum(row["status"] == "UNAVAILABLE" for row in result["axes"]["search"]), 4)
        self.assertEqual(result["status"], "NOT_PROMOTED")

    def test_deterministic_and_no_mutation(self) -> None:
        data = fixture()
        original = copy.deepcopy(data)
        self.assertEqual(run_calibration_study(data), run_calibration_study(data))
        self.assertEqual(data, original)


if __name__ == "__main__":
    unittest.main()
