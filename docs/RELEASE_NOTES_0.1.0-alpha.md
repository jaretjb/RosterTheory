# RosterTheory 0.1.0 public alpha release notes

Release type: source-only public alpha release candidate

RosterTheory 0.1.0 is a local, read-only decision-support CLI for Sleeper
Draft, Trade, and Waiver workflows. It does not make picks, send trade offers,
submit waiver claims, change FAAB, or edit lineups.

## Stable alpha infrastructure

The candidate provides:

- an installable Python 3.11+ package and `roster-theory` command;
- guided help, offline diagnostics, human-readable reports, and strict JSON
  output contracts;
- command-driven setup, expert-evidence preparation, NFL schedule preparation,
  and unified season/input readiness workflows;
- explicit provenance, authority horizon, freshness, completeness, identity,
  and league-scope checks;
- read-only Sleeper integration and user-authorized FantasyPros integration;
- replayable local evidence under ignored runtime directories; and
- multi-platform tests, repository-content checks, full-history secret
  scanning, static checks, dependency auditing, distribution inspection, and
  clean-wheel smoke tests.

"Stable" here describes those software and safety contracts within the alpha.
It does not mean that recommendation quality is portable or production-proven.

## Recommendation-policy limitations

The repository's examples and test fixtures are synthetic or deliberately
controlled. They validate schemas, orchestration, failure behavior, and
repeatability—not real-league recommendation accuracy.

Draft, Trade, and Waiver policy must remain separate. Calibration and audit
evidence belong to one declared league, season, scoring system, roster context,
and decision horizon. Do not transfer a policy, result, historical manager
curve, or recommendation to another league without separate evidence. Expert
rankings are authoritative only for their declared preseason, rest-of-season,
or weekly horizon.

The public configuration is intentionally uncalibrated. Until a league-local
policy has been reviewed and approved, decision commands report that limitation
instead of implying readiness. No stable or non-alpha recommendation-quality
claim is made by this release.

## Required data and recurring audit workflow

Users provide their own league configuration and any required FantasyPros HOF
Premium credential. Provider responses, manual imports, generated evidence,
and real league records remain local and ignored by Git.

For each league and relevant decision cycle:

1. Run `roster-theory inputs prepare LEAGUE --assistant MODE` (or the documented
   all-league form) to refresh or reuse only evidence that passes its freshness
   and authority checks.
2. Run `roster-theory inputs status LEAGUE` or `roster-theory doctor` and resolve
   every missing, stale, partial, ambiguous, or uncalibrated result.
3. Run the selected assistant. Treat its output as advice for human review, not
   an instruction that RosterTheory can execute.
4. Preserve and review the saved evidence. Repeat preparation and the
   league-specific audit whenever rosters, availability, scoring, season, or
   the authoritative ranking horizon changes.

Free-tier or incomplete FantasyPros responses are sample-only and never
recommendation-ready. The model does not invent missing expert ranks.

## Data, licensing, and release boundary

The candidate contains no provider rankings, projections, API responses,
league records, or generated recommendation evidence. Shipped examples and
fixtures are project-authored synthetic data. Users must ensure their provider
access and local use are authorized; see `docs/THIRD_PARTY_NOTICES.md`.

The existing private Git graph is not part of the public candidate. The
reviewed tree is prepared as a new single-root history so retired identifiers
and personal commit metadata do not become reachable. The private repository
and ignored local evidence remain preserved as a backup.

OS-007 prepares and verifies this candidate only. It does not create a tag,
publish a GitHub release, change repository visibility, push rewritten history,
or upload a package. Those actions require separate explicit approval under
OS-013.
