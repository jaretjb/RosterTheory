# OS-016 — NFL schedule and bye refresh command

Completed: September 16, 2026 (America/Los_Angeles)

## Outcome

`roster-theory inputs schedule` now provides `inspect`, `refresh`, `validate`,
and `import` operations. The normal refresh downloads the nflverse `schedules`
release, selects the configured league season, keeps regular-season rows, and
writes both replayable source evidence and the normalized schedule consumed by
Trade. Users no longer need to assemble a schedule or bye table by hand.

The provider adapter records the stable release asset endpoint, source page,
capture time, response hash, license, use restriction, and raw authorized CSV.
A separate transformation layer normalizes team aliases, opponents, home/away
state, game IDs, weeks, and optional game date/time fields. Bye weeks are
derived from the validated games rather than copied from a second table.

## Safety and usability

- Normal artifacts default to
  `data/cache/nflverse/{season}/schedule.json`; Trade derives that path from the
  selected league and refuses a schedule for another season.
- Validation requires the current 32 teams, the full regular-season week
  range, one appearance per team/week at most, exactly one derived bye per
  team, unique game IDs and weekly pairings, and regular-season-only games.
- `--replay` reproduces a schedule from hash-checked saved source evidence
  without a network call.
- `inputs schedule import` accepts a user-authorized provider-shaped UTF-8 CSV
  and requires explicit source, URL, license, and capture-time provenance.
- Explicit normalized/evidence paths, Windows paths with spaces, `--dry-run`,
  and stable `roster-theory.inputs/v1` JSON output are supported.
- Provider failures are typed and do not produce a partial schedule. A later
  corrected response replaces the normalized artifact and records its new
  response hash.
- Trade refresh reports the schedule path, capture time, age, and 24-hour
  freshness state. No schedule command or Trade analysis performs a Sleeper
  write.

The README and third-party notices now document the command workflow,
nflverse attribution, replay, and authorized CSV fallback.

## Validation

- Synthetic tests cover normalization, byes, postseason filtering, duplicate
  and impossible games, season mismatch, corrected responses, provider
  unavailability, replay, dry-run, import provenance, Windows paths, CLI
  discovery, season-aware Trade resolution, and zero Sleeper writes.
- Complete suite: 544 tests pass.

No live provider data was committed, no private league data was added, and no
Sleeper write occurred.
