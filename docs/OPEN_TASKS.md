# Draft Assistant task ledger

Updated: September 15, 2026

This is the durable task and validation ledger for the **Draft Assistant**.
`.codex/context/status/DRAFT.md` is the current Draft handoff, and `.codex/context/STEERING.md` routes
product tracks. The League Beta draft-day baseline is complete and no implementation
milestone is active. Completed records here do not authorize code,
live-policy changes, simulations, external data acquisition, or simultaneous
milestones.

The user's 2026 drafts are complete. All 2026 league-specific Draft operations
and experiments are closed. BD-901 through BD-905 and BD-908 are completed
records; no Draft tasks remain open. BD-905 completed with a failed validation
gate. Any future-cycle rollout proposal needs a newly scoped task.

Trade Assistant requirements live in `TRADE_ASSISTANT_REQUIREMENTS.md`. Its
design and separate planned backlog are `TRADE_ASSISTANT_DESIGN.md` and
`TRADE_ASSISTANT_TASKS.md`. Do not add trade implementation work to this Draft
backlog or treat any Trade planning document as an implementation milestone.

## 1. Closed: League Alpha preparation and live draft

The completed paired studies and live-draft record are retained only as private
local evidence because they contain provider-derived and league records. Do not
reopen their promoted or rejected choices without new League Alpha evidence,
and do not transfer them to League Beta.

## 2. Closed: final League Alpha operational checks

- Completed August 29: the normal-clock read-only strategy rehearsal
  reconciled all 150 picks and recommendation computation stayed below 0.43
  seconds. It did not prove click-to-API freshness; the user observed several
  slow visible refreshes, and a direct probe showed that Cloudflare could
  ignore the header-only revalidation request.
- Completed August 29: the next full read-only room supplied a stronger cache
  smoke test than required. All 839 cache-busted picks polls returned `MISS`
  with zero maximum age and no cache warning. Sleeper still provides no pick
  timestamp, so preserve user-observed click-to-screen latency separately.
- Completed August 29: the kicker-specialist cohort review reconciled the
  documentation to the active export and retained the independent 20-expert
  pool. Only four specialists overlap the Half-PPR skill pool; top-seven
  kicker order survives removal of any one cohort.
- Completed August 29: refreshed the selectable FantasyPros pools with a
  14-day skill-ranking freshness gate and Sean Koerner at the approved
  four-expert equivalent. The warranted 50-request rank-consistency audit found
  zero individual inversions and 2.14% composite inversions. Rebuilt only the
  545-player League Alpha board; it passes every readiness gate. League Beta remains
  deliberately deferred to its separate preparation milestone.
- Completed August 29: repeated sixth-RB misses across three watcher rooms and
  192 paired raw-market/human-history simulations promoted a structural cap on
  redundant same-position reserve credit. The 20% reserve weight did not
  change; no-absence value was identical and moderate/heavy weekly-use results
  improved across every rank/acquisition block.
- Completed August 30: captured a same-day Sleeper Half-PPR ADP snapshot. Keep
  it active only for Sleeper-CPU rehearsals and shadow-only in the human draft.
- Completed August 30: refreshed the full grouped FantasyPros pool and rebuilt
  only the League Alpha board; all completeness gates pass. The generated pool is
  authoritative over the superseded August 23 manual recommendation CSV.
- Completed August 30: rechecked material news and preference identities. Josh
  Jacobs is on the Commissioner's Exempt List and now receives an unconditional
  advisory availability warning; MarShawn Lloyd remains a target. The 36-entry
  League Alpha preference scope validates against the refreshed board.
- Completed August 30: the first post-cap forward mock followed all 15 Primary
  leaders, completed cleanly, produced a balanced QB2/RB5/WR5/TE1/K1/DST1
  roster, and received a 95/100 FantasyPros grade with no suggested changes.
- Completed August 30: the real league was verified and the read-only watcher
  preserved all 150 picks without a missed or stale turn. The detailed record
  remains private local evidence. No Sleeper pick was made by RosterTheory.

## 3. Preserved research ideas after the urgent draft work

### Sleeper displayed-order edge

Managers who arrive unprepared may follow Sleeper's ranked list. Preserve a
dated draft-day snapshot and measure per-manager and room-wide adherence from
forward evidence. Sleeper ADP may become a human acquisition input only after
real forward validation; CPU mocks cannot prove this edge.

### Opponent-specific tendencies

