from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from roster_theory.core.errors import (
    CoverageIncomplete,
    IdentityIncomplete,
    ProviderCapabilityMissing,
    StaleData,
)
from roster_theory.core.models import LeagueRules
from roster_theory.stats_guy_fantasy import (
    StatsGuyFantasyClient,
    StatsGuyFantasyError,
)
from roster_theory.trade.market import (
    STATS_GUY_ATTRIBUTION,
    ecr_proxy,
    load_trade_market_board,
    normalize_authorized_import,
    normalize_stats_guy_players,
    resolve_trade_market_evidence,
    save_trade_market_board,
    trade_market_format,
)


NOW = datetime(2026, 9, 20, 18, tzinfo=timezone.utc)


def league(*roster_positions: str) -> LeagueRules:
    return LeagueRules(
        league_id="league-1",
        season=2026,
        team_count=10,
        roster_positions=roster_positions or ("QB", "RB", "WR", "TE", "BN"),
        scoring=(("rec", 0.5),),
        playoff_start_week=15,
        championship_week=17,
    )


def provider_row(
    player_id: str,
    position: str,
    *,
    non_sf_value: int | None,
    sf_value: int | None,
    non_sf_rank: int = 1,
    sf_rank: int = 1,
    position_rank: int = 1,
) -> dict[str, object]:
    return {
        "id": player_id,
        "name": f"Player {player_id}",
        "team": "SEA",
        "position": position,
        "value": {
            "non_sf_redraft": non_sf_value,
            "sf_redraft": sf_value,
            "non_sf_dynasty": None,
            "sf_dynasty": None,
        },
        "rank": {
            "non_sf_redraft": non_sf_rank if non_sf_value is not None else None,
            "sf_redraft": sf_rank if sf_value is not None else None,
            "non_sf_dynasty": None,
            "sf_dynasty": None,
        },
        "positionRank": {
            "non_sf_redraft": position_rank if non_sf_value is not None else None,
            "sf_redraft": position_rank if sf_value is not None else None,
            "non_sf_dynasty": None,
            "sf_dynasty": None,
        },
        "valueChange": {
            "non_sf_redraft": {"days7": 5, "days30": -2},
            "sf_redraft": {"days7": 7, "days30": 3},
            "non_sf_dynasty": None,
            "sf_dynasty": None,
        },
    }


def provider_payload(
    *,
    as_of: datetime = NOW - timedelta(hours=6),
    first_value: int = 100,
) -> dict[str, object]:
    rows = [
        provider_row(
            "p1",
            "RB",
            non_sf_value=first_value,
            sf_value=110,
            non_sf_rank=1,
            sf_rank=2,
            position_rank=1,
        ),
        provider_row(
            "p2",
            "QB",
            non_sf_value=80,
            sf_value=150,
            non_sf_rank=2,
            sf_rank=1,
            position_rank=1,
        ),
        provider_row(
            "dynasty-only",
            "WR",
            non_sf_value=None,
            sf_value=None,
            non_sf_rank=3,
            sf_rank=3,
            position_rank=1,
        ),
    ]
    return {
        "total": len(rows),
        "valuesAsOf": {
            "non_sf_redraft": as_of.isoformat(),
            "sf_redraft": as_of.isoformat(),
            "non_sf_dynasty": None,
            "sf_dynasty": None,
        },
        "players": rows,
    }


def local_import() -> dict[str, object]:
    return {
        "provider": "Licensed Fixture",
        "authorization_basis": "User-authorized personal export",
        "source_url": "https://example.test/trade-values",
        "attribution": "Values by Licensed Fixture",
        "publication_at": (NOW - timedelta(hours=4)).isoformat(),
        "exported_at": (NOW - timedelta(hours=3)).isoformat(),
        "season": 2026,
        "week": 2,
        "format": "non_sf_redraft",
        "scoring_variant": "HALF_PPR",
        "te_premium_variant": "NO_TEP",
        "league_scoring_exact": True,
        "declared_count": 2,
        "rows": [
            {
                "player_id": "p1",
                "position": "RB",
                "overall_rank": 1,
                "position_rank": 1,
                "value": 101,
                "provider_change_7d": 4,
                "provider_change_30d": 8,
            },
            {
                "player_id": "p2",
                "position": "QB",
                "overall_rank": 2,
                "position_rank": 1,
                "value": 82,
                "provider_change_7d": -1,
                "provider_change_30d": 2,
            },
        ],
    }


