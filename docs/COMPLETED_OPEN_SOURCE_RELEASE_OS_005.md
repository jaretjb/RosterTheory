# OS-005 — Installable package and public documentation

Completed September 15, 2026 (America/Los_Angeles).

The initial release path is GitHub source-only. No PyPI upload, GitHub
publication, history rewrite, or private-data removal occurred in this task.
`pyproject.toml` now declares the README, MIT expression and license file,
Jaret Brown as author, project URLs, classifiers, keywords, and Python 3.11+.
Production dependencies remain empty and standard-library only.

The wheel bundles a synthetic league template exposed by the offline
`roster-theory example-config` command. League configuration resolves from a
per-user location, `ROSTER_THEORY_CONFIG`, or `--config`, independently of the
checkout. Provider-derived expert, pool, and NFL schedule inputs are not
bundled; missing-file errors point to explicit CLI paths and `doctor`. Local
data and cache defaults intentionally resolve from the command's working
directory and are documented as such.

The README now covers implemented Draft, Trade, and Waiver workflows, weekly
and expert-horizon limits, FantasyPros HOF Premium and free-tier sample-only
restrictions, offline setup, and the no-Sleeper-writes promise. Public
`CONTRIBUTING.md`, `SECURITY.md`, `CODE_OF_CONDUCT.md`, and `CHANGELOG.md` are
included in the source archive.

Verification: `python -m build --no-isolation` produced a wheel (74 archive
entries) and source distribution (168 entries). Archive inspection found no
`data/`, `.env`, private-league markers, or completed private Trade records.
The final wheel installed without dependencies into a new virtual environment
outside the checkout. Bare launch, guided help, plain/no-banner help, bundled
config output, offline `doctor`, `python -m roster_theory`, strict JSON output,
and narrow banner fallback passed. A saved synthetic config reported zero
provider calls and zero Sleeper writes, with no calibrated recommendation.
The complete 505-test suite passed.

OS-006 release quality and security gates remain before any public candidate.
