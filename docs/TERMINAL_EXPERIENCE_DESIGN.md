# Roster Theory terminal experience redesign

Status: proposed design, September 15, 2026 (America/Los_Angeles).

This is a new refinement after completed OS-009 through OS-012, not a
retroactive failure of those tasks. Planning this experience does not activate
an implementation milestone or change the OS-006/OS-013 public-release gates.
Implementation tasks are in docs/TERMINAL_EXPERIENCE_TASKS.md.

## 1. Outcome and boundaries

The interactive console should feel like a distinctive Roster Theory product:
a large, legible wordmark spelling both words; bright-yellow pixel linework
with an original arcade-scoreboard motif; a command title visible immediately; and readable
health and decision reports. The wordmark must never be only an RT monogram.

The user should see the identity on every ordinary interactive human command,
not just welcome and guided help. Doctor deserves a full checkup screen,
because it is a common first-run command. Its job remains offline diagnosis,
not repair. It must never query a provider, mutate a league, or imply that
local file presence proves current evidence or calibration.

The redesign owns presentation only. It must not change Draft, Trade, or Waiver
decision policy, league-local calibration, projections, simulation, provider
call plans, evidence hashes, exit codes, or Sleeper's read-only boundary.
Missing, ambiguous, partial, stale, and unavailable data stay conspicuous.
The expert ranking horizon and actual league scoring labels stay visible.

## 2. Design direction: the arcade scoreboard

The visual language is an original terminal-native 1980s arcade scoreboard:
bright game-cabinet yellow, warm cream text, stepped pixel lettering, double
rules, small diamond/pip motifs, and deliberate black-space rhythm. It takes
broad inspiration from the energetic gold-on-dark hierarchy of classic games
and modern terminal tools without copying another product's mascot, wording,
glyphs, or screen geometry.

The full wordmark is built from bespoke fixed-width glyphs for every letter in
ROSTER THEORY. On wide terminals the two words are stacked and each is drawn
at the same large pixel scale; neither word is a subtitle. It has a readable
full-name line beneath the glyphs, so the brand survives ambiguous fonts and
screen captures. Decorative borders are framing devices, not giant containers
around every paragraph.

The static README marquee gives those glyphs an oversized, hard-edged gold
extrusion inspired by 1990s video-game title screens. It labels the product as
`FANTASY FOOTBALL ASSISTANT` directly above `DRAFT ◆ TRADE ◆ WAIVER`; those
lines remain subordinate to the two-word title.

Conceptual wide-terminal specimen (synthetic content, not final glyph raster):

    ╔═◆══════════════════════  ROSTER THEORY  ══════════════════════◆═╗
    ║            ████   ███   ████  █████ █████ ████                 ║
    ║            █   █ █   █ █        █   █     █   █                ║
    ║            ████  █   █  ███     █   ████  ████                 ║
    ║            █  █  █   █     █    █   █     █  █                 ║
    ║            █   █  ███  ████     █   █████ █   █                ║
    ║                              •                                 ║
    ║             █████ █   █ █████  ███  ████  █   █                ║
    ║               █   █   █ █     █   █ █   █  █ █                 ║
    ║               █   █████ ████  █   █ ████    █                  ║
    ║               █   █   █ █     █   █ █  █    █                  ║
    ║               █   █   █ █████  ███  █   █   █                  ║
    ╚═◆══════════════════  INSERT COIN / CHOOSE WISELY  ═════════════◆═╝

The implementation must visually review all glyphs, kerning, border joins,
and Windows terminal rendering; this specimen specifies composition, not an
unreviewed final logo. Arcade yellow (`#FFD700`, or the nearest safe terminal
color) is the primary brand accent. Cream/muted bronze support hierarchy;
green, amber, and red are reserved for semantic status. Status is
always spelled out as text as well as colored.

### Width and capability tiers

| Surface | Identity | Layout |
| --- | --- | --- |
| Interactive, 100+ columns, Unicode and ANSI | Full bordered glyph wordmark | Two-column panels only where they remain legible |
| Interactive, 60-99 columns | Full-name bordered text wordmark, no cropped glyphs | Single-column cards |
| Interactive, 40-59 columns | Full "Roster Theory" name and command title | Minimal rule, wrapped sections |
| Below 40 columns or uncertain Unicode | Plain "Roster Theory / Command" | No box art; all content wraps |
| NO_COLOR or unsupported ANSI | Same hierarchy without color | Unicode if safe, otherwise ASCII |
| Redirected/piped human output | Plain full-name title, no art or ANSI | Stable linear sections |
| --json, CSV, saved evidence, logs | No decoration | Existing machine contract unchanged |

