import json
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from roster_theory.waiver.emergence import (
    FantasyResultComponents,
    GameUsageObservation,
    TrustedEditorialObservation,
    UsageMeasure,
    build_emergence_evidence,
    load_emergence_evidence,
    save_emergence_evidence,
)


NOW = datetime(2026, 9, 14, 12, tzinfo=timezone.utc)


def share(numerator, denominator):
    return UsageMeasure(
        numerator=float(numerator),
        team_denominator=float(denominator),
        reported_share=float(numerator) / float(denominator),
    )


def count(value, team_total=None):
    return UsageMeasure(
        numerator=float(value),
        team_denominator=float(team_total) if team_total is not None else None,
    )


def result(*, total=12.0, opportunity=8.0, touchdown=0.0, long_play=0.0, other=4.0, touchdowns=0, long_plays=0):
    return FantasyResultComponents(
        total_points=total,
        opportunity_points=opportunity,
        touchdown_points=touchdown,
        long_play_points=long_play,
        other_efficiency_points=other,
        touchdowns=touchdowns,
        long_plays=long_plays,
    )


def observation(
    week,
    *,
    snaps=(20, 60),
    routes=(12, 40),
    target_share=(2, 30),
    targets=2,
    carries=2,
    opportunities=4,
    designed=2,
    fantasy_result=None,
    injury="NONE",
    durability="NONE",
    identity="MATCHED",
    coverage="COMPLETE",
    game_status="PLAYED",
    source="fixture usage",
    updated_at=NOW,
    overtime=False,
):
    return GameUsageObservation(
        player_id="p1",
        player_name="Fixture Breakout",
        team="FX",
        position="RB",
        season=2026,
        week=week,
        game_id=f"fixture-{week}",
        source=source,
        captured_at=NOW,
        source_updated_at=updated_at,
        identity_status=identity,
        coverage_status=coverage,
        game_status=game_status,
        overtime=overtime,
        offensive_snap_share=share(*snaps),
        route_participation=share(*routes),
        target_share=share(*target_share),
        targets=count(targets, 30),
        carries=count(carries, 25),
        total_opportunities=count(opportunities, 55),
        goal_line_work=count(0, 4),
        red_zone_work=count(1, 12),
        two_minute_usage=count(1, 8),
        designed_touches=count(designed, 30),
        fantasy_result=fantasy_result or result(),
        teammate_injury_context=injury,
        role_durability=durability,
        role_news="Controlled fixture role context",
    )


def high_observation(week, **kwargs):
    kwargs.setdefault("durability", "DURABLE")
    return observation(
        week,
        snaps=(44, 60),
        routes=(30, 40),
        target_share=(6, 30),
        targets=6,
        carries=10,
        opportunities=16,
        designed=11,
        fantasy_result=result(total=17.0, opportunity=13.0, other=4.0),
        **kwargs,
    )


def evidence(observations, editorials=(), **kwargs):
    return build_emergence_evidence(
        league_key="fixture_league",
        observations=observations,
        editorials=editorials,
        captured_at=NOW,
        usage_maximum_age_hours=48,
        editorial_maximum_age_hours=72,
        **kwargs,
    )


