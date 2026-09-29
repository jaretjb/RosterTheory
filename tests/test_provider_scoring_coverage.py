"""Independent provider-to-readiness regression evidence for MA-002b."""
from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from roster_theory.core.errors import CoverageIncomplete
from roster_theory.core.models import Player, Projection
from roster_theory.core.projections import projection_is_complete, projection_is_usable
from roster_theory.core.provenance import canonical_json
from roster_theory.core.run_contract import restore_record
from roster_theory.core.scoring import score_stats
from roster_theory.core.scoring_contract import ScoringScope, assess_scoring_rules
from roster_theory.inseason.evaluation import (
    InSeasonContext, InSeasonWeek, build_weekly_projection_matrix,
)
from roster_theory.providers.fantasypros import (
    FantasyProsAdapter, normalize_projections, normalize_scored_projections,
)
from roster_theory.trade.board_service import _canonical_projections, _fetch_value_inputs
from roster_theory.trade.boards import build_projection_curves
from roster_theory.providers.projection_scoring import (
    SCORING_CONTRACT_VERSION, WEEKLY_RULES, score_draft_projection_row,
    score_projection_row, scoring_coverage,
)
from tests.ma001_fixtures import PROFILES, rules


class Provider:
    def __init__(self, rows):
        self.rows = rows

    def projections(self, season, **params):
        return {"season": season, "week": params["week"], "scoring": params["scoring"],
                "players": self.rows}

    def consensus_rankings(self, season, **params):
        return {"year": season, "week": params["week"], "scoring": params["scoring"],
                "ranking_type_name": "Weekly", "players": []}

    def news(self, **params):
        return {"items": []}


def projection(stats, scoring, position="QB"):
    provider = Provider([{"fpid": "synthetic", "position_id": position, "stats": stats}])
    return FantasyProsAdapter(provider).weekly_projections(2027, 4, position, scoring).projections[0]


