# Issue #30: scoring evidence acceptance

September 28, 2026. Base: merged PR #63 (`9b9d6a1`). This final slice fixes
the original false-completeness result in the legacy in-memory scorer and
audits the full #30 acceptance list. It does not certify live FantasyPros
coverage or make either reference league recommendation-ready.

## What changed for a fantasy decision

With 250 passing yards and no touchdown statistic, the old helper returned a
10-point subtotal and called it complete. It now returns the same diagnostic
subtotal with `pass_td` named as missing and `complete=false`. An explicit
zero touchdown remains complete. Invalid, conflicting and nonfinite inputs,
invalid multipliers and arithmetic overflow also cannot make this helper's
result complete. A reception bonus for a different position is irrelevant.
Its new `missing_settings` and `invalid_settings` fields are appended to the
in-memory result; callers using the original constructor arguments still work.

The production scoring paths already use the stricter, league- and
operation-scoped contract established across MA-002. This fix does not change
their points, ranking authority, decision thresholds or source availability.

## Acceptance evidence

| #30 requirement | Evidence on current main plus this slice |
| --- | --- |
| All nonzero reference settings inventoried | The frozen [inventory](../tests/fixtures/modular/scoring_inventory.json) records 35 active settings for A and 41 for B. Current adapter regressions account for every active and disabled setting separately: 35/113 for A and 41/2 for B. An unmapped or invalid active rule blocks complete points. These counts prove rule accounting, not delivery of raw statistics. |
| Independent QB, receiver, kicker and defense arithmetic | `tests.test_scoring_contract` hand-calculates all four roles. Provider tests independently check league-specific QB totals, reception premiums, kicking buckets and defense events. The same synthetic QB evidence yields 17 points under A's interception rule and 18 under B's. |
| Missing, zero, invalid and unsupported inputs | Core and provider tests distinguish absent touchdowns from observed zero; reject invalid/nonfinite values, conflicting aliases, unknown bonuses and overflow; and require exact event buckets. The original defect probe now reports `missing_complete=false`, `explicit_zero_complete=true`; its historical captured fixture remains unchanged. |
| Position relevance and structural zero | Known inapplicable settings need no statistic, including an RB reception bonus on a QB. Unknown positions do not excuse missing evidence. The neutral contract keeps an observed zero distinct from a structural zero with a cited source rule. No FantasyPros or Sleeper sparse-field zero rule has been verified or assumed. |
| Core/adapter and three-feature readiness | The new regression checks the legacy core and weekly adapter on the same missing, invalid, unsupported and irrelevant examples. Draft manual/API imports require complete, scoped points for readiness. Trade marks affected estimates conditional; Waiver can show an estimated player but cannot affirmatively add or claim from it. Waiver historical scoring also rejects incomplete actual-stat rows. |
| Scoped derivation, versions and saved evidence | Scoring scope binds league, season, operation, horizon and week. The two reference maps use their own coefficients. Weekly incomplete rows retain `scoring_incomplete_v1`; the Draft API source contract was versioned to v2 in PR #63. Existing raw caches are re-assessed; old derived results remain historical and exact-build replay does not silently upgrade them. This slice changes no persisted schema. |
| Semantic and safety gates | The full MA-001 synthetic output golden remains unchanged. No provider request, private-history access, live recommendation, calibration transfer or Sleeper write occurs. |

The [Sleeper scoring reference](https://support.sleeper.com/en/articles/3998131-what-scoring-options-are-available)
separates passing, receiving, kicking, team defense, player special teams and
miscellaneous fumble events. The [FantasyPros API documentation](https://api.fantasypros.com/public/v2/docs)
shows example projection fields, but examples do not guarantee that every
position or week supplies every field. An omitted, unverified field therefore
remains unavailable; no recommendation-readiness or wider-format claim follows
from closing #30. Source coverage can be revisited during later support-matrix
work when there is independent evidence.

Rollback: revert this PR as a unit. No user data or saved artifact is migrated;
the historical defect fixture remains a record of the original result.

Local verification: 83 focused tests and all 957 repository tests pass,
including the unchanged 24-workload MA-001 semantic golden. Ruff, Python
compilation, 18 context-routing checks, tracked privacy, package build,
distribution gate, clean wheel-install smoke and import smoke pass. Staged
privacy and PR CI remain before review handoff.
