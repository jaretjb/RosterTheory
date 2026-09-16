# OS-011 — Read-only setup diagnostics

Completed September 15, 2026 (America/Los_Angeles).

`roster-theory doctor [LEAGUE]` checks only local configuration and files by
default. It reports config discovery, owner and league identity, Draft identity,
league-scoped Draft/Trade/Waiver policies, and selected local Draft board,
Trade schedule/expert pool, and Waiver input paths. It provides a safe next
action for every missing, invalid, unavailable, or uncalibrated check.

Each league has separate Draft, Trade, and Waiver data-only and decision
summaries. `ready` means a local prerequisite or policy scope check passed, not
that provider evidence is fresh or a league is calibrated. Even when all local
checks pass, decision status remains `unavailable` until separate live evidence
and league-local calibration are verified. A data-only path can therefore be
locally ready while its decision policy is uncalibrated.

Human output lists statuses and next actions. `--json` produces one strict
redacted result without credentials, private filesystem paths, owner/league/
draft IDs, or numeric league keys; numeric keys use config entry numbers.
Missing setup is a successful diagnosis, not an external-operation failure.

Synthetic tests cover two independent leagues, missing and invalid config,
empty leagues, invalid identities, missing files/policies, cross-league policy
rejection, a fully configured offline example, selected-league scoping, JSON
redaction, and no provider calls. The focused CLI suite passed 18 tests; the
complete repository suite passed all 496 tests. No provider request, Sleeper
write, evidence deletion, history rewrite, or publication occurred.
