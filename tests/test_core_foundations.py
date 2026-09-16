import ast
import json
import tempfile
import unittest
from dataclasses import FrozenInstanceError
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from roster_theory.core.errors import RequestBudgetExceeded
from roster_theory.core.identity import reconcile_identities
from roster_theory.core.lineup import LineupPlayer, lineup_slots, optimize_lineup
from roster_theory.core.models import Player
from roster_theory.core.provenance import (
    AnalysisManifest,
    DataStamp,
    canonical_json,
    stable_hash,
)
from roster_theory.core.replacement import (
    current_free_agents,
    positional_waiver_baselines,
)
from roster_theory.core.scoring import score_stats
from roster_theory.providers.cache import (
    DailyRequestBudget,
    RequestDeduplicator,
    atomic_write_json,
    cache_key,
    is_fresh,
)


class ProvenanceTests(unittest.TestCase):
    def test_manifest_is_immutable_and_reproducible(self) -> None:
        stamp = DataStamp(
            source="fixture",
            endpoint="/weekly",
            captured_at=datetime(2026, 9, 4, tzinfo=timezone.utc),
            season=2026,
            week=1,
        )
        kwargs = {
            "league_id": "league-1",
            "user_id": "user-1",
            "current_week": 1,
            "horizon_start": 1,
            "horizon_end": 17,
            "configuration": {"b": 2, "a": 1},
            "normalized_inputs": {"players": ["2", "1"]},
            "data_stamps": (stamp,),
        }
        first = AnalysisManifest.build(**kwargs)
        second = AnalysisManifest.build(**kwargs)

        self.assertEqual(first, second)
        self.assertEqual(first.analysis_id, second.analysis_id)
        self.assertEqual(first.scenario_seed, first.analysis_id[:16])
        with self.assertRaises(FrozenInstanceError):
            first.current_week = 2  # type: ignore[misc]

    def test_canonical_json_orders_mappings_and_rejects_nonfinite_values(self) -> None:
        self.assertEqual(canonical_json({"b": 2, "a": 1}), '{"a":1,"b":2}')
        self.assertEqual(stable_hash({"a": 1, "b": 2}), stable_hash({"b": 2, "a": 1}))
        with self.assertRaises(ValueError):
            canonical_json({"bad": float("nan")})


class CacheTests(unittest.TestCase):
    def test_cache_key_deduplication_atomic_write_and_freshness(self) -> None:
        self.assertEqual(
            cache_key("/rank", {"week": 1, "position": "RB"}),
            cache_key("/rank", {"position": "RB", "week": 1}),
        )
        calls = 0

        def fetch():
            nonlocal calls
            calls += 1
            return {"value": 7}

        dedupe = RequestDeduplicator()
        first, first_hit = dedupe.get_or_call("/rank", {"week": 1}, fetch)
        second, second_hit = dedupe.get_or_call("/rank", {"week": 1}, fetch)
        self.assertEqual(first, second)
        self.assertFalse(first_hit)
        self.assertTrue(second_hit)
        self.assertEqual(calls, 1)

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nested" / "cache.json"
            atomic_write_json(path, {"b": 2, "a": 1})
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"a": 1, "b": 2})
            self.assertEqual(list(path.parent.glob("*.tmp")), [])

        now = datetime(2026, 9, 4, 12, tzinfo=timezone.utc)
        self.assertTrue(is_fresh(now - timedelta(hours=1), timedelta(hours=2), now=now))
        self.assertFalse(is_fresh(now - timedelta(hours=3), timedelta(hours=2), now=now))

    def test_daily_budget_rolls_over_and_stops_before_excess(self) -> None:
        budget = DailyRequestBudget(limit=3)
        self.assertEqual(budget.reserve(2, today=date(2026, 9, 4)), 1)
        with self.assertRaises(RequestBudgetExceeded):
            budget.reserve(2, today=date(2026, 9, 4))
        self.assertEqual(budget.reserve(1, today=date(2026, 9, 5)), 2)
        self.assertEqual(DailyRequestBudget.from_json(budget.to_json()), budget)


class IdentityTests(unittest.TestCase):
    def test_exact_external_alias_unmatched_and_ambiguous_are_audited(self) -> None:
        source = [
            {"sid": "same", "yahoo": None},
            {"sid": "s2", "yahoo": "y2"},
            {"sid": "s3"},
            {"sid": "missing"},
            {"sid": "ambiguous", "yahoo": "duplicate"},
        ]
        target = [
            {"fid": "same"},
            {"fid": "f2", "yahoo": "y2"},
            {"fid": "f3"},
            {"fid": "f4", "yahoo": "duplicate"},
            {"fid": "f5", "yahoo": "duplicate"},
        ]
        report = reconcile_identities(
            source,
            target,
            source_id_field="sid",
            target_id_field="fid",
            shared_id_fields=("yahoo",),
            aliases={"s3": "f3"},
        )

        self.assertEqual(
            [(match.source_id, match.target_id, match.method) for match in report.matches],
            [
                ("s2", "f2", "external_id"),
                ("s3", "f3", "explicit_alias"),
                ("same", "same", "exact_id"),
            ],
        )
        self.assertEqual(report.unmatched[0].source_id, "missing")
        self.assertEqual(report.ambiguous[0].candidate_target_ids, ("f4", "f5"))
        self.assertFalse(report.complete)