class TradeMarketNormalizationTests(unittest.TestCase):
    def test_format_selection_uses_actual_league_starters(self) -> None:
        self.assertEqual(trade_market_format(league()), "non_sf_redraft")
        self.assertEqual(
            trade_market_format(league("QB", "SUPER_FLEX", "RB", "WR", "BN")),
            "sf_redraft",
        )
        self.assertEqual(
            trade_market_format(league("QB", "QB", "RB", "WR", "BN")),
            "sf_redraft",
        )

    def test_stats_guy_bulk_payload_normalizes_sleeper_ids_and_limitations(self) -> None:
        board = normalize_stats_guy_players(
            provider_payload(),
            league=league(),
            required_player_ids=("p1", "p2"),
            current_week=2,
            captured_at=NOW,
            now=NOW,
        )
        self.assertEqual(board.mode, "STATS_GUY_FANTASY_API")
        self.assertEqual(board.format, "non_sf_redraft")
        self.assertEqual(board.source_total, 3)
        self.assertEqual(board.normalized_count, 2)
        self.assertEqual([row.player_id for row in board.prices], ["p1", "p2"])
        self.assertEqual(board.prices[0].value, 100)
        self.assertEqual(board.prices[0].provider_change_7d, 5)
        self.assertEqual(board.prices[0].provider_change_30d, -2)
        self.assertFalse(board.league_scoring_exact)
        self.assertEqual(board.attribution, STATS_GUY_ATTRIBUTION)
        self.assertTrue(any("RECEPTION BLEND" in row for row in board.warnings))
        self.assertTrue(any("TEP BLEND" in row for row in board.warnings))
        self.assertTrue(board.complete)
        self.assertTrue(board.evidence_hash)
        self.assertTrue(board.stamp.fresh)

    def test_superflex_uses_independently_calculated_values(self) -> None:
        board = normalize_stats_guy_players(
            provider_payload(),
            league=league("QB", "SUPER_FLEX", "RB", "WR", "BN"),
            required_player_ids=("p1", "p2"),
            captured_at=NOW,
            now=NOW,
        )
        self.assertEqual(board.format, "sf_redraft")
        self.assertEqual([row.player_id for row in board.prices], ["p2", "p1"])
        self.assertEqual(board.prices[0].value, 150)

    def test_consecutive_snapshot_change_is_derived_without_per_player_calls(self) -> None:
        previous_as_of = NOW - timedelta(hours=24)
        previous = normalize_stats_guy_players(
            provider_payload(as_of=previous_as_of, first_value=91),
            league=league(),
            captured_at=previous_as_of + timedelta(hours=1),
            now=previous_as_of + timedelta(hours=1),
        )
        current = normalize_stats_guy_players(
            provider_payload(first_value=100),
            league=league(),
            captured_at=NOW,
            now=NOW,
            previous_board=previous,
        )
        by_id = {row.player_id: row for row in current.prices}
        self.assertEqual(by_id["p1"].previous_board_change, 9)
        self.assertEqual(by_id["p2"].previous_board_change, 0)

    def test_stale_partial_duplicate_and_missing_coverage_fail_closed(self) -> None:
        with self.assertRaises(StaleData):
            normalize_stats_guy_players(
                provider_payload(as_of=NOW - timedelta(days=3)),
                league=league(),
                now=NOW,
            )
        partial = provider_payload()
        partial["total"] = 4
        with self.assertRaises(CoverageIncomplete):
            normalize_stats_guy_players(partial, league=league(), now=NOW)
        duplicate = provider_payload()
        duplicate["players"] = [
            duplicate["players"][0],  # type: ignore[index]
            duplicate["players"][0],  # type: ignore[index]
        ]
        duplicate["total"] = 2
        with self.assertRaises(IdentityIncomplete):
            normalize_stats_guy_players(duplicate, league=league(), now=NOW)
        with self.assertRaises(CoverageIncomplete):
            normalize_stats_guy_players(
                provider_payload(),
                league=league(),
                required_player_ids=("p1", "missing"),
                now=NOW,
            )