No tier may shorten the only visible brand to RT. Terminal width is measured
before rendering, including any status badge or command subtitle. Use
single-cell characters with known behavior; avoid emoji and invisible
alignment assumptions. ANSI escapes do not count toward layout width.

### Existing CLI compatibility

Doctor without --json is the human checkup; doctor --json is intentionally
JSON and must remain so. Some other current commands, including leagues,
Trade refresh, and Waiver refresh, print JSON even without a --json option.
The implementation must inventory these machine-first surfaces before adding
art. Proposed behavior: an unflagged interactive TTY gets the human card;
redirected/piped output keeps its existing plain machine value; an explicit
--json always gets the existing one-value contract. Add --json to machine-first
commands that lack it. Explicit --help may gain a small masthead only in a
TTY; redirected help remains ordinary argparse text.

Human uncalibrated failures currently emit a JSON line on stderr. A TTY human
failure may gain a readable status panel, but redirected legacy stderr and
explicit --json failures must retain their machine shape. Document and test
these deliberate interactive-only compatibility changes in
docs/CLI_OUTPUT_CONTRACT.md before shipping; do not silently break a script.

## 3. When the identity appears

| Command surface | Interactive presentation |
| --- | --- |
| Bare launch and guided help | Full hero wordmark and a concise next-command menu |
| Doctor | Full hero once, immediately followed by "Doctor" and "offline / read-only" |
| Leagues, snapshot, refresh, diagnose, evaluate, gaps, search, simulate | Full-name command masthead once at the start; wide terminals may use the bordered text variant |
| Command-specific --help | Small full-name masthead when interactive; ordinary plain help when redirected |
| Human failure | Compact full-name/command header on stderr, status, reason, safe next action |
| --no-banner | Suppress decorative wordmark/borders, retain semantic command headings and status |

Long commands render the masthead once, then restrained progress and the final
report. Do not reprint art after every provider call, progress tick, search
candidate, or check. Avoid random taglines and animation in diagnostic and
decision reports; they make screenshots harder to compare and can trivialize
uncertainty. Optional playful copy belongs only in welcome/help and never
replaces a factual result.

## 4. Doctor: a checkup, not a JSON dump

The current audit_setup report remains the source of truth. The human view
should transform its existing checks and track summaries into a deterministic
health board. A synthetic two-league sketch:

    ROSTER THEORY  /  DOCTOR
    ╭─ OFFLINE CHECKUP ───────────────────────────────────────────────────╮
    │  Config READY    Owner READY    Provider calls 0    Sleeper writes 0 │
    ╰──────────────────────────────────────────────────────────────────────╯

    LEAGUE                 DRAFT                 TRADE                WAIVER
    league_alpha           data READY            data READY           data READY
                           decision UNCALIBRATED decision UNCALIBRATED decision UNAVAILABLE (inputs)
    league_beta            data READY            data READY           data READY
                           decision UNCALIBRATED decision UNCALIBRATED decision UNAVAILABLE (inputs)

    NEXT ON THE BOARD
    1  league_alpha / Waiver: build and inspect fresh league-scoped inputs.
    2  league_alpha / Trade: add this league's approved decision policy.
    3  league_beta  / Waiver: build and inspect fresh league-scoped inputs.

    FINDINGS BY TRACK
    Setup   2 ready checks
    Draft   UNCALIBRATED draft_preferences — no league-specific policy.
            Next: set this league's draft_preferences path.
    Trade   UNCALIBRATED trade_decision — no league-specific policy.
            Next: set this league's trade_decision path.
    Waiver  READY waiver_decision; READY waiver_wire.
            UNAVAILABLE waiver_inputs — no fresh bundle selected.

    Local readiness is not proof of live freshness or league calibration.

This is a presentation example, not a sample audit result. The renderer must
display the exact underlying status words: ready, missing, invalid,
unavailable, and uncalibrated. A friendly phrase such as "needs inputs" may
explain unavailable, but must not replace or reclassify it. Data-only and
decision readiness remain separate for each track and league.