class ScoringAndLineupTests(unittest.TestCase):
    def test_scoring_preserves_stats_and_reports_unsupported_settings(self) -> None:
        result = score_stats(
            {"pass_yds": 250, "pass_tds": 2, "custom": 9},
            {"pass_yd": 0.04, "pass_td": 4, "bonus_pass_300": 3},
        )
        self.assertEqual(result.points, 18.0)
        self.assertEqual(result.unsupported_settings, ("bonus_pass_300",))
        self.assertIn(("custom", 9), result.raw_stats)

    def test_optimizer_handles_multiple_flex_types_and_stable_ties(self) -> None:
        players = [
            LineupPlayer("qb", ("QB",)),
            LineupPlayer("rb-a", ("RB",)),
            LineupPlayer("rb-b", ("RB",)),
            LineupPlayer("wr-a", ("WR",)),
            LineupPlayer("wr-b", ("WR",)),
            LineupPlayer("te", ("TE",)),
        ]
        result = optimize_lineup(
            players,
            ("QB", "RB", "WR", "WRRB_FLEX", "REC_FLEX", "BN"),
            {"qb": 20, "rb-a": 12, "rb-b": 11, "wr-a": 12, "wr-b": 10, "te": 9},
        )
        self.assertEqual(result.score, 65.0)
        self.assertEqual(result.filled_slots, 5)
        self.assertEqual(result.unused_player_ids, ("te",))
        self.assertEqual(
            [assignment.player_id for assignment in result.assignments],
            ["qb", "rb-a", "wr-a", "rb-b", "wr-b"],
        )

    def test_optimizer_supports_superflex_and_def_alias(self) -> None:
        result = optimize_lineup(
            [
                LineupPlayer("qb1", ("QB",)),
                LineupPlayer("qb2", ("QB",)),
                LineupPlayer("dst", ("DST",)),
            ],
            ("QB", "SUPER_FLEX", "DEF"),
            {"qb1": 21, "qb2": 19, "dst": 7},
        )
        self.assertEqual(result.score, 47.0)
        self.assertEqual(result.total_slots, 3)

    def test_optimizer_matches_brute_force_on_small_rosters(self) -> None:
        def brute_force(players, roster_positions, points):
            slots = lineup_slots(roster_positions)
            best = (0, 0.0)

            def visit(slot_index, used, filled, score):
                nonlocal best
                if slot_index == len(slots):
                    best = max(best, (filled, score))
                    return
                visit(slot_index + 1, used, filled, score)
                eligible = set(slots[slot_index][1])
                for player in players:
                    if player.player_id in used or eligible.isdisjoint(player.positions):
                        continue
                    visit(
                        slot_index + 1,
                        {*used, player.player_id},
                        filled + 1,
                        score + points[player.player_id],
                    )

            visit(0, set(), 0, 0.0)
            return best

        players = [
            LineupPlayer("a", ("QB",)),
            LineupPlayer("b", ("QB", "WR")),
            LineupPlayer("c", ("RB",)),
            LineupPlayer("d", ("WR", "TE")),
            LineupPlayer("e", ("TE",)),
        ]
        points = {"a": 4.0, "b": 7.0, "c": -1.0, "d": 5.0, "e": 3.0}
        for positions in (
            ("QB", "RB", "WR"),
            ("QB", "FLEX", "REC_FLEX"),
            ("SUPER_FLEX", "WRRB_FLEX", "TE"),
        ):
            with self.subTest(positions=positions):
                result = optimize_lineup(players, positions, points)
                expected_filled, expected_score = brute_force(players, positions, points)
                self.assertEqual(result.filled_slots, expected_filled)
                self.assertEqual(result.score, expected_score)


class ReplacementTests(unittest.TestCase):
    def test_baseline_uses_only_current_unowned_points(self) -> None:
        players = [
            Player("owned", "Owned", ("RB",)),
            Player("fa-low", "Low", ("RB",)),
            Player("fa-high", "High", ("RB", "WR")),
        ]
        free_agents = current_free_agents(players, ["owned"])
        self.assertEqual([player.player_id for player in free_agents], ["fa-high", "fa-low"])
        baselines = positional_waiver_baselines(
            players,
            ["owned"],
            {"owned": 1000, "fa-low": 8, "fa-high": 11},
            positions=("RB", "WR"),
        )
        self.assertEqual(baselines["RB"].player_id, "fa-high")
        self.assertEqual(baselines["RB"].points, 11)
        self.assertEqual(baselines["WR"].player_id, "fa-high")


class ImportBoundaryTests(unittest.TestCase):
    def test_core_and_providers_do_not_import_feature_policy(self) -> None:
        source_root = Path(__file__).parents[1] / "src" / "roster_theory"
        prohibited = (
            "roster_theory.trade",
            "roster_theory.simulation",
            "roster_theory.mock_watcher",
            "roster_theory.draft_analysis",
        )
        violations: list[str] = []
        for package in ("core", "providers"):
            for path in (source_root / package).glob("*.py"):
                tree = ast.parse(path.read_text(encoding="utf-8"))
                for node in ast.walk(tree):
                    module = None
                    if isinstance(node, ast.ImportFrom):
                        module = node.module
                    elif isinstance(node, ast.Import):
                        for alias in node.names:
                            if alias.name.startswith(prohibited):
                                violations.append(f"{path.name}:{alias.name}")
                    if module and module.startswith(prohibited):
                        violations.append(f"{path.name}:{module}")
        self.assertEqual(violations, [])


if __name__ == "__main__":
    unittest.main()