class ProviderScoringCoverageTests(unittest.TestCase):
    def test_legacy_core_and_weekly_adapter_agree_on_incomplete_inputs(self):
        scoring = {"pass_yd": .04, "pass_td": 6}
        for stats, expected_category in (
            ({"pass_yds": 250}, "missing"),
            ({"pass_yds": 250, "pass_tds": "nan"}, "invalid"),
        ):
            with self.subTest(category=expected_category):
                core = score_stats(stats, scoring, position="QB")
                adapter = projection(stats, scoring)
                self.assertEqual(core.points, 10)
                self.assertFalse(core.complete)
                self.assertIn("pass_td", getattr(core, expected_category + "_settings"))
                self.assertIn(expected_category + "_statistic=pass_td", adapter.coverage_status)
        zero = {"pass_yds": 250, "pass_tds": 0}
        self.assertTrue(score_stats(zero, scoring, position="QB").complete)
        self.assertEqual(projection(zero, scoring).coverage_status, "complete")
        unsupported = {**scoring, "bonus_pass_300": 3}
        self.assertFalse(score_stats(zero, unsupported, position="QB").complete)
        self.assertIn("unsupported_rule=bonus_pass_300",
                      projection(zero, unsupported).coverage_status)
        irrelevant = {**scoring, "bonus_rec_rb": 1}
        self.assertTrue(score_stats(zero, irrelevant, position="QB").complete)
        self.assertEqual(projection(zero, irrelevant).coverage_status, "complete")
        overflow = score_stats({"pass_yds": 1e308}, {"pass_yd": 1e308}, position="QB")
        self.assertFalse(overflow.complete)
        self.assertEqual(overflow.invalid_settings, ("arithmetic_overflow",))
        conflicting = score_stats({"pass_td": 1, "pass_tds": 2}, {"pass_td": 6},
                                  position="QB")
        self.assertFalse(conflicting.complete)
        self.assertEqual(conflicting.invalid_settings, ("pass_td",))
        bad_multiplier = score_stats({"pass_tds": 1}, {"pass_td": float("nan")},
                                     position="QB")
        self.assertFalse(bad_multiplier.complete)
        self.assertEqual(bad_multiplier.invalid_settings, ("pass_td",))

    def test_core_skill_forecast_becomes_labeled_estimate_only_for_missing_optional_stats(self):
        scoring = {"pass_yd": .04, "pass_td": 6, "pass_int": -2,
                   "rush_yd": .1, "rush_td": 6, "fum_lost": -2}
        core = {"pass_yds": 250, "pass_tds": 2, "pass_ints": 1,
                "rush_yds": 20, "rush_tds": 0}
        row = projection(core, scoring)
        self.assertEqual(row.league_points, 22)
        self.assertTrue(row.coverage_status.startswith("estimated_missing_stats_v1:"))
        self.assertIn("missing_statistic=fum_lost", row.coverage_status)
        self.assertFalse(projection_is_complete(row, current_week=4))
        self.assertTrue(projection_is_usable(row, current_week=4, allow_estimate=True))
        self.assertFalse(projection_is_usable(row, current_week=4))
        strict = build_projection_curves((row,), {"synthetic": "QB"},
            required_counts={"QB": 1}, expected_weeks=(4,), current_week=4,
            allow_partial=True)
        estimated = build_projection_curves((row,), {"synthetic": "QB"},
            required_counts={"QB": 1}, expected_weeks=(4,), current_week=4,
            allow_partial=True, allow_estimates=True)
        self.assertFalse(strict[0].slot_points)
        self.assertEqual(estimated[0].slot_points, ((1, 22.0),))
        missing_core = projection({"pass_yds": 250, "pass_ints": 1,
                                   "rush_yds": 20, "rush_tds": 0}, scoring)
        self.assertFalse(projection_is_usable(missing_core, current_week=4, allow_estimate=True))
        invalid = projection({**core, "fum_lost": "bad"}, scoring)
        self.assertFalse(projection_is_usable(invalid, current_week=4, allow_estimate=True))

    def test_missing_touchdowns_are_not_observed_zero(self):
        scoring = {"pass_yd": .04, "pass_td": 6}
        missing = projection({"pass_yds": 250}, scoring)
        zero = projection({"pass_yds": 250, "pass_tds": 0}, scoring)
        self.assertEqual((missing.league_points, zero.league_points), (10, 10))
        self.assertNotEqual(missing.coverage_status, "complete")
        self.assertEqual(zero.coverage_status, "complete")

    def test_unknown_active_rule_is_not_complete(self):
        row = projection({"pass_yds": 300}, {"pass_yd": .04, "bonus_pass_300": 3})
        self.assertEqual(row.league_points, 12)
        self.assertNotEqual(row.coverage_status, "complete")

    def test_independent_qb_receiver_and_specialist_arithmetic(self):
        for interception, expected in ((-2, 17), (-1, 18)):
            row = projection({"pass_yds": 250, "pass_tds": 2, "pass_ints": 1,
                              "rush_yds": -10, "fumbles_lost": 1},
                             {"pass_yd": .04, "pass_td": 6, "pass_int": interception,
                              "rush_yd": .1, "fum_lost": -2})
            self.assertEqual(row.league_points, expected)
            self.assertEqual(row.coverage_status, "complete")
        row = projection({"rec_rec": "4.5", "rec_yds": 50, "rec_tds": .5},
                         {"rec": .5, "rec_yd": .1, "rec_td": 6, "bonus_rec_te": 1}, "TE")
        self.assertEqual((row.league_points, row.coverage_status), (14.75, "complete"))
        kicker = projection({"fgm_40_49": 2, "fgm_50p": 1, "fgmiss": 1, "xpm": 3},
                            {"fgm_40_49": 4, "fgm_50p": 5, "fgmiss": -1, "xpm": 1}, "K")
        defense = projection({"def_int": 1, "def_sack": 2, "pts_allow_7_13": .5},
                             {"int": 2, "sack": 1, "pts_allow_7_13": 4}, "DEF")
        self.assertEqual((kicker.league_points, kicker.coverage_status), (15, "complete"))
        self.assertEqual((defense.league_points, defense.coverage_status), (6, "complete"))

    def test_missing_zero_and_invalid_statistics_across_positions(self):
        for position, key in (("QB", "pass_td"), ("WR", "rec"),
                              ("K", "fgm_50p"), ("DST", "pts_allow_0")):
            for value in (None, "", "-", True, "NaN", "inf", [], {}):
                with self.subTest(position=position, value=value):
                    row = projection({key: value}, {key: 1}, position)
                    self.assertIn(f"invalid_statistic={key}", row.coverage_status)
                    self.assertEqual(row.league_points, 0)
            row = projection({}, {key: 1}, position)
            self.assertIn(f"missing_statistic={key}", row.coverage_status)
            row = projection({key: "0"}, {key: 1}, position)
            self.assertEqual((row.league_points, row.coverage_status), (0, "complete"))

    def test_nonfinite_payload_cannot_acquire_valid_provenance(self):
        for value in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(value=value), self.assertRaisesRegex(CoverageIncomplete, "Non-finite"):
                projection({"pass_td": value}, {"pass_td": 6})

    def test_aliases_must_agree_and_cannot_hide_invalid_values(self):
        for stats in ({"pass_td": 0, "pass_tds": 1},
                      {"pass_td": None, "pass_tds": 1}):
            row = projection(stats, {"pass_td": 6})
            self.assertIn("invalid_statistic=pass_td", row.coverage_status)
        same = projection({"pass_td": "1", "pass_tds": 1}, {"pass_td": 6})
        self.assertEqual((same.league_points, same.coverage_status), (6, "complete"))

    def test_fantasypros_fumbles_are_lost_fumbles_in_weekly_projections(self):
        row = projection({"fumbles": 2.85}, {"fum_lost": -2})
        self.assertEqual((row.league_points, row.coverage_status), (-5.7, "complete"))
        # FantasyPros's published API example has 293.7 standard points;
        # the stat line reconciles only when its `fumbles` is scored as lost.
        sample = projection({"rush_yds": 1191.38, "rush_tds": 12.72,
            "rec_yds": 780.2, "rec_tds": 4.32, "fumbles": 2.85},
            {"rush_yd": .1, "rush_td": 6, "rec_yd": .1, "rec_td": 6,
             "fum_lost": -2}, "RB")
        self.assertAlmostEqual(sample.league_points, 293.7, places=1)
        self.assertEqual(sample.coverage_status, "complete")
        conflicting = projection({"fumbles": 1, "fumbles_lost": 2}, {"fum_lost": -2})
        self.assertIn("invalid_statistic=fum_lost", conflicting.coverage_status)
        draft_rules = assess_scoring_rules({"fum_lost": -2},
            scope=ScoringScope("synthetic", 2027, "draft", "SEASON", None),
            catalogue=WEEKLY_RULES, catalogue_version="draft-fumbles")
        draft = score_draft_projection_row(
            {"position_id": "RB", "stats": {"fumbles": 2.85}}, draft_rules)
        self.assertEqual((draft.diagnostic_points, scoring_coverage(draft)), (-5.7, "complete"))

    def test_preseason_fumbles_change_only_declared_reference_statistic(self):
        for profile, expected in (("reference_a", -7.7), ("reference_b", -6.7)):
            with self.subTest(profile=profile):
                source_rules = rules(profile)["scoring_settings"]
                scoring = {key: source_rules[key] for key in ("pass_int", "fum_lost")}
                scope = ScoringScope(profile, 2027, "draft", "SEASON", None)
                assessment = assess_scoring_rules(scoring, scope=scope,
                    catalogue=WEEKLY_RULES, catalogue_version="draft-fumbles")
                row = {"position_id": "QB", "stats": {"pass_ints": 1, "fumbles": 2.85}}
                scored = score_draft_projection_row(row, assessment)
                self.assertEqual((scored.diagnostic_points, scoring_coverage(scored)),
                                 (expected, "complete"))
                missing = score_draft_projection_row(
                    {"position_id": "QB", "stats": {"pass_ints": 1}}, assessment)
                self.assertIn("missing_statistic=fum_lost", scoring_coverage(missing))
                invalid = score_draft_projection_row(
                    {"position_id": "QB", "stats": {"pass_ints": 1,
                     "fumbles": 2.85, "fumbles_lost": 3}}, assessment)
                self.assertIn("invalid_statistic=fum_lost", scoring_coverage(invalid))
                full = assess_scoring_rules(source_rules, scope=scope,
                    catalogue=WEEKLY_RULES, catalogue_version="draft-fumbles")
                full_result = score_draft_projection_row(row, full)
                self.assertFalse(full_result.complete)
                self.assertNotIn("missing_statistic=fum_lost", scoring_coverage(full_result))

    def test_ambiguous_defense_aliases_do_not_prove_exact_events(self):
        for position, stats, setting in (
            ("DST", {"def_ff": 1}, "def_st_ff"),
            ("DST", {"def_fr": 1}, "def_st_fum_rec"),
            ("DST", {"def_retd": 1}, "def_st_td"),
            ("DST", {"def_pa_a": 1}, "pts_allow_0"),
        ):
            with self.subTest(setting=setting):
                self.assertIn(f"missing_statistic={setting}",
                              projection(stats, {setting: 2}, position).coverage_status)

    def test_player_and_defense_special_teams_categories_are_distinct(self):
        settings = {"st_td": 6, "st_ff": 1, "def_st_td": 6, "def_st_ff": 2}
        player = projection({"st_td": 1, "st_ff": 1}, settings, "WR")
        defense = projection({"def_st_td": 1, "def_st_ff": 1}, settings, "DST")
        self.assertEqual((player.league_points, player.coverage_status), (7, "complete"))
        self.assertEqual((defense.league_points, defense.coverage_status), (8, "complete"))
        missing = projection({"st_td": 1, "def_st_ff": 1}, settings, "WR")
        self.assertIn("missing_statistic=st_ff", missing.coverage_status)

    def test_position_and_rule_applicability_do_not_guess_zeros(self):
        row = projection({"rec": 4}, {"rec": .5, "bonus_rec_te": 1, "sack": 1}, "WR")
        self.assertEqual((row.league_points, row.coverage_status), (2, "complete"))
        row = projection({"pass_yds": 10}, {"pass_yd": .04}, "WR")
        self.assertEqual((row.league_points, row.coverage_status), (.4, "complete"))
        self.assertIn("missing_statistic=pass_yd", projection({}, {"pass_yd": .04}, "WR").coverage_status)
        for position in ("", "IDP"):
            self.assertIn("missing_position", projection({"rec": 4}, {"rec": .5}, position).coverage_status)
        self.assertEqual(projection({}, {"fum_rec": 2}, "WR").coverage_status, "complete")
        self.assertIn("missing_statistic=fum_rec",
                      projection({}, {"fum_rec": 2}, "DST").coverage_status)
        self.assertEqual(projection({"fum_rec": 1}, {"fum_rec": 2}, "DST").league_points, 2)

    def test_disabled_unknown_rules_and_invalid_multipliers_remain_distinct(self):
        row = projection({"pass_td": 1}, {"pass_td": 6, "bonus_pass_300": 0})
        self.assertEqual((row.league_points, row.coverage_status), (6, "complete"))
        for raw in ("0", True):
            row = projection({"pass_td": 1}, {"pass_td": raw})
            self.assertIn("invalid_multiplier=pass_td", row.coverage_status)

    def test_totals_do_not_supply_missing_event_buckets(self):
        for position, stats, scoring in (
            ("K", {"fgm": 3}, {"fgm_40_49": 4}),
            ("DST", {"points_allowed": 10}, {"pts_allow_7_13": 4}),
            ("QB", {"points": 20}, {"pass_td": 6}),
        ):
            row = projection(stats, scoring, position)
            self.assertEqual(row.league_points, 0)
            self.assertIn("missing_statistic", row.coverage_status)

    def test_unscored_normalization_is_not_a_completeness_check(self):
        value = Provider([{"fpid": "x", "position_id": "QB", "stats": {"pass_td": 1}}]).projections(
            2027, week=4, scoring="STD")
        row = normalize_projections(value, horizon="WEEKLY", league_points={"x": 6}).projections[0]
        self.assertEqual(row.coverage_status, "unverified_scoring_v1")

    def test_malformed_and_duplicate_rows_are_not_silently_discarded(self):
        for rows in ([None], [{"stats": {}}],
                     [{"fpid": "same"}, {"fpid": "same"}], "bad"):
            with self.subTest(rows=rows), self.assertRaises(CoverageIncomplete):
                FantasyProsAdapter(Provider(rows)).weekly_projections(2027, 4, "QB", {"pass_td": 6})

    def test_direct_and_prepared_cached_paths_preserve_identical_coverage(self):
        provider = Provider([
            {"fpid": "good", "position_id": "QB", "stats": {"pass_yds": 250, "pass_tds": 0}},
            {"fpid": "missing", "position_id": "QB", "stats": {"pass_yds": 250}},
        ])
        scoring = {"pass_yd": .04, "pass_td": 6}
        snapshot = SimpleNamespace(
            league=SimpleNamespace(league_id="synthetic", season=2027, scoring=tuple(scoring.items())),
            manifest=SimpleNamespace(current_week=1), weeks=(SimpleNamespace(week=4),),
        )
        direct = FantasyProsAdapter(provider).weekly_projections(2027, 4, "ALL", scoring,
                                                                league_id="synthetic")
        with tempfile.TemporaryDirectory() as directory, patch("roster_theory.storage.request_gate.time.sleep"):
            kwargs = dict(client=provider, cache_dir=Path(directory),
                          budget_path=Path(directory) / "budget.json", ranking_positions=("QB",))
            prepared = _fetch_value_inputs(SimpleNamespace(snapshot=snapshot), **kwargs).projection_sets[0]
            with patch.object(provider, "projections", side_effect=AssertionError("must use raw cache")):
                cached = _fetch_value_inputs(SimpleNamespace(snapshot=snapshot), **kwargs).projection_sets[0]
        self.assertEqual(direct.projections, prepared.projections)
        self.assertEqual(prepared.projections, cached.projections)
        self.assertEqual(direct.stamp.scoring_hash, prepared.stamp.scoring_hash)
        self.assertEqual(direct.stamp.parameter_hash, cached.stamp.parameter_hash)
        self.assertEqual(cached.stamp.cache_status, "hit")

    def test_scope_and_rule_hashes_are_league_specific_and_order_independent(self):
        value = Provider([{"fpid": "x", "position_id": "QB", "stats": {"pass_tds": 1}}]).projections(
            2027, week=4, scoring="STD")
        def dataset(league, scoring):
            return normalize_scored_projections(value, scoring_settings=scoring,
                season=2027, week=4, league_id=league, captured_at=datetime(2027, 9, 1, tzinfo=timezone.utc))
        first = dataset("a", {"pass_td": 6, "pass_int": 0})
        reordered = dataset("a", {"pass_int": 0, "pass_td": 6})
        other_league = dataset("b", {"pass_td": 6, "pass_int": 0})
        self.assertEqual(canonical_json(first), canonical_json(reordered))
        self.assertEqual(first.stamp.scoring_hash, other_league.stamp.scoring_hash)
        self.assertNotEqual(first.stamp.parameter_hash, other_league.stamp.parameter_hash)
        with self.assertRaises(CoverageIncomplete):
            normalize_scored_projections(value, scoring_settings={"pass_td": 6}, season=2027, week=5)

    def test_reference_rules_are_accounted_for_without_claiming_provider_coverage(self):
        for profile, active_count in zip(PROFILES, (35, 41)):
            scoring = rules(profile)["scoring_settings"]
            assessment = assess_scoring_rules(scoring,
                scope=ScoringScope(profile, 2026, "weekly_projection", "WEEKLY", 1),
                catalogue=WEEKLY_RULES, catalogue_version=SCORING_CONTRACT_VERSION)
            self.assertEqual(len(assessment.active_rules), active_count)
            self.assertEqual(len(assessment.active_rules) + len(assessment.disabled_settings), len(scoring))
            self.assertEqual(assessment.issues, ())
            observed = {
                rule.statistic: 0 for rule, _ in assessment.active_rules
                if rule.setting != "fum_rec_td"
            }
            qb = score_projection_row({"position_id": "QB", "stats": observed}, assessment)
            self.assertIn("missing_statistic=fum_rec_td", scoring_coverage(qb))
            self.assertNotIn("fum_rec=", scoring_coverage(qb))
            observed["fum_rec_td"] = 0
            self.assertEqual(scoring_coverage(score_projection_row(
                {"position_id": "QB", "stats": observed}, assessment
            )), "complete")
            for position in ("QB", "RB", "WR", "TE", "K", "DST"):
                empty = score_projection_row({"position_id": position, "stats": {}}, assessment)
                self.assertFalse(empty.complete)
                self.assertFalse(empty.structural_zero_settings)
                with self.assertRaises(CoverageIncomplete):
                    empty.require_points()

    def test_provider_gap_survives_serialization_canonicalization_and_decision_gates(self):
        value = Provider([{"fpid": "bad", "position_id": "QB", "stats": {"pass_yds": 250}},
                          {"fpid": "good", "position_id": "QB",
                           "stats": {"pass_yds": 250, "pass_tds": 0}}]).projections(
                               2027, week=4, scoring="STD")
        dataset = normalize_scored_projections(value, scoring_settings={"pass_yd": .04, "pass_td": 6},
                                               season=2027, week=4)
        restored = tuple(restore_record(Projection, json.loads(canonical_json(row))) for row in dataset.projections)
        players = {pid: Player(pid, pid, ("QB",), active=True) for pid in ("bad", "good")}
        canonical, positions, warnings = _canonical_projections(
            (replace(dataset, projections=restored),), {pid: pid for pid in players},
            {pid: "QB" for pid in players}, {}, players, current_week=4)
        self.assertIn("missing_statistic=pass_td", " ".join(warnings["bad"]))
        # Trade rank curves must exclude partial totals; shared Trade/Waiver
        # lineup evidence must retain missing points rather than substitute 0.
        curves = build_projection_curves(canonical, positions, required_counts={"QB": 1},
                                         expected_weeks=(4,), current_week=4)
        self.assertEqual(curves[0].raw_player_points, (("good", 10),))
        matrix = build_weekly_projection_matrix(InSeasonContext(
            players=tuple(players.values()), roster_positions=("QB",), weeks=(InSeasonWeek(4, False),),
            unowned_player_ids=(), current_week=4), canonical)
        self.assertIsNone(matrix.cell("bad", 4).points)
        self.assertEqual(matrix.cell("good", 4).points, 10)
        self.assertFalse(matrix.complete)
