import unittest
import json
import tempfile
from dataclasses import replace
from datetime import datetime, timezone, timedelta
from pathlib import Path
from types import SimpleNamespace

from roster_theory.core.models import Player
from roster_theory.waiver.evaluation import PlayerValueInput
from roster_theory.waiver.priority import WaiverPriorityWeights, build_waiver_priority_scores, _waiver_wire_ranks
from roster_theory.waiver.specialists import specialist_performance
from roster_theory.waiver_inputs import _performance_evidence, _rank_by_position
from roster_theory.waiver.policy import load_waiver_policy, apply_waiver_policy
from roster_theory.waiver.service import _best_waiver_reason
from roster_theory.waiver.evaluation import fresh_rank_dominates
from tests import test_waiver_policy as policy_fixtures
from tests.test_waiver_priority import waiver_evidence


class RankingSpecialistTests(unittest.TestCase):
    def scores(self, position, ranks, owned=False):
        return build_waiver_priority_scores(
            players=tuple(Player(str(i), str(i), (position,)) for i in range(len(ranks))),
            values=tuple(PlayerValueInput(str(i), 0, 0, 0, current_week_position_rank=r)
                         for i, r in enumerate(ranks)),
            owner_by_player={str(i): "1" for i in range(len(ranks))} if owned else {},
            waiver_wire_evidence=None,
        )

    def test_explicit_position_boundaries_and_irrelevant_weekly_tail(self):
        for position, cap in (("RB", 50), ("WR", 50), ("QB", 24), ("TE", 24), ("K", 16), ("DST", 16)):
            with self.subTest(position=position):
                short = self.scores(position, [cap])
                long = self.scores(position, [cap, cap + 1, 1000])
                self.assertEqual(short["0"], long["0"])
                self.assertEqual(short["0"].components[0].scope_size, cap)
                self.assertFalse(long["1"].components)
                self.assertIn(("WEEKLY", "OUTSIDE_WEEKLY_EVIDENCE_CAP"), long["1"].missing_signals)

    def test_nonfinite_weights_rejected(self):
        for weight in (float("nan"), float("inf"), -float("inf")):
            with self.assertRaises(ValueError):
                WaiverPriorityWeights(weekly=weight)

    def evidence(self, add=17, drop=31, games=8, weight=.75, **changes):
        args = dict(add_rank=4, drop_rank=10, add_points=add, drop_points=drop,
                    add_samples=games, drop_samples=games, weight=weight, prior_games=2)
        args.update(changes)
        return specialist_performance(**args)

    def test_scale_invariance_and_more_production_influence_for_k(self):
        first = self.evidence()
        self.assertLess(first.score, 0)
        self.assertAlmostEqual(first.score, self.evidence(add=170, drop=310).score)
        self.assertLess(first.score, self.evidence(weight=.4).score)

    def test_early_late_bye_and_unknown_samples(self):
        self.assertGreater(self.evidence(games=1).score, self.evidence(games=12).score)
        self.assertEqual(self.evidence(games=7).confidence,
                         self.evidence(games=8, drop_samples=7).confidence)
        self.assertIsNone(self.evidence(add_samples=None).score)
        self.assertIsNone(self.evidence(drop_samples=0).score)

    def test_equal_totals_and_ranks_do_not_create_upgrade(self):
        self.assertEqual(self.evidence(add=30, drop=30, add_rank=10).score, 0)
        self.assertEqual(self.evidence(add=0, drop=0, add_rank=10).score, 0)
        for ids in (("a", "z"), ("z", "a")):
            players = {pid: Player(pid, pid, ("K",)) for pid in ids}
            self.assertEqual(set(_rank_by_position(dict.fromkeys(ids, 20), players).values()), {1})

    def test_out_of_cap_incumbent_rank_uses_conservative_boundary(self):
        boundary = self.evidence(add=30, drop=15, add_rank=3, drop_rank=16)
        below_cap = self.evidence(add=30, drop=15, add_rank=3, drop_rank=23)
        self.assertEqual(boundary.weekly_advantage, below_cap.weekly_advantage)
        self.assertEqual(boundary.score, below_cap.score)
        self.assertIsNone(self.evidence(add_rank=17, drop_rank=23).score)

    def test_defense_preserves_full_population_rank_gap_without_admitting_tail_targets(self):
        result = self.evidence(add=25, drop=32, games=3, weight=.15,
                               add_rank=16, drop_rank=23, rank_population=32)
        self.assertAlmostEqual(result.weekly_advantage, 7 / 31)
        self.assertGreater(result.score, 0)
        self.assertIsNone(self.evidence(add_rank=17, drop_rank=23, rank_population=32).score)
        self.assertIsNone(self.evidence(add_rank=16, drop_rank=33, rank_population=32).score)
        self.assertLess(self.evidence(add=100, drop=100, add_rank=16,
                                     drop_rank=1, rank_population=32).score, 0)

    def test_weekly_defense_weight_overcomes_past_total_and_future_disadvantages(self):
        policy = replace(load_waiver_policy(policy_fixtures.POLICY_PATH), dst_season_points_weight=.15)
        original = self.specialist("DST", current_delta=2, future_delta=-7,
                                  current_rank=9, incumbent_season_points=60, target_season_points=20)
        result = apply_waiver_policy(original, policy)
        self.assertEqual(result.decision_label, "ADD NOW")
        evidence = result.decision.specialist_evidence
        self.assertEqual(evidence["basis"], "PROJECTION")
        self.assertEqual(evidence["current_week_weight"], .85)
        self.assertLess(result.candidates[0].dst_streaming.weighted_advantage, 0)
        self.assertIn("+2.00", _best_waiver_reason(result, result.candidates[0]))
        poor_week = self.specialist("DST", current_delta=-2, future_delta=7,
                                   current_rank=1, incumbent_season_points=20, target_season_points=60)
        self.assertNotIn(apply_waiver_policy(poor_week, policy).decision_label, {"ADD NOW", "CLAIM", "ACQUIRE"})

    def test_current_defense_projection_does_not_require_complete_future_forecasts(self):
        result = self.specialist("DST", current_delta=2,
            future_projection_status="scoring_incomplete_v1:missing_statistic=pts_allow")
        self.assertFalse(result.projection_inputs_complete)
        self.assertTrue(result.candidates[0].current_week_projection_complete)
        self.assertEqual(result.decision_label, "ADD NOW")
        self.assertEqual(result.decision.decision_path, "DST_CURRENT_WEEK_STREAM")

    def test_defense_rank_fallback_does_not_buy_a_worse_week_using_past_points(self):
        original = self.specialist("DST", current_delta=0, current_rank=12,
                                  incumbent_season_points=20, target_season_points=80)
        selected = replace(original.candidates[0], current_week_projection_complete=False)
        result = apply_waiver_policy(replace(original, candidates=(selected,)),
                                    load_waiver_policy(policy_fixtures.POLICY_PATH))
        self.assertNotIn(result.decision_label, {"ADD NOW", "CLAIM", "ACQUIRE"})

    def test_equal_panel_ranks_keep_ties_independent_of_ids(self):
        original = waiver_evidence()
        for ids in (("a", "z"), ("z", "a")):
            tied = replace(original, ranking_source="TRUSTED_EXPERT_PANEL",
                           players=tuple(replace(row, player_id=pid, market_overall_rank=1)
                                         for row, pid in zip(original.players, ids)))
            ranks, _ = _waiver_wire_ranks(tied)
            self.assertEqual({rank for rank, source in ranks.values()}, {1})

    def test_league_scoring_samples_and_capture_are_preserved(self):
        players = {pid: Player(pid, pid, ("K",)) for pid in ("a", "b")}
        client = SimpleNamespace(
            season_stats=lambda season: {"a": {"fgm": 3, "gp": 2}, "b": {"fgm": 2, "gp": 1}},
            weekly_stats=lambda season, week: {"a": {"fgm": 1, "gp": 1}, "b": {"gp": 0}}
                if week == 1 else {"a": {"fgm": 2, "gp": 1}, "b": {"fgm": 2, "gp": 1}},
        )
        now = datetime(2026, 9, 20, tzinfo=timezone.utc)
        results = []
        for scale in (3, 5):
            evidence, _ = _performance_evidence(client=client, league_id="fixture", season=2026, current_week=3,
                players=players, scoring={"fgm": scale}, as_of=now)
            self.assertEqual(evidence["b"]["season_sample_size"], 1)
            self.assertEqual(evidence["b"]["recent_sample_size"], 1)
            self.assertEqual(evidence["a"]["performance_as_of"], now)
            results.append(evidence["a"]["season_points"])
        self.assertEqual(results, [9, 15])

    def test_value_metadata_survives_replacement(self):
        value = PlayerValueInput("a", 0, 0, 0, season_sample_size=2, recent_sample_size=1)
        self.assertEqual(replace(value, raw_projection=1).season_sample_size, 2)

    def test_fresh_override_cannot_use_out_of_cap_weekly_rank(self):
        add = PlayerValueInput("add", 0, 0, 20, current_week_position_rank=50,
                               rest_of_season_position_rank=10, long_term_value_horizon="PRESEASON")
        drop = replace(add, player_id="drop", current_week_position_rank=51, rest_of_season_position_rank=20)
        self.assertFalse(fresh_rank_dominates(add, drop, same_position=True, position="RB"))
        self.assertFalse(fresh_rank_dominates(replace(add, current_week_position_rank=24),
                         replace(drop, current_week_position_rank=25), same_position=True, position="QB"))

    def specialist(self, position="K", **kwargs):
        return policy_fixtures.WaiverDecisionPolicyTests().special_team_evaluation(position, **kwargs)

    def test_projection_gain_cannot_bypass_negative_production_balance(self):
        for position in ("K", "DST"):
            result = self.specialist(position, current_delta=2, current_rank=9,
                                     incumbent_season_points=60, target_season_points=20)
            self.assertNotIn(result.decision_label, {"ADD NOW", "CLAIM", "ACQUIRE"})
            self.assertTrue(result.decision.specialist_evidence["projection_stream_pass"])
            self.assertFalse(result.decision.specialist_evidence["production_guard"])

    def test_rank_performance_reason_does_not_claim_projection_gain(self):
        result = self.specialist("DST", current_delta=-1, ros_rank=2)
        selected = replace(result.candidates[0], current_week_projection_complete=False)
        result = apply_waiver_policy(replace(result, candidates=(selected,)),
                                     load_waiver_policy(policy_fixtures.POLICY_PATH))
        self.assertEqual(result.decision.decision_path, "DST_RANK_PERFORMANCE")
        reason = _best_waiver_reason(result, result.candidates[0])
        self.assertIn("projections do not establish", reason)
        self.assertFalse(result.decision.specialist_evidence["historically_calibrated"])
        self.assertNotIn("four-week", " ".join(result.decision.reversal_conditions))

    def test_missing_or_stale_samples_do_not_invent_fallback(self):
        original = self.specialist(current_delta=0)
        policy = load_waiver_policy(policy_fixtures.POLICY_PATH)
        for changes in ({"season_add_sample_size": None},
                        {"performance_add_as_of": original.evaluated_at - timedelta(days=4)},
                        {"performance_add_as_of": original.evaluated_at + timedelta(hours=1)}):
            selected = original.candidates[0]
            selected = replace(selected, ownership=replace(selected.ownership, **changes))
            result = apply_waiver_policy(replace(original, candidates=(selected,)), policy)
            self.assertNotEqual(result.decision_label, "ADD NOW")
            self.assertFalse(result.decision.specialist_evidence["performance_complete"])

    def test_projection_only_path_discloses_missing_samples(self):
        original = self.specialist(current_delta=2)
        selected = original.candidates[0]
        selected = replace(selected, ownership=replace(selected.ownership, season_add_sample_size=None))
        result = apply_waiver_policy(replace(original, candidates=(selected,)), load_waiver_policy(policy_fixtures.POLICY_PATH))
        self.assertEqual(result.decision.decision_path, "K_STREAM")
        self.assertIn("missing game counts", result.strongest_uncertainty)

    def test_specialist_cap_and_projection_coverage_are_independent_gates(self):
        outside = self.specialist(current_delta=2, current_rank=17)
        self.assertNotEqual(outside.decision_label, "ADD NOW")
        original = self.specialist(current_delta=0)
        no_projections = apply_waiver_policy(replace(original, projection_inputs_complete=False),
                                             load_waiver_policy(policy_fixtures.POLICY_PATH))
        self.assertEqual(no_projections.decision.decision_path, "K_RANK_PERFORMANCE")
        self.assertFalse(no_projections.decision.specialist_evidence["projection_stream_pass"])

    def test_explicit_normalized_overrides_and_finite_validation(self):
        base = json.loads(policy_fixtures.POLICY_PATH.read_text())
        bad = ({"method": "unknown"}, {"kicker_season_points_weight": 2},
               {"dst_season_points_weight": .9}, {"prior_games": 0},
               {"prior_games": float("nan")}, {"prior_games": "inf"},
               {"elite_dst_ros_rank_cutoff": "inf"}, {"unknown": 1})
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "policy.json"
            for override in bad:
                path.write_text(json.dumps({**base, "special_teams": {**base["special_teams"], **override}}))
                with self.subTest(override=override), self.assertRaises(ValueError):
                    load_waiver_policy(path)
            special = {**base["special_teams"], "kicker_season_points_weight": .8, "dst_season_points_weight": .3, "prior_games": 3}
            path.write_text(json.dumps({**base, "special_teams": special}))
            policy = load_waiver_policy(path)
            self.assertEqual((policy.kicker_season_points_weight, policy.dst_season_points_weight, policy.specialist_prior_games), (.8, .3, 3))
            del special["method"]
            path.write_text(json.dumps({**base, "special_teams": special}))
            with self.assertRaisesRegex(ValueError, "migration"):
                load_waiver_policy(path)

    def test_independent_league_defaults_and_overrides(self):
        alpha = load_waiver_policy(policy_fixtures.POLICY_PATH)
        beta = load_waiver_policy(policy_fixtures.LEAGUE_BETA_POLICY_PATH)
        self.assertNotEqual(alpha.league_key, beta.league_key)
        self.assertEqual(alpha.kicker_season_points_weight, beta.kicker_season_points_weight)
        result = self.specialist(current_delta=2)
        independent = self.specialist(current_delta=2, current_rank=9,
                                      incumbent_season_points=60, target_season_points=20,
                                      policy_path=policy_fixtures.LEAGUE_BETA_POLICY_PATH)
        self.assertEqual(independent.policy_hash, beta.policy_hash)
        self.assertEqual(result.decision_label, "ADD NOW")
        self.assertNotEqual(independent.decision_label, "ADD NOW")
        with self.assertRaises(ValueError):
            apply_waiver_policy(result, beta)


if __name__ == "__main__":
    unittest.main()
