from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from roster_theory.sleeper import SleeperClient, load_league_config


class _Response:
    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return b"[]"


class _CachedResponse(_Response):
    headers = {"CF-Cache-Status": "HIT", "Age": "4"}


class SleeperClientTests(unittest.TestCase):
    def test_missing_local_league_config_points_to_synthetic_example(self) -> None:
        with TemporaryDirectory() as directory:
            missing = Path(directory) / "leagues.json"
            with self.assertRaisesRegex(FileNotFoundError, "roster-theory example-config"):
                load_league_config(missing)

    def test_trade_surfaces_use_documented_get_paths(self) -> None:
        urls: list[str] = []

        def transport(url: str):
            urls.append(url)
            return {} if "/state/" in url else []

        client = SleeperClient(transport=transport)
        client.state()
        client.league_matchups("league-1", 6)
        client.league_transactions("league-1", 6)
        client.league_winners_bracket("league-1")
        client.league_losers_bracket("league-1")
        client.trending_players(limit=10)

        self.assertEqual(
            [url.split("/v1/")[1] for url in urls],
            [
                "state/nfl",
                "league/league-1/matchups/6",
                "league/league-1/transactions/6",
                "league/league-1/winners_bracket",
                "league/league-1/losers_bracket",
                "players/nfl/trending/add?lookback_hours=24&limit=10",
            ],
        )

    def test_rejects_unknown_trend_type_before_retrieval(self) -> None:
        client = SleeperClient(transport=lambda _url: [])
        with self.assertRaisesRegex(ValueError, "trend_type"):
            client.trending_players(trend_type="trade")

    @patch("roster_theory.sleeper.urlopen", return_value=_Response())
    def test_draft_picks_bypasses_shared_cache(self, mocked_urlopen) -> None:
        client = SleeperClient(retries=0)
        client.draft_picks("draft-1")

        request = mocked_urlopen.call_args.args[0]
        self.assertEqual(request.get_header("Cache-control"), "no-cache")
        self.assertEqual(request.get_header("Pragma"), "no-cache")
        self.assertIn(
            "roster_theory_fresh",
            parse_qs(urlsplit(request.full_url).query),
        )
        self.assertTrue(client.last_get_metadata["cache_busted"])

    @patch("roster_theory.sleeper.urlopen", return_value=_CachedResponse())
    def test_draft_picks_preserves_cache_diagnostics(self, mocked_urlopen) -> None:
        client = SleeperClient(retries=0)
        client.draft_picks("draft-1")

        self.assertEqual(client.last_get_metadata["cache_status"], "HIT")
        self.assertEqual(client.last_get_metadata["cache_age_seconds"], 4.0)

    @patch("roster_theory.sleeper.urlopen", return_value=_Response())
    def test_static_draft_request_keeps_normal_cache_behavior(self, mocked_urlopen) -> None:
        client = SleeperClient(retries=0)
        client._get("draft/draft-1")

        request = mocked_urlopen.call_args.args[0]
        self.assertIsNone(request.get_header("Cache-control"))
        self.assertIsNone(request.get_header("Pragma"))


if __name__ == "__main__":
    unittest.main()
