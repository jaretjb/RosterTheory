# MA-002q: Sleeper Draft position-limit source check (#31)

September 28, 2026. Base: merged PR #61 (`b6e94e1`). This is an evidence-only
slice. No provider field mapping, decision policy or capability status changed.

## What Sleeper declares

Sleeper's [position-limit help](https://support.sleeper.com/en/articles/5379935-how-do-i-set-positional-limits)
separates roster spots from positional maximums. Commissioners configure the
maximums in a second Roster Settings tab and choose separately whether to
enforce them during the Draft. The article says the Draft switch is enabled by
default, IR and taxi players do not count, and trades or waivers may temporarily
exceed maximums. It does **not** publish the maximums of either reference league
or an API field name, shape, unit or unlimited sentinel for them.

Sleeper's [specific-draft API reference](https://docs.sleeper.com/#get-a-specific-draft)
shows `settings` and `slots_*` roster-place counts. It does not document
`enforce_position_limits`, positional maxima, the meaning of a missing switch,
or a relation between draft and league settings. The existing adapter recognizes
explicit integer `0`/`1` for the observed enforcement field; this is an
interpretation of the field name and binary convention alongside the help
article, not an API-documented binding. The UI default cannot fill an absent
API field.

## Reference evidence and admission

`tests/fixtures/modular/reference_rules.json` is the checked-in, redacted
read-only rule inventory. A key-only review on this base found:

| Profile | Draft enforcement field | Cap-like keys in draft settings | Cap-like keys in league settings | Current position-limit assessment |
| --- | --- | --- | --- | --- |
| `reference_a` | absent | none | `capacity_override`, `max_keepers`, `max_subs` | LIMITED: enforcement and maxima UNKNOWN |
| `reference_b` | integer `1` | `enforce_position_limits` only | same three unrelated keys | LIMITED: maxima UNKNOWN |

The league keys above are not positional maximums. The inventory contains
roster slot counts, but those describe places in a lineup or bench, not how
many players at each position Sleeper permits in a Draft. Draft `POSITION_CAPS`
are acquisition preferences. Neither can fill the missing source mapping.

The prior MA-002e assessment already classifies both reference scopes LIMITED;
its synthetic tests reject alleged `max_qb` and `position_limits` aliases as
unverified. PR #49 restored read-only room suggestions with a visible LIMITED
status and warning for absent or enabled-but-unmapped enforcement. This slice
does not turn that warning into a legality claim or promote either profile.
The #31 acceptance criteria extend beyond this one Draft scope, so #31 stays
open.

There is no admission change between merged PR #61 and this branch: `git diff
--exit-code origin/main -- src tests scripts` is clean. Running
`assess_draft_position_limits` on the two fixture drafts gives A
`UNKNOWN/UNKNOWN -> LIMITED` and B `SUPPORTED/UNKNOWN -> LIMITED` for
enforcement/maxima. The focused Draft admission and roster-matrix suite passes
14 tests, including the synthetic non-mapping cases. This documents the
before-and-after admission boundary without treating absent evidence as a cap.

## Missing evidence and recovery

For A, obtain a fresh source declaration of whether the Draft switch is enabled
for its draft; absence cannot be treated as the documented UI default. For B,
verify that the observed integer `1` has the intended enabled meaning in its
source/API version. For each profile independently, obtain its actual per-position
maximums and a verified mapping from the authoritative Sleeper source to API
fields, including missing values, unlimited values, position names, and the
league-to-draft association. An official API schema or a controlled, read-only
comparison of commissioner UI values with fresh league and draft responses
would support that mapping. Record only sanitized field names, types, status and
aggregate counts publicly; preserve any raw league evidence outside the repo.
Do not use private history or change league settings to manufacture a probe.

Only after that evidence exists should a separate reviewed slice implement
neutral count/enforcement mechanics with synthetic at-cap, over-cap, IR/taxi and
missing-source tests, plus before-and-after admission results for A and B. Full
Draft and other-feature capability admission still needs its own #31 evidence.
Rollback of this evidence-only PR is a documentation revert; saved artifacts
and reader schemas did not change.

## Local verification

The full suite passed (954 tests). Ruff, compilation, 18 context-routing tests,
tracked and staged repository privacy gates, package build, distribution gate,
clean wheel install smoke, import smoke and staged diff checks passed. PR CI is
the remaining remote gate.
