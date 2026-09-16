# Completed OS-004 — Generic league configuration and policy discovery

Completed: September 14, 2026 (America/Los_Angeles)

## Outcome

RosterTheory no longer requires a repository-relative `config/leagues.json`.
Every league-aware command can use a global `--config PATH`, the
`ROSTER_THEORY_CONFIG` environment variable, or the documented platform user
configuration location. The selected path is threaded through Draft, Trade,
and Waiver services rather than reloaded from the process working directory.

League entries may declare relative policy paths under `policies`; those paths
are anchored to the directory containing `leagues.json`. Trade decision/search,
Waiver decision/Waiver Wire, and Draft preference paths also support explicit
CLI overrides. JSON policy files must declare the selected `league_key`, and a
Draft preference CSV must contain the selected league in `league_scope`.

Missing, unavailable, or cross-league policy evidence raises the typed
`Uncalibrated` domain failure. Decision commands render that condition as a
machine-readable JSON result with `status: uncalibrated` and exit nonzero before
provider refresh. Data-only refresh and evidence-building commands remain
available without pretending that a recommendation policy is calibrated.

Previously removed named league experiments remain absent from the default CLI.
No provider request, Sleeper write, publication, history rewrite, or ignored
evidence deletion occurred.

## Validation

- Added synthetic configuration coverage for two independently located leagues.
- Covered explicit CLI config selection outside the repository working
  directory and environment-based discovery.
- Covered relative policy resolution, missing-policy fail-closed behavior,
  cross-league JSON rejection, Draft preference scope rejection, and the
  machine-readable CLI result.
- Verified top-level and decision-command help for the new options.
- `python -m unittest discover -s tests`: 471 tests passed.
- `git diff --check`: passed (line-ending notices only).
