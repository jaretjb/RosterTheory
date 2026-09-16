# RosterTheory Waiver Assistant requirements

Status: Approved initial baseline on September 9, 2026 (America/Los_Angeles)
Initial league: `league_alpha`
Scope: Read-only waiver decision support; this document does not authorize a
Sleeper roster transaction

## 1. Purpose

The Waiver Assistant helps the user decide whether adding an available player
and, when necessary, dropping one current player improves the exact roster
under the league's current rules. Player names are runtime inputs or search
results, never policy anchors or development requirements.

The assistant evaluates a waiver move as one roster transformation, not as a
two-manager trade. It must distinguish immediate starting value, longer-term
ownership value, usable depth, and the opportunity cost of the drop.

## 2. Product boundary and safety

- Commands, reports, configuration, evidence, and tests use a `waiver`
  namespace.
- The assistant never submits a claim, adds or drops a player, changes a
  lineup, or sends a message through Sleeper.
- Draft ADP, VONA, pick survival, room pace, and draft-slot policy do not
  determine waiver value.
- Trade partner benefit, fairness, acceptance, and bilateral package policy do
  not apply to waivers.
- Provider, identity, league scoring, weekly lineup, replacement, in-season
  valuation, risk, cache, and provenance capabilities may be shared when their
  semantics are feature-neutral.
- League Alpha evidence and policy may not be transferred to League Beta without a
  separate league-specific validation.

## 3. Initial workflows

### 3.1 Evaluate a named acquisition

The user can name an available player and optionally name a drop. The assistant
must refresh Sleeper, resolve the player exactly, confirm current ownership and
acquisition state, determine whether an open roster slot exists, and evaluate
the requested or best legal drop.

When no drop is supplied and the roster is full, the assistant must evaluate
every legal droppable skill player or a documented complete equivalent. It must
show the selected drop, the next-best alternatives, and any player excluded by
roster-lock, reserve, or unsupported-legality uncertainty.

### 3.2 Search waivers

After entered acquisition evaluation is validated, the assistant may search
the complete eligible unrostered pool. Candidate pruning may reduce expensive
exact evaluation only when the bound is deterministic, visible, and tested not
to hide controlled best moves.

### 3.3 Compare alternatives

The user can compare multiple add/drop pairs from the same immutable input
snapshot. The comparison must not refresh inputs between candidates.

## 4. Data requirements

Sleeper is authoritative for league rules, roster membership, reserve state,
waiver priority and budget fields, transaction state, and current player
ownership. Current non-ownership plus supported-position eligibility is
sufficient for candidate evaluation; exact free-agent versus waivers
classification is informational. The snapshot must preserve:

- league waiver-related settings and roster limits;
- each roster's waiver position, budget used, players, starters, and reserves;
- transaction type, status, creation and update times, adds, drops, waiver bid,
  and failure metadata when supplied;
- the capture time and a freshness gate suitable for an actionable waiver
  decision; and
- unmatched, ambiguous, locked, pending, partial, or unavailable state.

Competing pending claims do not block candidate evaluation. If their visibility
is unavailable, the assistant must not predict claim success.

FantasyPros may supply horizon-matched rankings, weekly and remaining-horizon
projections, injuries, and news under the existing budget and freshness rules.
Waiver Wire rankings, if the provider capability passes, remain a separately
labeled acquisition signal. They may not be silently blended into long-term
ownership value.

## 5. Evaluation requirements

For every add/drop alternative, calculate and preserve:

- selected-expert long-term ownership-value delta;
- market-consensus ownership-value delta;
- raw league-scored projection delta;
- remaining-week optimal-lineup delta and the weeks the added player starts;
- current-week lineup effect;
- usable depth and replacement exposure;
- bye and playoff coverage;
- player availability, injury, role, and material-news warnings; and
- offense concentration and the existing supported risk scenarios.

When the shared long-term value board is explicitly identified as a common
non-ROS horizon, it must not silently overrule complete fresher evidence. A
same-position add may satisfy the stale ownership gates only when it strictly
beats the legal drop in current-week rank and ROS consensus and has a
non-negative league-scored remaining projection delta. Every other evidence,
activity, legality, lineup, depth, concentration, and downside gate still
applies. Current ROS ownership values are never bypassed by this exception.

The strongest reason the recommendation could be wrong must be visible. A
bench stash must not be called worthless merely because it has no immediate
starter delta, and a highly ranked acquisition must not hide the value of the
player that must be dropped.

## 6. Decision language

The initial decision labels are:

- `ADD NOW`: a currently free agent passes the approved value and safety gates;
- `CLAIM`: a player currently on waivers passes those gates;
- `ACQUIRE`: an eligible unrostered player passes those gates when the exact
  transaction mechanism is unknown or pending;
- `WATCH`: the move is plausible but a required evidence, legality, or value
  gate is too uncertain for an affirmative recommendation; and
- `PASS`: the best legal roster transformation does not pass the documented
  value gates.

Exact thresholds belong in a versioned Waiver policy and require controlled
fixtures plus a hand audit before promotion. Until then, implementation may
report deltas without applying a final label.

FAAB bid amounts, waiver-priority opportunity cost, and claim-success
probabilities require separate calibration. The first release may report the
known budget/priority context but must not invent those outputs.

## 7. Initial scope and deferred scope

The first vertical slice supports one QB/RB/WR/TE addition plus zero or one
drop in League Alpha. Kicker and defense waiver streaming require their own weekly
matchup policy and are explicitly deferred. Multi-claim contingency queues,
automatic FAAB bids, dynasty, keepers, auction values, and transaction writes
are also deferred.

## 8. Acceptance criteria

1. The snapshot reconstructs all 10 League Alpha rosters and the user's roster with
   complete supported-player identity coverage.
2. It preserves and reports the league and user waiver state without a Sleeper
   write.
3. A named unrostered player resolves exactly; an owned, ambiguous, stale, or
   newly unavailable player stops visibly.
4. An open slot produces a no-drop evaluation; a full roster produces exactly
   one legal drop for the initial one-player acquisition.
5. Every reported candidate uses the same snapshot and value inputs.
6. Before/after weekly lineup, depth, long-term value, risk, and drop cost stay
   separate and reproduce from saved evidence.
7. Controlled fixtures cover an immediate starter upgrade, a bench-only
   insurance gain, and a case where the required drop makes the move negative.
8. Missing projections, ranks, injury/news freshness, waiver state, reserve
   legality, or supported-player coverage cannot produce an unqualified
   affirmative label.
9. Draft and Trade recommendations and evidence contracts remain unchanged.
10. The repository-root unit suite passes and no Sleeper write surface exists.
