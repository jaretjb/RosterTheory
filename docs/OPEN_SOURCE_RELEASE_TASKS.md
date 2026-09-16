# Open-source release task backlog

Updated: September 16, 2026 (America/Los_Angeles)

Goal: publish RosterTheory as a safe, reusable, fully open-source project
without exposing personal league data, redistributing third-party data without
a proved basis, or presenting league-specific calibration as portable.

License decision: MIT. Copyright holder confirmed by the user: Jaret Brown.

This backlog is planning scope, not permission to publish a repository, create
a release, rewrite Git history, delete local data, or upload a package. Only one
task may be active in `.codex/context/ACTIVE_MILESTONE.md` at a time. Product policies and
Sleeper recommendations remain read-only throughout release work.

## Release sequence

| Task | Outcome | Depends on | Status |
| --- | --- | --- | --- |
| OS-001 | Clean, reviewable release baseline | — | done — September 14, 2026 |
| OS-002 | MIT license and privacy-safe public boundary | OS-001 | done — September 14, 2026 |
| OS-003 | Third-party data redistribution decision | OS-001 | done — September 14, 2026 |
| OS-004 | Generic league configuration and policy discovery | OS-002, OS-003 | done — September 14, 2026 |
| OS-008 | Guided command discovery | OS-004 | done — September 14, 2026 |
| OS-009 | Interactive and machine-output contract | OS-008 | done — September 14, 2026 |
| OS-010 | Original adaptive terminal identity | OS-009 | done — September 15, 2026 |
| OS-011 | Read-only setup diagnostics | OS-010 | done — September 15, 2026 |
| OS-012 | Consistent reports and interactive progress | OS-011 | done — September 15, 2026 |
| OS-005 | Installable package and public documentation | OS-012 | done — September 15, 2026 |
| OS-014 | Command-driven runtime-input inventory and authority contract | OS-005 | done — September 16, 2026 |
| OS-015 | Expert evidence and in-season pool refresh commands | OS-014 | done — September 16, 2026 |
| OS-016 | NFL schedule and bye refresh command | OS-014 | done — September 16, 2026 |
| OS-017 | Private-input, override, and policy setup commands | OS-014 | done — September 16, 2026 |
| OS-018 | Unified season preparation and runtime refresh | OS-015, OS-016, OS-017 | done — September 16, 2026 |
| OS-006 | Automated public-release quality and security gates | OS-018 | done — September 16, 2026 |
| OS-007 | Public alpha release candidate | OS-006 | done — September 16, 2026 |
| OS-013 | GitHub publication and post-publication verification | OS-007 | planned — requires explicit user approval |

Task IDs reflect when work was added to the backlog; dependency order, not
numeric order, determines the release sequence. Complete only one active task
at a time.

The proposed terminal-experience refinement is tracked separately in
docs/TERMINAL_EXPERIENCE_DESIGN.md and docs/TERMINAL_EXPERIENCE_TASKS.md.
It does not reopen completed OS-010/OS-012 work or change the release sequence
unless the user explicitly schedules it for a release candidate.

OS-002 and OS-003 may be planned together, but perform destructive history
rewrites or public publication only with explicit user approval.

## OS-001 — Clean, reviewable release baseline

Goal: turn the current mixed working tree into a reproducible candidate that
can be audited without losing or combining unrelated work.

Acceptance:

- Inventory every modified and untracked file and assign it to product code,
  tests, public documentation, private/generated evidence, or local-only data.
- Preserve all existing work; do not discard or overwrite unrelated changes.
- Organize the intended public changes into reviewable commits or an equivalent
  explicit patch series with no accidental generated artifacts.
- From a clean clone or clean worktree, install the project and pass the complete
  test suite using only documented setup steps.
- Record the exact test count, Python versions, operating systems, and any
  unavailable verification.

Stop: a clean, reproducible baseline exists and every remaining local artifact
has an explicit public, private, generated, or excluded disposition.

Progress September 14, 2026: the repository-wide inventory and proposed
dispositions are recorded in `docs/OPEN_SOURCE_FILE_INVENTORY.md`. The user
approved the first preservation-first cleanup pass: private league documents
and configuration, completed experiment commands, and the duplicate waiver
input script. The pass is complete: 11 source/config/document/test paths are
preserved in ignored local archive storage, the public league config is
synthetic, five completed experiment commands are absent from CLI help, and the
Waiver input script has one generic path. The 461-test repository suite and
`git diff --check` pass. Ignored runtime evidence remains untouched.

