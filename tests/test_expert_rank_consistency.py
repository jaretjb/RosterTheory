import csv
import tempfile
import unittest
from pathlib import Path

from roster_theory.expert_rank_consistency import (
    audit_expert_rank_consistency,
    audit_weighted_export_consistency,
    build_weighted_ballot_preferences,
    enrich_ranked_csv_with_dispersion,
    rank_dispersion_by_player,
)


class FakeFantasyProsClient:
    def __init__(self) -> None:
        self.calls = []

    def consensus_rankings(self, season, **params):
        self.calls.append((season, params))
        position = params["position"]
        common = {
            "total_experts": 1,
            "expert_names": {"7": "Expert Seven"},
        }
        if position == "ALL":
            return {
                **common,
                "players": [
                    {
                        "player_id": "walker",
                        "player_name": "Kenneth Walker III",
                        "player_position_id": "RB",
                        "rank_ecr": 20,
                    },
                    {
                        "player_id": "henry",
                        "player_name": "Derrick Henry",
                        "player_position_id": "RB",
                        "rank_ecr": 19,
                    },
                    {
                        "player_id": "third",
                        "player_name": "Third Runner",
                        "player_position_id": "RB",
                        "rank_ecr": 30,
                    },
                ],
            }
        return {
            **common,
            "players": [
                {
                    "player_id": "walker",
                    "player_name": "Kenneth Walker III",
                    "player_position_id": "RB",
                    "rank_ecr": 9,
                },
                {
                    "player_id": "henry",
                    "player_name": "Derrick Henry",
                    "player_position_id": "RB",
                    "rank_ecr": 10,
                },
                {
                    "player_id": "third",
                    "player_name": "Third Runner",
                    "player_position_id": "RB",
                    "rank_ecr": 11,
                },
            ],
        }


