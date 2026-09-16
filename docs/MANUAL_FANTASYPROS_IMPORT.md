# Manual FantasyPros Pro import

> Fallback only as of August 23, 2026. The user now has HOF Premium API access, and `fantasypros-grouped-rankings` supersedes the manual ranking-selection/download steps. Keep this guide for recovery if API access is unavailable.

This workflow turns FantasyPros Pro CSV exports (or copied tables saved as CSV/TSV) into a league-scored RosterTheory board. It never changes the FantasyPros account and never makes a Sleeper pick.

## What to export

Create `data/manual/fantasypros_2026/`. This directory is ignored by Git so the personal-use FantasyPros data will not be committed.

Before choosing a FantasyPros scoring format, refresh both Sleeper snapshots and inspect the live reception setting. Do not assume a format from an earlier handoff:

```powershell
$env:PYTHONPATH = "src"
python -m roster_theory snapshot league_alpha
python -m roster_theory snapshot league_beta
```

Use Standard when Sleeper `rec` is `0`, Half-PPR when it is `0.5`, and PPR when it is `1`. The import command requires `--rankings-scoring` and refuses to run when that declaration conflicts with the current Sleeper snapshot.

### 1. One selected-consensus rankings export for each scoring format

The public repository does not ship FantasyPros rankings, accuracy histories,
expert IDs, or a recommended expert pool. Obtain those inputs through your own
authorized FantasyPros access and keep them under
`data/manual/fantasypros/`. FantasyPros requires attribution for published
research based on its API data and reserves redistribution rights for its
commercial offering; see `docs/THIRD_PARTY_NOTICES.md`.

If you use historical expert weighting, preserve the raw annual records,
normalize each year's ranks against that category's field size, keep coverage
explicit, and write the derived master and selected pool to the ignored paths
accepted by the CLI. `examples/expert_accuracy_template.csv` and
`examples/expert_pool_template.csv` document the schemas with synthetic rows;
they are not authoritative rankings and must never be used as a draft-ready
pool.

Open [FantasyPros Half-PPR Draft Rankings](https://www.fantasypros.com/nfl/rankings/half-point-ppr-cheatsheets.php), choose **Draft** and **Overall**, then open **Pick Experts**. Select only the experts justified by your locally retained evidence and click **Apply**. Before downloading, verify the displayed consensus count; a `filters=` URL by itself is not sufficient evidence that the picker state loaded.

Use the visible **Download CSV file** control. Save:

- Standard as `rankings_standard.csv` for `league_alpha`.
- Half PPR as `rankings_half_ppr.csv` for `league_beta`.

Verify the expert count before each download. The Pro CSV contains the selected consensus rather than individual rank columns; RosterTheory recognizes that layout automatically. Because the CSV does not embed the contributing expert names, each import must explicitly name its local scoring-specific expert-pool file as provenance.

If FantasyPros instead supplies an expert matrix with one column per analyst, keep it unchanged. RosterTheory still supports that richer format and applies its own position-specific numerical weights.

If download is unavailable, copy the complete rendered table into Excel or Google Sheets and save it as CSV or TSV. Preserve `RK` (or `ECR`), `PLAYER`, and `POS`, plus every QB/RB/WR/TE row.

### 2. Four full-season projection exports, shared by both leagues

Open the full-season (`week=draft`) projection pages and use **Download data**:

- [QB projections](https://www.fantasypros.com/nfl/projections/qb.php?week=draft) → `projections_qb.csv`
- [RB projections](https://www.fantasypros.com/nfl/projections/rb.php?week=draft) → `projections_rb.csv`
- [WR projections](https://www.fantasypros.com/nfl/projections/wr.php?week=draft) → `projections_wr.csv`
- [TE projections](https://www.fantasypros.com/nfl/projections/te.php?week=draft) → `projections_te.csv`

Keep the raw stat columns (`YDS`, `TDS`, `REC`, and so on). RosterTheory ignores FantasyPros' canned `FPTS` value and calculates projected points from each league's actual Sleeper scoring settings. The filename must contain `QB`, `RB`, `WR`, or `TE` so the repeated stat headings can be interpreted correctly.

### 3. One overall ADP export for each scoring format

Download the full overall table, including its `AVG` or actual `ADP` column:

- [Standard ADP](https://www.fantasypros.com/nfl/adp/overall.php) → `adp_standard.csv`
- [Half-PPR ADP](https://www.fantasypros.com/nfl/adp/half-point-ppr-overall.php) → `adp_half_ppr.csv`

Do not supply an `ECR vs ADP` difference column in place of actual ADP. The importer prefers `AVG`, then `ADP`.

## Build both boards

From the repository root in PowerShell:

```powershell
$env:PYTHONPATH = "src"

$projections = @(
  "data/manual/fantasypros_2026/projections_qb.csv",
  "data/manual/fantasypros_2026/projections_rb.csv",
  "data/manual/fantasypros_2026/projections_wr.csv",
  "data/manual/fantasypros_2026/projections_te.csv"
)

python -m roster_theory manual-board league_alpha `
  --rankings data/manual/fantasypros_2026/rankings_standard.csv `
  --rankings-mode selected-ecr `
  --rankings-scoring standard `
  --projections $projections `
  --adp data/manual/fantasypros_2026/adp_standard.csv `
  --expert-pool data/manual/fantasypros/expert_pool_standard_recommended_2026.csv

python -m roster_theory manual-board league_beta `
  --rankings data/manual/fantasypros_2026/rankings_half_ppr.csv `
  --rankings-mode selected-ecr `
  --rankings-scoring half-ppr `
  --projections $projections `
  --adp data/manual/fantasypros_2026/adp_half_ppr.csv `
  --expert-pool data/manual/fantasypros/expert_pool_half_ppr_recommended_2026.csv
```

The first run downloads Sleeper's public player directory to ignored `data/cache/sleeper_players.json`; later runs reuse it. Add `--refresh-sleeper-players` if Sleeper adds or changes a player.

Each run writes four ignored artifacts under `data/exports/`:

- `*_manual_board.csv`: weighted, league-scored player board;
- `*.metadata.json`: source counts, coverage, baselines, and draft-readiness checks;
- `*.matches.csv`: every ranked player and the Sleeper match decision;
- `*.issues.csv`: malformed rows and unrecognized expert columns.

The board is labeled `draft_ready=true` only when its configured pool has at least five draft-accuracy experts, it has at least 150 skill players, all four replacement baselines, at least 90% projection and ADP coverage among the top 180, complete top-180 Sleeper matching, and no suspicious/unrecognized numeric ranking columns.

## Resolve an unmatched or ambiguous player

Nothing is silently discarded. Unmatched and ambiguous players remain on the board with a name-based key and appear in `*.matches.csv`. Ambiguous rows include the candidate Sleeper IDs.

Copy `examples/player_match_overrides_template.csv`, fill only confirmed resolutions, and rerun with:

```powershell
python -m roster_theory manual-board league_alpha ... `
  --player-overrides data/manual/fantasypros_2026/player_match_overrides.csv
```

Never guess between candidates. If an unmatched player has no candidate, refresh the Sleeper player directory first.

## Repeat when rankings change

Replace only the changed export files using the same filenames and rerun the two commands. The audit artifacts are overwritten together, so the board and its readiness decision always describe the same import.

The synthetic files in `examples/manual_import_sample/` exercise both the individual-expert matrix and selected-consensus formats without containing a complete player pool. They must always report `NOT DRAFT-READY`.
