# Waiver Assistant current status

Updated: September 25, 2026 (America/Los_Angeles)

The Waiver Assistant is read-only. Evidence is in
`docs/WAIVER_ASSISTANT_TASKS.md`.

- WA-026 makes retention-safe Waiver Value universal with generic 50/30/20
  defaults, isolated league overrides, and pruning equivalence.
- WA-027 makes league-scored season production explicit in specialist add/drop
  evidence and requires one combined fallback score. The current league gives
  K season points a `2.0` weight and DST a smaller `0.5` weight; other leagues
  retain neutral defaults until separately calibrated. Fresh validation keeps
  the incumbent kicker, removes Detroit-for-Cincinnati, and retains only San
  Francisco and New England as affirmative DST alternatives.
- Missing roster value evidence is now isolated instead of aborting search.
  The uncovered player is visible and excluded from automatic drop selection;
  missing lineup projections produce a partial, non-affirmative result. Trade's
  stricter all-roster market gate is unchanged.
- WA-025 separates acquisition from retention. Waiver rank is acquisition-only;
  below-replacement weekly ranks do not reduce keep value, and injury-uncertain,
  above-replacement ROS players are protected. Calibrated weights remain local.
- WA-023–WA-025 cover DST streaming, three-signal scoring, retention safety,
  K/DST fallback, and ordered claim plans. WA-017–WA-022 cover input resilience,
  reporting, identity, visible omissions, rank dominance, and one-command use.

Ruff and all 676 tests pass. WA-006 audits recur; WA-016 remains optional
fail-closed research. No Waiver milestone is active.
