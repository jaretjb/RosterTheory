# RosterTheory

![Roster Theory in oversized, chunky bright-yellow 1990s arcade lettering](docs/assets/roster-theory-terminal-90s.svg)

RosterTheory is a local, read-only fantasy-football decision-support toolkit
for Sleeper leagues, powered by public Sleeper league data and FantasyPros
expert rankings and projections. Complete automated Draft, Trade, and Waiver
workflows require your own FantasyPros HOF Premium API key; offline diagnostics
and analysis of previously saved or manually imported inputs can run without
one. The app combines that evidence with each league's actual scoring and
roster settings to produce auditable recommendations.

It is designed to help answer questions such as:

- Who is the best pick for this league and draft slot—not just in a generic
  rankings list?
- How likely is a target to survive until the next pick?
- Which roster constructions hold up across simulated drafts?
- Where do selected experts and the broader market disagree on player value?
- Does a trade improve both teams after lineup, depth, waiver, bye, and risk
  effects are included?
- Is a waiver add/drop worth considering with this league's current evidence?

RosterTheory never makes a Sleeper pick, sends a trade, submits a waiver claim,
or changes a lineup. It fetches public Sleeper data and prints or saves advice
for a human manager to act on.

## Public alpha status

Version 0.1.0 is a source-only public alpha. Its installation, input
preparation, evidence, validation, and read-only output contracts are designed
for repeatable use, but its recommendation policies are not universally
calibrated fantasy-football models.

The public examples and fixtures are synthetic. A real recommendation requires
fresh provider evidence, the league's actual Sleeper settings, and a separately
reviewed policy for that league and season. Never transfer calibration, audit
results, or recommendations between leagues. Missing, stale, partial,
ambiguous, or uncalibrated inputs stop visibly instead of being filled with
invented ranks.

Run `roster-theory inputs prepare` before an assistant workflow and use
`roster-theory inputs status` or `roster-theory doctor` to inspect readiness.
Refresh and audit each league again as its rosters, availability, scoring,
season, or authoritative ranking horizon changes. See the
[0.1.0 alpha release notes](docs/RELEASE_NOTES_0.1.0-alpha.md) for the precise
support boundary and known limitations.

## What it includes

### Draft Assistant

- Builds league-specific boards from historically weighted expert rankings.
- Scores projections using the league's live Sleeper scoring settings.
- Keeps expert rank, raw projection, ADP, replacement value, and provenance
  visible rather than collapsing them into an unexplained score.
- Simulates draft strategies and acquisition timing from configurable slots.
- Watches a Sleeper draft or mock in read-only mode and updates available-player
  recommendations as picks occur.
- Records evidence that can be replayed after a mock or draft.

### Trade Assistant

- Builds independent selected-expert and market-consensus value boards at the
  appropriate weekly or rest-of-season horizon.
- Diagnoses lineup needs, waiver-relative depth, byes, and scenario risk.
- Evaluates entered packages of up to four players per side, including required
  adds and drops.
- Finds selected-versus-market valuation gaps and performs bounded,
  league-wide package searches.
- Saves immutable evidence so results can be reviewed without presenting stale
  data as current.

### Waiver Assistant

- Refreshes league-specific Waiver data without making a recommendation.
- Evaluates an entered add/drop or searches proved-eligible QB/RB/WR/TE options
  from a fresh, complete input bundle and an approved league policy.
- Surfaces missing projections, ambiguous identities, availability, legality,
  and uncertainty instead of silently dropping candidates.
- Never submits a claim, changes FAAB, or edits a lineup.

Start/sit is a possible future product track; it is not implemented.

## Requirements

- Python 3.11 or newer
- A Sleeper league (Sleeper access is public and requires no credentials)
- Your own FantasyPros HOF Premium API key for complete automated ranking,
  projection, and in-season expert workflows; offline help and doctor need no key