class EmergenceClassificationTests(unittest.TestCase):
    def test_low_volume_multi_touchdown_result_is_efficiency_only(self):
        spike = observation(
            3,
            fantasy_result=result(
                total=25.0,
                opportunity=4.0,
                touchdown=12.0,
                long_play=6.0,
                other=3.0,
                touchdowns=2,
                long_plays=1,
            ),
        )
        player = evidence((observation(1), observation(2), spike)).players[0]
        self.assertEqual(player.classification, "EFFICIENCY_ONLY")
        self.assertFalse(player.affirmative_eligible)
        self.assertEqual(player.triggering_result.touchdowns, 2)

    def test_latest_high_participation_increase_is_role_expansion(self):
        player = evidence(
            (observation(1), observation(2), high_observation(3))
        ).players[0]
        self.assertEqual(player.classification, "ROLE_EXPANSION")
        self.assertTrue(player.affirmative_eligible)
        snap = next(
            row for row in player.comparisons if row.metric == "offensive_snap_share"
        )
        self.assertEqual(snap.rolling_sample_size, 2)
        self.assertEqual(snap.baseline_sample_size, 1)
        self.assertGreater(snap.delta_from_baseline, 0.15)

    def test_two_high_usage_games_are_a_supported_trend(self):
        player = evidence(
            (observation(1), high_observation(2), high_observation(3))
        ).players[0]
        self.assertEqual(player.classification, "SUPPORTED_TREND")
        self.assertEqual(player.rolling_window_weeks, (2, 3))
        self.assertEqual(player.baseline_weeks, (1,))

    def test_injury_fill_in_is_conditional_not_unconditional(self):
        fill_in = high_observation(
            3,
            injury="INJURY_FILL_IN",
            durability="TEMPORARY",
        )
        player = evidence((observation(1), observation(2), fill_in)).players[0]
        self.assertEqual(player.classification, "INJURY_CONDITIONAL")
        self.assertFalse(player.affirmative_eligible)

    def test_inactive_bye_and_overtime_context_are_preserved(self):
        bye = replace(
            observation(2),
            game_status="BYE",
            fantasy_result=None,
        )
        latest = high_observation(3, overtime=True)
        player = evidence((observation(1), bye, latest)).players[0]
        self.assertIn((2, "BYE"), player.excluded_games)
        self.assertTrue(player.observations[-1].overtime)
        self.assertTrue(any("overtime" in warning.lower() for warning in player.warnings))


class EmergenceFailClosedTests(unittest.TestCase):
    def test_empty_bundle_is_not_complete(self):
        bundle = evidence(())
        self.assertFalse(bundle.complete)
        self.assertEqual(bundle.players, ())

    def test_missing_share_denominator_is_visible_and_unknown(self):
        malformed = replace(
            high_observation(3),
            offensive_snap_share=UsageMeasure(reported_share=0.75),
        )
        player = evidence((observation(1), observation(2), malformed)).players[0]
        self.assertEqual(player.classification, "UNKNOWN")
        self.assertFalse(player.affirmative_eligible)
        self.assertTrue(any("denominator" in warning for warning in player.warnings))

    def test_incomplete_latest_game_fails_closed_but_remains_visible(self):
        incomplete = replace(
            high_observation(3),
            game_status="INCOMPLETE",
            coverage_status="PARTIAL",
        )
        player = evidence((observation(1), observation(2), incomplete)).players[0]
        self.assertEqual(player.classification, "UNKNOWN")
        self.assertIn((3, "INCOMPLETE"), player.excluded_games)
        self.assertEqual(player.coverage_status, "PARTIAL")

    def test_conflicting_sources_have_explicit_classification(self):
        source_a = high_observation(3, source="fixture A")
        source_b = replace(
            high_observation(3, source="fixture B"),
            carries=count(3, 25),
        )
        player = evidence(
            (observation(1), observation(2), source_a, source_b)
        ).players[0]
        self.assertEqual(player.classification, "CONFLICTING")
        self.assertFalse(player.affirmative_eligible)
        self.assertEqual(len(player.observations), 4)

    def test_stale_or_ambiguous_evidence_fails_closed(self):
        stale = high_observation(3, updated_at=NOW - timedelta(hours=49))
        stale_player = evidence((observation(1), observation(2), stale)).players[0]
        self.assertEqual(stale_player.classification, "UNKNOWN")
        self.assertTrue(any("stale" in warning.lower() for warning in stale_player.warnings))

        ambiguous = high_observation(3, identity="AMBIGUOUS")
        bundle = evidence((observation(1), observation(2), ambiguous))
        self.assertEqual(bundle.ambiguous_player_ids, ("p1",))
        self.assertEqual(bundle.players[0].classification, "UNKNOWN")

    def test_unknown_injury_or_role_context_blocks_affirmative_signal(self):
        unknown = high_observation(
            3,
            injury="UNKNOWN",
            durability="UNCONFIRMED",
        )
        player = evidence((observation(1), observation(2), unknown)).players[0]
        self.assertEqual(player.classification, "UNKNOWN")
        self.assertTrue(any("injury" in warning.lower() for warning in player.warnings))