Completion September 14, 2026: all 81 changed non-ignored paths are assigned
exactly once to the four ordered review patches in
`docs/OPEN_SOURCE_PATCH_SERIES.md`; coverage has zero missing, duplicate, or
extra paths, and the real Git index remains empty. The patches applied in order
from `HEAD` (`6f693eb`) in a detached Windows worktree. Using Python 3.13.4 on
Microsoft Windows NT 10.0.22631.0, the README's editable install succeeded, CLI
help loaded, and all 461 tests passed. A deliberately offline
`--no-build-isolation` install was unavailable because the fresh Python 3.13
environment did not include setuptools; the normal documented install fetched
the declared build backend successfully. No repository publication, history
rewrite, provider operation, or ignored-evidence deletion occurred.

## OS-002 — MIT license and privacy-safe public boundary

Goal: license the source under MIT and remove personal or organization-specific
information from the public project surface.

Acceptance:

- Add the standard MIT license text with confirmed year and copyright holder;
  reference it from package metadata and the README.
- Replace the tracked real league configuration with a synthetic
  `config/leagues.example.json`; make the real local configuration ignored and
  document the copy/setup flow.
- Audit source, tests, configuration, documentation, and Git history for names,
  usernames, employer references, league/draft/user IDs, credentials, private
  paths, and generated evidence.
- Replace public tests and examples with synthetic identifiers unless a named
  real-world reference is intentionally retained and documented.
- Confirm `.env`, provider keys, caches, exports, and manual inputs are excluded.
- Produce a history-remediation recommendation. Do not rewrite published history
  without explicit approval, and explain that rewriting cannot revoke existing
  clones or forks.

Stop: the current public tree is privacy-safe, the MIT license is complete, and
any history risk has a documented decision.

Completed September 14, 2026; copyright-holder correction September 15, 2026.
`LICENSE` contains the standard MIT text for 2026 Jaret Brown;
`pyproject.toml` and `README.md` reference it.
The real league configuration is removed from the public tree, the documented
copy flow uses synthetic `config/leagues.example.json`, and generic ignore
rules preserve local configuration, keys, caches, exports, manual inputs, and
generated evidence. Public league, owner, team, and draft references were
renamed or redacted without combining League Alpha and League Beta calibration.
`docs/PRIVACY.md` records the 66-commit audit and the decision not to publish the
existing Git graph before sanitizing it. History was not rewritten, ignored
evidence was not deleted, and no provider or Sleeper operation occurred. The
463-test repository suite passed.

## OS-003 — Third-party data redistribution decision

Goal: prove that every non-code artifact may be distributed, or replace it with
a safe reproducible or synthetic alternative.

Acceptance:

- Inventory FantasyPros-derived expert accuracy, rankings, projections, source
  metadata, NFL schedule/bye data, Sleeper-derived records, and other external
  datasets committed under `config/`, `examples/`, and `docs/`.
- For each artifact, record its source, transformation, necessity, applicable
  terms or license, attribution requirement, and disposition:
  `REDISTRIBUTE`, `REGENERATE`, `SYNTHETIC_FIXTURE`, `USER_SUPPLIED`, or `REMOVE`.
- Do not assume that the MIT code license grants redistribution rights to
  third-party data.
- Replace uncertain datasets with import/generation instructions and minimal
  synthetic fixtures sufficient for tests and examples.
- Add a concise third-party notices or data-provenance document for retained
  artifacts.

Stop: every shipped data file has a documented redistribution basis and tests
pass without private or unapproved provider data.

Completed September 14, 2026. `docs/THIRD_PARTY_NOTICES.md` records the source,
transformation, necessity, terms/attribution, and disposition of every public
configuration and example data artifact. Eleven FantasyPros/NFL-derived data
files and five data-heavy provider/league reports were removed from the public
tree and preserved under ignored private archive storage. Runtime defaults now
point to ignored user-local FantasyPros and NFL paths. Public examples and
loader tests use invented expert, player, team, schedule, and identifier data;
all 19 shipped CSV/JSON artifacts are covered by an automated inventory test.
Project-authored policies and one contributor-authored defense preference are
retained with their redistribution basis documented. No provider call,
publication, history rewrite, or ignored-evidence deletion occurred. The full
465-test suite passed.

