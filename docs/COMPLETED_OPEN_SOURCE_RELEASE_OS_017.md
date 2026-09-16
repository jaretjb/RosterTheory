# OS-017 — Private-input, override, and policy setup commands

Completed: September 16, 2026 (America/Los_Angeles)

## Outcome

`roster-theory setup` now creates and maintains the private runtime without
requiring users to reproduce JSON or CSV shapes by hand:

- `init`, `import`, `owner`, and `add-league` create or update `leagues.json`;
- `scaffold` creates season-aware expert and identity override CSVs, Draft
  preferences, Trade decision/search policies, Waiver decision/Waiver Wire
  policies, and optional named-player contingency inputs;
- `list`, `show-redacted`, `validate`, and `explain` provide offline inspection
  and concrete next actions; and
- `override add` and `override remove` maintain explicit expert or identity
  decisions and a persistent audit history.

Policy scaffolds contain the complete structural fields expected by their
consumers but use `null` placeholders and a visible `UNCALIBRATED` status.
Policy resolution rejects that status before analysis. No threshold, expert
exclusion, freshness correction, identity mapping, anchor weight, contingency,
or calibration is inferred from provider data.

## Safety and isolation

- Every private write uses a same-directory temporary file and atomic replace.
- Existing files are refused unless the command receives the relevant explicit
  `--update`, `--update-config`, `--replace`, or scaffold `--replace` option.
- An accepted update or replacement creates a timestamped recoverable `.bak`
  copy before changing the destination.
- `--dry-run` reports intended writes and backups without filesystem changes.
- Paths with spaces are supported.
- Expert and identity override changes require scope, reason, evidence date,
  and source. Removes target exactly one existing row and remain in
  `override-audit.json`.
- Policy and artifact paths include both league and season. Scaffolding one
  league never reads or copies another league's policy or result.
- Redacted display hides account, league, draft, player, and expert identity
  values and shortens configured policy paths.
- All setup results report `sleeper_write_performed: false`.

Doctor now points missing configuration, policies, schedules, expert pools,
Draft boards, and Waiver inputs to concrete setup or refresh commands. The
README documents the normal command-driven workflow and explicit override
examples.

## Validation

- Synthetic tests cover initialization, import, owner/league setup, season
  scaffolding, uncalibrated policy rejection, redaction, cross-league
  isolation, exact override add/remove, audit retention, consumer-compatible
  CSVs, dry-run, Windows paths, overwrite refusal, and recoverable backups.
- Complete suite: 553 tests pass.

No provider call, private production input, or Sleeper write was used during
validation.
