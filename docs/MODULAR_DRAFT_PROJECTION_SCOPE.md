# MA-002l: Draft API preseason projection-source scope

Status: bounded issue #30 follow-up; CI and review remain the merge gate.

The Draft API board formerly requested projections by season and position but
did not specify `week=0`. It rejected a conflicting declared week or season,
yet accepted responses with those declarations missing. For example, a QB
response with no `week` could become season-long points if its player statistics
were otherwise complete. [FantasyPros' public NFL projection schema](https://api.fantasypros.com/public/v2/docs)
declares `season`, `week`, and `positions`; week zero denotes preseason.

The importer now requests week zero and admits raw statistics only when the
response declares the requested season, week zero, and exact position. A
contradictory optional year, type, rest-of-season marker or fallback label also
rejects the source. Missing declarations remain unverified; the request path
does not substitute for provider evidence. Each source records declarations and
scope reasons, and any uncertain source keeps the import incomplete. Rejected
responses are excluded before player-ID duplicate checks, so a wrong-scope QB
row cannot erase an independently valid RB projection with the same ID.

Synthetic tests cover missing and contradictory declarations, weekly and ROS
responses, fallback labels, explicit week-zero requests and independent valid
position preservation. Expert ordering and existing complete-case scoring stay
separate. No paid provider call, live Draft operation, league write, ranking
policy change, or Trade/Waiver behavior change occurred. Real provider field
semantics and coverage, `fum_rec`, positional-cap mapping and overall MA-002
acceptance remain open.

Local handoff: 915 tests pass with unchanged MA-001 reference goldens; Ruff,
compilation, context routing and tracked-tree privacy checks pass.