## OS-004 — Generic league configuration and policy discovery

Goal: allow a new user to configure their own league without editing source or
pretending that bundled league calibration applies to it.

Acceptance:

- Remove hard-coded private league choices from the public Draft, Trade, and
  Waiver command paths.
- Resolve league configuration from an explicit CLI path and/or documented user
  config location rather than requiring the repository's working directory.
- Resolve policy paths from league configuration or explicit CLI arguments.
- Fail closed with a clear `uncalibrated` result when a league lacks its own
  proved policy; never silently reuse another league's policy.
- Move named league experiments and organization-specific research commands out
  of the default public CLI, or convert them to clearly labeled generic examples.
- Add synthetic end-to-end tests for two independently configured leagues and
  for cross-league policy rejection.

Stop: a user-defined league can reach every supported read-only workflow from a
documented configuration, while league-specific calibration remains isolated.

Completed September 14, 2026. See
`docs/COMPLETED_OPEN_SOURCE_RELEASE_OS_004.md`.

## OS-008 — Guided command discovery

Goal: make the CLI understandable to a new user without requiring them to
decode the current flat `argparse` command list.

Acceptance:

- Add `roster-theory help` with short, grouped paths for league setup, Draft,
  Trade, Waiver, and diagnostics. Show one safe example per group and direct
  users to detailed subcommand `--help`.
- Make bare `roster-theory` display a concise welcome/next-step screen instead
  of only an argument error; preserve ordinary `--help` and nested help.
- Describe required inputs and read-only behavior accurately; do not imply a
  league is calibrated merely because it is configured.
- Keep help available offline, before league configuration exists, and test
  command discovery and exit codes from an arbitrary working directory.

Stop: a first-time user can find the correct read-only workflow and its
requirements in one or two commands.

## OS-009 — Interactive and machine-output contract

Goal: define a predictable boundary between decorative terminal output and
automation-safe data before adding visual branding.

Acceptance:

- Centralize detection of interactive stdout, terminal width, ANSI support,
  `NO_COLOR`, and redirected output using the standard library.
- Ensure every `--json` command writes one valid JSON value to stdout, with
  progress, banners, saved-path notices, and diagnostics either suppressed or
  sent to stderr as appropriate.
- Specify and test consistent exit codes and machine-readable failure status,
  including `uncalibrated`; never hide missing, ambiguous, partial, or
  unavailable evidence.
- Cover piped output, narrow terminals, `NO_COLOR`, Windows/Linux behavior,
  and existing human-readable watcher output without changing decision logic.

Stop: CLI output can be safely scripted before and after visual enhancements.

## OS-010 — Original adaptive terminal identity

Goal: give RosterTheory a recognizable console identity inspired by bold
amber-on-dark pixel art, without copying the attached Hermes artwork.

Acceptance:

- Create an original RosterTheory wordmark/banner as text or ANSI terminal art;
  do not require image viewers, graphics-capable terminals, or non-standard
  production dependencies.
- Show the full banner only on the bare welcome and guided help screens; use
  a compact mark only on selected interactive human-readable reports.
- Adapt to narrow terminal widths and provide plain-text/ASCII fallback.
  Respect `NO_COLOR`, redirected output, and an explicit `--no-banner` option.
- Never insert artwork into JSON, CSV, evidence files, logs, or error payloads.
  Add snapshot-style tests for the banner variants and rendering boundaries.

Stop: the identity is attractive in a capable terminal and harmless everywhere
else.

Completed September 15, 2026. See
`docs/COMPLETED_OPEN_SOURCE_RELEASE_OS_010.md`.

## OS-011 — Read-only setup diagnostics

Goal: give a new user a safe answer to “what is missing before I can use this
league?”

Acceptance:

- Add `roster-theory doctor` with an offline default that checks config
  discovery, configured league identity, policy existence and league scope,
  and required local input paths without provider requests or Sleeper writes.
- Report each check as ready, missing, invalid, unavailable, or uncalibrated;
  include the affected league and a concrete safe next action.
