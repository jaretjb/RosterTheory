from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from roster_theory.cli import build_parser
from roster_theory.core.errors import CoverageIncomplete, IdentityIncomplete, RosterIllegal
from roster_theory.core.isotonic import MonotoneCurve
from roster_theory.core.models import FantasyTeam, LeagueRules, Player, Projection
from roster_theory.core.provenance import AnalysisManifest, DataStamp
from roster_theory.trade.boards import BoardPlayerValue, ValueBoard
from roster_theory.trade.evaluation import (
    EvaluationOptions,
    PlayerAsset,
    TradePackage,
    build_entered_package,
    build_weekly_projection_matrix,
    diagnose_roster,
    evaluate_trade,
    load_trade_evaluation,
    resolve_player,
    save_trade_evaluation,
)
from roster_theory.trade.evaluation_service import format_trade_evaluation
from roster_theory.trade.schedule import EvaluationWeek
from roster_theory.trade.snapshot import SnapshotCompleteness, TradeSnapshot


PLAYER_DATA = (
    ("a_rb", "Alpha Runner", "RB", "AAA"),
    ("a_wr", "Alpha Receiver", "WR", "AAA"),
    ("a_bench", "Alpha Bench", "RB", "BBB"),
    ("a_low", "Alpha Low", "WR", "BBB"),
    ("b_rb", "Bravo Runner", "RB", "CCC"),
    ("b_wr", "Bravo Receiver", "WR", "CCC"),
    ("b_bench", "Bravo Bench", "WR", "DDD"),
    ("b_low", "Bravo Low", "RB", "DDD"),
    ("fa_rb", "Free Runner", "RB", "EEE"),
    ("fa_wr", "Free Receiver", "WR", "FFF"),
    ("twin_1", "Same Name", "WR", "GGG"),
    ("twin_2", "Same Name", "WR", "HHH"),
)
POINTS = {
    "a_rb": 10.0,
    "a_wr": 8.0,
    "a_bench": 5.0,
    "a_low": 1.0,
    "b_rb": 6.0,
    "b_wr": 12.0,
    "b_bench": 4.0,
    "b_low": 2.0,
    "fa_rb": 3.0,
    "fa_wr": 7.0,
    "twin_1": 0.0,
    "twin_2": 0.0,
}


def snapshot_fixture() -> TradeSnapshot:
    now = datetime.now(timezone.utc)
    players = tuple(
        Player(
            player_id=player_id,
            name=name,
            positions=(position,),
            sleeper_id=player_id,
            nfl_team=team,
            active=True,
            identity_confidence="exact",
        )
        for player_id, name, position, team in PLAYER_DATA
    )
    teams = (
        FantasyTeam("1", "u1", "User", ("a_rb", "a_wr", "a_bench", "a_low")),
        FantasyTeam("2", "u2", "Partner", ("b_rb", "b_wr", "b_bench", "b_low")),
    )
    weeks = tuple(
        EvaluationWeek(
            week=week,
            playoff=week == 3,
            fantasy_matchup_rows=2,
            fantasy_matchups_complete=True,
            bye_teams=(),
            nfl_schedule_complete=True,
        )
        for week in (1, 2, 3)
    )
    stamp = DataStamp("fixture", "fixture://trade", now, fresh=True)
    manifest = AnalysisManifest.build(
        league_id="league",
        user_id="u1",
        current_week=1,
        horizon_start=1,
        horizon_end=3,
        configuration={"fixture": True},
        normalized_inputs=(players, teams, weeks),
        data_stamps=(stamp,),
    )
    return TradeSnapshot(
        schema_version=1,
        product="TRADE ASSISTANT",
        league_key="fixture",
        captured_at=now,
        ranking_horizon="EARLY_SEASON_DRAFT_ANCHOR",
        current=True,
        league=LeagueRules(
            "league",
            2026,
            2,
            ("RB", "WR", "FLEX", "BN"),
            (("rec", 0.5),),
            playoff_start_week=3,
            championship_week=3,
            reserve_slots=0,
        ),
        user_roster_id="1",
        teams=teams,
        players=players,
        weeks=weeks,
        owner_by_player=tuple(
            sorted(
                (*((player_id, "1") for player_id in teams[0].player_ids),
                 *((player_id, "2") for player_id in teams[1].player_ids))
            )
        ),
        free_agent_ids=tuple(
            player_id
            for player_id, *_ in PLAYER_DATA
            if player_id not in {*teams[0].player_ids, *teams[1].player_ids}
        ),
        tradeable_player_ids=tuple(player_id for player_id, *_ in PLAYER_DATA),
        transaction_ids=(),
        stamps=(stamp,),
        capabilities=(("valuation_inputs_loaded", True),),
        completeness=SnapshotCompleteness(True, True, True, True, True, True),
        warnings=(),
        manifest=manifest,
    )


