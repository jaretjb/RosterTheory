from __future__ import annotations

import unittest
import json
import tempfile
from dataclasses import asdict, replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from roster_theory.cli import build_parser
from roster_theory.core.models import FantasyTeam, Player, Projection
from roster_theory.trade.boards import valuation_gaps
from roster_theory.trade.evaluation import PlayerAsset, TradePackage, evaluate_trade
from roster_theory.trade.search import (
    LARGE_PACKAGE_SIZES,
    SMALL_PACKAGE_SIZES,
    SearchConfig,
    _candidate_pool,
    _diagnosis_maps,
    enumerate_candidate_packages,
    search_league,
)
from roster_theory.trade.search_service import (
    _gap_report,
    format_search_result,
    load_search_evidence,
)
from tests.test_trade_evaluation import board_fixture, projection_fixture, snapshot_fixture


class CandidateEnumerationTests(unittest.TestCase):
    def test_near_waiver_starter_can_seed_a_construction_need(self) -> None:
        diagnosis = SimpleNamespace(
            positions=(
                SimpleNamespace(
                    position="TE",
                    need_above_waiver=0.0,
                    weakest_starter_average_points=7.1,
                    waiver_average_points=6.8,
                    usable_surplus_player_ids=(),
                ),
            )
        )

        strict_needs, _ = _diagnosis_maps(diagnosis)
        construction_needs, _ = _diagnosis_maps(diagnosis, 1.0)

        self.assertEqual(strict_needs, set())
        self.assertEqual(construction_needs, {"TE"})

    def test_bounded_pool_keeps_one_fringe_asset_per_skill_position(self) -> None:
        snapshot = snapshot_fixture()
        diagnosis = SimpleNamespace(
            positions=tuple(
                SimpleNamespace(
                    position=position,
                    need_above_waiver=0.0,
                    usable_surplus_player_ids=(),
                )
                for position in ("QB", "RB", "WR", "TE")
            )
        )
        selected_values = {
            "a_rb": 100.0,
            "a_wr": 90.0,
            "a_bench": 10.0,
            "a_low": 5.0,
        }

        pool = _candidate_pool(
            snapshot,
            snapshot.user_roster_id,
            diagnosis,
            selected_values,
            4,
        )

        eligible_positions = {
            position
            for player_id in pool
            for position in next(
                player.positions
                for player in snapshot.players
                if player.player_id == player_id
            )
        }
        roster_positions = {
            position
            for player in snapshot.players
            if player.player_id in snapshot.teams[0].player_ids
            for position in player.positions
        }
        self.assertEqual(eligible_positions, roster_positions)

    def test_enumeration_is_unique_owned_and_supports_four_player_sides(self) -> None:
        packages = enumerate_candidate_packages(
            "1",
            "2",
            ("a_rb", "a_wr", "a_bench", "a_low"),
            ("b_rb", "b_wr", "b_bench", "b_low"),
            (*SMALL_PACKAGE_SIZES, *LARGE_PACKAGE_SIZES),
        )
        keys = {
            (
                tuple(asset.player_id for asset in row.from_a),
                tuple(asset.player_id for asset in row.from_b),
            )
            for row in packages
        }
        self.assertEqual(len(keys), len(packages))
        self.assertTrue(any(len(row.from_a) == 4 for row in packages))
        self.assertTrue(any(len(row.from_b) == 4 for row in packages))
        self.assertTrue(
            all(
                {asset.player_id for asset in row.from_a}
                <= {"a_rb", "a_wr", "a_bench", "a_low"}
                and {asset.player_id for asset in row.from_b}
                <= {"b_rb", "b_wr", "b_bench", "b_low"}
                for row in packages
            )
        )


class LeagueSearchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.snapshot = snapshot_fixture()
        self.selected = board_fixture(self.snapshot, "selected_final")
        self.market = board_fixture(self.snapshot, "market")
        self.gaps = valuation_gaps(self.selected, self.market)

    def _search(self, config: SearchConfig):
        return search_league(
            self.snapshot,
            projections=projection_fixture(),
            selected_board=self.selected,
            market_board=self.market,
            gaps=self.gaps,
            config=config,
        )

    def test_safe_small_pruning_retains_controlled_exhaustive_frontier(self) -> None:
        exhaustive = self._search(
            SearchConfig(
                small_pool_per_team=4,
                large_pool_per_team=0,
                market_band_ratio=10.0,
                market_band_floor=100.0,
                bilateral_value_ratio=0.0,
                max_exact_per_opponent=10_000,
                max_large_exact_per_opponent=0,
                max_results=100,
            )
        )
        pruned = self._search(
            SearchConfig(
                small_pool_per_team=4,
                large_pool_per_team=0,
                max_exact_per_opponent=36,
                max_large_exact_per_opponent=0,
                max_results=100,
            )
        )
        key = lambda result: {
            (row.sent_player_ids, row.received_player_ids)
            for row in result.opportunities
        }
        self.assertEqual(key(pruned), key(exhaustive))
        self.assertTrue(any(row.pruned for row in pruned.coverage))
        self.assertTrue(
            all(row.enumerated == row.pruned + row.evaluated for row in pruned.coverage)
        )

    def test_results_are_bilateral_deterministic_and_auditable(self) -> None:
        config = SearchConfig(
            small_pool_per_team=4,
            large_pool_per_team=4,
            max_exact_per_opponent=40,
            max_large_exact_per_opponent=20,
            max_results=20,
            target_market_value_floor=-1_000.0,
            target_raw_projection_floor=-1_000.0,
            target_material_gap_floor=-1_000.0,
            reject_received_asset_drop=False,
        )
        first = self._search(config)
        second = self._search(config)
        self.assertEqual(first.evidence_hash, second.evidence_hash)
        self.assertFalse(first.exhaustive_large_search)
        self.assertTrue(first.opportunities)
        for row in first.opportunities:
            self.assertGreater(row.user_lineup_delta, 0.0)
            self.assertEqual(row.evaluation.decision_label, "ACCEPTABLE")
            self.assertTrue(
                row.partner_lineup_delta >= -config.max_partner_lineup_loss
                or row.partner_market_delta > 0.0
            )
            self.assertTrue(row.partner_rationale)
            self.assertTrue(row.objective_tags)
        coverage = {row.package_size: row for row in first.coverage}
        self.assertGreater(coverage["3-for-2"].evaluated, 0)
        self.assertGreater(coverage["1-for-4"].enumerated, 0)

    def test_candidate_enumeration_visits_every_opponent_roster(self) -> None:
        clone_ids = {
            "b_rb": "c_rb",
            "b_wr": "c_wr",
            "b_bench": "c_bench",
            "b_low": "c_low",
        }
        cloned_players = tuple(
            replace(
                player,
                player_id=clone_ids[player.player_id],
                name=player.name.replace("Bravo", "Charlie"),
                sleeper_id=clone_ids[player.player_id],
            )
            for player in self.snapshot.players
            if player.player_id in clone_ids
        )
        third_team = FantasyTeam(
            "3",
            "u3",
            "Second Partner",
            tuple(clone_ids[player_id] for player_id in self.snapshot.teams[1].player_ids),
        )
        snapshot = replace(
            self.snapshot,
            league=replace(self.snapshot.league, team_count=3),
            teams=(*self.snapshot.teams, third_team),
            players=(*self.snapshot.players, *cloned_players),
            owner_by_player=tuple(
                sorted(
                    (
                        *self.snapshot.owner_by_player,
                        *((player_id, "3") for player_id in third_team.player_ids),
                    )
                )
            ),
            tradeable_player_ids=(
                *self.snapshot.tradeable_player_ids,
                *third_team.player_ids,
            ),
        )
        projections = (
            *projection_fixture(),
            *(
                replace(row, player_id=clone_ids[row.player_id])
                for row in projection_fixture()
                if row.player_id in clone_ids
            ),
        )

        def extend_board(board):
            return replace(
                board,
                players=(
                    *board.players,
                    *(
                        replace(row, player_id=clone_ids[row.player_id])
                        for row in board.players
                        if row.player_id in clone_ids
                    ),
                ),
            )

        selected = extend_board(self.selected)
        market = extend_board(self.market)
        with patch(
            "roster_theory.trade.search.enumerate_candidate_packages",
            wraps=enumerate_candidate_packages,
        ) as enumerator:
            result = search_league(
                snapshot,
                projections=projections,
                selected_board=selected,
                market_board=market,
                gaps=valuation_gaps(selected, market),
                config=SearchConfig(
                    small_pool_per_team=4,
                    large_pool_per_team=0,
                    max_exact_per_opponent=0,
                    max_large_exact_per_opponent=0,
                ),
            )

        self.assertEqual(
            {call.args[1] for call in enumerator.call_args_list},
            {"2", "3"},
        )
        self.assertEqual(
            {diagnosis.roster_id for diagnosis in result.diagnostics},
            {"1", "2", "3"},
        )

    def test_league_beta_shape_covers_two_flex_and_all_eleven_opponents(self) -> None:
        base = self.snapshot
        players = []
        teams = []
        ownership = []
        points = {}
        position_points = {
            "QB": (20.0,),
            "RB": (15.0, 14.0, 13.0, 12.0),
            "WR": (14.0, 13.0, 12.0, 11.0, 10.0),
            "TE": (9.0, 8.0, 7.0),
        }
        for roster_number in range(1, 13):
            roster_id = str(roster_number)
            player_ids = []
            for position, values in position_points.items():
                for index, value in enumerate(values, 1):
                    player_id = f"t{roster_id}_{position.lower()}{index}"
                    players.append(
                        Player(
                            player_id,
                            f"Team {roster_id} {position} {index}",
                            (position,),
                            sleeper_id=player_id,
                            nfl_team=f"N{roster_number:02d}",
                            active=True,
                            identity_confidence="exact",
                        )
                    )
                    points[player_id] = value
                    player_ids.append(player_id)
                    ownership.append((player_id, roster_id))
            for specialist in ("k", "dst"):
                player_id = f"t{roster_id}_{specialist}"
                player_ids.append(player_id)
                ownership.append((player_id, roster_id))
            teams.append(
                FantasyTeam(
                    roster_id,
                    f"u{roster_id}",
                    f"Team {roster_id}",
                    tuple(player_ids),
                )
            )
        free_agent_ids = []
        for position, value in (("QB", 10.0), ("RB", 5.0), ("WR", 5.0), ("TE", 4.0)):
            player_id = f"fa_{position.lower()}"
            players.append(
                Player(
                    player_id,
                    f"Free {position}",
                    (position,),
                    sleeper_id=player_id,
                    nfl_team="NFA",
                    active=True,
                    identity_confidence="exact",
                )
            )
            points[player_id] = value
            free_agent_ids.append(player_id)
        weeks = tuple(
            replace(
                base.weeks[0],
                week=week,
                playoff=week >= 15,
                fantasy_matchup_rows=12,
            )
            for week in range(1, 18)
        )
        snapshot = replace(
            base,
            league_key="league_beta-fixture",
            league=replace(
                base.league,
                team_count=12,
                roster_positions=(
                    "QB",
                    "RB",
                    "RB",
                    "WR",
                    "WR",
                    "TE",
                    "FLEX",
                    "FLEX",
                    "K",
                    "DEF",
                    "BN",
                    "BN",
                    "BN",
                    "BN",
                    "BN",
                ),
                playoff_start_week=15,
                championship_week=17,
                reserve_slots=1,
            ),
            user_roster_id="11",
            teams=tuple(teams),
            players=tuple(players),
            weeks=weeks,
            owner_by_player=tuple(sorted(ownership)),
            free_agent_ids=tuple(free_agent_ids),
            tradeable_player_ids=tuple(player.player_id for player in players),
        )
        projections = tuple(
            Projection(player_id, "WEEKLY", week, (), value, "fixture")
            for player_id, value in points.items()
            for week in range(1, 18)
        )
        selected = board_fixture(snapshot, "selected_final", points)
        market = board_fixture(snapshot, "market", points)
        with patch(
            "roster_theory.trade.search.enumerate_candidate_packages",
            wraps=enumerate_candidate_packages,
        ) as enumerator:
            result = search_league(
                snapshot,
                projections=projections,
                selected_board=selected,
                market_board=market,
                gaps=valuation_gaps(selected, market),
                config=SearchConfig(
                    small_pool_per_team=4,
                    large_pool_per_team=0,
                    max_exact_per_opponent=0,
                    max_large_exact_per_opponent=0,
                ),
            )

        self.assertEqual(len(snapshot.teams), 12)
        self.assertEqual(len(snapshot.owner_by_player), 180)
        self.assertEqual(
            {call.args[1] for call in enumerator.call_args_list},
            {str(number) for number in range(1, 13)} - {"11"},
        )
        self.assertEqual(len(result.diagnostics), 12)
        user = next(row for row in result.diagnostics if row.roster_id == "11")
        self.assertEqual(len(user.weekly_optimal_points), 17)
        self.assertTrue(
            all(points == 110.0 for _, points in user.weekly_optimal_points)
        )
        unequal = evaluate_trade(
            snapshot,
            TradePackage(
                "11",
                "1",
                (PlayerAsset("t11_rb1"), PlayerAsset("t11_rb2")),
                (PlayerAsset("t1_wr5"),),
            ),
            projections=projections,
            selected_board=selected,
            market_board=market,
        )
        moves = {move.roster_id: move for move in unequal.secondary_moves}
        self.assertEqual(moves["11"].kind, "ADD")
        self.assertEqual(moves["1"].kind, "DROP")
        specialist_ids = {
            player_id
            for team in snapshot.teams
            for player_id in team.player_ids
            if player_id.endswith(("_k", "_dst"))
        }
        self.assertTrue(
            all(
                not (set(move.chosen_player_ids) & specialist_ids)
                for move in unequal.secondary_moves
            )
        )
        incoming = {
            "11": {"t1_wr5"},
            "1": {"t11_rb1", "t11_rb2"},
        }
        self.assertTrue(
            all(
                not (
                    move.kind == "DROP"
                    and set(move.chosen_player_ids) & incoming[move.roster_id]
                )
                for move in unequal.secondary_moves
            )
        )

    def test_four_player_side_can_survive_as_distinct_frontier_alternative(self) -> None:
        snapshot = replace(
            self.snapshot,
            league=replace(
                self.snapshot.league,
                roster_positions=("RB", "WR", "FLEX", "FLEX"),
            ),
        )
        points = {
            "a_rb": 0.0,
            "a_wr": 15.0,
            "a_bench": 0.0,
            "a_low": 0.0,
            "b_rb": 8.0,
            "b_wr": 8.0,
            "b_bench": 8.0,
            "b_low": 8.0,
            "fa_rb": 1.0,
            "fa_wr": 1.0,
            "twin_1": 0.0,
            "twin_2": 0.0,
        }
        projections = tuple(
            Projection(player_id, "WEEKLY", week, (), value, "fixture")
            for player_id, value in points.items()
            for week in (1, 2, 3)
        )
        selected_values = {
            **points,
            "a_wr": 40.0,
            "b_rb": 12.0,
            "b_wr": 11.0,
            "b_bench": 11.0,
            "b_low": 11.0,
        }
        market_values = {**points, "a_wr": 40.0}
        selected_base = board_fixture(snapshot, "selected_final", points)
        market_base = board_fixture(snapshot, "market", points)
        selected = replace(
            selected_base,
            players=tuple(
                replace(
                    row,
                    positional_vorp=selected_values[row.player_id],
                    reconciled_vorp=selected_values[row.player_id],
                )
                for row in selected_base.players
            ),
        )
        market = replace(
            market_base,
            players=tuple(
                replace(
                    row,
                    positional_vorp=market_values[row.player_id],
                    reconciled_vorp=market_values[row.player_id],
                )
                for row in market_base.players
            ),
        )
        result = search_league(
            snapshot,
            projections=projections,
            selected_board=selected,
            market_board=market,
            gaps=valuation_gaps(selected, market),
            config=SearchConfig(
                small_pool_per_team=4,
                large_pool_per_team=4,
                market_band_ratio=10.0,
                market_band_floor=100.0,
                bilateral_value_ratio=0.0,
                max_exact_per_opponent=10_000,
                max_large_exact_per_opponent=10_000,
                max_results=100,
                target_market_value_floor=-1_000.0,
                target_raw_projection_floor=-1_000.0,
                target_material_gap_floor=-1_000.0,
                reject_received_asset_drop=False,
            ),
        )
        self.assertTrue(
            any(
                len(row.sent_player_ids) == 4 or len(row.received_player_ids) == 4
                for row in result.opportunities
            )
        )

    def test_gap_report_includes_owner_and_sign_convention(self) -> None:
        refresh = SimpleNamespace(
            refresh=SimpleNamespace(snapshot=self.snapshot),
            gaps=self.gaps,
        )
        report = _gap_report(refresh)
        by_id = {row.player_id: row for row in report.rows}
        self.assertEqual(by_id["a_wr"].ownership, "USER")
        self.assertEqual(by_id["b_rb"].ownership, "OPPONENT")
        self.assertEqual(by_id["fa_wr"].ownership, "WAIVER")
        self.assertEqual(by_id["a_wr"].signal, "BUY-LOW")
        self.assertEqual(by_id["b_rb"].signal, "SELL-HIGH")

    def test_user_sell_high_can_return_a_partner_credible_target(self) -> None:
        selected = replace(
            self.selected,
            players=tuple(
                replace(row, positional_vorp=5.0, reconciled_vorp=5.0)
                if row.player_id == "a_rb"
                else row
                for row in self.selected.players
            ),
        )
        gaps = valuation_gaps(selected, self.market)
        self.assertEqual(
            next(row.signal for row in gaps if row.player_id == "a_rb"),
            "SELL-HIGH",
        )

        result = search_league(
            self.snapshot,
            projections=projection_fixture(),
            selected_board=selected,
            market_board=self.market,
            gaps=gaps,
            config=SearchConfig(
                small_pool_per_team=4,
                large_pool_per_team=0,
                max_exact_per_opponent=100,
                max_large_exact_per_opponent=0,
                max_results=100,
                near_waiver_need_margin=0.0,
            ),
        )
        target = next(
            row
            for row in result.opportunities
            if row.sent_player_ids == ("a_rb",)
            and row.received_player_ids == ("b_wr",)
        )
        self.assertEqual(target.user_rationale, "exploits a material selected-versus-market gap")
        self.assertEqual(
            target.partner_rationale,
            "keeps the partner's market-value return within the policy floor",
        )
        self.assertGreater(target.user_lineup_delta, 0.0)
        self.assertGreaterEqual(target.user_selected_delta, 0.0)
        self.assertGreaterEqual(target.user_market_delta, 0.0)
        self.assertGreaterEqual(target.user_raw_projection_delta, 0.0)

    def test_search_config_rejects_invalid_limits(self) -> None:
        with self.assertRaises(ValueError):
            SearchConfig(small_pool_per_team=2, large_pool_per_team=3)
        with self.assertRaises(ValueError):
            SearchConfig(max_exact_per_opponent=-1)
        with self.assertRaises(ValueError):
            SearchConfig(near_waiver_need_margin=-0.1)

    def test_received_asset_immediately_dropped_is_not_a_search_result(self) -> None:
        result = self._search(
            SearchConfig(
                small_pool_per_team=4,
                large_pool_per_team=4,
                market_band_ratio=10.0,
                market_band_floor=100.0,
                bilateral_value_ratio=0.0,
                max_exact_per_opponent=10_000,
                max_large_exact_per_opponent=10_000,
                max_results=100,
                target_market_value_floor=-1_000.0,
                target_raw_projection_floor=-1_000.0,
                target_material_gap_floor=-1_000.0,
            )
        )
        rejections = dict(result.rejection_counts)
        self.assertGreater(rejections["received_asset_immediately_dropped"], 0)
        for opportunity in result.opportunities:
            incoming = {
                opportunity.evaluation.package.roster_a_id: {
                    row.player_id for row in opportunity.evaluation.package.from_b
                },
                opportunity.evaluation.package.roster_b_id: {
                    row.player_id for row in opportunity.evaluation.package.from_a
                },
            }
            self.assertTrue(
                all(
                    not (
                        move.kind == "DROP"
                        and set(move.chosen_player_ids) & incoming[move.roster_id]
                    )
                    for move in opportunity.evaluation.secondary_moves
                )
            )

    def test_automatic_targets_require_cross_model_value_agreement(self) -> None:
        market = replace(
            self.market,
            players=tuple(
                replace(row, positional_vorp=8.0, reconciled_vorp=8.0)
                if row.player_id == "b_wr"
                else row
                for row in self.market.players
            ),
        )

        def run(config: SearchConfig):
            return search_league(
                self.snapshot,
                projections=projection_fixture(),
                selected_board=self.selected,
                market_board=market,
                gaps=valuation_gaps(self.selected, market),
                config=config,
            )

        permissive = run(
            SearchConfig(
                small_pool_per_team=4,
                large_pool_per_team=0,
                max_exact_per_opponent=100,
                max_large_exact_per_opponent=0,
                max_results=100,
                target_market_value_floor=-1_000.0,
                target_raw_projection_floor=-1_000.0,
                target_material_gap_floor=-1_000.0,
                reject_received_asset_drop=False,
            )
        )
        strict = run(
            SearchConfig(
                small_pool_per_team=4,
                large_pool_per_team=0,
                max_exact_per_opponent=100,
                max_large_exact_per_opponent=0,
                max_results=100,
                target_material_gap_floor=-1_000.0,
                reject_received_asset_drop=False,
            )
        )
        self.assertTrue(permissive.opportunities)
        self.assertLess(len(strict.opportunities), len(permissive.opportunities))
        self.assertTrue(
            all(
                row.user_selected_delta >= 0.0
                and row.user_market_delta >= 0.0
                and row.user_raw_projection_delta >= 0.0
                and row.label == "TARGET"
                for row in strict.opportunities
            )
        )
        self.assertTrue(
            {
                "target_market_value_gate",
                "target_raw_projection_gate",
                "target_market_and_raw_projection_gates",
            }
            & set(dict(strict.rejection_counts))
        )

    def test_saved_search_evidence_replays_and_rejects_tampering(self) -> None:
        result = self._search(
            SearchConfig(
                small_pool_per_team=4,
                large_pool_per_team=0,
                max_exact_per_opponent=2,
                max_large_exact_per_opponent=0,
            )
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "search.json"
            path.write_text(json.dumps(asdict(result)), encoding="utf-8")
            self.assertEqual(
                load_search_evidence(path)["replay_mode"], "OFFLINE/NON-CURRENT"
            )
            value = json.loads(path.read_text(encoding="utf-8"))
            value["league_key"] = "tampered"
            path.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "hash"):
                load_search_evidence(path)

    def test_compact_search_report_explains_policy_and_rejections(self) -> None:
        result = self._search(
            SearchConfig(
                small_pool_per_team=4,
                large_pool_per_team=0,
                max_exact_per_opponent=2,
                max_large_exact_per_opponent=0,
            )
        )
        formatted = format_search_result(
            SimpleNamespace(
                search=result,
                board_refresh=SimpleNamespace(
                    refresh=SimpleNamespace(snapshot=self.snapshot)
                ),
            )
        )
        self.assertIn("phase9-search-construction-v1", formatted)
        self.assertIn("Rejections:", formatted)


class SearchCliTests(unittest.TestCase):
    def test_phase_seven_commands_parse(self) -> None:
        parser = build_parser()
        gaps = parser.parse_args(["trade", "gaps", "fixture", "--csv", "gaps.csv"])
        search = parser.parse_args(["trade", "search", "fixture", "--max-results", "5"])
        compare = parser.parse_args(
            ["trade", "compare", "fixture", "--packages", "packages.json"]
        )
        self.assertEqual(gaps.func.__name__, "command_trade_gaps")
        self.assertEqual(search.max_results, 5)
        self.assertEqual(compare.func.__name__, "command_trade_compare")


if __name__ == "__main__":
    unittest.main()
