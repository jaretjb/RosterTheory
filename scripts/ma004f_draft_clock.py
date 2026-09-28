"""Offline, synthetic Draft-turn clock review across both reference shapes."""

from __future__ import annotations

import json
from statistics import median
from time import perf_counter

from roster_theory.draft.simulation import DraftSeasonSchedule, compare_strategies
from roster_theory.draft.watcher import reconcile_draft_state, recommend_for_state
from roster_theory.schedule_inputs import NFL_TEAMS
from scripts.ma001_baseline import offline
from tests.ma001_fixtures import draft_fixture, rules


def measure(repeats: int = 5) -> dict:
    if repeats < 5:
        raise ValueError("At least five measured repetitions are required")
    schedule = DraftSeasonSchedule(2026, {team: 8 for team in NFL_TEAMS}, 17)
    rows = []
    with offline():
        for profile, teams in (("reference_a", 10), ("reference_b", 12)):
            draft, board = draft_fixture(profile)
            positions = rules(profile)["roster_positions"]
            for slot in range(1, teams + 1):
                trace = compare_strategies(
                    board, teams, slot, positions, 15, trials=1, seed=33,
                    strategies=("scenario_safe",), include_special_teams=True,
                    include_trace=True, availability_rates=(0.1,),
                    availability_samples=2, bench_weights=(0.2,),
                    rank_weights=(0.0,), season=2026, schedule=schedule,
                )[0]["trace"]
                user_picks = [
                    row for row in trace["picks"] if row["draft_slot"] == slot
                ]
                for phase, index in (("early", 0), ("middle", 7), ("late", 13)):
                    target = user_picks[index]["pick_no"]
                    picks = [
                        {
                            "pick_no": row["pick_no"],
                            "draft_slot": row["draft_slot"],
                            "player_id": row["player_key"].split(":", 1)[1],
                            "metadata": {"position": row["position"]},
                        }
                        for row in trace["picks"] if row["pick_no"] < target
                    ]
                    state = reconcile_draft_state(draft, picks, slot)

                    def recommend():
                        result = recommend_for_state(
                            state, draft, board, limit=3,
                            policy_override=("scenario_safe",),
                        )
                        if not result.get("recommendations", {}).get("scenario_safe"):
                            raise AssertionError(f"No recommendation: {profile}/{slot}/{phase}")

                    recommend()  # Warm-up is outside measured runs.
                    timings = []
                    for _ in range(repeats):
                        start = perf_counter()
                        recommend()
                        timings.append(perf_counter() - start)
                    rows.append({
                        "profile": profile, "slot": slot, "phase": phase,
                        "median_seconds": median(timings),
                        "max_seconds": max(timings),
                    })
    return {
        "scope": "synthetic offline ready-input Draft advice; 60-second clock",
        "budget_seconds": 2.0,
        "repeats": repeats,
        "states": len(rows),
        "max_median_seconds": max(row["median_seconds"] for row in rows),
        "max_observed_seconds": max(row["max_seconds"] for row in rows),
        "by_phase_max_median_seconds": {
            phase: max(row["median_seconds"] for row in rows if row["phase"] == phase)
            for phase in ("early", "middle", "late")
        },
    }


if __name__ == "__main__":
    print(json.dumps(measure(), sort_keys=True))
