from __future__ import annotations

import unittest
from collections import Counter
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from roster_theory.inseason.evaluation import build_weekly_projection_matrix, weighted_lineup_score
from roster_theory.trade import finder
from roster_theory.trade.finder_roster import RosterGuard, qb_bundle_gain
from roster_theory.trade.target_optimizer import _context
from tests.test_trade_finder import inputs, run
from tests.test_trade_target_optimizer import permissive_options


def qb_case(*, slots=("QB", "WR", "BN", "BN", "BN")):
    case = list(inputs())
    snapshot, projections = case[:2]
    qbs = {"u_rb", "u_flex", "o_need", "o_fill", "fa_rb"}
    players = tuple(replace(p, positions=("QB",)) if p.player_id in qbs else p for p in snapshot.players)
    snapshot = replace(snapshot, players=players, league=replace(snapshot.league, roster_positions=slots))
    projections = tuple(replace(p, league_points=18.0) if p.player_id == "o_fill" else p for p in projections)
    case[:2] = snapshot, projections
    context = _context(snapshot)
    matrix = build_weekly_projection_matrix(context, projections)
    bases = {t.roster_id: set(t.player_ids) - set(t.reserve_ids) for t in snapshot.teams}
    return tuple(case), context, matrix, bases


class FinderRosterTests(unittest.TestCase):
    def test_both_qbs_cannot_be_rescued_by_a_waiver_add(self):
        case, _, matrix, bases = qb_case()
        guard = RosterGuard(case[0], matrix, bases)
        failures = guard.exchange_failures("2", ("u_sell",), ("o_fill", "o_need"))
        self.assertIn("starter_coverage:2:QB", failures)
        self.assertIn("redundant_depth:1:QB", failures)
        # A strong eligible unowned QB does not change actual exchanged coverage.
        self.assertIn("fa_rb", case[0].free_agent_ids)
        self.assertIn("fa_rb", guard.viable)

    def test_redundant_third_qb_is_pruned_but_qb_swap_is_allowed(self):
        case, _, matrix, bases = qb_case()
        guard = RosterGuard(case[0], matrix, bases)
        self.assertIn("redundant_depth:1:QB", guard.exchange_failures("2", ("u_sell",), ("o_need",)))
        self.assertFalse(guard.exchange_failures("2", ("u_rb",), ("o_need",)))

    def test_required_drop_can_resolve_depth_only_when_a_qb_is_returned(self):
        case, _, matrix, bases = qb_case()
        guard = RosterGuard(case[0], matrix, bases)
        self.assertFalse(guard.exchange_failures("2", ("u_rb",), ("o_fill", "o_need")))
        self.assertIn("redundant_depth:1:QB", guard.exchange_failures("2", ("u_sell",), ("o_fill", "o_need")))

    def test_superflex_allows_multi_qb_packages_with_returned_coverage(self):
        case, _, matrix, bases = qb_case(slots=("QB", "SUPER_FLEX", "WR", "BN", "BN"))
        guard = RosterGuard(case[0], matrix, bases)
        self.assertFalse(guard.exchange_failures("2", ("u_rb", "u_sell"), ("o_fill", "o_need")))
        self.assertIn("starter_coverage:2:QB", guard.exchange_failures("2", ("u_sell",), ("o_fill", "o_need")))

    def test_two_dedicated_qb_slots_retain_two_viable_qbs(self):
        case, _, matrix, bases = qb_case(slots=("QB", "QB", "WR", "BN", "BN"))
        guard = RosterGuard(case[0], matrix, bases)
        self.assertIn("starter_coverage:2:QB", guard.exchange_failures("2", ("u_sell",), ("o_need",)))
        self.assertFalse(guard.exchange_failures("2", ("u_rb",), ("o_need",)))

    def test_zero_forecast_backup_does_not_supply_viable_coverage(self):
        case, _, _, bases = qb_case()
        projections = tuple(replace(p, league_points=0.0) if p.player_id == "o_fill" else p for p in case[1])
        matrix = build_weekly_projection_matrix(_context(case[0]), projections)
        guard = RosterGuard(case[0], matrix, bases)
        self.assertIn("starter_coverage:2:QB", guard.exchange_failures("2", ("u_sell",), ("o_need",)))

    def test_joint_qb_estimate_matches_legal_lineup_not_independent_gains(self):
        case, context, matrix, bases = qb_case()
        options = permissive_options()
        before = bases["1"]
        incoming = {"o_fill", "o_need"}
        exact = weighted_lineup_score(context, matrix, before | incoming, options) - weighted_lineup_score(context, matrix, before, options)
        independent = sum(weighted_lineup_score(context, matrix, before | {pid}, options)
                          - weighted_lineup_score(context, matrix, before, options) for pid in incoming)
        joint = qb_bundle_gain(context, matrix, {"u_rb", "u_flex"}, {"u_rb", "u_flex", *incoming}, options)
        self.assertEqual(joint, exact)
        self.assertLess(joint, independent)
        loss = qb_bundle_gain(context, matrix, incoming, set(), options)
        self.assertEqual(loss, -54.0)

    def test_finder_prunes_before_exact_and_keeps_accounted_reasons(self):
        case, _, _, _ = qb_case()
        calls = []
        original = finder.evaluate_trade
        def counted(*args, **kwargs):
            calls.append(args[1])
            return original(*args, **kwargs)
        with patch.object(finder, "evaluate_trade", side_effect=counted):
            result = run(case)
        self.assertFalse(any({a.player_id for a in p.from_b} == {"o_fill", "o_need"}
                             and not any(a.player_id in {"u_rb", "u_flex"} for a in p.from_a) for p in calls))
        self.assertEqual(result.roster_policy_version, "trade-finder-roster-v1")
        self.assertTrue(result.rejection_samples)
        self.assertTrue(any("starter_coverage:2:QB" in r.failed_checks for r in result.rejection_samples))
        counts = Counter((r.opponent_roster_id, len(r.sent_player_ids), len(r.received_player_ids),
                          r.stage, reason) for r in result.rejection_samples for reason in r.failed_checks)
        self.assertTrue(all(n <= 3 for n in counts.values()))
        for row in result.shape_coverage:
            self.assertEqual(row.enumerated, row.price_pruned + row.roster_pruned + row.eligible + row.unconstructed)

    def test_unused_incoming_asset_is_diagnostic_even_when_strictly_acceptable(self):
        case = list(inputs())
        case[1] = tuple(replace(p, league_points=0.0) if p.player_id == "o_fill" else p for p in case[1])
        result = run(tuple(case))
        d = next(d for d in result.evaluated_decisions if d.sent_player_ids == ("u_sell",)
                 and d.received_player_ids == ("o_con", "o_fill"))
        self.assertFalse(d.accepted)
        self.assertEqual(d.package_verdict, "ACCEPTABLE")
        check = next(c for c in result.package_checks if c.evaluation_hash == d.evaluation_hash)
        self.assertIn("incoming_use:1:o_fill", check.failed_checks)
        self.assertFalse(next(u for u in check.incoming_usage if u.player_id == "o_fill").useful)
        self.assertNotIn(d.evaluation_hash, {i.decision.evaluation_hash for i in result.ideas})

    def test_counteroffer_requires_user_gates_and_partner_floor(self):
        result = run(inputs(), max_exact=1, max_large_exact=0)
        d = result.evaluated_decisions[0]
        d = replace(d, accepted=False, package_verdict="COUNTER", intrinsic_outcome="WIN")
        for changes in ({"intrinsic_outcome": "LOSS"}, {"user_downside_passed": False},
                        {"user_depth_passed": False}, {"partner_plausible": False},
                        {"partner_weighted_lineup_delta": -228.814}):
            self.assertIsNone(finder.idea_status(replace(d, **changes), minimum_gain=0.1,
                                                partner_lineup_floor=-5.0))
        self.assertEqual(d.package_verdict, "COUNTER")

    def test_csv_and_hash_verified_loader_preserve_new_evidence(self):
        import csv
        import json
        from dataclasses import asdict
        from roster_theory.core.provenance import stable_hash
        from roster_theory.trade.target_workflow import _csv_rows, _write_csv, load_target_workflow_evidence
        case = inputs()
        result = run(case, max_exact=1, max_large_exact=0)
        workflow = SimpleNamespace(packages=result, targets=case[-1],
            board_refresh=SimpleNamespace(refresh=SimpleNamespace(snapshot=case[0])))
        with TemporaryDirectory() as directory:
            path = Path(directory) / "finder.csv"
            _write_csv(path, _csv_rows(workflow))
            with path.open(encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertTrue({"EXECUTION", "COVERAGE", "PACKAGE_CHECK", "INCOMING_USE",
                             "ROSTER_REJECTION_SAMPLE"}.issubset({r["record_type"] for r in rows}))
            payload = {"packages": asdict(result), "evidence_hash": ""}
            payload["evidence_hash"] = stable_hash(payload)
            saved = Path(directory) / "finder.json"
            saved.write_text(json.dumps(payload), encoding="utf-8")
            loaded = load_target_workflow_evidence(saved)
            self.assertEqual(loaded["packages"]["roster_policy_version"], "trade-finder-roster-v1")
            self.assertEqual(loaded["packages"]["package_checks"][0]["evaluation_hash"],
                             result.package_checks[0].evaluation_hash)
