import json
import tempfile
import unittest
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from roster_theory.cli import build_parser, command_waiver_search
from roster_theory.core.errors import CoverageIncomplete, StaleData
from roster_theory.core.models import Projection
from roster_theory.core.provenance import stable_hash
from roster_theory.inseason.evaluation import InSeasonContext, build_weekly_projection_matrix
from roster_theory.waiver.evaluation import (
    ContingencyScenarioInput,
    PlayerValueInput,
    reconcile_current_week_inactive_omissions,
)
from roster_theory.waiver.policy import load_waiver_policy
from roster_theory.waiver.search import (
    load_waiver_search,
    save_waiver_search,
    search_waiver_candidates,
)
from roster_theory.waiver.service import (
    WaiverRefreshResult,
    format_waiver_search,
    search_waivers,
    waiver_search_action_summary,
    waiver_refresh_plan,
    waiver_search_report,
)
from roster_theory.waiver.snapshot import PlayerAcquisition
from tests.test_waiver_evaluation import (
    CAPTURED,
    NOW,
    emergence_evidence,
    legality,
    player,
    projections,
    values,
    waiver_snapshot,
    waiver_wire_evidence,
    weeks,
)


POLICY_PATH = (
    Path(__file__).parent
    / "fixtures"
    / "waiver"
    / "league_alpha.decision-policy.json"
)


def complete_search_snapshot(*, open_slot=False, league_key="league_alpha"):
    snapshot = waiver_snapshot(open_slot=open_slot)
    return replace(
        snapshot,
        league_key=league_key,
        players=(*snapshot.players, player("fa_te", "Free Tight End", "TE", "JJJ")),
        acquisitions=(
            *snapshot.acquisitions,
            PlayerAcquisition(
                player_id="fa_te",
                state="WAIVERS",
                owner_roster_id=None,
                transaction_ids=(),
                evidence=("controlled_fixture",),
            ),
        ),
    )


def complete_projections(*, prunable=False):
    result = list(projections())
    result.extend(
        Projection(
            player_id="fa_te",
            horizon="WEEKLY",
            week=week,
            raw_stats=(),
            league_points=6.0,
            source="fixture",
        )
        for week in (1, 2, 3)
    )
    if prunable:
        result = [
            replace(row, league_points=-1.0)
            if row.player_id in {"bench", "fa_rb", "fa_wr", "fa_te"}
            else row
            for row in result
        ]
    return tuple(result)


def complete_values(*, candidates_negative=False):
    result = [*values(), PlayerValueInput("fa_te", 12.0, 9.0, 18.0)]
    if candidates_negative:
        candidate_ids = {"add", "fa_rb", "fa_wr", "fa_te"}
        result = [
            replace(
                row,
                selected_value=-100.0,
                market_value=-100.0,
                raw_projection=-100.0,
            )
            if row.player_id in candidate_ids
            else row
            for row in result
        ]
    return tuple(result)


def news():
    return {"add": True, "fa_rb": True, "fa_wr": True, "fa_te": True}


def search(
    *,
    enable_pruning=False,
    snapshot=None,
    projection_rows=None,
    value_rows=None,
    contingencies=(),
    role_evidence=None,
    waiver_wire_evidence=None,
):
    return search_waiver_candidates(
        snapshot or complete_search_snapshot(),
        weeks=weeks(),
        projections=projection_rows or complete_projections(),
        values=value_rows or complete_values(),
        drop_legality=legality(),
        news_fresh=news(),
        contingencies=contingencies,
        waiver_wire_evidence=waiver_wire_evidence,
        emergence_evidence=role_evidence,
        input_bundle_hash="controlled-bundle-hash",
        availability_source="controlled fixture",
        policy=load_waiver_policy(POLICY_PATH),
        enable_pruning=enable_pruning,
        now=NOW,
    )


def input_payload(*, league_key="league_alpha"):
    payload = {
        "schema_version": 1,
        "product": "WAIVER ASSISTANT",
        "league_key": league_key,
        "captured_at": CAPTURED.isoformat(),
        "availability_source": "controlled fixture",
        "availability_by_player": {
            "add": "FREE_AGENT",
            "fa_rb": "FREE_AGENT",
            "fa_wr": "FREE_AGENT",
            "fa_te": "WAIVERS",
        },
        "drop_legality": legality(),
        "weeks": [
            {"week": row.week, "playoff": row.playoff, "bye_teams": list(row.bye_teams)}
            for row in weeks()
        ],
        "projections": [
            {
                "player_id": row.player_id,
                "horizon": row.horizon,
                "week": row.week,
                "raw_stats": [],
                "league_points": row.league_points,
                "source": row.source,
                "coverage_status": row.coverage_status,
            }
            for row in complete_projections()
        ],
        "values": [
            {
                "player_id": row.player_id,
                "selected_value": row.selected_value,
                "market_value": row.market_value,
                "raw_projection": row.raw_projection,
                "coverage_status": row.coverage_status,
                "warnings": list(row.warnings),
            }
            for row in complete_values()
        ],
        "news_fresh": news(),
    }
    payload["input_hash"] = stable_hash(payload)
    return payload


