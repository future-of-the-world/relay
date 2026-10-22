# Variants: spec-review (`sdd:spec-review`)

Copies read (2026-10-19): `kartoteka-spec-review`, `clean-spec-review`
(identical but for names), `carry-spec-review` (Mind) and `sight-spec-review`
(identical but for wording), `alix-spec-review`, `glyph-spec-review`.

## Taken, and from where

| Rule | From | Why |
|---|---|---|
| Reviewer reads only the artifacts, as a worker will | all | |
| Typed agents only; each pass and fix a fresh agent; never resume idle | Mind, Sight, ALIX | stricter than Kartoteka/Clean |
| Record the review base before fixes | Mind, Sight, ALIX, Glyph | Kartoteka/Clean lacked it, so the second pass's range was undefined |
| Sort questions first: a self-contradiction is an author fix | ALIX | cheap, saves owner questions |
| Numbered questions, lettered options, recommendation first, person-facing questions shown not described | Glyph + global "Working with me" | Kartoteka/Mind phrased options in the person's terms; Glyph adds "shown live" |
| Work that doesn't depend on an answer carries on | Glyph, ALIX | |
| One author, one report, ~60 tool calls hand-back | Mind, Sight, ALIX | |
| The sweep (all artifacts, docs outside `openspec/changes/`, `git grep` empty, validate, spec-check, commit message) | all | identical |
| Second pass only on BLOCKER or restructure, on the fix range, last pass even if a core rule changed | Mind | strictest wording |
| Open findings: smallest fix now, a queue item (was: follow-up), or drop | ALIX, Glyph | |

## Dropped or changed

- **Fix author on Opus** (all six copies) → `model: "sonnet"`. The global
  model rule (measured 2026-10-12) puts "fixes after review" on Sonnet. Weak
  point: an artifact fix can need design judgment; if Sonnet fixes come back
  weak, the remedy is the global rule's own escape (Opus after a Sonnet
  failure), not a project-wide switch back.
- **ALIX's decider** (`alix-decide`: questions go to the decider, only
  `OPERATOR:` answers reach the operator; decision records in
  `docs/decisions/log/`; `Check: promised` must be closed before the plan is
  presented): ALIX's addition.
- **ALIX's reviewer check 12** (`docs/principles.md` bounds): ALIX's addition
  (it is the reviewer's rule, mentioned so the coordinator expects it).
- **Per-project question phrasing** ("what the screen will show", "what the
  player will feel in a run", "what the user will get"): one generic rule;
  Kartoteka's and Clean's lists of owner-only decisions kept in their
  additions where they name project things (the approved prototype).
- `bin/spec-check` → `kit spec-check`; Glyph had none and gains it.

## Project additions

Drafted as `migration/<project>/kit/spec-review.md` for: alix, clean, kartoteka, mind, sight.