FantasyPros free-tier responses may be useful for pipeline checks, but they are
sample-only and must not be treated as a complete draft board. A manual
FantasyPros CSV workflow is also available; see
[`docs/MANUAL_FANTASYPROS_IMPORT.md`](docs/MANUAL_FANTASYPROS_IMPORT.md).

## Install

The initial release is GitHub source-only, not published to PyPI. Clone the
repository and create an isolated environment:

```powershell
git clone https://github.com/jaret81/RosterTheory.git
cd RosterTheory
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install .
```

On macOS or Linux, activate the environment with:

```bash
source .venv/bin/activate
```

This non-editable install provides `roster-theory` and `python -m roster_theory`.
The built wheel also works outside the checkout. Contributors can instead use
`python -m pip install -e .` for an editable source tree.

## Configure your league

Create the ignored private runtime through the CLI. These commands work from a
wheel install and do not contact Sleeper:

```powershell
roster-theory setup init
roster-theory setup owner `
  --sleeper-username YOUR_NAME `
  --sleeper-user-id YOUR_USER_ID `
  --update
roster-theory setup add-league home_league `
  --season 2026 `
  --name 'Home League' `
  --league-id YOUR_LEAGUE_ID `
  --user-roster-id 1 `
  --draft-id YOUR_DRAFT_ID `
  --user-draft-slot 1 `
  --update
roster-theory setup scaffold home_league --update-config
roster-theory setup validate home_league
```

`setup init`, `owner`, and `add-league` create `leagues.json` without requiring
the user to reproduce its shape. `setup scaffold` creates season-aware Draft,
Trade, Waiver, override, and optional contingency files. Policy scaffolds are
deliberately marked `UNCALIBRATED`; they do not become recommendation authority
until the user supplies separately supported thresholds for that league.

All setup writes are atomic. Existing files are refused unless the command has
an explicit `--update`, `--update-config`, `--replace`, or equivalent option;
accepted replacement creates a timestamped `.bak` file first. Add `--dry-run`
to preview paths without writing, including when paths contain spaces.

The default user configuration directory is:

- Windows: `%APPDATA%\RosterTheory\leagues.json`
- macOS/Linux: `$XDG_CONFIG_HOME/roster-theory/leagues.json`, or
  `~/.config/roster-theory/leagues.json` when `XDG_CONFIG_HOME` is unset

You can instead set `ROSTER_THEORY_CONFIG` or pass `--config PATH` before the
subcommand. Configuration is independent of the repository and current working
directory. The source checkout also contains
[`config/leagues.example.json`](config/leagues.example.json). A real entry
looks like this after replacing the synthetic values:

```json
{
  "owner": {
    "sleeper_username": "your_username",
    "sleeper_user_id": "your_sleeper_user_id"
  },
  "leagues": [
    {
      "key": "home_league",
      "name": "Home League",
      "league_id": "current_sleeper_league_id",
      "draft_id": "current_sleeper_draft_id",
      "season": "YYYY",
      "user_roster_id": 1,
      "user_draft_slot": 1,
      "history_league_ids": [],
      "policies": {
        "draft_preferences": "policies/home_league/2026/draft-preferences.csv",
        "trade_decision": "policies/home_league/2026/trade-decision.json",
        "trade_search": "policies/home_league/2026/trade-search.json",
        "waiver_decision": "policies/home_league/2026/waiver-decision.json",
        "waiver_wire": "policies/home_league/2026/waiver-wire.json"
      }
    }
  ]
}
```

The `key` is the short name used in commands. `league_id` is required for
snapshots and league-aware analysis. `draft_id` is used by the configured-draft
recommendation command. `sleeper_user_id` is required for owner-aware Trade
Assistant analysis. Historical league IDs are optional and should be included
only when those drafts are truly comparable to the current league.

Configured policy paths are resolved relative to `leagues.json`; explicit CLI
policy paths are resolved relative to the current directory. Every JSON policy
must declare a `league_key` exactly matching the selected league. Draft
preference CSVs must include that league in at least one `league_scope` cell.
An uncalibrated scaffold remains blocked even though its schema and league
scope are valid. Decision commands stop with a clear `uncalibrated` result
instead of reusing another league's thresholds.

