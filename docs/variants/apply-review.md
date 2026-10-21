# Variants: apply-review (`sdd:apply-review`)

Copies read (2026-10-19): `kartoteka-apply-review`, `clean-apply-review`,
`carry-apply-review` (Mind, the fullest look review), `sight-apply-review`,
`alix-apply-review` (remote final gate, decider), `glyph-apply-review`
(remote gate, funds review).

## Taken, and from where

| Rule | From | Why |
|---|---|---|
| Gate base recorded first; coordinator reads only hand-backs | all | |
| Reviewers in one message: correctness, conformance, code review | all | ALIX/Glyph swap correctness for safety/funds (see additions) |
| Skip correctness for a no-code change, saying so | all | |
| Look review: three cases by file list; a claim never skips; only a pixel check skips | Mind (Clean has the same check) | strictest; owner rule 2026-10-10 "If you can verify nothing is changed, yes" |
| Kartoteka without a pixel check: look review always runs on a surface change | Kartoteka | covered by "no `product.look_diff` binding → it runs" |
| Triage in one author, CONFIRMED/PLAUSIBLE, spec gaps first, groups by files, own group for manifests | all | |
| Look findings checked against their screenshot; DEFECT vs TASTE | Mind | |
| Matters of taste shown A beside B, never in words | Mind | measured: the owner could not answer a words-only question and answered at once from the picture |
| Fix order (artifacts, manifests, then groups), chain ≤4 or worktrees ≤4 | Mind, Sight, ALIX | |
| Every fix has a test seen failing without it | all | |
| Look defect → end-to-end test when the page can be asked, else screenshot proof | Mind | |
| Second pass: correctness always, plus each reviewer whose findings were fixed, plus look when fixes touch the surface | ALIX (correctness found bugs the fixes made), Glyph (those with findings), Mind (look reshoots) | union; stricter than Kartoteka's correctness-only |
| Open findings: fix now on the owner's word, or follow-up with id, owner, deadline; ask a high one before the gate | Sight, Mind, ALIX | |
| Local close: `ci`, validate, spec-check; detached when long | all local copies; Sight for detached | |
| Remote close: merge base in, push, start by hand, Haiku reader started when due, failure file for a fixer, can't run → ask, gate holds for its commit, docs-only commits need no new gate | ALIX, Glyph | the two remote copies agree; now one shared procedure under `gate.final = "remote"` |
| Owner sees a person-facing change before merge; contact sheets; offer to launch | Mind, Kartoteka, Clean | |
| Report template | Mind (fullest) + ALIX gate line | |

## Dropped or changed

- **Triage author on Opus** (all copies) → `model: "sonnet"`. The global
  model rule says triage is never an Opus job (measured 2026-10-12). Weak
  point: triage drops false findings by reading code; if Sonnet keeps false
  positives, the fix round grows. Watch the dropped/confirmed counts in
  parity runs.
- **Reviewer "looks at" columns** (legal text, media misbehaving, seeds,
  refs, order paths): they belong to the reviewer agents and their
  `kit/reviewer.md` additions, not this skill.
- **ALIX**: `alix-safety-reviewer` in place of the correctness reviewer, its
  skip rule, Opus fixer for a high safety finding, decider for judgment
  calls and open findings, high findings never dropped, `Check: promised`
  records and sampling, Woodpecker details, doc tests: ALIX's addition.
- **Glyph**: `glyph-funds-reviewer`, its skip rule, Woodpecker details:
  Glyph's addition.
- **Mind's web-build file list** → binding `product.surface`; its look-diff
  command → binding `product.look_diff`.
- Kartoteka's "until merged, read the ui-reviewer from the worktree": a
  bootstrap note, obsolete with a plugin agent.

## Weak points

- `sdd:reviewer` is now generic; its value depends on each project's
  `kit/reviewer.md` carrying the "looks at" list the copies had in this table.
- The second pass may now run three Opus reviewers where Kartoteka ran one.
  Cost: up to 2 extra Opus passes on small fix ranges; gain: fixes reviewed
  by the reviewer that found the problem.

## Project additions

Drafted as `migration/<project>/kit/apply-review.md` for: alix, clean, glyph, kartoteka, mind, sight.
