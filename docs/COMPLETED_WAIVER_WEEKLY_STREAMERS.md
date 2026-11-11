# WA-035 independent weekly skill streamers

The user authorized activating and implementing issue #80 after the WA-034
kicker repair. This work uses a separate branch based on that repair.

## Behavior

Waiver preparation retains selected-expert weekly position ranks separately
from ownership values. A player outside the selected/market ownership boards
keeps the player's weekly forecasts and rank without receiving a fabricated
ownership value. Existing expert weighting and source freshness checks apply.

The weekly comparison uses the current-week projection matrix and the existing
exact lineup optimizer. It compares the owned active skill lineup with each
available target and legal skill drop, or an open active slot. Flex, superflex
and multiple player positions follow the league's slot eligibility. A mention
requires the target to start and increase lineup points while preserving fixed
starter coverage. Known current absences and byes remain excluded.

Each mention records the lineup gain, displaced starters, the proposed drop's
weekly points and available ROS rank, forecast coverage and retention warnings.
Injury retention, above-replacement ROS holdings, supplied contingency evidence,
backup-QB coverage and missing future effects remain visible. The comparison
can suggest a weekly starter when the target lacks ROS ranks, long-term values
or future forecasts. Missing current-week core evidence stays an exclusion.

Singleton mentions appear alongside the default weekly plan and in ROS reports.
They keep their separate evidence and require combined-claim revalidation.
Season acquisition gates and plan thresholds retain their existing behavior.
An unavailable multiweek plan preserves its limitation alongside any supported
weekly mentions. A changed-roster evidence/legality failure rejects the affected
plan alternative and records the reason.

## Compatibility and evidence

Input schema 11 adds independent weekly position ranks. Earlier bundles retain
their existing rank fields as a fallback. Search schema 14 includes streamer
omissions and weekly-plan limitations. Normal search publication and offline
manifest replay use the same weekly inputs and preserve deterministic hashes.
Historical manifests retain the existing build-verification requirements.

Regression cases cover ROS-blocked and ROS-unranked starters, missing future
forecasts, inactive/bye/owned/locked targets, backup QBs, superflex, multiple
positions, protected drops, open slots, missing current evidence, no legal drop,
availability scenarios, preparation, fresh news, default reports and replay.
All fixtures are synthetic. Private provider and league data remain ignored.

Validation passes all 1,130 unit tests, including 21 new weekly regressions.
Ruff, compilation, repository privacy, distribution contents and clean wheel
installation pass. The wheel matches all 139 production Python source files.
Both synthetic league baselines retain their existing season claim decisions.

PR #90's Windows Python 3.11 run exposed a race when simultaneous requests
opened a fresh pacing lock file. The lock now acquires the same byte range
without writing a marker. Regression coverage checks fresh empty lock files
and existing marker files alongside the process spacing and recovery tests.
