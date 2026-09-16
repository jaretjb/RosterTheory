import unittest
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

from roster_theory.providers.fantasypros import normalize_rankings
from roster_theory.waiver.emergence import build_emergence_evidence
from roster_theory.waiver.evaluation import PlayerValueInput, evaluate_waiver
from roster_theory.waiver.policy import apply_waiver_policy, load_waiver_policy
from roster_theory.waiver.service import format_waiver_evaluation
from roster_theory.waiver.ww_evidence import (
    WaiverWireConfig,
    build_waiver_wire_evidence,
)
from tests.test_waiver_emerging_value import (
    emergence_bundle,
    measure,
    scored_snapshot,
    trend_rows,
)
from tests.test_waiver_evaluation import NOW, legality, projections, values, weeks


WAIVER_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "waiver"
LEAGUE_ALPHA_POLICY = WAIVER_FIXTURE_DIR / "league_alpha.decision-policy.json"
LEAGUE_BETA_POLICY = WAIVER_FIXTURE_DIR / "league_beta.decision-policy.json"


def _snapshot(*, league_key="league_alpha", state="FREE_AGENT"):
    snapshot = scored_snapshot()
    players = tuple(
        replace(player, fantasypros_id="10")
        if player.player_id == "fa_rb"
        else player
        for player in snapshot.players
    )
    acquisitions = tuple(
        replace(row, state=state) if row.player_id == "fa_rb" else row
        for row in snapshot.acquisitions
    )
    return replace(
        snapshot,
        league_key=league_key,
        players=players,
        acquisitions=acquisitions,
    )


def _ranking(rank, *, captured_at, expert_id=None):
    return normalize_rankings(
        {
            "year": "2026",
            "week": "1",
            "scoring": "HALF",
            "ranking_type_name": "Waiver Wire",
            "last_updated": captured_at.isoformat(),
            "players": [
                {
                    "player_id": "10",
                    "player_name": "Free Runner",
                    "player_position_id": "RB",
                    "player_team_id": "HHH",
                    "rank_ecr": rank,
                    "pos_rank": "RB1",
                    "rank_min": rank,
                    "rank_max": rank,
                    "rank_std": 0.0,
                }
            ],
        },
        requested_horizon="WAIVER",
        board_source="market" if expert_id is None else "selected",
        expert_id=expert_id,
        captured_at=captured_at,
    )


def waiver_wire(
    *,
    league_key="league_alpha",
    market_rank=5,
    expert_ranks=(5,),
    stale=False,
):
    captured = NOW - timedelta(hours=48) if stale else NOW
    expert_ids = tuple(f"expert-{index}" for index in range(len(expert_ranks)))
    return build_waiver_wire_evidence(
        config=WaiverWireConfig(
            league_key=league_key,
            scoring="HALF",
            position="ALL",
            maximum_age_hours=24,
            trusted_expert_ids=expert_ids,
            config_hash=f"{league_key}-controlled-ww",
        ),
        players=_snapshot(league_key=league_key).players,
        market=_ranking(market_rank, captured_at=captured),
        selected={
            expert_id: _ranking(rank, captured_at=captured, expert_id=expert_id)
            for expert_id, rank in zip(expert_ids, expert_ranks)
        },
        now=NOW,
    )


def _league_beta_values():
    return tuple(
        PlayerValueInput("fa_rb", 12.0, 9.0, 15.0)
        if row.player_id == "fa_rb"
        else row
        for row in values()
    )


def _conflicting_role():
    rows = trend_rows("fa_rb", "Free Runner", "HHH", "RB")
    source_a = replace(rows[2], source="controlled source A")
    source_b = replace(
        rows[2],
        source="controlled source B",
        carries=measure(3, 25),
    )
    return build_emergence_evidence(
        league_key="league_alpha",
        observations=(rows[0], rows[1], source_a, source_b),
        captured_at=NOW,
    )


