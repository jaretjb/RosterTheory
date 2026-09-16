import csv
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from roster_theory.draft_preferences import (
    DraftPreferenceBook,
    evaluate_draft_preferences,
    load_draft_preferences,
)
from roster_theory.simulation import Player


FIELDS = (
    "player_name",
    "position",
    "stance",
    "category",
    "take_at_or_after",
    "condition",
    "linked_player",
    "source",
    "league_scope",
)


class DraftPreferenceTests(unittest.TestCase):
    @staticmethod
    def board() -> list[dict]:
        return [
            {
                "player_key": "target-a",
                "player_name": "Target A",
                "position": "RB",
                "projected_points": 200,
                "adp": 20,
                "vbd": 50,
                "rank_score": 10,
            },
            {
                "player_key": "target-b",
                "player_name": "Target B",
                "position": "WR",
                "projected_points": 190,
                "adp": 40,
                "vbd": 40,
                "rank_score": 20,
            },
            {
                "player_key": "tucker",
                "player_name": "Tucker Kraft",
                "position": "TE",
                "projected_points": 180,
                "adp": 65,
                "vbd": 30,
                "rank_score": 30,
            },
            {
                "player_key": "burrow",
                "player_name": "Joe Burrow",
                "position": "QB",
                "projected_points": 280,
                "adp": 53,
                "vbd": 20,
                "rank_score": 25,
            },
        ]

    @staticmethod
    def rows() -> list[dict]:
        return [
            {
                "player_name": "Target A",
                "position": "RB",
                "stance": "target",
                "category": "upside",
                "take_at_or_after": "",
                "condition": "",
                "linked_player": "",
                "source": "user",
                "league_scope": "league_alpha|league_beta",
            },
            {
                "player_name": "Target B",
                "position": "WR",
                "stance": "target",
                "category": "upside",
                "take_at_or_after": "",
                "condition": "",
                "linked_player": "",
                "source": "user",
                "league_scope": "league_alpha",
            },
            {
                "player_name": "Tucker Kraft",
                "position": "TE",
                "stance": "target",
                "category": "price_conditional",
                "take_at_or_after": "85",
                "condition": "",
                "linked_player": "",
                "source": "koerner",
                "league_scope": "league_alpha",
            },
            {
                "player_name": "Tucker Kraft",
                "position": "TE",
                "stance": "caution",
                "category": "fade_at_te5_cost",
                "take_at_or_after": "",
                "condition": "",
                "linked_player": "",
                "source": "koerner",
                "league_scope": "league_alpha",
            },
            {
                "player_name": "Joe Burrow",
                "position": "QB",
                "stance": "target",
                "category": "conditional_qb",
                "take_at_or_after": "",
                "condition": "six_point_passing_td_preferred",
                "linked_player": "",
                "source": "koerner",
                "league_scope": "league_alpha",
            },
        ]

    def write_preferences(self, directory: str, rows: list[dict]) -> Path:
        path = Path(directory) / "preferences.csv"
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows(rows)
        return path

    def test_loader_filters_scope_matches_board_and_preserves_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_preferences(directory, self.rows())
            fourth = load_draft_preferences(path, self.board(), "league_alpha")
            league_beta = load_draft_preferences(path, self.board(), "league_beta")

        self.assertEqual(len(fourth.entries), 5)
        self.assertEqual([entry.player_name for entry in league_beta.entries], ["Target A"])
        self.assertEqual(len(fourth.sha256), 64)
        self.assertEqual(
            fourth.evidence_metadata()["entries"][2]["take_at_or_after"], 85
        )

    def test_loader_rejects_unmatched_and_duplicate_preferences(self) -> None:
        rows = self.rows()
        rows.append(dict(rows[0]))
        rows.append(
            {
                **rows[0],
                "player_name": "Missing Player",
                "position": "QB",
            }
        )
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_preferences(directory, rows)
            with self.assertRaisesRegex(ValueError, "duplicate target.*unmatched player"):
                load_draft_preferences(path, self.board(), "league_alpha")

    def test_overlay_uses_both_survival_models_price_floor_and_scoring_condition(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            book = load_draft_preferences(
                self.write_preferences(directory, self.rows()),
                self.board(),
                "league_alpha",
            )
        raw = {row["player_key"]: Player.from_mapping(row) for row in self.board()}
        adjusted = {
            key: replace(
                player,
                acquisition_adp=player.adp + 5,
                acquisition_position_slot=5 if key == "tucker" else 1,
            )
            for key, player in raw.items()
        }
        overlay = evaluate_draft_preferences(
            book,
            raw,
            adjusted,
            set(raw),
            {"target-a": 0.40, "target-b": 0.40, "tucker": 0.10, "burrow": 0.10},
            {"target-a": 0.30, "target-b": 0.70, "tucker": 0.10, "burrow": 0.10},
            70,
            {"primary": [{"player_key": "tucker"}]},
            scoring_settings={"pass_td": 4},
        )

        self.assertEqual(
            [row["call"] for row in overlay["display_targets"]],
            ["NOW", "SPLIT", "WAIT"],
        )
        self.assertEqual(overlay["display_targets"][2]["note"], "after 85")
        self.assertEqual(overlay["inactive_targets"][0]["player_name"], "Joe Burrow")
        self.assertEqual(overlay["cautions"][0]["reason"], "before pick 85")
        self.assertFalse(overlay["recommendations_changed"])

        after_floor = evaluate_draft_preferences(
            book,
            raw,
            adjusted,
            set(raw),
            {key: 0.10 for key in raw},
            {key: 0.10 for key in raw},
            85,
            {"primary": [{"player_key": "tucker"}]},
            scoring_settings={"pass_td": 6},
        )
        tucker = next(
            row for row in after_floor["targets"] if row["player_name"] == "Tucker Kraft"
        )
        self.assertEqual(tucker["call"], "NOW")
        self.assertFalse(after_floor["cautions"])
        self.assertFalse(after_floor["inactive_targets"])

        roster_filtered = evaluate_draft_preferences(
            book,
            raw,
            adjusted,
            set(raw),
            {key: 0.10 for key in raw},
            {key: 0.10 for key in raw},
            85,
            {"primary": []},
            candidate_rows={"target-a": {"roster_need": "bench_depth"}},
            scoring_settings={"pass_td": 6},
        )
        self.assertEqual(
            [row["player_name"] for row in roster_filtered["display_targets"]],
            ["Target A"],
        )
        self.assertTrue(
            any(
                row["reason"] == "not eligible under current roster construction"
                for row in roster_filtered["inactive_targets"]
            )
        )

        last_skill_pick = evaluate_draft_preferences(
            book,
            raw,
            adjusted,
            set(raw),
            {key: 0.90 for key in raw},
            {key: 0.85 for key in raw},
            124,
            {"primary": []},
            candidate_rows={"target-a": {"roster_need": "bench_depth"}},
            scoring_settings={"pass_td": 4},
            last_skill_pick=True,
        )
        target = last_skill_pick["display_targets"][0]
        self.assertEqual(target["player_name"], "Target A")
        self.assertEqual(target["call"], "NOW")
        self.assertEqual(target["note"], "last skill pick")

    def test_unavailable_caution_remains_active_after_market_price(self) -> None:
        rows = self.rows()
        rows.append(
            {
                "player_name": "Target A",
                "position": "RB",
                "stance": "caution",
                "category": "unavailable",
                "take_at_or_after": "",
                "condition": "",
                "linked_player": "",
                "source": "official_news",
                "league_scope": "league_alpha",
            }
        )
        with tempfile.TemporaryDirectory() as directory:
            book = load_draft_preferences(
                self.write_preferences(directory, rows),
                self.board(),
                "league_alpha",
            )
        raw = {row["player_key"]: Player.from_mapping(row) for row in self.board()}
        overlay = evaluate_draft_preferences(
            book,
            raw,
            raw,
            set(raw),
            {key: 0.10 for key in raw},
            {key: 0.10 for key in raw},
            120,
            {"primary": [{"player_key": "target-a"}]},
        )

        self.assertEqual(overlay["cautions"][0]["reason"], "currently unavailable")
        self.assertFalse(overlay["recommendations_changed"])


if __name__ == "__main__":
    unittest.main()