Two managers are new to League Alpha, so aggregate returning-manager survival still
works but is less individualized for those seats. Add at most one tendency at a
time when the user supplies a current manager/seat and repeatable
position/round behavior. Shrink it toward the league prior, cap its effect, and
show the counterfactual before activation. Room pace is an availability update,
not an instruction to chase a positional run.

### Longer-range construction

The bounded elite-TE exception is active only for the exact calibrated
ten-team roster and still needs forward validation. Preserve broader two-pick
and multi-round sequencing as a shadow challenger; protect the successful
rounds 1-2 behavior and do not hard-code player-specific counterfactuals. The
August 29 normal-clock room adds a narrow exact-board example: Jameson
Williams/Joe Burrow improved Jayden Daniels/Christian Watson by roughly one
rank-informed point, far below FantasyPros' claimed 21, while losing under
raw-channel deeper stress.

The later Bijan-fall watcher room's bounded reserve-construction test is now
closed. Repeated exact-room evidence and paired, disjoint simulations promoted
a structural cap on redundant same-position reserve credit; it did not change
the 20% reserve weight or create an RB/WR preference. Reopen only if forward
human-draft evidence shows the cap suppressing a reserve who can enter a legal
weekly lineup. The user explicitly rejected exploring QB2 over authored target
Stefon Diggs; do not use the weekly-use evaluator's late QB-insurance result to
open that challenger.

The August 30 Sleeper-CPU room `synthetic-rehearsal-02` adds a bounded shadow
challenger: when two-pick path scores are effectively tied, prefer the player
with materially lower next-turn survival. At 6.04 this would have taken Luther
Burden III before Jayden Daniels; the likely Burden/Daniels pair improves every
rank/stress channel over Daniels/Christian Watson. The required disjoint
50%-history test is complete: 60 paired rooms found no qualifying intervention
at `0.5/15%`, `1.0/15%`, or `2.0/10%`, and every weekly-use result tied live.
The code remains an opt-in shadow policy, but the live policy did not change.
Reopen only with additional forward human evidence; do not generalize the mixed
Tuten branch or validate human acquisition from the CPU outcome.

The forced early-RB-run study shows that current expected-value recommendations
should not chase an RB avalanche: WR-WR plus the later best available backs
comfortably beat forcing a frozen-pond RB at 2.07. It also shows that ordinary
50%-history rooms never sampled that tail and that the strong-run advantage
reverses between 10% and 20% RB13-30-only projection haircuts. Before adding
any risk display or ordering rule, obtain a defensible empirical downside model
for that tier and test it as a shadow sensitivity. Do not infer a 20% bust
penalty from this stress test, and do not change the watcher without explicit
user approval.

### Late-round upside experience

The separate `UPSIDE TARGETS` panel is the current safe boundary. Eventually
test whether, after starters are filled and calculated candidates are near
replacement, the panel should replace ordinary low-ceiling late-round
recommendations. Keep user targets, handcuffs, price floors, league scope, and
scoring conditions explicit. Do not let target status silently alter expert
ranks or projections. The panel now marks eligible targets `NOW` on the last
skill-position pick instead of claiming the user can wait through forced K/DST
picks; this display correction does not change recommendation order.

### Compact decision support

- The selected-expert disagreement warning is complete and display-only. Keep
  its weighted SD/range evidence distinct from injury or player-volatility
  claims; do not convert it into an ordering penalty without separate approval
  and validation.
- Add a compact `CLOSE` indicator only after defining a stable threshold for a
  genuinely close top decision. Do not add the rejected `NO RUSH` label;
  Kittle's 77% modeled survival still failed in a real mock.
- Make a target-table conflict conspicuous when an authored elite target says
  `NOW` but remains just outside a bounded ordering exception. The August 29
  McBride case missed the 15-point threshold by only 0.704 while the Primary
  table still led with Kyren; do not silently turn the target into a ranking
  override.
- Keep Market and Lg survival numeric and visible. Prefer short labels over
  explanatory sentences during a 60-second window.
- A friendlier local UI remains low priority. Do not add hosting, accounts,
  databases, or a framework without agreement.

## 4. Closed: League Beta preparation and draft-day watcher

The detailed League Beta operational runbook is preserved as private local evidence.
League Beta is a separate 12-team, two-flex, five-bench problem. None of the ten-team slot-4
calibration, returning-manager history, elite-TE exception, QB streaming floor,
reserve weight/cap, specialist rounds, or opponent exclusions may be inherited
without a League Beta-specific paired test.