class AuthorizedImportAndReplayTests(unittest.TestCase):
    def test_authorized_import_requires_provenance_and_matching_format(self) -> None:
        missing = local_import()
        missing["authorization_basis"] = ""
        with self.assertRaises(ProviderCapabilityMissing):
            normalize_authorized_import(missing, league=league(), now=NOW)
        wrong_format = local_import()
        wrong_format["format"] = "sf_redraft"
        with self.assertRaises(ProviderCapabilityMissing):
            normalize_authorized_import(wrong_format, league=league(), now=NOW)
        wrong_week = local_import()
        wrong_week["week"] = 1
        with self.assertRaises(StaleData):
            normalize_authorized_import(
                wrong_week,
                league=league(),
                current_week=2,
                now=NOW,
            )

    def test_minimal_authorized_provenance_exposes_unspecified_scoring_limits(self) -> None:
        value = local_import()
        value["publication_date"] = value.pop("publication_at").split("T", 1)[0]
        value.pop("source_url")
        value.pop("attribution")
        value.pop("scoring_variant")
        value.pop("te_premium_variant")
        value.pop("league_scoring_exact")
        board = normalize_authorized_import(
            value,
            league=league(),
            now=NOW,
            maximum_age=timedelta(days=2),
        )
        self.assertEqual(board.source_url, "authorized-local-import")
        self.assertEqual(board.attribution, "Trade values by Licensed Fixture")
        self.assertEqual(board.scoring_variant, "UNSPECIFIED")
        self.assertEqual(board.te_premium_variant, "UNSPECIFIED")
        self.assertFalse(board.league_scoring_exact)

    def test_authorized_import_round_trips_with_hash_and_provenance(self) -> None:
        board = normalize_authorized_import(
            local_import(),
            league=league(),
            required_player_ids=("p1", "p2"),
            now=NOW,
        )
        self.assertEqual(board.mode, "AUTHORIZED_LOCAL_IMPORT")
        self.assertTrue(board.league_scoring_exact)
        self.assertEqual(board.authorization_basis, "User-authorized personal export")
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "trade-market.json"
            save_trade_market_board(board, path)
            loaded = load_trade_market_board(path)
        self.assertEqual(loaded, board)

    def test_replay_rejects_tampering(self) -> None:
        board = normalize_authorized_import(local_import(), league=league(), now=NOW)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "trade-market.json"
            save_trade_market_board(board, path)
            value = json.loads(path.read_text(encoding="utf-8"))
            value["prices"][0]["value"] = 999
            path.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                load_trade_market_board(path)


