"""Shared preparation boundaries and cross-process provider coordination."""

from __future__ import annotations

import ast
import json
import multiprocessing
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.error import URLError

from roster_theory.core.errors import RequestBudgetExceeded
from roster_theory.fantasypros import FantasyProsClient
from roster_theory.storage.request_gate import pace_request, reserve_requests
from roster_theory.waiver_inputs import _waiver_value_refresh, build_waiver_inputs


def _reserve_worker(path: str, results: object) -> None:
    try:
        reserve_requests(Path(path), 1)
        results.put("reserved")
    except RequestBudgetExceeded:
        results.put("exceeded")


def _pace_worker(path: str, results: object) -> None:
    pace_request(Path(path), minimum_spacing_seconds=0.5)
    results.put(datetime.now(timezone.utc).timestamp())


class SharedValuePreparationTests(unittest.TestCase):
    def test_waiver_passes_its_snapshot_into_shared_preparation(self):
        source = SimpleNamespace(
            league=SimpleNamespace(scoring=(("rec", 0.5),)),
        )
        refresh = SimpleNamespace(snapshot=source)
        with (
            patch("roster_theory.waiver_inputs.resolve_league_policy_path", return_value="fixture"),
            patch("roster_theory.waiver_inputs.load_waiver_policy"),
            patch("roster_theory.waiver_inputs.refresh_waiver_snapshot", return_value=refresh),
            patch("roster_theory.waiver_inputs.load_waiver_wire_config",
                  return_value=SimpleNamespace(scoring="HALF")),
            patch("roster_theory.waiver_inputs.ranking_format",
                  return_value=SimpleNamespace(scoring="HALF")),
            patch("roster_theory.waiver_inputs.refresh_value_boards",
                  side_effect=RuntimeError("captured")) as shared,
            patch("roster_theory.waiver_inputs._waiver_value_refresh",
                  return_value="prepared") as adapt,
        ):
            with self.assertRaisesRegex(RuntimeError, "captured"):
                build_waiver_inputs("fixture")
            self.assertEqual(shared.call_args.kwargs["refresh_snapshot"]("fixture"), "prepared")
            self.assertIs(adapt.call_args.args[0], refresh)
        self.assertEqual(shared.call_args.kwargs["output_root"], "data/exports/waiver")
        self.assertEqual(shared.call_args.kwargs["snapshot_filename"], "value_snapshot.json")

    def test_waiver_adapts_its_own_snapshot_without_trade_workflow(self):
        active = SimpleNamespace(player_id="rb1", positions=("RB",), active=True, nfl_team="SEA")
        rostered = SimpleNamespace(player_id="wr1", positions=("WR",), active=False, nfl_team="SEA")
        defense = SimpleNamespace(player_id="sea", positions=("DST",), active=True, nfl_team="SEA")
        source = SimpleNamespace(
            league_key="fixture",
            captured_at=datetime(2026, 9, 27, tzinfo=timezone.utc),
            league=SimpleNamespace(season=2026, championship_week=17),
            manifest=SimpleNamespace(current_week=4),
            owner_by_player=(("wr1", "1"),),
            players=(active, rostered, defense),
        )
        refresh = SimpleNamespace(snapshot=source, call_plan=object(), output_path=Path("waiver.json"))
        schedule = SimpleNamespace(
            season=2026, weeks=tuple(range(1, 19)), teams=("SEA",),
            captured_at="2026-09-27T00:00:00+00:00", verified_at="",
        )
        with patch("roster_theory.waiver_inputs.load_schedule", return_value=schedule):
            prepared = _waiver_value_refresh(refresh, include_special_teams=True)
        self.assertIs(prepared.call_plan, refresh.call_plan)
        self.assertIs(prepared.snapshot.manifest, source.manifest)
        self.assertEqual(prepared.snapshot.valuation_player_ids, ("rb1", "wr1"))
        self.assertEqual(tuple(player.player_id for player in prepared.snapshot.players),
                         ("rb1", "sea", "wr1"))
        self.assertEqual((prepared.snapshot.weeks[0].week, prepared.snapshot.weeks[-1].week),
                         (4, 17))

    def test_waiver_and_shared_modules_do_not_import_trade(self):
        root = Path(__file__).resolve().parents[1] / "src" / "roster_theory"
        paths = [root / "waiver_inputs.py", *sorted((root / "waiver").glob("*.py")),
                 *sorted((root / "application").glob("*.py")),
                 *sorted((root / "inseason").glob("*.py"))]
        for path in paths:
            with self.subTest(path=path.name):
                tree = ast.parse(path.read_text(encoding="utf-8"))
                modules = [node.module or "" for node in ast.walk(tree)
                           if isinstance(node, ast.ImportFrom)]
                modules.extend(alias.name for node in ast.walk(tree)
                               if isinstance(node, ast.Import) for alias in node.names)
                self.assertFalse(any(name.startswith("roster_theory.trade") for name in modules))
                if path.parent.name == "inseason":
                    self.assertFalse(any(name.startswith((
                        "roster_theory.providers", "roster_theory.storage",
                        "roster_theory.application",
                    )) for name in modules))
        for path in sorted((root / "trade").glob("*.py")):
            with self.subTest(path=path.name):
                tree = ast.parse(path.read_text(encoding="utf-8"))
                modules = [node.module or "" for node in ast.walk(tree)
                           if isinstance(node, ast.ImportFrom)]
                modules.extend(alias.name for node in ast.walk(tree)
                               if isinstance(node, ast.Import) for alias in node.names)
                self.assertFalse(any(name.startswith("roster_theory.waiver") for name in modules))

    def test_two_processes_cannot_reserve_last_request_twice(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "budget.json"
            path.write_text(json.dumps({"limit": 1, "used": 0,
                                        "budget_date": datetime.now(timezone.utc).date().isoformat()}),
                            encoding="utf-8")
            context = multiprocessing.get_context("spawn")
            results = context.Queue()
            workers = [context.Process(target=_reserve_worker, args=(str(path), results))
                       for _ in range(2)]
            for worker in workers:
                worker.start()
            for worker in workers:
                worker.join(timeout=15)
                self.assertEqual(worker.exitcode, 0)
            self.assertEqual(sorted(results.get(timeout=2) for _ in workers),
                             ["exceeded", "reserved"])
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["used"], 1)

    def test_processes_share_request_spacing(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "budget.json"
            context = multiprocessing.get_context("spawn")
            results = context.Queue()
            workers = [context.Process(target=_pace_worker, args=(str(path), results))
                       for _ in range(2)]
            for worker in workers:
                worker.start()
            for worker in workers:
                worker.join(timeout=15)
                self.assertEqual(worker.exitcode, 0)
            times = sorted(results.get(timeout=2) for _ in workers)
            self.assertGreaterEqual(times[1] - times[0], 0.4)

    def test_retry_requires_an_additional_budget_reservation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "budget.json"
            path.write_text(json.dumps({"limit": 1, "used": 0,
                                        "budget_date": datetime.now(timezone.utc).date().isoformat()}),
                            encoding="utf-8")
            reserve_requests(path, 1)
            client = FantasyProsClient(
                api_key="synthetic-test-key", retries=1,
                before_retry=lambda: reserve_requests(path, 1),
            )
            with patch("roster_theory.fantasypros.urlopen", side_effect=URLError("offline")) as fetch:
                with patch("roster_theory.fantasypros.time.sleep"):
                    with self.assertRaises(RequestBudgetExceeded):
                        client.get("nfl/news")
            self.assertEqual(fetch.call_count, 1)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["used"], 1)


if __name__ == "__main__":
    unittest.main()