class ExpertRankConsistencyTests(unittest.TestCase):
    def test_calculates_and_exports_weighted_rank_dispersion(self) -> None:
        individual = [
            {
                "expert_id": 1,
                "expert_weight": 0.75,
                "ranking_feed": feed,
                "player_id": "walker",
                "rank": rank,
            }
            for feed, rank in (("ALL", 10), ("RB", 5))
        ] + [
            {
                "expert_id": 2,
                "expert_weight": 0.25,
                "ranking_feed": feed,
                "player_id": "walker",
                "rank": rank,
            }
            for feed, rank in (("ALL", 30), ("RB", 13))
        ]
        dispersion = rank_dispersion_by_player(individual)
        self.assertAlmostEqual(
            dispersion[("walker", "ALL")]["rank_stddev"], 8.660254
        )
        self.assertEqual(dispersion[("walker", "ALL")]["rank_min"], 10)
        self.assertEqual(dispersion[("walker", "ALL")]["rank_max"], 30)
        self.assertEqual(dispersion[("walker", "ALL")]["expert_count"], 2)

        with tempfile.TemporaryDirectory() as temporary:
            rankings = Path(temporary) / "weighted.csv"
            with rankings.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=(
                        "scope",
                        "position",
                        "fantasypros_id",
                        "player_name",
                        "rank_score",
                    ),
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "scope": "skills_half_ppr",
                        "position": "RB",
                        "fantasypros_id": "walker",
                        "player_name": "Kenneth Walker III",
                        "rank_score": 7,
                    }
                )
            result = enrich_ranked_csv_with_dispersion(
                rankings, individual, scope="skills_half_ppr"
            )
            with rankings.open("r", encoding="utf-8", newline="") as handle:
                row = next(csv.DictReader(handle))

        self.assertEqual(result["enriched_player_count"], 1)
        self.assertEqual(float(row["overall_rank_stddev"]), 8.660254)
        self.assertEqual(float(row["position_rank_stddev"]), 3.464102)
        self.assertEqual(int(row["overall_rank_experts"]), 2)
        self.assertEqual(float(row["overall_rank_weight_coverage"]), 1.0)

    def test_audits_individual_all_versus_position_pair_inversions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            pool = Path(temporary) / "expert_pools.csv"
            with pool.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=(
                        "scope",
                        "selection_rank",
                        "expert_name",
                        "expert_id",
                        "last_updated",
                    ),
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "scope": "skills_half_ppr",
                        "selection_rank": 1,
                        "expert_name": "Expert Seven",
                        "expert_id": 7,
                        "last_updated": "2026-08-25 01:00:00",
                    }
                )
            client = FakeFantasyProsClient()
            audit = audit_expert_rank_consistency(
                client,
                season=2026,
                expert_pool_path=pool,
                positions=("RB",),
                minimum_interval=0,
            )

        self.assertEqual(audit["request_count"], 2)
        self.assertEqual(audit["issues"], [])
        self.assertEqual(len(audit["individual_rankings"]), 6)
        self.assertEqual(
            {row["ranking_feed"] for row in audit["individual_rankings"]},
            {"ALL", "RB"},
        )
        self.assertEqual(audit["summary"]["comparable_pairs"], 3)
        self.assertEqual(audit["summary"]["inversion_count"], 1)
        target = audit["target_comparisons"][0]
        self.assertEqual(target["all_order"], "Derrick Henry")
        self.assertEqual(target["position_order"], "Kenneth Walker III")
        self.assertEqual(client.calls[0][1]["type"], "DRAFT")
        self.assertNotIn("type", client.calls[1][1])
        self.assertEqual(client.calls[0][1]["filters"], "7:7")

    def test_detects_a_composite_all_versus_position_reversal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            rankings = Path(temporary) / "weighted.csv"
            with rankings.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=(
                        "scope",
                        "position",
                        "fantasypros_id",
                        "player_name",
                        "rank_score",
                        "overall_rank_score",
                    ),
                )
                writer.writeheader()
                writer.writerows(
                    [
                        {
                            "scope": "skills_half_ppr",
                            "position": "RB",
                            "fantasypros_id": "walker",
                            "player_name": "Kenneth Walker III",
                            "rank_score": 9.9,
                            "overall_rank_score": 20.8,
                        },
                        {
                            "scope": "skills_half_ppr",
                            "position": "RB",
                            "fantasypros_id": "henry",
                            "player_name": "Derrick Henry",
                            "rank_score": 10.3,
                            "overall_rank_score": 19.4,
                        },
                    ]
                )
            audit = audit_weighted_export_consistency(
                rankings, "skills_half_ppr"
            )

        self.assertEqual(audit["comparable_pairs"], 1)
        self.assertEqual(audit["inversion_count"], 1)
        self.assertEqual(audit["inversions"][0]["position"], "RB")

    def test_builds_direct_weighted_pairwise_preferences(self) -> None:
        rankings = [
            {
                "expert_id": 1,
                "expert_weight": 0.6,
                "ranking_feed": "RB",
                "player_id": "walker",
                "rank": 2,
            },
            {
                "expert_id": 1,
                "expert_weight": 0.6,
                "ranking_feed": "RB",
                "player_id": "henry",
                "rank": 1,
            },
            {
                "expert_id": 2,
                "expert_weight": 0.4,
                "ranking_feed": "RB",
                "player_id": "walker",
                "rank": 1,
            },
            {
                "expert_id": 2,
                "expert_weight": 0.4,
                "ranking_feed": "RB",
                "player_id": "henry",
                "rank": 2,
            },
        ]
        board = [
            {
                "fantasypros_id": "walker",
                "player_key": "walker-key",
                "player_name": "Kenneth Walker III",
                "position": "RB",
            },
            {
                "fantasypros_id": "henry",
                "player_key": "henry-key",
                "player_name": "Derrick Henry",
                "position": "RB",
            },
        ]

        preferences, metadata = build_weighted_ballot_preferences(
            rankings, board
        )

        self.assertAlmostEqual(preferences[("henry-key", "walker-key")], 0.6)
        self.assertAlmostEqual(preferences[("walker-key", "henry-key")], 0.4)
        self.assertEqual(metadata["covered_pairs"], 1)


if __name__ == "__main__":
    unittest.main()
