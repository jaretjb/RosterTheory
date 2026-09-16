import csv
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from roster_theory.grouped_rankings import (
    SelectedExpert,
    _available_experts,
    _consensus_params,
    _scope_available_experts,
    assign_cohort_weights,
    coverage_factor,
    export_grouped_rankings,
    filter_recent_experts,
    load_historical_experts,
    load_expert_pool_overrides,
    load_recency_historical_experts,
    parse_fantasypros_expert_picker,
    select_available_experts,
)

FIXTURES = Path(__file__).parent / "fixtures" / "provider"


class GroupedRankingsTests(unittest.TestCase):
    def test_all_cross_position_feed_requires_explicit_draft_type(self) -> None:
        self.assertEqual(
            _consensus_params("ALL", "HALF", experts="show"),
            {
                "position": "ALL",
                "scoring": "HALF",
                "experts": "show",
                "type": "DRAFT",
            },
        )
        self.assertNotIn("type", _consensus_params("RB", "HALF"))

    def test_two_year_coverage_factor_is_88_percent(self) -> None:
        self.assertAlmostEqual(coverage_factor(2), 0.88)
        self.assertAlmostEqual(coverage_factor(5), 1.0)

    def test_overall_recency_master_uses_agreed_weights_and_gate(self) -> None:
        experts = load_recency_historical_experts(
            FIXTURES / "expert_accuracy.synthetic.csv",
            FIXTURES / "expert_accuracy_annual.synthetic.csv",
        )

        self.assertEqual(experts[0].name, "Expert 01")
        self.assertEqual(experts[0].score_method, "recency_8_15_21_26_30")
        self.assertEqual(dict(experts[0].annual_ranks)[2025], 1)
        self.assertTrue(all(expert.years >= 3 for expert in experts))

    def test_selects_top_available_overall_experts_then_weights_cohorts(self) -> None:
        historical = load_historical_experts(
            FIXTURES / "expert_accuracy.synthetic.csv", "OVERALL"
        )
        available = {
            index: {"name": expert.name, "last_updated": "2026-08-23"}
            for index, expert in enumerate(historical[5:30], start=1000)
        }

        selected, issues = select_available_experts(historical, available, limit=20)
        weighted = assign_cohort_weights(selected, cohort_size=5)

        self.assertEqual(len(weighted), 20)
        self.assertEqual(weighted[0].historical.master_rank, 6)
        self.assertEqual(weighted[-1].historical.master_rank, 25)
        self.assertEqual([expert.cohort for expert in weighted], [1] * 5 + [2] * 5 + [3] * 5 + [4] * 5)
        cohort_weights = [weighted[index].cohort_weight for index in (0, 5, 10, 15)]
        self.assertGreater(cohort_weights[0], cohort_weights[1])
        self.assertGreater(cohort_weights[1], cohort_weights[2])
        self.assertGreater(cohort_weights[2], cohort_weights[3])
        self.assertAlmostEqual(sum(cohort_weights), 1.0)
        self.assertTrue(any(issue["status"] == "historical_leader_unavailable" for issue in issues))

    def test_anchor_expert_can_equal_four_ordinary_experts(self) -> None:
        historical = load_historical_experts(
            FIXTURES / "expert_accuracy.synthetic.csv", "OVERALL"
        )[:10]
        selected = [
            SelectedExpert(
                historical=expert,
                expert_id=index,
                api_name=expert.name,
                last_updated="2026-08-29",
            )
            for index, expert in enumerate(historical, start=1)
        ]

        weighted = assign_cohort_weights(
            selected,
            cohort_size=5,
            anchor_expert_name=historical[0].name,
            anchor_equivalent_weight=4,
        )

        self.assertEqual([expert.cohort for expert in weighted], [1] + [2] * 5 + [3] * 4)
        self.assertAlmostEqual(weighted[0].cohort_weight, 4 / 13)
        self.assertAlmostEqual(
            sum({expert.cohort: expert.cohort_weight for expert in weighted}.values()),
            1.0,
        )

    def test_skill_freshness_requires_update_inside_two_weeks(self) -> None:
        available = {
            1: {"name": "Fresh", "last_updated": "2026-08-20T00:00:00+00:00"},
            2: {"name": "Stale", "last_updated": "2026-08-08T00:00:00+00:00"},
            3: {"name": "Undated", "last_updated": ""},
        }

        retained, issues = filter_recent_experts(
            available,
            14,
            as_of=datetime(2026, 8, 29, tzinfo=UTC),
        )

        self.assertEqual(set(retained), {1})
        self.assertEqual(len(issues), 2)

    def test_loads_dated_expert_pool_overrides(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "overrides.csv"
            path.write_text(
                "scope,expert_name,action,value,reason\n"
                "skills_half_ppr,Anchor,anchor_equivalent,4,leader\n"
                "skills_half_ppr,Stale,last_updated_override,2026-08-08,verified\n"
                "skills_half_ppr,Missing,exclude,,not selectable\n",
                encoding="utf-8",
            )

            result = load_expert_pool_overrides(path)["skills_half_ppr"]

        self.assertEqual(result["anchor"]["expert_name"], "Anchor")
        self.assertEqual(result["anchor"]["equivalent_weight"], 4.0)
        self.assertEqual(
            result["last_updated_overrides"][0]["last_updated"], "2026-08-08"
        )
        self.assertEqual(result["excluded_experts"][0]["expert_name"], "Missing")

    def test_kicker_history_uses_category_ranking(self) -> None:
        kickers = load_historical_experts(
            FIXTURES / "expert_accuracy.synthetic.csv", "K"
        )

        self.assertEqual(kickers[0].name, "Expert 01")
        self.assertEqual(kickers[0].category_rank, 1)
        self.assertEqual(kickers[0].category, "K")

    def test_default_ecr_availability_can_vary_across_positions(self) -> None:
        responses = [
            {"expert_names": {"1": "QB Expert"}, "expert_pub": {"1": "2026-08-23"}},
            {"expert_names": {"2": "RB Expert"}, "expert_pub": {"2": "2026-08-22"}},
        ]

        available, issues = _available_experts(responses)

        self.assertEqual(set(available), {1, 2})
        self.assertEqual(
            sum(issue["status"] == "position_availability_varies" for issue in issues), 2
        )

    def test_skill_availability_uses_single_overall_picker(self) -> None:
        picker = {
            101: {"name": "Expert Available", "last_updated": "2026-08-20"},
            202: {"name": "Expert Alternate", "last_updated": "2026-08-20"},
        }
        default_position_responses = [
            {"expert_names": {999: "Default Expert"}, "expert_pub": {}},
        ]

        available, issues = _scope_available_experts(
            "OVERALL", picker, default_position_responses
        )

        self.assertEqual(set(available), {101, 202})
        self.assertEqual(issues, [])

    def test_parses_selectable_experts_from_picker_rows(self) -> None:
        html = """
        <table><tbody>
          <tr><td><input name="expert[]" value="101" /></td>
              <td><a href="/experts/expert-available.php">Expert Available</a></td>
              <td data-sort="1787250846">8/20</td></tr>
          <tr><td><input name="expert[]" value="202" /></td>
              <td><a href="/experts/expert-alternate.php">Expert Alternate</a></td>
              <td data-sort="1787240304">8/20</td></tr>
        </tbody></table>
        """

        available = parse_fantasypros_expert_picker(html)

        self.assertEqual(available[101]["name"], "Expert Available")
        self.assertEqual(available[202]["name"], "Expert Alternate")
        self.assertTrue(available[101]["last_updated"].startswith("2026-08-20"))

    def test_export_keeps_picker_expert_omitted_from_default_ecr(self) -> None:
        class FakeClient:
            def consensus_rankings(self, season: int, **params: object) -> dict[str, object]:
                position = str(params["position"])
                filters = str(params.get("filters") or "")
                if filters:
                    expert_id = int(filters.split(":")[0])
                    expert_names = {
                        str(expert_id): {
                            101: "Expert 01",
                            202: "Expert 01",
                            303: "Expert 01",
                        }[expert_id]
                    }
                elif position == "K":
                    expert_names = {"202": "Expert 01"}
                elif position == "DST":
                    expert_names = {"303": "Expert 01"}
                else:
                    # Wheeler is selectable and filterable, but not part of
                    # FantasyPros' smaller default/recent ECR contributor set.
                    expert_names = {"999": "Default ECR Expert"}
                player_position = "QB" if position == "ALL" else position
                return {
                    "tier": "premium",
                    "expert_names": expert_names,
                    "expert_pub": {key: "2026-08-20" for key in expert_names},
                    "total_experts": len(expert_names),
                    "players": [
                        {
                            "player_id": f"player-{player_position}",
                            "player_name": f"Player {player_position}",
                            "player_team_id": "TST",
                            "player_position_id": player_position,
                            "rank_ecr": 1,
                        }
                    ],
                }

        picker = {101: {"name": "Expert 01", "last_updated": "2026-08-20"}}
        with tempfile.TemporaryDirectory() as temporary_directory:
            result = export_grouped_rankings(
                FakeClient(),
                accuracy_path=FIXTURES / "expert_accuracy.synthetic.csv",
                annual_accuracy_path=FIXTURES / "expert_accuracy_annual.synthetic.csv",
                output_dir=temporary_directory,
                expert_limit=1,
                specialist_expert_limit=1,
                cohort_size=1,
                expert_overrides_path=None,
                minimum_interval_seconds=0,
                max_skill_ranking_age_days=None,
                progress=lambda _: None,
                expert_picker_loader=lambda _: picker,
            )
            with (Path(temporary_directory) / "expert_pools.csv").open(
                encoding="utf-8", newline=""
            ) as handle:
                rows = list(csv.DictReader(handle))

        skill_rows = [row for row in rows if row["scope"].startswith("skills_")]
        self.assertEqual(result.request_count, 24)
        self.assertEqual(
            [row["expert_name"] for row in skill_rows], ["Expert 01"] * 2
        )
        self.assertEqual(result.selected_counts["skills_half_ppr"], 1)


if __name__ == "__main__":
    unittest.main()
