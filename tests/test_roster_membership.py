"""Independent membership facts, admission and saved-evidence compatibility."""
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest

from roster_theory.core.errors import RosterIllegal
from roster_theory.core.models import FantasyTeam, LeagueRules, Player
from roster_theory.core.provenance import canonical_json
from roster_theory.core.roster import assess_membership, require_membership
from roster_theory.core.run_contract import restore_record
from roster_theory.providers.sleeper import normalize_teams, normalize_league
from roster_theory.providers.sleeper_membership import reserve_eligibility, require_draft_snapshot_membership
from roster_theory.mock_watcher import reconcile_draft_state
from roster_theory.trade.snapshot import assert_current as trade_current, load_trade_snapshot, save_trade_snapshot
from roster_theory.trade.evaluation import evaluate_trade, build_entered_package
from roster_theory.waiver.snapshot import assert_current as waiver_current, load_waiver_snapshot, save_waiver_snapshot, _capacity
from tests.test_trade_evaluation import snapshot_fixture
from tests.test_trade_evaluation import projection_fixture, board_fixture
from tests.test_waiver_evaluation import waiver_snapshot, NOW
from tests.test_waiver_evaluation import weeks, projections, values, legality
from roster_theory.waiver.evaluation import evaluate_waiver
from tests.ma001_fixtures import PROFILES, reference_fixture


