# Runtime input and refresh contract

Status: OS-014 contract, September 16, 2026

This document is the normative input contract for the Draft, Trade, and Waiver
assistants. Follow-on tasks implement it. It deliberately makes the ordinary
workflow shorter: a decision command prepares its own inputs instead of asking
the user to remember a sequence of refresh commands.

## Ordinary-use rule

`draft`, `trade`, and `waiver` decision commands must invoke the same input
planner as `roster-theory inputs prepare` before analysis:

1. Resolve the league and season from the selected config entry. An explicit
   `--season` must match that entry.
2. Reload and validate user decisions on every run.
3. Build a side-effect-free plan and show provider calls and local writes on
   human stderr before executing them where practical. JSON stdout stays one
   value; planned and completed effects are fields in that value.
4. Reuse complete evidence inside its freshness window. Automatically fetch or
   deterministically derive stale provider evidence within provider budgets.
5. Validate scope, horizon, completeness, freshness, identity, and provenance.
6. Run the assistant only when every required input is ready. Never substitute
   one horizon, league, or season for another.

Users therefore do not need to run a refresh command before normal use.
Explicit input commands remain available for setup, inspection, forced refresh,
offline validation, automation, and troubleshooting. `--offline` forbids
provider calls and fails visibly when a required cache is not ready. `--dry-run`
prints the plan without provider calls or writes. `--refresh force` bypasses
otherwise-fresh fetchable caches but never overwrites a human decision.

No input operation may make a Sleeper pick, submit a trade or waiver claim,
change a lineup, or print credentials or private provider/league identifiers.

## Authority classes

- `provider_fact`: fetched or imported evidence whose authority remains the
  named source. It may be cached and deterministically normalized.
- `derived_fact`: reproducible output from declared provider facts and league
  settings. Its provenance must name every input hash.
- `user_decision`: league policy, trusted-expert membership, calibration, or an
  exception. A command may scaffold, import, and validate it, but may not invent
  it. A documented deterministic selection rule may produce a proposal; it is
  not approved until its provenance and approval are recorded.
- `user_identity`: private configuration that identifies the user's account or
  league. It is validated locally and redacted from reports.

Provider data may be shared only when its raw meaning is independent of league
settings. Policies, calibrations, availability, scored projections, boards, and
results remain league-scoped. Sharing a raw input never transfers a conclusion.

## Season-aware command namespaces

Provider and reproducible runtime-input operations live beneath
`roster-theory inputs`. Private identity, policy, and override operations live
beneath `roster-theory setup`:

```text
roster-theory [--config PATH] inputs status LEAGUE [--season YEAR] [--assistant draft|trade|waiver|all] [--data-dir DIR] [--json]
roster-theory [--config PATH] inputs prepare LEAGUE [--season YEAR] [--assistant draft|trade|waiver|all] [--data-dir DIR] [--output PATH] [--offline] [--dry-run] [--refresh auto|force] [--json]
roster-theory [--config PATH] inputs refresh LEAGUE [--season YEAR] --artifact ID [--data-dir DIR] [--output PATH] [--dry-run] [--json]
roster-theory [--config PATH] inputs validate LEAGUE [--season YEAR] [--artifact ID] [--input PATH] [--data-dir DIR] [--json]
roster-theory [--config PATH] setup init [--replace] [--dry-run] [--json]
roster-theory [--config PATH] setup import --input PATH [--replace] [--dry-run] [--json]
roster-theory [--config PATH] setup scaffold LEAGUE [--season YEAR] --artifact ID [--update-config] [--replace] [--dry-run] [--json]
roster-theory [--config PATH] setup override add|remove LEAGUE --kind expert|identity --scope SCOPE --subject NAME --action ACTION --reason REASON --evidence-date YYYY-MM-DD --source SOURCE [--update] [--dry-run] [--json]
roster-theory [--config PATH] setup list|validate [LEAGUE] [--json]
roster-theory [--config PATH] setup show-redacted [LEAGUE] [--artifact ID] [--json]
roster-theory setup explain [ARTIFACT] [--json]
```