- Keep Draft, Trade, and Waiver readiness separate. A data-only workflow may
  be available while its recommendation policy remains uncalibrated.
- Provide concise human-readable and valid `--json` reports; redact private
  IDs and paths where appropriate, and never reveal credentials.
- Add synthetic tests for two leagues, absent config, missing files, wrong-
  league policy, and a fully configured offline example.

Stop: setup failures can be diagnosed without changing external state or
pretending that generic policy is league calibration.

Completed September 15, 2026. See
`docs/COMPLETED_OPEN_SOURCE_RELEASE_OS_011.md`.

## OS-012 — Consistent reports and interactive progress

Goal: make routine results easy to scan while preserving evidence and safety
gates.

Acceptance:

- Use a consistent human-readable report structure across supported Draft,
  Trade, and Waiver commands: league/horizon, readiness, result, warnings and
  limitations, then saved evidence paths.
- Make incomplete inputs and `uncalibrated` states prominent; preserve the
  authoritative expert horizon and league-local scoring/provenance labels.
- Add restrained progress for long refresh/simulation operations only when
  stdout is interactive; make it cancellable and silent in JSON/piped modes.
- Verify that formatting changes do not alter recommendations, evidence
  hashes, saved artifacts, or Sleeper's read-only boundary. Cover wide/narrow,
  color/plain, success/degraded/failure terminal cases.

Stop: terminal output is clearer without changing the underlying decisions.

## OS-005 — Installable package and public documentation

Goal: make the documented install work outside a repository checkout and give a
new contributor an accurate path from clone to first safe result.

Acceptance:

- Complete `pyproject.toml` metadata: README, MIT license expression/file,
  maintainers or authors, URLs, classifiers, keywords, and supported Python.
- Decide and document whether the initial release is GitHub source-only or also
  published to PyPI; package only what that decision requires.
- Make required default resources package-safe or require explicit external
  paths with actionable errors; remove accidental current-working-directory
  assumptions.
- Build both wheel and source distribution, inspect their contents, install the
  wheel into a clean environment outside the repository, and run CLI smoke
  tests including bare launch, guided help, `doctor`, banner fallback, and
  machine-readable output.
- Update the README for Draft, Trade, and Waiver behavior, including current
  limitations, FantasyPros requirements, sample-only restrictions, and the
  read-only safety promise.
- Add `CONTRIBUTING.md`, `SECURITY.md`, `CODE_OF_CONDUCT.md`, and `CHANGELOG.md`.

Stop: a new user can install, configure a synthetic league, run help and a safe
offline example, and understand support and contribution expectations.

## OS-014 — Command-driven runtime-input inventory and authority contract

Goal: identify every external or private artifact required to reach a
decision-ready Draft, Trade, or Waiver result and define how a command obtains,
creates, imports, validates, or deliberately declines to invent it.

Acceptance:

- Inventory the league config, league policies, historical accuracy, current
  expert pools, expert overrides, rankings, projections, ADP, news, Waiver Wire
  evidence, NFL schedule/byes, player identity data, and current Sleeper state.
  For each artifact record its authority, decision horizon, freshness rule,
  default ignored path, producing command, and fail-closed behavior.
- Separate provider facts from user decisions. A command may fetch or
  deterministically derive authorized provider evidence, but it must not infer
  trusted-expert membership, an exception override, or league calibration
  without an explicit documented rule and provenance.
- Define one season-aware command namespace and stable JSON result contract for
  input setup and refresh. Every command must support explicit config/output
  paths, avoid printing credentials or private IDs, and make provider calls and
  local writes visible before execution where practical.
- Resolve the source and redistribution/use authority for an automated NFL
  schedule and bye refresh before implementation. If no acceptable source is
  available, specify a command-driven import path with complete schema and
  provenance validation rather than silently retaining hand-edited files.
- Add fixture-based contracts for two synthetic leagues and document which
  inputs are shared provider evidence versus league-scoped policy. No result or
  calibration may transfer between leagues.

Stop: every runtime prerequisite has one explicit command path or a documented
reason that the command can only scaffold/import and validate a human decision.

## OS-015 — Expert evidence and in-season pool refresh commands

Goal: replace undocumented expert-file preparation with reproducible commands
that fetch authorized evidence and build auditable Draft and in-season pools.

