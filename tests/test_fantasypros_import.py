import unittest

from roster_theory.fantasypros_import import build_fantasypros_board, select_experts
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


class SyntheticDraftClient:
    def __init__(self, ranked, projected, *, scope_by_position=None, ranking_scope_by_source=None):
        self.ranked = ranked
        self.projected = projected
        self.scope_by_position = scope_by_position or {}
        self.ranking_scope_by_source = ranking_scope_by_source or {}
        self.ranking_requests = []

    def ranking_experts(self, season, **params):
        return {"experts": [
            {"expert_id": index, "name": f"Expert {index}",
             "accuracy_draft": {"ALL": index}}
            for index in range(1, 6)
        ], "public_api_limited": False}

    def players(self, sport):
        return {"players": []}

    def projections(self, season, **params):
        position = params["position"]
        return {"season": season, "players": self.projected.get(position, []),
                **self.scope_by_position.get(position, {})}

    def consensus_rankings(self, season, **params):
        self.ranking_requests.append(params)
        source = params.get("filters") or "ecr"
        return {
            "year": str(season), "week": "0", "position_id": params["position"],
            "scoring": params["scoring"], "ranking_type_name": "DRAFT",
            "players": self.ranked.get(params["position"], []),
            **self.ranking_scope_by_source.get((params["position"], source), {}),
        }


def draft_board(client, scoring):
    historical = {
        f"expert{index}": AccuracyRecord(f"Expert {index}", index, {})
        for index in range(1, 6)
    }
    return build_fantasypros_board(
        client, season=2026, league_id="synthetic-draft-league",
        scoring_settings=scoring, roster_positions=["QB", "RB", "WR", "TE"],
        team_count=1, historical_accuracy=historical,
    )


class DraftApiScoringTests(unittest.TestCase):
    def test_explicit_zero_is_usable_but_missing_and_invalid_are_not(self):
        ranked = {"QB": [
            {"player_id": str(index), "player_name": f"Passer {index}",
             "player_position_id": "QB", "rank_ecr": index}
            for index in range(1, 4)
        ]}
        projected = {"QB": [
            {"fpid": "1", "stats": {"pass_yds": 250, "pass_tds": 0}},
            {"fpid": "2", "stats": {"pass_yds": 250}},
            {"fpid": "3", "stats": {"pass_yds": 250, "pass_tds": "nan"}},
        ]}
        board = draft_board(SyntheticDraftClient(ranked, projected),
                            {"pass_yd": 0.04, "pass_td": 6})
        players = {row["fantasypros_id"]: row for row in board.players}
        self.assertEqual(players["1"]["projected_points"], 10.0)
        self.assertIsNone(players["2"]["projected_points"])
        self.assertIsNone(players["3"]["projected_points"])
        self.assertTrue(all(row["rank_score"] is not None for row in players.values()))
        self.assertEqual(board.metadata["players_with_projections"], 1)
        self.assertEqual(board.metadata["projection_scoring_contract"], "fantasypros-draft-season-v1")
        reasons = {issue["fpid"]: issue["reason"] for issue in board.metadata["projection_issues"]}
        self.assertIn("missing_statistic=pass_td", reasons["2"])
        self.assertIn("invalid_statistic=pass_td", reasons["3"])
        self.assertFalse(board.metadata["draft_ready"])

    def test_scope_duplicate_and_unknown_rule_evidence_are_visible(self):
        ranked = {"QB": [{"player_id": "one", "player_name": "One Passer",
                           "player_position_id": "QB", "rank_ecr": 1}]}
        projected = {"QB": [{"fpid": "one", "stats": {"pass_yds": 250}},
                             {"fpid": "one", "stats": {"pass_yds": 300}}]}
        duplicate = draft_board(SyntheticDraftClient(ranked, projected), {"pass_yd": 0.04})
        self.assertIsNone(duplicate.players[0]["projected_points"])
        self.assertIn("duplicate_fpid", [issue["reason"] for issue in duplicate.metadata["projection_issues"]])

        scoped = draft_board(SyntheticDraftClient(ranked, {"QB": projected["QB"][:1]},
                                                  scope_by_position={"QB": {"week": 3}}),
                             {"pass_yd": 0.04})
        self.assertIsNone(scoped.players[0]["projected_points"])
        self.assertIn("source_scope_mismatch:weekly_response=3",
                      [issue["reason"] for issue in scoped.metadata["projection_issues"]])

        unsupported = draft_board(SyntheticDraftClient(ranked, {"QB": projected["QB"][:1]}),
                                  {"pass_yd": 0.04, "bonus_unknown": 1})
        self.assertIsNone(unsupported.players[0]["projected_points"])
        self.assertIn("unsupported_rule=bonus_unknown",
                      unsupported.metadata["projection_issues"][0]["reason"])

        conflicting = draft_board(SyntheticDraftClient(ranked, {"QB": [
            {"fpid": "one", "stats": {"pass_yd": 250, "pass_yds": 300}},
        ]}), {"pass_yd": 0.04})
        self.assertIsNone(conflicting.players[0]["projected_points"])
        self.assertIn("invalid_statistic=pass_yd",
                      conflicting.metadata["projection_issues"][0]["reason"])

    def test_irrelevant_missing_projection_does_not_block_top_board_coverage(self):
        ranked = {position: [] for position in ("QB", "RB", "WR", "TE")}
        projected = {position: [] for position in ranked}
        positions = tuple(ranked)
        for index in range(1, 182):
            position = positions[(index - 1) % 4]
            ranked[position].append({
                "player_id": str(index), "player_name": f"Player {index:03d}",
                "player_position_id": position, "rank_ecr": index,
            })
            projected[position].append({
                "fpid": str(index), "stats": {} if index == 181 else {"rec_rec": 0},
            })
        client = SyntheticDraftClient(ranked, projected)
        independent = draft_board(client, {"rec": 0.5})
        self.assertEqual(independent.metadata["top_180_projection_coverage"], 1.0)
        self.assertTrue(independent.metadata["draft_ready"])

        class SparseExperts(SyntheticDraftClient):
            def consensus_rankings(self, season, **params):
                response = super().consensus_rankings(season, **params)
                if params.get("filters") not in (None, "1:1"):
                    response["players"] = []
                return response

        sparse = draft_board(SparseExperts(ranked, projected), {"rec": 0.5})
        self.assertFalse(sparse.metadata["checks"]["at_least_five_current_experts"])
        self.assertFalse(sparse.metadata["draft_ready"])
        for position in positions:
            for row in projected[position]:
                if int(row["fpid"]) <= 20:
                    row["stats"] = {}
        missing_top = draft_board(client, {"rec": 0.5})
        self.assertLess(missing_top.metadata["top_180_projection_coverage"], 0.90)
        self.assertFalse(missing_top.metadata["draft_ready"])


