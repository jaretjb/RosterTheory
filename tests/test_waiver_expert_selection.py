import csv
import json
import tempfile
import unittest
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from roster_theory.application.value_preparation import ValueInputs
from roster_theory.core.call_plan import build_call_plan
from roster_theory.core.errors import CoverageIncomplete
from roster_theory.core.models import RankObservation
from roster_theory.providers.cache import DailyRequestBudget
from roster_theory.providers.expert_accuracy import (
    AnnualExpertAccuracy, annual_accuracy_from_directory, load_weekly_accuracy_history,
    write_weekly_accuracy_history,
)
from roster_theory.providers.fantasypros import normalize_rankings
from roster_theory.providers.inseason_experts import CurrentExpert
from roster_theory.waiver.expert_selection import (
    WaiverExpertPreparation, historical_scores, select_position_panel, strict_selected_ranks,
    publication_issue,
)


NOW = datetime(2099, 10, 13, 12, tzinfo=timezone.utc)
YEARS = tuple(range(2094, 2099))
POSITIONS = ("QB", "RB", "WR", "TE")


def expert(i, source=None, positions=POSITIONS):
    return CurrentExpert(str(i), f"Expert {i}", source or f"Source {i}",
        tuple((p, NOW.isoformat()) for p in positions), (("ALL", 1),), (("ALL", 1),))


def annual(i, year, rank, field=100):
    return AnnualExpertAccuracy(year, str(i), f"Expert {i}", f"Source {i}", rank, field,
                               f"https://www.fantasypros.com/nfl/accuracy/?year={year}")


def ballot(player, i, rank, horizon="ROS", position="TE"):
    return RankObservation(player, horizon, "expert_ballot", str(i), position, rank, None)


def market(player, rank, horizon="ROS", position="TE"):
    return RankObservation(player, horizon, "market", None, position, rank, None)


def ranking(position, horizon, experts=("1",)):
    return {"year": 2099, "scoring": "HALF", "week": 6,
        "ranking_type_name": horizon, "last_updated": NOW.isoformat(),
        "expert_names": {i: f"Expert {i}" for i in experts},
        "players": [{"player_id": f"{position}-{j}", "player_name": f"Player {j}",
            "player_position_id": position, "player_team_id": "SEA", "pos_rank": f"{position}{j}",
            "rank_ecr": j, "experts": {i: j for i in experts}} for j in range(1, 4)]}


class FakeProvider:
    def __init__(self, *, unavailable=(), wrong_filter=False, ros_omits=()):
        self.calls = []
        self.unavailable, self.wrong_filter = unavailable, wrong_filter
        self.ros_omits = ros_omits

    def get(self, endpoint, params):
        self.calls.append((endpoint, params))
        if endpoint.endswith("/experts"):
            return {"season": 2099, "experts": [{"expert_id": i, "name": f"Expert {i}",
                "source": f"Source {i}", "positions": {p: NOW.isoformat() for p in POSITIONS}}
                for i in range(1, 5) if not (params.get("ranking_type") == "ros" and str(i) in self.ros_omits)]}
        i = params["filters"].split(":")[0]
        raw = ranking(params["position"], "ROS" if "type" in params else "WEEKLY", (i,))
        if i in self.unavailable:
            raw["fallback_for"] = "ROS"
        if self.wrong_filter:
            raw["expert_names"]["999"] = "Unexpected expert"
        return raw