`prepare` is the public form of the planner automatically used by assistants.
`status` and `validate` are offline. `refresh` accepts only `provider_fact` or
`derived_fact` artifacts. `setup scaffold`, `setup import`, and audited
`setup override` operations are the paths for `user_decision` artifacts.
Private writes are atomic, previewable, refused by default when a destination
exists, and backed up before an explicit update or replacement.

Default paths are derived from the configured season, never a hard-coded year:

```text
data/cache/{provider}/{season}/...                 raw/private provider cache
data/cache/{assistant}/{league}/{season}/...       league-local live cache
data/manual/{provider}/{season}/...                authorized imports
data/manual/policies/{league}/{season}/...         user decisions
data/exports/{assistant}/{league}/{season}/...      derived evidence/results
```

Configured policy paths continue to resolve relative to the config file.
Explicit paths resolve from the current directory. Stored manifests use
normalized paths but reports expose private paths only when the user explicitly
requests details.

## Stable JSON result

Every `inputs` command emits schema `roster-theory.inputs/v1`. Fields are
additive within v1; existing meanings and types do not change. A failed command
still emits one object in `--json` mode and exits nonzero.

Required top-level fields are:

```json
{
  "schema_version": "roster-theory.inputs/v1",
  "operation": "prepare",
  "status": "ready",
  "league": "league_alpha",
  "season": 2099,
  "assistant": "waiver",
  "mode": "auto",
  "dry_run": false,
  "artifacts": [],
  "provider_calls": [],
  "writes": [],
  "summary": {"ready": 0, "refreshed": 0, "blocked": 0, "declined": 0},
  "errors": [],
  "sleeper_write_performed": false
}
```

Each artifact entry contains `id`, `authority`, `scope`, `horizon`, `status`,
`freshness_rule`, `path`, `source`, `captured_at`, `content_hash`, `action`, and
`reason`. Nullable values remain present. Allowed status values are `ready`,
`refresh_planned`, `refreshed`, `missing`, `stale`, `invalid`, `blocked`, and
`declined`. Provider-call entries contain a redacted provider, endpoint class,
budget cost, cache disposition, and status. Write entries contain the artifact
ID, destination, overwrite flag, and status. Errors contain stable `type`,
`artifact`, and `reason` values plus a safe `next_command`; they never contain an
API key, Sleeper ID, raw provider response, or private path by default.

The synthetic fixtures in `tests/fixtures/runtime_inputs/` are executable
examples of this contract. Their shared provider paths are identical; every
league policy and derived output path is distinct.

## Runtime prerequisite inventory

Freshness values below are maximum defaults. A narrower existing assistant or
policy gate wins. All inputs are revalidated before use even on a cache hit.