Inspect private setup without exposing IDs:

```powershell
roster-theory setup list home_league
roster-theory setup show-redacted home_league --artifact trade-decision
roster-theory setup explain trade-decision
roster-theory setup validate home_league --json
```

To migrate an existing configuration, use
`roster-theory setup import --input PATH`; add `--replace` only after reviewing
the destination because an existing file is otherwise preserved.

Confirm that the configuration loads before any provider request:

```powershell
# Set this once in each new PowerShell session. Resolve-Path safely handles
# spaces in the repository path.
$env:ROSTER_THEORY_CONFIG = (Resolve-Path '.\data\manual\private_runtime\leagues.json').Path

roster-theory doctor home_league
roster-theory doctor home_league --json
roster-theory leagues

# Or select any config explicitly (the option precedes the subcommand).
roster-theory --config C:\path\to\leagues.json doctor home_league --json
```

Replace `home_league` with the `key` in your configuration. If the file is not
inside the checkout, use its absolute path instead:

```powershell
$env:ROSTER_THEORY_CONFIG = 'D:\path\to\RosterTheory\data\manual\private_runtime\leagues.json'
roster-theory doctor home_league --json
```

`$env:...` lasts for the current PowerShell process. To save the config path
for future PowerShell sessions, set a user environment variable once, then
open a new terminal:

```powershell
[Environment]::SetEnvironmentVariable(
  'ROSTER_THEORY_CONFIG',
  'D:\path\to\RosterTheory\data\manual\private_runtime\leagues.json',
  'User'
)
```

Snapshots and other personal/generated artifacts default to `data/cache/`,
`data/exports/`, and `data/manual/` relative to the directory where the command
runs; those directories are ignored in a source checkout. For wheel installs,
run from a workspace you control or pass explicit input/output paths. The CLI
does not create provider data as part of installation.

Adding a league makes the shared Sleeper, scoring, board, and simulation
machinery available; it does not make any bundled strategy calibration
portable. Treat recommendations for a new league as research until that
league's board passes its completeness checks and each decision policy has
separate evidence.

## Configure FantasyPros

Prefer setting `FANTASYPROS_API_KEY` in your environment. In a source checkout,
you may copy [`.env.example`](.env.example) to an ignored `.env` file in the
working directory:

```powershell
# Current PowerShell session only. Do not paste the real value into Git files.
$env:FANTASYPROS_API_KEY = 'your_key_here'
```

```dotenv
FANTASYPROS_API_KEY=your_key_here
```

`.env` is ignored by Git. Never paste the key into source, configuration,
command output, or a commit. The client rate-limits HOF Premium access to one
request per second, and Trade Assistant access is budgeted against 500 requests
per day.

The repository does not include FantasyPros rankings, projections, accuracy
histories, expert IDs, or selected pools. Keep authorized inputs beneath
`data/manual/fantasypros/`; the CLI defaults point there and fail when required
data is missing. The files under `examples/` document supported schemas using
invented values only. See [`docs/THIRD_PARTY_NOTICES.md`](docs/THIRD_PARTY_NOTICES.md)
for provider terms, attribution, and every retained or removed data artifact.

### Refresh provider inputs

Some inputs are refreshed by commands; others intentionally remain reviewed
local files. Installing the package does not create provider data. For normal
use, one command inspects freshness, refreshes only missing or stale provider
facts, reuses fresh evidence, and finishes with league-specific readiness and
exact next commands:

```powershell
roster-theory inputs prepare home_league --assistant all
```

Use `--assistant draft`, `trade`, or `waiver` to limit the work, or replace the
league with `--all-leagues`. Shared evidence is fetched once where possible;
policies, readiness, derived pools, and results remain isolated by league.
`--dry-run` prints the provider-call and local-write preflight without doing
either, `--offline` forbids network calls, and `inputs status` is always an
offline inspection. `--refresh force` deliberately replaces a valid fresh
cache. Preparation never creates a recommendation, calibrates a policy, or
writes to Sleeper.

