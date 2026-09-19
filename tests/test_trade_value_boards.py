from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from roster_theory.core.errors import CoverageIncomplete, IdentityIncomplete, UnsupportedScoring
from roster_theory.core.isotonic import fit_nonincreasing_curve
from roster_theory.core.models import Projection, RankObservation
from roster_theory.core.models import Player
from roster_theory.providers.fantasypros import FantasyProsIdentity, normalize_rankings
from roster_theory.providers.cache import DailyRequestBudget, cache_key
from roster_theory.trade.boards import (
    aggregate_selected_ranks,
    build_projection_curves,
    build_value_board,
    export_board_evidence,
    valuation_gaps,
)
from roster_theory.trade.experts import (
    CurrentExpert,
    InSeasonAccuracy,
    accuracy_from_expert_directory,
    parse_inseason_accuracy_page,
    score_experts,
    select_current_experts,
)
from roster_theory.trade.board_service import (
    _build_provider_projection_curves,
    _input_calls,
    _identity_map,
    board_refresh_report,
    classify_trade_scoring,
    refresh_value_boards,
    resolve_draft_anchor,
)
from roster_theory.trade.horizons import choose_season_stage
from roster_theory.cli import build_parser


def accuracy(year: int, expert_id: str, rank: int, field: int = 101) -> InSeasonAccuracy:
    return InSeasonAccuracy(
        year=year,
        expert_id=expert_id,
        expert_name=f"Expert {expert_id}",
        source_name=f"Site {expert_id}",
        overall_rank=rank,
        qb_rank=rank,
        rb_rank=rank,
        wr_rank=rank,
        te_rank=rank,
        field_size=field,
        overall_percentile=1.0 - (rank - 1.0) / (field - 1.0),
        source_url="https://example.test",
        retrieved_at="2026-09-05T00:00:00+00:00",
    )


def current(expert_id: str, source: str | None = None) -> CurrentExpert:
    return CurrentExpert(
        expert_id=expert_id,
        name=f"Expert {expert_id}",
        source_name=source or f"Site {expert_id}",
        position_updates=tuple(
            (position, "2026-09-05T00:00:00+00:00")
            for position in ("QB", "RB", "WR", "TE")
        ),
        latest_weekly_accuracy=(("ALL", 1),),
        prior_weekly_accuracy=(("ALL", 2),),
    )


def rank(
    player_id: str,
    position_rank: int,
    *,
    expert_id: str | None = None,
    horizon: str = "WEEKLY-PROXY",
) -> RankObservation:
    return RankObservation(
        player_id=player_id,
        horizon=horizon,
        board_source="market" if expert_id is None else "expert_ballot",
        expert_id=expert_id,
        position="RB",
        position_rank=float(position_rank),
        overall_rank=float(position_rank) if expert_id is None else None,
        tier=1,
        scoring="HALF",
        updated_at="2026-09-05T00:00:00+00:00",
    )