def projection_fixture() -> tuple[Projection, ...]:
    return tuple(
        Projection(
            player_id=player_id,
            horizon="WEEKLY",
            week=week,
            raw_stats=(),
            league_points=points,
            source="fixture",
        )
        for player_id, points in POINTS.items()
        for week in (1, 2, 3)
    )


def board_fixture(
    snapshot: TradeSnapshot,
    board_id: str,
    point_values: dict[str, float] = POINTS,
) -> ValueBoard:
    selected = {
        "a_wr": 20.0,
        "b_rb": 15.0,
        "fa_wr": 2.0,
        "a_low": 1.0,
    }
    market = {
        "a_wr": 18.0,
        "b_rb": 22.0,
        "fa_wr": 3.0,
        "a_low": 1.0,
    }
    values = selected if board_id == "selected_final" else market
    players = tuple(
        BoardPlayerValue(
            player_id=player.player_id,
            position=player.positions[0],
            position_rank=index,
            overall_rank=index,
            raw_projection=point_values[player.player_id] * 3,
            raw_projection_rank=index,
            aligned_points=point_values[player.player_id] * 3,
            replacement_points=0.0,
            positional_vorp=values.get(player.player_id, point_values[player.player_id]),
            reconciled_vorp=values.get(player.player_id, point_values[player.player_id]),
            tier=1,
        )
        for index, player in enumerate(snapshot.players, 1)
    )
    return ValueBoard(
        board_id=board_id,
        horizon=snapshot.ranking_horizon,
        players=players,
        curves=(),
        replacement_baselines=(("RB", 0.0), ("WR", 0.0)),
        overall_curve=MonotoneCurve(((1.0, 1.0),), len(players), 1),
        complete=True,
        stamps=snapshot.stamps,
    )


class PackageContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.snapshot = snapshot_fixture()

    def test_exact_name_resolution_ownership_and_supported_size(self) -> None:
        package = build_entered_package(
            self.snapshot,
            send=("Alpha Receiver",),
            receive=("Bravo Runner",),
        )
        self.assertEqual(package.roster_a_id, "1")
        self.assertEqual(package.roster_b_id, "2")
        self.assertEqual(package.from_a[0].player_id, "a_wr")
        with self.assertRaises(IdentityIncomplete):
            build_entered_package(
                self.snapshot,
                send=("Bravo Runner",),
                receive=("Alpha Receiver",),
            )
        with self.assertRaises(RosterIllegal):
            build_entered_package(
                self.snapshot,
                send=("a_wr", "a_wr"),
                receive=("b_rb",),
            )
        with self.assertRaises(RosterIllegal):
            build_entered_package(
                self.snapshot,
                send=("a_wr", "a_rb", "a_low", "a_bench", "a_wr"),
                receive=("b_rb",),
            )

    def test_ambiguous_exact_name_stops(self) -> None:
        with self.assertRaisesRegex(IdentityIncomplete, "Ambiguous"):
            resolve_player(self.snapshot, "Same Name")

    def test_three_and_four_player_equal_packages_are_supported(self) -> None:
        three = build_entered_package(
            self.snapshot,
            send=("a_rb", "a_wr", "a_bench"),
            receive=("b_rb", "b_wr", "b_bench"),
        )
        four = build_entered_package(
            self.snapshot,
            send=("a_rb", "a_wr", "a_bench", "a_low"),
            receive=("b_rb", "b_wr", "b_bench", "b_low"),
        )
        self.assertEqual((len(three.from_a), len(three.from_b)), (3, 3))
        self.assertEqual((len(four.from_a), len(four.from_b)), (4, 4))

    def test_self_trade_stops(self) -> None:
        with self.assertRaisesRegex(RosterIllegal, "different rosters"):
            build_entered_package(
                self.snapshot,
                send=("a_wr",),
                receive=("a_rb",),
            )


class ProjectionAndEvaluationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.snapshot = snapshot_fixture()
        self.projections = projection_fixture()
        self.selected = board_fixture(self.snapshot, "selected_final")
        self.market = board_fixture(self.snapshot, "market")

    def evaluate(self, send, receive, **options):
        package = build_entered_package(
            self.snapshot,
            send=send,
            receive=receive,
        )
        return evaluate_trade(
            self.snapshot,
            package,
            projections=self.projections,
            selected_board=self.selected,
            market_board=self.market,
            options=EvaluationOptions(**options),
        )

    def test_bye_zeroes_only_the_affected_week(self) -> None:
        weeks = (
            replace(self.snapshot.weeks[0], bye_teams=("AAA",)),
            *self.snapshot.weeks[1:],
        )
        matrix = build_weekly_projection_matrix(
            replace(self.snapshot, weeks=weeks), self.projections
        )
        self.assertEqual(matrix.cell("a_rb", 1).points, 0.0)
        self.assertEqual(matrix.cell("a_rb", 2).points, 10.0)

    def test_known_inactive_player_is_zeroed_and_labeled(self) -> None:
        players = tuple(
            replace(player, injury_status="OUT") if player.player_id == "a_rb" else player
            for player in self.snapshot.players
        )
        matrix = build_weekly_projection_matrix(
            replace(self.snapshot, players=players), self.projections
        )
        self.assertEqual(matrix.cell("a_rb", 1).points, 0.0)
        self.assertEqual(matrix.cell("a_rb", 1).availability, "INACTIVE")

    def test_cross_position_one_for_one_reports_both_teams_and_model_split(self) -> None:
        result = self.evaluate(("a_wr",), ("b_rb",))
        user, partner = result.team_impacts
        self.assertEqual(user.weighted_delta, -18.0)
        self.assertEqual(partner.weighted_delta, 0.0)
        self.assertEqual(result.ownership_impacts[0].selected_package_delta, -5.0)
        self.assertEqual(result.ownership_impacts[0].market_package_delta, 4.0)
        self.assertTrue(
            any(row.component == "model_disagreement" for row in result.provisional_reversal_conditions)
        )
        self.assertEqual(result.decision_label, "DECLINE")
        self.assertFalse(
            next(
                gate
                for gate in result.decision.gates
                if gate.name == "user_expected_lineup_delta"
            ).passed
        )

    def test_four_for_four_evaluates_both_rosters_without_secondary_moves(self) -> None:
        for sent, received in (
            (
                ("a_rb", "a_wr", "a_bench"),
                ("b_rb", "b_wr", "b_bench"),
            ),
            (
                ("a_rb", "a_wr", "a_bench", "a_low"),
                ("b_rb", "b_wr", "b_bench", "b_low"),
            ),
        ):
            with self.subTest(size=len(sent)):
                result = self.evaluate(sent, received)
                self.assertEqual(len(result.team_impacts), 2)
                self.assertTrue(
                    all(move.kind == "NONE" for move in result.secondary_moves)
                )
                self.assertEqual(result.team_impacts[0].weighted_delta, -3.0)
                self.assertEqual(result.team_impacts[1].weighted_delta, 3.0)

    def test_swapping_package_perspective_preserves_team_results(self) -> None:
        original = self.evaluate(("a_wr",), ("b_rb",))
        reversed_package = TradePackage(
            roster_a_id="2",
            roster_b_id="1",
            from_a=(PlayerAsset("b_rb"),),
            from_b=(PlayerAsset("a_wr"),),
        )
        reversed_result = evaluate_trade(
            self.snapshot,
            reversed_package,
            projections=self.projections,
            selected_board=self.selected,
            market_board=self.market,
        )
        self.assertEqual(original.team_impacts[0], reversed_result.team_impacts[1])
        self.assertEqual(original.team_impacts[1], reversed_result.team_impacts[0])
        self.assertEqual(
            original.ownership_impacts[0].market_package_delta,
            -original.ownership_impacts[1].market_package_delta,
        )

    def test_traded_player_status_names_availability_reversal(self) -> None:
        players = tuple(
            replace(player, injury_status="Q") if player.player_id == "a_wr" else player
            for player in self.snapshot.players
        )
        snapshot = replace(self.snapshot, players=players)
        package = build_entered_package(snapshot, send=("a_wr",), receive=("b_rb",))
        result = evaluate_trade(
            snapshot,
            package,
            projections=self.projections,
            selected_board=self.selected,
            market_board=self.market,
        )
        self.assertTrue(
            any(row.component == "availability" for row in result.provisional_reversal_conditions)
        )

    def test_same_offense_concentration_and_scenarios_are_explicit_not_a_tax(self) -> None:
        players = tuple(
            replace(player, nfl_team="AAA")
            if player.player_id == "a_bench"
            else player
            for player in self.snapshot.players
        )
        snapshot = replace(self.snapshot, players=players)
        result = evaluate_trade(
            snapshot,
            build_entered_package(snapshot, send=("a_low",), receive=("b_low",)),
            projections=self.projections,
            selected_board=board_fixture(snapshot, "selected_final"),
            market_board=board_fixture(snapshot, "market"),
        )
        before = result.risk_impacts[0].before
        aaa = next(row for row in before.exposures if row.nfl_team == "AAA")
        self.assertEqual(aaa.full_roster_player_ids, ("a_bench", "a_rb", "a_wr"))
        self.assertEqual(aaa.starter_player_ids, ("a_bench", "a_rb", "a_wr"))
        self.assertTrue(any(row.pair_type == "RB_PASS_CATCHER" for row in before.pairs))
        self.assertGreater(before.offense_downside_loss, 0.0)
        self.assertGreater(before.offense_upside_gain, 0.0)
        self.assertEqual(
            next(row for row in result.decision.gates if row.name == "user_selected_value_delta").actual,
            result.ownership_impacts[0].selected_package_delta
            + result.ownership_impacts[0].selected_secondary_delta,
        )

    def test_roster_diagnosis_distinguishes_unused_depth_from_player_count(self) -> None:
        diagnosis = diagnose_roster(self.snapshot, self.projections)
        self.assertEqual(diagnosis.roster_id, "1")
        self.assertEqual(len(diagnosis.weekly_optimal_points), 3)
        receiver = next(row for row in diagnosis.positions if row.position == "WR")
        self.assertIn("a_low", receiver.never_started_player_ids)
        self.assertNotIn("a_low", receiver.usable_surplus_player_ids)
        self.assertEqual(diagnosis.bye_gap_weeks, ())
        self.assertTrue(diagnosis.smallest_useful_change)

    def test_bengals_diversification_and_discounted_offer_have_opposite_labels(self) -> None:
        replacements = {
            "a_rb": ("Chase Brown", ("RB",), "CIN"),
            "a_wr": ("Ja'Marr Chase", ("WR",), "CIN"),
            "a_bench": ("Tee Higgins", ("WR",), "CIN"),
        }
        players = tuple(
            replace(
                player,
                name=replacements[player.player_id][0],
                positions=replacements[player.player_id][1],
                nfl_team=replacements[player.player_id][2],
            )
            if player.player_id in replacements
            else player
            for player in self.snapshot.players
        )
        snapshot = replace(self.snapshot, players=players)
        point_values = {**POINTS, "b_bench": 5.0}
        projections = tuple(
            Projection(
                player_id=player_id,
                horizon="WEEKLY",
                week=week,
                raw_stats=(),
                league_points=points,
                source="fixture",
            )
            for player_id, points in point_values.items()
            for week in (1, 2, 3)
        )

        def neutral_board(board_id: str) -> ValueBoard:
            board = board_fixture(snapshot, board_id, point_values)
            return replace(
                board,
                players=tuple(
                    replace(
                        row,
                        reconciled_vorp=point_values[row.player_id],
                        positional_vorp=point_values[row.player_id],
                    )
                    for row in board.players
                ),
            )

        selected = neutral_board("selected_final")
        market = neutral_board("market")
        fair = evaluate_trade(
            snapshot,
            build_entered_package(snapshot, send=("a_bench",), receive=("b_bench",)),
            projections=projections,
            selected_board=selected,
            market_board=market,
        )
        self.assertEqual(fair.decision_label, "ACCEPTABLE")
        self.assertLess(fair.risk_impacts[0].max_offense_share_delta, 0.0)
        cin_before = next(
            row for row in fair.risk_impacts[0].before.exposures if row.nfl_team == "CIN"
        )
        self.assertEqual(len(cin_before.starter_player_ids), 3)
        self.assertEqual(
            [
                (week.week, week.before_points, week.after_points, week.delta)
                for week in fair.team_impacts[0].weeks
            ],
            [(1, 23.0, 23.0, 0.0), (2, 23.0, 23.0, 0.0), (3, 23.0, 23.0, 0.0)],
        )
        self.assertEqual(
            [
                (week.week, week.before_points, week.after_points, week.delta)
                for week in fair.team_impacts[1].weeks
            ],
            [(1, 23.0, 23.0, 0.0), (2, 23.0, 23.0, 0.0), (3, 23.0, 23.0, 0.0)],
        )

        discounted = evaluate_trade(
            snapshot,
            build_entered_package(snapshot, send=("a_bench",), receive=("b_low",)),
            projections=projections,
            selected_board=selected,
            market_board=market,
        )
        self.assertEqual(discounted.decision_label, "DECLINE")
        self.assertLess(discounted.risk_impacts[0].max_offense_share_delta, 0.0)
        self.assertLess(discounted.team_impacts[0].weighted_delta, 0.0)
        self.assertEqual(
            [
                (week.week, week.before_points, week.after_points, week.delta)
                for week in discounted.team_impacts[0].weeks
            ],
            [(1, 23.0, 20.0, -3.0), (2, 23.0, 20.0, -3.0), (3, 23.0, 20.0, -3.0)],
        )
        self.assertEqual(
            [
                (week.week, week.before_points, week.after_points, week.delta)
                for week in discounted.team_impacts[1].weeks
            ],
            [(1, 23.0, 23.0, 0.0), (2, 23.0, 23.0, 0.0), (3, 23.0, 23.0, 0.0)],
        )

    def test_risk_posture_changes_only_explicit_gate_thresholds(self) -> None:
        package = build_entered_package(
            self.snapshot, send=("a_low",), receive=("b_low",)
        )
        conservative = evaluate_trade(
            self.snapshot,
            package,
            projections=self.projections,
            selected_board=self.selected,
            market_board=self.market,
            options=EvaluationOptions(
                risk_posture="CONSERVATIVE",
                max_depth_loss=10.0,
                max_downside_increase=0.0,
            ),
        )
        ceiling = evaluate_trade(
            self.snapshot,
            package,
            projections=self.projections,
            selected_board=self.selected,
            market_board=self.market,
            options=EvaluationOptions(
                risk_posture="CEILING",
                max_depth_loss=40.0,
                max_downside_increase=10.0,
            ),
        )
        self.assertEqual(conservative.team_impacts, ceiling.team_impacts)
        self.assertEqual(conservative.ownership_impacts, ceiling.ownership_impacts)
        conservative_depth = next(
            row for row in conservative.decision.gates if row.name == "user_depth_delta"
        )
        ceiling_depth = next(
            row for row in ceiling.decision.gates if row.name == "user_depth_delta"
        )
        self.assertEqual(conservative_depth.threshold, -10.0)
        self.assertEqual(ceiling_depth.threshold, -40.0)
        self.assertIn("SCENARIO-ONLY-RISK", conservative.modes)

    def test_two_for_one_enumerates_add_and_drop_with_next_best(self) -> None:
        result = self.evaluate(("a_wr", "a_low"), ("b_wr",))
        moves = {move.roster_id: move for move in result.secondary_moves}
        self.assertEqual((moves["1"].kind, moves["1"].chosen_player_id), ("ADD", "fa_wr"))
        self.assertEqual((moves["2"].kind, moves["2"].chosen_player_id), ("DROP", "a_low"))
        self.assertEqual(result.team_impacts[0].weighted_delta, 18.0)
        self.assertEqual(result.team_impacts[1].weighted_delta, -12.0)
        self.assertIsNotNone(moves["1"].next_best_player_id)
        self.assertTrue(
            any(row.component == "secondary_move" for row in result.provisional_reversal_conditions)
        )

    def test_one_for_two_required_drop_reverses_apparent_package_gain(self) -> None:
        result = self.evaluate(("a_bench",), ("b_bench", "b_low"))
        user_value = result.ownership_impacts[0]
        user_move = next(
            move for move in result.secondary_moves if move.roster_id == "1"
        )

        self.assertEqual((user_move.kind, user_move.chosen_player_ids), ("DROP", ("a_low",)))
        self.assertGreater(user_value.raw_projection_package_delta, 0.0)
        self.assertEqual(
            user_value.raw_projection_package_delta
            + user_value.raw_projection_secondary_delta,
            0.0,
        )
        self.assertLess(result.team_impacts[0].weighted_delta, 0.0)

    def test_two_for_three_adds_best_waiver_and_drops_for_other_team(self) -> None:
        result = self.evaluate(
            ("a_wr", "a_low"),
            ("b_wr", "b_bench", "b_low"),
        )
        moves = {move.roster_id: move for move in result.secondary_moves}
        self.assertEqual((moves["1"].kind, moves["1"].chosen_player_ids), ("DROP", ("b_bench",)))
        self.assertEqual((moves["2"].kind, moves["2"].chosen_player_ids), ("ADD", ("fa_wr",)))
        self.assertEqual(moves["2"].candidate_pool_size, len(self.snapshot.free_agent_ids))
        self.assertEqual(result.ownership_impacts[1].market_secondary_delta, 3.0)

    def test_below_replacement_secondary_player_cannot_create_phantom_value(self) -> None:
        def negative_waiver(board: ValueBoard) -> ValueBoard:
            return replace(
                board,
                players=tuple(
                    replace(row, reconciled_vorp=-100.0, positional_vorp=-100.0)
                    if row.player_id == "fa_wr"
                    else row
                    for row in board.players
                ),
            )

        result = evaluate_trade(
            self.snapshot,
            build_entered_package(
                self.snapshot,
                send=("a_wr", "a_low"),
                receive=("b_wr", "b_bench", "b_low"),
            ),
            projections=self.projections,
            selected_board=negative_waiver(self.selected),
            market_board=negative_waiver(self.market),
        )
        user_add = result.ownership_impacts[1]
        self.assertEqual(user_add.selected_secondary_delta, 0.0)
        self.assertEqual(user_add.market_secondary_delta, 0.0)
        self.assertGreater(user_add.raw_projection_secondary_delta, 0.0)

    def test_four_for_one_jointly_resolves_three_adds_and_three_drops(self) -> None:
        result = self.evaluate(
            ("a_rb", "a_wr", "a_bench", "a_low"),
            ("b_wr",),
        )
        moves = {move.roster_id: move for move in result.secondary_moves}
        self.assertEqual(moves["1"].kind, "ADD")
        self.assertEqual(len(moves["1"].chosen_player_ids), 3)
        self.assertEqual(moves["2"].kind, "DROP")
        self.assertEqual(len(moves["2"].chosen_player_ids), 3)
        self.assertLessEqual(moves["1"].combinations_considered, 1_000)
        self.assertLessEqual(moves["2"].combinations_considered, 1_000)
        repeated = self.evaluate(
            ("a_rb", "a_wr", "a_bench", "a_low"),
            ("b_wr",),
        )
        self.assertEqual(result.evidence_hash, repeated.evidence_hash)
        report = format_trade_evaluation(result)
        self.assertIn("add set", report)
        self.assertIn("combinations from", report)

        reversed_package = TradePackage(
            roster_a_id="2",
            roster_b_id="1",
            from_a=(PlayerAsset("b_wr"),),
            from_b=tuple(
                PlayerAsset(player_id)
                for player_id in ("a_rb", "a_wr", "a_bench", "a_low")
            ),
        )
        reversed_result = evaluate_trade(
            self.snapshot,
            reversed_package,
            projections=self.projections,
            selected_board=self.selected,
            market_board=self.market,
        )
        self.assertEqual(result.team_impacts[0], reversed_result.team_impacts[1])
        self.assertEqual(result.team_impacts[1], reversed_result.team_impacts[0])

        overridden = self.evaluate(
            ("a_rb", "a_wr", "a_bench", "a_low"),
            ("b_wr",),
            add_overrides=("fa_rb", "twin_1", "twin_2"),
            drop_overrides=("a_low", "b_low", "b_bench"),
        )
        overridden_moves = {move.roster_id: move for move in overridden.secondary_moves}
        self.assertEqual(
            overridden_moves["1"].chosen_player_ids,
            ("fa_rb", "twin_1", "twin_2"),
        )
        self.assertEqual(
            overridden_moves["2"].chosen_player_ids,
            ("a_low", "b_bench", "b_low"),
        )

    def test_rank_only_large_imbalance_requires_every_secondary_override(self) -> None:
        package = build_entered_package(
            self.snapshot,
            send=("a_rb", "a_wr", "a_bench", "a_low"),
            receive=("b_wr",),
        )
        with self.assertRaisesRegex(CoverageIncomplete, "exactly 3"):
            evaluate_trade(
                self.snapshot,
                package,
                projections=(),
                selected_board=None,
                market_board=self.market,
                options=EvaluationOptions(
                    allow_rank_only=True,
                    add_overrides=("fa_rb",),
                    drop_overrides=("a_low", "b_low", "b_bench"),
                ),
            )
        result = evaluate_trade(
            self.snapshot,
            package,
            projections=(),
            selected_board=None,
            market_board=self.market,
            options=EvaluationOptions(
                allow_rank_only=True,
                add_overrides=("fa_rb", "twin_1", "twin_2"),
                drop_overrides=("a_low", "b_low", "b_bench"),
            ),
        )
        self.assertIn("RANK-ONLY", result.modes)
        self.assertEqual(len(result.secondary_moves[0].chosen_player_ids), 3)

    def test_secondary_combination_search_reports_its_hard_bound(self) -> None:
        package = build_entered_package(
            self.snapshot,
            send=("a_rb", "a_wr", "a_bench", "a_low"),
            receive=("b_wr",),
        )
        with patch(
            "roster_theory.trade.evaluation.MAX_SECONDARY_COMBINATIONS", 1
        ):
            result = evaluate_trade(
                self.snapshot,
                package,
                projections=self.projections,
                selected_board=self.selected,
                market_board=self.market,
            )
        self.assertTrue(all(move.search_truncated for move in result.secondary_moves))
        self.assertTrue(
            all(move.combinations_considered == 1 for move in result.secondary_moves)
        )
        self.assertIn("BOUNDED-SECONDARY-SEARCH", result.modes)

    def test_joint_waiver_set_beats_greedy_first_add(self) -> None:
        extra_players = (
            Player("fa_stable", "Stable Free Agent", ("WR",), sleeper_id="fa_stable", nfl_team="III", active=True),
            Player("fa_boom1", "Week One Free Agent", ("WR",), sleeper_id="fa_boom1", nfl_team="JJJ", active=True),
            Player("fa_boom2", "Later Free Agent", ("WR",), sleeper_id="fa_boom2", nfl_team="KKK", active=True),
        )
        snapshot = replace(
            self.snapshot,
            league=replace(self.snapshot.league, roster_positions=("WR", "BN", "BN", "BN")),
            players=(*self.snapshot.players, *extra_players),
            free_agent_ids=(*self.snapshot.free_agent_ids, *(row.player_id for row in extra_players)),
            tradeable_player_ids=(
                *self.snapshot.tradeable_player_ids,
                *(row.player_id for row in extra_players),
            ),
        )
        weekly = {
            "fa_stable": (10.0, 10.0, 10.0),
            "fa_boom1": (20.0, 0.0, 0.0),
            "fa_boom2": (0.0, 11.0, 11.0),
        }
        projections = (
            *self.projections,
            *(
                Projection(
                    player_id=player_id,
                    horizon="WEEKLY",
                    week=week,
                    raw_stats=(),
                    league_points=points,
                    source="fixture",
                )
                for player_id, week_points in weekly.items()
                for week, points in enumerate(week_points, 1)
            ),
        )
        point_values = {
            **POINTS,
            **{player_id: sum(points) / 3 for player_id, points in weekly.items()},
        }
        package = build_entered_package(
            snapshot,
            send=("a_wr", "a_bench", "a_low"),
            receive=("b_rb",),
        )
        result = evaluate_trade(
            snapshot,
            package,
            projections=projections,
            selected_board=board_fixture(snapshot, "selected_final", point_values),
            market_board=board_fixture(snapshot, "market", point_values),
        )
        move = next(row for row in result.secondary_moves if row.roster_id == "1")
        self.assertEqual(move.chosen_player_ids, ("fa_boom1", "fa_boom2"))
        stable = next(
            row for row in move.candidates if "fa_stable" in row.player_ids
        )
        self.assertGreater(move.candidates[0].weighted_lineup_points, stable.weighted_lineup_points)

    def test_secondary_add_choice_can_reverse_lineup_result(self) -> None:
        projections = tuple(
            replace(
                row,
                league_points=(
                    6.0 if row.player_id == "b_wr" else 9.0 if row.player_id == "fa_wr" else row.league_points
                ),
            )
            for row in self.projections
        )
        package = build_entered_package(
            self.snapshot, send=("a_wr", "a_low"), receive=("b_wr",)
        )
        automatic = evaluate_trade(
            self.snapshot,
            package,
            projections=projections,
            selected_board=self.selected,
            market_board=self.market,
        )
        overridden = evaluate_trade(
            self.snapshot,
            package,
            projections=projections,
            selected_board=self.selected,
            market_board=self.market,
            options=EvaluationOptions(add_override="fa_rb", drop_override="a_low"),
        )
        self.assertEqual(automatic.team_impacts[0].weighted_delta, 6.0)
        self.assertEqual(overridden.team_impacts[0].weighted_delta, -6.0)

    def test_playoff_weight_changes_total_without_hiding_week_delta(self) -> None:
        default = self.evaluate(("a_wr",), ("b_rb",))
        weighted = self.evaluate(("a_wr",), ("b_rb",), playoff_weight=2.0)
        self.assertEqual(default.team_impacts[0].weighted_delta, -18.0)
        self.assertEqual(weighted.team_impacts[0].weighted_delta, -24.0)
        self.assertEqual(weighted.team_impacts[0].playoff_delta, -6.0)

    def test_add_and_drop_overrides_change_the_secondary_consequence(self) -> None:
        result = self.evaluate(
            ("a_wr", "a_low"),
            ("b_wr",),
            add_override="fa_rb",
            drop_override="b_bench",
        )
        moves = {move.roster_id: move for move in result.secondary_moves}
        self.assertEqual(moves["1"].chosen_player_id, "fa_rb")
        self.assertEqual(moves["2"].chosen_player_id, "b_bench")
        self.assertEqual(result.team_impacts[0].weighted_delta, 12.0)
        self.assertEqual(result.team_impacts[1].weighted_delta, -18.0)

    def test_reserve_asset_is_explicitly_manual_legality(self) -> None:
        user, partner = self.snapshot.teams
        snapshot = replace(
            self.snapshot,
            teams=(replace(user, reserve_ids=("a_low",)), partner),
        )
        package = build_entered_package(snapshot, send=("a_low",), receive=("b_rb",))
        result = evaluate_trade(
            snapshot,
            package,
            projections=self.projections,
            selected_board=self.selected,
            market_board=self.market,
        )
        self.assertIn("MANUAL-LEGALITY", result.modes)
        self.assertTrue(all(move.manual_legality for move in result.secondary_moves))
        self.assertTrue(any("manual Sleeper legality" in row for row in result.warnings))

    def test_missing_week_stops_or_is_explicitly_partial(self) -> None:
        incomplete = tuple(
            row
            for row in self.projections
            if not (row.player_id == "a_bench" and row.week == 2)
        )
        package = build_entered_package(
            self.snapshot, send=("a_wr",), receive=("b_rb",)
        )
        with self.assertRaises(CoverageIncomplete):
            evaluate_trade(
                self.snapshot,
                package,
                projections=incomplete,
                selected_board=self.selected,
                market_board=self.market,
            )
        partial = evaluate_trade(
            self.snapshot,
            package,
            projections=incomplete,
            selected_board=self.selected,
            market_board=self.market,
            options=EvaluationOptions(allow_partial_schedule=True),
        )
        self.assertIn("SCHEDULE-PARTIAL", partial.modes)
        self.assertTrue(any("missing projection" in row.casefold() for row in partial.warnings))
        issue = next(
            row
            for row in partial.projection_coverage.issues
            if row.player_id == "a_bench"
        )
        self.assertEqual(issue.scope, "EVALUATED_ROSTER")
        self.assertEqual(issue.missing_weeks, (2,))

    def test_missing_fringe_projection_is_aggregated_without_warning_flood(self) -> None:
        incomplete = tuple(
            row
            for row in self.projections
            if not (row.player_id == "twin_1" and row.week in (1, 2, 3))
        )
        result = evaluate_trade(
            self.snapshot,
            build_entered_package(
                self.snapshot, send=("a_wr",), receive=("b_rb",)
            ),
            projections=incomplete,
            selected_board=self.selected,
            market_board=self.market,
        )
        self.assertFalse(any("twin_1" in row for row in result.warnings))
        self.assertEqual(result.projection_coverage.outside_player_count, 1)
        self.assertEqual(result.projection_coverage.outside_player_week_count, 3)
        report = format_trade_evaluation(result)
        self.assertIn("all evaluated/package players covered", report)
        self.assertIn("3 missing player-weeks omitted", report)

    def test_ecr_only_and_rank_only_do_not_overclaim(self) -> None:
        package = build_entered_package(
            self.snapshot, send=("a_wr",), receive=("b_rb",)
        )
        result = evaluate_trade(
            self.snapshot,
            package,
            projections=(),
            selected_board=None,
            market_board=self.market,
            options=EvaluationOptions(allow_rank_only=True),
        )
        self.assertEqual(set(result.modes), {"ECR-ONLY", "RANK-ONLY"})
        self.assertEqual(result.team_impacts, ())
        self.assertIsNone(result.ownership_impacts[0].selected_package_delta)
        self.assertIn("without projected lineup impact", result.summary)

    def test_evidence_is_deterministic_and_offline_replay_is_labeled(self) -> None:
        first = self.evaluate(("a_wr",), ("b_rb",))
        second = self.evaluate(("a_wr",), ("b_rb",))
        self.assertEqual(first.evidence_hash, second.evidence_hash)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "evaluation.json"
            save_trade_evaluation(first, path)
            replay = load_trade_evaluation(path)
        self.assertEqual(replay["evidence_hash"], first.evidence_hash)
        self.assertEqual(replay["replay_mode"], "OFFLINE/NON-CURRENT")

    def test_evidence_replay_rejects_modified_contents(self) -> None:
        result = self.evaluate(("a_wr",), ("b_rb",))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "evaluation.json"
            save_trade_evaluation(result, path)
            value = json.loads(path.read_text(encoding="utf-8"))
            value["summary"] = "changed"
            path.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "hash"):
                load_trade_evaluation(path)


