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

## MA-003b request-limit follow-up (#32)

The original extraction protected Trade and Waiver's planned API batches, Waiver
Wire, historical backtests and expert refreshes, but older direct commands could
still contact FantasyPros outside the shared ledger. The Draft board and refresh,
grouped rankings, rank-consistency report, and API probes now construct a client
that reserves and paces every HTTP attempt. That includes retries and excludes
cache hits. The grouped-rankings expert-picker page and draft-accuracy history
pages also reserve and pace before each HTML request. These entry points use the
same `data/cache/trade/fantasypros/daily_budget.json` path as the existing
workflows; the path is a compatibility alias, not a Trade dependency.

The old daily ledger JSON remains readable without migration. Reservation is
written before pacing or network I/O; a crash can therefore overcount but cannot
silently exceed the 500-request daily ceiling. A live lock times out rather than
start an uncounted request, and an operating-system-released lock can be used
after its process dies. A corrupt ledger fails closed. The budget resets on the
next UTC date through the existing budget contract. Rolling back the code must
retain the ledger file and stop concurrent paid requests until the older paths
are protected again; deleting the ledger would erase already spent requests.

Synthetic tests cover CLI composition, API attempts and retries, HTML-page
charging, cache hits, old-ledger rollover, invalid ledgers, two-process
contention, pacing and recovery from a terminated lock holder. No paid-provider
call or private league evidence was used. This changes request coordination only;
Draft, Trade and Waiver ranking, scoring and recommendation decisions are
unchanged.

The offline MA-001 benchmark was rerun for five measured repetitions on both
synthetic reference profiles, with identical semantic evidence on every run.
The larger profile's Draft turn was 0.112 seconds versus 0.112 at baseline;
Trade bounded search was 3.23 versus 3.27 seconds; Waiver search was 20.80
versus 20.97 seconds. No workload exceeded the proposed 20% time threshold.
Two single-run allocation peaks initially exceeded the proposed 25% review
threshold; three follow-up traced runs put each median at 12% above baseline,
showing that the initial peak was not repeatable. The local benchmark artifact
stays ignored under `data/exports/`.

Local handoff checks: 935 unit tests, Ruff, Python compilation, context routing,
tracked-tree privacy scan and whitespace validation pass. CI and review remain
the merge gate.