| Input | How to refresh it |
| --- | --- |
| Historical Draft accuracy and the in-season expert pool | `roster-theory inputs experts refresh LEAGUE`; this creates the annual and category-level Draft inputs, current league-scoped in-season pool, replayable provider evidence, and selection audit. |
| Current Draft expert availability and rankings | `roster-theory fantasypros-grouped-rankings`; this uses the FantasyPros Premium API and writes the selected pools and weighted rankings under `data/exports/`. |
| Draft projections and ADP | `roster-theory fantasypros-league-boards --league LEAGUE`; this uses FantasyPros plus current Sleeper league settings. |
| Current Trade rankings, projections, and news | `roster-theory trade values`, `trade diagnose`, `trade evaluate`, or `trade search`; these refresh through the API and cache responses locally. |
| Current Waiver rankings, projections, availability, and Waiver Wire evidence | `roster-theory waiver inputs LEAGUE`; this installed command refreshes the required provider data and produces the search input bundle. |
| Expert and identity overrides | `roster-theory setup override add LEAGUE ...`; every change requires explicit scope, reason, evidence date, and source, and is retained in the override audit. Provider data never creates one automatically. |
| NFL schedule and byes | `roster-theory inputs schedule refresh LEAGUE`; this downloads the nflverse schedules release, validates the selected season, derives byes, and retains replayable source evidence. |

A typical preseason preparation is:

```powershell
roster-theory inputs prepare home_league --assistant draft

roster-theory fantasypros-grouped-rankings `
  --season 2026 `
  --accuracy data/manual/fantasypros/expert_accuracy_2021_2025.csv `
  --annual-accuracy data/manual/fantasypros/expert_accuracy_annual_2021_2025.csv `
  --expert-overrides data/manual/fantasypros/expert_pool_overrides_2026.csv `
  --output-dir data/exports/fantasypros_2026

roster-theory fantasypros-league-boards `
  --season 2026 `
  --league home_league `
  --rankings data/exports/fantasypros_2026/weighted_rankings.csv `
  --output-dir data/exports/league_boards_2026
```

Override files are optional. Scaffold their valid season-aware headers without
hand editing:

```powershell
roster-theory setup scaffold home_league `
  --artifact expert-overrides
```

Add an exclusion only when you have made the decision and can record why:

```powershell
roster-theory setup override add home_league `
  --kind expert `
  --scope skills_half_ppr `
  --subject 'Expert Name' `
  --action exclude `
  --reason 'Documented conflict for this pool' `
  --evidence-date 2026-09-16 `
  --source 'User review' `
  --update
```

`last_updated_override` and `anchor_equivalent` require an explicit `--value`.
Identity mappings additionally require `--fantasypros-id`, `--sleeper-id`,
`--team`, and `--position`. `setup override remove` requires the same scope,
subject, action, reason, evidence date, and source, removes one exact match, and
retains the removal in `override-audit.json`.

Use
`roster-theory COMMAND --help` before changing the season or default paths.

The expert refresh preserves each source URL, capture time, season/category
coverage, and payload hash beneath ignored `data/cache/`. It uses weekly
in-season accuracy—not preseason Draft accuracy—to select currently available
Trade/Waiver experts, records every selection and rejection reason, and writes
the league-scoped pool to
`data/manual/policies/LEAGUE/SEASON/inseason_experts.csv`. Use `--dry-run` to
inspect calls and writes first, `inspect` for an offline readiness report, and
`--json` for the stable machine result.

If API access is unavailable, import authorized saved provider evidence without
editing a CSV:

```powershell
roster-theory inputs experts import home_league `
  --input D:\path\to\saved-expert-evidence