The September 7 refresh confirmed slot 1 and all prepared league fields. The
614-player board, dated Half-PPR Sleeper ADP snapshot, 35-entry League Beta
preference scope, 20-expert kicker pool, and user-authored defense order are
ready. BD-901 corrected projection completeness; BD-902 promoted the narrow
adjacent-turn QB horizon guard after exact mock replay and paired/disjoint
stress validation. The user approved live read-only watcher use.

The 2025 league is positively identified with three returning opponents, but
it was an 8-team, 120-pick draft. It fails the required 12-team/180-pick gate,
so it is inactive and human acquisition remains raw market ADP.

The user-approved representative-slot structural screen is complete with
eight-room selection and disjoint confirmation blocks at slots 2, 6, and 11.
No final policy was promoted. Before `draft_order` was published, the retained
slot-relevant shortlist was centered 20%-30% reserve weights (10%/40%
boundaries), a 100% late-upside tie-breaker, round-9 QB and WR3-by-round-6 only
for an early seat, and adaptive versus K14/DST15 specialist timing. Forced TE,
positional tolerance, reserve cap, forced RB construction, late QB, and rounds
13-14 specialists did not advance. Those preliminary results did not authorize
a watcher change; the completed exact slot-1 result is recorded below.

The exact slot-1 selection, disjoint confirmation, fresh validation, and
32-room full-draft extension are complete. Reserve weights 10%-30% tied;
round-9 QB, WR3-by-round-6, 40% reserve weight, and fixed K14/DST15 did not
clear their gates. The late-upside tie-breaker was positive in skill-only
blocks but inert to slightly negative in the extended full 15-round draft.
The result at that checkpoint was the strict primary, expert-curve secondary,
raw-market acquisition, and adaptive specialist timing. BD-902 subsequently
preserved the strict score, added only the tested adjacent-turn QB horizon
guard, and received live read-only watcher approval.

A user-approved second phase has also completed 8,512 full policy drafts under
six acquisition environments and larger 64/128-room blocks. It directly
tested the League Alpha primary, wider/narrower market variance, RB/WR/QB/TE demand
surges, fixed QB/TE timing, two-FLEX construction, reserve rules, caps, and
specialists. WR4-by-round-8 was the only finalist, but a 128-room extension
confirmed that its QB/TE-surge benefit depends on rank channel: raw heavy
`-1.13`, live heavy `+2.35`, full-rank heavy `+5.08`. Do not promote it. Keep
WR4 scarcity as a round-8 decision alert and retain adaptive construction.
Two normal-clock, read-only Sleeper-CPU rehearsals and two September 7 mocks
pass with 180/180 picks, no stale or missed turns, and legal rosters. The final
refresh, complete test suite, and one-poll human-mode smoke check pass. At draft
time, the read-only human watcher was launched only after draft ID and slot
verification. That completed operating procedure remains private.

## 5. Closed: 2026 probabilistic multi-turn lookahead research

This section records the September 7 evidence that fixed-roster late-pick
counterfactuals can improve a completed draft while a simple deterministic
three-pick objective regresses under some opponent stresses. The current
`half_ppr_reconciled_horizon_guard` remains the baseline because BD-905 failed.
Any future promotion needs newly declared gates and target-season authoritative
evidence. Do not hard-code Brock Purdy or any other player.

Season boundary: all 2026 league-specific work is closed. A future rollout
proposal needs a newly activated milestone, target-season evidence, a passing
new offline validation, and separately proved league/format calibration. Work
must remain staged: begin with a bounded feasibility or eight-room smoke run and
report the result before extending it. No single unattended simulation batch
may exceed 15 minutes without explicit approval.

### BD-903 — Empirical acquisition uncertainty

Status: COMPLETE feasibility review, September 7. Depends on BD-902 only.

Replace the global `max(2.5, 18% of ADP)` uncertainty heuristic only if a
reproducible corpus of sufficiently recent, comparable 12-team Half-PPR drafts
is available. Fit conditional draft survival by position and ADP band; use
player-specific variance only with adequate samples and otherwise shrink to
the band prior. Preserve the current heuristic as a control, model the fact
that an available player has already survived to the current pick, and keep
live room pace and exact intervening seats explicit.

Required gate: selection and disjoint holdout drafts improve probability
calibration (Brier/log loss plus reliability bins) over the current heuristic,
with sample coverage and provenance reported. Sleeper's point-in-time ADP alone
does not establish variance. Cross-source disagreement may be a sensitivity,
not a substitute for observed pick distributions. If comparable data is not
available, stop with the heuristic and documented stress bounds.