class DraftRankingScopeTests(unittest.TestCase):
    def test_wrong_horizon_and_fallback_are_excluded_without_losing_valid_positions(self):
        ranked = {
            "QB": [{"player_id": "qb", "player_name": "A Passer",
                    "player_position_id": "QB", "rank_ecr": 1}],
            "RB": [{"player_id": "rb", "player_name": "A Runner",
                    "player_position_id": "RB", "rank_ecr": 1}],
        }
        client = SyntheticDraftClient(ranked, {}, ranking_scope_by_source={
            ("QB", "ecr"): {"ranking_type_name": "ROS"},
            ("QB", "1:1"): {"ranking_type_name": "WW"},
            ("QB", "2:2"): {"fallback_for": "DRAFT"},
        })
        board = draft_board(client, {"rec": 0.5})
        players = {row["fantasypros_id"]: row for row in board.players}
        self.assertEqual(players["qb"]["expert_count"], 3)
        self.assertIsNone(players["qb"]["ecr"])
        self.assertEqual(players["rb"]["expert_count"], 5)
        self.assertFalse(board.metadata["checks"]["draft_ranking_sources_verified"])
        self.assertFalse(board.metadata["draft_ready"])
        self.assertTrue(all(request["type"] == "DRAFT" and request["week"] == 0
                            for request in client.ranking_requests))
        self.assertEqual(len(board.metadata["ranking_issues"]), 3)

    def test_missing_and_mismatched_source_declarations_remain_incomplete(self):
        ranked = {"QB": [{"player_id": "qb", "player_name": "A Passer",
                          "player_position_id": "QB", "rank_ecr": 1}]}
        client = SyntheticDraftClient(ranked, {}, ranking_scope_by_source={
            ("QB", "ecr"): {"year": "2025", "week": "3", "scoring": "PPR",
                            "position_id": "RB", "ranking_type_name": None},
            ("QB", "1:1"): {"year": None, "week": None, "scoring": None,
                            "position_id": None, "ranking_type_name": None},
        })
        board = draft_board(client, {"rec": 0.5})
        reasons = [item["reason"] for item in board.metadata["ranking_issues"]]
        self.assertTrue(any("year_mismatch" in reason and "week_mismatch" in reason
                            and "scoring_mismatch" in reason and "position_id_mismatch" in reason
                            and "missing_ranking_type_name" in reason for reason in reasons))
        self.assertTrue(any("missing_year" in reason and "missing_week" in reason
                            and "missing_scoring" in reason and "missing_position_id" in reason
                            for reason in reasons))
        self.assertEqual(board.players[0]["expert_count"], 4)
        self.assertFalse(board.metadata["draft_ready"])

    def test_malformed_ranking_rows_do_not_crash_or_enter_board(self):
        client = SyntheticDraftClient({"QB": [None]}, {}, ranking_scope_by_source={
            ("QB", "ecr"): {"players": []},
        })
        board = draft_board(client, {"rec": 0.5})
        self.assertEqual(board.players, [])
        self.assertIn("invalid_player_shape", [
            issue["reason"] for issue in board.metadata["ranking_issues"]
        ])
        self.assertFalse(board.metadata["draft_ready"])


if __name__ == "__main__":
    unittest.main()
