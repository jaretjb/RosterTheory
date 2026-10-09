from __future__ import annotations

import math
import unittest
from dataclasses import replace
from unittest.mock import patch

from roster_theory.cli import build_parser
from roster_theory.trade import finder
from roster_theory.trade.evaluation import DecisionGate
from roster_theory.trade.execution import FinderExecutionPolicy, SearchExecution, cached, search_execution
from roster_theory.trade.finder import (
    SHAPES, find_trade_packages, idea_status, one_edit_packages, rank_ideas, resolve_scope,
)
from roster_theory.trade.targets import discover_trade_targets
from tests.test_trade_target_optimizer import optimizer_config, permissive_options
from tests.test_trade_targets import fixture, config as discovery_config


def inputs():
    snapshot, projections, selected, ecr, market = fixture()
    # Two independent free agents make every shape's two required adds legal.
    player = next(p for p in snapshot.players if p.player_id == "fa_rb")
    additions = tuple(replace(player, player_id=f"fa_{n}", sleeper_id=f"fa_{n}",
                              name=f"Waiver player {n}") for n in (2, 3))
    snapshot = replace(snapshot, players=(*snapshot.players, *additions),
                       free_agent_ids=(*snapshot.free_agent_ids, *(p.player_id for p in additions)))
    projections = (*projections, *(replace(p, player_id=a.player_id)
                    for a in additions for p in projections if p.player_id == "fa_rb"))
    def expand(board):
        value = next(v for v in board.players if v.player_id == "fa_rb")
        return replace(board, players=(*board.players, *(replace(value, player_id=a.player_id)
                                                        for a in additions)))
    selected, ecr = expand(selected), expand(ecr)
    targets = discover_trade_targets(snapshot, projections=projections, selected_board=selected,
        market_ecr_board=ecr, trade_market=market, config=discovery_config(), options=permissive_options())
    return snapshot, projections, selected, ecr, market, targets


def run(case, **kwargs):
    snapshot, projections, selected, ecr, market, targets = case
    return find_trade_packages(snapshot, projections=projections, selected_board=selected,
        market_ecr_board=ecr, trade_market=market, target_result=replace(targets, targets=()),
        config=optimizer_config(), options=permissive_options(),
        scope=kwargs.pop("scope", resolve_scope(snapshot, None)),
        execution_policy=FinderExecutionPolicy(league_seconds=60, repairs_per_counter=0), **kwargs)


