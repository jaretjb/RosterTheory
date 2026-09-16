# Trade Assistant provider feasibility — 2026

Captured September 4, 2026 (America/Los_Angeles). This is the dated evidence
for TA-101 through TA-106. It is conditional Trade context, not a startup
steering file. The schema-only machine reports are ignored personal artifacts
under `data/exports/trade/`.

## Decision summary

Fresh Sleeper ownership is complete and weekly point inputs are feasible. The
intended selected-expert-versus-market MVP is **conditionally feasible**, but
it is not truthful to activate full mode before two gates are resolved:

1. FantasyPros has not published 2026 ROS ranks before Week 1. A request with
   `type=ROS` currently returns Draft Half PPR data and explicitly reports
   `fallback_for=ROS`. RosterTheory must reject that fallback.
2. No usable 2021–2025 multi-year *ROS-specific* expert-accuracy leaderboard
   or API field was found. Recent weekly in-season accuracy is available, but
   using it to choose ROS contributors would be a disclosed proxy and requires
   user approval.

Approved path: multi-year weekly in-season accuracy is the authority for
selecting the best in-season experts. Before ROS ranks publish, their current
weekly rankings and full weekly ECR form separate boards labeled
`WEEKLY-PROXY`; weekly projections supply the current and remaining-horizon
point evidence. When true ROS becomes available, both boards switch together
to ROS while retaining the same in-season expert-selection history.

## Sleeper evidence (TA-101 and TA-102)

The GET-only probe captured NFL state, league, users, rosters, Weeks 1–17
matchups and transactions, both brackets, the player directory, and optional
add/drop trends. It stores field shapes, counts, timestamps, and safe league
aggregates—not raw rows.

| Check | Live result |
| --- | --- |
| League/status | 2026; `in_season`; NFL state Week 1 |
| Teams/owners | 10 rosters returned of 10 declared; 10 unique owners |
| Ownership integrity | 150 roster slots; 150 unique players; 0 duplicates |
| Current user | Resolves exactly once to roster 2; 15 players; 9 starters |
| Lineup | QB, 2 RB, 2 WR, TE, WR/RB FLEX, K, DEF; 6 bench |
| Reserve/IR | `reserve_slots=0`; no user reserve players |
| Trading | `disable_trades=0`; raw deadline value `99` retained without inferred semantics |
| Playoffs | 6 teams; starts Week 15; 3 bracket rounds; championship Week 17 |
| Matchups | 10 team rows and 10 populated matchup IDs in every Week 1–17 |
| Player identity | 12,226 directory entries; shared external IDs include Yahoo, ESPN, SportsData and others |

Sleeper therefore supplies authoritative current ownership, league rules,
fantasy matchup horizon, brackets, transactions, player availability fields,
and identity bridges. It does not supply a documented full NFL schedule feed.
The adapter exposes no transaction-writing method.

## FantasyPros evidence (TA-103)

The reproducible probe made 10 paced requests. The complete Phase 1 exploration
used **31 successful requests**, including validation of fallbacks, individual
expert filtering, archived ROS behavior, future-week projections, and expert
accuracy fields. No API key or licensed player rows were printed or saved. The
server returned no rate-limit headers, so the project must continue enforcing
its one-request-per-second and 500-request-per-day limits itself.

| Capability | 2026 finding | MVP treatment |
| --- | --- | --- |
| ROS market ECR | API supports it, but pre-Week-1 request falls back to Draft | Required; reject fallback and wait for real ROS |
| Individual ROS ballots | Filtering works with verified duplicated-ID syntax; current result still Draft fallback | Required for selected board once ROS publishes |
| Archived ROS ranks | 2025 request returns true ROS Half PPR: 106 RBs, 9 contributors | Confirms endpoint semantics |
| Weekly ECR | Available for Week 1: 174 RBs, 27 experts | Weekly context, never a silent ROS substitute |
| Current weekly projections | Available: 124 RBs with raw stats and half-PPR point fields | Required weekly matrix input |
| Future weekly projections | Weeks 15 and 17 returned populated rows before those weeks | Sum current-through-17 weekly projections for remaining-horizon distribution |
| Direct ROS projections | Unsupported in observed behavior; `week=ROS` is ignored/falls back | Do not claim a direct ROS projection feed |
| Structured availability | Sleeper directory has injury/practice fields | Sleeper primary; FantasyPros injury news optional context |
| Historical player points | 2025 endpoint available for PPR; documentation also lists STD | Study input; derive no half-PPR history without audited matching data |
| Direct Sleeper player ID | Not present in FantasyPros base player rows | Join by shared stable external IDs; ambiguity stops |
| Current selectable experts | 29 returned; 23 have weekly accuracy data | Candidate pool only after approved methodology |

Future weekly ECR was not populated for Week 15. That is acceptable: future
weekly ranks are optional, while future weekly projections provide the common
point curve and actual current ROS ballots provide the two value orderings.

## Schedule and bye provenance (TA-104)

Use three explicit layers:

- Sleeper league settings and winner bracket define the fantasy evaluation and
  playoff horizon (Weeks 1–17; playoffs Weeks 15–17 for League Alpha).
