import unittest

from roster_theory.fantasypros_import import select_experts
from roster_theory.rankings import AccuracyRecord


class FantasyProsImportTests(unittest.TestCase):
    def test_prefers_multi_year_matches(self) -> None:
        api = [
            {"expert_id": index, "name": f"Expert {index}", "accuracy_draft": {"ALL": 50 + index}}
            for index in range(1, 7)
        ]
        historical = {
            f"expert{index}": AccuracyRecord(f"Expert {index}", index, {"RB": index})
            for index in range(1, 7)
        }
        selected, source = select_experts(api, historical, limit=5)
        self.assertEqual(source, "multi_year_2021_2025")
        self.assertEqual([expert_id for expert_id, _ in selected], [1, 2, 3, 4, 5])

    def test_uses_api_accuracy_for_limited_sample(self) -> None:
        api = [
            {"expert_id": 1, "name": "One", "accuracy_draft": {"ALL": 9, "RB": 2}},
            {"expert_id": 2, "name": "Two", "accuracy_draft": {"ALL": 3, "RB": 8}},
        ]
        selected, source = select_experts(api, {}, limit=2)
        self.assertEqual(source, "api_latest_year_sample_fallback")
        self.assertEqual([expert_id for expert_id, _ in selected], [2, 1])


if __name__ == "__main__":
    unittest.main()