```

The import directory uses the replayable JSON files produced by an earlier
refresh. Hash, coverage, identity, horizon, and freshness checks are identical
for live and imported evidence.

Prepare and verify Trade's schedule without editing a schedule or bye table:

```powershell
roster-theory inputs schedule refresh home_league
roster-theory inputs schedule validate home_league
```

The normalized artifact defaults to
`data/cache/nflverse/SEASON/schedule.json`. It contains all regular-season
games, home/away state, derived bye weeks, response hash, capture time, source,
license, and use restriction. `trade refresh` selects this path from the
configured league season and rejects an artifact for another season. Use
`--output` for an explicit schedule path, `--evidence-output` for the saved raw
evidence path, `--dry-run` to validate without writing, and `--json` for the
stable machine result. A saved refresh can be rebuilt without network access:

```powershell
roster-theory inputs schedule refresh home_league `
  --replay data/cache/nflverse/2026/schedule_source.json
```

If nflverse is unavailable, import a provider-shaped UTF-8 CSV that you are
authorized to use. The CSV columns are `season`, `game_type`, `week`,
`away_team`, and `home_team`; `game_id`, `gameday`, and `gametime` are retained
when present. Import applies the same coverage, pairing, postseason, season,
and provenance checks:

```powershell
roster-theory inputs schedule import home_league `
  --input 'D:\path with spaces\authorized-schedule.csv' `
  --source 'Authorized source name' `
  --source-url 'https://source.example/schedule' `
  --license 'Your authorized terms' `
  --captured-at '2026-05-20T12:00:00Z'
```

## Launch the assistants

Run these commands from the repository root after activating `.venv` and
setting `ROSTER_THEORY_CONFIG`. Commands that contact FantasyPros also require
`FANTASYPROS_API_KEY`. Every assistant is read-only: it recommends but never
submits a draft pick, trade, waiver claim, FAAB bid, or lineup change.

Start each session with the targeted preparation command. Fresh valid inputs
are reused, so this is the ordinary entry point rather than a manual checklist:

```powershell
roster-theory inputs prepare home_league --assistant trade
```

### Draft Assistant

After building a draft-ready league board, launch the continuous draft watcher:

```powershell
roster-theory watch-mock 'https://sleeper.com/draft/nfl/DRAFT_ID' `
  --league home_league `
  --board data/exports/league_boards_2026/home_league_board.csv `
  --slot 1 `
  --user-id YOUR_SLEEPER_USER_ID
```

Use the real Sleeper draft URL or draft ID and your configured slot. For one
snapshot of the draft room configured in `leagues.json`, use:

```powershell
roster-theory recommend home_league `
  --board data/exports/league_boards_2026/home_league_board.csv `
  --slot 1
```

### Trade Assistant

Refresh the immutable league snapshot, then launch the view that answers your
question:

```powershell
roster-theory trade refresh home_league
roster-theory trade diagnose home_league
roster-theory trade search home_league
```

Use `trade evaluate` instead of `trade search` when you already have a package:

```powershell
roster-theory trade evaluate home_league `
  --send 'Player A' `
  --receive 'Player B'
```

### Waiver Assistant

`waiver refresh` is an optional data-only Sleeper check; it does not build a
recommendation. Build one fresh provider bundle and pass that exact file to the
search:

```powershell
# Optional data-only check:
roster-theory waiver refresh home_league

# This is the recommendation workflow:
roster-theory waiver inputs home_league
roster-theory waiver search home_league `
  --inputs data/cache/waiver/home_league_live_inputs.json
```

To evaluate one move rather than search the whole wire:

```powershell
roster-theory waiver evaluate home_league `
  --add 'Player A' `
  --drop 'Player B' `
  --inputs data/cache/waiver/home_league_live_inputs.json