class RosterMembershipTests(unittest.TestCase):
    def setUp(self):
        self.rules = LeagueRules("fixture", 2026, 2, ("QB", "RB", "BN"), (), reserve_slots=1, taxi_slots=0)
        self.team = FantasyTeam("1", "owner", "Fixture", ("qb", "rb", "ir"), ("qb", "rb"), ("ir",))

    def test_taxi_survives_provider_normalization_and_never_counts_as_active(self):
        team = normalize_teams([], [{"roster_id": 1, "players": ["qb", "ir", "taxi"],
            "starters": ["qb", "0"], "reserve": ["ir"], "taxi": ["taxi"]}])[0]
        self.assertEqual(team.taxi_ids, ("taxi",))
        result = assess_membership(self.rules, (team,))
        self.assertEqual(result.rosters[0].active_ids, ("qb",))
        self.assertEqual(result.rosters[0].open_active_slots, 2)
        self.assertIn("TAXI_UNSUPPORTED", {row.code for row in result.issues})
        self.assertFalse(result.complete)

    def test_missing_taxi_field_requires_explicit_zero_capacity(self):
        team = normalize_teams([], [{"roster_id": 1, "players": [], "starters": [], "reserve": None}])[0]
        self.assertIsNone(team.taxi_ids)
        self.assertTrue(assess_membership(self.rules, (team,)).complete)
        unknown = assess_membership(replace(self.rules, taxi_slots=None), (team,))
        self.assertIsNone(unknown.rosters[0].active_ids)
        self.assertEqual(unknown.issues[0].code, "TAXI_MEMBERSHIP_UNKNOWN")

    def test_null_and_explicit_empty_taxi_are_distinct(self):
        base = {"roster_id": 1, "players": [], "starters": [], "reserve": []}
        self.assertIsNone(normalize_teams([], [{**base, "taxi": None}])[0].taxi_ids)
        self.assertEqual(normalize_teams([], [{**base, "taxi": []}])[0].taxi_ids, ())

    def test_invalid_membership_is_never_silently_deduplicated(self):
        for team, code in (
            (replace(self.team, player_ids=("qb", "qb")), "DUPLICATE_OWNED"),
            (replace(self.team, starter_ids=("qb", "qb")), "DUPLICATE_STARTER"),
            (replace(self.team, reserve_ids=("qb",)), "STARTER_IN_RESERVE"),
            (replace(self.team, reserve_ids=("missing",)), "RESERVE_NOT_OWNED"),
            (replace(self.team, starter_ids=("missing",)), "STARTER_NOT_OWNED"),
            (replace(self.team, taxi_ids=("ir",)), "TAXI_MEMBERSHIP_OVERLAP"),
            (replace(self.team, player_ids=(*self.team.player_ids, "x", "y")), "ACTIVE_CAPACITY_EXCEEDED"),
        ):
            with self.subTest(code=code):
                self.assertIn(code, {row.code for row in assess_membership(self.rules, (team,)).issues})
                with self.assertRaises(RosterIllegal):
                    require_membership(self.rules, (team,))

    def test_duplicate_roster_and_cross_roster_ownership_are_invalid(self):
        result = assess_membership(self.rules, (self.team, self.team))
        self.assertTrue({"DUPLICATE_ROSTER_ID", "DUPLICATE_OWNERSHIP"} <= {row.code for row in result.issues})

    def test_starter_empty_slots_do_not_own_a_fake_player(self):
        result = assess_membership(self.rules, (replace(self.team, starter_ids=("0", "0")),))
        self.assertTrue(result.complete)
        self.assertEqual(result.rosters[0].starter_ids, ())

    def test_non_string_identity_is_reported_without_hiding_the_other_ids(self):
        team = replace(self.team, player_ids=("qb", "rb", "ir", 42))
        result = assess_membership(self.rules, (team,))
        self.assertIn("INVALID_OWNED_IDENTITY", {row.code for row in result.issues})
        self.assertEqual(set(result.rosters[0].owned_ids), {"qb", "rb", "ir", 42})

    def test_malformed_collection_and_missing_required_membership_are_rejected(self):
        base = {"roster_id": 1, "players": ["qb"], "starters": [], "reserve": [], "taxi": []}
        for field in ("players", "starters", "reserve", "taxi"):
            with self.subTest(field=field), self.assertRaises(ValueError):
                normalize_teams([], [{**base, field: "qb"}])
        for field in ("players", "starters", "reserve"):
            with self.subTest(missing=field), self.assertRaises(ValueError):
                normalize_teams([], [{key: value for key, value in base.items() if key != field}])

    def test_capacity_fields_preserve_absence_and_reject_coercion(self):
        base = {"league_id": "fixture", "season": "2026", "total_rosters": 2, "roster_positions": ["QB"]}
        self.assertIsNone(normalize_league(base).taxi_slots)
        for key in ("reserve_slots", "taxi_slots"):
            for value in (-1, 1.9, "1", True):
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    normalize_league({**base, "settings": {key: value}})

    def test_both_reference_profiles_reconcile_independently(self):
        for profile in PROFILES:
            for open_slot in (False, True):
                f = reference_fixture(profile, open_slot=open_slot)
                result = assess_membership(f.bundle.league, f.bundle.teams)
                self.assertTrue(result.complete)
                self.assertEqual(result.rosters[0].active_limit, 15)
                self.assertEqual(len(result.rosters[0].active_ids), 14 if open_slot else 15)
                self.assertEqual(result.rosters[0].open_active_slots, int(open_slot))
                self.assertFalse(reserve_eligibility(f.bundle.league, f.bundle.teams[0], f.bundle.players))

    def test_reserve_rules_distinguish_missing_disabled_and_enabled(self):
        player = Player("ir", "Reserve", ("RB",), injury_status="Out")
        self.assertEqual(reserve_eligibility(self.rules, self.team, (player,))[0].status, "UNKNOWN")
        for flag, expected in ((0, "INVALID"), (1, None), ("1", "UNKNOWN")):
            rules = replace(self.rules, platform_settings=(("reserve_allow_out", flag),))
            issues = reserve_eligibility(rules, self.team, (player,))
            self.assertEqual(issues[0].status if issues else None, expected)
        for status in ("IR", "PUP"):
            self.assertFalse(reserve_eligibility(self.rules, self.team, (replace(player, injury_status=status),)))

    def test_waiver_capacity_does_not_equate_empty_ir_space_with_eligibility(self):
        known = _capacity(self.rules, self.team, (Player("ir", "Reserve", ("RB",), injury_status="IR"),))
        self.assertTrue(known.reserve_legal)
        unknown = _capacity(self.rules, self.team, (Player("ir", "Reserve", ("RB",), injury_status="OUT"),))
        self.assertFalse(unknown.reserve_legality_known)
        self.assertFalse(unknown.reserve_legal)

    def test_three_feature_admission_rejects_taxi(self):
        trade = snapshot_fixture()
        trade = replace(trade, teams=(replace(trade.teams[0], taxi_ids=("a_bench",)), *trade.teams[1:]))
        with self.assertRaisesRegex(RosterIllegal, "TAXI_UNSUPPORTED"):
            trade_current(trade)
        waiver = waiver_snapshot()
        waiver = replace(waiver, teams=(replace(waiver.teams[0], taxi_ids=("bench",)), *waiver.teams[1:]))
        with self.assertRaisesRegex(RosterIllegal, "TAXI_UNSUPPORTED"):
            waiver_current(waiver, now=NOW)
        with self.assertRaisesRegex(RosterIllegal, "taxi"):
            reconcile_draft_state({"settings": {"teams": 10, "rounds": 15, "taxi_slots": 2}}, (), 1)
        with self.assertRaisesRegex(RosterIllegal, "TAXI_UNSUPPORTED"):
            require_draft_snapshot_membership({"current": {"rosters": [{"taxi": ["taxi"]}]}})

    def test_typed_restore_rejects_lost_membership_but_preserves_new_records(self):
        encoded = json.loads(canonical_json(self.team))
        self.assertEqual(restore_record(FantasyTeam, encoded), self.team)
        del encoded["taxi_ids"]
        with self.assertRaisesRegex(ValueError, "refresh"):
            restore_record(FantasyTeam, encoded)
        encoded['taxi_ids'] = ''
        with self.assertRaisesRegex(ValueError, "array"):
            restore_record(FantasyTeam, encoded)

    def test_unknown_reserve_capacity_cannot_pass_trade_legality(self):
        snapshot = snapshot_fixture()
        user, partner = snapshot.teams
        snapshot = replace(snapshot, league=replace(snapshot.league, reserve_slots=None),
            teams=(replace(user, reserve_ids=("a_low",)), partner),
            players=tuple(replace(player, injury_status="IR") if player.player_id == "a_low" else player
                          for player in snapshot.players))
        result = evaluate_trade(snapshot, build_entered_package(snapshot, send=("a_wr",), receive=("b_rb",)),
            projections=projection_fixture(), selected_board=board_fixture(snapshot, "selected"),
            market_board=board_fixture(snapshot, "market"))
        self.assertIn("MANUAL-LEGALITY", result.modes)
        self.assertFalse(next(row.passed for row in result.decision.gates if row.name == "complete_evidence"))
        self.assertTrue(any("RESERVE_CAPACITY_UNKNOWN" in warning for warning in result.warnings))

    def test_waiver_rechecks_reserve_status_even_if_saved_capacity_was_legal(self):
        snapshot = waiver_snapshot()
        for status, code in (("Healthy", "RESERVE_INELIGIBLE"), ("Out", "RESERVE_ELIGIBILITY_UNKNOWN")):
            changed = replace(snapshot, players=tuple(replace(player, injury_status=status)
                if player.player_id == "ir" else player for player in snapshot.players))
            with self.subTest(status=status), self.assertRaisesRegex(RosterIllegal, code):
                evaluate_waiver(changed, add="Target Quarterback", weeks=weeks(), projections=projections(),
                    values=values(), drop_legality=legality(), news_fresh={"add": True}, now=NOW)

    def test_snapshot_readers_preserve_membership_and_reject_legacy_or_future_schema(self):
        for snapshot, save, load in ((snapshot_fixture(), save_trade_snapshot, load_trade_snapshot),
                                     (waiver_snapshot(), save_waiver_snapshot, load_waiver_snapshot)):
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "snapshot.json"
                save(snapshot, path)
                self.assertEqual(load(path).teams, snapshot.teams)
                encoded = json.loads(path.read_text())
                del encoded["teams"][0]["taxi_ids"]
                path.write_text(json.dumps(encoded))
                with self.assertRaisesRegex(ValueError, "refresh"):
                    load(path)
                encoded["schema_version"] = 999
                path.write_text(json.dumps(encoded))
                with self.assertRaisesRegex(ValueError, "schema"):
                    load(path)