class WaiverSearchTests(unittest.TestCase):
    def test_emerging_candidate_below_ordinary_ownership_floor_is_exact(self):
        from tests.test_waiver_emerging_policy import waiver_wire
        from tests.test_waiver_emerging_value import emergence_bundle, scored_snapshot

        snapshot = complete_search_snapshot()
        snapshot = replace(
            snapshot,
            league=replace(
                snapshot.league,
                scoring=scored_snapshot().league.scoring,
            ),
            players=tuple(
                replace(row, fantasypros_id="10")
                if row.player_id == "fa_rb"
                else row
                for row in snapshot.players
            ),
        )
        value_rows = tuple(
            replace(
                row,
                selected_value=5.0,
                market_value=3.0,
                raw_projection=15.0,
            )
            if row.player_id == "fa_rb"
            else row
            for row in complete_values()
        )
        evidence = emergence_bundle()
        ww = waiver_wire()
        pruned = search(
            enable_pruning=True,
            snapshot=snapshot,
            value_rows=value_rows,
            role_evidence=evidence,
            waiver_wire_evidence=ww,
        )
        exhaustive = search(
            enable_pruning=False,
            snapshot=snapshot,
            value_rows=value_rows,
            role_evidence=evidence,
            waiver_wire_evidence=ww,
        )
        emerging = next(
            row for row in pruned.exact_evaluations if row.add_player_id == "fa_rb"
        )
        self.assertEqual(emerging.decision.decision_path, "EMERGING_UPSIDE")
        self.assertEqual(emerging.decision_label, "ADD NOW")
        self.assertFalse(
            any(row.player_id == "fa_rb" for row in pruned.pruned_candidates)
        )
        self.assertEqual(pruned.best_add_player_id, exhaustive.best_add_player_id)
        self.assertEqual(pruned.best_drop_player_id, exhaustive.best_drop_player_id)
        self.assertEqual(pruned.recommended_action, exhaustive.recommended_action)

        self.assertEqual(pruned.no_action.selected, exhaustive.no_action.selected)
        report = format_waiver_search(
            SimpleNamespace(
                search=pruned,
                refresh=SimpleNamespace(snapshot=snapshot),
                output_path=Path("controlled-search.json"),
            )
        )
        self.assertIn("BEST MOVE", report)
        self.assertIn("The upside case is strong enough", report)
        self.assertNotIn("EMERGING_UPSIDE", report)
        self.assertNotIn("reversal conditions", report.lower())

    def test_emerging_protected_drop_search_preserves_no_action(self):
        from tests.test_waiver_emerging_policy import waiver_wire
        from tests.test_waiver_emerging_value import emergence_bundle

        snapshot = complete_search_snapshot()
        snapshot = replace(
            snapshot,
            players=tuple(
                replace(row, fantasypros_id="10")
                if row.player_id == "fa_rb"
                else row
                for row in snapshot.players
            ),
        )
        evidence = emergence_bundle(drop="bench")
        pruned = search(
            enable_pruning=True,
            snapshot=snapshot,
            value_rows=complete_values(candidates_negative=True),
            role_evidence=evidence,
            waiver_wire_evidence=waiver_wire(),
        )
        exhaustive = search(
            enable_pruning=False,
            snapshot=snapshot,
            value_rows=complete_values(candidates_negative=True),
            role_evidence=evidence,
            waiver_wire_evidence=waiver_wire(),
        )
        self.assertTrue(pruned.no_action.selected)
        self.assertTrue(exhaustive.no_action.selected)
        self.assertEqual(pruned.recommended_action, exhaustive.recommended_action)

    def test_contingency_add_candidates_are_exact_and_remain_visible(self):
        scenario = ContingencyScenarioInput(
            beneficiary_player_id="fa_rb",
            unavailable_teammate_player_id="other",
            relationship="AMBIGUOUS_COMMITTEE",
            evidence_source="controlled fixture",
            evidence_captured_at=NOW,
            relationship_status="AMBIGUOUS",
            projections=(),
            strongest_uncertainty="Committee successor is unresolved",
        )
        result = search(enable_pruning=True, contingencies=(scenario,))
        self.assertTrue(result.pruning_enabled)
        self.assertTrue(
            any("contingency beneficiaries" in row for row in result.warnings)
        )
        evaluated = next(
            row for row in result.exact_evaluations if row.add_player_id == "fa_rb"
        )
        self.assertEqual(
            evaluated.candidates[0].contingency.add.evidence_status,
            "AMBIGUOUS",
        )

    def special_team_search(self, *, current_rank=1):
        snapshot = complete_search_snapshot(open_slot=True)
        kicker = player("fa_k", "Free Kicker", "K", "KKK")
        snapshot = replace(
            snapshot,
            league=replace(
                snapshot.league,
                roster_positions=(*snapshot.league.roster_positions[:-1], "K"),
            ),
            players=(*snapshot.players, kicker),
            acquisitions=(
                *snapshot.acquisitions,
                PlayerAcquisition("fa_k", "FREE_AGENT", None, (), ("fixture",)),
            ),
        )
        projection_rows = (
            *complete_projections(),
            Projection("fa_k", "WEEKLY", 1, (), 30.0, "fixture"),
            Projection("fa_k", "WEEKLY", 2, (), 0.0, "fixture"),
            Projection("fa_k", "WEEKLY", 3, (), 0.0, "fixture"),
        )
        value_rows = (
            *complete_values(),
            PlayerValueInput(
                "fa_k",
                0.0,
                0.0,
                30.0,
                current_week_position_rank=current_rank,
            ),
        )
        return search_waiver_candidates(
            snapshot,
            weeks=weeks(),
            projections=projection_rows,
            values=value_rows,
            drop_legality=legality(),
            news_fresh={**news(), "fa_k": True},
            input_bundle_hash="special-team-controlled-bundle",
            availability_source="controlled fixture",
            policy=load_waiver_policy(POLICY_PATH),
            enable_pruning=True,
            now=NOW,
        )

    def test_search_includes_kicker_and_evaluates_it_exactly_before_pruning(self):
        result = self.special_team_search()
        self.assertIn("fa_k", result.eligible_candidate_ids)
        self.assertEqual(result.best_add_player_id, "fa_k")
        self.assertEqual(result.best_decision_label, "ADD NOW")
        self.assertTrue(result.pruning_enabled)
        self.assertTrue(
            any(row.add_player_id == "fa_k" for row in result.exact_evaluations)
        )
        self.assertTrue(any("K/DST" in warning for warning in result.warnings))

    def test_search_omits_special_team_without_authoritative_weekly_rank(self):
        result = self.special_team_search(current_rank=None)
        self.assertNotIn("fa_k", result.eligible_candidate_ids)
        omission = next(row for row in result.omissions if row.player_id == "fa_k")
        self.assertEqual(omission.reason, "CURRENT_WEEK_POSITION_RANK_UNAVAILABLE")

    def test_dst_streams_are_exact_and_owned_defenses_are_excluded(self):
        snapshot = complete_search_snapshot()
        roster_dst = player("JAX", "Jacksonville Jaguars", "DST", "JAX")
        tampa_dst = player("TB", "Tampa Bay Buccaneers", "DST", "TB")
        san_francisco_dst = player("SF", "San Francisco 49ers", "DST", "SF")
        owned_dst = player("DEN", "Denver Broncos", "DST", "DEN")
        other_roster_id = next(
            team.roster_id
            for team in snapshot.teams
            if team.roster_id != snapshot.user_roster_id
        )
        snapshot = replace(
            snapshot,
            league=replace(
                snapshot.league,
                roster_positions=(*snapshot.league.roster_positions, "DEF"),
            ),
            teams=tuple(
                replace(team, player_ids=(*team.player_ids, "JAX"))
                if team.roster_id == snapshot.user_roster_id
                else replace(team, player_ids=(*team.player_ids, "DEN"))
                if team.roster_id == other_roster_id
                else team
                for team in snapshot.teams
            ),
            players=(
                *snapshot.players,
                roster_dst,
                tampa_dst,
                san_francisco_dst,
                owned_dst,
            ),
            owner_by_player=tuple(
                sorted(
                    (
                        *snapshot.owner_by_player,
                        ("JAX", snapshot.user_roster_id),
                        ("DEN", other_roster_id),
                    )
                )
            ),
            acquisitions=(
                *snapshot.acquisitions,
                PlayerAcquisition("JAX", "LOCKED", snapshot.user_roster_id, (), ("fixture",)),
                PlayerAcquisition("TB", "FREE_AGENT", None, (), ("fixture",)),
                PlayerAcquisition("SF", "WAIVERS", None, (), ("fixture",)),
                PlayerAcquisition("DEN", "LOCKED", other_roster_id, (), ("fixture",)),
            ),
        )
        special_projections = tuple(
            Projection(player_id, "WEEKLY", week, (), points, "fixture")
            for player_id, weekly in {
                "JAX": (2.0, 7.0, 7.0),
                "TB": (10.0, 6.0, 6.0),
                "SF": (9.0, 6.0, 6.0),
            }.items()
            for week, points in enumerate(weekly, start=1)
        )
        result = search_waiver_candidates(
            snapshot,
            weeks=weeks(),
            projections=(*complete_projections(), *special_projections),
            values=(
                *complete_values(candidates_negative=True),
                PlayerValueInput("JAX", 0.0, 0.0, 16.0, current_week_position_rank=11, rest_of_season_position_rank=15),
                PlayerValueInput("TB", 0.0, 0.0, 22.0, current_week_position_rank=2, rest_of_season_position_rank=10),
                PlayerValueInput("SF", 0.0, 0.0, 21.0, current_week_position_rank=3, rest_of_season_position_rank=11),
            ),
            drop_legality={**legality(), "JAX": True},
            news_fresh={**news(), "TB": True, "SF": True},
            input_bundle_hash="dst-stream-controlled-bundle",
            availability_source="controlled fixture",
            policy=load_waiver_policy(POLICY_PATH),
            enable_pruning=True,
            now=NOW,
        )

        self.assertEqual(result.best_add_player_id, "TB")
        self.assertEqual(result.best_drop_player_id, "JAX")
        self.assertEqual(result.best_decision_label, "ADD NOW")
        self.assertTrue(
            {"TB", "SF"}.issubset(
                {row.add_player_id for row in result.exact_evaluations}
            )
        )
        self.assertNotIn("DEN", result.eligible_candidate_ids)
        best = next(row for row in result.exact_evaluations if row.add_player_id == "TB")
        self.assertEqual(best.candidates[0].current_week_add_points, 10.0)
        self.assertEqual(best.candidates[0].current_week_drop_points, 2.0)
        report = format_waiver_search(
            SimpleNamespace(
                search=result,
                refresh=SimpleNamespace(snapshot=snapshot),
                output_path=Path("controlled-dst-search.json"),
            )
        )
        self.assertIn("Tampa Bay Buccaneers", report)
        self.assertIn("10.00 pts", report)
        self.assertIn("+8.00 vs Jacksonville Jaguars", report)
        self.assertIn("DST2", report)
        self.assertIn("DEFENSE STREAMERS", report)
        self.assertIn("San Francisco 49ers", report)

    def test_missing_incumbent_special_projection_does_not_block_skill_search(self):
        snapshot = complete_search_snapshot()
        roster_k = player("roster_k", "Roster Kicker", "K", "LAC")
        free_k = player("free_k", "Free Kicker", "K", "NYJ")
        snapshot = replace(
            snapshot,
            league=replace(
                snapshot.league,
                roster_positions=(*snapshot.league.roster_positions, "K"),
            ),
            teams=tuple(
                replace(team, player_ids=(*team.player_ids, "roster_k"))
                if team.roster_id == snapshot.user_roster_id
                else team
                for team in snapshot.teams
            ),
            players=(*snapshot.players, roster_k, free_k),
            owner_by_player=tuple(sorted((*snapshot.owner_by_player, ("roster_k", "1")))),
            acquisitions=(
                *snapshot.acquisitions,
                PlayerAcquisition("roster_k", "LOCKED", "1", (), ("fixture",)),
                PlayerAcquisition("free_k", "FREE_AGENT", None, (), ("fixture",)),
            ),
        )
        result = search_waiver_candidates(
            snapshot,
            weeks=weeks(),
            projections=(
                *complete_projections(),
                *(
                    Projection("free_k", "WEEKLY", week, (), 8.0, "fixture")
                    for week in (1, 2, 3)
                ),
            ),
            values=(
                *complete_values(),
                PlayerValueInput("roster_k", 0.0, 0.0, 0.0),
                PlayerValueInput(
                    "free_k",
                    0.0,
                    0.0,
                    24.0,
                    current_week_position_rank=5,
                ),
            ),
            drop_legality={**legality(), "roster_k": True},
            news_fresh={**news(), "free_k": True},
            input_bundle_hash="missing-incumbent-special-projection",
            availability_source="controlled fixture",
            policy=load_waiver_policy(POLICY_PATH),
            enable_pruning=True,
            now=NOW,
        )
        self.assertNotIn("free_k", result.eligible_candidate_ids)
        omission = next(row for row in result.omissions if row.player_id == "free_k")
        self.assertEqual(omission.reason, "ROSTER_POSITION_PROJECTION_UNAVAILABLE")
        self.assertTrue(
            {"add", "fa_rb", "fa_wr", "fa_te"}.issubset(
                result.eligible_candidate_ids
            )
        )

    def test_exhaustive_search_covers_every_skill_position_and_legal_drop(self):
        result = search()
        self.assertEqual(result.schema_version, 8)
        self.assertEqual(result.evaluation_schema_version, 11)
        self.assertEqual(
            set(result.eligible_candidate_ids), {"add", "fa_rb", "fa_wr", "fa_te"}
        )
        player_by_id = {
            row.player_id: row for row in complete_search_snapshot().players
        }
        self.assertEqual(
            {
                next(iter(player_by_id[player_id].positions))
                for player_id in result.eligible_candidate_ids
            },
            {"QB", "RB", "WR", "TE"},
        )
        self.assertEqual(len(result.exact_evaluations), 4)
        self.assertFalse(result.pruned_candidates)
        for evaluation in result.exact_evaluations:
            self.assertEqual(
                {row.drop_player_id for row in evaluation.candidates},
                {"rb", "wr", "bench"},
            )
        self.assertEqual(result.best_add_player_id, "add")
        self.assertEqual(result.recommended_action, "MOVE")

    def test_emergence_bundle_is_preserved_without_changing_search_policy(self):
        baseline = search()
        role_evidence = emergence_evidence()
        result = search(role_evidence=role_evidence)
        self.assertEqual(result.emergence_evidence, role_evidence)
        self.assertEqual(result.best_add_player_id, baseline.best_add_player_id)
        self.assertEqual(result.best_decision_label, baseline.best_decision_label)
        self.assertFalse(result.sleeper_write_performed)
        self.assertFalse(result.no_action.selected)
        self.assertFalse(result.sleeper_write_performed)

    def test_verified_bye_zero_counts_as_complete_projection_coverage(self):
        projection_rows = tuple(
            replace(row, coverage_status="verified_bye_zero")
            if row.player_id == "add" and row.week == 2
            else row
            for row in complete_projections()
        )
        result = search(projection_rows=projection_rows)
        self.assertIn("add", result.eligible_candidate_ids)

    def test_top_waiver_candidate_with_missing_value_is_explained(self):
        result = search(
            value_rows=tuple(
                row for row in complete_values() if row.player_id != "add"
            ),
            waiver_wire_evidence=waiver_wire_evidence(),
        )
        notable = next(
            row for row in result.notable_candidates if row.player_id == "add"
        )
        self.assertEqual(notable.category, "MISSING_EVIDENCE")
        self.assertEqual(notable.waiver_wire_market_rank, 2)
        self.assertIn("rest-of-season value is missing", notable.reason)

    def test_top_waiver_candidate_just_outside_value_board_retains_ranks(self):
        value_rows = tuple(
            replace(
                row,
                coverage_status="incomplete",
                current_week_position_rank=38,
                rest_of_season_position_rank=51,
                warnings=(
                    "Ranked Waiver candidate is outside complete selected/market "
                    "value-board coverage; retained for visibility only",
                ),
            )
            if row.player_id == "add"
            else row
            for row in complete_values()
        )
        result = search(
            value_rows=value_rows,
            waiver_wire_evidence=waiver_wire_evidence(),
        )
        notable = next(
            row for row in result.notable_candidates if row.player_id == "add"
        )
        self.assertEqual(notable.category, "MISSING_EVIDENCE")
        self.assertEqual(notable.current_week_position_rank, 38)
        self.assertEqual(notable.rest_of_season_position_rank, 51)
        self.assertIn("retained for visibility", notable.reason)
        self.assertNotIn("add", result.eligible_candidate_ids)
        self.assertEqual(result.recommended_action, "NO ACTION")
        self.assertTrue(result.no_action.selected)
        report = format_waiver_search(
            SimpleNamespace(
                search=result,
                refresh=SimpleNamespace(snapshot=complete_search_snapshot()),
                output_path=Path("controlled-no-action.json"),
            )
        )
        self.assertIn("BEST IDEA", report)
        self.assertIn("HOLD FOR NOW", report)
        self.assertIn("OTHER PLAYERS TO WATCH", report)
        self.assertNotIn("policy:", report.lower())
        self.assertNotIn("pruning", report.lower())

    def test_ranked_but_pruned_candidate_has_roster_comparison(self):
        value_rows = tuple(
            replace(
                row,
                selected_value=-100.0,
                market_value=-100.0,
                current_week_position_rank=42,
                rest_of_season_position_rank=49,
            )
            if row.player_id == "fa_wr"
            else replace(row, current_week_position_rank=47)
            if row.player_id == "wr"
            else row
            for row in complete_values()
        )
        result = search(enable_pruning=True, value_rows=value_rows)
        notable = next(
            row for row in result.notable_candidates if row.player_id == "fa_wr"
        )
        self.assertEqual(notable.category, "BELOW_THRESHOLD")
        self.assertIn("ahead of Roster Receiver WR47", notable.roster_comparison)
        report = format_waiver_search(
            SimpleNamespace(
                search=result,
                refresh=SimpleNamespace(snapshot=complete_search_snapshot()),
                output_path=Path("controlled-search.json"),
            )
        )
        self.assertIn("OTHER PLAYERS TO WATCH", report)
        self.assertIn("Free Receiver", report)
        self.assertIn("WR III", report)
        self.assertIn("not enough of an upgrade", report)

    def test_current_week_ir_roster_omission_is_reconciled_from_fresh_snapshot(self):
        snapshot = complete_search_snapshot()
        snapshot = replace(
            snapshot,
            players=tuple(
                replace(row, injury_status="IR") if row.player_id == "wr" else row
                for row in snapshot.players
            ),
        )
        projection_rows = tuple(
            replace(row, league_points=0.0, raw_stats=(),
                    source="FantasyPros source omission",
                    coverage_status="source_omission_zero")
            if row.player_id == "wr" and row.week == 1 else row
            for row in complete_projections()
        )
        reconciled = reconcile_current_week_inactive_omissions(snapshot, projection_rows)
        current = next(row for row in reconciled if row.player_id == "wr" and row.week == 1)
        self.assertEqual(current.coverage_status, "known_inactive_zero")
        self.assertIn("Sleeper IR", current.source)
        self.assertEqual(
            next(row for row in reconciled if row.player_id == "wr" and row.week == 2).coverage_status,
            "complete",
        )
        wr = next(row for row in snapshot.players if row.player_id == "wr")
        matrix = build_weekly_projection_matrix(
            InSeasonContext(
                (wr,), snapshot.league.roster_positions, weeks(), (),
                current_status_week_only=True,
            ),
            reconciled,
        )
        self.assertEqual(matrix.cell("wr", 1).points, 0.0)
        self.assertEqual(matrix.cell("wr", 2).points, 9.0)
        self.assertTrue(any(
            "future availability is unverified" in warning
            for warning in matrix.cell("wr", 2).warnings
        ))
        self.assertFalse(search(snapshot=snapshot, projection_rows=projection_rows).sleeper_write_performed)

    def test_healthy_and_future_week_source_omissions_still_fail_closed(self):
        snapshot = complete_search_snapshot()
        injured = replace(
            snapshot,
            players=tuple(
                replace(row, injury_status="IR") if row.player_id == "wr" else row
                for row in snapshot.players
            ),
        )
        for week, selected_snapshot in ((1, snapshot), (2, injured)):
            projection_rows = tuple(
                replace(row, league_points=0.0, raw_stats=(),
                        source="FantasyPros source omission",
                        coverage_status="source_omission_zero")
                if row.player_id == "wr" and row.week == week else row
                for row in complete_projections()
            )
            with self.subTest(week=week):
                with self.assertRaisesRegex(CoverageIncomplete, f"wr/W{week}"):
                    search(snapshot=selected_snapshot, projection_rows=projection_rows)

    def test_safe_pruning_retains_the_same_best_move_as_exhaustive_search(self):
        projection_rows = complete_projections(prunable=True)
        exhaustive = search(projection_rows=projection_rows)
        pruned = search(enable_pruning=True, projection_rows=projection_rows)
        self.assertEqual(pruned.best_add_player_id, exhaustive.best_add_player_id)
        self.assertEqual(pruned.best_drop_player_id, exhaustive.best_drop_player_id)
        self.assertEqual(pruned.best_decision_label, exhaustive.best_decision_label)
        self.assertLess(len(pruned.exact_evaluations), len(exhaustive.exact_evaluations))
        self.assertEqual(
            len(pruned.exact_evaluations) + len(pruned.pruned_candidates),
            len(pruned.eligible_candidate_ids),
        )
        incumbent = pruned.exact_evaluations[0].candidates[0]
        self.assertTrue(
            all(
                row.maximum_after_weighted_points
                < incumbent.lineup.after_weighted_points
                for row in pruned.pruned_candidates
            )
        )

    def test_stale_draft_values_cannot_prune_fresh_same_position_dominance(self):
        projection_rows = tuple(
            replace(row, league_points=11.0)
            if row.player_id == "fa_rb"
            else row
            for row in complete_projections()
        )
        value_rows = []
        for row in complete_values(candidates_negative=True):
            if row.player_id == "fa_rb":
                value_rows.append(
                    replace(
                        row,
                        selected_value=-3.0,
                        market_value=-3.0,
                        raw_projection=31.0,
                        current_week_position_rank=32,
                        rest_of_season_position_rank=37,
                        long_term_value_horizon="EARLY_SEASON_DRAFT_ANCHOR",
                    )
                )
            elif row.player_id == "rb":
                value_rows.append(
                    replace(
                        row,
                        selected_value=0.0,
                        market_value=0.0,
                        raw_projection=30.0,
                        current_week_position_rank=42,
                        rest_of_season_position_rank=41,
                        long_term_value_horizon="EARLY_SEASON_DRAFT_ANCHOR",
                    )
                )
            else:
                value_rows.append(row)

        exhaustive = search(
            projection_rows=projection_rows,
            value_rows=tuple(value_rows),
        )
        pruned = search(
            enable_pruning=True,
            projection_rows=projection_rows,
            value_rows=tuple(value_rows),
        )

        self.assertEqual(pruned.recommended_action, "MOVE")
        self.assertEqual(pruned.best_add_player_id, "fa_rb")
        self.assertEqual(pruned.best_drop_player_id, "rb")
        self.assertEqual(pruned.best_decision_label, "ADD NOW")
        selected = pruned.exact_evaluations[0].candidates[0]
        self.assertTrue(selected.ownership.fresh_rank_dominance)
        self.assertEqual(
            pruned.exact_evaluations[0].decision.decision_path,
            "FRESH_RANK_DOMINANCE",
        )
        self.assertFalse(
            any(row.player_id == "fa_rb" for row in pruned.pruned_candidates)
        )
        self.assertEqual(pruned.best_add_player_id, exhaustive.best_add_player_id)
        self.assertEqual(pruned.best_drop_player_id, exhaustive.best_drop_player_id)
        self.assertEqual(pruned.recommended_action, exhaustive.recommended_action)

        current_ros_values = tuple(
            replace(row, long_term_value_horizon="ROS")
            if row.player_id in {"fa_rb", "rb"}
            else row
            for row in value_rows
        )
        current_ros = search(
            enable_pruning=True,
            projection_rows=projection_rows,
            value_rows=current_ros_values,
        )
        self.assertEqual(current_ros.recommended_action, "NO ACTION")

    def test_pruning_preserves_required_no_action_proof(self):
        exhaustive = search(value_rows=complete_values(candidates_negative=True))
        pruned = search(
            enable_pruning=True,
            value_rows=complete_values(candidates_negative=True),
        )
        self.assertEqual(exhaustive.recommended_action, "NO ACTION")
        self.assertEqual(pruned.recommended_action, exhaustive.recommended_action)
        self.assertEqual(pruned.best_add_player_id, exhaustive.best_add_player_id)
        self.assertEqual(pruned.best_drop_player_id, exhaustive.best_drop_player_id)
        self.assertGreater(len(pruned.pruned_candidates), 0)
        self.assertEqual(
            len(pruned.exact_evaluations) + len(pruned.pruned_candidates),
            len(pruned.eligible_candidate_ids),
        )
        self.assertTrue(
            any(
                "OWNERSHIP_UPPER_BOUND_BELOW_WATCH_FLOORS" in row.reason
                for row in pruned.pruned_candidates
            )
        )

    def test_one_qb_candidates_are_exact_before_ordinary_pruning(self):
        projection_rows = tuple(
            replace(row, league_points=18.0) if row.player_id == "add" else row
            for row in complete_projections()
        )
        result = search(enable_pruning=True, projection_rows=projection_rows)
        self.assertTrue(result.pruning_enabled)
        self.assertTrue(
            any(row.add_player_id == "add" for row in result.exact_evaluations)
        )
        self.assertEqual(
            len(result.exact_evaluations) + len(result.pruned_candidates),
            len(result.eligible_candidate_ids),
        )
        self.assertTrue(any("QB-hold" in warning for warning in result.warnings))

    def test_open_slot_uses_no_drop_and_passes_select_no_action(self):
        open_result = search(snapshot=complete_search_snapshot(open_slot=True))
        self.assertTrue(
            all(
                evaluation.selected_drop_player_id is None
                and len(evaluation.candidates) == 1
                for evaluation in open_result.exact_evaluations
            )
        )
        pass_result = search(value_rows=complete_values(candidates_negative=True))
        self.assertEqual(pass_result.recommended_action, "NO ACTION")
        self.assertTrue(pass_result.no_action.selected)
        self.assertNotIn(
            pass_result.best_decision_label, {"ADD NOW", "CLAIM"}
        )

    def test_no_eligible_player_returns_no_action_without_drop_search(self):
        snapshot = complete_search_snapshot()
        snapshot = replace(
            snapshot,
            acquisitions=tuple(
                replace(row, state="LOCKED", owner_roster_id="2")
                if row.state in {"FREE_AGENT", "WAIVERS"}
                else row
                for row in snapshot.acquisitions
            ),
        )
        result = search_waiver_candidates(
            snapshot,
            weeks=weeks(),
            projections=complete_projections(),
            values=complete_values(),
            drop_legality={},
            news_fresh={},
            input_bundle_hash="controlled-bundle-hash",
            availability_source="controlled fixture",
            policy=load_waiver_policy(POLICY_PATH),
            now=NOW,
        )
        self.assertEqual(result.eligible_candidate_ids, ())
        self.assertEqual(result.exact_evaluations, ())
        self.assertEqual(result.recommended_action, "NO ACTION")
        self.assertTrue(result.no_action.selected)

    def test_incomplete_candidate_evidence_is_omitted_and_stale_bundle_fails(self):
        partial = search_waiver_candidates(
            complete_search_snapshot(),
            weeks=weeks(),
            projections=complete_projections(),
            values=complete_values(),
            drop_legality=legality(),
            news_fresh={"add": True},
            input_bundle_hash="controlled-bundle-hash",
            availability_source="controlled fixture",
            policy=load_waiver_policy(POLICY_PATH),
            now=NOW,
        )
        self.assertEqual(partial.eligible_candidate_ids, ("add",))
        self.assertEqual(
            {
                row.player_id
                for row in partial.omissions
                if row.reason == "MATERIAL_NEWS_NOT_FRESH"
            },
            {"fa_rb", "fa_te", "fa_wr"},
        )
        with self.assertRaisesRegex(StaleData, "freshness"):
            search_waiver_candidates(
                complete_search_snapshot(),
                weeks=weeks(),
                projections=complete_projections(),
                values=complete_values(),
                drop_legality=legality(),
                news_fresh=news(),
                input_bundle_hash="controlled-bundle-hash",
                availability_source="controlled fixture",
                policy=load_waiver_policy(POLICY_PATH),
                now=NOW + timedelta(hours=1),
            )

    def test_saved_search_replays_and_rejects_tampering(self):
        result = search()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "search.json"
            save_waiver_search(result, path)
            replay = load_waiver_search(path)
            self.assertTrue(replay["offline_replay"])
            self.assertFalse(replay["current"])
            raw = json.loads(path.read_text(encoding="utf-8"))
            raw["best_add_player_id"] = "tampered"
            path.write_text(json.dumps(raw), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "hash verification"):
                load_waiver_search(path)


