"""A roster's observed overage has different consequences for different actions."""
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

from roster_theory.core.errors import CoverageIncomplete, RosterIllegal
from roster_theory.providers.sleeper import SleeperAdapter, SleeperBundle
from roster_theory.trade.evaluation import build_entered_package, evaluate_trade
from roster_theory.trade.snapshot import assert_current as trade_current, build_trade_snapshot
from roster_theory.waiver.evaluation import evaluate_waiver
from roster_theory.waiver.plans import hypothetical_claim
from roster_theory.waiver.snapshot import build_waiver_snapshot

from tests.test_trade_evaluation import board_fixture, projection_fixture, snapshot_fixture
from tests.test_trade_snapshot import FakeSleeperClient, schedule_fixture
from tests.test_waiver_evaluation import NOW, legality, projections, values, waiver_snapshot, weeks
from tests.test_waiver_search import complete_search_snapshot, search


def overfull_waiver_snapshot(*, user_overfull: bool):
    base = waiver_snapshot()
    teams = list(base.teams)
    index = 0 if user_overfull else 1
    extra_ids = ("fa_rb",) if user_overfull else ("fa_rb", "fa_wr", "add", "qb_extra")
    extra_players = () if user_overfull else (
        replace(next(player for player in base.players if player.player_id == "qb"),
                player_id="qb_extra", name="Opponent Extra"),
    )
    teams[index] = replace(teams[index], player_ids=(*teams[index].player_ids, *extra_ids))
    bundle = SleeperBundle(
        captured_at=base.captured_at,
        state=base.nfl_state,
        league=base.league,
        teams=tuple(teams),
        players=(*base.players, *extra_players),
        matchups=(),
        transactions=(),
        winner_bracket_rounds=None,
        loser_bracket_rows=0,
        stamps=base.stamps,
        player_directory_cache_status="fixture",
    )
    return build_waiver_snapshot(
        league_key=base.league_key, user_id="u1", sleeper=bundle,
        expected_user_roster_id="1", now=NOW,
    )