```

The input builder and Waiver decision commands require league-matched
`waiver_wire` and `waiver_decision` policies. Rebuild the bundle for each
league and whenever current-week evidence changes.

## Quick start: draft preparation

In the examples below, replace `home_league` with the key from your league
configuration.

1. Generate and validate all historical Draft accuracy inputs. Then use the
   Premium API to select current Draft experts and refresh their rankings:

   ```powershell
   roster-theory inputs experts refresh home_league --artifact draft-accuracy
   roster-theory inputs experts validate home_league --artifact draft-accuracy
   roster-theory fantasypros-grouped-rankings
   ```

2. Refresh Sleeper settings and build a league-scored board:

   ```powershell
   roster-theory fantasypros-league-boards --league home_league
   ```

3. Inspect the generated board metadata. Do not proceed unless it reports the
   required completeness checks and `draft_ready=true`.

4. Run a small strategy simulation before committing to a longer study:

   ```powershell
   roster-theory simulate home_league `
     --board data/exports/league_boards_YYYY/home_league_board.csv `
     --trials 25 `
     --trace
   ```

5. Watch a Sleeper mock or live draft in read-only mode:

   ```powershell
   roster-theory watch-mock "https://sleeper.com/draft/nfl/DRAFT_ID" `
     --board data/exports/league_boards_YYYY/home_league_board.csv `
     --user-id YOUR_SLEEPER_USER_ID
   ```

The watcher validates the room and reconciles picks, but it never submits a
selection. Use `--once` for a single poll and `--json` for the full machine-
readable report. Run `roster-theory watch-mock --help` before adding historical
acquisition data, preferences, CPU-mock timing, or evidence recording; each has
additional compatibility and completeness requirements.

## Quick start: in-season trade analysis

These workflows require current in-season expert inputs, complete schedule
data, and a league-appropriate long-term value anchor. No authorized schedule,
expert pool, or league policy is bundled. Prepare and validate them for each
league before relying on a recommendation.

Start by refreshing the league and diagnosing the current roster:

```powershell
roster-theory inputs experts refresh home_league --artifact inseason-pool
roster-theory inputs schedule refresh home_league
roster-theory trade refresh home_league
roster-theory trade diagnose home_league
```

Then choose the workflow that matches the question:

```powershell
# Build the selected-expert and market value boards.
roster-theory trade values home_league

# Evaluate a package. Repeat --send or --receive for multi-player sides.
roster-theory trade evaluate home_league `
  --send "Player A" `
  --receive "Player B"

# Inspect league-wide expert-versus-market disagreements.
roster-theory trade gaps home_league

# Search for bounded, mutually credible package ideas.
roster-theory trade search home_league
```

`trade evaluate`, `trade diagnose`, and `trade compare` resolve
`policies.trade_decision`; `trade search` also resolves
`policies.trade_search`. Each accepts `--policy`, and search additionally accepts
`--search-policy`, for an explicit league-scoped override. Data-only refresh and
value-board commands do not require a decision policy.

Waiver evaluation and search similarly resolve `policies.waiver_decision` (or
`--policy`). The installed `waiver inputs` builder also resolves
`policies.waiver_wire`; the source-checkout script remains a compatibility
entry point. All Waiver operations are read-only and never submit a claim or
FAAB bid.

## Quick start: weekly waiver analysis

Run `roster-theory waiver refresh home_league` for read-only league data. It
does not itself produce a claim recommendation. To evaluate an add/drop or
search candidates, prepare a fresh Waiver-scoped bundle containing current
projections, values, availability, and legality evidence for this league:

```powershell
roster-theory waiver inputs home_league
roster-theory waiver evaluate home_league --add "Player A" --inputs PATH
roster-theory waiver search home_league --inputs PATH
```

An approved `waiver_decision` policy for the same league is required for
decision-ready output. Missing inputs or calibration produce incomplete or
uncalibrated results, not fabricated expert ranks. Weekly rankings cannot be
substituted for rest-of-season or preseason draft rankings. Refresh the bundle
each week; replaying saved evidence is not a fresh audit.

Trade results are recommendations, not transactions. Search is deliberately
bounded rather than exhaustive, and a result with no qualifying packages is a
valid outcome. Use `roster-theory trade --help` and the subcommand help for
JSON output, evidence replay, CSV exports, risk posture, explicit waiver moves,
and degraded-data controls.

