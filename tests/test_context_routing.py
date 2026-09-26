import json
import re
import tomllib
import unittest
from pathlib import Path

from scripts.release_gate import validate_repository


ROOT = Path(__file__).parents[1]


def words(path: str) -> int:
    return len(re.findall(r"\S+", (ROOT / path).read_text(encoding="utf-8")))


class ContextRoutingTests(unittest.TestCase):
    def test_ac007_summary_and_detail_have_matching_status(self):
        tracker = (ROOT / "docs/ASSISTANT_RELIABILITY_TASKS.md").read_text(encoding="utf-8")
        row = next(line for line in tracker.splitlines() if line.startswith("| AC-007 |"))
        table_state = row.split("|")[3].strip().split()[0].rstrip(";:").lower()
        detail = tracker.split("## AC-007", 1)[1].split("## AC-008", 1)[0]
        self.assertEqual(table_state, re.search(r"Status:\s*(\w+)", detail).group(1).lower())

    def test_ac006_summary_and_detail_have_matching_status(self):
        tracker = (ROOT / "docs/ASSISTANT_RELIABILITY_TASKS.md").read_text(encoding="utf-8")
        row = next(line for line in tracker.splitlines() if line.startswith("| AC-006 |"))
        table_state = row.split("|")[3].strip().split()[0].rstrip(";:").lower()
        detail = tracker.split("## AC-006", 1)[1].split("## AC-007", 1)[0]
        detail_state = re.search(r"Status:\s*(\w+)", detail).group(1).lower()
        self.assertEqual(table_state, detail_state)

    def test_ac005_merged_status_is_consistent_across_tracking_records(self):
        tracker = (ROOT / "docs/ASSISTANT_RELIABILITY_TASKS.md").read_text(encoding="utf-8")
        table_row = next(line for line in tracker.splitlines() if line.startswith("| AC-005 |"))
        self.assertIn("Merged in [PR #19]", table_row)
        detail = tracker.split("## AC-005", 1)[1].split("## AC-006", 1)[0]
        self.assertIn("Status: merged in [PR #19]", detail)
        self.assertIn("issue #11 is closed", detail)
        for path in (".codex/context/status/WAIVER.md", ".codex/context/ACTIVE_MILESTONE.md",
                     "docs/COMPLETED_ASSISTANT_RELIABILITY_AC_005.md"):
            text = (ROOT / path).read_text(encoding="utf-8")
            self.assertNotRegex(text, r"PR #19[^\n]*awaits review/merge")
        completed = (ROOT / "docs/COMPLETED_ASSISTANT_RELIABILITY_AC_005.md").read_text(encoding="utf-8")
        self.assertIn("7bf808cf0315369ee11f1eca9ce276f46dd91bdd", completed)

    def test_always_loaded_context_stays_bounded(self):
        self.assertLessEqual(words("AGENTS.md"), 300)
        self.assertLessEqual(words(".codex/context/STEERING.md"), 400)
        self.assertLessEqual(words(".codex/context/DEVELOPMENT_STATUS.md"), 150)
        self.assertLessEqual(words(".codex/context/IMPLEMENTATION_POLICY.md"), 350)

    def test_startup_loads_only_the_router(self):
        agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("At the start of a task, read only `.codex/context/STEERING.md`", agents)
        self.assertRegex(
            agents, r"Do\s+not read `.codex/context/DEVELOPMENT_STATUS\.md`"
        )
        self.assertIn(".codex/context/IMPLEMENTATION_POLICY.md", agents)

    def test_router_targets_exist_and_track_status_stays_conditional(self):
        router = (ROOT / ".codex/context/STEERING.md").read_text(encoding="utf-8")
        for path in (
            ".codex/context/status/DRAFT.md",
            ".codex/context/status/TRADE.md",
            ".codex/context/status/WAIVER.md",
            ".codex/context/IMPLEMENTATION_POLICY.md",
            "docs/OPEN_SOURCE_RELEASE_TASKS.md",
        ):
            self.assertIn(path, router)
            self.assertTrue((ROOT / path).is_file())
        for name in ("DRAFT", "TRADE", "WAIVER"):
            self.assertLessEqual(words(f".codex/context/status/{name}.md"), 250)

    def test_project_wide_next_task_routes_to_release_backlog(self):
        router = (ROOT / ".codex/context/STEERING.md").read_text(encoding="utf-8")
        status = (ROOT / ".codex/context/DEVELOPMENT_STATUS.md").read_text(encoding="utf-8")
        self.assertIn("what's next?", router)
        self.assertIn("docs/OPEN_SOURCE_RELEASE_TASKS.md", status)
        self.assertIn("OS-001", status)

    def test_context_gate_is_fast_local_and_ci_visible(self):
        workflow = (ROOT / ".github/workflows/release-gates.yml").read_text(
            encoding="utf-8"
        )
        contributing = (ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
        command = "python -m unittest tests.test_context_routing"
        self.assertIn(command, workflow)
        self.assertIn(command, contributing)

    def test_draft_handoff_closes_2026_and_requires_new_future_milestone(self):
        status = (ROOT / ".codex/context/status/DRAFT.md").read_text(encoding="utf-8")
        tasks = (ROOT / "docs/OPEN_TASKS.md").read_text(encoding="utf-8")
        self.assertIn("2026 drafts are complete", status)
        self.assertIn("no Draft tasks remain open", tasks)
        self.assertIn("BD-905 completed with a failed validation", tasks)
        self.assertNotIn("### BD-906", tasks)
        self.assertNotIn("### BD-907", tasks)
        self.assertIn("a newly scoped task", status)

    def test_public_surface_excludes_completed_league_experiments(self):
        cli = (ROOT / "src/roster_theory/cli.py").read_text(encoding="utf-8")
        for command in (
            "league_beta-rollout-validation",
            "league_beta-dst-counterfactual",
            "positional-guardrail-comparison",
            "provisional-ten-team-comparison",
            "locked-ten-team-comparison",
        ):
            self.assertNotIn(command, cli)

    def test_public_league_config_is_synthetic_and_local_config_is_ignored(self):
        example = json.loads(
            (ROOT / "config/leagues.example.json").read_text(encoding="utf-8")
        )
        self.assertEqual(example["leagues"][0]["key"], "home_league")
        self.assertNotIn("league_beta", repr(example).lower())
        ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("config/leagues.json", ignore)

    def test_unlicense_is_referenced_by_readme_and_package_metadata(self):
        license_text = (ROOT / "LICENSE").read_text(encoding="utf-8")
        metadata_text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        metadata = tomllib.loads(metadata_text)
        readme = (ROOT / "README.md").read_text(encoding="utf-8")

        self.assertTrue(
            license_text.startswith(
                "This is free and unencumbered software released into the public domain.\n"
            )
        )
        self.assertIn("THE SOFTWARE IS PROVIDED \"AS IS\"", license_text)
        self.assertEqual(metadata["project"]["license"], "Unlicense")
        self.assertIn("LICENSE", metadata["project"]["license-files"])
        self.assertEqual(metadata["project"]["readme"], "README.md")
        self.assertIn("[the Unlicense](LICENSE)", readme)

    def test_public_boundary_uses_only_synthetic_manager_identifiers(self):
        self.assertEqual(validate_repository(ROOT), [])

    def test_third_party_inventory_covers_every_public_data_file(self):
        notice = (ROOT / "docs/THIRD_PARTY_NOTICES.md").read_text(
            encoding="utf-8"
        )
        private_config_patterns = (
            "leagues.json",
            "*_rollout_counterfactuals_*.json",
            "inseason_identity_overrides_*.csv",
            "waiver/*.decision-policy.json",
            "waiver/*.walk-forward.json",
            "waiver/*.ww-evidence.json",
        )
        config_files = [
            path
            for path in (ROOT / "config").rglob("*")
            if path.suffix in {".csv", ".json"}
            and not any(
                path.relative_to(ROOT / "config").match(pattern)
                for pattern in private_config_patterns
            )
        ]
        example_files = [
            path
            for path in (ROOT / "examples").rglob("*")
            if path.suffix in {".csv", ".json"}
        ]

        for path in config_files + example_files:
            relative = path.relative_to(ROOT).as_posix()
            self.assertIn(f"`{relative}`", notice)

    def test_provider_data_defaults_are_local_and_ignored(self):
        source = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (ROOT / "src").rglob("*.py")
        )
        self.assertNotIn("config/expert_accuracy_", source)
        self.assertNotIn("config/expert_pool_", source)
        self.assertNotIn("config/trade/inseason_", source)
        self.assertNotIn("config/trade/nfl_", source)
        self.assertIn("data/manual/fantasypros/", source)
        self.assertIn("data/manual/nfl/", source)

    def test_waiver_input_script_has_one_generic_surface(self):
        self.assertTrue((ROOT / "scripts/waiver_live_inputs.py").is_file())
        self.assertFalse((ROOT / "scripts/wa006_live_inputs.py").exists())

    def test_full_suite_policy_uses_compact_output(self):
        policy = (ROOT / ".codex/context/IMPLEMENTATION_POLICY.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("python -m unittest discover -s tests", policy)
        self.assertNotIn("python -m unittest discover -s tests -v", policy)


if __name__ == "__main__":
    unittest.main()
