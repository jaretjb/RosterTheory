import json
import unittest
from pathlib import Path


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "runtime_inputs"
REQUIRED_TOP_LEVEL = {
    "schema_version",
    "operation",
    "status",
    "league",
    "season",
    "assistant",
    "mode",
    "dry_run",
    "artifacts",
    "provider_calls",
    "writes",
    "summary",
    "errors",
    "sleeper_write_performed",
}
REQUIRED_ARTIFACT_FIELDS = {
    "id",
    "authority",
    "scope",
    "horizon",
    "status",
    "freshness_rule",
    "path",
    "source",
    "captured_at",
    "content_hash",
    "action",
    "reason",
}


def load_fixture(league: str) -> dict:
    return json.loads((FIXTURE_DIR / f"{league}.contract.json").read_text(encoding="utf-8"))


class RuntimeInputContractTests(unittest.TestCase):
    def test_two_synthetic_leagues_follow_v1_shape_and_never_write_sleeper(self):
        for league in ("league_alpha", "league_beta"):
            value = load_fixture(league)
            self.assertEqual(set(value), REQUIRED_TOP_LEVEL)
            self.assertEqual(value["schema_version"], "roster-theory.inputs/v1")
            self.assertEqual(value["league"], league)
            self.assertEqual(value["season"], 2099)
            self.assertFalse(value["sleeper_write_performed"])
            for artifact in value["artifacts"]:
                self.assertEqual(set(artifact), REQUIRED_ARTIFACT_FIELDS)

    def test_only_raw_provider_evidence_is_shared_between_leagues(self):
        alpha = load_fixture("league_alpha")
        beta = load_fixture("league_beta")
        by_league = {alpha["league"]: alpha, beta["league"]: beta}

        shared_paths = {}
        for league, contract in by_league.items():
            other = "league_beta" if league == "league_alpha" else "league_alpha"
            for artifact in contract["artifacts"]:
                if artifact["scope"] == "shared":
                    self.assertEqual(artifact["authority"], "provider_fact")
                    shared_paths.setdefault(artifact["id"], set()).add(artifact["path"])
                else:
                    self.assertEqual(artifact["scope"], "league")
                    self.assertIn(league, artifact["path"])
                    self.assertNotIn(other, artifact["path"])

        self.assertTrue(shared_paths)
        self.assertTrue(all(len(paths) == 1 for paths in shared_paths.values()))

    def test_league_scoped_hashes_cannot_transfer(self):
        alpha = load_fixture("league_alpha")
        beta = load_fixture("league_beta")
        alpha_hashes = {
            row["content_hash"] for row in alpha["artifacts"] if row["scope"] == "league"
        }
        beta_hashes = {
            row["content_hash"] for row in beta["artifacts"] if row["scope"] == "league"
        }
        self.assertTrue(alpha_hashes.isdisjoint(beta_hashes))


if __name__ == "__main__":
    unittest.main()
