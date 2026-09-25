# AC-004 — Consistent Trade decisions and secondary moves

Issue: [#10](https://github.com/jaretjb/RosterTheory/issues/10).
Status: implemented; tested PR handoff pending.

## Shared decision contract

The exact evaluator now owns the package verdict and intrinsic, ECR ownership,
partner, modeled legality and confidence axes. Target search records that same
assessment and cannot approve a package whose entered verdict is COUNTER or
DECLINE. Its minimum gain, partner-plausibility, strategy/consolidation and chart
fairness screens remain explicit additional filters, not alternative intrinsic
verdicts. A positive intrinsic outcome is not a claim that every other gate passed.

Entered evaluation does not load a direct trade chart. Its market axis explicitly
states ECR ownership only, and confidence is provisional with respect to direct
market pricing. Target search adds chart evidence separately; ECR-proxy shortlists
remain visibly PROVISIONAL_MARKET in evidence, CSV and human output. Prior-week
pricing remains indicative-only, not an approved current offer. No paid/provider
refresh was performed for this repair.

## Required roster moves

Secondary candidates are evaluated as package-plus-move outcomes. Passing common
user value, lineup, depth, downside and partner ECR gates takes precedence over
raw lineup score. On lineup ties, retained ownership value, depth and downside
precede stable player IDs. Candidates remain cross-position.

Injured rostered players with positive selected or market ownership value are
protected from automatic sacrifice. This uses Trade ownership evidence, not
Waiver Value, waiver rank cutoffs or Waiver policy. Immediately dropping an asset
being received is unsafe. Explicit unsafe overrides remain visible but cannot
produce an acceptable verdict.

Missing secondary value/projection candidates are disclosed locally. All
evidenced free agents enter initial scoring; the former hidden projection-only
shortlist is removed. Existing player-pool/combination budgets remain bounded
heuristics, with counts and explicit disclosure that unevaluated combinations may
be better. The selection is not an exhaustive global trade optimizer. Reused
single-candidate assessments are memoized within one fixed package evaluation.

## Verification

`tests/test_trade_decision_consistency.py` adds nine regressions:

- Identical package verdict and all shared axes match entered evaluation for
  1-for-1, 1-for-2, 2-for-1 and 2-for-2 target-search candidates.
- Independent lineup, selected value, depth, downside, partner and legality
  perturbations change the correct gate; partner loss does not redefine user gain.
- Search cannot bypass the entered partner-value gate.
- Injured positive-value bench protection and cross-position lineup ties.
- A lower-lineup outcome that passes value gates beats a higher-lineup failure.
- Explicit received-asset drop is shown but declined.
- Bounded secondary search and unavailable chart pricing are visibly provisional.
- ECR-proxy target shortlist status remains provisional.

The partner-gate bypass and injured-drop regressions failed before repair and
passed afterward. Legacy tests expecting an immediately received asset to be
dropped were updated to the safe alternative; downstream search rejection counts
are no longer required when exact evaluation prevents the unsafe choice.

Exact evidence schema is 5; target-package evidence schema is 2. The common axes
identify engine `ac-004-common-axes-v1`; older evidence remains offline replay.
Verification: all 746 unit tests pass; Ruff and `git diff --check` pass.

No Sleeper action, live league report or calibration change occurred. AC-005
through AC-008 remain planned; this milestone does not close the overall audit.
