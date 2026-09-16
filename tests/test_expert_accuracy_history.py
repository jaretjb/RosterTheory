import unittest

from roster_theory.expert_accuracy_history import (
    AnnualAccuracy,
    parse_accuracy_page,
    recency_accuracy_scores,
)


def annual(year: int, name: str, rank: int, field_size: int = 101) -> AnnualAccuracy:
    return AnnualAccuracy(
        year=year,
        expert_id=year,
        expert_name=name,
        overall_rank=rank,
        field_size=field_size,
        overall_percentile=1.0 - (rank - 1.0) / (field_size - 1.0),
    )


class ExpertAccuracyHistoryTests(unittest.TestCase):
    def test_parses_object_and_legacy_string_experts(self) -> None:
        html = (
            '<script>[{"id":1,"rank":1,"expert":{"label":"Alpha - Site"},'
            '"qb":1},{"id":2,"rank":2,"expert":"Beta - Old Site","qb":2},'
            '{"id":3,"rank":3,"expert":{"label":"Site Rankings - FFToday"},'
            '"qb":3}]</script>'
        )

        rows = parse_accuracy_page(html, 2025)

        self.assertEqual(
            [row.expert_name for row in rows],
            ["Alpha", "Beta", "Site Rankings (FFToday)"],
        )
        self.assertEqual([row.overall_percentile for row in rows], [1.0, 0.5, 0.0])

    def test_recency_weights_are_8_15_21_26_30(self) -> None:
        rows = [
            annual(2021, "Veteran", 101),
            annual(2022, "Veteran", 101),
            annual(2023, "Veteran", 101),
            annual(2024, "Veteran", 101),
            annual(2025, "Veteran", 1),
        ]

        score = recency_accuracy_scores(rows)["veteran"]

        self.assertTrue(score.eligible)
        self.assertAlmostEqual(score.weighted_percentile, 0.30)
        self.assertAlmostEqual(score.score, 0.30)

    def test_two_year_expert_requires_consecutive_top_ten_finishes(self) -> None:
        rows = [
            annual(2024, "Qualifies", 10),
            annual(2025, "Qualifies", 1),
            annual(2023, "Gap", 1),
            annual(2025, "Gap", 1),
            annual(2024, "Outside", 11),
            annual(2025, "Outside", 1),
            annual(2025, "One Year", 1),
        ]

        scores = recency_accuracy_scores(rows)

        self.assertTrue(scores["qualifies"].eligible)
        self.assertAlmostEqual(
            scores["qualifies"].score,
            scores["qualifies"].weighted_percentile * 0.88,
        )
        self.assertFalse(scores["gap"].eligible)
        self.assertFalse(scores["outside"].eligible)
        self.assertFalse(scores["oneyear"].eligible)


if __name__ == "__main__":
    unittest.main()