class TradeEvaluationCliTests(unittest.TestCase):
    def test_evaluate_parser_is_namespaced_and_read_only(self) -> None:
        args = build_parser().parse_args(
            [
                "trade",
                "evaluate",
                "fixture",
                "--send",
                "Alpha Receiver",
                "--receive",
                "Bravo Runner",
                "--add",
                "Free Runner",
                "--add",
                "Free Receiver",
                "--allow-rank-only",
                "--json",
            ]
        )
        self.assertEqual(args.trade_command, "evaluate")
        self.assertEqual(args.send, ["Alpha Receiver"])
        self.assertEqual(args.receive, ["Bravo Runner"])
        self.assertEqual(args.add, ["Free Runner", "Free Receiver"])
        self.assertTrue(args.allow_rank_only)
        self.assertTrue(args.json)
        self.assertEqual(args.risk_posture, "balanced")

    def test_diagnose_parser_is_namespaced_and_read_only(self) -> None:
        args = build_parser().parse_args(
            ["trade", "diagnose", "fixture", "--risk-posture", "ceiling", "--json"]
        )
        self.assertEqual(args.trade_command, "diagnose")
        self.assertEqual(args.risk_posture, "ceiling")
        self.assertTrue(args.json)

    def test_compact_report_keeps_value_views_separate_and_prints_decision_gates(self) -> None:
        snapshot = snapshot_fixture()
        evaluation = evaluate_trade(
            snapshot,
            build_entered_package(snapshot, send=("a_wr",), receive=("b_rb",)),
            projections=projection_fixture(),
            selected_board=board_fixture(snapshot, "selected_final"),
            market_board=board_fixture(snapshot, "market"),
        )
        report = format_trade_evaluation(evaluation)
        self.assertIn("DECISION: DECLINE", report)
        self.assertIn("Decision gates:", report)
        self.assertIn("Roster 1 risk:", report)
        self.assertIn("selected ownership", report)
        self.assertIn("market ownership", report)
        self.assertIn("raw projection", report)
        self.assertIn("Data:", report)


if __name__ == "__main__":
    unittest.main()
