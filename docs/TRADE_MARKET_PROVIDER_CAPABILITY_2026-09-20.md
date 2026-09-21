# Weekly trade-market provider capability — 2026-09-20

Task: TA-1301

Decision date: September 20, 2026 (America/Los_Angeles)

Decision: `STATS_GUY_FANTASY_API` with `AUTHORIZED_LOCAL_IMPORT` and
`ECR-PROXY` fallbacks

FantasyPros inquiry: not submitted and no longer needed

## Football consequence

RosterTheory can use an actual, recent trade market instead of guessing how
FantasyPros converts rankings and recent performance into proprietary chart
values. Stats Guy Fantasy publishes daily redraft values solved from completed
trades across many leagues. Its documented methodology weights recent trades
more heavily, so a market reaction after a large game reaches the price board
through observed manager behavior rather than an invented performance weight.

The market board remains separate from selected-expert value, FantasyPros ECR,
and league-scored team value. It is evidence of the price managers are paying,
not a projection or proof that a particular opponent will agree.

## Decision summary

Use the documented Stats Guy Fantasy public API as the preferred Phase 13
`trade-market` provider:

- `non_sf_redraft` for leagues without a superflex/2QB starter;
- `sf_redraft` for leagues with a superflex or 2QB starter;
- Sleeper player IDs as the canonical join key;
- provider `asOf` timestamps for freshness;
- current numeric values plus historical snapshots or player value history for
  changes; and
- one cached bulk synchronization per provider calculation date.

Keep two fail-closed fallbacks:

1. a provenance-checked, user-supplied authorized local import; and
2. explicit `ECR-PROXY`, which disables chart-price, chart-change, and
   consolidation-premium claims.

Do not scrape FantasyPros article HTML or fit a formula to reproduce its
unpublished chart. FantasyPros' website terms permit only a personal copy
unless reuse is authorized, and the active milestone forbids article scraping.

## FantasyPros capability evidence

Checked on September 20, 2026:

| Question | Safe evidence | Result |
| --- | --- | --- |
| Does the documented REST API expose weekly redraft trade values? | The official API catalog enumerates players, news, injuries, compare-player, rankings, consensus rankings, ranking experts, projections, player points, and MLB lineups. | No trade-value endpoint or export is documented. Do not guess a path. |
| Does HOF include production API access? | The official API access page says a paid HOF subscription includes personal, non-commercial production access to the documented read endpoints. | Yes for the documented endpoint set; this does not establish trade-chart access. |
| Does another documented FantasyPros interface expose the board? | The official MCP list includes ECR, projections, player research, league data, Trade Analyzer, and Trade Finder. | No tool is documented as returning the complete weekly chart. Advice-tool output is not a price-board export contract. |
| Does the desired artifact exist? | FantasyPros' Week 2 article is dated September 15, 2026 and says its analysts' rankings formulate the values. | Yes, as article content only. It provides no formula or authorized machine-readable source. |
| Which fields and variants are visibly published? | Table headers inspected only for capability comparison. | Name, team, value, change, bye, and near-term opponents; QB adds 2QB value/change and TE adds TEP value/change. Stable player IDs are not displayed. |
| What is the visible coverage? | Section headings in the current article. | QB, RB, WR, and TE. K and DST are not shown. Reception variants are not identified in the visible schema. |

## Selected provider capability evidence

Stats Guy Fantasy documents a public, unauthenticated API specifically for
trade-derived dynasty and redraft values.

