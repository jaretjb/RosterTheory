# TX-001 — Terminal visual primitives and output boundaries

Completed September 16, 2026 (America/Los_Angeles).

The terminal layer now has deterministic wide, standard, compact, and narrow
width tiers; an amber/cream/bronze palette; readable status colors; exact-width
sideline rules; visible-width handling; and Unicode-to-ASCII fallback. Color
and artwork are limited to safe interactive output. Redirected, JSON, CSV,
evidence, and log output remain undecorated, while `--no-banner` preserves
semantic command labels.

Focused capability and output-contract tests pass as part of the complete
527-test suite. No provider behavior, recommendation logic, evidence format,
or Sleeper state changed.