- The official NFL schedule is the authority for team opponents, game weeks,
  and byes. Store the minimal audited season schedule in Trade-scoped config.
- FantasyPros player `bye` and current-week `opponent` fields are validation
  signals, not the full schedule authority.

If any evaluation week lacks a verifiable NFL game/bye mapping, full remaining-
season evaluation stops or is explicitly labeled schedule-partial.

## Expert-accuracy coverage (TA-105)

FantasyPros treats Draft, weekly in-season, and ROS accuracy as separate skills.
Its ROS methodology describes Tuesday snapshots for Weeks 2–16, Half PPR
scoring, and heavier weight on earlier snapshots. This explains the absence of
2026 ROS ranks before Week 1, but does not provide the required recent annual
leader tables.

The audit found annual weekly in-season leaderboards for 2021–2025 and current
weekly accuracy metadata. It found a dedicated public ROS leaderboard for 2020,
but no equivalent usable multi-year ROS tables for 2021–2025 and no ROS accuracy
field in the probed expert API. Draft accuracy remains prohibited as authority.

This is not a blocker: the user confirmed that FantasyPros does not provide ROS
expert-accuracy rankings and selected weekly in-season accuracy as the correct
authority. It must never be relabeled ROS accuracy.

## Capability and source matrix (TA-106)

| Required input | Primary | Fallback | Stop condition |
| --- | --- | --- | --- |
| Current ownership/rules | Sleeper live GET | None | Missing, stale, duplicate, or ambiguous roster |
| Fantasy horizon | Sleeper settings/bracket | Explicit manual confirmation | Unknown playoff end |
| NFL games/byes | Audited official NFL schedule config | None | Missing evaluation week/team |
| Market ROS ordering | FantasyPros true ROS ECR | `ECR-ONLY` only with approval | Draft fallback or incomplete universe |
| Selected ROS ordering | Actual current ROS ballots selected by approved accuracy method | Market ECR shrinkage for ballot omissions | No approved selector/current contributors |
| Common point scale | Sum of FantasyPros weekly consensus projections over remaining weeks | Rank-only mode with approval | Missing likely-starter week coverage |
| Availability | Sleeper injury/practice fields | FantasyPros injury news warning | Unresolved key-player status for automation |
| Historical outcomes | FantasyPros player points when licensed/complete | Broad scenario-only risk mode | Partial data presented as calibrated risk |

### Planned live call cost

A refresh planner must count fresh cache hits before retrieval. A conservative
cold refresh is expected to use:

- Sleeper: league, users, rosters, NFL state, player directory if older than 24
  hours, required matchup/transaction weeks, and brackets. Sleeper has no paid
  daily budget; calls remain GET-only and cached appropriately.
- FantasyPros rankings: one complete ROS ECR request per required position or
  one verified multi-position request, plus only the approved selected expert
  ballots. Deduplicate identical requests.
- FantasyPros projections: at most one verified multi-position request per
  remaining NFL week (17 or fewer), rather than one request per position/week.
- Optional injury news and historical study calls occur only when their output
  is used and budget remains.

The exact count must be displayed before every refresh and may never exceed the
remaining configured daily budget.

### Freshness and degraded modes

| Dataset | Maximum age | Stale behavior |
| --- | ---: | --- |
| Sleeper league/users/rosters/state | Current run | Stop current recommendation |
| Sleeper player directory | 24 hours | Refresh |
| Current matchup/transactions | Current run | Stop or label historical |
| FantasyPros ROS ranks/ECR/projections | 24 hours | Refresh; approved ECR-only fallback only |
| FantasyPros weekly ranks/projections | 12 hours | Week-level result stops |
| Availability/news | 2 hours | Prominent warning; injured-player automation stops |
| Completed historical points | Immutable after verification | Reuse cache |

Allowed labels are `FULL`, `ECR-ONLY`, `RANK-ONLY`, `SCHEDULE-PARTIAL`, and
`OFFLINE/NON-CURRENT`. Draft ranks must never masquerade as ROS, weekly ranks
must never silently replace ROS ranks, and a degraded result cannot use full-
confidence recommendation language.

## Phase 1 recommendation

TA-101 through TA-106 have exit evidence. On September 4 the user approved
in-season accuracy for expert selection and weekly rankings/projections as the
pre-ROS proxy. The Phase 1 gate passes and Phase 2 may build feature-neutral
contracts. Every output must retain the active horizon label.

## Sources

- Sleeper API documentation: https://docs.sleeper.com/
- FantasyPros API v2 documentation: https://api.fantasypros.com/v2/docs
- FantasyPros ROS accuracy methodology: https://www.fantasypros.com/about/faq/football-rest-of-season-accuracy-methodology/
- FantasyPros weekly accuracy methodology: https://www.fantasypros.com/about/faq/football-inseason-accuracy-methodology/
- FantasyPros accuracy archive: https://www.fantasypros.com/nfl/accuracy/
- FantasyPros 2020 ROS leaderboard: https://www.fantasypros.com/2021/01/2020-fantasy-football-rest-of-season-rankings-most-accurate-experts/
- Official NFL 2026 schedule: https://www.nfl.com/schedules/2026/by-week/reg-1
