# Active milestone

AC-003 — Joint cross-position optimization and claim plans (issue #9) is implemented,
pending tested PR handoff/review. Authorized by the request to merge PR #16 and work #9.
Load only AC-003 and the completion protocol in `docs/ASSISTANT_RELIABILITY_TASKS.md`.
Implement joint add/drop ranking, truthful bounded-search coverage, consistent
recommendation/report identity and ordering, and safe claim branches. Preserve
AC-002 safety gates; no calibration changes or Trade strategy work are authorized.
Verification: 737 tests and Ruff pass. Stop at the tested PR handoff.

AC-001 and prerequisite PR #6 are merged through PRs into main. PR #15 passed
all CI checks. Evidence: `docs/COMPLETED_ASSISTANT_RELIABILITY_AC_001.md`.
AC-002/#8 merged in PR #16 with all CI checks passing. AC-004–AC-008 remain
planned; the overall audit is not closed. All league actions remain read-only.

WA-027 — League-scored specialist performance weighting completed September
25, 2026 (America/Los_Angeles). K and DST exact evidence now preserves actual
season and recent league-scored production, and rank fallback must clear one
transparent combined score rather than any favorable rank authorizing a swap.
The current league uses a larger K season-points weight and a smaller DST
weight; other leagues retain neutral defaults pending separate evidence.

Fresh read-only validation protects the productive rostered kicker, removes
Detroit from the claim plan behind Cincinnati, and retains only San Francisco
and New England as affirmative DST alternatives. All 676 tests and Ruff pass;
no Sleeper write occurred. Acceptance evidence is in WA-027 of
`docs/WAIVER_ASSISTANT_TASKS.md`.

WA-026 — Universal retention safety and pruning equivalence completed
September 24, 2026 (America/Los_Angeles). Retention-safe Waiver Value is now
application-default behavior for every league policy, while calibrated weight
overrides remain league-local. Exact-budget pruning yields to fresh
same-position weekly/ROS/projection dominance, with bounded-versus-exhaustive
decision and drop equivalence covered by regression tests.

The fresh League Beta read-only proof selected J.K. Dobbins for Rachaad White.
Kyle Pitts improved projected lineup output over Oronde Gadsden but failed the
retention-safe value gate, 60.1 to 68.4. The coverage-isolation amendment now
records rostered player `12508` as `ROSTER_VALUE_UNAVAILABLE` while completing
League Alpha and keeping unrelated alternatives eligible. The result was an
ACQUIRE recommendation with a different legal drop; no Sleeper write occurred.
Trade retains strict all-roster coverage. Ruff and all 673 tests pass. Full
acceptance evidence is in the WA-026 row of `docs/WAIVER_ASSISTANT_TASKS.md`.

Trade TA-1312 — ROS expert-panel resilience completed September 23, 2026
(America/Los_Angeles). Trade now prefers three accurate, fresh experts who
actually contribute to all current ROS position feeds, accepts two as an
explicitly degraded panel, renormalizes their weights, and fails closed below
two. FantasyPros Latest ECR remains an independent market board; Waiver
acquisition scoring, weekly weighting, and Waiver Wire policy did not transfer.

Today's cached League Beta value-board refresh completed with three actual
contributors, complete selected and market ROS boards, 25 cache hits, zero
FantasyPros calls, and no Sleeper write. League Alpha passed the repaired expert
selection and then stopped at the separate rostered-player coverage gate for
inactive player 12508. All 666 tests and Ruff pass. Details:
`docs/COMPLETED_TRADE_ASSISTANT_TA_1312.md`.

WA-025 — Retention-safe Waiver Value and ordered claim portfolio completed
September 22, 2026 (America/Los_Angeles). Waiver Wire rank now affects only
acquisition; roster retention excludes below-replacement weekly ranks and
protects injury-uncertain, above-replacement ROS players. League-scored season
and last-two-week performance provide a bounded modifier. Same-position ROS,
nonnegative-lineup, and retention gates prevent destructive drops. K/DST can
use weekly, ROS, and league-scored season/recent ranks when projections do not
settle the choice. Search schema 10 returns a nine-item claim plan with shared-
drop alternatives identified.

The fresh read-only `fourth_and_20` proof protected Caleb Williams and Rico
Dowdle and exactly reproduced the four requested skill moves and two kicker
moves. Current defensive evidence changed after the user's dated list and now
ranks Minnesota, New England, and Carolina; Cincinnati fell to DST17 for the
week and was not forced into the result. The run evaluated 57 candidates,
pruned 75, and performed no Sleeper write. Ruff and all 661 tests pass. The
40/35/25 calibration remains league-local and was not transferred.

WA-024 completed September 22, 2026 (America/Los_Angeles). Waiver now combines
normalized weekly, Waiver Wire, and selected-panel ROS ranks at initial
50/30/20 weights. Missing ranks are neutral and the remaining weights
renormalize. The score applies to both adds and drops and owns the skill-player
value comparison. Waiver Wire uses the three most accurate trustworthy current
contributors when at least three are available; otherwise it uses FantasyPros
Latest ECR. Trade expert policy remains unchanged.

The read-only `fourth_and_20` proof selected Pat Fitzmaurice, Derek Brown, and
Andrew Erickson for Waiver Wire evidence and Pat Fitzmaurice, Derek Brown, and
Scott Pianowski for ROS evidence. It evaluated 57 candidates exactly, pruned 75
lower-valued candidates with audited bounds, and performed no Sleeper write.
All 658 tests and Ruff pass.

Trade TA-1309 completed September 21, 2026 (America/Los_Angeles). TA-1310
remains planned for separate league-local empirical calibration when
sufficient dated evidence exists.

TA-1309 replaced the whole-universe chart gate with explicit per-target and
per-package pricing coverage. Current chart prices remain primary; missing
current prices use one compatible archived prior-week chart for an entire
candidate package, visibly indicative and never current-market FAIR. An
unpriced asset without either chart is excluded and counted. Fresh read-only
searches in both leagues used current chart prices; one yielded four modeled
offers, the other none. Prior-week behavior was verified on fixtures because
there is not yet an older local chart. All 649 tests and Ruff pass. Details:
`docs/COMPLETED_TRADE_ASSISTANT_TA_1309.md`. The earlier failed gate is retained
as chronology in `docs/TRADE_ASSISTANT_TA_1309_GATE_2026-09-21.md`.

TA-1308 completed record: `docs/COMPLETED_TRADE_ASSISTANT_TA_1308.md`.
The deterministic per-league study harness remains available, but the local
export audit found no complete historical calibration corpus. No empirical
parameter was promoted. All 643 tests and Ruff pass; no live finder was run.

TA-1301 selected the documented Stats Guy Fantasy API as the weekly redraft
trade-market provider, with an authorized local import and explicit
`ECR-PROXY` as fail-closed fallbacks. The provider offers separately calculated
1QB and superflex redraft values, Sleeper player IDs, daily provider timestamps,
historical values, and application-compatible terms. Its market is a reception
and TEP blend, so that limitation must remain visible and exact team value must
continue to use each league's Sleeper scoring.

Phase 13 now has an explicit two-axis decision contract. The finder maximizes
the user's intrinsic/team-value gain subject to a current trade-market fairness
band, partner exact-roster plausibility, legality, and downside gates. Market
price constructs and prunes offers; it never determines the football-value
winner. Entered-package evaluation remains useful without a chart and exposes
market fairness only as a separate optional or `ECR-PROXY` result.

FantasyPros has no documented weekly chart endpoint. No FantasyPros support
request was sent; no endpoint was guessed; and its article was not scraped or
reverse-engineered. Twelve documented, unauthenticated provider GETs verified
current metadata and a dated FantasyPros/CBS relative-agreement check without
retaining a player row. The dated decision is in
`docs/TRADE_MARKET_PROVIDER_CAPABILITY_2026-09-20.md`.

Completed records below are retained as handoff history and do not authorize
additional work.

Trade TA-1303 — Leakage-safe optional recent-performance evidence is complete.
Completed results now join only to compatible pregame point/rank captures at a
rolling-origin decision time, with visible exclusions, position-aware
shrinkage, and claim-disabled small/stale samples. Expert order is untouched.
Six focused tests, all 630 tests, and Ruff pass. No live history was read or
calibration promoted. Details: `docs/COMPLETED_TRADE_ASSISTANT_TA_1303.md`.

Trade TA-1307 — Target-first CLI presentation is complete. `trade targets`
shows `WATCH` cards without claiming an offer; `trade search` uses the same
cards before exact grouped offers and prints separate intrinsic/market axes.
Hashed JSON, flat CSV, offline replay, one-command evidence preparation, and
advanced overrides have synthetic CLI coverage. All 624 tests and Ruff pass.
Live use awaits a league-scoped `trade_target` policy in TA-1308; no fixture
premium was promoted. Details: `docs/COMPLETED_TRADE_ASSISTANT_TA_1307.md`.

Trade TA-1306 — Exact 2-for-1 consolidation is complete. The consolidation
lane now constructs only 2-for-1 offers, applies a visible versioned chart
premium to construction and fairness, and audits the user's starter gain/add
plus partner drop and each outgoing player's post-drop lineup/depth use.
`ECR-PROXY` makes no chart-premium claim. Four new focused tests, all 622 tests,
and Ruff pass. The fixture premium is not an empirical league calibration;
TA-1308 owns that later work. No live league or Sleeper write occurred. Details
are in `docs/COMPLETED_TRADE_ASSISTANT_TA_1306.md`.

Trade TA-1305 — Target-lane constrained package optimization is complete. All
four target lanes and four package sizes receive independent exact-evaluation
budgets and coverage. Outgoing seeds expose exact surplus, marginal cost,
market price, and partner need. Exact decisions keep intrinsic outcome, direct
fairness or `ECR-PROXY`, market-ECR corroboration, partner plausibility,
legality, depth, and downside separate. Controlled exhaustive fixtures retain
the best intrinsic result in all 16 groups, including the formerly crowded-out
consolidation 2-for-1. Six focused tests, all 618 tests, and Ruff pass. No
provider request, live league operation, calibration, recommendation, or
Sleeper write occurred. Details are in
`docs/COMPLETED_TRADE_ASSISTANT_TA_1305.md`.

Trade TA-1304 — Deterministic target discovery and evidence contracts is
complete. `BUY_LOW`, `SELL_HIGH`, `CONSOLIDATE`, and fallback `NEED_FIT` cards
now preserve intrinsic, market-ECR, direct-price or `ECR-PROXY`, team-fit,
owner-disposability, optional performance, and freshness evidence separately.
Visible lexicographic factors replace any blended score. Every target remains
`WATCH` without a passing package, owner preference is never inferred, and
partial direct-price coverage fails the complete run to a named proxy. Seven
focused tests, all 612 tests, and Ruff pass. No provider request, live league
operation, calibration, recommendation, or Sleeper write occurred. Details are
in `docs/COMPLETED_TRADE_ASSISTANT_TA_1304.md`.

Trade TA-1302 — Trade-market ingestion and normalization is complete. A
GET-only Stats Guy bulk client now produces a fresh, complete, attributed 1QB
or superflex `TradeMarketBoard` keyed by Sleeper ID, with raw changes and
scoring-blend limitations. Authorized import, hashed replay, and claim-disabled
`ECR-PROXY` fallbacks pass synthetic tests. A metadata-only live check
normalized 396 source rows into 211 1QB redraft prices without retaining a
player row. All 605 tests and Ruff pass. Details are in
`docs/COMPLETED_TRADE_ASSISTANT_TA_1302.md`.

Trade TA-1301 — Weekly trade-market provider contract is complete. The
documented Stats Guy Fantasy API supplies daily trade-derived 1QB and superflex
redraft values keyed by Sleeper player ID; authorized local import and
`ECR-PROXY` remain fail-closed fallbacks. The provider's reception/TEP blend is
explicit, exact team value remains league-scored, and no FantasyPros article
scrape, secret, provider row, recommendation, or Sleeper write occurred.

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
