# Waiver Assistant current status

Updated: September 18, 2026 (America/Los_Angeles)

The Waiver Assistant is read-only for both leagues. Detailed task evidence and
exit proofs remain in the selected rows of `docs/WAIVER_ASSISTANT_TASKS.md`.

- WA-022 makes `waiver search LEAGUE` prepare, build/reuse, and report in one
  command. It repairs legacy same-league policy metadata with backups, uses the
  live FantasyPros expert contract, resumes shared history, and works for both
  leagues from the default config. Search remains a performance target.

- WA-023 requires DST moves to beat this week's and the four-week decaying
  incumbent/streamer baseline. Future-only value is WATCH; K/DST replacements
  must match the fixed position.

- WA-012–WA-015 provide Waiver Wire, role, emerging-upside, and league-local
  policy evidence; incomplete cases fail closed.
- WA-017 permits current-week projection-omission zeroes only for fresh league-
  local IR/PUP/SUSP/OUT evidence; healthy and future-week omissions fail closed.
- WA-018 leads human reports with the move, reason, and weekly effect.
- WA-019 maps numeric DST identities only through unique normalized teams and
  compares weekly points/ranks with the incumbent.
- WA-020 explains five `Worth a look` candidates and keeps incomplete players
  visible but ineligible.
- WA-021 allows a legal same-position add with superior fresh weekly rank, ROS
  ECR, and projection to override stale non-ROS ownership gates only.

WA-006 audits recur. WA-016 remains optional fail-closed shadow research;
probability or threshold promotion requires its evidence and a new milestone.
Replacement baselines use the next legal acquirable alternative without
assuming a second transaction. Full proofs remain in JSON. No Waiver milestone
is active.
