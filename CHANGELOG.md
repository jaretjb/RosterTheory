# Changelog

## 0.1.0 — Unreleased alpha

- Rewritten plain-language README and a switch from MIT to the Unlicense.
- Local read-only Draft, Trade, and Waiver decision-support CLI for Sleeper
  leagues; no automatic picks, offers, claims, or lineup changes.
- Synthetic league configuration, offline setup diagnostics, guided help, and
  strict JSON output for machine-oriented decision commands.
- League-scoped evidence, policy boundaries, provenance, and completeness
  gates; free-tier FantasyPros samples are not decision-ready.
- Command-driven, replayable Draft accuracy and league-scoped in-season expert
  pool preparation with selection audits and no hand-edited expert CSVs.
- Command-driven, replayable NFL schedule preparation with strict season/game
  validation, derived byes, authorized CSV fallback, and season-aware Trade
  consumption.
- Atomic private-runtime setup with season-aware uncalibrated policy scaffolds,
  redacted validation, explicit audited override maintenance, and recoverable
  backups instead of hand-built JSON/CSV shapes.
- Unified `inputs prepare/status` season workflows with freshness-aware reuse,
  provider-call/write preflights, offline and dry-run modes, resumable failure
  handling, multi-league evidence reuse, and league-local readiness reporting.
- Blocking multi-platform release gates for the complete test suite, CLI output
  contracts, tracked private/generated artifacts, full-history secret scanning,
  pinned static and dependency audits, distributions, and clean wheel installs.
- Public GitHub source with wheel and source-distribution support; no PyPI
  publication.

Stable alpha infrastructure includes installation, command discovery,
machine-output contracts, command-driven input preparation, evidence
provenance, completeness checks, and read-only safety boundaries. Public
fixtures demonstrate those contracts but do not validate recommendation
quality for a real league.

Draft, Trade, and Waiver recommendation policies remain league- and
season-local. A user must supply fresh authorized evidence and separately
reviewed calibration; missing or incomplete authority fails closed. See
`docs/RELEASE_NOTES_0.1.0-alpha.md` for the full support boundary and recurring
audit workflow.
