# Variants: `sdd:fixer`

Built 2026-10-19 from the six copies of the fixer agent:
`kartoteka-fixer` (11.0 KB), `clean-fixer` (11.4 KB), `carry-fixer` (Mind,
11.9 KB), `sight-fixer` (10.9 KB), `alix-fixer` (14.6 KB), `glyph-fixer`
(2.0 KB). Shared file: `plugins/sdd/agents/fixer.md`.

## What came from where

| Part | Source | Note |
|---|---|---|
| Skeleton (findings, failing test then fix, check budget, commit gate, rules, reply) | Kartoteka = Clean | the common version |
| Report kinds incl. a gate-failure file and a failed check (not only `bin/ci`) | Sight, ALIX, Mind | later |
| Opus only after a Sonnet fixer failed, or where the project names the case | all; ALIX's second case moved to its addition | |
| "What the fix changes for others": tests naming a changed thing in scope, callers, diff scan, clause assertion | ALIX | measured 13 Oct: 7 of 14 red tests of a final gate came from review-fix commits; general, kept |
| Flaky: fix the wait or signal; the coordinator proves it under load | Mind, Sight, ALIX | later and stricter than Kartoteka's |
| Pictures for a look finding (A as built beside B) | Mind | general for person-facing projects; the apply-review skill already asks a fixer for it via `product.run_skill`; Mind's two themes stay in its addition |
| Fix the finding, not its neighbourhood; don't push; no pipeline | Mind, Sight, ALIX, Kartoteka | |
| Own addition holds the worker's project rules | new | an addition is injected for its own role only (`fixer.md` for `sdd:fixer`), so a project whose fixer needs the worker's code and test rules repeats those lines in `kit/fixer.md` (Kartoteka's does); nothing is read by instruction |
| Tests rules, code rules, secret files | as in `sdd:worker` | inlined, so a fixer never has to read the worker agent |

## Conflicts and how they were settled

- **Full gate.** Kartoteka/Clean/ALIX: never. Mind: when the prompt says,
  foreground (2 min). Sight: when the prompt says (fallout of a merged
  wave), detached. Shared: only when the prompt says so, under the general
  4-minute rule.
- **Glyph's short form** (no budget, no diagnostics, no blocker procedure)
  was dropped in favour of the full one: it is the older, weaker version.

## Dropped

- Project paths, timeouts, helpers, markers, file lists (into the worker
  and fixer additions).

## What each project keeps as `.claude/kit/fixer.md`

Drafts: `migration/<project>/kit/fixer.md` (a fixer gets only its own
addition, so the worker rules it needs are written there too).

- **Kartoteka, Clean, Sight**: the worker's code and test rules, repeated
  (Kartoteka's draft is the model; Clean's `probe/` gate for fixes goes here).
- **Mind**: pictures on the notebook and the chalkboard, via `carry-run`.
- **ALIX**: Opus also for a finding `alix-safety-reviewer` tagged high on
  an order path or a risk limit; `test/docs` in scope when config, a
  follow-up, or an event changed; never start a pipeline or `load` run.
- **Glyph**: a pipeline failure as a report kind; its `Check:` commands;
  commit message `Review fixes: <group>`.

## Weak points

- The worker rules a fixer needs are written twice per project (worker and
  fixer addition), and can drift apart; the cost of injecting one file per
  role instead of chaining additions.
- The pictures section is dead weight in a project with no person-facing
  surface (Sight, ALIX, Glyph's contracts): 6 lines read on every request.
