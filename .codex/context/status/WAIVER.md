# Waiver Assistant current status

Updated: September 24, 2026 (America/Los_Angeles)

The Waiver Assistant is read-only. Detailed requirements, task evidence, and
exit proofs remain in `docs/WAIVER_ASSISTANT_TASKS.md`.

- WA-026 makes retention-safe Waiver Value universal application behavior.
  Policies without a `waiver_priority` block receive generic 50/30/20 defaults;
  league-local overrides remain isolated. Exact-budget pruning cannot hide a
  fresh same-position weekly/ROS/projection upgrade, and budget-only omissions
  no longer claim that the player failed a decision threshold.
- The fresh League Beta proof selected J.K. Dobbins for Rachaad White. Kyle
  Pitts improved modeled lineup points over Oronde Gadsden but was a PASS
  because his Waiver Value was 60.1 versus Gadsden's 68.4. No Sleeper write
  occurred.
- The fresh League Alpha proof was attempted and failed closed because current
  value input omits rostered skill player `12508`; the blocker was not bypassed.
- WA-025 separates acquisition from retention. Waiver rank is acquisition-only;
  below-replacement weekly ranks do not reduce keep value, and injury-uncertain,
  above-replacement ROS players are protected. Its League Alpha 40/35/25
  calibration remains local; the underlying safety behavior is universal.
- WA-023–WA-025 cover DST streaming, three-signal scoring, retention safety,
  K/DST fallback, and ordered claim plans. WA-017–WA-022 cover input resilience,
  reporting, identity, visible omissions, rank dominance, and one-command use.

Ruff and all 668 tests pass. WA-006 audits recur; WA-016 remains optional
fail-closed research. No Waiver milestone is active.