class WaiverSearchServiceAndCliTests(unittest.TestCase):
    def test_search_parser_is_namespaced_and_read_only(self):
        for league_key in ("league_alpha", "league_beta"):
            with self.subTest(league_key=league_key):
                args = build_parser().parse_args(
                    ["waiver", "search", league_key, "--inputs", "inputs.json"]
                )
                self.assertIs(args.func, command_waiver_search)
                self.assertIsNone(args.policy)
                self.assertFalse(hasattr(args, "bid"))

    def test_league_beta_search_uses_its_default_policy(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inputs_path = root / "inputs.json"
            output_path = root / "search.json"
            payload = input_payload(league_key="league_beta")
            inputs_path.write_text(json.dumps(payload), encoding="utf-8")
            refresh = WaiverRefreshResult(
                snapshot=complete_search_snapshot(league_key="league_beta"),
                call_plan=waiver_refresh_plan("league-1", 1, player_cache_hit=True),
                output_path=root / "snapshot.json",
            )
            with patch(
                "roster_theory.waiver.service.refresh_waiver_snapshot",
                return_value=refresh,
            ):
                result = search_waivers(
                    "league_beta",
                    inputs_path=inputs_path,
                    output_path=output_path,
                    policy_path=(
                        POLICY_PATH.parent / "league_beta.decision-policy.json"
                    ),
                    now=NOW,
                    enable_pruning=False,
                )
        self.assertEqual(result.search.league_key, "league_beta")
        self.assertEqual(
            result.search.policy_version,
            "test-league-beta-emerging-upside-v1",
        )
        self.assertIn(
            result.search.best_decision_label,
            {"ADD NOW", "CLAIM", "ACQUIRE", "WATCH", "PASS"},
        )
        self.assertFalse(result.search.sleeper_write_performed)

    def test_service_saves_search_evidence_and_formats_coverage(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inputs_path = root / "inputs.json"
            output_path = root / "search.json"
            inputs_path.write_text(json.dumps(input_payload()), encoding="utf-8")
            refresh = WaiverRefreshResult(
                snapshot=complete_search_snapshot(),
                call_plan=waiver_refresh_plan("league-1", 1, player_cache_hit=True),
                output_path=root / "snapshot.json",
            )
            with patch(
                "roster_theory.waiver.service.refresh_waiver_snapshot",
                return_value=refresh,
            ):
                result = search_waivers(
                    "league_alpha",
                    inputs_path=inputs_path,
                    output_path=output_path,
                    policy_path=POLICY_PATH,
                    now=NOW,
                    enable_pruning=False,
                )
            self.assertTrue(output_path.is_file())
            self.assertEqual(result.search.input_bundle_hash, input_payload()["input_hash"])
            machine_report = waiver_search_report(result)
            json.dumps(machine_report, allow_nan=False)
            self.assertIsInstance(
                machine_report["exact_evaluations"][0]["evaluated_at"], str
            )
            report = format_waiver_search(result)
            self.assertEqual(
                waiver_search_action_summary(result),
                "ADD NOW: add Target Quarterback; drop Bench Receiver",
            )
            self.assertIn("BEST MOVE", report)
            self.assertIn("projected lineup change", report)
            self.assertIn("No bid or claim-success probability is predicted", report)
            self.assertNotIn("Eligible players", report)
            self.assertNotIn("exact evaluations", report)
            self.assertNotIn(result.search.policy_version, report)
            self.assertIn("eligible_candidate_ids", machine_report)
            self.assertIn("policy_version", machine_report)
            report.encode("ascii")


if __name__ == "__main__":
    unittest.main()
