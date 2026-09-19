from __future__ import annotations

import unittest

from roster_theory.core.models import Player, Projection
from roster_theory.inseason.evaluation import (
    InSeasonContext,
    InSeasonWeek,
    build_weekly_projection_matrix,
    lineup_with_replacement_floor,
)


def player(player_id: str, position: str, team: str) -> Player:
    return Player(
        player_id=player_id,
        name=player_id,
        positions=(position,),
        sleeper_id=player_id,
        nfl_team=team,
        active=True,
        identity_confidence="fixture",
    )


def replacement_result(
    *,
    players: tuple[Player, ...],
    roster_positions: tuple[str, ...],
    roster: set[str],
    points: dict[str, float],
    bye_teams: tuple[str, ...],
    evaluation_positions: tuple[str, ...] = ("QB", "RB", "WR", "TE"),
    exclusions: tuple[str, ...] = (),
):
    roster_ids = set(roster)
    context = InSeasonContext(
        players=players,
        roster_positions=roster_positions,
        weeks=(InSeasonWeek(1, False, bye_teams),),
        unowned_player_ids=tuple(
            row.player_id for row in players if row.player_id not in roster_ids
        ),
        evaluation_positions=evaluation_positions,
    )
    matrix = build_weekly_projection_matrix(
        context,
        tuple(
            Projection(row.player_id, "WEEKLY", 1, (), points[row.player_id], "fixture")
            for row in players
        ),
    )
    return lineup_with_replacement_floor(
        context,
        matrix,
        roster,
        1,
        allow_partial=False,
        replacement_exclusions=exclusions,
    )


class InSeasonReplacementCounterfactualTests(unittest.TestCase):
    def test_active_bench_fills_bye_before_waiver_is_used(self) -> None:
        players = (
            player("starter", "RB", "BYE"),
            player("bench", "RB", "ACT"),
            player("waiver", "RB", "FA"),
        )
        result = replacement_result(
            players=players,
            roster_positions=("RB", "BN"),
            roster={"starter", "bench"},
            points={"starter": 12.0, "bench": 6.0, "waiver": 9.0},
            bye_teams=("BYE",),
        )
        self.assertEqual(result.lineup.score, 6.0)
        self.assertEqual(result.roster_starter_ids, ("bench",))
        self.assertEqual(result.replacement_player_ids, ())

    def test_evaluated_add_is_excluded_in_favor_of_next_waiver(self) -> None:
        players = (
            player("starter", "QB", "BYE"),
            player("target", "QB", "FA1"),
            player("next", "QB", "FA2"),
        )
        result = replacement_result(
            players=players,
            roster_positions=("QB", "BN"),
            roster={"starter"},
            points={"starter": 22.0, "target": 20.0, "next": 17.0},
            bye_teams=("BYE",),
            exclusions=("target",),
        )
        self.assertEqual(result.lineup.score, 17.0)
        self.assertEqual(result.replacement_player_ids, ("next",))

    def test_flex_optimizer_uses_only_the_lost_capacity(self) -> None:
        players = (
            player("active_rb", "RB", "ACT"),
            player("bye_wr", "WR", "BYE"),
            player("waiver_rb", "RB", "FA1"),
            player("waiver_wr", "WR", "FA2"),
        )
        result = replacement_result(
            players=players,
            roster_positions=("RB", "FLEX", "BN"),
            roster={"active_rb", "bye_wr"},
            points={
                "active_rb": 6.0,
                "bye_wr": 8.0,
                "waiver_rb": 10.0,
                "waiver_wr": 9.0,
            },
            bye_teams=("BYE",),
        )
        self.assertEqual(result.lineup.score, 16.0)
        self.assertEqual(result.replacement_player_ids, ("waiver_rb",))

    def test_multiple_byes_allow_multiple_legal_replacements(self) -> None:
        players = (
            player("bye_rb", "RB", "BYE1"),
            player("bye_wr", "WR", "BYE2"),
            player("active_te", "TE", "ACT"),
            player("waiver_rb", "RB", "FA1"),
            player("waiver_wr", "WR", "FA2"),
            player("second_rb", "RB", "FA3"),
        )
        result = replacement_result(
            players=players,
            roster_positions=("RB", "WR", "FLEX", "BN"),
            roster={"bye_rb", "bye_wr", "active_te"},
            points={
                "bye_rb": 11.0,
                "bye_wr": 10.0,
                "active_te": 5.0,
                "waiver_rb": 12.0,
                "waiver_wr": 7.0,
                "second_rb": 11.0,
            },
            bye_teams=("BYE1", "BYE2"),
        )
        self.assertEqual(result.lineup.score, 24.0)
        self.assertEqual(result.replacement_player_ids, ("waiver_rb", "waiver_wr"))

    def test_dst_bye_uses_next_available_dst_without_touching_kicker(self) -> None:
        players = (
            player("kicker", "K", "ACT"),
            player("bye_dst", "DST", "BYE"),
            player("target_dst", "DST", "FA1"),
            player("next_dst", "DST", "FA2"),
        )
        result = replacement_result(
            players=players,
            roster_positions=("K", "DST", "BN"),
            roster={"kicker", "bye_dst"},
            points={"kicker": 8.0, "bye_dst": 7.0, "target_dst": 9.0, "next_dst": 6.0},
            bye_teams=("BYE",),
            evaluation_positions=("K", "DST"),
            exclusions=("target_dst",),
        )
        self.assertEqual(result.lineup.score, 14.0)
        self.assertEqual(result.roster_starter_ids, ("kicker",))
        self.assertEqual(result.replacement_player_ids, ("next_dst",))

    def test_dst_bye_cannot_be_replaced_by_higher_scoring_superflex_qb(self) -> None:
        players = (
            player("active_qb", "QB", "ACT"),
            player("bye_dst", "DST", "BYE"),
            player("waiver_qb", "QB", "FA1"),
            player("waiver_dst", "DST", "FA2"),
        )
        result = replacement_result(
            players=players,
            roster_positions=("SUPER_FLEX", "DST", "BN"),
            roster={"active_qb", "bye_dst"},
            points={
                "active_qb": 20.0,
                "bye_dst": 8.0,
                "waiver_qb": 19.0,
                "waiver_dst": 6.0,
            },
            bye_teams=("BYE",),
            evaluation_positions=("QB", "DST"),
        )
        self.assertEqual(result.lineup.score, 26.0)
        self.assertEqual(result.replacement_player_ids, ("waiver_dst",))


if __name__ == "__main__":
    unittest.main()
