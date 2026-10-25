# Variants: openspec:spec-conformance

Built from six copies (2026-10-19). Kartoteka and Clean are one text; Mind
adds the rules check; Sight and ALIX swap the e2e item for data files and
the trace; Glyph is a short rewrite with a wording check. Model stays
Sonnet, with `openspec-verify-change` preloaded (all six).

## What came from where

| Rule | From | Why |
|---|---|---|
| 1 Verify with CRITICAL/WARNING/SUGGESTION | all | |
| 2 A test counts only if it could fail, and not with a pasted value | Kartoteka, Clean, Mind | stricter than Sight, ALIX, Glyph |
| 2 A snapshot counts when it shows the THEN | Sight | makes the rule usable for snapshot tests |
| 3 End-to-end entries black-box | Kartoteka, Clean, Mind | |
| 3 Smoke entries (`smoke "<command>"`) run as their own process | ALIX (plan and spec-review rules) | `openspec:plan` asks for smoke entries; nothing checked them |
| 4 Stored shapes: version, older data restored, documented, tested | Clean 5, Mind 5, Sight 4 | merged; Sight adds "documented" |
| 5 Words on screen match the locked wording character for character | Glyph 3, Clean ui-reviewer 9 | product-work rule: locked words are quoted exactly |
| 6 One test file at most | all | the command is in `CLAUDE.md`, not bound |
| 7 `kit spec-check` | all but Glyph | Glyph had no spec-check; it gains one |

## Dropped

- Named test globs (`*.test.ts(x)`, `e2e/`, `test/`, `tests/`) and
  commands (`bun run test`, `cargo test`, `mix test`): moved to additions.
- ALIX's trace item and Mind's `Rules` item: project-bound, in additions.

## Weak points

- Item 6 tells the agent to find the single-file command in `CLAUDE.md`;
  a binding (`gate.test_one`) would be firmer. Not added: every project's
  addition names it, and the agent may skip running tests.

## Project additions (`migration/<project>/kit/spec-conformance.md`)

Kartoteka (globs, card data), Clean (globs), Mind (rules numbers, black-box
form, `PROFILE_VERSION`, `Rules`), Sight (`cargo`, data files), ALIX
(`mix`, trace, failure names), Glyph (Tolk and app tests, `bin/check`).
