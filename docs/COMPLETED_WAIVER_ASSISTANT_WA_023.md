# WA-023 — Availability-aware DST streaming valuation

Completed September 18, 2026 (America/Los_Angeles).

## Outcome

DST waiver decisions no longer compare an acquisition with forcing the current
defense into every remaining game. Each target is compared for four weeks with
the best attainable alternative among the incumbent and other defenses that
are currently acquirable. The horizon weights are `1.0, 0.5, 0.25, 0.125`.

An affirmative DST move must clear the league's current-week gain floor and
have a nonnegative weighted advantage. A defense whose value is only future or
rest-of-season value is WATCH rather than an immediate add/drop. JSON evidence
records every weekly target, baseline defense, projection, weight, and delta;
human search reports show the four-week weighted advantage.

The shared replacement optimizer also accepts required fixed slots. Waiver and
Trade replacement floors therefore cannot use a QB or another position as the
replacement for an uncovered K or DST slot, while ordinary RB/WR/TE flex
optimization remains unchanged.

## Live read-only acceptance

- `fourth_and_20`: Denver changed from ACQUIRE over Tampa Bay to WATCH. Its
  four-week weighted advantage is `-2.654`; weekly baselines are Tampa Bay,
  Minnesota, Jacksonville, and Minnesota.
- `boeing`: Denver changed from ACQUIRE over San Francisco to WATCH. Its
  four-week weighted advantage is `-2.471`; weekly baselines are Chicago,
  Detroit, Jacksonville, and Detroit.
- Bye replacement evidence uses DST alternatives (`JAX`/`PIT`) rather than the
  previously observed QB substitutions. No Sleeper write occurred.

Both live searches were read-only. Provider readiness was DEGRADED because
some non-DST evidence remained incomplete or stale; DST projection and
availability evidence used by this acceptance was complete.

## Verification

- `python -m unittest discover -s tests`: 591 tests passed.
- `python -m ruff check src tests`: passed.
- Focused coverage includes horizon weights, streamer-baseline selection,
  future-only WATCH behavior, schema evidence, and a SUPER_FLEX/DST regression
  proving a higher-scoring QB cannot replace a DST.