def decide(
    *,
    league_key="league_alpha",
    state="FREE_AGENT",
    market_rank=5,
    expert_ranks=(5,),
    stale=False,
    role=None,
    value_rows=None,
):
    policy_path = LEAGUE_BETA_POLICY if league_key == "league_beta" else LEAGUE_ALPHA_POLICY
    evaluated = evaluate_waiver(
        _snapshot(league_key=league_key, state=state),
        add="Free Runner",
        drop="Bench Receiver",
        weeks=weeks(),
        projections=projections(),
        values=value_rows or (_league_beta_values() if league_key == "league_beta" else values()),
        drop_legality=legality(),
        news_fresh={"fa_rb": True},
        waiver_wire_evidence=waiver_wire(
            league_key=league_key,
            market_rank=market_rank,
            expert_ranks=expert_ranks,
            stale=stale,
        ),
        emergence_evidence=role or emergence_bundle(league_key=league_key),
        now=NOW,
    )
    return apply_waiver_policy(evaluated, load_waiver_policy(policy_path))


class EmergingUpsidePolicyTests(unittest.TestCase):
    def test_league_alpha_complete_evidence_adds_cheap_drop_now(self):
        result = decide()
        self.assertEqual(result.decision_label, "ADD NOW")
        self.assertEqual(result.decision.decision_path, "EMERGING_UPSIDE")
        self.assertTrue(all(gate.passed for gate in result.decision.gates))
        self.assertGreater(result.decision.priority_score, 0)
        self.assertTrue(result.decision.reversal_conditions)

    def test_emerging_waiver_target_is_a_claim(self):
        result = decide(state="WAIVERS")
        self.assertEqual(result.decision_label, "CLAIM")
        self.assertEqual(result.decision.decision_path, "EMERGING_UPSIDE")

    def test_league_alpha_policy_allows_selected_support_without_market_support(self):
        result = decide(market_rank=30, expert_ranks=(5,))
        support = next(
            gate for gate in result.decision.gates if gate.name == "waiver_wire_support"
        )
        self.assertEqual(result.decision_label, "ADD NOW")
        self.assertTrue(support.passed)
        self.assertIn("mode=MARKET_OR_SELECTED", support.explanation)

    def test_league_beta_requires_market_and_two_selected_experts(self):
        result = decide(league_key="league_beta", expert_ranks=(5, 8))
        self.assertEqual(result.decision_label, "ADD NOW")
        self.assertEqual(result.decision.decision_path, "EMERGING_UPSIDE")
        support = next(
            gate for gate in result.decision.gates if gate.name == "waiver_wire_support"
        )
        self.assertIn("2/2", support.explanation)
        self.assertIn("mode=MARKET_AND_SELECTED", support.explanation)

    def test_league_beta_does_not_promote_selected_only_support(self):
        result = decide(
            league_key="league_beta",
            market_rank=30,
            expert_ranks=(5, 8),
        )
        self.assertNotIn(result.decision_label, {"ADD NOW", "CLAIM"})
        support = next(
            gate for gate in result.decision.gates if gate.name == "waiver_wire_support"
        )
        self.assertFalse(support.passed)
        self.assertTrue(any("disagree" in warning.lower() for warning in result.warnings))

    def test_stale_waiver_evidence_can_only_watch(self):
        result = decide(stale=True)
        self.assertEqual(result.decision_label, "WATCH")
        self.assertEqual(
            result.decision.decision_path,
            "EMERGING_UPSIDE_INCOMPLETE_OR_NEAR_THRESHOLD",
        )
        complete = next(
            gate
            for gate in result.decision.gates
            if gate.name == "emerging_complete_fresh_evidence"
        )
        self.assertFalse(complete.passed)

    def test_near_threshold_value_deficit_can_only_watch(self):
        near_values = tuple(
            PlayerValueInput("fa_rb", 3.5, 2.5, 15.0)
            if row.player_id == "fa_rb"
            else row
            for row in values()
        )
        result = decide(value_rows=near_values)
        self.assertEqual(result.decision_label, "WATCH")
        self.assertEqual(
            result.decision.decision_path,
            "EMERGING_UPSIDE_INCOMPLETE_OR_NEAR_THRESHOLD",
        )
        selected_value = next(
            gate
            for gate in result.decision.gates
            if gate.name == "emerging_selected_value_deficit"
        )
        self.assertFalse(selected_value.passed)

    def test_conflicting_role_sources_can_only_watch(self):
        role = _conflicting_role()
        self.assertEqual(role.players[0].classification, "CONFLICTING")
        result = decide(role=role)
        self.assertEqual(result.decision_label, "WATCH")
        self.assertEqual(
            result.decision.decision_path,
            "EMERGING_UPSIDE_INCOMPLETE_OR_NEAR_THRESHOLD",
        )

    def test_touchdown_spike_without_role_growth_never_promotes(self):
        negative_values = tuple(
            PlayerValueInput("fa_rb", 0.0, 0.0, 0.0)
            if row.player_id == "fa_rb"
            else row
            for row in values()
        )
        result = decide(
            role=emergence_bundle(spike=True),
            value_rows=negative_values,
        )
        self.assertEqual(result.decision_label, "PASS")
        self.assertEqual(
            result.decision.decision_path,
            "EMERGING_UPSIDE_VALUE_OR_SAFETY_FAILURE",
        )

    def test_comparable_drop_emergence_is_protected(self):
        result = decide(role=emergence_bundle(drop="bench"))
        self.assertEqual(result.decision_label, "PASS")
        self.assertEqual(
            result.decision.decision_path,
            "EMERGING_UPSIDE_RETAINED_DROP_PROTECTED",
        )
        option_gate = next(
            gate
            for gate in result.decision.gates
            if gate.name == "emerging_incremental_option_value"
        )
        self.assertFalse(option_gate.passed)
        self.assertLess(
            result.candidates[0].emerging_upside.incremental_option_value,
            0,
        )
        self.assertTrue(result.candidates[0].emerging_upside.no_action.best_in_every_scenario)

    def test_selected_expert_disagreement_remains_visible(self):
        result = decide(expert_ranks=(5, 30))
        self.assertEqual(result.decision_label, "ADD NOW")
        self.assertIn("disagree", result.strongest_uncertainty.lower())
        self.assertTrue(any("disagree" in warning.lower() for warning in result.warnings))

    def test_report_explains_states_break_even_disagreement_and_reversals(self):
        result = decide(expert_ranks=(5, 30))
        report = format_waiver_evaluation(
            SimpleNamespace(
                evaluation=result,
                refresh=SimpleNamespace(snapshot=_snapshot()),
                output_path=Path("controlled-evaluation.json"),
            )
        )
        self.assertIn("Emerging state MISS", report)
        self.assertIn("Emerging state USEFUL_ROLE", report)
        self.assertIn("Emerging state BREAKOUT", report)
        self.assertIn("ACT_NOW minus RETAIN_DROP", report)
        self.assertIn("Emerging break-even interpretation", report)
        self.assertIn("selected-expert support=1/2", report)
        self.assertIn("Reversal conditions", report)
        self.assertIn("disagree", report.lower())

    def test_league_specific_policies_are_independent(self):
        league_alpha = load_waiver_policy(LEAGUE_ALPHA_POLICY)
        league_beta = load_waiver_policy(LEAGUE_BETA_POLICY)
        self.assertNotEqual(league_alpha.league_key, league_beta.league_key)
        self.assertNotEqual(
            league_alpha.emerging_ww_support_mode,
            league_beta.emerging_ww_support_mode,
        )
        self.assertNotEqual(
            league_alpha.emerging_minimum_incremental_option_value,
            league_beta.emerging_minimum_incremental_option_value,
        )


if __name__ == "__main__":
    unittest.main()
