import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from roster_theory.core.errors import CoverageIncomplete
from roster_theory.core.models import Player
from roster_theory.providers.fantasypros import normalize_rankings
from roster_theory.waiver.ww_evidence import (
    WaiverWireConfig,
    build_waiver_wire_evidence,
    load_waiver_wire_evidence,
    load_waiver_wire_config,
    refresh_waiver_wire_evidence,
)


NOW = datetime(2026, 9, 14, 12, tzinfo=timezone.utc)


def config(*, experts=("17",), maximum_age_hours=24.0):
    return WaiverWireConfig(
        league_key="league_alpha",
        scoring="PPR",
        position="ALL",
        maximum_age_hours=maximum_age_hours,
        trusted_expert_ids=tuple(experts),
        config_hash="config-hash",
    )


def dataset(*, expert_id=None, player_id="10", captured_at=NOW, updated_at=None):
    return normalize_rankings(
        {
            "year": "2026",
            "week": "2",
            "scoring": "PPR",
            "ranking_type_name": "Waiver Wire",
            "last_updated": (updated_at or captured_at.isoformat()),
            "expert_names": {"17": "Trusted", "29": "Other"},
            "players": [
                {
                    "player_id": player_id,
                    "player_name": "Runner",
                    "player_position_id": "RB",
                    "player_yahoo_id": "y10",
                    "rank_ecr": 3 if expert_id is None else 1,
                    "pos_rank": "RB2" if expert_id is None else "RB1",
                    "rank_min": 1,
                    "rank_max": 8,
                    "rank_std": 2.25,
                    "experts": {"17": "1", "29": "4"},
                }
            ],
        },
        requested_horizon="WAIVER",
        board_source="market" if expert_id is None else "selected",
        expert_id=expert_id,
        captured_at=captured_at,
    )