class TrustedEditorialAndReplayTests(unittest.TestCase):
    def editorial(self, **kwargs):
        values = {
            "player_id": "p1",
            "player_name": "Fixture Breakout",
            "author": "Fixture Analyst",
            "source": "Fixture Waiver Notes",
            "source_url": "https://example.invalid/fixture",
            "artifact_id": None,
            "published_at": NOW - timedelta(hours=2),
            "captured_at": NOW,
            "identity_status": "MATCHED",
            "explicit_labels": ("priority add", "stash"),
            "explicit_rank": 3,
            "explicit_tier": "Tier 1",
            "explicit_role_claim": "The author explicitly calls this a durable role.",
            "explicit_faab_min_percent": 8.0,
            "explicit_faab_max_percent": 12.0,
            "excerpt": "Short fixture excerpt.",
        }
        values.update(kwargs)
        return TrustedEditorialObservation(**values)

    def test_editorial_fields_preserve_explicit_types_without_reinterpretation(self):
        player = evidence(
            (observation(1), high_observation(2), high_observation(3)),
            (self.editorial(),),
        ).players[0]
        editorial = player.editorials[0]
        self.assertEqual(editorial.explicit_rank, 3)
        self.assertEqual(editorial.explicit_labels, ("priority add", "stash"))
        self.assertEqual(editorial.explicit_tier, "Tier 1")
        self.assertEqual(editorial.explicit_faab_min_percent, 8.0)
        self.assertEqual(player.classification, "SUPPORTED_TREND")

    def test_stale_editorial_is_visible_and_blocks_affirmative_path(self):
        stale = self.editorial(published_at=NOW - timedelta(hours=73))
        player = evidence(
            (observation(1), high_observation(2), high_observation(3)),
            (stale,),
        ).players[0]
        self.assertEqual(player.classification, "UNKNOWN")
        self.assertTrue(any("editorial" in warning.lower() for warning in player.warnings))

    def test_equivalent_input_order_has_identical_classification_and_hash(self):
        rows = (observation(1), high_observation(2), high_observation(3))
        first = evidence(rows, (self.editorial(),))
        second = evidence(tuple(reversed(rows)), (self.editorial(),))
        self.assertEqual(first.evidence_hash, second.evidence_hash)
        self.assertEqual(first.players[0].classification, second.players[0].classification)

    def test_expert_explanatory_prose_cannot_change_classification(self):
        first = evidence(
            (observation(1), high_observation(2), high_observation(3)),
            (self.editorial(excerpt="Explanation A"),),
        )
        second = evidence(
            (observation(1), high_observation(2), high_observation(3)),
            (self.editorial(excerpt="Explanation B"),),
        )
        self.assertEqual(first.players[0].classification, "SUPPORTED_TREND")
        self.assertEqual(
            first.players[0].classification,
            second.players[0].classification,
        )

    def test_hash_verified_round_trip_rejects_tampering(self):
        bundle = evidence(
            (observation(1), high_observation(2), high_observation(3)),
            (self.editorial(),),
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "emergence.json"
            save_emergence_evidence(bundle, path)
            self.assertEqual(load_emergence_evidence(path), bundle)
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["players"][0]["classification"] = "EFFICIENCY_ONLY"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "hash verification"):
                load_emergence_evidence(path)


if __name__ == "__main__":
    unittest.main()
