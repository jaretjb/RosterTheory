# Third-party data notices and disposition

Updated: September 14, 2026 (America/Los_Angeles)

The MIT license covers RosterTheory's code and project-authored documentation.
It does not grant rights to third-party rankings, projections, API responses,
league records, schedules, names, logos, or other data.

Disposition labels in this inventory are:

- `REDISTRIBUTE`: project-authored material retained in the public tree.
- `REGENERATE`: omitted from Git; a user may recreate it locally using their
  own authorized access.
- `SYNTHETIC_FIXTURE`: invented data retained only to demonstrate a schema or
  test behavior.
- `USER_SUPPLIED`: omitted from Git and provided locally by the user.
- `REMOVE`: excluded from the public tree and not required at runtime.

These are conservative repository decisions, not legal advice or a statement
that factual information is always copyrightable.

## Provider terms reviewed

### FantasyPros

FantasyPros' [API terms](https://api.fantasypros.com/public/v2/terms-of-use)
describe personal, non-commercial, non-transferable use and restrict
distribution of API materials/data. Its current
[API plans](https://www.fantasypros.com/api-data/) reserve redistribution
rights for commercial access, and its
[official access guidance](https://support.fantasypros.com/hc/en-us/articles/49749297704475-How-do-I-request-access-to-the-FantasyPros-API)
requires FantasyPros credit when publishing research based on API data.

Decision: the public repository ships integration code, schema-only templates,
and synthetic fixtures, but no FantasyPros rankings, projections, expert IDs,
accuracy tables, API responses, or selected-expert pools. Users generate or
import those under ignored `data/manual/`, `data/cache/`, and `data/exports/`
paths using their own authorization. Research summaries that remain public are
project-authored prose and credit FantasyPros here; they are not a substitute
for the underlying data.

### Sleeper

Sleeper's [API documentation](https://docs.sleeper.com/) describes a read-only
API for non-commercial use and requests attribution for trending data. Its
[current terms](https://support.sleeper.com/en/articles/5486620-general-terms-of-use)
restrict automated third-party retrieval without approval.

Decision: no downloaded player directory, league, roster, matchup,
transaction, or draft record is shipped. Public examples use invented owners,
players, teams, leagues, and IDs. RosterTheory remains read-only; users are
responsible for ensuring their own API use is authorized. No trending dataset
is included.

### NFL and clubs

The [NFL.com terms](https://www.nfl.com/legal/terms/) restrict copying and
systematic retrieval or compilation of service content without permission.
NFL and club names and marks remain the property of their respective owners.

The independent
[`nflverse-data`](https://github.com/nflverse/nflverse-data) project publishes a
schedule release under
[CC BY 4.0](https://github.com/nflverse/nflverse-data/blob/main/LICENSE.md).
That license permits reuse and adaptation subject to attribution and change
notices; it does not grant NFL trademark rights or imply NFL endorsement.

Decision: official schedule and bye tables are not shipped. The
`roster-theory inputs schedule refresh` command retrieves the nflverse
`schedules` release into an ignored local cache, retains the required
attribution and provenance, and derives bye weeks only after complete
validation. A user-authorized, provenance-checked CSV import remains the
command-driven fallback. RosterTheory's optional defense-order file is
contributor-authored editorial preference, not a copied NFL ranking or
schedule; its team references are nominative text only. RosterTheory is not
endorsed by nflverse, the NFL, any club, FantasyPros, or Sleeper.

## Configuration artifact inventory

| Artifact | Source and transformation | Necessity | Terms / attribution | Disposition |
| --- | --- | --- | --- | --- |
| `config/leagues.example.json` | Invented league, owner, and draft values | Public setup schema | None | `SYNTHETIC_FIXTURE` |
| `config/defense_draft_order_2026.csv` | Contributor-authored editorial ordering; no copied rankings | Optional Draft preference | NFL/club marks acknowledged above | `REDISTRIBUTE` |
| `config/trade/phase6_policy.json` | Project-authored scenario and decision thresholds derived from RosterTheory tests | Trade evaluation default | No third-party rows; FantasyPros/Sleeper credited above for research context | `REDISTRIBUTE` |
| `config/trade/phase7_search_policy.json` | Project-authored search thresholds derived from RosterTheory tests | Trade search default | No third-party rows; FantasyPros/Sleeper credited above for research context | `REDISTRIBUTE` |
| `config/expert_accuracy_2021_2025.csv` | FantasyPros accuracy results aggregated into ranks, percentiles, and coverage | Historical weighting input | Personal terms do not grant redistribution | `REGENERATE` (removed; local path `data/manual/fantasypros/`) |
| `config/expert_accuracy_2023_2025.csv` | Earlier FantasyPros accuracy summary | Superseded | Personal terms do not grant redistribution | `REMOVE` |
| `config/expert_accuracy_annual_2021_2025.csv` | FantasyPros annual accuracy rows normalized by field size | Recency weighting input | Personal terms do not grant redistribution | `REGENERATE` (removed; local path `data/manual/fantasypros/`) |
| `config/expert_pool_2026.csv` | FantasyPros picker/export expert names and IDs | Manual-import provenance | Personal terms do not grant redistribution | `USER_SUPPLIED` (removed) |
| `config/expert_pool_standard_recommended_2026.csv` | Project selection applied to FantasyPros expert identity/availability data | Optional Standard pool | Underlying provider data is not redistributable | `REGENERATE` (removed) |
| `config/expert_pool_half_ppr_recommended_2026.csv` | Project selection applied to FantasyPros expert identity/availability data | Optional Half-PPR pool | Underlying provider data is not redistributable | `REGENERATE` (removed) |
| `config/expert_pool_overrides_2026.csv` | Local decisions tied to FantasyPros picker availability | Optional pool overrides | Underlying provider state is not redistributable | `USER_SUPPLIED` (removed) |
| `config/trade/inseason_accuracy_2021_2025.csv` | FantasyPros weekly accuracy rows plus normalized percentiles | Trade expert selection | Personal terms do not grant redistribution | `REGENERATE` (removed) |
| `config/trade/inseason_expert_pool_2026.csv` | Project weights applied to FantasyPros expert names, IDs, and availability | Trade selected-expert board | Underlying provider data is not redistributable | `REGENERATE` (removed) |
| `config/trade/nfl_byes_2024_2025.json` | Manually compiled from archived NFL schedules | Historical Trade backtest | NFL.com terms do not grant compilation redistribution | `USER_SUPPLIED` (removed) |
| `config/trade/nfl_schedule_2026.json` | Manually compiled and verified from NFL schedule pages | Trade horizon evaluation | NFL.com terms do not grant compilation redistribution | `USER_SUPPLIED` (removed) |

Removed configuration originals are retained only in ignored private archive
storage for local continuity. Runtime defaults now point to ignored local paths;
missing or incomplete authoritative inputs must stop visibly.

## Example and test artifact inventory

Every retained file below was authored specifically for RosterTheory with
invented values. None is authoritative, recommendation-ready, or suitable for
a real league.

| Artifact | Purpose | Disposition |
| --- | --- | --- |
| `examples/manual_import_sample/adp.csv` | Minimal ADP parser sample | `SYNTHETIC_FIXTURE` |
| `examples/manual_import_sample/projections_qb.csv` | Minimal QB projection schema | `SYNTHETIC_FIXTURE` |
| `examples/manual_import_sample/projections_rb.csv` | Minimal RB projection schema | `SYNTHETIC_FIXTURE` |
| `examples/manual_import_sample/projections_wr.csv` | Minimal WR projection schema | `SYNTHETIC_FIXTURE` |
| `examples/manual_import_sample/projections_te.csv` | Minimal TE projection schema | `SYNTHETIC_FIXTURE` |
| `examples/manual_import_sample/rankings.csv` | Synthetic expert-matrix schema | `SYNTHETIC_FIXTURE` |
| `examples/manual_import_sample/rankings_selected_ecr.csv` | Synthetic selected-consensus schema | `SYNTHETIC_FIXTURE` |
| `examples/manual_import_sample/sleeper_players.json` | Invented provider-identity map | `SYNTHETIC_FIXTURE` |
| `examples/player_match_overrides_template.csv` | Invented identity-override row | `SYNTHETIC_FIXTURE` |
| `examples/rankings_long_template.csv` | Generic long-ranking input schema | `SYNTHETIC_FIXTURE` |
| `examples/expert_accuracy_template.csv` | Generic historical-accuracy schema | `SYNTHETIC_FIXTURE` |
| `examples/expert_pool_template.csv` | Generic draft expert-pool schema | `SYNTHETIC_FIXTURE` |
| `examples/inseason_expert_pool_template.csv` | Generic Trade expert-pool schema | `SYNTHETIC_FIXTURE` |
| `examples/nfl_schedule_template.json` | Invented 32-team schedule schema | `SYNTHETIC_FIXTURE` |
| `examples/nfl_byes_template.json` | Invented historical-bye schema | `SYNTHETIC_FIXTURE` |

The files under `tests/fixtures/provider/` are also invented and exist only to
exercise data loaders without provider data.

## Documentation artifact inventory

The following data-heavy records were removed from the public tree and retained
only in ignored private archive storage:

| Former artifact | Embedded source material | Disposition |
| --- | --- | --- |
| `docs/EXPERT_SELECTION_2026.md` | Large FantasyPros-derived accuracy tables and expert IDs | `REMOVE` |
| `docs/EXPERT_POOLS_2026.md` | FantasyPros-derived expert selection tables and generated-ranking summaries | `REMOVE` |
| `docs/TRADE_INSEASON_EXPERT_SELECTION_2026.md` | FantasyPros weekly accuracy and selected-expert table | `REMOVE` |
| `docs/LEAGUE_ALPHA_2026_DRAFT_REVIEW.md` | Substantial Sleeper draft/roster record and provider grades | `REMOVE` |
| `docs/COMPLETED_LEAGUE_ALPHA_ROSTER_DEPTH_MILESTONE.md` | Detailed provider-derived and league-specific evaluation record | `REMOVE` |

All other shipped Markdown in `docs/` is project-authored requirements,
design, methodology, operational guidance, task/status records, or bounded
analytical summary. It may name a provider, professional player, expert, or
team and may summarize a result, but it does not ship the underlying rankings,
projections, API responses, league records, or schedule tables. Those documents
are `REDISTRIBUTE` under the repository's MIT license, with FantasyPros,
Sleeper, and NFL attribution supplied by this notice where applicable.

Provider names and trademarks are used only to identify interoperability and
source provenance. No provider sponsors or endorses RosterTheory.