class HistoricalSelectionTests(unittest.TestCase):
    def test_consistent_five_year_expert_beats_one_recent_spike(self):
        rows = [annual(1, y, 10) for y in YEARS]
        rows += [annual(2, y, 80 if y != YEARS[-1] else 1) for y in YEARS]
        scores = historical_scores(rows, YEARS)
        self.assertGreater(scores["1"]["score"], scores["2"]["score"])
        expected = (0.08 * (1 - 9 / 99) + 0.15 * (1 - 9 / 99)
                    + 0.21 * (1 - 9 / 99) + 0.26 * (1 - 9 / 99) + 0.30 * (1 - 9 / 99))
        self.assertAlmostEqual(scores["1"]["score"], expected)

    def test_history_coverage_penalty_and_one_year_exclusion(self):
        rows = [annual(1, y, 10) for y in YEARS]
        rows += [annual(2, y, 10) for y in YEARS[-2:]] + [annual(3, YEARS[-1], 1)]
        scores = historical_scores(rows, YEARS)
        self.assertGreater(scores["1"]["score"], scores["2"]["score"])
        self.assertFalse(scores["3"]["eligible"])

    def test_position_and_horizon_coverage_are_independent_and_audited(self):
        experts = (expert(1, positions=("TE",)), expert(2), expert(3), expert(4))
        scores = historical_scores([annual(i, y, i) for i in range(1, 5) for y in YEARS], YEARS)
        te, _ = select_position_panel(experts=experts, scores=scores, published_ids={"1", "2", "3", "4"},
                                     position="TE", now=NOW, horizon="ROS")
        qb, evidence = select_position_panel(experts=experts, scores=scores,
            published_ids={"2", "3", "4"}, position="QB", now=NOW, horizon="ROS", advertised_ids={"1"})
        self.assertEqual([m.expert_id for m in te], ["1", "2", "3"])
        self.assertEqual([m.expert_id for m in qb], ["2", "3", "4"])
        self.assertEqual(evidence["candidates"][0]["reason"], "missing_position_update")
        self.assertNotAlmostEqual(te[0].weight, te[1].weight)

    def test_source_cap_replaces_same_source_third_expert(self):
        experts = (expert(1, "Same"), expert(2, "Same"), expert(3, "Same"), expert(4))
        scores = historical_scores([annual(i, y, i) for i in range(1, 5) for y in YEARS], YEARS)
        members, audit = select_position_panel(experts=experts, scores=scores,
            published_ids={"1", "2", "3", "4"}, position="TE", now=NOW, horizon="ROS")
        self.assertEqual([m.expert_id for m in members], ["1", "2", "4"])
        self.assertEqual(next(r for r in audit["candidates"] if r["expert_id"] == "3")["reason"],
                         "source_concentration_limit")

    def test_stale_future_unknown_and_missing_history_are_distinct(self):
        old = replace(expert(1), position_updates=(("TE", (NOW - timedelta(days=15)).isoformat()),))
        future = replace(expert(2), position_updates=(("TE", (NOW + timedelta(days=1)).isoformat()),))
        scores = historical_scores([annual(i, y, i) for i in (1, 2) for y in YEARS], YEARS)
        _, audit = select_position_panel(experts=(old, future, expert(3)), scores=scores,
            published_ids={"1", "2", "3"}, position="TE", now=NOW, horizon="ROS", advertised_ids={"99"})
        reasons = {r["expert_id"]: r["reason"] for r in audit["candidates"]}
        self.assertEqual(reasons, {"1": "stale_position_update", "2": "future_position_update",
            "3": "insufficient_historical_accuracy", "99": "missing_current_expert_directory_identity"})

    def test_provider_month_day_update_retains_calendar_precision(self):
        current = replace(expert(1), position_updates=(("TE", "10/13"),))
        self.assertIsNone(publication_issue(current, "TE", NOW, timedelta(days=7)))
        future = replace(expert(1), position_updates=(("TE", "10/14"),))
        self.assertEqual(publication_issue(future, "TE", NOW, timedelta(days=7)), "future_position_update")

    def test_no_market_substitution_for_missing_or_partial_player_ballots(self):
        rows = strict_selected_ranks((market("a", 1), market("b", 2), market("missing", 3)),
            (ballot("a", 1, 2), ballot("a", 2, 1), ballot("b", 1, 1), ballot("b", 2, 2),
             ballot("missing", 1, 3)), {"TE": {"1": 0.7, "2": 0.3}}, horizon="ROS")
        by_id = {row.player_id: row for row in rows}
        self.assertEqual(set(by_id), {"a", "b"})
        self.assertEqual(by_id["b"].final_position_rank, 1)
        self.assertAlmostEqual(by_id["a"].raw_position_rank, 1.7)
        self.assertTrue(all(row.shrinkage_to_ecr == 0 for row in rows))

    def test_conflicting_duplicate_ballot_fails(self):
        with self.assertRaisesRegex(CoverageIncomplete, "Conflicting"):
            strict_selected_ranks((market("a", 1),), (ballot("a", 1, 1), ballot("a", 1, 2)),
                                  {"TE": {"1": 1}}, horizon="ROS")

    def test_canonical_weekly_proxy_keeps_weighted_rank_and_separate_market(self):
        selector = WaiverExpertPreparation("fixture")
        from roster_theory.application.value_preparation import ExpertPoolMember
        selector.panels[("WEEKLY", "TE")] = (
            ExpertPoolMember("1", "Expert 1", "Source 1", 0.7),
            ExpertPoolMember("2", "Expert 2", "Source 2", 0.3))
        market_rows = (market("a", 1, "WEEKLY-PROXY"), market("b", 2, "WEEKLY-PROXY"))
        ballots = (ballot("a", 1, 2, "WEEKLY-PROXY"), ballot("a", 2, 1, "WEEKLY-PROXY"),
                   ballot("b", 1, 1, "WEEKLY-PROXY"), ballot("b", 2, 2, "WEEKLY-PROXY"))
        ranked = selector.aggregate_weekly(market_rows, ballots)
        self.assertEqual(next(r.position_rank for r in ranked if r.player_id == "b"), 1)
        self.assertEqual(market_rows[0].position_rank, 1)
        self.assertTrue(all(r.board_source == "historical_selected_experts" for r in ranked))


