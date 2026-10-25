# Variants: archive (`openspec:archive`)

Copies read (2026-10-19): `kartoteka-archive`, `clean-archive`,
`carry-archive` (Mind), `sight-archive`, `alix-archive`, `glyph-archive`. The
copies are near identical apart from the pre-archive gate and the docs list.

## Taken, and from where

| Rule | From | Why |
|---|---|---|
| Archive in the change worktree; archive and code land in one merge | all | |
| Pre-gate: apply-review with no open high finding, all tasks ticked, validate, spec-check | all | |
| Pre-gate: the `Look:` line clean (no defect, no taste waiting; "not run" has a reason, "skipped" a count) | Mind | now for every project with `look_review = true` |
| Pre-gate: full gate passed; local → `ci` here; remote → pipeline on the pushed branch, not rerun | local copies; ALIX, Glyph | `gate.final` |
| Sync now; MODIFIED replaces the whole block | all | |
| Scenario count check; a new capability counts 0 | all; the "0" note from Kartoteka/Clean | |
| Docs sweep: CLAUDE.md, README, product skills/docs, area index pages, handover, `git grep` for retired terms, frozen record never edited | union of all | |
| Remote: archive needs no new pipeline; run the tests that read docs; anything else reruns the gate | ALIX, Glyph | |
| Sonnet; the coordinator or one Sonnet agent; an agent never merges | ALIX, Glyph, Mind (model) | |
| Never merge; the owner (or the lead where granted) does | all | |

## Dropped or changed

- **Project docs lists** (Kartoteka principles/sources, Clean and Mind
  `docs/tauri.md`, Mind's game skills and "Known difference" list, Sight
  roadmap and self-map, ALIX docs index pages, Glyph `docs/dev.md`):
  additions.
- **Lead merges** (ALIX: the lead merges a gated branch; Glyph: `merge
  --ff-only`, push master, `bin/wt prune`): additions, since the global rule
  is "merge only when the owner asks"; a project's rules may grant it.
- **ALIX `Check: promised`** decision records: ALIX's addition.

## Project additions

Drafted as `migration/<project>/kit/archive.md` for: alix, clean, glyph, kartoteka, mind, sight.