class WaiverWireEvidenceTests(unittest.TestCase):
    def test_config_is_waiver_and_league_scoped(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "product": "WAIVER ASSISTANT",
                        "league_key": "league_alpha",
                        "scoring": "PPR",
                        "position": "ALL",
                        "maximum_age_hours": 24,
                        "trusted_expert_ids": ["17"],
                    }
                ),
                encoding="utf-8",
            )
            loaded = load_waiver_wire_config(path, league_key="league_alpha")
            self.assertEqual(loaded.trusted_expert_ids, ("17",))
            with self.assertRaisesRegex(ValueError, "not league_beta"):
                load_waiver_wire_config(path, league_key="league_beta")

    def test_market_and_selected_expert_evidence_remain_distinct(self):
        evidence = build_waiver_wire_evidence(
            config=config(),
            players=(Player("s1", "Runner", ("RB",), fantasypros_id="10"),),
            market=dataset(),
            selected={"17": dataset(expert_id="17")},
            now=NOW + timedelta(hours=1),
        )
        self.assertTrue(evidence.complete)
        self.assertEqual(evidence.raw_market_horizon, "Waiver Wire")
        self.assertEqual(evidence.contributor_ids, ("17", "29"))
        player = evidence.players[0]
        self.assertEqual(player.player_id, "s1")
        self.assertEqual(player.market_overall_rank, 3.0)
        self.assertEqual(player.market_rank_std, 2.25)
        self.assertEqual(player.selected_expert_ranks[0].expert_id, "17")
        self.assertEqual(player.selected_expert_ranks[0].overall_rank, 1.0)
        self.assertTrue(evidence.evidence_hash)

    def test_unmatched_stale_and_missing_expert_evidence_fails_closed(self):
        evidence = build_waiver_wire_evidence(
            config=config(maximum_age_hours=12),
            players=(),
            market=dataset(captured_at=NOW, updated_at=NOW.isoformat()),
            selected={},
            now=NOW + timedelta(hours=13),
        )
        self.assertFalse(evidence.complete)
        self.assertFalse(evidence.market_complete)
        self.assertFalse(evidence.selected_experts_complete)
        self.assertEqual(evidence.unmatched_fantasypros_ids, ("10",))
        self.assertEqual(evidence.missing_trusted_expert_ids, ("17",))
        self.assertTrue(any("stale" in warning.lower() for warning in evidence.warnings))

    def test_shared_external_id_resolves_without_direct_fantasypros_id(self):
        evidence = build_waiver_wire_evidence(
            config=config(experts=()),
            players=(
                Player(
                    "s1",
                    "Runner",
                    ("RB",),
                    external_ids=(("yahoo", "y10"),),
                ),
            ),
            market=dataset(),
            selected={},
            now=NOW,
        )
        self.assertEqual(evidence.players[0].player_id, "s1")
        self.assertEqual(evidence.players[0].match_status, "MATCHED")
        self.assertEqual(evidence.unmatched_fantasypros_ids, ())

    def test_unconfigured_selected_dataset_is_rejected(self):
        with self.assertRaisesRegex(CoverageIncomplete, "Unconfigured"):
            build_waiver_wire_evidence(
                config=config(experts=()),
                players=(Player("s1", "Runner", ("RB",), fantasypros_id="10"),),
                market=dataset(),
                selected={"17": dataset(expert_id="17")},
                now=NOW,
            )

    def test_duplicate_identity_is_ambiguous_and_fails_closed(self):
        with self.assertRaisesRegex(CoverageIncomplete, "multiple players"):
            build_waiver_wire_evidence(
                config=config(experts=()),
                players=(
                    Player("s1", "Runner", ("RB",), fantasypros_id="10"),
                    Player("s2", "Other Runner", ("RB",), fantasypros_id="10"),
                ),
                market=dataset(),
                selected={},
                now=NOW,
            )

    def test_refresh_obeys_budget_cache_and_selected_expert_parameters(self):
        calls = []

        class Client:
            def consensus_rankings(self, _season, **params):
                calls.append(dict(params))
                return {
                    "year": "2026",
                    "week": str(params["week"]),
                    "scoring": params["scoring"],
                    "ranking_type_name": "WW",
                    "last_updated": NOW.isoformat(),
                    "expert_names": {"17": "Trusted"},
                    "players": [
                        {
                            "player_id": "10",
                            "player_name": "Runner",
                            "player_position_id": "RB",
                            "rank_ecr": 1,
                            "pos_rank": "RB1",
                        }
                    ],
                }

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            kwargs = {
                "config": config(),
                "season": 2026,
                "week": 2,
                "players": (Player("s1", "Runner", ("RB",), fantasypros_id="10"),),
                "client": Client(),
                "cache_dir": root / "cache",
                "budget_path": root / "budget.json",
                "output_path": root / "evidence.json",
                "now": NOW + timedelta(hours=1),
                "minimum_interval": 0,
            }
            first = refresh_waiver_wire_evidence(**kwargs)
            second = refresh_waiver_wire_evidence(**kwargs)
            self.assertEqual(len(calls), 2)
            self.assertEqual(first.call_plan.fantasypros_calls, 2)
            self.assertEqual(second.call_plan.fantasypros_calls, 0)
            self.assertEqual(second.call_plan.cache_hits, 2)
            self.assertEqual(calls[0]["experts"], "show")
            self.assertEqual(calls[1]["filters"], "17:17")
            self.assertTrue(first.evidence.complete)
            budget = json.loads((root / "budget.json").read_text(encoding="utf-8"))
            self.assertEqual(budget["used"], 2)
            replay = load_waiver_wire_evidence(root / "evidence.json")
            self.assertEqual(replay, second.evidence)
            tampered = json.loads((root / "evidence.json").read_text(encoding="utf-8"))
            tampered["players"][0]["market_overall_rank"] = 99
            (root / "evidence.json").write_text(json.dumps(tampered), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "hash verification"):
                load_waiver_wire_evidence(root / "evidence.json")


if __name__ == "__main__":
    unittest.main()