Acceptance:

- Add a command that refreshes all historical expert-accuracy inputs required
  by the current Draft pipeline, including the category-level file not produced
  by `fantasypros-accuracy-history` today. Preserve source URL/endpoint, capture
  time, season/category coverage, and payload hashes.
- Add a deterministic in-season expert-pool builder using current FantasyPros
  availability plus the approved historical selection rules. Emit the exact
  schema consumed by Trade and Waiver, selection/rejection reasons, horizon,
  weights, freshness, provider IDs, and a machine-readable audit artifact.
- Keep Draft pools and in-season pools distinct. Do not reuse preseason
  accuracy as an in-season authority unless the declared policy explicitly
  permits that proxy and the output labels it.
- Support inspect, refresh, validate, `--json`, explicit output paths, dry-run,
  rate limits, request budgets, and replay from saved provider evidence.
  Missing access, partial coverage, stale rankings, or ambiguous expert
  identity must fail closed rather than produce a trusted pool.
- Replace direct file-preparation instructions in the README with the new
  commands and retain a command-driven import fallback for users without the
  required API entitlement.

Stop: a user can create every expert accuracy and pool artifact consumed by
Draft, Trade, and Waiver without editing CSV data by hand.

## OS-016 — NFL schedule and bye refresh command

Goal: produce the complete season schedule and bye evidence consumed by Trade
from an authorized source through one repeatable command.

Acceptance:

- Implement the source decision from OS-014 with a provider adapter separated
  from normalization and validation. Record source, URL/endpoint, capture time,
  season, response hash, and any use/redistribution restriction.
- Normalize all 32 teams, regular-season weeks, opponents, home/away state, and
  bye weeks into the existing schedule contract. Reject duplicates, missing
  teams/weeks, impossible pairings, postseason leakage, and season mismatch.
- Add refresh, validate, replay/import, explicit output, dry-run, and `--json`
  modes. The import mode must accept a documented user-authorized source file
  and perform the same completeness/provenance checks as the network adapter.
- Make `trade refresh` consume the generated season-aware path or an explicit
  override and report schedule freshness. It must never substitute an old
  season or infer missing games/byes.
- Cover schedule corrections, provider unavailability, narrow/redirected
  output, Windows paths, and zero Sleeper writes with synthetic fixtures.

Stop: no hand-edited schedule or bye table is required when an authorized
provider is available; the fallback remains command-driven import and validate.

## OS-017 — Private-input, override, and policy setup commands

Goal: eliminate manual file-shape work while preserving the rule that user
judgment and league calibration cannot be fabricated.

Acceptance:

- Add commands to initialize the ignored private runtime directory, create or
  import `leagues.json`, and scaffold season-aware expert override, Trade/Waiver
  policy, Draft preference, and optional contingency files with valid headers
  or schemas.
- Add list, show-redacted, validate, and explain commands for those files.
  Override commands must support explicit add/remove operations with scope,
  reason, evidence date, and source; they must never infer an exclusion,
  freshness correction, or anchor weight from provider data alone.
- Policy scaffolds must be league-scoped and visibly uncalibrated until the
  user supplies separately supported thresholds. Never copy a policy or result
  from one league into another.
- Make every write atomic, previewable with dry-run, non-destructive by default,
  and safe on paths containing spaces. Existing private files require an
  explicit replace/update option and retain a recoverable backup.
- Integrate the commands with `doctor` so every missing file points to a
  concrete setup or refresh command rather than prose-only editing guidance.

Stop: users create and maintain required private file structures through the
CLI, while substantive overrides and calibration remain explicit human choices.

## OS-018 — Unified season preparation and runtime refresh

Goal: provide a discoverable command-driven path from an installed application
and private league config to fresh assistant inputs for a selected season.

Acceptance:

- Add a season preparation command that composes OS-015 through OS-017 without
  collapsing their authority boundaries. It must show a preflight call/write
  plan, support dry-run and `--json`, resume safely, and avoid repeating fresh
  provider requests.
- Provide targeted modes for Draft, Trade, Waiver, one selected league, or all
  configured leagues. Shared provider evidence may be reused; league scoring,
  policies, readiness, and results remain separately validated.