| Contract item | Evidence and decision |
| --- | --- |
| License | The API terms permit use in applications, tools, and analyses. Personal/internal use does not require attribution; a publicly distributed product displaying the data must visibly credit and link to Stats Guy Fantasy. Wholesale republication as a competing dataset is prohibited. |
| Method | Values solve completed trades as approximate equations across many leagues. Recent trades receive greater weight, older trades fade smoothly, and calculation runs occur roughly daily. |
| Formats | `non_sf_redraft` and `sf_redraft` are calculated as separate markets. The public board is otherwise a scoring-format blend; it does not expose PPR/half-PPR/standard or TEP query variants. That limitation must be visible. |
| Freshness | `asOf` is the provider calculation timestamp, not retrieval time. Redraft updates during the fantasy season and freezes in the offseason. Current-season use requires the latest published calculation date. |
| Identity | Every player uses a Sleeper player ID, directly matching RosterTheory's league ownership source. |
| Value | Each ranking row has a numeric `value`; rank and positional rank are derived from the served values. |
| Change | Player detail exposes 7-day and 30-day value changes. The history endpoint exposes dated values. TA-1302 should derive the report's prior-published-board change from consecutive verified snapshots rather than spend one request per player. |
| Coverage | Documented positions are QB, RB, WR, and TE. A live one-row query reported 211 players for 1QB redraft and 225 for superflex redraft. K, DST, IDP, and draft picks are outside the redraft board. |
| Request cost | The documented limit is 60 requests per minute. Responses include remaining/reset headers. The provider recommends one bulk `/players` synchronization per day. |
| History | Daily snapshots are documented from September 1, 2025. Date lookup resolves to the latest snapshot on or before the requested date with a 14-day lookback. |
| Quality controls | The methodology filters incompatible leagues, FAAB-heavy and oversized trades, low-diversity player samples, outliers, and persistently anomalous leagues. Clean 1-for-1 trades receive more weight than large packages. |

### Live schema probe

Three documented, read-only GET requests were made on September 20, 2026. No
authentication or secret was used, and only metadata—not player rows—was
retained in this record.

| Request | Safe result |
| --- | --- |
| `GET /api/v1/rankings?format=non_sf_redraft&limit=1` | `asOf` `2026-09-20T13:01:05.336Z`; total 211; row has a non-empty player ID and integer value. |
| `GET /api/v1/rankings?format=sf_redraft&limit=1` | Same `asOf`; total 225; row has a non-empty player ID and integer value. |
| `GET /api/v1/trades/most-traded?days=7` | Both redraft format groups were present with ten aggregate entries each. This endpoint is optional context, not a price input. |

### Cross-source market sanity check

The provider's September 15 historical snapshot was compared with the
FantasyPros and CBS Sports Week 2 charts published that day. Raw point scales
were not compared because each source defines its own units. Player overlap and
relative ordering were compared after normalizing names, using CBS half-PPR
where its chart exposes scoring variants.

| Comparison | Top-25 overlap | Shared-pair ordering agreement | Top-10 overlap |
| --- | ---: | ---: | ---: |
| Stats Guy vs. FantasyPros | 80% | 79.5% | 9/10 |
| Stats Guy vs. CBS Sports | 92% | 86.2% | 9/10 |
| FantasyPros vs. CBS Sports | 84% | 80.5% | 8/10 |

Position-level Stats Guy ordering agreement ranged from 85.6% to 92.3% against
FantasyPros and from 80.2% to 92.2% against CBS. This is evidence of relative
market agreement, not proof of future player performance or of any individual
manager's willingness to trade. Reception-format ambiguity, tied CBS values,
and the Stats Guy scoring blend limit exact comparisons. The result is strong
enough to use the board as the finder's market-price axis while keeping exact
league-scored intrinsic/team value independent.

Four additional documented GETs retrieved the Stats Guy QB, RB, WR, and TE
top-20 historical rankings for `2026-09-15`. The source rows were inspected for
this comparison but were not saved or committed.

TA-1302 made five additional documented schema/implementation GETs: one
format-specific ranking check, three bulk-player shape/type checks, and one
end-to-end live normalization check through the implemented client. The final
check used one `/players` request and reported only metadata: 396 source rows,
211 normalized 1QB redraft prices, provider timestamp
`2026-09-20T13:01:05.336Z`, complete status, two scoring-blend warnings, and
present attribution. No player row was printed, saved, or committed.

## Approved provider contract for TA-1302

TA-1302 may implement these modes:

### `STATS_GUY_FANTASY_API`

- Use documented GET endpoints only.
- Prefer one cached bulk `/players` synchronization per provider calculation
  date; never poll faster than the documented cadence.