class OperationCapacityTests(unittest.TestCase):
    def test_trade_can_compare_overfull_partner_with_conditional_lineup(self):
        base = snapshot_fixture()
        partner = replace(base.teams[1], player_ids=(*base.teams[1].player_ids, "fa_wr"))
        snapshot = replace(base, teams=(base.teams[0], partner),
            owner_by_player=(*base.owner_by_player, ("fa_wr", "2")),
            free_agent_ids=tuple(pid for pid in base.free_agent_ids if pid != "fa_wr"))
        trade_current(snapshot)
        result = evaluate_trade(snapshot, build_entered_package(snapshot, send=("a_wr",), receive=("b_rb",)),
            projections=projection_fixture(), selected_board=board_fixture(snapshot, "selected"),
            market_board=board_fixture(snapshot, "market"))
        self.assertIn("DECISION-CONDITIONAL", result.modes)
        self.assertTrue(any("exceeds active capacity" in warning.lower() and "lineup" in warning.lower()
                            for warning in result.warnings))

    def test_trade_refresh_records_overage(self):
        with tempfile.TemporaryDirectory() as directory:
            bundle = SleeperAdapter(FakeSleeperClient(),
                player_cache_path=Path(directory) / "players.json").fetch("league-1", [1, 2])
        bundle = replace(bundle,
            league=replace(bundle.league, roster_positions=("QB",)),
            teams=(bundle.teams[0], replace(bundle.teams[1], player_ids=("p2", "fa"))))
        snapshot = build_trade_snapshot(
            league_key="fixture", user_id="u1", ranking_horizon="WEEKLY-PROXY",
            sleeper=bundle, schedule=schedule_fixture())
        self.assertTrue(any("ACTIVE_CAPACITY_EXCEEDED" in warning for warning in snapshot.warnings))
        trade_current(snapshot)

    def test_reserve_overage_trade_requires_manual_legality(self):
        base = snapshot_fixture()
        partner = replace(base.teams[1], reserve_ids=("b_low",))
        snapshot = replace(base, teams=(base.teams[0], partner))
        result = evaluate_trade(snapshot, build_entered_package(snapshot, send=("a_wr",), receive=("b_rb",)),
            projections=projection_fixture(), selected_board=board_fixture(snapshot, "selected"),
            market_board=board_fixture(snapshot, "market"))
        self.assertIn("DECISION-CONDITIONAL", result.modes)
        self.assertIn("MANUAL-LEGALITY", result.modes)
        self.assertTrue(any("reserve capacity" in warning for warning in result.warnings))

    def test_opponent_overage_is_observed_without_blocking_waiver_refresh(self):
        snapshot = overfull_waiver_snapshot(user_overfull=False)
        opponent = next(row for row in snapshot.roster_capacity if row.roster_id == "2")
        self.assertFalse(opponent.capacity_legal)
        self.assertFalse(snapshot.completeness.roster_capacity_complete)
        self.assertTrue(any("ACTIVE_CAPACITY_EXCEEDED" in warning for warning in snapshot.warnings))
        self.assertTrue(next(row for row in snapshot.roster_capacity if row.roster_id == "1").capacity_legal)

    def test_reserve_overage_is_observed_as_distinct_from_active_capacity(self):
        base = waiver_snapshot()
        user = replace(base.teams[0],
            player_ids=tuple(pid for pid in base.teams[0].player_ids if pid != "ir"), reserve_ids=())
        opponent = replace(base.teams[1], player_ids=("other", "fa_rb"),
            starter_ids=(), reserve_ids=("other", "fa_rb"))
        bundle = SleeperBundle(
            captured_at=base.captured_at, state=base.nfl_state, league=base.league,
            teams=(user, opponent), players=base.players, matchups=(), transactions=(),
            winner_bracket_rounds=None, loser_bracket_rows=0, stamps=base.stamps,
            player_directory_cache_status="fixture")
        snapshot = build_waiver_snapshot(
            league_key=base.league_key, user_id="u1", sleeper=bundle, now=NOW)
        capacity = next(row for row in snapshot.roster_capacity if row.roster_id == "2")
        self.assertFalse(capacity.reserve_legal)
        self.assertTrue(any("RESERVE_CAPACITY_EXCEEDED" in warning for warning in snapshot.warnings))

    def test_user_overage_is_visible_but_cannot_add_or_search(self):
        snapshot = overfull_waiver_snapshot(user_overfull=True)
        self.assertFalse(next(row for row in snapshot.roster_capacity if row.roster_id == "1").capacity_legal)
        with self.assertRaisesRegex(RosterIllegal, "capacity"):
            evaluate_waiver(snapshot, add="Target Quarterback", weeks=weeks(),
                projections=projections(), values=values(), drop_legality=legality(),
                news_fresh={"add": True}, now=NOW)
        with self.assertRaises((CoverageIncomplete, RosterIllegal)):
            search(snapshot=replace(complete_search_snapshot(),
                teams=snapshot.teams, roster_capacity=snapshot.roster_capacity,
                completeness=snapshot.completeness))
        with self.assertRaisesRegex(RosterIllegal, "capacity"):
            hypothetical_claim(snapshot, "add", "bench")

    def test_opponent_overage_does_not_veto_independent_waiver_search(self):
        observed = overfull_waiver_snapshot(user_overfull=False)
        fixture = complete_search_snapshot()
        searched = search(snapshot=replace(fixture,
            teams=observed.teams,
            players=(*observed.players, fixture.players[-1]),
            owner_by_player=observed.owner_by_player,
            roster_capacity=observed.roster_capacity,
            acquisitions=(*observed.acquisitions, fixture.acquisitions[-1]),
            completeness=observed.completeness,
            warnings=observed.warnings))
        self.assertTrue(searched)
        self.assertTrue(any("ACTIVE_CAPACITY_EXCEEDED" in warning for warning in searched.warnings))

    def test_structural_defects_still_block_observation(self):
        base = snapshot_fixture()
        broken = replace(base, teams=(replace(base.teams[0],
            player_ids=(*base.teams[0].player_ids, "b_rb")), base.teams[1]))
        with self.assertRaisesRegex(RosterIllegal, "DUPLICATE_OWNERSHIP"):
            trade_current(broken)


if __name__ == "__main__":
    unittest.main()