- Finish with Doctor-equivalent readiness showing the exact next command for
  every missing, stale, partial, ambiguous, or uncalibrated input. A successful
  data refresh must not be presented as a recommendation or proof of policy
  calibration.
- Verify a fresh clone/wheel workflow on Windows PowerShell and a POSIX shell,
  including paths with spaces, API failure/resume, two synthetic leagues,
  redirected output, and absence of secrets or provider payloads from Git.
- Update README launch and season-rollover instructions so ordinary use needs
  commands rather than manual file editing. Preserve expert horizons, evidence
  hashes, rate/request budgets, and the zero-Sleeper-write boundary.

Stop: all fetchable/derivable runtime evidence and all required private file
shapes are command-driven; remaining human work is limited to explicit league
calibration and documented override decisions.

## OS-006 — Automated public-release quality and security gates

Goal: make regressions, packaging failures, secrets, and unsafe repository
contents block release automatically.

Acceptance:

- Test supported Python versions on Linux and Windows; add macOS if practical.
- Run the complete unit suite plus focused clean-install and CLI smoke tests.
- Gate guided help, `doctor`, banner suppression, narrow/plain rendering, and
  single-value JSON output with focused automated tests.
- Build wheel and source distribution in CI and validate their contents.
- Add secret scanning and a repository check that rejects tracked `.env`, cache,
  export, manual-input, credential, or private league configuration artifacts.
- Add dependency/security auditing appropriate to the minimal dependency set.
- Require formatting/static checks only after their tools and versions are
  declared in development dependencies.
- Document the release checklist and required passing checks.

Stop: every public-release acceptance criterion is machine-checked where
practical, with remaining manual checks explicit.

## OS-007 — Public alpha release candidate

Goal: prepare a reviewable `0.1.0` public alpha without overstating the validity
or portability of recommendations.

Acceptance:

- All OS-001 through OS-006 and OS-008 through OS-012 acceptance criteria pass
  from a clean clone.
- The repository contains no unresolved private-data or third-party-data
  disposition, no known secret exposure, and no unreviewed generated evidence.
- Release notes distinguish stable infrastructure from controlled-fixture or
  league-specific recommendation policy.
- Known calibration limitations, league-local evidence requirements, and the
  recurring fresh-audit workflow are visible; public alpha status is
  unambiguous.
- Present the exact final diff, candidate commit, approved history disposition,
  and release checklist for user review. Do not tag, create a GitHub release,
  change repository visibility, or upload a package in OS-007.

Stop: a review-ready release candidate can be handed to OS-013 for an explicit
user-authorized public publication step. A stable/non-alpha recommendation
release remains gated on the applicable product calibration milestones and
fresh league-specific audits.

## OS-013 — GitHub publication and post-publication verification

Goal: make the approved source-only alpha repository public on GitHub, then
verify what an unauthenticated visitor can actually see and install.

Acceptance:

- OS-007 is complete. Present the exact candidate commit/branch, final diff,
  release checklist, and history-remediation disposition. Obtain explicit user
  approval for changing the named GitHub repository's visibility to public;
  planning or completion of OS-007 is not that approval.
- Recheck the GitHub remote, candidate branch and tags, tracked files, and
  reachable history immediately before publication. Stop if private league
  evidence, credentials, unapproved provider data, or unresolved old commits
  would become public. A history rewrite or deletion requires separate explicit
  authorization; never silently perform it as part of visibility change.
- After approval and a clean preflight, arrange only the approved candidate
  state and refs on the still-private remote, verify them again, and then change
  only the approved repository's visibility to public. Do not upload to PyPI;
  creating a tag or GitHub release needs separate explicit approval.
- Verify the repository is publicly reachable without authentication, that its
  visible branch and history match the approved candidate, and that README,
  MIT license, public templates, and safe installation instructions are present.
  Repeat a clean-clone install and offline `doctor` smoke test against the public
  source; check public pages for unintended secrets or private data.
- Record the public URL, commit, visibility result, verification results, and
  any remaining alpha/calibration limitations. If a post-publication exposure
  is found, report it immediately and seek user direction on containment.

Stop: the GitHub repository is public only after explicit sign-off, and the
published source and installation path are independently verified. The task
does not authorize a stable release or automatic Sleeper actions.
