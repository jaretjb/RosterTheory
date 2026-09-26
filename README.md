# RosterTheory

![Roster Theory in oversized, chunky bright-yellow 1990s arcade lettering](docs/assets/roster-theory-terminal-90s.svg)

A command-line decision engine for Sleeper leagues, built to answer the
question a generic rankings page cannot: **what is the best move for this
roster, in this league, right now?**

FantasyPros supplies authoritative expert rankings and projection data.
RosterTheory turns that evidence into league-specific draft, trade, and waiver
advice. It reads the actual Sleeper scoring and roster rules, models the players
likely to remain available, optimizes legal starting lineups, and keeps every
recommendation tied to its source and decision horizon.

## Why use it with FantasyPros?

RosterTheory is not another set of invented player rankings, and it does not
claim that one model knows more than the experts. Its advantage is the decision
work that begins after the rankings arrive:

- **Thousands of simulated drafts, not a static cheat sheet.** A standard
  strategy comparison runs 1,000 seeded Monte Carlo trials for each of two
  default policies—2,000 simulated draft paths from your configured slot. The
  engine tests roster construction, opponent behavior, positional runs,
  acquisition timing, and whether a target is likely to survive to your next
  pick.
- **Your scoring, not a canned point total.** Raw projection statistics are
  rescored from the league's real Sleeper settings, then evaluated against its
  exact lineup and roster constraints.
- **Expert evidence with an audit trail.** When authorized accuracy history is
  available, the draft board can weight experts by their demonstrated,
  position-specific performance. Rankings stay authoritative only for their
  declared preseason, weekly, or rest-of-season horizon. Missing, stale,
  partial, or ambiguously matched data is reported instead of silently replaced
  with a guess.
- **Whole-roster decisions.** Trade and waiver analysis compares optimized
  legal lineups before and after a move, including replacement value, schedule,
  availability risk, and the cost of the player or roster spot being given up.
- **Advice without account risk.** The app is read-only: it can follow a live
  room and explain a recommendation, but it cannot make a pick, send a trade,
  submit a claim, or change a lineup.

There is also a concrete project sanity check. In a documented 2026 live draft,
the user followed RosterTheory's displayed leader on all 15 picks; the resulting
roster received a **98/100 FantasyPros Draft Wizard score** and was projected to
finish first. That is one draft—not proof of universal outperformance—but it
shows that the simulation-driven process can produce an excellent result by
FantasyPros' own evaluation.

You remain the manager. RosterTheory shows its recommendation and evidence;
you decide what to do with them.

## What it does

- **Draft:** builds a draft board, compares strategies, and follows live
  Sleeper drafts and mocks.
- **Trade:** reviews your roster, evaluates proposed trades, and searches for
  deals that could help both teams.
- **Waiver:** evaluates add/drop ideas and searches the available player pool.

RosterTheory does not guess when important information is missing. If your
rankings are stale, a player cannot be matched, or your league needs its own
decision rules, the command will explain what is missing and how to fix it.

## What you need

- Python 3.11 or newer
- A Sleeper league
- A FantasyPros HOF Premium API key for automatic rankings and projections

Sleeper's public data does not require a key. You can also use the help and
setup-checking commands without a FantasyPros key.

## Install

RosterTheory is installed directly from GitHub:

```powershell
git clone https://github.com/jaretjb/RosterTheory.git
cd RosterTheory
python -m venv .venv
./.venv/Scripts/Activate.ps1
python -m pip install .
```

On macOS or Linux, activate the environment with:

```bash
source .venv/bin/activate
```

Run the built-in guide to see the main commands:

```text
roster-theory help
```

## Set up a league

The setup commands create the private configuration files for you. Replace the
example values below with your Sleeper information:

```powershell
roster-theory setup init

roster-theory setup owner `
  --sleeper-username YOUR_NAME `
  --sleeper-user-id YOUR_USER_ID `
  --update

roster-theory setup add-league home_league `
  --season 2026 `
  --name "Home League" `
  --league-id YOUR_LEAGUE_ID `
  --user-roster-id 1 `
  --draft-id YOUR_DRAFT_ID `
  --user-draft-slot 1 `
  --update

roster-theory setup scaffold home_league --update-config
roster-theory doctor home_league
```

`home_league` is a nickname used only in your commands. You can choose a
different name.

Your private configuration is stored in your normal user configuration folder:

- Windows: `%APPDATA%\RosterTheory\leagues.json`
- macOS and Linux: `~/.config/roster-theory/leagues.json`, unless
  `$XDG_CONFIG_HOME` is set

You can use a different file by putting `--config PATH` before the command or
by setting `ROSTER_THEORY_CONFIG`.

The generated decision-policy files start as uncalibrated. That is intentional:
rules that work for one league should not silently be reused in another.
`roster-theory doctor home_league` will show what still needs attention.

## Add your FantasyPros key

Set the key in your terminal session. Do not paste it into a tracked file.

PowerShell:

```powershell
$env:FANTASYPROS_API_KEY = "YOUR_KEY"
```

macOS or Linux:

```bash
export FANTASYPROS_API_KEY="YOUR_KEY"
```

If your FantasyPros plan does not provide the data an assistant needs, you can
import an authorized CSV instead. See the
[manual import guide](docs/MANUAL_FANTASYPROS_IMPORT.md).