## Useful commands

| Command | Purpose |
| --- | --- |
| `roster-theory` | Show a brief welcome and the next discovery commands. |
| `roster-theory help` | Choose a grouped, read-only workflow and see its inputs. |
| `roster-theory doctor [LEAGUE]` | Diagnose local setup offline without provider calls. |
| `roster-theory setup init` | Create the ignored private runtime and `leagues.json` atomically. |
| `roster-theory setup scaffold LEAGUE --update-config` | Create season-aware uncalibrated policies, valid override headers, Draft preferences, and optional contingencies. |
| `roster-theory setup list|show-redacted|validate|explain` | Inspect private setup without provider calls or exposed IDs. |
| `roster-theory setup override add|remove LEAGUE ...` | Maintain explicit audited expert and identity overrides. |
| `roster-theory example-config` | Print a bundled synthetic config for offline setup. |
| `roster-theory --help` | List every command. |
| `roster-theory leagues` | Show configured leagues. |
| `roster-theory snapshot LEAGUE` | Refresh read-only Sleeper league and draft data. |
| `roster-theory analyze LEAGUE` | Analyze comparable historical draft tendencies. |
| `roster-theory inputs status LEAGUE --assistant MODE` | Inspect unified season readiness offline. |
| `roster-theory inputs prepare LEAGUE --assistant MODE` | Refresh only missing or stale provider facts and report exact next actions. |
| `roster-theory inputs prepare --all-leagues --assistant MODE` | Reuse shared provider evidence while preserving league-local policy and results. |
| `roster-theory inputs experts inspect LEAGUE` | Inspect Draft and in-season expert input readiness offline. |
| `roster-theory inputs experts refresh LEAGUE` | Build auditable Draft accuracy and in-season expert artifacts. |
| `roster-theory inputs experts validate LEAGUE` | Fail closed unless the selected expert artifacts are complete. |
| `roster-theory inputs experts import LEAGUE --input DIR` | Rebuild from authorized saved provider evidence without API calls. |
| `roster-theory fantasypros-grouped-rankings` | Refresh historically weighted expert rankings. |
| `roster-theory fantasypros-league-boards --league LEAGUE` | Build and validate a league-specific draft board. |
| `roster-theory simulate LEAGUE --board PATH` | Compare draft strategies. |
| `roster-theory watch-mock DRAFT --board PATH` | Follow a draft and rank available choices. |
| `roster-theory audit-mock-evidence PATH` | Rebuild an audit from a saved watcher transcript. |
| `roster-theory trade diagnose LEAGUE` | Summarize lineup, depth, bye, and scenario needs. |
| `roster-theory trade evaluate LEAGUE ...` | Evaluate a specific package for both teams. |
| `roster-theory trade gaps LEAGUE` | Find selected-expert versus market gaps. |
| `roster-theory trade search LEAGUE` | Search bounded bilateral trade opportunities. |
| `roster-theory waiver refresh LEAGUE` | Refresh league Waiver data without a recommendation. |
| `roster-theory waiver inputs LEAGUE` | Build fresh league-scored Waiver evidence without hand-created files. |
| `roster-theory waiver evaluate LEAGUE ...` | Evaluate one entered add/drop from fresh inputs. |
| `roster-theory waiver search LEAGUE ...` | Search eligible Waiver candidates from fresh inputs. |

Every subcommand supports `--help`. Several research and provider-diagnostic
commands are intentionally omitted from this introductory list but remain
available from the top-level CLI help. For scripting, the
[`--json` output and exit-code contract](docs/CLI_OUTPUT_CONTRACT.md) keeps
stdout to one JSON value and routes saved-path notices to stderr. The watcher
returns one JSON report collection when it stops.

