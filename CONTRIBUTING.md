# Contributing to RosterTheory

RosterTheory is a local, read-only fantasy-football decision-support project.
The initial release is GitHub source-only. Contributions are welcome once the
repository is made public; this file does not announce publication.

Before changing a product track, read `.codex/context/STEERING.md` and follow its one
route. `.codex/context/ACTIVE_MILESTONE.md` authorizes implementation; do not promote a
league's calibration or result into another league. Keep Draft, Trade, and
Waiver decision policies separate. Recommendations must never submit a Sleeper
pick, trade, waiver claim, or lineup change.

## Local setup

Use Python 3.11 or newer. From a checkout:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python -m unittest tests.test_context_routing
python -m unittest discover -s tests
```

On macOS/Linux, activate with `source .venv/bin/activate`. Production code
uses the Python standard library; tests use `unittest`. Offline help,
`example-config`, and `doctor` need no provider credentials. Provider tests
should use fakes or synthetic fixtures, never live private league evidence.
Run the fast context-routing check after editing `.codex/context`, a backlog,
or public repository metadata; CI runs the same gate on every push and pull
request.

## Patches

- Open an issue for a material behavior or policy change before implementing
  it, unless a maintainer has already identified the task.
- Keep patches bounded, include tests for changed behavior, and explain the
  fantasy-football consequence and any degraded-data behavior.
- Use invented league, draft, owner, team, and player identifiers in public
  fixtures. Do not commit `.env`, API keys, Sleeper responses, personal exports,
  expert data without redistribution rights, or private histories.
- Preserve JSON, evidence, and read-only contracts; report partial or
  ambiguous data rather than silently omitting it.
- Include the command and result of relevant tests in a pull request. Do not
  rewrite repository history or publish a release as part of an ordinary PR.

By participating, you agree to [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md). For
security concerns, use [SECURITY.md](SECURITY.md), not a public issue.

Changes intended for a release candidate must pass the complete automated
workflow and the manual review items in
[`docs/RELEASE_CHECKLIST.md`](docs/RELEASE_CHECKLIST.md).