class PreparationTests(unittest.TestCase):
    def prepare(self, root, client):
        path = root / "history.csv"
        write_weekly_accuracy_history(path, [annual(i, y, i, 4) for y in YEARS for i in range(1, 5)])
        datasets = {h: tuple(normalize_rankings(ranking(p, h), requested_horizon=h,
            board_source="market", captured_at=NOW) for p in POSITIONS) for h in ("WEEKLY", "ROS")}
        inputs = ValueInputs(datasets["WEEKLY"], datasets["ROS"], (), (), (),
                             build_call_plan([], DailyRequestBudget()))
        selector = WaiverExpertPreparation("fixture", history_path=path)
        with patch("roster_theory.waiver.expert_selection.pace_request"):
            prepared = selector.prepare_inputs(inputs,
                SimpleNamespace(league=SimpleNamespace(season=2099), manifest=SimpleNamespace(current_week=6)),
                client, root / "cache", root / "budget.json", NOW)
        return selector, prepared

    def test_missing_advertised_ballots_are_fetched_and_all_positions_audited(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            provider = FakeProvider()
            selector, prepared = self.prepare(root, provider)
            self.assertEqual(len(selector.evidence["panels"]), 8)
            self.assertTrue(selector.evidence["ros_accuracy_is_proxy"])
            self.assertTrue(all(len(p["members"]) == 3 for p in selector.evidence["panels"].values()))
            self.assertEqual(prepared.call_plan.fantasypros_calls, len(provider.calls))
            self.assertGreater(len(provider.calls), 2)
            resolution = selector(prepared, NOW)
            self.assertAlmostEqual(sum(m.weight for m in resolution.members), 1.0)
            self.assertNotEqual(resolution.members[0].weight, resolution.members[1].weight)
            self.assertEqual(resolution.evidence["member_weight_scope"],
                             "union_identity_list; rank weights are recorded per panel")
            # The same immutable sources are reusable without any provider calls.
            cached = FakeProvider()
            _, second = self.prepare(root, cached)
            self.assertEqual(cached.calls, [])
            self.assertEqual(second.call_plan.fantasypros_calls, 0)

    def test_unpublished_expert_is_recorded_and_two_member_panel_is_degraded(self):
        with tempfile.TemporaryDirectory() as directory:
            selector, _ = self.prepare(Path(directory), FakeProvider(unavailable=("2",)))
            panel = selector.evidence["panels"]["ROS:TE"]
            self.assertEqual(panel["status"], "DEGRADED")
            self.assertEqual(next(r for r in panel["candidates"] if r["expert_id"] == "2")["reason"],
                             "wrong_or_partial_ballot_horizon")

    def test_ignored_single_expert_filter_cannot_be_used_as_individual_ballot(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(CoverageIncomplete, "fewer than 2"):
                self.prepare(Path(directory), FakeProvider(wrong_filter=True))

    def test_missing_ros_directory_identity_is_reconciled_without_borrowing_weekly_votes(self):
        with tempfile.TemporaryDirectory() as directory:
            provider = FakeProvider(ros_omits=("2",))
            selector, prepared = self.prepare(Path(directory), provider)
            self.assertIn("2", selector.evidence["ros_identity_reconciliation"]["additional_identity_ids"])
            self.assertFalse(selector.evidence["ros_identity_reconciliation"]["publication_inferred"])
            self.assertIn("2", [m["expert_id"] for m in selector.evidence["panels"]["ROS:TE"]["members"]])
            self.assertTrue(any(params.get("filters") == "2" and params.get("type") == "ROS"
                                for _, params in provider.calls))
            self.assertTrue(all(row.horizon == "ROS" for dataset in prepared.ros_rankings
                                for row in dataset.contributor_observations))


class HistoryAuthorityTests(unittest.TestCase):
    def test_refreshed_history_retains_shared_csv_compatibility(self):
        from roster_theory.trade.experts import load_inseason_accuracy
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "history.csv"
            write_weekly_accuracy_history(path, [annual(i, y, i, 4) for y in YEARS for i in range(1, 5)])
            records = load_inseason_accuracy(path)
            self.assertEqual(len(records), 20)
            self.assertAlmostEqual(records[0].overall_percentile, 1.0)

    def test_public_top_ten_population_is_not_promoted(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "history.csv"
            write_weekly_accuracy_history(path, [annual(i, y, i, 10) for y in YEARS for i in range(1, 11)])
            (root / f"inseason_accuracy_{YEARS[0]}.json").write_text(
                json.dumps({"payload": "Accuracy scores rank over 150 fantasy analysts"}), encoding="utf-8")
            with self.assertRaisesRegex(CoverageIncomplete, "public top-ten"):
                load_weekly_accuracy_history(path, YEARS, evidence_dir=root)

    def test_declared_accuracy_year_must_match_requested_completed_year(self):
        with self.assertRaisesRegex(CoverageIncomplete, "cannot replace"):
            annual_accuracy_from_directory({"accuracy_weekly_season": 2099,
                "accuracy_weekly_last_season": 2097, "experts": []}, 2098, source_url="fixture")

    def test_current_directory_cannot_stand_in_for_incomplete_annual_population(self):
        with self.assertRaisesRegex(CoverageIncomplete, "omits annual rank slots"):
            annual_accuracy_from_directory({"accuracy_weekly_season": 2098, "experts": [
                {"expert_id": 2, "name": "Expert 2", "accuracy_weekly": {"ALL": 2}}]},
                2098, source_url="fixture")

    def test_complete_correctly_declared_directory_is_usable(self):
        rows = annual_accuracy_from_directory({"accuracy_weekly_season": 2098, "experts": [
            {"expert_id": i, "name": f"Expert {i}", "accuracy_weekly": {"ALL": i}}
            for i in range(1, 4)]}, 2098, source_url="fixture")
        self.assertEqual(len(rows), 3)
        self.assertEqual({r.field_size for r in rows}, {3})


if __name__ == "__main__":
    unittest.main()
