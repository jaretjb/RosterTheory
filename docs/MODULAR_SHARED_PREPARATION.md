# MA-003 shared in-season preparation handoff

Trade and Waiver now call `application.value_preparation.refresh_value_boards`.
Trade supplies its snapshot refresh and ROS expert selector through its own
entry point. Waiver adapts the Waiver snapshot it already fetched and supplies
its own ROS panel selector. Neither feature imports the other's workflow.

The shared service owns FantasyPros retrieval and cache interpretation,
player-identity reconciliation, league-scored weekly projections, source
freshness checks, horizon evidence, and value-board construction. Pure
calculations live in `inseason`; schedule, Draft-anchor and evidence file I/O
live in `application`. Trade evaluation/search and Waiver add/drop and claim
policy remain in their feature packages. Old Trade imports remain compatibility
entry points; their public value-board result fields are unchanged.

Waiver writes value-board and prospective evidence under its Waiver analysis
directory. Its adapted value snapshot uses `value_snapshot.json`, preserving
the Waiver `snapshot.json` needed for replay. The value artifacts identify
Waiver as their product; no stored value-board schema version changed. The
existing FantasyPros raw-cache and daily-budget paths retain their historical
`data/cache/trade/fantasypros` spelling so prior cache evidence remains usable
without a paid refresh. The path is now an infrastructure compatibility alias,
not a call into Trade.

The standard-library request gate serializes daily reservations and request
starts across processes on Windows and POSIX. It charges a planned batch
before retrieval, and charges a retry before that attempt. Interrupted
reservations stay charged. Board, Waiver Wire, historical backtest and expert
refresh paths use the gate. Synthetic tests exercise two-process contention,
shared pacing, retry budget exhaustion, snapshot reuse and import boundaries.
No live provider or Sleeper write was used in this extraction.

Reference Trade/Waiver decisions, CLI/report contracts, context routing, Ruff,
compilation, privacy and full-suite gates are the handoff checks. The MA-002
provider-field and league-rule evidence remains open; this extraction does not
promote estimates, recommendations or format support.
