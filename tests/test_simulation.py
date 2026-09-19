import random
import unittest
from dataclasses import replace

from roster_theory.assistant import recommend_available
from roster_theory.draft_analysis import HistoricalPositionCurves
from roster_theory.simulation import (
    Player,
    RankVorpCurve,
    _construction_filtered_available,
    _construction_policy_config,
    _deterministic_pick_roster_value,
    _expected_next_by_position,
    _elite_te_sequence_score_gap,
    _experimental_profile,
    _near_tie_scarcity_config,
    _opponent_pick,
    _position_guardrail_config,
    _promote_elite_te_sequence_candidate,
    _promote_close_construction_candidate,
    _promote_near_tie_scarcity_candidate,
    _promote_turn_aware_qb_deferral,
    _reconciled_pick_policy,
    _two_pick_path_value,
    _top3_dst_guard_candidates,
    acquisition_adp_metadata,
    apply_acquisition_adp,
    bounded_multi_turn_rollout,
    compare_strategies,
    deterministic_roster_strength,
    expert_ordered_projection_players,
    expected_roster_score,
    fit_rank_vorp_curve,
    market_replacement_baselines,
    next_pick_for_slot,
    opponent_position_stress_rates,
    rank_user_candidates,
    rank_adjusted_player,
    rank_adjusted_players,
    roster_score,
    snake_slot,
    survival_probability,
    weekly_use_roster_strength,
)


