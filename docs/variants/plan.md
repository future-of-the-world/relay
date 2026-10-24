# Variants: plan (`openspec:plan`)

Copies read (2026-10-19): `kartoteka-plan`, `clean-plan`, `carry-plan` (Mind),
`sight-plan`, `alix-plan`, `glyph-plan`. Kartoteka and Clean are the same text
with project names and research lists swapped; Mind and Sight add the typed
agents rule and the one-line author prompt; ALIX adds the "first time right"
rules; Glyph is the short lead version.

## Taken, and from where

| Rule | From | Why |
|---|---|---|
| Worktree before the first artifact; explore writes nothing | all | identical |
| Repo first via `Explore` with `file:line`, sweeps on Sonnet, network last, facts into `docs/` | all | identical in substance |
| Every role to a typed agent, never fork or `general-purpose` | Mind, Sight, ALIX | stricter; matches the global agents rule |
| Author brief file + one-line prompt, hand-back at ~60 tool calls, never resume idle | Mind, Sight, ALIX | later copies; Kartoteka/Clean had the looser "prompt ends in Brief:" |
| Leading apps before shaping | Kartoteka, Glyph (CLAUDE.md "Product surface") | owner's product-work rule; generalised to every `[product]` project |
| Settle in the person's terms, timeline, owner decides feel/scope/departures | Kartoteka, Clean, Mind | union of the three lists |
| Sketch shows longest/shortest values, every theme, narrowest width, every state; A beside B; saved in `openspec/changes/<change>/sketch/` | Mind | the latest improvement; the look review needs it to compare against. Now reaches Kartoteka and Clean |
| Purpose in one line and a size budget | ALIX, Glyph | cheap, stops plan bloat |
| Concrete scenarios, worked values in design.md | Kartoteka, Clean, Mind | |
| No scenario looser than its design section | ALIX | measured: half of ~380 kept review findings were clauses no test asserted |
| Failure-state table before tasks | ALIX, Glyph; Kartoteka "data misbehaving", Clean "media misbehaves" | the same idea in four copies; the table is the strictest form |
| "Never/only/first" sentences name their test | ALIX, Glyph | |
| `Interfaces` section | all but Glyph | |
| Task fields, 4-source-file size, `module` ref rule, line-range refs for frozen records | Kartoteka/Clean/Mind/Sight/ALIX | Kartoteka's line-range rule generalised |
| End-to-end entry for an entry point (screen, command) | Kartoteka/Mind (e2e), Sight/ALIX (smoke) | one rule; the syntax is `kit packet`'s |
| Level of a scenario in `Tests:`, wave-0 fakes for every failure, parity list, caller sweep | ALIX | measured on add-backtest/outbox-sqlite; generic to any stack |
| Build one brief for the largest task and read it | all but Glyph | |

## Dropped or changed

- **"Main session on Opus is the planner"** (leadless copies) vs **"the lead
  plans and carries on to apply"** (ALIX, Glyph): now read from
  `coordination.mode`.
- **"Apply starts in a fresh session after `/clear`"**: softened to "may start
  in a fresh session". The global rules now forbid asking the owner to
  `/clear` for budget; a phase boundary is still a fine place for a fresh
  session.
- **Research document lists, skills tables, domain network rules** (bank
  pages, tube-ex, Tauri measuring, mental-math sources, crates.io, Bybit
  probes, TON): project-bound, moved to each project's `kit/plan.md`.
- **Mind's sketch specifics** (notebook and chalkboard themes, 340 vs 390 px,
  the longest stage name, `divide-remainder` overlay script, ESLint/Prettier
  skipping `sketch/`): the generic rule is shared; the specifics stay in
  Mind's addition.
- **ALIX's `docs/principles.md` bounds rule and `rules.proposal` pre-flight**:
  ALIX's addition.

## Weak points

- The sketch-in-the-change rule now binds Kartoteka and Clean, which never
  had it. Cost: each must make its linters skip `openspec/**/sketch/**` (Mind
  did) and each plan for a screen grows by the sketch files. Gain: the look
  review gets a locked reference instead of "the approved page".
- The failure-state table reaches small UI changes. "Adds no failure state:
  one line" keeps the cost low, but an author may write the line too easily.
- `project.stack_skills` covers the stack skills; area skills (product, run,
  tree-sitter, jev) stay in additions, so the shared skill has no table.

## Project additions

Drafted as `migration/<project>/kit/plan.md` for: alix, clean, glyph, kartoteka, mind, sight.