Run `roster-theory doctor` before the first provider refresh to check your
private config, owner/league identity fields, league-scoped Draft/Trade/Waiver
policy files, and local board/schedule/expert/waiver-input paths. It makes no
provider request or Sleeper change. Use `roster-theory --config PATH doctor
LEAGUE --json` for one redacted JSON result, or pass `--schedule`,
`--expert-pool`, `--draft-board`, and `--waiver-inputs` to check selected local
files. A `ready` file check means only that its local path and league scope
passed; fresh evidence and league-specific calibration still need separate
verification. Numeric league keys are shown as config entry numbers rather
than printed as possible private IDs.

In an interactive terminal, bare `roster-theory`, `roster-theory help`, and
Doctor show the full bright-yellow arcade wordmark, `FANTASY FOOTBALL
ASSISTANT` descriptor, and Draft/Trade/Waiver mode line (ASCII when color is
unavailable).
Narrow terminals get a one-line form; redirected output and `--json` never get
artwork. Put `--no-banner` before a command to suppress interactive art, for
example `roster-theory --no-banner help`; `roster-theory help --no-banner` also
works. Routine human commands use a smaller full-name command masthead. Draft,
Trade, and Waiver human reports put readiness and limitations before detailed
evidence. Interactive Draft refresh and simulation show cancellable progress;
JSON and piped output remain plain.

## Season rollover

The application is intended for reuse across seasons, but rankings, expert
accuracy windows, overrides, NFL schedules/byes, policy calibration, and some
default output paths are season-specific evidence. Before using a new season,
update league and draft identity with `setup add-league ... --update`, then run:

```powershell
roster-theory inputs prepare LEAGUE --assistant all
```

The command creates or refreshes every supported provider-derived prerequisite
and names the next command for anything still missing, stale, partial,
ambiguous, or uncalibrated. Only human-governed calibration and explicit
overrides remain manual decisions; their valid file shapes and updates are
available through `setup scaffold` and `setup override`, without hand-editing
JSON or CSV. Build the current Draft board and read-only Sleeper snapshots when
the readiness report requests them, then require the relevant assistant's
completeness checks to pass.

Do not carry a league's strategy calibration, draft slot, manager-history
curve, or result into another league or season without separate evidence.

## Development

Production code uses the Python standard library. Install the optional
development dependencies if desired:

```powershell
python -m pip install -e ".[dev]"
```

Before release-candidate review, every CI job in `release gates` must pass.
The same package, repository-content, static, dependency, and clean-install
checks can be run locally using the [release checklist](docs/RELEASE_CHECKLIST.md).
Passing those checks does not publish anything or establish league-specific
calibration.

Run the repository test suite from the root:

```powershell
$env:PYTHONPATH = "src"
python -m unittest discover -s tests
```

Key paths:

- `src/roster_theory/` — application code
- `tests/` — `unittest` coverage
- `config/` — synthetic examples and distributable configuration templates
- `examples/` — manual-import templates and samples
- `docs/` — product contracts, guides, and completed records; see [`docs/README.md`](docs/README.md)
- `.codex/context/` — task router, policies, milestone, and status handoffs

For contributors, [`.codex/context/STEERING.md`](.codex/context/STEERING.md) is the only startup
document. It conditionally routes work to one track-specific status file.
[`.codex/context/DEVELOPMENT_STATUS.md`](.codex/context/DEVELOPMENT_STATUS.md) is a compatibility
index for overall-status requests, not routine context.
See [CONTRIBUTING.md](CONTRIBUTING.md), [SECURITY.md](SECURITY.md), and
[CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) before opening a public issue or patch.

## License and privacy

RosterTheory is available under the [MIT License](LICENSE). Public examples use
synthetic league, draft, owner, and team identifiers. Keep real league
configuration in the documented per-user location (or another path selected by
`ROSTER_THEORY_CONFIG`/`--config`), and keep provider responses, exports, and
manual inputs under the ignored `data/` directories described above. See
[`docs/PRIVACY.md`](docs/PRIVACY.md) for the public-boundary and Git history
decision and [`docs/THIRD_PARTY_NOTICES.md`](docs/THIRD_PARTY_NOTICES.md) for
third-party data provenance and redistribution decisions.
