# Waiver Assistant current status

Updated: September 24, 2026 (America/Los_Angeles)

The Waiver Assistant is read-only. Evidence is in
`docs/WAIVER_ASSISTANT_TASKS.md`.

- WA-026 makes retention-safe Waiver Value universal application behavior.
  Policies without a `waiver_priority` block receive generic 50/30/20 defaults;
  league-local overrides remain isolated. Pruning preserves fresh same-position
  weekly/ROS/projection upgrades and labels budget-only omissions accurately.
- Missing roster value evidence is now isolated instead of aborting search.
  The uncovered player is visible and excluded from automatic drop selection;
  missing lineup projections produce a partial, non-affirmative result. Trade's
  stricter all-roster market gate is unchanged.
- The fresh League Beta proof selected J.K. Dobbins for Rachaad White. Kyle
  Pitts improved lineup points over Oronde Gadsden but was a PASS because his
  Waiver Value was 60.1 versus Gadsden's 68.4.
- The fresh League Alpha proof completed as DEGRADED, recorded player `12508`
  as `ROSTER_VALUE_UNAVAILABLE`, and kept unrelated moves eligible. Its best
  move was a kicker stream with a different legal drop. No Sleeper write
  occurred.
- WA-025 separates acquisition from retention. Waiver rank is acquisition-only;
  below-replacement weekly ranks do not reduce keep value, and injury-uncertain,
  above-replacement ROS players are protected. Its League Alpha 40/35/25
  calibration remains local; safety behavior is universal.
- WA-023–WA-025 cover DST streaming, three-signal scoring, retention safety,
  K/DST fallback, and ordered claim plans. WA-017–WA-022 cover input resilience,
  reporting, identity, visible omissions, rank dominance, and one-command use.

Ruff and all 673 tests pass. WA-006 audits recur; WA-016 remains optional
fail-closed research. No Waiver milestone is active.
