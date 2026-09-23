# Waiver Assistant current status

Updated: September 22, 2026 (America/Los_Angeles)

The Waiver Assistant is read-only for both leagues. Detailed requirements,
task evidence, and exit proofs remain in `docs/WAIVER_ASSISTANT_TASKS.md`.

- WA-024 makes a 50/30/20 weekly/Waiver Wire/ROS score the skill-player Waiver
  Value for both adds and drops. Missing lists are neutral and the remaining
  weights renormalize. Waiver Wire uses the three best trustworthy current
  contributors, falling back to FantasyPros Latest ECR when fewer than three
  qualify. ROS uses a separate two- or three-expert Waiver panel. The read-only
  `fourth_and_20` proof and all 658 tests passed without a Sleeper write.
- WA-023 values DST moves against current-week and decaying four-week
  incumbent/streamer baselines; K/DST replacements remain position-matched.
- WA-022 provides one-command prepare, build/reuse, and reporting for both
  leagues. Search performance remains a target.
- WA-017–WA-021 cover inactive projection omissions, action-first reports, DST
  identity matching, visible omitted candidates, and fresh-rank dominance.
- WA-012–WA-015 provide Waiver Wire, role, emerging-upside, and league-local
  policy evidence; incomplete cases fail closed.

WA-006 audits recur. WA-016 remains optional fail-closed research; promoting
probabilities or thresholds requires its evidence and a new milestone.
Replacement baselines use the next legal acquirable alternative without
assuming another transaction. Full proofs remain in JSON. No Waiver milestone
is active.
