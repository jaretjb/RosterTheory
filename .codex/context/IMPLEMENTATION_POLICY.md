# Conditional implementation and data-operation policy

Load this file only for product implementation, simulation, live/provider data
work, or validation of those changes.

## Working agreement

- Work on one named active milestone at a time and stop at a tested handoff.
- Explain fantasy-football consequences before implementation details.
- Keep this a small local decision-support tool. Do not add hosting, accounts,
  databases, or frameworks without agreement.
- Do not start a simulation or operational interface until required data passes
  completeness checks and the user approves moving on.
- Update only the affected `.codex/context/status/` handoff. Put detailed evidence in the
  relevant completed milestone and chronology in the archive.

## Data rules

- HOF Premium is the primary FantasyPros source. Respect 1 request/second and
  500 requests/day.
- Treat `data/cache/`, `data/exports/`, and `data/manual/` as ignored personal
  or reproducible artifacts.
- Sleeper is read-only and requires no credentials.
- Label free-tier FantasyPros results sample-only. Never call incomplete data
  draft-ready or recommendation-ready.
- Prefer sustained multi-year accuracy, coverage adjustment, and concentration
  limits. Use shrinkage or independent market consensus only when the governing
  feature model specifies it, and preserve raw views.

## Technical and validation rules

- Python 3.11+; production code uses the standard library.
- Source: `src/roster_theory`; tests: `tests`.
- Use `apply_patch`, preserve unrelated user changes, and add or update
  `unittest` coverage for behavior changes.
- Inspect with `rg` and narrow line ranges. Do not dump whole large source files,
  documents, diffs, or generated evidence into the conversation.
- Keep routine test output compact. Use verbose output only for a focused test
  or while diagnosing a failure.
- Before handoff run:

```powershell
$env:PYTHONPATH = "src"
python -m unittest discover -s tests
```
