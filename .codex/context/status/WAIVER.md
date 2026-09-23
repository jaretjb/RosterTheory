# Waiver Assistant current status

Updated: September 22, 2026 (America/Los_Angeles)

The Waiver Assistant is read-only for both leagues. Detailed requirements,
task evidence, and exit proofs remain in `docs/WAIVER_ASSISTANT_TASKS.md`.

- WA-025 separates acquisition from retention. Waiver rank is acquisition-only;
  below-replacement weekly ranks no longer reduce keep value; injury-uncertain,
  above-replacement ROS players are protected. Recent league-scored performance
  is bounded. Lineup and same-position ROS gates prevent destructive cuts.
  K/DST have rank/performance fallback, and search returns an ordered claim plan
  with shared-drop conflicts.
- The fresh `fourth_and_20` proof protected Caleb Williams and Rico Dowdle and
  reproduced the requested skill and kicker moves. Updated defense evidence
  selected Minnesota, New England, and Carolina. It evaluated 57/pruned 75,
  made no Sleeper write, and passed Ruff plus all 661 tests.
- WA-024 introduced weekly/Waiver/ROS scoring. WA-025 supersedes symmetric
  add/drop treatment and applies 40/35/25 to `fourth_and_20` only. Trustworthy
  expert panels and Latest-ECR fallbacks remain horizon-specific.
- WA-023 values DST moves against current-week and decaying four-week
  incumbent/streamer baselines; K/DST replacements remain position-matched.
- WA-022 provides one-command preparation and reporting.
- WA-017–WA-021 cover inactive projection omissions, action-first reports, DST
  identity matching, visible omitted candidates, and fresh-rank dominance.
- WA-012–WA-015 cover Waiver Wire, role, emerging-upside, and league policy.

WA-006 audits recur. WA-016 remains optional fail-closed research. Replacement
baselines use the next legal alternative. Full proofs remain in JSON. No Waiver
milestone is active.