Default view prioritizes: global blockers, the league/track matrix, next
actions for every non-ready finding, then grouped findings. It may summarize
ready checks only if it states how many are summarized and provides a
--details mode showing every original check, reason, and next_action. No
non-ready check may be hidden. --details affects only the human view; JSON
keeps its current report shape. The action list is derived deterministically
from existing next_action fields, ordered first by setup/identity blockers,
then selected league/track, then required policies and inputs. Never invent a
fix, run it automatically, or suggest transferring another league's policy.

For a selected league, keep the single-league version spacious; for multiple
leagues, align rows only when width permits and fall back to stacked cards.
Numeric/private league IDs, credentials, and private filesystem paths are
never inserted into the masthead or summary.

## 5. Human decision and refresh reports

Every human report starts with a full-name command masthead, then a compact
"decision card" using the current ReportFrame facts:

1. League and exact horizon, with scoring/provenance where applicable.
2. Readiness and outcome in a high-contrast status panel.
3. The three to five facts that actually explain the result.
4. Warnings, blockers, and limitations before long evidence details.
5. A safe next action only when the existing result supports one.
6. Saved evidence paths last, with no duplicate notices.

Example layout, using synthetic data and an illustrative no-action result:

    ROSTER THEORY  /  WAIVER SEARCH                         WEEK 2
    ╭─ RESULT ────────────────────────────────────────────────────────────╮
    │  NO ACTION   ·   Evidence incomplete                               │
    │  League-scored utility; weekly horizon; no claim submitted.         │
    ╰──────────────────────────────────────────────────────────────────────╯
    WHY IT STOPPED
      UNAVAILABLE  One roster projection was not supplied.
      PARTIAL      Eleven provider players remain unmatched.
    NEXT
      Refresh the missing projection, then rebuild the input bundle.
    EVIDENCE
      Saved search: [path]

The card is not a new decision engine. Detail adapters must use authoritative
result fields, not infer a recommendation from presentation text. A valid
"no action" with complete evidence is visibly different from an incomplete
search that cannot recommend. Partial coverage, conflicting ranks, protected
drops, spike-only upside, and wrong-horizon rankings remain prominent.

Draft, Trade, and Waiver each get their own detail adapter. Shared rendering
may own only feature-neutral layout, status, provenance, evidence, and risk
tokens. It cannot translate one product's decision gates into another's.

Interactive human errors get the same grammar: command, exact
readiness/failure status, reason, and existing safe remediation. Keep the
legacy redirected human stderr payload and explicit --json failure payload
machine-safe until a separately documented compatibility decision. Preserve
exit codes and the underlying error facts.

## 6. Implementation seams and invariants

- src/roster_theory/terminal.py owns terminal capabilities, full-name art
  variants, borders, width calculations, ANSI/ASCII fallbacks, and --no-banner.
- src/roster_theory/reporting.py owns feature-neutral mastheads, status cards,
  wrapping, warning/limitation ordering, and evidence notices.
- src/roster_theory/doctor.py keeps audit_setup data unchanged and gains a
  separate grouped human renderer.
- src/roster_theory/cli.py chooses human versus machine presentation once per
  command and labels Doctor and other common commands before output.
- Product-specific human detail adapters remain in their respective Draft,
  Trade, and Waiver modules.

Explicit and redirected machine JSON remain one valid value on stdout. CSV,
evidence files, hashes,
and saved replay are byte-for-byte unaffected by presentation. No new
production dependency is needed. Rendering is deterministic for a given
report and terminal capability set. Redirection, NO_COLOR, narrow Windows
consoles, Unicode-disabled consoles, and screen readers retain readable
text-only paths.

Golden tests should cover hero and masthead variants, Doctor with two
synthetic leagues, every status and track boundary, no-banner, redirected
stdout, --json, human failures, narrow widths, long reasons/paths, and
Windows/Linux capability detection. Integration tests should compare the
underlying report data, decision labels, evidence hashes, provider call plans,
and Sleeper write count before and after visual changes.

## 7. External reference and deliberate differences

OpenClaw's official CLI documentation describes terminal-only styling with a
distinct palette and JSON output that suppresses decoration; its Doctor
documentation distinguishes guided diagnosis from advisory JSON and repair.
Those are useful presentation boundaries, not art to copy:

- https://docs.openclaw.ai/cli
- https://docs.openclaw.ai/cli/doctor/running

Roster Theory keeps its existing offline, read-only Doctor. It will not adopt
OpenClaw's repair posture, configuration writes, mascot, or lobster palette.