- Record provider name, retrieval time, `valuesAsOf`, selected redraft format,
  response count, resolved count, missing/ambiguous IDs, and source URL.
- Select `sf_redraft` only when the actual league has a superflex or 2QB
  starter; otherwise select `non_sf_redraft`.
- Reject missing, stale, nonnumeric, duplicate-ID, or partial required-player
  coverage rather than filling prices.
- Preserve the raw provider value. Never treat it as projected points or
  subtract it directly from VORP.
- Derive week-over-week change from two provider-dated complete snapshots on a
  consistent format. Do not use retrieval timestamps as publication dates.
- Treat reception scoring and TEP as unsupported board dimensions. Exact team
  value still comes from Sleeper scoring; chart-specific claims must disclose
  the market blend and must not pretend to be league-exact.
- Include visible provider attribution whenever values appear in the public
  CLI/report output, even though personal use alone would not require it.
- Store provider rows only in ignored cache/evidence locations. Commit only
  synthetic fixtures.

### `AUTHORIZED_LOCAL_IMPORT`

- Accept only a user-supplied file whose provenance states provider,
  authorization basis, publication date/week, season, export time, and format.
- Require stable provider IDs or complete, unambiguous canonical identity
  reconciliation.
- Require numeric values, current publication week/date, and complete declared
  positional coverage.
- Preserve raw values and provenance locally without redistributing them.

The implemented JSON boundary uses these top-level fields: `provider`,
`authorization_basis`, `publication_at` or `publication_date`, `exported_at`,
`season`, optional `week`, `format`, `declared_count`, and `rows`. Optional
`source_url`, `attribution`, `scoring_variant`, `te_premium_variant`, and
`league_scoring_exact` fields make limitations more precise; omitted scoring
variants remain visibly `UNSPECIFIED`. Each row requires `player_id` (the
canonical Sleeper ID), `position`, `overall_rank`, `position_rank`, and
`value`; provider changes are optional. The import fails closed on provenance,
format, freshness, identity, count, numeric, or required-player coverage
errors.

### `ECR-PROXY`

- Use the existing complete, horizon-matched selected-expert and market-ECR
  boards.
- Emit no fabricated `TradeMarketBoard`.
- Disable chart price, chart change, chart fairness, and consolidation-premium
  claims.

## Request and data-handling audit

- Successful Stats Guy Fantasy API requests: **12 documented GETs**.
- Authenticated FantasyPros API requests: **0**.
- Guessed or undocumented endpoint requests: **0**.
- Article HTML scraping requests: **0**.
- Provider player rows saved or committed: **0**.
- Secrets printed, copied, or transmitted: **0**.

## Sources

FantasyPros:

- <https://www.fantasypros.com/api-data/>
- <https://support.fantasypros.com/hc/en-us/articles/49749297704475-How-do-I-request-access-to-the-FantasyPros-API>
- <https://support.fantasypros.com/hc/en-us/articles/55238312588571-What-tools-are-available-in-the-FantasyPros-MCP-Server>
- <https://www.fantasypros.com/about/legal/>
- <https://www.fantasypros.com/2026/09/fantasy-football-trade-value-chart-week-2-2026/>

CBS Sports:

- <https://hubapi.cbssports.com/fantasy/football/news/dave-richards-week-2-trade-chart-and-rest-of-season-fantasy-football-rankings-help-you-win-now/>

Stats Guy Fantasy:

- <https://statsguyfantasy.com/developers/docs>
- <https://statsguyfantasy.com/methodology/how-values-work>
- <https://statsguyfantasy.com/methodology/packages-and-the-value-curve>
- <https://statsguyfantasy.com/methodology/data-quality>
- <https://statsguyfantasy.com/terms>
- <https://statsguyfantasy.com/data-sources>

## Exit decision

TA-1301 selects `STATS_GUY_FANTASY_API` as the documented trade-market source.
Its direct observation of completed trades is a better market-price input than
reverse-engineering FantasyPros' unpublished transformation. Authorized local
import and `ECR-PROXY` remain explicit fallbacks. The evidence is sufficient to
activate TA-1302 deliberately; this record does not itself authorize TA-1302.