class TradeMarketResolutionTests(unittest.TestCase):
    def test_archived_chart_is_dated_fallback_not_current_fairness(self) -> None:
        class Source:
            def players(self):
                return provider_payload()

        class FailedSource:
            def players(self):
                raise StatsGuyFantasyError("offline")

        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / "league-a" / "2026"
            fresh = resolve_trade_market_evidence(
                league=league(), source=Source(), current_week=2,
                archive_dir=archive, now=NOW,
            )
            self.assertTrue(fresh.chart_fairness_available)
            cached = resolve_trade_market_evidence(
                league=league(), source=FailedSource(), current_week=2,
                archive_dir=archive, now=NOW + timedelta(hours=12),
            )
            self.assertEqual(cached.mode, "STATS_GUY_FANTASY_API")
            self.assertTrue(cached.chart_fairness_available)
            self.assertEqual(cached.board.stamp.cache_status, "current_archive_hit")
            prior = resolve_trade_market_evidence(
                league=league(), source=FailedSource(), current_week=3,
                archive_dir=archive, now=NOW + timedelta(days=6),
            )
            self.assertEqual(prior.mode, "PRIOR_WEEK_MARKET")
            self.assertTrue(prior.chart_price_available)
            self.assertFalse(prior.chart_change_available)
            self.assertFalse(prior.chart_fairness_available)
            self.assertFalse(prior.consolidation_premium_available)
            self.assertFalse(prior.board.stamp.fresh)
            self.assertTrue(all(
                row.provider_change_7d is None for row in prior.board.prices
            ))
            expired = resolve_trade_market_evidence(
                league=league(), source=FailedSource(), current_week=4,
                archive_dir=archive, now=NOW + timedelta(days=9),
            )
            self.assertEqual(expired.mode, "ECR-PROXY")
            incompatible = resolve_trade_market_evidence(
                league=league("QB", "SUPER_FLEX", "RB"),
                source=FailedSource(), current_week=3,
                archive_dir=archive, now=NOW + timedelta(days=6),
            )
            self.assertEqual(incompatible.mode, "ECR-PROXY")

    def test_package_coverage_can_use_one_prior_chart_for_all_assets(self) -> None:
        class PriorSource:
            def players(self):
                return provider_payload(as_of=NOW - timedelta(hours=6))

        class CurrentMissingAsset:
            def players(self):
                value = provider_payload(as_of=NOW + timedelta(days=6))
                value["players"] = [
                    row for row in value["players"] if row["id"] != "p2"
                ]
                value["total"] = len(value["players"])
                return value

        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / "league-a" / "2026"
            resolve_trade_market_evidence(
                league=league(), source=PriorSource(), current_week=2,
                archive_dir=archive, now=NOW,
            )
            result = resolve_trade_market_evidence(
                league=league(), source=CurrentMissingAsset(),
                required_player_ids=("p1", "p2"), current_week=3,
                archive_dir=archive, now=NOW + timedelta(days=6, hours=6),
            )
            self.assertEqual(result.mode, "PRIOR_WEEK_MARKET")
            self.assertEqual({row.player_id for row in result.board.prices} & {"p1", "p2"}, {"p1", "p2"})
            self.assertFalse(result.chart_fairness_available)

    def test_client_uses_one_public_bulk_get_without_credentials(self) -> None:
        urls: list[str] = []

        def transport(url: str):
            urls.append(url)
            return provider_payload()

        client = StatsGuyFantasyClient(transport=transport)
        value = client.players()
        self.assertEqual(value["total"], 3)
        self.assertEqual(client.request_count, 1)
        self.assertEqual(urls, ["https://api.statsguyfantasy.com/api/v1/players"])
        self.assertNotIn("key", urls[0].casefold())

    def test_resolver_prefers_api_and_can_cache_normalized_board(self) -> None:
        class Source:
            def players(self):
                return provider_payload()

        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "board.json"
            result = resolve_trade_market_evidence(
                league=league(),
                required_player_ids=("p1", "p2"),
                current_week=2,
                source=Source(),
                cache_path=path,
                now=NOW,
            )
            replay = load_trade_market_board(path)
        self.assertEqual(result.mode, "STATS_GUY_FANTASY_API")
        self.assertTrue(result.chart_price_available)
        self.assertTrue(result.chart_change_available)
        self.assertTrue(result.chart_fairness_available)
        self.assertEqual(replay.evidence_hash, result.board.evidence_hash)

    def test_resolver_falls_back_to_authorized_import_then_ecr_proxy(self) -> None:
        class FailedSource:
            def players(self):
                raise StatsGuyFantasyError("offline")

        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "authorized.json"
            path.write_text(json.dumps(local_import()), encoding="utf-8")
            imported = resolve_trade_market_evidence(
                league=league(),
                required_player_ids=("p1", "p2"),
                source=FailedSource(),
                authorized_import_path=path,
                now=NOW,
            )
        self.assertEqual(imported.mode, "AUTHORIZED_LOCAL_IMPORT")
        self.assertIsNotNone(imported.board)

        proxy = resolve_trade_market_evidence(
            league=league(),
            source=FailedSource(),
            now=NOW,
        )
        self.assertEqual(proxy, ecr_proxy("Stats Guy Fantasy unavailable: offline"))
        self.assertIsNone(proxy.board)
        self.assertFalse(proxy.chart_price_available)
        self.assertFalse(proxy.chart_change_available)
        self.assertFalse(proxy.chart_fairness_available)
        self.assertFalse(proxy.consolidation_premium_available)

    def test_resolver_can_require_a_real_board(self) -> None:
        with self.assertRaises(ProviderCapabilityMissing):
            resolve_trade_market_evidence(
                league=league(),
                now=NOW,
                allow_ecr_proxy=False,
            )

    def test_prior_board_format_mismatch_fails_closed(self) -> None:
        prior = normalize_stats_guy_players(
            provider_payload(as_of=NOW - timedelta(hours=24)),
            league=league("QB", "SUPER_FLEX", "RB", "WR", "BN"),
            now=NOW - timedelta(hours=23),
        )
        with self.assertRaises(CoverageIncomplete):
            normalize_stats_guy_players(
                provider_payload(),
                league=league(),
                now=NOW,
                previous_board=replace(prior, evidence_hash="not-relevant"),
            )


if __name__ == "__main__":
    unittest.main()