class InSeasonExpertTests(unittest.TestCase):
    def test_public_parser_preserves_position_evidence(self) -> None:
        html = (
            '<script>{"rows":[{"id":1,"rank":1,"expert":{"label":"Alpha - One"},'
            '"qb":2,"rb":1,"wr":3,"te":null,"k":4,"dst":5,"idp":null},'
            '{"id":2,"rank":2,"expert":"Beta - Two","qb":1,"rb":2,'
            '"wr":1,"te":2,"k":null,"dst":null,"idp":null}]}</script>'
        )
        rows = parse_inseason_accuracy_page(
            html, 2025, retrieved_at="2026-09-05T00:00:00+00:00"
        )
        self.assertEqual(len(rows), 2)
        self.assertEqual((rows[0].expert_name, rows[0].source_name), ("Alpha", "One"))
        self.assertIsNone(rows[0].te_rank)
        self.assertEqual(rows[1].wr_rank, 1)

    def test_directory_extracts_only_qualified_weekly_rows(self) -> None:
        value = {
            "accuracy_weekly_season": "2025",
            "accuracy_weekly_last_season": "2024",
            "experts": [
                {"expert_id": 1, "name": "One", "source": "A", "accuracy_weekly": {"ALL": 1, "QB": 2}},
                {"expert_id": 2, "name": "Two", "source": "B", "accuracy_weekly": None},
                {"expert_id": 3, "name": "Three", "source": "C", "accuracy_weekly": {"ALL": 3, "RB": 1}},
            ],
        }
        rows = accuracy_from_expert_directory(
            value,
            retrieved_at="2026-09-05T00:00:00+00:00",
            source_url="https://api.example.test",
        )
        self.assertEqual([row.overall_rank for row in rows], [1, 3])
        self.assertEqual(rows[0].field_size, 3)

    def test_scoring_normalizes_field_and_penalizes_coverage(self) -> None:
        rows = [
            accuracy(2024, "1", 1),
            accuracy(2025, "1", 1),
            accuracy(2021, "2", 2),
            accuracy(2022, "2", 2),
            accuracy(2023, "2", 2),
            accuracy(2024, "2", 2),
            accuracy(2025, "2", 2),
        ]
        scores = {item.expert_id: item for item in score_experts(rows)}
        self.assertLess(scores["1"].coverage, scores["2"].coverage)
        self.assertEqual(scores["2"].seasons, 5)

    def test_selection_enforces_freshness_and_site_cap(self) -> None:
        rows = [accuracy(year, expert, int(expert)) for year in (2024, 2025) for expert in ("1", "2", "3", "4")]
        scores = score_experts(rows, weights={2024: 1, 2025: 1})
        active = [current("1", "Shared"), current("2", "Shared"), current("3", "Shared"), current("4", "Other")]
        selected = select_current_experts(
            scores,
            active,
            now=datetime(2026, 9, 5, 1, tzinfo=timezone.utc),
            pool_size=3,
            maximum_source_count=2,
            freshness_hours=2,
        )
        self.assertEqual([item.expert_id for item in selected], ["1", "2", "4"])
        self.assertAlmostEqual(sum(item.weight for item in selected), 1.0)