Result: the local evidence contains four complete 12-team League Beta CPU mocks but
no comparable completed 12-team human-draft corpus. Four CPU rooms cannot
identify human player- or position-specific variance. Retain the conditioned
`max(2.5, 18% of ADP)` model, exact-seat needs, live room pace, and the existing
six acquisition stresses. No uncertainty parameter changed and no external
request was made.

### BD-904 — Bounded multi-turn rollout engine

Status: COMPLETE, September 7. BD-903 explicitly retains the current heuristic
with documented stress bounds. Tested evidence is in
`docs/COMPLETED_LEAGUE_BETA_MULTI_TURN_ROLLOUT_PROTOTYPE.md`.

Build an offline shadow evaluator that starts from the authoritative available
board, branches only over a declared small candidate set, and follows the
current adjacent pair through two opponent-contested intervals. At slot 1 this
means the current pair plus the next two user pairs. Use common random numbers,
exact roster legality, cached states, and correlated positional-run scenarios.
A bounded beam retains only the best declared number of user paths; every
pruned path and runtime cap must be auditable.

Required gate: deterministic replay with a fixed seed, no future information,
no player-specific rule, and complete outputs for unblended, primary, and
full-rank roster value, expected value, P10, and regret. This task cannot alter
the watcher or primary ordering.

### BD-905 — Offline calibration and counterfactual validation

Status: COMPLETE shadow validation, September 7. Depends on BD-904. The
September 15 failed-validation diagnostic is in
`docs/research/BD_905_FAILURE_REVIEW.md`; the former detailed public
record is absent from the current tree. The rollout remains offline
shadow-only and is rejected for promotion.

Compare the rollout shadow against the current primary in paired selection and
disjoint confirmation rooms across the six League Beta acquisition environments.
Replay both September 7 mocks and evaluate the recorded FantasyPros packages
only when the alternative path is feasible at every intervening pick. Separate
fixed-roster hindsight from opponent-redrafted rollouts.

Required gate: no material primary mean or P10 regression, no unexplained
unblended loss, stable regret improvement across seed blocks, and an explicit
accounting of how often the rollout changes a decision. A sign-changing result
stays shadow-only.

Result: two-room selection and disjoint confirmation blocks across all six
environments evaluated 48 pick-72/pick-96 decisions. The rollout changed
79.2% of selection decisions and 62.5% of confirmation decisions. Primary
mean changed from `-0.302` to `+0.079` between blocks; middle-QB/TE selection
lost `1.77` mean and `3.97` at P10; full-rank mean/regret regressed in both
blocks. All nine recorded FantasyPros packages were feasible in fixed realized
rosters, but none remained feasible in all three opponent-redraft scenarios.
The gate fails and the rollout stays offline shadow-only.

### BD-908 — Bounded top-three DST acquisition counterfactual

Status: COMPLETE offline validation, September 7. Evidence is in
`docs/COMPLETED_LEAGUE_BETA_DST_COUNTERFACTUAL.md`.

The user approved a separate draft-day test of whether the live forced-late
specialist gate suppresses a worthwhile user top-three defense. The challenger
could take Houston, Seattle, or the Rams from round 9 onward only after all
eight skill starters were covered and modeled survival to the next turn was
50% or less. It remained simulation-only and assigned no invented DST points.

Across 96 paired/disjoint full rooms, top-three acquisition improved from 0%
to 100%, but all three skill-roster mean and P10 channels regressed in both
blocks. The task fails its promotion gate. Keep the current live specialist
timing and watcher unchanged.

## Completed items that should not be reopened without new evidence

- Expert player identity order comes from selected experts; raw projections
  provide positional value spacing only.
- Raw ADP and raw projections remain preserved. Adjusted ADP is acquisition-
  only, and the old round-position tendency is disabled when positional-slot
  history is active.
- Market and Lg survival columns, room timing, compact red warnings (including
  selected-expert disagreement), aligned table, removal of recent
  picks/roster-use from the console, and green-only `NOW` upside targets are
  implemented.
- The defense order is HOU, SEA, LAR, DEN, LAC, JAX, PHI, PIT, BAL, DET for both
  drafts; it changes defense identity, not the round in which DST is selected.
- The watcher is read-only. Draft-pick requests use a unique cache key on each
  poll and preserve Cloudflare cache-status/age diagnostics in evidence.