class TradeFinderTests(unittest.TestCase):
    def test_baseline_exhausts_all_nine_shapes_without_target_cards(self):
        case = inputs()
        result = run(case)
        expected = sum(math.comb(5, a) * math.comb(4, b) for a, b in SHAPES)
        self.assertEqual(result.termination, "EXHAUSTED")
        self.assertEqual(sum(c.enumerated for c in result.shape_coverage), expected)
        self.assertEqual(sum(c.evaluated for c in result.shape_coverage), expected)
        self.assertEqual(len(result.evaluated_decisions), expected)
        self.assertEqual({d.package_size for d in result.evaluated_decisions},
                         {f"{a}-for-{b}" for a, b in SHAPES})
        self.assertEqual(len({(d.sent_player_ids, d.received_player_ids) for d in result.evaluated_decisions}), expected)
        three = next(d for d in result.evaluated_decisions if d.package_size == "3-for-1")
        self.assertEqual(len(three.consolidation.user_add_player_ids), 2)
        self.assertEqual(len(three.consolidation.partner_drop_player_ids), 2)
        self.assertEqual(len(three.consolidation.partner_asset_uses), 3)
        self.assertAlmostEqual(three.market_fairness.consolidation_premium_value,
                               three.market_fairness.received_value * 0.1)

    def test_scoped_same_candidate_retains_exact_verdict_and_value(self):
        case = inputs()
        league = run(case, max_exact=1, max_large_exact=1)
        scoped = run(case, scope=resolve_scope(case[0], "Partner Team"), max_exact=1, max_large_exact=1)
        self.assertEqual(league.evaluated_decisions, scoped.evaluated_decisions)
        self.assertEqual(scoped.scope.opponent_roster_ids, ("2",))
        self.assertEqual(scoped.execution_profile["time_budget_seconds"], 300)
        self.assertEqual(league.termination, "EXACT_CAP")

    def test_opponent_is_resolved_and_excludes_other_discovery_work(self):
        case = inputs()
        snapshot, projections, selected, ecr, market, _ = case
        third = replace(snapshot.teams[1], roster_id="3", owner_id="other", display_name="Other Team", player_ids=())
        snapshot = replace(snapshot, teams=(*snapshot.teams, third), league=replace(snapshot.league, team_count=3))
        from roster_theory.trade import targets
        original = targets.diagnose_roster
        called = []
        def counted(*args, **kwargs):
            called.append(kwargs["roster_id"])
            return original(*args, **kwargs)
        with patch.object(targets, "diagnose_roster", side_effect=counted):
            result = discover_trade_targets(snapshot, projections=projections, selected_board=selected,
                market_ecr_board=ecr, trade_market=market, config=discovery_config(),
                options=permissive_options(), opponent_roster_ids=("2",))
        self.assertEqual(set(called), {"1", "2"})
        self.assertTrue(all(t.roster.owner_roster_id in {"1", "2"} for t in result.targets))
        for value in ("1", "unknown", "partner team"):
            with self.assertRaisesRegex(ValueError, "Valid opponents"):
                resolve_scope(snapshot, value)
        duplicate = replace(third, display_name="Partner Team")
        with self.assertRaises(ValueError):
            resolve_scope(replace(snapshot, teams=(*snapshot.teams[:2], duplicate)), "Partner Team")

    def test_deadline_rotation_and_unfinished_exact_not_published(self):
        case = inputs()
        class Clock:
            value = 0.0
            def __call__(self):
                return self.value
        clock = Clock()
        execution = SearchExecution(10, "fixture-bound", clock=clock)
        original = finder.evaluate_trade
        def timed(*args, **kwargs):
            result = original(*args, **kwargs)
            clock.value += 1
            return result
        with patch.object(finder, "evaluate_trade", side_effect=timed):
            result = run(case, execution=execution)
        self.assertEqual(result.termination, "TIME_BUDGET")
        self.assertEqual(len(result.evaluated_decisions), 9)
        self.assertEqual({d.package_size for d in result.evaluated_decisions},
                         {f"{a}-for-{b}" for a, b in SHAPES})
        self.assertEqual(sum(c.attempted for c in result.shape_coverage), 10)
        self.assertEqual(sum(c.evaluated for c in result.shape_coverage), 9)
        self.assertGreater(sum(c.unevaluated for c in result.shape_coverage), 0)
        self.assertTrue(all(c.status != "EXHAUSTED" for c in result.shape_coverage
                            if c.evaluated + c.errors < c.eligible))

    def test_negotiation_preserves_counter_and_requires_only_partner_value_failure(self):
        result = run(inputs(), max_exact=1, max_large_exact=0)
        d = result.evaluated_decisions[0]
        gates = (DecisionGate("complete_evidence", True, "==", True, True, "complete"),
                 DecisionGate("partner_market_delta", -10.482, ">=", -5, False, "partner value"))
        d = replace(d, package_verdict="COUNTER", accepted=False, complete_and_legal=True,
            intrinsic_outcome="WIN", decision_axes=replace(d.decision_axes, label="COUNTER", gates=gates),
            user_weighted_lineup_delta=6.485, partner_weighted_lineup_delta=6.434,
            partner_plausible=True, received_asset_dropped=False, consolidation=None,
            market_fairness=replace(d.market_fairness, mode="CURRENT_MARKET", status="FAIR", within_band=True))
        self.assertEqual(idea_status(d, minimum_gain=0.5), "NEGOTIATION_CANDIDATE")
        self.assertEqual(d.package_verdict, "COUNTER")
        self.assertEqual(idea_status(d, minimum_gain=0.5, partner_assets_used=False), "COUNTEROFFER_IDEA")
        self.assertEqual(idea_status(replace(d, complete_and_legal=False), minimum_gain=0.5), None)
        self.assertEqual(idea_status(replace(d, partner_weighted_lineup_delta=0), minimum_gain=0.5), "COUNTEROFFER_IDEA")
        self.assertEqual(idea_status(replace(d, package_verdict="DECLINE"), minimum_gain=0.5), None)
        self.assertEqual(idea_status(replace(d, user_weighted_lineup_delta=0.2), minimum_gain=0.5), "COUNTEROFFER_IDEA")
        self.assertIn("minimum_lineup_gain", finder.failed_checks(replace(d, user_weighted_lineup_delta=0.2), 0.5))
        self.assertIsNone(idea_status(replace(d, accepted=True, market_fairness=replace(d.market_fairness, mode="ECR-PROXY")), minimum_gain=0.5))

    def test_repairs_are_unique_one_edit_and_bounded_to_three_assets(self):
        pairs = tuple(one_edit_packages(("a", "b"), ("x",), ("a", "b", "c", "d"), ("x", "y", "z", "w")))
        self.assertEqual(len(pairs), len(set(pairs)))
        self.assertTrue(all(1 <= len(s) <= 3 and 1 <= len(r) <= 3 for s, r in pairs))
        self.assertIn((("a", "b", "c"), ("x",)), pairs)
        self.assertIn((("a",), ("x",)), pairs)
        self.assertIn((("a", "b"), ("y",)), pairs)
        self.assertTrue(all((s == ("a", "b")) != (r == ("x",)) for s, r in pairs))

    def test_counter_repairs_reuse_the_exact_evaluator_and_keep_raw_failures(self):
        snapshot, projections, selected, ecr, market, targets = inputs()
        original = finder.evaluate_trade
        calls = []
        def counted(*args, **kwargs):
            package = args[1]
            calls.append((tuple(a.player_id for a in package.from_a), tuple(a.player_id for a in package.from_b)))
            return original(*args, **kwargs)
        with patch.object(finder, "evaluate_trade", side_effect=counted):
            result = find_trade_packages(snapshot, projections=projections, selected_board=selected,
                market_ecr_board=ecr, trade_market=market, target_result=targets,
                config=optimizer_config(), options=replace(permissive_options(), partner_market_floor=10000),
                scope=resolve_scope(snapshot, "2"), execution_policy=FinderExecutionPolicy(repairs_per_counter=2),
                max_exact=3, max_large_exact=3)
        self.assertGreater(result.repair_evaluated, 0)
        self.assertEqual(len(calls), len(set(calls)))
        by_hash = {d.evaluation_hash: d for d in result.evaluated_decisions}
        for idea in result.ideas:
            self.assertLessEqual(len(idea.repairs), 2)
            for repair in idea.repairs:
                self.assertIn(repair.evaluation_hash, by_hash)
                self.assertEqual(repair.package_verdict, by_hash[repair.evaluation_hash].package_verdict)

    def test_ranking_preserves_tiers_and_opponent_representatives(self):
        result = run(inputs(), max_exact=1, max_large_exact=0)
        base = result.ideas[0]
        rows = (
            replace(base, status="COUNTEROFFER_IDEA", decision=replace(base.decision, opponent_roster_id="2", user_weighted_lineup_delta=100)),
            replace(base, status="RECOMMENDED", decision=replace(base.decision, opponent_roster_id="2", user_weighted_lineup_delta=5)),
            replace(base, status="NEGOTIATION_CANDIDATE", decision=replace(base.decision, opponent_roster_id="3", user_weighted_lineup_delta=10)),
        )
        ranked = rank_ideas(rows, replace(result.scope, opponent_roster_ids=("2", "3")), 2)
        self.assertEqual(tuple(i.status for i in ranked), ("RECOMMENDED", "NEGOTIATION_CANDIDATE"))
        self.assertEqual({i.decision.opponent_roster_id for i in ranked}, {"2", "3"})

    def test_cache_is_run_bound_and_options_bound(self):
        calls = []
        @cached
        def calculation(roster, options):
            calls.append((set(roster), options))
            return options.partner_market_floor
        first, second = permissive_options(), replace(permissive_options(), partner_market_floor=-5)
        with search_execution(SearchExecution(5, "snapshot-A")):
            self.assertEqual(calculation({"a"}, first), -100)
            calculation({"a"}, first)
            self.assertEqual(calculation({"a"}, second), -5)
        with search_execution(SearchExecution(5, "snapshot-B")):
            calculation({"a"}, first)
        self.assertEqual(len(calls), 3)

    def test_price_index_never_prunes_an_accepted_band_pair(self):
        import random
        rng = random.Random(1315)
        for _ in range(2000):
            sent, received = (round(rng.uniform(-10, 100), 6) for _ in range(2))
            ratio = rng.choice((0, 0.12, 0.35, 0.99, 1.5))
            floor = rng.choice((0, 2, 6))
            premium = rng.choice((1.0, 1.05))
            adjusted = round(received + round(received * (premium - 1), 6), 6)
            allowed = round(max(floor, ratio * max(sent, adjusted, 1)), 6)
            if abs(round(adjusted - sent, 6)) <= allowed:
                low, high = finder._price_range(sent, ratio, floor, premium)
                self.assertLessEqual(low, received)
                self.assertGreaterEqual(high, received)

    def test_cli_and_honest_fewer_than_ten(self):
        args = build_parser().parse_args(["trade", "search", "fixture", "--opponent", "2", "--time-budget-seconds", "15"])
        self.assertEqual((args.opponent, args.time_budget_seconds), ("2", 15))
        result = run(inputs(), max_exact=1, max_large_exact=0)
        self.assertLess(len(result.ideas), 10)
        self.assertEqual(rank_ideas(result.ideas, result.scope, 10), result.ideas)
        for seconds in (0, -1, float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                SearchExecution(seconds, "binding")


if __name__ == "__main__":
    unittest.main()
