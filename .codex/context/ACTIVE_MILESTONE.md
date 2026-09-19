# Active milestone

No implementation milestone is active as of September 18, 2026
(America/Los_Angeles). Completed records below are retained as handoff history
and do not authorize additional work.

WA-023 — Availability-aware DST streaming valuation is complete. DST decisions
now use a four-week `1.0/0.5/0.25/0.125` comparison against the incumbent and
currently acquirable streamers, require both an immediate and weighted edge,
and classify future-only cases as WATCH. Fixed K/DST replacement slots cannot
be filled by another position. Both live Denver recommendations became WATCH;
all 591 tests and Ruff pass. Details are in
`docs/COMPLETED_WAIVER_ASSISTANT_WA_023.md`.

Trade TA-1201 — Search runtime optimization and publication is complete.
League Beta's full search fell from about 225 seconds to about 63 seconds while
retaining 6,226 enumerated packages, 33 exact evaluations, identical rejection
counts, and no target. League Alpha retained 5,094/27 and no target. Complete
quality, privacy, packaging, publication, and remote checks pass. Details are
in `docs/COMPLETED_TRADE_ASSISTANT_TA_1201.md`.

Trade TA-1101 — Single-command Trade analysis is complete. Diagnose, evaluate,
gaps, search, and compare now prepare required current evidence automatically,
reuse fresh caches, preserve explicit overrides and offline replay, retain
league-local policy authority, and remain read-only. Both configured leagues
completed direct diagnosis and search from the default config. All 588 tests
and Ruff pass. League Beta's roughly 225-second bounded search remains a performance
target. Details are in `docs/COMPLETED_TRADE_ASSISTANT_TA_1101.md`.

WA-022 — Single-command Waiver readiness and report reliability is complete.
`roster-theory waiver search LEAGUE` now prepares stale/missing provider facts,
builds or reuses the league-local input bundle, and produces the report without
requiring `inputs prepare`, `waiver inputs`, or `--inputs`. The FantasyPros
expert-directory parameters and timestamp handling match the live provider
contract; shared history is resumable; five-minute freshness is consistent;
legacy same-league policy metadata migrates with backups; and per-search caches
reduce verified live runtime while preserving results. Both configured leagues
complete read-only from the default per-user config. All 582 tests and Ruff
pass. Details are in `docs/COMPLETED_WAIVER_ASSISTANT_WA_022.md`.

Replacement Counterfactual Consistency is complete. Trade and general Waiver
lineup deltas now optimize the active bench first and compare bye/inactive
capacity with the best legal, acquirable waiver alternative. A Waiver target
is excluded from its own baseline, structural roster holes do not assume an
extra transaction, and replacement IDs are auditable in evidence and human
reports. Draft's legacy bye sensitivity now reports reserve value above the
waiver floor while retaining the total filled and floor components. Focused
feature tests, all 575 repository tests, and Ruff pass. No provider request,
league calibration transfer, transaction, or Sleeper write occurred. Details
are in `docs/COMPLETED_REPLACEMENT_COUNTERFACTUAL_CONSISTENCY.md`.

Trade Phase 10 — Ranking-exclusion resilience and roster-context targets is
complete. Provider-only rank slots no longer collapse projection curves;
automatic targets respect one-starter roster capacity and report incoming
lineup use. League Alpha evidence hash `f46d834e73b0935a` and League Beta hash
`7cfa494b39a6ed4b` both replay and return no target. Beta passes the former WR
106/107 stop. The dedicated context gate passes 14 tests, all 568 repository
tests pass, and CI runs context routing separately on every push and pull
request. No Sleeper write occurred. Exact evidence is in Trade Phase 10.

OS-013 — GitHub publication and post-publication verification is complete as
of September 16, 2026 (America/Los_Angeles). The reviewed source-only alpha is
public at <https://github.com/jaretjb/RosterTheory>. Remote `main` was replaced
by a fresh repository whose history starts at the approved sanitized root. The
original GitHub repository is retained as the private
`RosterTheory-private-archive`; this avoids exposing unreachable objects that
GitHub retained after the initial force-update. The replacement's complete
release workflow and full-history Gitleaks scan pass. Anonymous repository,
README, license, clone, install, retired-SHA, and offline `doctor` checks pass.
No tag, GitHub release, PyPI upload, provider request, or Sleeper write occurred.
Details are in
`docs/COMPLETED_OPEN_SOURCE_RELEASE_OS_013.md`.

OS-007 — Public alpha release candidate is complete as of September 16, 2026
(America/Los_Angeles). The reviewable `0.1.0` source-only alpha is a sanitized
single-root local branch whose tree matches the reviewed preparation branch.
The existing private history and ignored evidence remain preserved. Clean-clone
release gates, full-candidate-history Gitleaks, identity/privacy review,
redistribution review, packaging, and isolated installation pass. No candidate
history was pushed; no tag, GitHub release, visibility change, or package upload
occurred. Details are in `docs/COMPLETED_OPEN_SOURCE_RELEASE_OS_007.md`.

