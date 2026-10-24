# Variants: product:ui-reviewer

Built from three copies (2026-10-19): `kartoteka-`, `clean-` and
`carry-ui-reviewer` (Mind). Kartoteka's is a copy of an older Clean text
with stale Clean lines left in it ("D16, D17", "a long file name … an empty
library"); Clean's adds the look-diff coverage list and `e2e/layout.ts`;
Mind's is the latest, with the measure, the locked sketch, second-pass
reruns and colour meaning. Model Opus; tools Read, Grep, Glob, Bash.

## What came from where

| Part | From | Why |
|---|---|---|
| Never print the environment, no tracing, never list processes | Clean | strictest; the others lack it |
| Run skill read from the worktree, not the main checkout | Clean, Kartoteka | the branch may change it |
| 1 Screens, states, words, longest values written down first | Mind 1, Clean 1 | |
| 1 "The claim alone never skips you"; `different.txt` | Mind, Clean | |
| 1 Second pass reruns the first pass's scripts | Mind | later improvement |
| 2 Build into the scratchpad, never serve the worktree's output, check the port is closed | Mind | |
| 3 Two engines, two themes, every width; reach states by roles | all; Kartoteka for "by what a person does" | |
| 4 Measure: `cut`, `off`, `sideways`, `overlap`, `scrolls`, `moved` | Mind (`measure.mjs`, now `plugins/product/scripts/measure.mjs`) | the only copy that measures overlap and jumps; Clean's `e2e/layout.ts` stays in its addition |
| 5 Contact sheets, read every sheet, `index.html` | all | |
| 6 Compare with the locked sketch, every difference | Mind 6 | later improvement, matches `openspec:plan` |
| 6 Departure from a reference app without a reason is a question | Kartoteka 5 | |
| Look for 4: real controls, 44 px, focus visible | Clean, Kartoteka | Mind lacks it |
| Look for 6: each colour keeps its meaning | Mind 4 | generalised from red/yellow |
| Look for 8: no letter for a word | Mind 6 | |
| Look for 11: words character for character | Clean 9 | |
| Reply: DEFECT/TASTE, A beside B made in the served page | all | |

## Dropped, and why

- `skills:` preload (`<prefix>-run`, `<prefix>-product`): a shared agent
  cannot name a project skill. The run skill comes from
  `kit get product.run_skill`; the product skill is named in additions.
- The fixed build and serve commands (`bun run build`, `bun run preview`):
  now bindings `product.build` and `product.serve`.
- Fixed widths (320/340/390 or 340/390): now `product.widths`.
- Mind's 130-line `measure` inline in the agent text: moved to a plugin
  file, so it is not re-read on every request.

## Weak points

- `kit path product/scripts/measure.mjs` does not exist yet in `kit`; the
  core plugin must add it (or another way to reach a plugin file), or the
  measure is unreachable.
- Kartoteka's look review today shoots only phone widths, though its
  `CLAUDE.md` says the look check covers the computer layout from 1024 px.
  Its `product.widths` should add 1024; that makes its reviews longer.
- Kartoteka gains the 44 px and colour checks it had, and the sketch,
  measure and second-pass rules it lacked: its first reviews will find more.

## New bindings

| Key | Kartoteka | Clean | Mind |
|---|---|---|---|
| `product.build` | `bun run build --outDir {out} --emptyOutDir` | same | same |
| `product.serve` | `bun run preview --port {port} --strictPort --outDir {out}` | same | same |
| `product.widths` | `[320, 340, 390, 1024]` | `[320, 340, 390]` | `[340, 390]` |

## Project additions (`migration/<project>/kit/ui-reviewer.md`)

Kartoteka (desktop layout, card states, legal text readable, Russian
typography, reference apps), Clean (`e2e/layout.ts`, the screen catalogue,
the look-diff coverage list, Finder-only states, `mockup-2.html`, 1100 px,
design rules, words), Mind (web-build file list, screens, every stage and
guide, sizes, states and how to reach them, colours red and yellow, longest
values, game terms, sketches by script).
