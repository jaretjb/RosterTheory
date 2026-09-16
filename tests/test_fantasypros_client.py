import json
import unittest
from unittest.mock import patch

from roster_theory.fantasypros import FantasyProsClient


class _Response:
    headers = {
        "Content-Type": "application/json",
        "X-RateLimit-Remaining": "491",
    }

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self) -> bytes:
        return json.dumps({"players": []}).encode("utf-8")


class FantasyProsClientTests(unittest.TestCase):
    @patch("roster_theory.fantasypros.urlopen", return_value=_Response())
    def test_records_safe_request_metadata_and_count(self, mocked_urlopen) -> None:
        client = FantasyProsClient(api_key="secret", retries=0)

        self.assertEqual(
            client.projections(2026, position="RB", scoring="HALF", week=1),
            {"players": []},
        )

        self.assertEqual(client.request_count, 1)
        self.assertEqual(client.last_get_metadata["path"], "nfl/2026/projections")
        self.assertEqual(
            client.last_get_metadata["parameters"],
            ["position", "scoring", "week"],
        )
        self.assertEqual(
            client.last_get_metadata["rate_limit_headers"],
            {"x-ratelimit-remaining": "491"},
        )
        request = mocked_urlopen.call_args.args[0]
        self.assertEqual(request.get_method(), "GET")
        self.assertNotIn("secret", request.full_url)


if __name__ == "__main__":
    unittest.main()