OS-006 — Automated public-release quality and security gates is complete as of
September 16, 2026 (America/Los_Angeles). The `release gates` workflow blocks
on the complete suite across supported Linux/Windows Python versions plus a
macOS smoke matrix, focused CLI/output contracts, unsafe tracked artifacts,
full-history Gitleaks findings, pinned Ruff and pip-audit checks, distribution
contents, and a clean wheel install. All 564 tests and every locally runnable
gate pass; remote CI will execute on push or pull request. Details are in
`docs/COMPLETED_OPEN_SOURCE_RELEASE_OS_006.md`.

OS-018 — Unified season preparation and runtime refresh is complete as of
September 16, 2026 (America/Los_Angeles). `roster-theory inputs prepare/status`
now provides preflighted, resumable, freshness-aware preparation for
selected/all leagues and Draft/Trade/Waiver modes. Shared provider evidence is
reused while league policies, derived inputs, readiness, and results remain
isolated. The installed CLI also builds Waiver input bundles without a source
checkout. All 560 tests pass; wheel workflows were verified in PowerShell and
Git Bash with paths containing spaces and redirected JSON. Details are in
`docs/COMPLETED_OPEN_SOURCE_RELEASE_OS_018.md`.

OS-015 — Expert evidence and in-season pool refresh commands is complete as of
September 16, 2026 (America/Los_Angeles). `roster-theory inputs experts`
provides inspect, refresh, validate, and import workflows for all Draft accuracy
inputs and the league-scoped in-season pool. Refreshes retain replayable source
evidence and an auditable selection/rejection record, respect the one-request-
per-second and 500-request daily limits, and fail closed on incomplete coverage,
stale availability, or ambiguous identity. Preseason accuracy is never used as
in-season authority. All 537 tests pass; no Sleeper write occurred. Details are
in `docs/COMPLETED_OPEN_SOURCE_RELEASE_OS_015.md`.

TX-002 console marquee alignment is complete as of September 16, 2026
(America/Los_Angeles). Wide, standard, compact, narrow, Unicode, and ASCII
interactive heroes now carry the finalized `ROSTER THEORY` marquee hierarchy:
`FANTASY FOOTBALL ASSISTANT` immediately above the Draft/Trade/Waiver mode
line. Redirected, JSON, and suppressed-banner output remain unchanged. All 528
tests pass; decision behavior is unchanged.

TX-002 README artwork refinement is complete as of September 16, 2026
(America/Los_Angeles). The vector marquee now uses larger, heavier pixel
letters with a hard-edged 1990s arcade extrusion; `ROSTER` is vertically
rebalanced, and `FANTASY FOOTBALL ASSISTANT` appears immediately above the
Draft/Trade/Waiver mode line. A native 1200x520 browser render was visually
reviewed. All 528 tests pass; terminal behavior, machine output, and decision
policy are unchanged.

TX-002 arcade amendment is complete as of September 16, 2026
(America/Los_Angeles). The terminal and README now use an original
bright-yellow 1980s arcade-scoreboard identity. Wide terminals render both
`ROSTER` and `THEORY` as equally large stacked pixel words; standard and
compact command mastheads inherit the arcade framing, with aligned ASCII and
narrow fallbacks. The logo's `read-only` marketing tagline was removed while
factual safety boundaries remain in operational text. All 528 tests pass;
machine output and recommendation behavior are unchanged.

TX-003 — Doctor health-board human view is complete as of September 16, 2026
(America/Los_Angeles). Doctor now opens with the full interactive identity and
renders a concise offline/read-only checkup, a per-league Draft/Trade/Waiver
data-versus-decision matrix, league-scoped next actions, and an explicit ready
check count. `--details` exposes every original check. JSON remains unchanged,
and Doctor still makes zero provider calls and zero Sleeper writes. All 527
tests pass. Details are in `docs/COMPLETED_TERMINAL_EXPERIENCE_TX_003.md`.

TX-002 — Full Roster Theory wordmark and command mastheads is complete as of
September 16, 2026 (America/Los_Angeles). The interactive hero spells out the
full product name with adaptive original sideline-card borders; routine
commands and command help use full-name command mastheads. Redirected and
machine output remain undecorated. Details are in
`docs/COMPLETED_TERMINAL_EXPERIENCE_TX_002.md`.

TX-001 — Terminal visual primitives and output boundaries is complete as of
September 16, 2026 (America/Los_Angeles). Shared width tiers, Unicode/ASCII
fallbacks, palette tokens, status styling, and visible-width handling now
provide the stable foundation for human terminal presentation. Details are in
`docs/COMPLETED_TERMINAL_EXPERIENCE_TX_001.md`.

WA-018 — Action-first human Waiver search report is complete as of September
16, 2026 (America/Los_Angeles). Human search output now leads with the action,
best move, plain-English reason, and current-week effect, followed by compact
DST, kicker, and watchlist sections. Audit counts, policy IDs, pruning proofs,
and full reversals remain in JSON and saved evidence. Windows PowerShell and
narrow/redirected output are verified. All 520 tests pass; no decision logic or
Sleeper state changed. Details are in
`docs/COMPLETED_WAIVER_ASSISTANT_WA_018.md`.