| Artifact ID | Authority / scope | Decision horizon and freshness | Default ignored path | Command behavior | Fail closed |
| --- | --- | --- | --- | --- | --- |
| `league.config` | `user_identity`; config-wide, selected per league | Current entry; reload every run; season must match provider state | Per-user config or explicit `--config` | `setup init`/`import`/`owner`/`add-league`; `setup validate` is offline | Missing/ambiguous owner, league, roster, scoring, season, or draft identity blocks the affected assistant |
| `policy.draft_preferences` | `user_decision`; league + season | Preseason Draft only; hash and validate every run | Configured policy path | `scaffold`, `import`, `validate`; never auto-create values | Missing or cross-league policy blocks Draft recommendation, not data refresh |
| `policy.trade_decision` | `user_decision`; league + season | In-season Trade; hash and validate every run | Configured policy path | Same | Blocks Trade evaluation/diagnosis/search |
| `policy.trade_search` | `user_decision`; league + season | In-season Trade search; hash and validate every run | Configured policy path | Same | Blocks Trade search only |
| `policy.waiver_decision` | `user_decision`; league + season | In-season Waiver; hash and validate every run | Configured policy path | Same | Blocks Waiver evaluation/search |
| `policy.waiver_wire` | `user_decision`; league + season | In-season trusted-expert and evidence rules; hash and validate every run | Configured policy path | Same | Blocks policy paths that require Waiver Wire evidence |
| `accuracy.draft` | FantasyPros `provider_fact`; shared raw evidence | Completed historical Draft seasons; refresh after a new final accuracy season is available | `data/manual/fantasypros/{season}/draft_accuracy.csv` | `refresh` when authorized endpoint supports it; otherwise `import` with source, period, and hash | Missing required seasons/categories or redistribution-unknown data blocks expert weighting |
| `accuracy.inseason` | FantasyPros `provider_fact`; shared raw evidence | Completed weekly accuracy seasons; review at season setup | `data/manual/fantasypros/{season}/inseason_accuracy.csv` | `refresh` or provenance-checked `import` | Incomplete history blocks trusted-pool proposal/validation |
| `experts.draft_pool` | documented selection rule plus explicit `user_decision`; league + season | Preseason Draft; recheck availability and ranking dates on prepare; skill ballots default to 14 days | `data/manual/policies/{league}/{season}/draft_experts.csv` | Refresh candidate facts automatically; `scaffold` proposal, explicit import/approval for membership | No silent expert substitution; missing approved pool blocks selected-expert ranking |
| `experts.inseason_pool` | documented selection rule plus explicit `user_decision`; league + season | Trade/Waiver; recheck eligibility and availability each prepare; source eligibility defaults to 48 hours | `data/manual/policies/{league}/{season}/inseason_experts.csv` | Same | Missing, stale eligibility, or unavailable approved experts is visible and blocks selected-expert claims |
| `experts.overrides` | `user_decision`; league + season | Same horizon as target pool; load/hash each run | `{config_dir}/policies/{league}/{season}/expert-overrides.csv` | `setup scaffold` and explicit audited `setup override add/remove`; an empty scaffold is valid | Never manufacture an exception; invalid override blocks the affected pool |
| `rankings.preseason` | FantasyPros `provider_fact`; shared raw ballots, league-scoped weighted board | Preseason Draft only; auto-refresh absent/stale ballots, with 14-day skill-ballot maximum | `data/cache/fantasypros/{season}/draft_rankings/`; derived board in `data/exports/draft/{league}/{season}/` | `refresh`; normal Draft prepare refreshes automatically | Wrong scoring/horizon, stale, partial, or unmatched rows block readiness |
| `rankings.weekly` | FantasyPros `provider_fact`; shared raw response, league-scoped use | Specific NFL week; Trade default 12 hours; Waiver uses its stricter bundle/policy gate | `data/cache/fantasypros/{season}/week-{week}/rankings/` | `refresh`; auto on Trade/Waiver prepare | A weekly rank may not stand in for ROS or preseason value |
| `rankings.ros` | FantasyPros `provider_fact`; shared raw response, league-scoped selected board | Rest of season; response default 24 hours, approved-expert availability 12 hours, contributor ballots maximum 14 days | `data/cache/fantasypros/{season}/ros/` | `refresh`; auto on Trade/Waiver prepare | Stale/incomplete selected or market coverage is reported and affected decisions fail closed |
| `projections.preseason` | FantasyPros `provider_fact`, then league-scored `derived_fact` | Full configured season; refresh on Draft prepare when missing/stale or source version changes | Raw cache under FantasyPros; board under `data/exports/draft/{league}/{season}/` | `refresh`; automatically score from actual Sleeper settings | Missing positions, identity, or scoring fields block the Draft board |
| `projections.weekly` | FantasyPros `provider_fact`, then league-scored `derived_fact` | Specific week; default two-hour provider cache; Waiver's complete bundle remains valid for at most five minutes | `data/cache/fantasypros/{season}/week-{week}/projections/` | `refresh`; auto on Trade/Waiver prepare | Missing required player/position coverage blocks affected comparisons; only proved inactive/bye exceptions apply |
| `adp.preseason` | FantasyPros or Sleeper `provider_fact`, source-labelled | Preseason Draft; refresh at prepare when absent or older than 24 hours | `data/cache/{provider}/{season}/adp/` | `refresh`; auto for Draft when ADP is required | Never blend unlabeled sources; absent ADP blocks ADP-dependent analysis but not rank-only modes that declare it optional |
| `news.current` | authorized provider `provider_fact`; shared raw item, league-scoped relevance | Current material news; default 12 hours, or the narrower Waiver input gate | `data/cache/{provider}/{season}/news/` | `refresh`; auto for in-season assistants | Unknown freshness is not “no news”; affected candidates remain unproved |
| `waiver_wire.current` | FantasyPros `provider_fact` plus approved `policy.waiver_wire`; league + week | Current week/ROS as declared; maximum age comes from league policy and may not be widened by CLI | `data/cache/waiver/{league}/{season}/week-{week}/waiver_wire.json` | `refresh`; auto during Waiver prepare | Missing expert, wrong scoring/horizon, stale timestamp, or partial market coverage blocks policy claims |
| `nfl.schedule` | nflverse schedule data under CC BY 4.0, or authorized user import; shared raw facts | One NFL season; validate on every use and refresh daily after schedule release or when upstream changes | `data/cache/nflverse/{season}/schedule.json` or `data/manual/nfl/{season}/schedule.json` | `refresh` from pinned nflverse release asset with attribution/provenance; `import` is the fallback | Season mismatch, fewer than 32 teams, incomplete weeks/byes, unknown source, or failed hash blocks bye/horizon analysis |
| `identity.players` | Sleeper `provider_fact` plus explicit `user_decision` overrides; shared directory, overrides league/season-scoped | Current NFL player identity; Trade cache max 24 hours, Waiver max 5 minutes | `data/cache/sleeper/{season}/players.json`; overrides under league policy path | `refresh` directory automatically; `scaffold`/`import` ambiguous overrides | Unmatched, ambiguous, partial, or cross-season identity is reported and affected rows are not dropped |
| `sleeper.state` | Sleeper read-only `provider_fact`; league + current run | Current league, rosters, users, transactions, draft, NFL state, and scoring; maximum five minutes for ownership decisions | `data/cache/{assistant}/{league}/{season}/sleeper_state.json` | `refresh`; always auto when stale | Network failure, season disagreement, incomplete rosters/settings, or ambiguous owner blocks decisions; no writes to Sleeper |

