import csv
import tempfile
import unittest
from pathlib import Path

from roster_theory.league_boards import (
    _match_sleeper,
    _sleeper_candidates,
    build_league_board,
    fetch_board_sources,
    maximum_rosterable_skill_counts,
    projection_counts_complete,
    ranked_skill_projection_coverage,
    ranking_counts_complete,
    score_api_projection,
)
from roster_theory.rankings import starter_baselines


class FakeFantasyProsClient:
    def projections(self, season, **params):
        return {"tier": "premium", "players": [{"fpid": 1, "stats": {}}]}

    def consensus_rankings(self, season, **params):
        return {
            "tier": "premium",
            "ranking_type_name": "adp",
            "total_experts": 3,
            "players": [{"player_id": 1, "rank_ecr": 1}],
        }


class LeagueBoardTests(unittest.TestCase):
    def test_projection_depth_covers_maximum_legal_league_beta_roster_capacity(self) -> None:
        requirements = maximum_rosterable_skill_counts(
            [
                "QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "FLEX",
                "K", "DEF", "BN", "BN", "BN", "BN", "BN",
            ],
            12,
        )

        self.assertEqual(
            requirements,
            {"QB": 72, "RB": 108, "WR": 108, "TE": 96},
        )
        self.assertTrue(
            projection_counts_complete(
                {"QB": 79, "RB": 132, "WR": 203, "TE": 129},
                requirements,
            )
        )
        self.assertFalse(
            projection_counts_complete(
                {"QB": 71, "RB": 132, "WR": 203, "TE": 129},
                requirements,
            )
        )
        self.assertFalse(
            projection_counts_complete(
                {position: 50 for position in ("QB", "RB", "WR", "TE")},
                requirements,
            )
        )

    def test_ranked_projection_coverage_cannot_hide_a_missing_top_player(self) -> None:
        rows = [
            {
                "position": "QB",
                "overall_rank_score": rank,
                "projected_points": None if rank == 1 else 100.0,
            }
            for rank in range(1, 181)
        ]
        rows.append(
            {
                "position": "QB",
                "overall_rank_score": None,
                "projected_points": None,
            }
        )

        count, coverage = ranked_skill_projection_coverage(rows)

        self.assertEqual(count, 180)
        self.assertEqual(coverage, 0.9944)
        self.assertLess(coverage, 1.0)

    def test_ten_expert_fringe_depth_still_requires_complete_draftable_coverage(self) -> None:
        complete = {"QB": 60, "RB": 120, "WR": 150, "TE": 80, "K": 40, "DST": 32}

        self.assertTrue(ranking_counts_complete(complete))
        self.assertFalse(ranking_counts_complete({**complete, "QB": 59}))

    def test_hypothetical_scoring_override_is_simulation_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ranking_path = Path(directory) / "rankings.csv"
            with ranking_path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=(
                        "scope", "position", "fantasypros_id", "player_name", "team",
                        "rank_score", "weighted_position_rank",
                    ),
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "scope": "skills_half_ppr",
                        "position": "RB",
                        "fantasypros_id": "1",
                        "player_name": "Example Back",
                        "team": "SEA",
                        "rank_score": "1",
                        "weighted_position_rank": "1",
                    }
                )
            result = build_league_board(
                league_key="example",
                snapshot={
                    "captured_at": 1,
                    "current": {
                        "league": {
                            "league_id": "league",
                            "name": "Example",
                            "season": "2026",
                            "total_rosters": 1,
                            "roster_positions": ["RB"],
                            "scoring_settings": {"rec": 0},
                        }
                    },
                },
                ranking_path=ranking_path,
                projections={"RB": [{"fpid": "1", "stats": {"rec_rec": 10}}]},
                adp_rows={
                    "STD": [],
                    "HALF": [
                        {
                            "player_id": "1",
                            "rank_ecr": 1,
                            "player_position_id": "RB",
                        }
                    ],
                },
                sleeper_players={
                    "s1": {
                        "full_name": "Example Back",
                        "position": "RB",
                        "team": "SEA",
                    }
                },
                source_metadata={
                    "season": 2026,
                    "projections": {
                        position: {"count": 1}
                        for position in ("QB", "RB", "WR", "TE")
                    },
                    "adp": {"STD": {"count": 0}, "HALF": {"count": 1}},
                },
                scoring_settings_override={"rec": 0.5},
            )
        self.assertEqual(result.metadata["scoring"], "HALF")
        self.assertTrue(result.metadata["hypothetical"])
        self.assertFalse(result.metadata["draft_ready"])
        self.assertEqual(result.players[0]["projected_points"], 5.0)

    def test_scores_skill_projection_with_uniform_two_point_scoring(self) -> None:
        points, status, unsupported = score_api_projection(
            "QB",
            {"pass_yds": 4000, "pass_tds": 30, "pass_ints": 10, "2pt_tds": 2},
            {"pass_yd": 0.04, "pass_td": 4, "pass_int": -2, "pass_2pt": 2, "rush_2pt": 2, "rec_2pt": 2},
        )
        self.assertEqual(points, 264.0)
        self.assertEqual(status, "complete")
        self.assertEqual(unsupported, [])

    def test_scores_supported_dst_stats_and_reports_missing_categories(self) -> None:
        points, status, unsupported = score_api_projection(
            "DST",
            {"def_sack": 40, "def_int": 12, "def_fr": 8, "def_pa_a": 1, "def_pa_g": 2},
            {"sack": 1, "int": 2, "def_st_fum_rec": 1, "pts_allow_0": 10, "pts_allow_35p": -4, "blk_kick": 2},
        )
        self.assertEqual(points, 74.0)
        self.assertEqual(status, "partial")
        self.assertEqual(unsupported, ["blk_kick"])

    def test_does_not_invent_kicker_distance_mix(self) -> None:
        points, status, unsupported = score_api_projection(
            "K",
            {"fg": 30, "fga": 35, "xpt": 40},
            {"xpm": 1, "fgmiss": -1, "fgm_0_19": 3, "fgm_50p": 5},
        )
        self.assertIsNone(points)
        self.assertEqual(status, "unavailable")
        self.assertEqual(unsupported, ["fgm_0_19", "fgm_50p"])

    def test_replacement_baselines_include_k_and_def_alias(self) -> None:
        players = [
            {"position": "K", "projected_points": 100},
            {"position": "DST", "projected_points": 90},
        ]
        self.assertEqual(starter_baselines(players, ["K", "DEF"], 1), {"K": 100.0, "DST": 90.0})

    def test_fetches_four_skill_projection_positions_and_two_adp_formats(self) -> None:
        projections, adp, metadata = fetch_board_sources(
            FakeFantasyProsClient(), season=2026, minimum_interval=0
        )
        self.assertEqual(set(projections), {"QB", "RB", "WR", "TE"})
        self.assertEqual(set(adp), {"STD", "HALF"})
        self.assertEqual(metadata["request_count"], 6)

    def test_sleeper_matching_accepts_omitted_suffix_and_known_nickname(self) -> None:
        candidates = _sleeper_candidates({
            "one": {"full_name": "Patrick Mahomes", "position": "QB", "team": "KC"},
            "two": {"full_name": "Marquise Brown", "position": "WR", "team": "PHI"},
        })
        self.assertEqual(_match_sleeper("Patrick Mahomes II", "QB", "KC", candidates)[0], "one")
        self.assertEqual(_match_sleeper("Hollywood Brown", "WR", "PHI", candidates)[0], "two")


if __name__ == "__main__":
    unittest.main()
