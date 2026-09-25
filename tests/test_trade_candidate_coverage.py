import unittest
from dataclasses import replace

from roster_theory.core.models import FantasyTeam, Player
from roster_theory.trade.targets import discover_trade_targets
from roster_theory.trade.target_optimizer import optimize_target_packages
from roster_theory.trade.boards import build_projection_curves, build_value_board, scoped_board_universe
from roster_theory.core.models import Projection
from roster_theory.core.errors import CoverageIncomplete
from roster_theory.trade.evaluation import evaluate_trade, TradePackage, PlayerAsset
from tests.test_trade_targets import fixture, config
from tests.test_trade_target_optimizer import optimizer_config, permissive_options


class TradeCandidateCoverageTests(unittest.TestCase):
    def run_search(self, missing=None, unrelated=False):
        snapshot, projections, selected, market, direct = fixture()
        if unrelated:
            snapshot = replace(
                snapshot, players=(*snapshot.players, Player("unknown", "Unknown", ("WR",))),
                teams=(*snapshot.teams, FantasyTeam("3", "third", "Third", ("unknown",))),
                owner_by_player=(*snapshot.owner_by_player, ("unknown", "3")),
                tradeable_player_ids=(*snapshot.tradeable_player_ids, "unknown"),
            )
        projections = tuple(row for row in projections if row.player_id != missing)
        targets = discover_trade_targets(
            snapshot, projections=projections, selected_board=selected,
            market_ecr_board=market, trade_market=direct, config=config(),
        )
        result = optimize_target_packages(
            snapshot, projections=projections, selected_board=selected,
            market_ecr_board=market, trade_market=direct, target_result=targets,
            config=optimizer_config(), options=permissive_options(),
        )
        return targets, result

    def test_unrelated_missing_roster_does_not_change_safe_targets(self):
        baseline, _ = self.run_search()
        partial, result = self.run_search(unrelated=True)
        self.assertEqual([(t.kind, t.player_id) for t in baseline.targets],
                         [(t.kind, t.player_id) for t in partial.targets])
        self.assertEqual(len(partial.roster_exclusions), 1)
        self.assertEqual(partial.roster_exclusions[0].missing_player_weeks[0], ("unknown", 1))
        self.assertTrue(result.coverage)

    def test_user_missing_evidence_has_no_targets_or_offers(self):
        targets, result = self.run_search(missing="u_rb")
        self.assertFalse(targets.targets)
        self.assertFalse(result.opportunities)
        self.assertTrue(any("USER_ROSTER" in row.reason for row in targets.exclusions))

    def test_missing_partner_excludes_only_that_partner(self):
        targets, result = self.run_search(missing="o_fill")
        self.assertFalse(any(t.roster.owner_roster_id == "2" for t in targets.targets))
        self.assertTrue(targets.roster_exclusions)
        self.assertFalse(result.opportunities)

    def test_partial_curves_preserve_expert_ranks_and_expose_exclusions(self):
        positions = {"a": "RB", "missing": "RB", "c": "RB", "te": "TE"}
        ranks = {"a": 1, "missing": 2, "c": 3, "te": 1}
        projections = tuple(Projection(pid, "WEEKLY", 1, (), points, "fixture")
                            for pid, points in (("a", 20), ("c", 10), ("te", 8)))
        curves = build_projection_curves(
            projections, positions, required_counts={"RB": 3, "TE": 1},
            expected_weeks=(1,), allow_partial=True,
        )
        usable, excluded = scoped_board_universe(positions, (ranks,), curves, {"RB": 5, "TE": 4})
        self.assertEqual(usable, {"a": "RB", "te": "TE"})
        self.assertIn(("c", "AUTHORITATIVE_RANK_SLOT_UNAVAILABLE"), excluded)
        self.assertIn(("missing", "INCOMPLETE_PROJECTION_EVIDENCE"), excluded)
        board = build_value_board(
            board_id="test", horizon="ROS", positions=usable,
            position_ranks={pid: ranks[pid] for pid in usable}, curves=curves,
            replacement_baselines={"RB": 5, "TE": 4}, excluded_players=excluded,
        )
        self.assertEqual({row.player_id for row in board.players}, {"a", "te"})
        self.assertEqual(board.excluded_players, excluded)

    def test_missing_positional_baseline_is_local_and_empty_scope_has_no_values(self):
        snapshot, _, selected, _, _ = fixture()
        del snapshot
        positions = {"a": "RB", "b": "TE"}
        ranks = {"a": 1, "b": 1}
        projections = (Projection("a", "ROS", None, (), 20, "fixture"),
                       Projection("b", "ROS", None, (), 10, "fixture"))
        curves = build_projection_curves(projections, positions, required_counts={"RB": 1, "TE": 1})
        usable, excluded = scoped_board_universe(positions, (ranks,), curves, {"TE": 4})
        self.assertEqual(usable, {"b": "TE"})
        self.assertEqual(excluded, (("a", "POSITION_REPLACEMENT_BASELINE_UNAVAILABLE"),))
        empty = build_value_board(board_id="empty", horizon=selected.horizon, positions={},
                                 position_ranks={}, curves=(), replacement_baselines={},
                                 excluded_players=(("a", "UNAVAILABLE"),))
        self.assertFalse(empty.players)
        self.assertFalse(empty.overall_curve.points)

    def test_exact_trade_rejects_only_relevant_unresolved_identity(self):
        snapshot, projections, selected, market, _ = fixture()
        package = TradePackage("1", "2", (PlayerAsset("u_sell"),), (PlayerAsset("o_con"),))
        unrelated = replace(snapshot, player_exclusions=(("unknown-third-roster", "PLAYER_IDENTITY_UNAVAILABLE"),))
        evaluate_trade(unrelated, package, projections=projections, selected_board=selected,
                       market_board=market, options=permissive_options())
        affected = replace(snapshot, player_exclusions=(("u_rb", "PLAYER_IDENTITY_UNAVAILABLE"),))
        with self.assertRaisesRegex(CoverageIncomplete, "u_rb"):
            evaluate_trade(affected, package, projections=projections, selected_board=selected,
                           market_board=market, options=permissive_options())

    def test_missing_user_directory_identity_is_not_silently_removed_from_lineup(self):
        snapshot, projections, selected, market, direct = fixture()
        snapshot = replace(snapshot, players=tuple(row for row in snapshot.players if row.player_id != "u_rb"),
                           player_exclusions=(("u_rb", "PLAYER_IDENTITY_UNAVAILABLE"),))
        targets = discover_trade_targets(snapshot, projections=projections, selected_board=selected,
                                         market_ecr_board=market, trade_market=direct, config=config())
        self.assertFalse(targets.targets)
        self.assertEqual(targets.roster_exclusions[0].reason, "ROSTER_PLAYER_IDENTITY_OR_TEAM_UNAVAILABLE")