class SimulationTests(unittest.TestCase):
    @staticmethod
    def player(
        name: str,
        position: str,
        *,
        projection: float,
        adp: float,
        vols: float,
        rank: float,
        team: str = "",
    ) -> Player:
        return Player(name, name, position, projection, adp, vols, rank, team=team)

    def test_snake_order(self) -> None:
        self.assertEqual([snake_slot(pick, 4) for pick in range(1, 9)], [1, 2, 3, 4, 4, 3, 2, 1])
        self.assertEqual(next_pick_for_slot(1, 1, 4), 8)
        self.assertEqual(next_pick_for_slot(4, 4, 4), 5)

    def test_top_three_dst_guard_requires_completed_starters_and_low_survival(self) -> None:
        roster = [
            self.player("QB", "QB", projection=250, adp=10, vols=80, rank=10),
            self.player("RB1", "RB", projection=220, adp=11, vols=70, rank=11),
            self.player("RB2", "RB", projection=210, adp=12, vols=60, rank=12),
            self.player("WR1", "WR", projection=200, adp=13, vols=50, rank=13),
            self.player("WR2", "WR", projection=190, adp=14, vols=40, rank=14),
            self.player("TE", "TE", projection=180, adp=15, vols=30, rank=15),
            self.player("FLEX1", "RB", projection=170, adp=16, vols=20, rank=16),
            self.player("FLEX2", "WR", projection=160, adp=17, vols=10, rank=17),
        ]
        available = [
            self.player("Houston", "DST", projection=0, adp=110, vols=0, rank=1, team="HOU"),
            self.player("Seattle", "DST", projection=0, adp=126, vols=0, rank=2, team="SEA"),
            self.player("Rams", "DST", projection=0, adp=102, vols=0, rank=3, team="LAR"),
            self.player("Denver", "DST", projection=0, adp=100, vols=0, rank=4, team="DEN"),
        ]
        common = dict(
            available=available,
            pick_no=97,
            round_no=9,
            teams=12,
            draft_slot=1,
            simulation_rounds=15,
            roster_positions=[
                "QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "FLEX",
                "K", "DEF", "BN", "BN", "BN", "BN", "BN",
            ],
        )

        eligible = _top3_dst_guard_candidates(roster=roster, **common)

        self.assertEqual({player.team for player in eligible}, {"HOU", "LAR"})
        self.assertEqual(
            _top3_dst_guard_candidates(roster=roster[:-1], **common),
            [],
        )
        self.assertEqual(
            _top3_dst_guard_candidates(roster=roster, **{**common, "round_no": 8}),
            [],
        )

    def test_offline_dst_profiles_preserve_live_primary_and_stay_simulation_only(self) -> None:
        baseline = _experimental_profile(
            "half_ppr_reconciled_live_specialist_gate_horizon_guard", 1
        )
        challenger = _experimental_profile(
            "half_ppr_reconciled_top3_dst_guard_horizon_guard", 1
        )

        self.assertEqual(
            baseline["offline_specialist_gate"]["mode"],
            "live_specialist_gate",
        )
        self.assertEqual(
            challenger["offline_specialist_gate"],
            {
                "mode": "top3_dst_guard",
                "minimum_round": 9,
                "maximum_next_turn_survival": 0.5,
                "maximum_user_dst_rank": 3,
                "requires_skill_starters_complete": True,
            },
        )

    def test_koerner_rb_screen_requires_anchor_and_expires_after_round_eight(self) -> None:
        anchor = self.player("Anchor", "RB", projection=200, adp=8, vols=80, rank=8)
        dead_zone = self.player(
            "Dead Zone", "RB", projection=160, adp=40, vols=50, rank=20
        )
        late_rb = self.player("Late RB", "RB", projection=120, adp=90, vols=25, rank=35)
        receiver = self.player("Receiver", "WR", projection=170, adp=42, vols=48, rank=18)
        config = _construction_policy_config("half_ppr_reconciled_koerner_rb")

        without_anchor = _construction_filtered_available(
            [dead_zone, late_rb, receiver], [], 5, config
        )
        with_anchor = _construction_filtered_available(
            [dead_zone, late_rb, receiver], [anchor], 5, config
        )
        after_punt_window = _construction_filtered_available(
            [dead_zone, late_rb, receiver], [anchor], 9, config
        )

        self.assertIn(dead_zone, without_anchor)
        self.assertNotIn(dead_zone, with_anchor)
        self.assertIn(late_rb, with_anchor)
        self.assertIn(dead_zone, after_punt_window)

    def test_league_beta_position_mix_challenger_forces_only_at_deadline(self) -> None:
        rb = self.player("RB", "RB", projection=180, adp=40, vols=50, rank=12)
        wr = self.player("WR", "WR", projection=180, adp=40, vols=50, rank=12)
        config = _construction_policy_config("half_ppr_reconciled_rb3_by6")

        early = _construction_filtered_available([rb, wr], [], 3, config)
        deadline = _construction_filtered_available([rb, wr], [], 4, config)
        nearly_complete = _construction_filtered_available(
            [rb, wr], [rb, rb], 6, config
        )

        self.assertEqual(early, [rb, wr])
        self.assertEqual(deadline, [rb])
        self.assertEqual(nearly_complete, [rb])

    def test_koerner_onesie_screen_punts_early_and_blocks_qb2_te2(self) -> None:
        qb = self.player("QB", "QB", projection=300, adp=50, vols=50, rank=6)
        elite_te = self.player("Elite TE", "TE", projection=180, adp=20, vols=60, rank=2)
        other_te = self.player("Other TE", "TE", projection=150, adp=60, vols=35, rank=5)
        receiver = self.player("Receiver", "WR", projection=170, adp=42, vols=48, rank=18)
        config = _construction_policy_config(
            "half_ppr_reconciled_koerner_onesie"
        )

        early = _construction_filtered_available(
            [qb, elite_te, other_te, receiver], [], 5, config
        )
        filled = _construction_filtered_available(
            [qb, elite_te, other_te, receiver], [qb, elite_te], 10, config
        )

        self.assertNotIn(qb, early)
        self.assertIn(elite_te, early)
        self.assertNotIn(other_te, early)
        self.assertNotIn(qb, filled)
        self.assertNotIn(elite_te, filled)
        self.assertNotIn(other_te, filled)
        self.assertIn(receiver, filled)

    def test_locked_ten_team_policy_combines_narrow_guardrail_and_onesie_caps(self) -> None:
        self.assertEqual(
            _construction_policy_config("half_ppr_reconciled_locked10"),
            {"maximum_qb": 1, "maximum_te": 1},
        )
        self.assertEqual(
            _position_guardrail_config("half_ppr_reconciled_locked10"),
            {"method": "position_rank_tolerance", "tolerance": 0.5},
        )

    def test_elite_te_sequence_challenger_requires_a_close_early_top_two_te(self) -> None:
        elite_te = self.player("Elite TE", "TE", projection=190, adp=22, vols=65, rank=2)
        receiver = self.player("Receiver", "WR", projection=210, adp=18, vols=75, rank=8)
        context = {
            "teams": 10,
            "draft_slot": 4,
            "roster_positions": (
                "QB", "RB", "RB", "WR", "WR", "TE", "WRRB_FLEX", "K", "DEF",
                "BN", "BN", "BN", "BN", "BN", "BN",
            ),
        }
        close = [
            {"_player": receiver, "final_score": 110.0},
            {"_player": elite_te, "final_score": 101.0},
        ]
        far = [
            {"_player": receiver, "final_score": 130.0},
            {"_player": elite_te, "final_score": 101.0},
        ]

        promoted = _promote_elite_te_sequence_candidate(
            close, [], 3, 10.0, **context
        )
        self.assertEqual(promoted[0]["_player"], elite_te)
        self.assertEqual(promoted[0]["sequence_option_score_gap"], 9.0)
        self.assertEqual(
            _promote_elite_te_sequence_candidate(
                far, [], 3, 10.0, **context
            )[0]["_player"],
            receiver,
        )
        self.assertEqual(
            _promote_elite_te_sequence_candidate(
                close, [], 5, 10.0, **context
            )[0]["_player"],
            receiver,
        )
        self.assertEqual(
            _promote_elite_te_sequence_candidate(
                close, [elite_te], 3, 10.0, **context
            )[0]["_player"],
            receiver,
        )
        self.assertEqual(
            _promote_elite_te_sequence_candidate(
                close,
                [],
                3,
                10.0,
                **{**context, "teams": 12},
            )[0]["_player"],
            receiver,
        )
        self.assertEqual(
            _promote_elite_te_sequence_candidate(
                close,
                [],
                3,
                10.0,
                **{**context, "draft_slot": 5},
            )[0]["_player"],
            receiver,
        )
        self.assertEqual(
            _position_guardrail_config("half_ppr_reconciled_tol05_elite_te10"),
            {"method": "position_rank_tolerance", "tolerance": 0.5},
        )
        self.assertEqual(
            _elite_te_sequence_score_gap("half_ppr_reconciled_tol05"), 15.0
        )
        self.assertEqual(
            _reconciled_pick_policy("half_ppr_reconciled_tol05"),
            ("half_ppr_team_w20_reserve_cap", 0.5, True),
        )
        self.assertEqual(
            _position_guardrail_config("half_ppr_reconciled_tol05_w50"),
            {"method": "position_rank_tolerance", "tolerance": 0.5},
        )
        self.assertEqual(
            _elite_te_sequence_score_gap("half_ppr_reconciled_tol05_w50"),
            15.0,
        )
        self.assertEqual(
            _experimental_profile("half_ppr_reconciled_tol05_w50", 4)
            ["total_team_bench_weight"],
            0.5,
        )
        upside_profile = _experimental_profile(
            "half_ppr_team_w20_u50", 4
        )
        self.assertEqual(upside_profile["total_team_bench_weight"], 0.2)
        self.assertEqual(upside_profile["upside_weight"], 0.5)
        self.assertTrue(upside_profile["starter_deferral"])
        endgame_profile = _experimental_profile(
            "half_ppr_reconciled_tol05_w20_endgame", 4
        )
        self.assertEqual(endgame_profile["total_team_bench_weight"], 0.2)
        self.assertTrue(endgame_profile["late_round_plan"])
        self.assertIsNone(
            _elite_te_sequence_score_gap(
                "half_ppr_reconciled_tol05_no_sequence"
            )
        )

    def test_near_tie_scarcity_challenger_reorders_only_a_reciprocal_top_two(self) -> None:
        positions = (
            "QB", "RB", "RB", "WR", "WR", "TE", "WRRB_FLEX", "K", "DEF",
            "BN", "BN", "BN", "BN", "BN", "BN",
        )
        leader = {
            "player_name": "Jayden Daniels",
            "final_score": 92.675,
            "next_pick_survival": 0.762,
            "two_pick_path_value": 92.675,
            "expected_next_path_player": "Luther Burden",
            "roster_need": "starter",
        }
        challenger = {
            "player_name": "Luther Burden",
            "final_score": 92.346,
            "next_pick_survival": 0.584,
            "two_pick_path_value": 92.346,
            "expected_next_path_player": "Jayden Daniels",
            "roster_need": "starter",
        }

        promoted = _promote_near_tie_scarcity_candidate(
            [leader, challenger],
            0.5,
            0.15,
            teams=10,
            draft_slot=4,
            roster_positions=positions,
        )

        self.assertEqual(promoted[0]["player_name"], "Luther Burden")
        self.assertEqual(promoted[0]["near_tie_scarcity_score_gap"], 0.329)
        self.assertEqual(promoted[0]["near_tie_scarcity_survival_gap"], 0.178)
        self.assertTrue(promoted[1]["near_tie_scarcity_displaced"])

    def test_near_tie_scarcity_challenger_is_bounded(self) -> None:
        positions = (
            "QB", "RB", "RB", "WR", "WR", "TE", "WRRB_FLEX", "K", "DEF",
            "BN", "BN", "BN", "BN", "BN", "BN",
        )

        def rows() -> list[dict[str, object]]:
            return [
                {
                    "player_name": "Leader",
                    "final_score": 100.0,
                    "next_pick_survival": 0.75,
                    "two_pick_path_value": 100.0,
                    "expected_next_path_player": "Challenger",
                    "roster_need": "starter",
                },
                {
                    "player_name": "Challenger",
                    "final_score": 99.0,
                    "next_pick_survival": 0.55,
                    "two_pick_path_value": 99.0,
                    "expected_next_path_player": "Leader",
                    "roster_need": "starter",
                },
            ]

        common = {
            "maximum_score_gap": 0.5,
            "minimum_survival_gap": 0.15,
            "teams": 10,
            "draft_slot": 4,
            "roster_positions": positions,
        }
        self.assertEqual(
            _promote_near_tie_scarcity_candidate(rows(), **common)[0]["player_name"],
            "Leader",
        )
        small_survival_gap = rows()
        small_survival_gap[1]["final_score"] = 99.75
        small_survival_gap[1]["next_pick_survival"] = 0.65
        self.assertEqual(
            _promote_near_tie_scarcity_candidate(
                small_survival_gap, **common
            )[0]["player_name"],
            "Leader",
        )
        nonreciprocal = rows()
        nonreciprocal[1]["final_score"] = 99.75
        nonreciprocal[1]["expected_next_path_player"] = "Someone Else"
        self.assertEqual(
            _promote_near_tie_scarcity_candidate(
                nonreciprocal, **common
            )[0]["player_name"],
            "Leader",
        )
        bench_depth = rows()
        bench_depth[1]["final_score"] = 99.75
        bench_depth[1]["roster_need"] = "bench_depth"
        self.assertEqual(
            _promote_near_tie_scarcity_candidate(
                bench_depth, **common
            )[0]["player_name"],
            "Leader",
        )
        wrong_room = rows()
        wrong_room[1]["final_score"] = 99.75
        self.assertEqual(
            _promote_near_tie_scarcity_candidate(
                wrong_room, **{**common, "draft_slot": 5}
            )[0]["player_name"],
            "Leader",
        )

    def test_near_tie_scarcity_policy_preserves_live_policy_components(self) -> None:
        policy = "half_ppr_reconciled_tol05_scarcity05_surv15"
        self.assertEqual(
            _near_tie_scarcity_config(policy),
            {"maximum_score_gap": 0.5, "minimum_survival_gap": 0.15},
        )
        self.assertEqual(
            _reconciled_pick_policy(policy),
            ("half_ppr_team_w20_reserve_cap", 0.5, True),
        )
        self.assertEqual(
            _position_guardrail_config(policy),
            {"method": "position_rank_tolerance", "tolerance": 0.5},
        )
        self.assertEqual(_elite_te_sequence_score_gap(policy), 15.0)

        board = [
            {
                "player_key": f"shadow-{index}",
                "player_name": f"Shadow {index}",
                "position": ("QB", "RB", "WR", "TE")[(index - 1) % 4],
                "projected_points": 300 - index,
                "adp": index,
                "vbd": 100 - index,
                "rank_score": index,
                "overall_rank_score": index,
                "overall_ecr": index,
            }
            for index in range(1, 49)
        ]
        summary = compare_strategies(
            board,
            teams=2,
            draft_slot=1,
            roster_positions=["QB", "RB", "WR", "TE"],
            rounds=4,
            trials=1,
            strategies=[policy],
        )[0]
        self.assertEqual(summary["near_tie_scarcity"]["promotions"], 0)
        self.assertEqual(
            summary["near_tie_scarcity"]["config"],
            {"maximum_score_gap": 0.5, "minimum_survival_gap": 0.15},
        )

    def test_survival_declines_with_target(self) -> None:
        near = survival_probability(30, 10, 20)
        far = survival_probability(30, 10, 40)
        self.assertGreater(near, far)

    def test_missing_overall_adp_does_not_use_position_rank(self) -> None:
        player = Player.from_mapping(
            {
                "player_key": "backup-qb",
                "player_name": "Backup QB",
                "position": "QB",
                "projected_points": 100,
                "rank_score": 30,
            }
        )
        self.assertEqual(player.adp, 999.0)

    def test_positional_slot_acquisition_adp_matches_qb_examples(self) -> None:
        current_adps = [19, 37, 45, 50, 55, 60, 71, 77, 78, 85, 90, 95, 100, 103, 107]
        targets = (19, 26, 35, 44, 52, 56, 63, 79, 88, 118, 120, 131, 133, 136, 143)
        players = [
            self.player(
                f"QB{slot}",
                "QB",
                projection=350 - slot,
                adp=adp,
                vols=100 - slot,
                rank=slot,
            )
            for slot, adp in enumerate(current_adps, start=1)
        ]
        history = HistoricalPositionCurves(
            position_picks={"QB": targets},
            draft_end_pick=180,
            source="fixture",
        )
        adjusted = apply_acquisition_adp(players, history, 0.5)
        by_slot = {player.acquisition_position_slot: player for player in adjusted}

        expected = {1: 19.0, 2: 31.5, 7: 67.0, 8: 78.0, 9: 83.0, 10: 101.5, 15: 125.0}
        for slot, acquisition_adp in expected.items():
            self.assertEqual(by_slot[slot].acquisition_pick, acquisition_adp)
            self.assertEqual(by_slot[slot].adp, current_adps[slot - 1])

    def test_acquisition_weights_censor_missing_history_and_preserve_quality(self) -> None:
        players = [
            Player(
                "qb1", "Current QB1", "QB", 300, 5, 80, 1,
                overall_rank_score=10, overall_ecr_rank=11,
            ),
            Player(
                "qb2", "Current QB2", "QB", 280, 6, 70, 2,
                overall_rank_score=20, overall_ecr_rank=21,
            ),
            Player("missing", "Missing QB", "QB", 100, 999, 1, 30),
            Player("rb1", "Current RB", "RB", 200, 4, 60, 1),
        ]
        history = HistoricalPositionCurves(
            position_picks={"QB": (10,), "RB": (3,)},
            draft_end_pick=20,
            source="fixture",
            excluded_user_ids=("absent",),
            exclusion_audit=({"draft_id": "fixture", "excluded_pick_count": 2},),
        )

        raw_weight = apply_acquisition_adp(players, history, 0.0)
        full_weight = apply_acquisition_adp(players, history, 1.0)
        no_history = apply_acquisition_adp(players, None, 0.5)

        self.assertEqual([player.acquisition_pick for player in raw_weight], [5, 6, 999, 4])
        self.assertEqual([player.acquisition_pick for player in full_weight], [10, 21, 999, 3])
        self.assertEqual([player.acquisition_pick for player in no_history], [5, 6, 999, 4])
        no_history_metadata = acquisition_adp_metadata(None, 0.5)
        self.assertFalse(no_history_metadata["history_applied"])
        self.assertEqual(
            no_history_metadata["fallback_state"],
            "history_unavailable_raw_adp",
        )
        history_metadata = acquisition_adp_metadata(history, 0.5)
        self.assertEqual(history_metadata["excluded_user_ids"], ["absent"])
        self.assertEqual(
            history_metadata["exclusion_audit"][0]["excluded_pick_count"],
            2,
        )
        for original, adjusted in zip(players, full_weight):
            self.assertEqual(adjusted.adp, original.adp)
            self.assertEqual(adjusted.projected_points, original.projected_points)
            self.assertEqual(adjusted.vbd, original.vbd)
            self.assertEqual(adjusted.rank_score, original.rank_score)
            self.assertEqual(adjusted.overall_rank_score, original.overall_rank_score)
        for position in ("QB", "RB"):
            curve = [
                player.acquisition_pick
                for player in full_weight
                if player.position == position and player.adp < 999
            ]
            self.assertTrue(all(left <= right for left, right in zip(curve, curve[1:])))
        with self.assertRaises(ValueError):
            apply_acquisition_adp(players, history, 1.01)

    def test_acquisition_adp_drives_all_survival_and_hazard_paths(self) -> None:
        replacement = {"QB": 200, "RB": 100, "WR": 100, "TE": 100}
        next_rb = self.player(
            "Next RB", "RB", projection=180, adp=80, vols=80, rank=2
        )
        adjusted_next_rb = replace(next_rb, acquisition_adp=5)
        raw_fallback = _expected_next_by_position(
            [next_rb], 20, 30, replacement
        )["RB"]
        adjusted_fallback = _expected_next_by_position(
            [adjusted_next_rb], 20, 30, replacement
        )["RB"]
        self.assertGreater(
            raw_fallback["expected_projected_points"],
            adjusted_fallback["expected_projected_points"],
        )

        unavailable_fallback = _expected_next_by_position(
            [next_rb],
            20,
            30,
            replacement,
            survival_overrides={next_rb.key: 0.0},
        )["RB"]
        certain_fallback = _expected_next_by_position(
            [next_rb],
            20,
            30,
            replacement,
            survival_overrides={next_rb.key: 1.0},
        )["RB"]
        self.assertEqual(unavailable_fallback["expected_projected_points"], 100.0)
        self.assertEqual(certain_fallback["expected_projected_points"], 180.0)

        common = dict(
            roster=[], policy="vona", pick_no=20, round_no=5, teams=4,
            draft_slot=4, roster_positions=["RB"], total_user_picks=5,
            replacement_baselines=replacement,
        )
        raw_row = rank_user_candidates(available=[next_rb], **common)[0]
        adjusted_row = rank_user_candidates(available=[adjusted_next_rb], **common)[0]
        self.assertGreater(raw_row["next_pick_survival"], adjusted_row["next_pick_survival"])
        self.assertGreater(adjusted_row["vona"], raw_row["vona"])

        roster = [
            self.player("QB", "QB", projection=280, adp=1, vols=80, rank=1),
            self.player("RB", "RB", projection=200, adp=2, vols=70, rank=1),
            self.player("WR", "WR", projection=190, adp=3, vols=60, rank=1),
        ]
        bench = self.player("Bench RB", "RB", projection=175, adp=4, vols=50, rank=3)
        patient_te = self.player("Patient TE", "TE", projection=170, adp=80, vols=40, rank=1)
        urgent_te = replace(patient_te, acquisition_adp=5)
        raw_path = _two_pick_path_value(
            bench, [bench, patient_te], roster, ["QB", "RB", "WR", "TE"],
            6, 20, 25, (0.05, 0.10, 0.15), replacement,
        )
        adjusted_path = _two_pick_path_value(
            bench, [bench, urgent_te], roster, ["QB", "RB", "WR", "TE"],
            6, 20, 25, (0.05, 0.10, 0.15), replacement,
        )
        self.assertGreater(raw_path[3], adjusted_path[3])

        raw_market = self.player("Raw Market", "WR", projection=200, adp=5, vols=50, rank=1)
        later_market = self.player("Later Market", "RB", projection=190, adp=20, vols=45, rank=2)
        adjusted_raw = replace(raw_market, acquisition_adp=100)
        adjusted_later = replace(later_market, acquisition_adp=1)
        self.assertEqual(
            _opponent_pick(
                [raw_market, later_market], [], 20, 2, random.Random(1)
            ).name,
            "Raw Market",
        )
        self.assertEqual(
            _opponent_pick(
                [adjusted_raw, adjusted_later], [], 20, 2, random.Random(1)
            ).name,
            "Later Market",
        )

    def test_selected_expert_policy_uses_cross_position_rank_not_projection(self) -> None:
        chase = Player(
            "chase", "Ja'Marr Chase", "WR", 215, 3, 79, 1,
            overall_rank_score=2,
        )
        henry = Player(
            "henry", "Derrick Henry", "RB", 256, 13, 118, 6,
            overall_rank_score=13,
        )
        ranked = rank_user_candidates(
            [henry, chase],
            [],
            "standard_expert_consensus",
            pick_no=6,
            round_no=1,
            teams=12,
            draft_slot=6,
            roster_positions=["QB", "RB", "RB", "WR", "WR", "TE", "FLEX"],
            total_user_picks=13,
            replacement_baselines={"QB": 250, "RB": 137, "WR": 136, "TE": 100},
        )
        self.assertEqual(ranked[0]["player_name"], "Ja'Marr Chase")
        self.assertEqual(ranked[0]["selection_basis"], "selected_expert_overall_consensus")

    def test_missing_cross_position_rank_sorts_after_ranked_players(self) -> None:
        missing = Player.from_mapping(
            {
                "player_key": "missing",
                "player_name": "Unranked Player",
                "position": "WR",
                "weighted_overall_rank": "0",
            }
        )
        self.assertEqual(missing.overall_rank_score, 999.0)

    def test_rank_vorp_curve_is_monotone_and_adjustment_follows_disagreement(self) -> None:
        players = [
            Player("p1", "P1", "RB", 200, 1, 100, 1, overall_rank_score=1, overall_ecr_rank=1),
            Player("p2", "P2", "RB", 180, 2, 80, 2, overall_rank_score=2, overall_ecr_rank=2),
            Player("p3", "P3", "RB", 190, 3, 90, 3, overall_rank_score=3, overall_ecr_rank=3),
            Player("p4", "P4", "RB", 150, 4, 50, 4, overall_rank_score=4, overall_ecr_rank=4),
        ]
        curve = fit_rank_vorp_curve(players, {"RB": 100})
        values = [curve.value(rank) for rank in (1, 2, 3, 4)]
        self.assertEqual(curve.observation_count, 4)
        self.assertTrue(all(left >= right for left, right in zip(values, values[1:])))

        promoted = replace(
            players[-1], overall_rank_score=1, overall_ecr_rank=4
        )
        demoted = replace(
            players[0], overall_rank_score=4, overall_ecr_rank=1
        )
        self.assertGreater(
            rank_adjusted_player(promoted, curve, 1.0, {"RB": 100}).projected_points,
            promoted.projected_points,
        )
        self.assertLess(
            rank_adjusted_player(demoted, curve, 1.0, {"RB": 100}).projected_points,
            demoted.projected_points,
        )
        zero_projection = replace(
            promoted, projected_points=0.0, vbd=0.0
        )
        self.assertIs(
            rank_adjusted_player(zero_projection, curve, 1.0, {"RB": 100}),
            zero_projection,
        )

    def test_projection_values_follow_expert_position_order_not_player_projection_order(self) -> None:
        expert_first = Player(
            "expert-first",
            "Expert First",
            "RB",
            190,
            20,
            40,
            1.0,
            overall_rank_score=10,
            overall_ecr_rank=10,
        )
        expert_second = Player(
            "expert-second",
            "Expert Second",
            "RB",
            200,
            21,
            50,
            2.0,
            overall_rank_score=11,
            overall_ecr_rank=11,
        )

        aligned = expert_ordered_projection_players(
            [expert_second, expert_first]
        )
        by_key = {player.key: player for player in aligned}

        self.assertEqual(by_key["expert-first"].projected_points, 200)
        self.assertEqual(by_key["expert-second"].projected_points, 190)
        self.assertEqual(by_key["expert-first"].source_projected_points, 190)
        self.assertEqual(by_key["expert-second"].source_projected_points, 200)
        self.assertEqual(by_key["expert-first"].projection_value_position_rank, 1)
        self.assertEqual(by_key["expert-second"].projection_value_position_rank, 2)
        self.assertEqual(
            [row["player_name"] for row in rank_user_candidates(
                aligned,
                [],
                "vorp",
                pick_no=20,
                round_no=2,
                teams=10,
                draft_slot=4,
                roster_positions=["RB"],
                total_user_picks=1,
                replacement_baselines={"RB": 100},
            )],
            ["Expert First", "Expert Second"],
        )

    def test_two_pick_timing_can_promote_lower_expert_player_without_projection_inversion(self) -> None:
        better, endangered = expert_ordered_projection_players(
            [
                Player(
                    "better",
                    "Better RB",
                    "RB",
                    190,
                    30,
                    50,
                    1.0,
                    overall_rank_score=10,
                    overall_ecr_rank=10,
                ),
                Player(
                    "endangered",
                    "Endangered RB",
                    "RB",
                    200,
                    31,
                    60,
                    1.4,
                    overall_rank_score=11,
                    overall_ecr_rank=11,
                ),
            ]
        )
        roster = [
            Player("qb", "QB", "QB", 250, 1, 50, 1),
            Player("wr", "WR", "WR", 180, 2, 50, 1),
            Player("te", "TE", "TE", 150, 3, 50, 1),
        ]
        ranked = rank_user_candidates(
            [better, endangered],
            roster,
            "half_ppr_reconciled_locked10",
            pick_no=3,
            round_no=2,
            teams=2,
            draft_slot=2,
            roster_positions=["QB", "RB", "WR", "TE", "FLEX"],
            total_user_picks=5,
            replacement_baselines={"QB": 100, "RB": 100, "WR": 100, "TE": 100},
            next_pick_survival_overrides={"better": 1.0, "endangered": 0.0},
            rank_vorp_curve=RankVorpCurve(
                points=((1.0, 100.0), (20.0, 90.0)),
                observation_count=2,
                block_count=2,
            ),
            reconciliation_baselines={
                0.5: {"QB": 100, "RB": 100, "WR": 100, "TE": 100}
            },
        )

        self.assertGreater(better.projected_points, endangered.projected_points)
        self.assertEqual(ranked[0]["player_name"], "Endangered RB")
        self.assertEqual(ranked[0]["expected_next_path_player"], "Better RB")
        self.assertGreater(
            ranked[0]["two_pick_path_value"], ranked[1]["two_pick_path_value"]
        )

    def test_turn_horizon_reaches_the_next_opponent_contested_pick(self) -> None:
        candidate = self.player(
            "Current RB", "RB", projection=200, adp=20, vols=100, rank=1
        )
        receiver = self.player(
            "Second WR", "WR", projection=190, adp=25, vols=90, rank=1
        )
        quarterback = self.player(
            "Later QB", "QB", projection=300, adp=90, vols=50, rank=1
        )
        details: dict = {}

        path = _two_pick_path_value(
            candidate,
            [candidate, receiver, quarterback],
            [],
            ["QB", "RB", "WR"],
            3,
            24,
            25,
            (0.05, 0.10, 0.15),
            {"QB": 250, "RB": 100, "WR": 100},
            {receiver.key: 1.0, quarterback.key: 1.0},
            continuation_pick=48,
            continuation_survival_overrides={
                receiver.key: 1.0,
                quarterback.key: 1.0,
            },
            path_details=details,
        )

        self.assertEqual(details["continuation_pick"], 48)
        self.assertTrue(details["planned_second_player"])
        self.assertTrue(details["planned_second_player_key"])
        self.assertTrue(details["expected_continuation_player"])
        self.assertGreater(path[0], path[1])

    def test_league_beta_qb_guard_defers_only_a_high_survival_near_tie(self) -> None:
        qb = self.player("Replaceable QB", "QB", projection=260, adp=120, vols=20, rank=8)
        rb = self.player("Urgent RB", "RB", projection=150, adp=95, vols=25, rank=30)
        rows = [
            {
                "_player": qb,
                "player_name": qb.name,
                "final_score": 47.4,
                "continuation_pick": 120,
                "contested_pick_survival": 0.77,
                "turn_aware_path_value": 58.49,
                "turn_aware_next_path_player": "Second RB",
                "turn_aware_continuation_path_player": "Urgent RB",
            },
            {
                "_player": rb,
                "player_name": rb.name,
                "final_score": 46.7,
                "continuation_pick": 120,
                "contested_pick_survival": 0.20,
                "turn_aware_path_value": 58.11,
                "turn_aware_next_path_player": "Second RB",
                "turn_aware_continuation_path_player": qb.name,
            },
        ]

        promoted = _promote_turn_aware_qb_deferral(
            rows,
            [],
            teams=12,
            draft_slot=1,
            roster_positions=[
                "QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "FLEX"
            ],
        )

        self.assertEqual(promoted[0]["player_name"], "Urgent RB")
        self.assertTrue(promoted[0]["turn_aware_qb_deferred"])
        self.assertEqual(promoted[0]["turn_aware_qb_name"], "Replaceable QB")
        self.assertEqual(promoted[0]["turn_aware_qb_score_gap"], 0.38)

        rows[0]["contested_pick_survival"] = 0.64
        self.assertIs(
            _promote_turn_aware_qb_deferral(
                rows,
                [],
                teams=12,
                draft_slot=1,
                roster_positions=[
                    "QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "FLEX"
                ],
            )[0]["_player"],
            qb,
        )

    def test_bounded_rollout_is_deterministic_and_audits_its_limits(self) -> None:
        prior = self.player("Prior RB", "RB", projection=190, adp=1, vols=80, rank=1)
        opponent_rb = self.player(
            "Opponent RB", "RB", projection=185, adp=2, vols=75, rank=2
        )
        opponent_wr = self.player(
            "Opponent WR", "WR", projection=180, adp=3, vols=70, rank=2
        )
        available = [
            self.player(
                f"Player {index}",
                ("QB", "RB", "WR", "TE")[index % 4],
                projection=280 - index * 4,
                adp=4 + index,
                vols=70 - index,
                rank=1 + index / 4,
            )
            for index in range(16)
        ]
        kwargs = dict(
            available=available,
            rosters={1: [prior], 2: [opponent_rb, opponent_wr]},
            forced_candidates=available[:3],
            policy="half_ppr_reconciled",
            current_pick=4,
            teams=2,
            draft_slot=1,
            roster_positions=["QB", "RB", "WR", "TE", "FLEX"],
            total_user_picks=6,
            replacement_baselines={"QB": 200, "RB": 100, "WR": 100, "TE": 90},
            scenarios=2,
            beam_width=2,
            branch_width=2,
            future_user_picks=2,
            seed=42,
        )

        first = bounded_multi_turn_rollout(**kwargs)
        second = bounded_multi_turn_rollout(**kwargs)

        self.assertEqual(first, second)
        self.assertEqual(first["status"], "shadow_only")
        self.assertEqual(first["target_pick"], 8)
        self.assertEqual(first["scenarios"], 2)
        self.assertEqual(first["beam_width"], 2)
        self.assertEqual(first["branch_width"], 2)
        self.assertEqual(first["forced_candidate_count"], 3)
        self.assertEqual(first["position_run_sigma"], 0.18)
        self.assertGreaterEqual(first["pruned_path_count"], 0)
        self.assertEqual(len(first["candidates"]), 3)
        self.assertIn("mean_regret", first["candidates"][0]["channels"]["primary"])
        self.assertEqual(len(first["candidates"][0]["representative_path"]), 3)
        for position, count in first["candidates"][0][
            "representative_position_counts"
        ].items():
            self.assertLessEqual(count, first["position_caps"][position])

    def test_full_rank_blend_targets_absolute_selected_rank_vorp(self) -> None:
        player = Player(
            "bowers", "Brock Bowers", "TE", 195, 22, 58, 1.4,
            overall_rank_score=18,
            overall_ecr_rank=18,
        )
        curve = RankVorpCurve(
            points=((1.0, 200.0), (18.0, 120.0), (40.0, 60.0)),
            observation_count=3,
            block_count=3,
        )
        adjusted = rank_adjusted_player(player, curve, 1.0, {"TE": 117})
        self.assertAlmostEqual(adjusted.projected_points - 117, 120.0)

    def test_overall_value_curve_is_indexed_by_selected_experts_not_general_ecr(self) -> None:
        selected_first = Player(
            "first",
            "Selected First",
            "RB",
            200,
            1,
            100,
            1,
            overall_rank_score=1,
            overall_ecr_rank=4,
        )
        selected_later = Player(
            "later",
            "Selected Later",
            "RB",
            150,
            4,
            50,
            2,
            overall_rank_score=4,
            overall_ecr_rank=1,
        )

        curve = fit_rank_vorp_curve(
            [selected_first, selected_later], {"RB": 100}
        )

        self.assertGreater(curve.value(1), curve.value(4))

    def test_overall_rank_blend_cannot_invert_selected_position_order(self) -> None:
        players = expert_ordered_projection_players(
            [
                Player(
                    "pos-first",
                    "Position First",
                    "WR",
                    200,
                    10,
                    100,
                    1,
                    overall_rank_score=20,
                    overall_ecr_rank=20,
                ),
                Player(
                    "pos-second",
                    "Position Second",
                    "WR",
                    190,
                    11,
                    90,
                    2,
                    overall_rank_score=1,
                    overall_ecr_rank=1,
                ),
            ]
        )
        curve = RankVorpCurve(
            points=((1.0, 150.0), (20.0, 50.0)),
            observation_count=2,
            block_count=2,
        )

        adjusted = rank_adjusted_players(players, curve, 1.0, {"WR": 100})
        by_key = {player.key: player for player in adjusted}

        self.assertGreaterEqual(
            by_key["pos-first"].projected_points,
            by_key["pos-second"].projected_points,
        )
        self.assertEqual(by_key["pos-first"].source_projected_points, 200)
        self.assertEqual(by_key["pos-second"].source_projected_points, 190)

    def test_consensus_anchor_is_strict_in_round_one(self) -> None:
        chase = Player(
            "chase", "Ja'Marr Chase", "WR", 215, 3, 79, 1,
            overall_rank_score=2,
        )
        henry = Player(
            "henry", "Derrick Henry", "RB", 256, 13, 118, 6,
            overall_rank_score=13,
        )
        ranked = rank_user_candidates(
            [henry, chase], [], "standard_consensus_band8",
            pick_no=6, round_no=1, teams=12, draft_slot=6,
            roster_positions=["QB", "RB", "RB", "WR", "WR", "TE", "FLEX"],
            total_user_picks=13,
            replacement_baselines={"QB": 250, "RB": 137, "WR": 136, "TE": 100},
        )
        self.assertEqual([row["player_name"] for row in ranked], ["Ja'Marr Chase"])
        self.assertEqual(ranked[0]["consensus_candidate_band"], 1)

    def test_reconciled_policy_drafts_with_rank_adjusted_projection_value(self) -> None:
        raw_leader = Player(
            "raw", "Raw Leader", "RB", 200, 1, 100, 1,
            overall_rank_score=20, overall_ecr_rank=1,
        )
        expert_leader = Player(
            "expert", "Expert Leader", "WR", 180, 2, 80, 1,
            overall_rank_score=1, overall_ecr_rank=20,
        )
        common = dict(
            available=[raw_leader, expert_leader],
            roster=[],
            pick_no=1,
            round_no=1,
            teams=2,
            draft_slot=1,
            roster_positions=["RB", "WR"],
            total_user_picks=2,
            replacement_baselines={"RB": 100, "WR": 100},
        )
        raw = rank_user_candidates(policy="half_ppr_total_team", **common)
        reconciled = rank_user_candidates(
            policy="half_ppr_reconciled_full",
            rank_vorp_curve=RankVorpCurve(
                points=((1.0, 100.0), (20.0, 0.0)),
                observation_count=2,
                block_count=2,
            ),
            reconciliation_baselines={1.0: {"RB": 100, "WR": 100}},
            **common,
        )
        self.assertEqual(raw[0]["player_name"], "Raw Leader")
        self.assertEqual(reconciled[0]["player_name"], "Expert Leader")
        self.assertEqual(reconciled[0]["rank_reconciliation_weight"], 1.0)

    def test_reconciled_first_round_prefers_chase_over_mccaffrey(self) -> None:
        chase = Player(
            "chase", "Ja'Marr Chase", "WR", 275, 3, 110, 1,
            overall_rank_score=3,
            overall_ecr_rank=3,
        )
        mccaffrey = Player(
            "mccaffrey", "Christian McCaffrey", "RB", 296, 5, 129, 3.8,
            overall_rank_score=7.4,
            overall_ecr_rank=8,
        )
        ranked = rank_user_candidates(
            [mccaffrey, chase],
            [],
            "half_ppr_reconciled",
            pick_no=4,
            round_no=1,
            teams=12,
            draft_slot=4,
            roster_positions=["RB", "WR"],
            total_user_picks=2,
            replacement_baselines={"RB": 96, "WR": 125},
            rank_vorp_curve=RankVorpCurve(
                points=((3.0, 214.0), (7.4, 147.0)),
                observation_count=2,
                block_count=2,
            ),
            reconciliation_baselines={0.5: {"RB": 96, "WR": 125}},
        )
        self.assertEqual(ranked[0]["player_name"], "Ja'Marr Chase")

    def test_controlled_qb_policy_waits_then_forces_first_qb(self) -> None:
        qb = Player(
            "qb", "Quarterback", "QB", 300, 50, 60, 5,
            overall_rank_score=50,
            overall_ecr_rank=50,
        )
        rb = Player(
            "rb", "Running Back", "RB", 180, 60, 40, 20,
            overall_rank_score=60,
            overall_ecr_rank=60,
        )
        common = dict(
            available=[qb, rb],
            policy="half_ppr_reconciled_qb_r6",
            teams=12,
            draft_slot=6,
            roster_positions=["QB", "RB"],
            total_user_picks=13,
            replacement_baselines={"QB": 240, "RB": 100},
        )
        before_window = rank_user_candidates(
            roster=[], pick_no=54, round_no=5, **common
        )
        forced_round = rank_user_candidates(
            roster=[rb], pick_no=67, round_no=6, **common
        )

        self.assertEqual([row["position"] for row in before_window], ["RB"])
        self.assertEqual([row["position"] for row in forced_round], ["QB"])
        self.assertEqual(forced_round[0]["forced_first_qb_round"], 6)

    def test_dynamic_qb_floor_waits_when_next_pick_drop_is_small(self) -> None:
        qb_now = Player(
            "qb-now", "QB Now", "QB", 300, 20, 60, 1,
            overall_rank_score=20, overall_ecr_rank=20,
        )
        qb_later = Player(
            "qb-later", "QB Later", "QB", 295, 80, 55, 2,
            overall_rank_score=80, overall_ecr_rank=80,
        )
        rb = Player(
            "rb", "Running Back", "RB", 180, 30, 40, 10,
            overall_rank_score=30, overall_ecr_rank=30,
        )

        ranked = rank_user_candidates(
            [qb_now, qb_later, rb],
            [],
            "half_ppr_reconciled_tol05_w20_qb_floor15",
            pick_no=20,
            round_no=2,
            teams=10,
            draft_slot=4,
            roster_positions=["QB", "RB"],
            total_user_picks=5,
            replacement_baselines={"QB": 250, "RB": 100},
            next_pick_survival_overrides={
                qb_now.key: 0.0,
                qb_later.key: 1.0,
                rb.key: 0.0,
            },
        )

        self.assertEqual([row["position"] for row in ranked], ["RB"])
        self.assertTrue(ranked[0]["qb_streaming_floor_deferred"])
        self.assertLessEqual(ranked[0]["qb_expected_next_pick_drop"], 15.0)

    def test_forced_te_policy_waits_then_forces_first_te(self) -> None:
        te = Player(
            "te", "Tight End", "TE", 180, 60, 50, 5,
            overall_rank_score=60, overall_ecr_rank=60,
        )
        wr = Player(
            "wr", "Wide Receiver", "WR", 190, 50, 55, 10,
            overall_rank_score=50, overall_ecr_rank=50,
        )
        common = dict(
            available=[te, wr],
            teams=12,
            draft_slot=6,
            roster_positions=["TE", "WR", "FLEX"],
            total_user_picks=13,
            replacement_baselines={"TE": 100, "WR": 100},
        )
        before_window = rank_user_candidates(
            roster=[], policy="half_ppr_reconciled_te_r6",
            pick_no=54, round_no=5, **common
        )
        forced_round = rank_user_candidates(
            roster=[wr], policy="half_ppr_reconciled_te_r6",
            pick_no=67, round_no=6, **common
        )

        self.assertEqual([row["position"] for row in before_window], ["WR"])
        self.assertEqual([row["position"] for row in forced_round], ["TE"])
        self.assertEqual(forced_round[0]["forced_first_te_round"], 6)

    def test_expert_ordered_policy_cannot_invert_same_position_rank(self) -> None:
        bowers = Player(
            "bowers", "Brock Bowers", "TE", 180, 20, 50, 1.4,
            overall_rank_score=18,
        )
        mcbride = Player(
            "mcbride", "Trey McBride", "TE", 220, 21, 90, 1.6,
            overall_rank_score=22,
        )
        ranked = rank_user_candidates(
            [mcbride, bowers],
            [],
            "half_ppr_expert_ordered_raw",
            pick_no=1,
            round_no=1,
            teams=2,
            draft_slot=1,
            roster_positions=["TE"],
            total_user_picks=1,
            replacement_baselines={"TE": 100},
        )
        self.assertEqual(
            [row["player_name"] for row in ranked],
            ["Brock Bowers", "Trey McBride"],
        )

        kyren = replace(
            bowers,
            key="kyren",
            name="Kyren Williams",
            position="RB",
            rank_score=13.1,
            overall_rank_score=30.3,
        )
        jacobs = replace(
            mcbride,
            key="jacobs",
            name="Josh Jacobs",
            position="RB",
            rank_score=15.0,
            overall_rank_score=34.8,
        )
        ranked_rbs = rank_user_candidates(
            [jacobs, kyren],
            [],
            "half_ppr_expert_ordered_raw",
            pick_no=1,
            round_no=1,
            teams=2,
            draft_slot=1,
            roster_positions=["RB"],
            total_user_picks=1,
            replacement_baselines={"RB": 100},
        )
        self.assertEqual(
            [row["player_name"] for row in ranked_rbs],
            ["Kyren Williams", "Josh Jacobs"],
        )

    def test_shadow_guardrails_can_release_a_composite_position_inversion(self) -> None:
        walker = Player(
            "walker", "Kenneth Walker III", "RB", 180, 18, 40, 9.968,
            overall_rank_score=20.767,
        )
        henry = Player(
            "henry", "Derrick Henry", "RB", 210, 15, 70, 10.269,
            overall_rank_score=19.446,
        )
        common = dict(
            available=[walker, henry],
            roster=[],
            pick_no=16,
            round_no=2,
            teams=12,
            draft_slot=9,
            roster_positions=["RB", "RB"],
            total_user_picks=13,
            replacement_baselines={"RB": 100},
        )

        strict = rank_user_candidates(
            policy="half_ppr_reconciled", **common
        )
        tolerance = rank_user_candidates(
            policy="half_ppr_reconciled_tol05", **common
        )
        ballots = rank_user_candidates(
            policy="half_ppr_reconciled_ballot50",
            ballot_preferences={
                ("henry", "walker"): 0.542,
                ("walker", "henry"): 0.458,
            },
            **common,
        )

        self.assertEqual(strict[0]["player_name"], "Kenneth Walker III")
        self.assertEqual(tolerance[0]["player_name"], "Derrick Henry")
        self.assertTrue(tolerance[0]["reserve_redundancy_cap"])
        self.assertEqual(ballots[0]["player_name"], "Derrick Henry")
        self.assertEqual(
            ballots[0]["positional_guardrail"]["method"],
            "direct_weighted_ballot",
        )
        with self.assertRaisesRegex(ValueError, "requires direct weighted ballot"):
            rank_user_candidates(
                policy="half_ppr_reconciled_ballot50", **common
            )

    def test_opponents_clear_an_overdue_elite_player(self) -> None:
        elite = self.player("Elite", "WR", projection=300, adp=2, vols=100, rank=1)
        on_time = self.player("On Time", "RB", projection=200, adp=20, vols=50, rank=20)
        for seed in range(10):
            selected = _opponent_pick(
                [elite, on_time],
                [],
                pick_no=20,
                round_no=2,
                rng=random.Random(seed),
            )
            self.assertEqual(selected.name, "Elite")

    def test_opponent_acquisition_stress_is_explicit_and_auditable(self) -> None:
        rb_rates = opponent_position_stress_rates("early_rb")
        self.assertEqual(set(rb_rates), set(range(1, 6)))
        self.assertGreater(rb_rates[1]["RB"], rb_rates[1]["WR"])
        self.assertEqual(opponent_position_stress_rates("raw"), {})
        with self.assertRaisesRegex(ValueError, "Unknown opponent position profile"):
            opponent_position_stress_rates("copied_history")

        positions = ["RB", "WR", "QB", "TE"]
        board = [
            {
                "player_key": f"stress-{index}",
                "player_name": f"Stress {index}",
                "position": positions[(index - 1) % len(positions)],
                "projected_points": 300 - index,
                "adp": index,
                "vbd": 100 - index,
                "rank_score": index,
            }
            for index in range(1, 65)
        ]
        result = compare_strategies(
            board,
            teams=2,
            draft_slot=1,
            roster_positions=["QB", "RB", "WR", "TE", "FLEX"],
            rounds=5,
            trials=1,
            strategies=["half_ppr_reconciled"],
            opponent_market_noise=0.0,
            opponent_position_profile="early_rb",
        )[0]
        acquisition = result["acquisition_adp"]
        self.assertEqual(acquisition["opponent_market_noise"], 0.0)
        self.assertEqual(acquisition["opponent_position_profile"], "early_rb")
        self.assertEqual(acquisition["opponent_position_rates"]["1"]["RB"], 0.55)

        with self.assertRaisesRegex(ValueError, "finite non-negative"):
            compare_strategies(
                board,
                teams=2,
                draft_slot=1,
                roster_positions=["QB", "RB", "WR", "TE", "FLEX"],
                rounds=5,
                trials=1,
                opponent_market_noise=-1.0,
            )

        history = HistoricalPositionCurves(
            position_picks={position: tuple(range(1, 13)) for position in positions},
            draft_end_pick=24,
            source="fixture",
        )
        with self.assertRaisesRegex(ValueError, "cannot be combined"):
            compare_strategies(
                board,
                teams=2,
                draft_slot=1,
                roster_positions=["QB", "RB", "WR", "TE", "FLEX"],
                rounds=5,
                trials=1,
                acquisition_history=history,
                history_weight=0.5,
                opponent_position_profile="early_wr",
            )

    def test_close_wr_construction_promotes_only_inside_score_gap(self) -> None:
        rb = self.player("RB", "RB", projection=200, adp=20, vols=40, rank=5)
        wr = self.player("WR", "WR", projection=195, adp=21, vols=38, rank=6)
        roster = [
            self.player(f"WR {index}", "WR", projection=180, adp=30 + index, vols=20, rank=index)
            for index in range(1, 4)
        ]
        config = _construction_policy_config(
            "half_ppr_reconciled_wr4_by8_gap10"
        )
        self.assertEqual(
            config["minimum_position_if_close_by_round"],
            ("WR", 4, 8, 1.0),
        )
        close = [
            {"_player": rb, "final_score": 40.0},
            {"_player": wr, "final_score": 39.25},
        ]
        promoted = _promote_close_construction_candidate(close, roster, 8, config)
        self.assertIs(promoted[0]["_player"], wr)
        self.assertTrue(promoted[0]["construction_close_promoted"])

        distant = [
            {"_player": rb, "final_score": 40.0},
            {"_player": wr, "final_score": 38.5},
        ]
        unchanged = _promote_close_construction_candidate(distant, roster, 8, config)
        self.assertIs(unchanged[0]["_player"], rb)

    def test_early_wr_challenger_is_bounded_to_round_three_score_gap(self) -> None:
        rb = self.player("RB", "RB", projection=200, adp=20, vols=40, rank=5)
        wr = self.player("WR", "WR", projection=195, adp=21, vols=38, rank=6)
        config = _construction_policy_config(
            "half_ppr_reconciled_wr1_by3_gap10"
        )
        self.assertEqual(
            config["minimum_position_if_close_by_round"],
            ("WR", 1, 3, 10.0),
        )
        ranked = [
            {"_player": rb, "final_score": 40.0},
            {"_player": wr, "final_score": 30.5},
        ]

        before_deadline = _promote_close_construction_candidate(
            [dict(row) for row in ranked], [], 2, config
        )
        promoted = _promote_close_construction_candidate(
            [dict(row) for row in ranked], [], 3, config
        )

        self.assertIs(before_deadline[0]["_player"], rb)
        self.assertIs(promoted[0]["_player"], wr)
        self.assertEqual(promoted[0]["construction_close_score_gap"], 9.5)

    def test_recommendation_rewards_urgency(self) -> None:
        board = [
            {"player_key": "sleeper_id:1", "player_name": "Urgent", "position": "WR", "adp": 11, "vbd": 20, "rank_score": 1},
            {"player_key": "sleeper_id:2", "player_name": "Patient", "position": "WR", "adp": 40, "vbd": 20, "rank_score": 2},
        ]
        result = recommend_available(board, [], current_pick=10, teams=12, draft_slot=10)
        self.assertEqual(result[0]["player_name"], "Urgent")

    def test_strategy_simulation_completes(self) -> None:
        positions = ["RB", "WR", "QB", "TE"]
        board = []
        for index in range(1, 65):
            board.append(
                {
                    "player_key": f"player-{index}",
                    "player_name": f"Player {index}",
                    "position": positions[(index - 1) % len(positions)],
                    "projected_points": 300 - index,
                    "adp": index,
                    "vbd": 100 - index,
                    "rank_score": index,
                }
            )
        results = compare_strategies(
            board,
            teams=4,
            draft_slot=2,
            roster_positions=["QB", "RB", "WR", "TE", "FLEX", "BN", "BN", "BN"],
            rounds=8,
            trials=3,
            strategies=["dynamic", "vbd"],
            include_trial_records=True,
            include_draft_pick_records=True,
        )
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["trials"], 3)
        self.assertEqual(len(results[0]["trial_records"]), 3)
        self.assertEqual(
            len(results[0]["trial_records"][0]["user_picks"]), 8
        )
        self.assertNotIn("_player", results[0]["trial_records"][0]["user_picks"][0])
        self.assertEqual(
            len(results[0]["trial_records"][0]["draft_picks"]), 32
        )
        self.assertIn(
            "player_key", results[0]["trial_records"][0]["draft_picks"][0]
        )
        replacement_result = compare_strategies(
            board,
            teams=4,
            draft_slot=2,
            roster_positions=["QB", "RB", "WR", "TE", "FLEX", "BN", "BN", "BN"],
            rounds=8,
            trials=1,
            strategies=["half_ppr_calibrated"],
        )[0]
        self.assertTrue(replacement_result["replacement_aware_evaluation"])

    def test_slot_warp_disables_round_position_tendencies_and_traces_both_adps(self) -> None:
        positions = ["RB", "WR", "QB", "TE"]
        board = [
            {
                "player_key": f"warp-{index}",
                "player_name": f"Warp {index}",
                "position": positions[(index - 1) % len(positions)],
                "projected_points": 300 - index,
                "adp": index,
                "vbd": 100 - index,
                "rank_score": index,
            }
            for index in range(1, 49)
        ]
        history = HistoricalPositionCurves(
            position_picks={position: tuple(range(1, 13)) for position in positions},
            draft_end_pick=24,
            source="fixture",
        )
        result = compare_strategies(
            board,
            teams=2,
            draft_slot=1,
            roster_positions=["QB", "RB", "WR", "TE", "FLEX"],
            rounds=5,
            trials=1,
            strategies=["half_ppr_reconciled"],
            round_position_rates={1: {"QB": 1.0, "RB": 0.0, "WR": 0.0, "TE": 0.0}},
            acquisition_history=history,
            history_weight=0.0,
            include_trace=True,
        )[0]

        self.assertFalse(result["acquisition_adp"]["round_position_rates_applied"])
        self.assertEqual(result["acquisition_adp"]["fallback_state"], "zero_weight_raw_adp")
        first_pick = result["trace"]["picks"][0]
        self.assertEqual(first_pick["adp"], first_pick["acquisition_adp"])
        self.assertIn("qb_availability", result["trace"]["user_decisions"][0])

    def test_market_replacement_is_best_undrafted_projection(self) -> None:
        players = [
            self.player("Drafted RB", "RB", projection=100, adp=1, vols=30, rank=1),
            self.player("Drafted WR", "WR", projection=110, adp=2, vols=30, rank=2),
            self.player("Waiver RB A", "RB", projection=90, adp=3, vols=10, rank=3),
            self.player("Waiver RB B", "RB", projection=95, adp=4, vols=8, rank=4),
            self.player("Waiver WR", "WR", projection=85, adp=5, vols=5, rank=5),
        ]
        baselines = market_replacement_baselines(players, teams=1, skill_rounds=2)
        self.assertEqual(baselines["RB"], 95)
        self.assertEqual(baselines["WR"], 85)

    def test_bench_has_no_flat_credit_but_can_improve_availability_score(self) -> None:
        starters = [
            self.player("QB", "QB", projection=300, adp=1, vols=100, rank=1),
            self.player("RB", "RB", projection=200, adp=2, vols=80, rank=2),
            self.player("WR", "WR", projection=190, adp=3, vols=70, rank=3),
        ]
        bench = self.player("Bench RB", "RB", projection=150, adp=20, vols=20, rank=20)
        positions = ["QB", "RB", "WR"]
        self.assertEqual(
            roster_score(starters, positions),
            roster_score([*starters, bench], positions),
        )
        without_bench, _ = expected_roster_score(
            starters,
            positions,
            availability_rates=(0.5,),
            samples_per_rate=200,
            scenario_seed=17,
        )
        with_bench, _ = expected_roster_score(
            [*starters, bench],
            positions,
            availability_rates=(0.5,),
            samples_per_rate=200,
            scenario_seed=17,
        )
        self.assertGreater(with_bench, without_bench)

    def test_weekly_use_reserve_scores_only_when_it_enters_above_waivers(self) -> None:
        starters = [
            self.player("QB", "QB", projection=300, adp=1, vols=100, rank=1),
            self.player("RB", "RB", projection=200, adp=2, vols=80, rank=2),
            self.player("WR", "WR", projection=190, adp=3, vols=70, rank=3),
        ]
        useful = self.player("Useful RB", "RB", projection=150, adp=20, vols=20, rank=20)
        unusable = self.player("Waiver RB", "RB", projection=90, adp=30, vols=0, rank=30)
        positions = ["QB", "RB", "WR"]
        baselines = {"QB": 250.0, "RB": 100.0, "WR": 100.0, "TE": 0.0}

        useful_result = weekly_use_roster_strength(
            [*starters, useful], positions, baselines
        )
        unusable_result = weekly_use_roster_strength(
            [*starters, unusable], positions, baselines
        )

        self.assertEqual(
            useful_result["stress_levels"]["no_absence"]
            ["mean_reserve_lift_above_waivers"],
            0.0,
        )
        self.assertGreater(
            useful_result["stress_levels"]["light"]
            ["mean_reserve_lift_above_waivers"],
            0.0,
        )
        self.assertEqual(
            unusable_result["stress_levels"]["light"]
            ["mean_reserve_lift_above_waivers"],
            0.0,
        )

    def test_weekly_use_projection_miss_can_activate_a_reserve(self) -> None:
        starters = [
            self.player("QB", "QB", projection=300, adp=1, vols=100, rank=1),
            self.player("RB", "RB", projection=200, adp=2, vols=80, rank=2),
            self.player("WR", "WR", projection=190, adp=3, vols=70, rank=3),
        ]
        reserve = self.player("Reserve WR", "WR", projection=150, adp=20, vols=20, rank=20)
        result = weekly_use_roster_strength(
            [*starters, reserve],
            ["QB", "RB", "WR"],
            {"QB": 250.0, "RB": 100.0, "WR": 100.0, "TE": 0.0},
        )

        self.assertGreater(
            result["stress_levels"]["light"]["reserve_entry_rates"][reserve.key],
            0.0,
        )
        self.assertEqual(result["stress_levels"]["light"]["scenario_count"], 6)

    def test_weekly_use_result_is_independent_of_bye_alignment(self) -> None:
        same_bye_roster = [
            self.player("QB", "QB", projection=300, adp=1, vols=100, rank=1, team="ATL"),
            self.player("RB", "RB", projection=200, adp=2, vols=80, rank=2, team="ATL"),
            self.player("WR", "WR", projection=190, adp=3, vols=70, rank=3, team="ATL"),
            self.player("Reserve", "RB", projection=150, adp=20, vols=20, rank=20, team="ATL"),
        ]
        spread_bye_roster = [
            replace(player, team=team)
            for player, team in zip(same_bye_roster, ("ATL", "BUF", "CHI", "ARI"))
        ]
        positions = ["QB", "RB", "WR"]
        baselines = {"QB": 250.0, "RB": 100.0, "WR": 100.0, "TE": 0.0}

        self.assertEqual(
            weekly_use_roster_strength(same_bye_roster, positions, baselines),
            weekly_use_roster_strength(spread_bye_roster, positions, baselines),
        )

    def test_single_flex_lineup_uses_best_leftover_after_dedicated_starters(self) -> None:
        players = [
            self.player("RB1", "RB", projection=100, adp=1, vols=1, rank=1),
            self.player("RB2", "RB", projection=90, adp=2, vols=1, rank=2),
            self.player("RB3", "RB", projection=80, adp=3, vols=1, rank=3),
            self.player("WR1", "WR", projection=95, adp=4, vols=1, rank=1),
            self.player("WR2", "WR", projection=85, adp=5, vols=1, rank=2),
            self.player("WR3", "WR", projection=70, adp=6, vols=1, rank=3),
        ]

        self.assertEqual(
            roster_score(players, ["RB", "RB", "WR", "WR", "WRRB_FLEX"]),
            450,
        )
        self.assertEqual(
            roster_score(players, ["RB", "RB", "WR", "WR", "FLEX", "FLEX"]),
            520,
        )

    def test_deterministic_score_credits_known_bye_coverage_above_waivers(self) -> None:
        starter = self.player(
            "Starter QB", "QB", projection=340, adp=1, vols=100, rank=1, team="CAR"
        )
        different_bye = self.player(
            "Bench QB", "QB", projection=272, adp=20, vols=30, rank=20, team="CIN"
        )
        same_bye = self.player(
            "Same Bye QB", "QB", projection=272, adp=21, vols=29, rank=21, team="KC"
        )
        baseline = {"QB": 170}
        covered = deterministic_roster_strength(
            [starter, different_bye], ["QB"], baseline
        )
        uncovered = deterministic_roster_strength(
            [starter, same_bye], ["QB"], baseline
        )
        self.assertEqual(covered["base_lineup_score"], 340)
        self.assertAlmostEqual(covered["bye_coverage_points"], 6.0)
        self.assertAlmostEqual(uncovered["bye_coverage_points"], 0.0)
        self.assertAlmostEqual(covered["bye_replacement_floor_points"], 10.0)
        self.assertAlmostEqual(uncovered["bye_replacement_floor_points"], 10.0)
        self.assertAlmostEqual(covered["bye_filled_points"], 16.0)
        self.assertAlmostEqual(uncovered["bye_filled_points"], 10.0)
        self.assertAlmostEqual(covered["bye_adjusted_lineup_score"], 346.0)
        self.assertEqual(covered["bench_vorp"], 102)
        self.assertEqual(covered["total_roster_vorp"], 272)

    def test_simulation_reports_deterministic_bench_weight_sensitivity(self) -> None:
        positions = ["RB", "WR", "QB", "TE"]
        board = [
            {
                "player_key": f"metric-{index}",
                "player_name": f"Metric {index}",
                "position": positions[(index - 1) % len(positions)],
                "team": ("CAR", "CIN", "BUF", "HOU")[(index - 1) % 4],
                "projected_points": 300 - index,
                "adp": index,
                "vbd": 100 - index,
                "rank_score": index,
                "overall_rank_score": 49 - index,
                "overall_ecr": index,
            }
            for index in range(1, 49)
        ]
        result = compare_strategies(
            board,
            teams=2,
            draft_slot=1,
            roster_positions=["QB", "RB", "WR", "TE", "FLEX"],
            rounds=5,
            trials=2,
            strategies=["half_ppr_next_pick", "half_ppr_next_pick_safe"],
            bench_weights=(0.10, 0.20, 0.30),
        )
        for summary in result:
            self.assertEqual(
                set(summary["deterministic_draft_scores"]),
                {"0.10", "0.20", "0.30"},
            )
            self.assertIn("mean_bye_adjusted_lineup_score", summary)
            self.assertIn("mean_bye_replacement_floor_points", summary)
            self.assertIn("mean_bye_filled_points", summary)
            self.assertIn("mean_bench_vorp", summary)
            self.assertEqual(summary["score_type"], "availability_robustness_diagnostic")
            self.assertEqual(
                set(summary["rank_reconciled_draft_scores"]),
                {"0.00", "0.50", "1.00"},
            )
            self.assertIn("cross_channel_robustness", summary)
            self.assertEqual(
                summary["weekly_use"]["method"],
                "no_bye_common_absence_and_projection_miss",
            )
            self.assertEqual(
                set(summary["weekly_use"]["rank_channels"]),
                {"0.00", "0.50", "1.00"},
            )
            self.assertIn(
                "paired_mean_regret",
                summary["weekly_use"]["rank_channels"]["0.50"]["moderate"],
            )
            self.assertEqual(
                summary["rank_reconciliation"]["method"],
                "absolute_selected_rank_vorp_blend",
            )
            for bench_weight in ("0.10", "0.20", "0.30"):
                self.assertEqual(
                    summary["rank_reconciled_draft_scores"]["0.00"]
                    ["bench_weight_scores"][bench_weight],
                    summary["deterministic_draft_scores"][bench_weight],
                )

    def test_replacement_floor_fills_an_uncovered_lineup_slot(self) -> None:
        positions = ["QB", "RB"]
        rb = self.player("RB", "RB", projection=200, adp=1, vols=80, rank=1)
        self.assertEqual(
            roster_score([rb], positions, {"QB": 100, "RB": 75}),
            300,
        )
        replacement_score, _ = expected_roster_score(
            [rb],
            positions,
            availability_rates=(0.5,),
            samples_per_rate=50,
            scenario_seed=22,
            replacement_baselines={"QB": 100, "RB": 75},
        )
        empty_score, _ = expected_roster_score(
            [rb],
            positions,
            availability_rates=(0.5,),
            samples_per_rate=50,
            scenario_seed=22,
        )
        self.assertGreater(replacement_score, empty_score)

    def test_replacement_aware_policy_devalues_a_backup_over_waivers(self) -> None:
        roster = [
            self.player("QB", "QB", projection=300, adp=1, vols=100, rank=1),
            self.player("RB", "RB", projection=200, adp=2, vols=80, rank=2),
            self.player("WR", "WR", projection=190, adp=3, vols=70, rank=3),
        ]
        backup = self.player("Backup QB", "QB", projection=250, adp=30, vols=20, rank=20)
        common = dict(
            available=[backup],
            roster=roster,
            pick_no=8,
            round_no=8,
            teams=1,
            draft_slot=1,
            roster_positions=["QB", "RB", "WR"],
            total_user_picks=13,
            replacement_baselines={"QB": 240, "RB": 100, "WR": 100},
        )
        zero_floor = rank_user_candidates(policy="v3_bs40_p0_u0", **common)[0]
        waiver_floor = rank_user_candidates(policy="v4_bs40_p0_u0", **common)[0]
        self.assertGreater(
            zero_floor["scenario_marginal_value"],
            waiver_floor["scenario_marginal_value"],
        )
        self.assertTrue(waiver_floor["replacement_aware_marginal"])

    def test_scenario_policy_uses_slot_specific_vona_weights(self) -> None:
        policy = "v3_bs30_p100_u100"
        self.assertEqual(_experimental_profile(policy, 2)["vona_weight"], 5.0)
        self.assertEqual(_experimental_profile(policy, 6)["vona_weight"], 7.5)
        self.assertEqual(_experimental_profile(policy, 11)["vona_weight"], 3.0)
        self.assertEqual(_experimental_profile(policy, 6)["soft_bench_penalty"], 30)
        self.assertEqual(_experimental_profile("scenario_calibrated", 6)["vona_weight"], 7.5)
        self.assertEqual(
            _experimental_profile("scenario_calibrated", 6)["post_starter_vona_weight"],
            2.0,
        )
        fixed = _experimental_profile("v3x_w200_bs40_p50_u100", 11)
        self.assertEqual(fixed["vona_weight"], 2.0)
        self.assertEqual(fixed["soft_bench_penalty"], 40)
        self.assertEqual(fixed["post_starter_vona_weight"], 0.5)
        self.assertEqual(fixed["upside_weight"], 1.0)
        half_primary = _experimental_profile("half_ppr_calibrated", 2)
        half_safe = _experimental_profile("half_ppr_safe", 11)
        self.assertEqual(half_primary["bench_before_starters"], 0)
        self.assertEqual(half_primary["post_starter_vona_weight"], 0.05)
        self.assertEqual(half_safe["bench_before_starters"], 0)
        self.assertEqual(half_safe["post_starter_vona_weight"], 1.0)
        self.assertTrue(
            _experimental_profile("half_ppr_replacement_safe", 2)["replacement_aware"]
        )
        next_pick = _experimental_profile("half_ppr_next_pick", 11)
        self.assertIsNone(next_pick["bench_before_starters"])
        self.assertTrue(next_pick["starter_deferral"])
        self.assertTrue(next_pick["replacement_aware"])
        total_team = _experimental_profile("half_ppr_team_w20", 6)
        self.assertTrue(total_team["starter_deferral"])
        self.assertEqual(total_team["total_team_bench_weight"], 0.20)
        reserve_cap = _experimental_profile("half_ppr_team_w20_reserve_cap", 6)
        self.assertTrue(reserve_cap["reserve_redundancy_cap"])
        self.assertEqual(
            _reconciled_pick_policy("half_ppr_reconciled_tol05_reserve_cap"),
            ("half_ppr_team_w20_reserve_cap", 0.5, True),
        )
        self.assertEqual(
            _experimental_profile("half_ppr_total_team", 6)["total_team_bench_weight"],
            0.30,
        )
        self.assertEqual(
            _experimental_profile("half_ppr_total_team_safe", 6)["total_team_bench_weight"],
            0.10,
        )
        self.assertEqual(
            _experimental_profile("standard_total_team", 6)["total_team_bench_weight"],
            0.30,
        )
        self.assertEqual(
            _experimental_profile("standard_total_team_safe", 6)["total_team_bench_weight"],
            0.10,
        )
        self.assertEqual(
            _reconciled_pick_policy("half_ppr_reconciled_w40"),
            ("half_ppr_team_w40", 0.5, True),
        )
        self.assertEqual(
            _reconciled_pick_policy("half_ppr_reconciled_w30_reserve_cap"),
            ("half_ppr_team_w30_reserve_cap", 0.5, True),
        )
        self.assertTrue(
            _experimental_profile(
                "half_ppr_reconciled_w30_reserve_cap", 6
            )["reserve_redundancy_cap"]
        )
        self.assertEqual(
            _experimental_profile(
                "half_ppr_reconciled_w30_upside50", 6
            )["upside_weight"],
            0.5,
        )
        self.assertEqual(
            _position_guardrail_config("half_ppr_reconciled_w30_upside50"),
            {"method": "strict_position_rank", "tolerance": 0.0},
        )

    def test_total_team_policy_values_bench_points_above_waivers_not_raw_points(self) -> None:
        roster = [
            self.player("QB", "QB", projection=300, adp=1, vols=100, rank=1),
            self.player("RB", "RB", projection=200, adp=2, vols=80, rank=2),
            self.player("WR", "WR", projection=190, adp=3, vols=70, rank=3),
            self.player("TE", "TE", projection=160, adp=4, vols=60, rank=4),
        ]
        backup_qb = self.player(
            "Backup QB", "QB", projection=250, adp=40, vols=20, rank=5
        )
        depth_wr = self.player(
            "Depth WR", "WR", projection=150, adp=40, vols=20, rank=6
        )
        ranked = rank_user_candidates(
            [backup_qb, depth_wr], roster, "half_ppr_team_w20",
            pick_no=20, round_no=5, teams=4, draft_slot=4,
            roster_positions=["QB", "RB", "WR", "TE"], total_user_picks=6,
            replacement_baselines={"QB": 240, "RB": 120, "WR": 100, "TE": 100},
        )
        self.assertEqual(ranked[0]["player_name"], "Depth WR")
        self.assertGreater(
            ranked[0]["deterministic_bench_marginal"],
            ranked[1]["deterministic_bench_marginal"],
        )

    def test_reserve_cap_does_not_double_count_a_fourth_rb_reserve(self) -> None:
        positions = ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX"]
        baselines = {"QB": 200, "RB": 100, "WR": 100, "TE": 100}
        roster = [
            self.player("QB1", "QB", projection=300, adp=1, vols=100, rank=1),
            self.player("RB1", "RB", projection=220, adp=2, vols=90, rank=2),
            self.player("RB2", "RB", projection=210, adp=3, vols=80, rank=3),
            self.player("WR1", "WR", projection=215, adp=4, vols=85, rank=4),
            self.player("WR2", "WR", projection=205, adp=5, vols=75, rank=5),
            self.player("WR3", "WR", projection=195, adp=6, vols=65, rank=6),
            self.player("TE1", "TE", projection=180, adp=7, vols=60, rank=7),
            self.player("RB3", "RB", projection=180, adp=8, vols=55, rank=8),
            self.player("RB4", "RB", projection=170, adp=9, vols=50, rank=9),
            self.player("RB5", "RB", projection=160, adp=10, vols=45, rank=10),
        ]
        redundant_rb = self.player(
            "RB6", "RB", projection=150, adp=11, vols=40, rank=11
        )
        useful_wr = self.player(
            "WR4", "WR", projection=150, adp=12, vols=40, rank=12
        )
        base = _deterministic_pick_roster_value(
            roster, positions, baselines, 0.20, True
        )
        rb_value = _deterministic_pick_roster_value(
            [*roster, redundant_rb], positions, baselines, 0.20, True
        )
        wr_value = _deterministic_pick_roster_value(
            [*roster, useful_wr], positions, baselines, 0.20, True
        )

        self.assertEqual(rb_value, base)
        self.assertGreater(wr_value[0], base[0])

    def test_late_round_vona_retains_below_last_starter_fallback_value(self) -> None:
        current = self.player(
            "Current RB", "RB", projection=130, adp=1, vols=-35, rank=36
        )
        next_available = self.player(
            "Next RB", "RB", projection=100, adp=999, vols=-65, rank=50
        )
        unusable = self.player(
            "Unusable RB", "RB", projection=0, adp=999, vols=0, rank=49
        )
        fallback = _expected_next_by_position(
            [current, unusable, next_available],
            current_pick=100,
            target_pick=117,
            replacement_baselines={"RB": 90},
        )["RB"]

        self.assertGreater(fallback["expected_projected_points"], 99)
        self.assertLess(fallback["expected_projected_points"], 101)
        self.assertGreater(
            current.projected_points - fallback["expected_projected_points"], 20
        )

    def test_total_team_proxy_discounts_redundant_onesie_depth(self) -> None:
        roster = [
            self.player("QB", "QB", projection=300, adp=1, vols=100, rank=1),
            self.player("RB1", "RB", projection=210, adp=2, vols=90, rank=2),
            self.player("RB2", "RB", projection=200, adp=3, vols=80, rank=3),
            self.player("RB Flex", "RB", projection=190, adp=4, vols=70, rank=4),
            self.player("WR1", "WR", projection=205, adp=5, vols=85, rank=5),
            self.player("WR2", "WR", projection=195, adp=6, vols=75, rank=6),
            self.player("Bowers", "TE", projection=180, adp=7, vols=60, rank=7),
        ]
        positions = ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX"]
        baselines = {"QB": 240, "RB": 95, "WR": 120, "TE": 95}
        kelce = self.player(
            "Kelce", "TE", projection=145, adp=90, vols=8, rank=10
        )
        mason = self.player(
            "Mason", "RB", projection=135, adp=95, vols=-30, rank=36
        )
        base = _deterministic_pick_roster_value(
            roster, positions, baselines, bench_weight=0.30
        )
        kelce_value = _deterministic_pick_roster_value(
            [*roster, kelce], positions, baselines, bench_weight=0.30
        )
        mason_value = _deterministic_pick_roster_value(
            [*roster, mason], positions, baselines, bench_weight=0.30
        )

        self.assertGreater(
            kelce.projected_points - baselines["TE"],
            mason.projected_points - baselines["RB"],
        )
        self.assertGreater(mason_value[2] - base[2], kelce_value[2] - base[2])

    def test_next_pick_policy_defers_a_likely_to_survive_starter_for_scarce_bench_value(self) -> None:
        roster = [
            self.player("QB", "QB", projection=280, adp=1, vols=100, rank=1),
            self.player("RB Starter", "RB", projection=210, adp=2, vols=80, rank=2),
            self.player("WR Starter", "WR", projection=200, adp=3, vols=70, rank=3),
        ]
        scarce_rb = self.player(
            "Scarce RB", "RB", projection=195, adp=5, vols=65, rank=4
        )
        patient_te = self.player(
            "Patient TE", "TE", projection=170, adp=80, vols=40, rank=5
        )
        ranked = rank_user_candidates(
            [scarce_rb, patient_te],
            roster,
            "half_ppr_next_pick",
            pick_no=20,
            round_no=3,
            teams=4,
            draft_slot=4,
            roster_positions=["QB", "RB", "WR", "TE"],
            total_user_picks=6,
            replacement_baselines={"QB": 200, "RB": 130, "WR": 130, "TE": 120},
            next_pick_survival_overrides={scarce_rb.key: 0.0, patient_te.key: 1.0},
        )
        self.assertEqual(ranked[0]["player_name"], "Scarce RB")
        self.assertTrue(ranked[0]["starter_deferred"])
        self.assertGreater(ranked[0]["starter_deferral_effect"], 0.0)
        self.assertEqual(ranked[0]["expected_next_path_player"], "Patient TE")

    def test_next_pick_policy_takes_starter_during_a_run(self) -> None:
        roster = [
            self.player("QB", "QB", projection=280, adp=1, vols=100, rank=1),
            self.player("RB Starter", "RB", projection=210, adp=2, vols=80, rank=2),
            self.player("WR Starter", "WR", projection=200, adp=3, vols=70, rank=3),
        ]
        scarce_rb = self.player(
            "Scarce RB", "RB", projection=195, adp=5, vols=65, rank=4
        )
        urgent_te = self.player(
            "Urgent TE", "TE", projection=170, adp=21, vols=40, rank=5
        )
        ranked = rank_user_candidates(
            [scarce_rb, urgent_te],
            roster,
            "half_ppr_next_pick",
            pick_no=20,
            round_no=3,
            teams=4,
            draft_slot=4,
            roster_positions=["QB", "RB", "WR", "TE"],
            total_user_picks=6,
            replacement_baselines={"QB": 200, "RB": 130, "WR": 130, "TE": 120},
            next_pick_survival_overrides={scarce_rb.key: 1.0, urgent_te.key: 0.0},
        )
        self.assertEqual(ranked[0]["player_name"], "Urgent TE")
        self.assertFalse(ranked[0]["starter_deferred"])

    def test_higher_starter_survival_cannot_reduce_deferral_value(self) -> None:
        roster = [
            self.player("QB", "QB", projection=280, adp=1, vols=100, rank=1),
            self.player("RB Starter", "RB", projection=210, adp=2, vols=80, rank=2),
            self.player("WR Starter", "WR", projection=200, adp=3, vols=70, rank=3),
        ]
        bench = self.player("Bench RB", "RB", projection=195, adp=5, vols=65, rank=4)
        te = self.player("TE", "TE", projection=170, adp=40, vols=40, rank=5)
        common = dict(
            available=[bench, te], roster=roster, policy="half_ppr_next_pick",
            pick_no=20, round_no=3, teams=4, draft_slot=4,
            roster_positions=["QB", "RB", "WR", "TE"], total_user_picks=6,
            replacement_baselines={"QB": 200, "RB": 130, "WR": 130, "TE": 120},
        )
        low = rank_user_candidates(
            **common, next_pick_survival_overrides={bench.key: 0.0, te.key: 0.25}
        )
        high = rank_user_candidates(
            **common, next_pick_survival_overrides={bench.key: 0.0, te.key: 0.75}
        )
        low_bench = next(row for row in low if row["player_name"] == "Bench RB")
        high_bench = next(row for row in high if row["player_name"] == "Bench RB")
        self.assertGreaterEqual(
            high_bench["starter_deferral_effect"],
            low_bench["starter_deferral_effect"],
        )

    def test_next_pick_policy_cannot_defer_the_last_feasible_starter(self) -> None:
        roster = [
            self.player("QB", "QB", projection=280, adp=1, vols=100, rank=1),
            self.player("RB", "RB", projection=210, adp=2, vols=80, rank=2),
            self.player("WR", "WR", projection=200, adp=3, vols=70, rank=3),
        ]
        bench = self.player("Bench RB", "RB", projection=250, adp=4, vols=120, rank=4)
        te = self.player("Needed TE", "TE", projection=120, adp=80, vols=10, rank=5)
        ranked = rank_user_candidates(
            [bench, te], roster, "half_ppr_next_pick",
            pick_no=40, round_no=10, teams=4, draft_slot=4,
            roster_positions=["QB", "RB", "WR", "TE"], total_user_picks=4,
            replacement_baselines={"QB": 200, "RB": 130, "WR": 130, "TE": 100},
            next_pick_survival_overrides={bench.key: 0.0, te.key: 1.0},
        )
        self.assertEqual([row["player_name"] for row in ranked], ["Needed TE"])

    def test_vona_rewards_the_position_with_the_larger_next_pick_drop(self) -> None:
        players = [
            self.player("Top WR", "WR", projection=210, adp=2, vols=110, rank=1),
            self.player("Top RB", "RB", projection=200, adp=2, vols=100, rank=2),
            self.player("Next WR", "WR", projection=195, adp=100, vols=95, rank=3),
            self.player("Next RB", "RB", projection=120, adp=100, vols=20, rank=4),
        ]
        common = dict(
            available=players,
            roster=[],
            pick_no=1,
            round_no=1,
            teams=2,
            draft_slot=1,
            roster_positions=["RB", "WR"],
            total_user_picks=2,
            replacement_baselines={"RB": 100, "WR": 100},
        )
        vols = rank_user_candidates(policy="vols", **common)
        vona = rank_user_candidates(policy="vona", **common)
        protected_vona = rank_user_candidates(policy="fs_vona", round_no=2, **{
            key: value for key, value in common.items() if key != "round_no"
        })
        self.assertEqual(vols[0]["player_name"], "Top WR")
        self.assertEqual(vona[0]["player_name"], "Top RB")
        self.assertEqual(protected_vona[0]["player_name"], "Top RB")
        self.assertGreater(vona[0]["vona"], vona[1]["vona"])

    def test_candidate_ranking_preserves_a_path_to_all_starters(self) -> None:
        roster = [
            self.player("QB", "QB", projection=200, adp=1, vols=50, rank=1),
            self.player("RB", "RB", projection=180, adp=2, vols=40, rank=2),
            self.player("WR", "WR", projection=170, adp=3, vols=30, rank=3),
        ]
        available = [
            self.player("Extra WR", "WR", projection=300, adp=4, vols=200, rank=4),
            self.player("Needed TE", "TE", projection=80, adp=30, vols=1, rank=30),
        ]
        ranked = rank_user_candidates(
            available,
            roster,
            "vols",
            pick_no=4,
            round_no=4,
            teams=1,
            draft_slot=1,
            roster_positions=["QB", "RB", "WR", "TE"],
            total_user_picks=4,
            replacement_baselines={},
        )
        self.assertEqual([row["player_name"] for row in ranked], ["Needed TE"])

    def test_market_aware_policy_values_an_open_starter_over_bench_surplus(self) -> None:
        roster = [
            self.player("RB Starter", "RB", projection=180, adp=1, vols=80, rank=1),
            self.player("RB Flex", "RB", projection=170, adp=2, vols=70, rank=2),
        ]
        available = [
            self.player("RB Bench", "RB", projection=180, adp=3, vols=20, rank=3),
            self.player("WR Starter", "WR", projection=140, adp=4, vols=40, rank=4),
        ]
        ranked = rank_user_candidates(
            available,
            roster,
            "market_aware",
            pick_no=3,
            round_no=3,
            teams=1,
            draft_slot=1,
            roster_positions=["RB", "WR", "FLEX", "BN"],
            total_user_picks=4,
            replacement_baselines={"RB": 80, "WR": 100},
        )
        self.assertEqual(ranked[0]["player_name"], "WR Starter")
        self.assertGreater(ranked[0]["marginal_vorp"], ranked[1]["marginal_vorp"])

    def test_hybrid_uses_vols_in_round_one_then_vorp_formula(self) -> None:
        players = [
            self.player("VOLS Leader", "RB", projection=150, adp=1, vols=100, rank=1),
            self.player("VORP Leader", "WR", projection=180, adp=2, vols=90, rank=2),
        ]
        common = dict(
            available=players,
            roster=[],
            teams=1,
            draft_slot=1,
            roster_positions=["RB", "WR"],
            total_user_picks=2,
            replacement_baselines={"RB": 100, "WR": 100},
            bench_before_starters=1,
        )
        first = rank_user_candidates(
            policy="hybrid_20", pick_no=1, round_no=1, **common
        )
        later = rank_user_candidates(
            policy="hybrid_20", pick_no=2, round_no=2, **common
        )
        calibrated = rank_user_candidates(
            policy="calibrated", pick_no=2, round_no=2, **common
        )
        explicit = rank_user_candidates(
            policy="fs_w750", pick_no=2, round_no=2, **common
        )
        self.assertEqual(first[0]["player_name"], "VOLS Leader")
        self.assertEqual(later[0]["player_name"], "VORP Leader")
        self.assertEqual(calibrated[0]["player_name"], explicit[0]["player_name"])
        self.assertEqual(calibrated[0]["final_score"], explicit[0]["final_score"])

    def test_one_bench_cap_blocks_a_second_surplus_before_starters(self) -> None:
        roster = [
            self.player("QB", "QB", projection=200, adp=1, vols=50, rank=1),
            self.player("RB One", "RB", projection=180, adp=2, vols=40, rank=2),
            self.player("RB Flex", "RB", projection=170, adp=3, vols=35, rank=3),
            self.player("RB Bench", "RB", projection=160, adp=4, vols=30, rank=4),
        ]
        available = [
            self.player("More RB", "RB", projection=300, adp=5, vols=200, rank=5),
            self.player("Needed WR", "WR", projection=100, adp=20, vols=1, rank=20),
            self.player("Needed TE", "TE", projection=90, adp=21, vols=1, rank=21),
        ]
        ranked = rank_user_candidates(
            available,
            roster,
            "hybrid_20",
            pick_no=5,
            round_no=5,
            teams=1,
            draft_slot=1,
            roster_positions=["QB", "RB", "WR", "TE", "FLEX"],
            total_user_picks=13,
            replacement_baselines={"QB": 100, "RB": 100, "WR": 80, "TE": 70},
            bench_before_starters=1,
        )
        self.assertNotIn("More RB", [row["player_name"] for row in ranked])
        self.assertIn(ranked[0]["position"], {"WR", "TE"})

    def test_full_hybrid_draft_reserves_defense_kicker_and_sleeper(self) -> None:
        positions = ["RB", "WR", "QB", "TE"]
        board = [
            {
                "player_key": f"skill-{index}",
                "player_name": f"Skill {index}",
                "position": positions[(index - 1) % len(positions)],
                "projected_points": 350 - index,
                "adp": index,
                "vbd": 150 - index,
                "rank_score": index,
            }
            for index in range(1, 65)
        ]
        board.extend(
            {
                "player_key": f"k-{index}",
                "player_name": f"K {index}",
                "position": "K",
                "adp": 25 + index,
                "rank_score": index,
            }
            for index in range(1, 7)
        )
        board.extend(
            {
                "player_key": f"dst-{index}",
                "player_name": f"DST {index}",
                "position": "DST",
                "adp": 25 + index,
                "rank_score": index,
            }
            for index in range(1, 7)
        )
        results = compare_strategies(
            board,
            teams=2,
            draft_slot=1,
            roster_positions=[
                "QB", "RB", "RB", "WR", "WR", "TE", "WRRB_FLEX", "K", "DEF",
                "BN", "BN", "BN", "BN", "BN", "BN",
            ],
            rounds=15,
            trials=1,
            strategies=[
                "hybrid_20",
                "none_w00",
                "half_ppr_reconciled_special_k14_dst15",
                "half_ppr_reconciled_special_dst13_k14_flier15",
            ],
            include_trace=True,
            include_special_teams=True,
        )
        by_strategy = {result["strategy"]: result for result in results}
        trace = by_strategy["hybrid_20"]["trace"]
        self.assertEqual(len(trace["picks"]), 30)
        self.assertEqual(len(trace["user_decisions"]), 15)
        self.assertEqual(
            [decision["pick_role"] for decision in trace["user_decisions"][-3:]],
            ["defense", "kicker", "sleeper"],
        )
        self.assertTrue(trace["late_round_plan_complete"])
        self.assertIn(trace["final_roster"][-1]["position"], {"RB", "WR"})
        self.assertLessEqual(trace["max_bench_before_starters"], 1)
        self.assertIn("K", by_strategy["hybrid_20"]["average_special_ranks"])
        self.assertIn("DST", by_strategy["hybrid_20"]["average_special_ranks"])
        market_trace = by_strategy["none_w00"]["trace"]
        self.assertTrue(market_trace["special_teams_complete"])
        self.assertFalse(market_trace["late_round_plan_complete"])
        k_first_trace = by_strategy[
            "half_ppr_reconciled_special_k14_dst15"
        ]["trace"]
        self.assertEqual(
            [decision["pick_role"] for decision in k_first_trace["user_decisions"][-2:]],
            ["kicker", "defense"],
        )
        self.assertTrue(k_first_trace["specialist_plan_complete"])
        flier_trace = by_strategy[
            "half_ppr_reconciled_special_dst13_k14_flier15"
        ]["trace"]
        self.assertEqual(
            [decision["pick_role"] for decision in flier_trace["user_decisions"][-3:]],
            ["defense", "kicker", "sleeper"],
        )
        self.assertTrue(flier_trace["specialist_plan_complete"])

    def test_default_policies_produce_complete_auditable_drafts(self) -> None:
        positions = ["RB", "WR", "QB", "TE"]
        board = [
            {
                "player_key": f"player-{index}",
                "player_name": f"Player {index}",
                "position": positions[(index - 1) % len(positions)],
                "projected_points": 350 - index,
                "adp": index,
                "vbd": 150 - index,
                "rank_score": index,
            }
            for index in range(1, 49)
        ]
        result = compare_strategies(
            board,
            teams=2,
            draft_slot=1,
            roster_positions=["QB", "RB", "WR", "TE", "FLEX"],
            rounds=5,
            trials=2,
            seed=99,
            include_trace=True,
        )
        self.assertEqual(
            {row["strategy"] for row in result},
            {"scenario_safe", "scenario_calibrated"},
        )
        for row in result:
            self.assertIn("paired_win_rate", row)
            self.assertIn("paired_mean_regret", row)
            trace = row["trace"]
            self.assertEqual(len(trace["picks"]), 10)
            self.assertEqual(len(trace["user_decisions"]), 5)
            self.assertEqual(trace["starter_slots_filled"], trace["starter_slot_count"])
            self.assertTrue(trace["user_decisions"][0]["top_candidates"])
            self.assertEqual(
                set(row["representative_rosters"]), {"worst", "median", "best"}
            )

    def test_final_sleeper_feature_uses_vorp_for_nonzero_rb_or_wr(self) -> None:
        positions = ["RB", "WR", "QB", "TE"]
        board = [
            {
                "player_key": f"player-{index}",
                "player_name": f"Player {index}",
                "position": positions[(index - 1) % len(positions)],
                "projected_points": 250 - index,
                "adp": index,
                "vbd": 100 - index,
                "rank_score": index,
            }
            for index in range(1, 49)
        ]
        trace = compare_strategies(
            board,
            teams=2,
            draft_slot=1,
            roster_positions=["QB", "RB", "WR", "TE", "FLEX"],
            rounds=5,
            trials=1,
            strategies=["fsu_w750"],
            include_trace=True,
        )[0]["trace"]
        final_decision = trace["user_decisions"][-1]
        self.assertEqual(final_decision["pick_role"], "sleeper")
        self.assertIn(final_decision["selected"]["position"], {"RB", "WR"})
        self.assertGreater(final_decision["selected"]["projected_points"], 0)


if __name__ == "__main__":
    unittest.main()