WA-019 — Reliable FantasyPros-to-Sleeper DST identity reconciliation is
complete as of September 16, 2026 (America/Los_Angeles). Waiver value refreshes
retain the Sleeper K/DST identity directory without expanding Trade's valuation
universe, and uniquely normalized NFL team abbreviations reconcile FantasyPros
numeric defense IDs. Exact DST evidence now preserves and reports both defenses'
current-week points and ranks. A live read-only search recovered the full DST
pool and surfaced the expected streaming alternatives. All 519 tests pass; no
Sleeper write occurred. Details are in
`docs/COMPLETED_WAIVER_ASSISTANT_WA_019.md`.

WA-021 — Prevent stale Draft anchors from vetoing fresh Waiver dominance is
complete as of September 16, 2026 (America/Los_Angeles). Waiver input evidence
now identifies the actual long-term value horizon and uses a two-hour ranking
and expert cache window. The narrowly bounded same-position dominance path is
protected from pruning and rechecked by exact evaluation. Live local validation
selects the intended same-position upgrade. All 514 tests pass; no Sleeper
write occurred. Details are in `docs/COMPLETED_WAIVER_ASSISTANT_WA_021.md`.

WA-020 — Explain notable omitted and pruned Waiver candidates is complete as
of September 16, 2026 (America/Los_Angeles). Human search output now gives a
small deterministic shortlist with available ranks, roster comparison, and a
plain exclusion reason. Top Waiver players outside complete value-board
coverage remain visible but ineligible. The completed amendment raises the
shared RB valuation minimum from 50 to 60, so RB51-RB60 receive normal complete
evaluation. All 511 tests pass. No provider request or Sleeper write occurred.
Details are in
`docs/COMPLETED_WAIVER_ASSISTANT_WA_020.md`.

WA-017 — Current-week inactive projection omission resilience is complete as
of September 15, 2026 (America/Los_Angeles). Waiver search and entered
evaluation reconcile only a current-week FantasyPros omission zero supported
by fresh league-local Sleeper inactive status. Waiver player-directory cache
age is capped at five minutes; future availability is not inferred. All 508
tests pass. No live provider request or Sleeper write occurred. Details are in
`docs/COMPLETED_WAIVER_ASSISTANT_WA_017.md`.

WA-015 — Live audit acceptance closure is complete as of September 15, 2026
(America/Los_Angeles). Both leagues were audited read-only; saved successful
searches replay by hash, and the fresh incomplete search failed closed on a
FantasyPros Week 2 projection omission. There was no affirmative move or
Sleeper write. Provider coverage and role limitations remain visible, and no
policy was promoted. The Waiver JSON reporting defect is repaired; all 505
tests pass. Details are in docs/COMPLETED_WAIVER_ASSISTANT_WA_015.md.

OS-005 — Installable package and public documentation is
complete as of September 15, 2026 (America/Los_Angeles). The initial release
is GitHub source-only; no distribution was published. OS-006 is next and must
be activated separately.

OS-009 — Interactive and machine-output contract is complete. Terminal
capabilities are detected centrally; `--json` commands produce one valid JSON
value with saved-path notices on stderr. Machine failures preserve status,
type, and reason. Watcher JSON is one report collection when it stops, while
human reports remain readable. Redirected, narrow, `NO_COLOR`, Windows/Linux,
and exit-code coverage pass; the complete 483-test suite passes.

OS-010 — Original adaptive terminal identity is complete. Original amber/ASCII
RT art appears only on interactive welcome and guided help; narrow terminals
get a one-line fallback, selected human reports get a compact mark, and
`--no-banner` suppresses both. Redirected, JSON, CSV, evidence, log, error,
and ordinary argparse help output are undecorated. Snapshot and boundary tests
pass, and the full 489-test suite is green. Details are in
`docs/COMPLETED_OPEN_SOURCE_RELEASE_OS_010.md`.

OS-011 — Read-only setup diagnostics is complete. The offline `doctor` command
checks config, identity, league-scoped policies, and selected local inputs;
Draft, Trade, and Waiver readiness remain separate. Human and redacted JSON
views preserve safe next actions without implying fresh evidence or portable
calibration. All 496 tests pass. Details are in
`docs/COMPLETED_OPEN_SOURCE_RELEASE_OS_011.md`.

OS-012 — Draft, Trade, and Waiver human decision reports now share a context-
first frame, with prominent failure readiness and evidence paths at the end.
Draft simulation and board-source refresh show cancellable start/end progress
only on interactive human stdout. JSON/piped modes stay silent. All 502 tests
pass; details are in `docs/COMPLETED_OPEN_SOURCE_RELEASE_OS_012.md`.

OS-005 — Complete package metadata and public setup, contribution, security,
conduct, and changelog documents are in place. A bundled synthetic config
works from a wheel outside the checkout; external expert and schedule inputs
give actionable errors. Wheel and source archive contents were inspected,
fresh-wheel offline smoke tests passed, and all 505 tests pass. Details are in
`docs/COMPLETED_OPEN_SOURCE_RELEASE_OS_005.md`.