class TradeBoardTests(unittest.TestCase):
    def test_provider_only_projection_keeps_its_rank_slot_without_entering_board_universe(self) -> None:
        projections = tuple(
            Projection(
                player_id=player_id,
                horizon="WEEKLY",
                week=1,
                raw_stats=(("points", points),),
                league_points=points,
                source="fixture",
                coverage_status="complete",
            )
            for player_id, points in (
                ("sleeper-1", 30.0),
                ("sleeper-2", 20.0),
                ("fp:draft-sleeper-6149", 10.0),
            )
        )
        distribution_positions = {
            "sleeper-1": "WR",
            "sleeper-2": "WR",
            "fp:draft-sleeper-6149": "WR",
        }
        board_positions = {"sleeper-1": "WR", "sleeper-2": "WR"}

        curves = _build_provider_projection_curves(
            projections,
            distribution_positions,
            required_counts={"WR": 3},
            expected_weeks=(1,),
        )

        curve = next(row for row in curves if row.position == "WR")
        self.assertEqual(curve.slot_points, ((1, 30.0), (2, 20.0), (3, 10.0)))
        self.assertNotIn("fp:draft-sleeper-6149", board_positions)

    def test_waiver_ranking_window_can_be_shorter_without_changing_trade_defaults(self):
        now = datetime(2026, 9, 10, 12, tzinfo=timezone.utc)
        definitions = (
            (
                "/nfl/2026/consensus-rankings",
                {"position": "RB", "scoring": "HALF", "week": 2, "experts": "show"},
            ),
            (
                "/nfl/2026/consensus-rankings",
                {
                    "position": "RB",
                    "scoring": "HALF",
                    "type": "ROS",
                    "experts": "show",
                },
            ),
            (
                "/nfl/2026/rankings/experts",
                {"type": "ROS", "include_overall": "true"},
            ),
        )
        with tempfile.TemporaryDirectory() as directory:
            cache_dir = Path(directory)
            for endpoint, parameters in definitions:
                path = cache_dir / f"{cache_key(endpoint, parameters)}.json"
                path.write_text(
                    json.dumps(
                        {
                            "captured_at": (now - timedelta(hours=3)).isoformat(),
                            "payload": {},
                        }
                    ),
                    encoding="utf-8",
                )
            default_plan, _, _ = _input_calls(
                2026,
                2,
                (2,),
                cache_dir,
                now,
                DailyRequestBudget(),
                ("RB",),
            )
            waiver_plan, _, _ = _input_calls(
                2026,
                2,
                (2,),
                cache_dir,
                now,
                DailyRequestBudget(),
                ("RB",),
                timedelta(hours=2),
                timedelta(hours=2),
                timedelta(hours=2),
            )

        default_hits = {row.name for row in default_plan.calls if row.fresh_cache_hit}
        waiver_hits = {row.name for row in waiver_plan.calls if row.fresh_cache_hit}
        self.assertTrue(
            {"rankings_rb", "ros_rankings_rb", "ros_experts"}.issubset(default_hits)
        )
        self.assertFalse(
            {"rankings_rb", "ros_rankings_rb", "ros_experts"} & waiver_hits
        )

    def test_waiver_special_team_plan_adds_weekly_k_dst_and_week_one_dst_ros(self):
        with tempfile.TemporaryDirectory() as directory:
            plan, _, cached = _input_calls(
                2026,
                1,
                (1, 2, 3),
                Path(directory),
                datetime(2026, 9, 10, tzinfo=timezone.utc),
                DailyRequestBudget(),
                ("QB", "RB", "WR", "TE", "K", "DST"),
            )
        names = {row.name for row in plan.calls}
        self.assertEqual(cached, {})
        self.assertTrue({"rankings_k", "rankings_dst", "ros_rankings_dst"}.issubset(names))
        self.assertNotIn("ros_rankings_k", names)
        self.assertEqual(
            len([name for name in names if name.startswith("projections_")]), 3
        )

    def test_league_beta_specialist_scoring_is_position_scoped(self) -> None:
        capability = classify_trade_scoring(
            {
                "rec": 0.5,
                "pass_td": 4,
                "blk_kick": 2,
                "ff": 1,
                "fgm_50_59": 5,
                "fgm_60p": 6,
                "st_ff": 1,
                "st_fum_rec": 1,
                "fum_rec": 2,
                "fum_rec_td": 6,
            }
        )

        self.assertEqual(capability.unsupported_settings, ())
        self.assertEqual(
            set(capability.supported_skill_settings), {"pass_td", "rec"}
        )
        self.assertEqual(
            {setting for setting, _ in capability.out_of_scope_settings},
            {
                "blk_kick",
                "ff",
                "fgm_50_59",
                "fgm_60p",
                "st_ff",
                "st_fum_rec",
            },
        )
        self.assertEqual(
            {setting for setting, _ in capability.projection_limited_settings},
            {"fum_rec", "fum_rec_td"},
        )

    def test_unknown_skill_scoring_stops_before_paid_retrieval(self) -> None:
        refresh = SimpleNamespace(
            snapshot=SimpleNamespace(
                league=SimpleNamespace(
                    scoring=(("rec", 0.5), ("bonus_unknown_skill", 2.0))
                )
            )
        )
        with tempfile.TemporaryDirectory() as directory:
            budget_path = Path(directory) / "budget.json"
            budget_path.write_text('{"budget_date":"2026-09-08","limit":500,"used":21}', encoding="utf-8")
            before = budget_path.read_bytes()
            with (
                patch(
                    "roster_theory.trade.board_service.refresh_trade_snapshot",
                    return_value=refresh,
                ),
                patch(
                    "roster_theory.trade.board_service._fetch_value_inputs"
                ) as fetch_inputs,
            ):
                with self.assertRaisesRegex(
                    UnsupportedScoring, "bonus_unknown_skill"
                ):
                    refresh_value_boards("fixture", budget_path=budget_path)

            fetch_inputs.assert_not_called()
            self.assertEqual(budget_path.read_bytes(), before)

    def test_draft_anchor_resolution_is_league_scoped(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            board = root / "league_beta_board.csv"
            board.write_text("scope,scoring\nskills_half_ppr,HALF\n", encoding="utf-8")
            metadata = root / "league_beta_metadata.json"
            metadata.write_text(
                json.dumps(
                    {
                        "league_key": "league_beta",
                        "league_id": "league-league_beta",
                        "generated_at": "2026-09-07T10:17:12-07:00",
                    }
                ),
                encoding="utf-8",
            )

            resolved, updated_at = resolve_draft_anchor(
                "league_beta", "league-league_beta", path=board
            )
            self.assertEqual(resolved, board)
            self.assertEqual(updated_at, "2026-09-07T10:17:12-07:00")

            metadata.write_text(
                json.dumps(
                    {
                        "league_key": "league_alpha",
                        "league_id": "league-fourth",
                        "generated_at": "2026-09-07T10:02:21-07:00",
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(CoverageIncomplete, "wrong league key"):
                resolve_draft_anchor("league_beta", "league-league_beta", path=board)

    def setUp(self) -> None:
        self.market = tuple(rank(f"p{number}", number) for number in range(1, 11))
        self.ballots = tuple(
            [rank(f"p{number}", 11 - number, expert_id="a") for number in range(1, 11)]
            + [rank(f"p{number}", number, expert_id="b") for number in range(1, 11)]
        )
        self.positions = {f"p{number}": "RB" for number in range(1, 11)}
        self.projections = tuple(
            Projection(
                player_id=f"p{number}",
                horizon="WEEKLY",
                week=1,
                raw_stats=(("points", float(250 - number * 10)),),
                league_points=float(250 - number * 10),
                source="FantasyPros consensus",
            )
            for number in range(1, 11)
        )

    def test_provider_retains_raw_contributor_ballots(self) -> None:
        value = {
            "ranking_type_name": "weekly",
            "week": 1,
            "scoring": "HALF",
            "last_updated": "9/04",
            "expert_names": {"a": "Alpha", "b": "Beta"},
            "players": [
                {"player_id": 1, "player_name": "One", "player_position_id": "RB", "pos_rank": "RB1", "rank_ecr": 1, "experts": {"a": "2", "b": "1"}}
            ],
        }
        dataset = normalize_rankings(value, requested_horizon="WEEKLY", board_source="market")
        self.assertEqual(dataset.contributor_ids, ("a", "b"))
        self.assertEqual(
            [(row.expert_id, row.position_rank) for row in dataset.contributor_observations],
            [("a", 2.0), ("b", 1.0)],
        )

    def test_cross_provider_numeric_ids_do_not_create_false_exact_match(self) -> None:
        sleepers = (
            Player("100", "Wrong", ("RB",), external_ids=(("sportradar", "wrong"),)),
            Player("200", "Right", ("RB",), external_ids=(("sportradar", "shared"),)),
        )
        fantasypros = (
            FantasyProsIdentity(
                "100", "Right", "RB", "X", (("sportradar", "shared"),)
            ),
        )
        mapping, matches = _identity_map(sleepers, fantasypros)
        self.assertEqual(matches, 1)
        self.assertEqual(mapping, {"100": "200"})

    def test_dst_identity_uses_unique_normalized_team_when_ids_are_unshared(self) -> None:
        sleepers = (
            Player("TB", "Tampa Bay Buccaneers", ("DEF",), nfl_team="TB"),
            Player("SF", "San Francisco 49ers", ("DEF",), nfl_team="SF"),
            Player("JAX", "Jacksonville Jaguars", ("DEF",), nfl_team="JAX"),
        )
        fantasypros = (
            FantasyProsIdentity("8270", "Tampa Bay Buccaneers", "DST", "TB", ()),
            FantasyProsIdentity("8290", "San Francisco 49ers", "DST", "SF", ()),
            FantasyProsIdentity("8140", "Jacksonville Jaguars", "DST", "JAC", ()),
        )

        mapping, matches = _identity_map(sleepers, fantasypros)

        self.assertEqual(matches, 3)
        self.assertEqual(mapping, {"8140": "JAX", "8270": "TB", "8290": "SF"})

    def test_dst_team_fallback_fails_closed_when_sleeper_team_is_ambiguous(self) -> None:
        sleepers = (
            Player("TB", "Tampa Bay Buccaneers", ("DEF",), nfl_team="TB"),
            Player("TB-duplicate", "Duplicate Defense", ("DST",), nfl_team="TB"),
        )
        fantasypros = (
            FantasyProsIdentity("8270", "Tampa Bay Buccaneers", "DST", "TB", ()),
        )

        with self.assertRaises(IdentityIncomplete):
            _identity_map(sleepers, fantasypros)

    def test_team_fallback_never_maps_individual_player_or_mismatched_dst(self) -> None:
        sleepers = (
            Player("rb", "Runner", ("RB",), nfl_team="TB"),
            Player("SF", "San Francisco 49ers", ("DEF",), nfl_team="SF"),
        )
        fantasypros = (
            FantasyProsIdentity("100", "Runner", "RB", "TB", ()),
            FantasyProsIdentity("8270", "Tampa Bay Buccaneers", "DST", "TB", ()),
        )

        mapping, matches = _identity_map(sleepers, fantasypros)

        self.assertEqual(matches, 0)
        self.assertEqual(mapping, {})

    def test_trade_values_cli_is_namespaced_and_read_only(self) -> None:
        args = build_parser().parse_args(["trade", "values", "league_alpha"])
        self.assertEqual(args.trade_command, "values")
        self.assertIsNone(args.expert_pool)

    def test_selected_aggregation_preserves_raw_and_missing_weight_anchor(self) -> None:
        ballots = tuple(row for row in self.ballots if not (row.expert_id == "b" and row.player_id == "p1"))
        selected = aggregate_selected_ranks(
            self.market, ballots, {"a": 0.6, "b": 0.4}, horizon="WEEKLY-PROXY"
        )
        first = next(row for row in selected if row.player_id == "p1")
        self.assertEqual(first.raw_position_rank, 10.0)
        self.assertAlmostEqual(first.contributor_weight, 0.6)
        self.assertAlmostEqual(first.shrinkage_to_ecr, 0.4)
        self.assertEqual(first.omissions, (("b", "missing_player_ballot"),))

    def test_horizon_mismatch_stops(self) -> None:
        bad = (rank("p1", 1, horizon="ROS"), *self.market[1:])
        with self.assertRaises(CoverageIncomplete):
            aggregate_selected_ranks(
                bad, self.ballots, {"a": 1.0}, horizon="WEEKLY-PROXY"
            )

    def test_weekly_projection_curve_requires_complete_week_coverage(self) -> None:
        with self.assertRaises(CoverageIncomplete):
            build_projection_curves(
                self.projections,
                self.positions,
                required_counts={"RB": 10},
                expected_weeks=(1, 2),
            )

    def test_rb10_rank_slot_transfer_and_raw_projection_are_both_preserved(self) -> None:
        curves = build_projection_curves(
            self.projections,
            self.positions,
            required_counts={"RB": 10},
            expected_weeks=(1,),
        )
        selected_ranks = {f"p{number}": 11 - number for number in range(1, 11)}
        board = build_value_board(
            board_id="selected_final",
            horizon="WEEKLY-PROXY",
            position_ranks=selected_ranks,
            positions=self.positions,
            curves=curves,
            replacement_baselines={"RB": 100.0},
        )
        joe = next(row for row in board.players if row.player_id == "p1")
        self.assertEqual(joe.position_rank, 10)
        self.assertEqual(joe.aligned_points, 150.0)
        self.assertEqual(joe.raw_projection, 240.0)
        self.assertEqual(joe.raw_projection_rank, 1)

    def test_boards_share_distribution_and_baseline_but_not_identity_order(self) -> None:
        curves = build_projection_curves(self.projections, self.positions, required_counts={"RB": 10}, expected_weeks=(1,))
        selected = build_value_board(
            board_id="selected_final",
            horizon="WEEKLY-PROXY",
            position_ranks={f"p{number}": 11 - number for number in range(1, 11)},
            positions=self.positions,
            curves=curves,
            replacement_baselines={"RB": 100.0},
        )
        market = build_value_board(
            board_id="market",
            horizon="WEEKLY-PROXY",
            position_ranks={f"p{number}": number for number in range(1, 11)},
            positions=self.positions,
            curves=curves,
            replacement_baselines={"RB": 100.0},
        )
        self.assertEqual(selected.curves, market.curves)
        self.assertEqual(selected.replacement_baselines, market.replacement_baselines)
        gaps = valuation_gaps(selected, market)
        p1 = next(row for row in gaps if row.player_id == "p1")
        p10 = next(row for row in gaps if row.player_id == "p10")
        self.assertEqual(p1.signal, "SELL-HIGH")
        self.assertGreater(p1.value_gap, 0)
        self.assertEqual(p10.signal, "BUY-LOW")
        self.assertLess(p10.value_gap, 0)

    def test_gap_report_never_claims_an_opponent_preference(self) -> None:
        curves = build_projection_curves(
            self.projections,
            self.positions,
            required_counts={"RB": 10},
            expected_weeks=(1,),
        )
        selected = build_value_board(
            board_id="selected_final",
            horizon="WEEKLY-PROXY",
            position_ranks={f"p{number}": 11 - number for number in range(1, 11)},
            positions=self.positions,
            curves=curves,
            replacement_baselines={"RB": 100.0},
        )
        market = build_value_board(
            board_id="market",
            horizon="WEEKLY-PROXY",
            position_ranks={f"p{number}": number for number in range(1, 11)},
            positions=self.positions,
            curves=curves,
            replacement_baselines={"RB": 100.0},
        )
        snapshot = SimpleNamespace(
            league_key="fixture",
            players=tuple(
                Player(f"p{number}", f"Player {number}", ("RB",))
                for number in range(1, 11)
            ),
            owner_by_player=tuple(
                (f"p{number}", "1" if number <= 5 else "2")
                for number in range(1, 11)
            ),
        )
        result = SimpleNamespace(
            gaps=valuation_gaps(selected, market),
            refresh=SimpleNamespace(snapshot=snapshot),
            selected_final=selected,
            market=market,
            stage=choose_season_stage(1),
            horizon_views=(),
            prospective_snapshot_path=Path("prospective.json"),
            call_plan=SimpleNamespace(
                calls=(),
                fantasypros_calls=0,
                cache_hits=0,
                fantasypros_remaining_after_plan=500,
            ),
            output_path=Path("boards.json"),
            required_players=10,
            identity_matches=10,
        )
        with patch(
            "roster_theory.trade.board_service.load_expert_pool",
            return_value=(),
        ):
            report = board_refresh_report(result)

        self.assertFalse(report["opponent_preference_claimed"])
        self.assertFalse(report["recommendation_generated"])
        self.assertFalse(report["sleeper_write_performed"])

    def test_monotone_curve_pools_inversions(self) -> None:
        curve = fit_nonincreasing_curve(((1, 10), (2, 5), (3, 8), (4, 2)))
        values = [curve.value(rank) for rank in range(1, 5)]
        self.assertEqual(values, sorted(values, reverse=True))
        self.assertLess(curve.block_count, curve.observation_count)

    def test_missing_fixed_universe_member_stops_board(self) -> None:
        curves = build_projection_curves(self.projections, self.positions, required_counts={"RB": 10}, expected_weeks=(1,))
        with self.assertRaises(CoverageIncomplete):
            build_value_board(
                board_id="market",
                horizon="WEEKLY-PROXY",
                position_ranks={f"p{number}": number for number in range(1, 10)},
                positions=self.positions,
                curves=curves,
                replacement_baselines={"RB": 100.0},
            )

    def test_export_is_manifest_linked_and_deterministic(self) -> None:
        curves = build_projection_curves(self.projections, self.positions, required_counts={"RB": 10}, expected_weeks=(1,))
        ranks = aggregate_selected_ranks(self.market, self.ballots, {"a": 0.6, "b": 0.4}, horizon="WEEKLY-PROXY")
        selected = build_value_board(
            board_id="selected_final", horizon="WEEKLY-PROXY",
            position_ranks={row.player_id: row.final_position_rank for row in ranks},
            positions=self.positions, curves=curves, replacement_baselines={"RB": 100.0},
        )
        market = build_value_board(
            board_id="market", horizon="WEEKLY-PROXY",
            position_ranks={f"p{number}": number for number in range(1, 11)},
            positions=self.positions, curves=curves, replacement_baselines={"RB": 100.0},
        )
        with tempfile.TemporaryDirectory() as directory:
            first = Path(directory) / "first.json"
            second = Path(directory) / "second.json"
            export_board_evidence(first, selected_ranks=ranks, selected_raw=None, selected=selected, market=market, gaps=valuation_gaps(selected, market), manifest_id="manifest")
            export_board_evidence(second, selected_ranks=ranks, selected_raw=None, selected=selected, market=market, gaps=valuation_gaps(selected, market), manifest_id="manifest")
            one = json.loads(first.read_text(encoding="utf-8"))
            two = json.loads(second.read_text(encoding="utf-8"))
            self.assertEqual(one["evidence_hash"], two["evidence_hash"])
            self.assertEqual(one["manifest_id"], "manifest")


if __name__ == "__main__":
    unittest.main()