## Inspect or prefetch data

Assistant commands prepare the data they need automatically. These lower-level
commands are available for troubleshooting, offline checks, and prefetching:

```text
roster-theory inputs prepare home_league --assistant all
```

It reuses fresh data, refreshes anything missing or stale, and tells you about
anything that still needs a decision from you. To check without refreshing:

```text
roster-theory inputs status home_league --assistant all
roster-theory doctor home_league
```

Use `draft`, `trade`, or `waiver` instead of `all` when you only want to inspect
or prefetch one assistant.

## Draft

Build your league's draft board:

```text
roster-theory inputs prepare home_league --assistant draft
roster-theory fantasypros-league-boards --league home_league
```

The board command prints the path it created. Use that path to get a single
recommendation:

```text
roster-theory recommend home_league --board PATH_TO_BOARD --slot 1
```

Or follow a live Sleeper draft or mock:

```text
roster-theory watch-mock SLEEPER_DRAFT_URL --league home_league --board PATH_TO_BOARD --slot 1 --user-id YOUR_USER_ID
```

## Trade

Request a current read-only roster diagnosis or target-first trade search. Each
analysis refreshes stale schedule/expert evidence, current Sleeper ownership,
and value boards automatically while reusing fresh caches:

```text
roster-theory trade diagnose home_league
roster-theory trade targets home_league
roster-theory trade search home_league
```

To evaluate a trade you already have in mind:

```text
roster-theory trade evaluate home_league --send "Player A" --receive "Player B"
```

Repeat `--send` or `--receive` for multi-player trades.
`trade gaps` and `trade compare` use the same automatic preparation. The
`targets` command shows `WATCH` cards without implying an offer exists;
`search` adds exact, grouped offers with separate intrinsic and market verdicts.
These Phase 13 commands require an explicit, league-scoped `trade_target`
policy (or `--target-policy PATH`). Until its thresholds are supported for that
league, they stop as uncalibrated; fixture premiums are not production defaults.
`--ecr-proxy` disables chart claims, while `--trade-market-import PATH` uses an
authorized local chart. `--snapshot PATH` replays saved evidence offline.
The lower-level `inputs prepare`, `trade refresh`, and `trade values` commands remain
available for diagnostics and reproducible operations; they are not normal
end-user prerequisites.

## Waiver

Request a current read-only waiver report with one command. It refreshes stale
evidence and reuses fresh cached inputs automatically:

```text
roster-theory waiver search home_league
```

`--inputs PATH` remains available for an explicit reproducible input bundle.

To evaluate one move:

```text
roster-theory waiver evaluate home_league --add "Player A" --drop "Player B" --inputs PATH_TO_INPUTS
```

## Finding commands

Start with:

```text
roster-theory help
```

Every command also has its own help:

```text
roster-theory --help
roster-theory trade --help
roster-theory trade evaluate --help
roster-theory waiver --help
roster-theory inputs --help
```

Add `--json` to supported commands when another program needs to read the
result. Add `--no-banner` before a command if you do not want terminal artwork.

## Privacy

Keep real league IDs, provider responses, exports, and manual inputs out of
Git. RosterTheory's default private-data folders are ignored by this repository,
and setup commands can show a redacted version of your configuration:

```text
roster-theory setup show-redacted home_league
```

Public examples contain invented data. See [Privacy](docs/PRIVACY.md) and
[third-party data notices](docs/THIRD_PARTY_NOTICES.md) for details.

## Maintenance

RosterTheory is owner-maintained and is not accepting outside patches or pull
requests. Public availability is for installation and use under the license
below. Only the repository owner, including tools acting through the owner's
account, manages changes and merges.

Install the development tools and run the tests:

```powershell
python -m pip install -e ".[dev]"
$env:PYTHONPATH = "src"
python -m unittest tests.test_context_routing
python -m unittest discover -s tests
```

Maintainer changes use a separate branch and a pull request. Direct pushes,
force pushes, and bypass merges to `main` are prohibited. Pull requests must
be up to date with `main`, pass all required checks, and resolve review threads
before merging. No account has a ruleset bypass exception. A second account's
approval is not required: the owner and their tools use the same GitHub account,
which cannot approve its own pull requests.

Before committing, run `python scripts/release_gate.py repository` and
`python scripts/release_gate.py repository --staged` to check both tracked
files and the exact staged contents for unsafe artifacts and known private
identifiers. These checks do not recognize every possible private identifier;
manual review is still necessary. Keep real IDs, credentials, provider data,
and personal reports out of code, test output, issues, and pull requests.
Use synthetic fixtures and offline provider fakes for tests.

New checkouts can enable the pre-commit gate with
`git config core.hooksPath .githooks`; preserve any additional privacy/history
hooks already installed in an existing checkout. CI runs the same gates.
Follow the [task router](.codex/context/STEERING.md) before product changes and
the [release checklist](docs/RELEASE_CHECKLIST.md) before a release.
For private security reporting, see [SECURITY.md](SECURITY.md).

## License

RosterTheory is released under [the Unlicense](LICENSE). You may use, copy,
change, distribute, or sell it for any purpose. It comes without a warranty.