## NFL schedule source decision

The automated source is the `schedules` release from
[`nflverse/nflverse-data`](https://github.com/nflverse/nflverse-data/releases/tag/schedules).
The repository identifies it as NFL game/schedule data and documents access via
`load_schedules()`. The data repository is licensed under
[CC BY 4.0](https://github.com/nflverse/nflverse-data/blob/main/LICENSE.md),
which permits reuse and adaptation with attribution and change notices.

Implementation must download a pinned release asset over HTTPS, retain source
URL, retrieval time, upstream release/asset identity, content hash, license,
attribution, and transformation version, and derive byes only from complete
regular-season rows. RosterTheory will not ship a real schedule in its source or
wheel. Local normalized caches remain ignored. Reports and manifests attribute
nflverse and state that RosterTheory is not endorsed by nflverse or the NFL.
If the asset, license, schema, or completeness cannot be verified, the command
must decline automatic use and direct the user to `inputs import` with the
existing complete schedule schema and provenance fields; it must not fall back
to NFL.com scraping or a hand-edited unproven file.

## Two-league isolation contract

`league_alpha` and `league_beta` fixtures intentionally share raw schedule,
FantasyPros, and Sleeper player-directory paths. They use different league
config entries, scoring, policies, current Sleeper state, derived boards, and
results. Tests require all `league`-scoped paths to contain the matching league
key and prohibit either fixture from naming the other league in policy or
output paths. A cache hit in one fixture can satisfy only a `shared` provider
artifact in the other; it can never satisfy policy, calibration, readiness, or
result status.
