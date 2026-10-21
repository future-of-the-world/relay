# Variants: sdd:code-reviewer

Built from six copies (2026-10-19). Kartoteka, Clean, Mind, Sight and ALIX
are the same text but for the names of the other reviewers and the build
tool; Glyph is a shortened form. Model Opus, tools with `Skill`.

## What came from where

- The whole body: Kartoteka/Clean (`/code-review high`, never `--fix`,
  `--comment`, `--post` or `ultra`, no Agent tool, CONFIRMED/PLAUSIBLE).
- "The coordinator's context is the budget; the fixers read the file":
  Mind, Sight, ALIX.
- "Never call the network": Kartoteka, Clean, ALIX, Glyph (stricter than
  Mind's "run nothing in the main checkout"; both kept).
- The range base comes from `kit get project.default_branch` instead of a
  hard-coded `master`.

## Dropped

- The names of the sibling reviewers in item 4 ("the product rules, the
  scenario coverage and the look"): now "the project's promise, the
  scenario coverage and the look", which covers ALIX's and Glyph's safety
  reviewers through their additions.

## Weak points

- None found beyond the copies' own: the agent depends on the `code-review`
  skill's recipe, which changes with Claude Code releases.

## Project additions (`migration/<project>/kit/code-reviewer.md`)

ALIX (no `mix`, no venue tests or Jev calls; its safety reviewer), Glyph
(its funds reviewer). Kartoteka, Clean, Mind and Sight need none.
