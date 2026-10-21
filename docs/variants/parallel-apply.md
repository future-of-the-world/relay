# Variants: parallel-apply (`sdd:parallel-apply`)

Copies read (2026-10-19): `kartoteka-parallel-apply`, `clean-parallel-apply`
(the same text), `carry-parallel-apply` (Mind), `sight-parallel-apply`,
`alix-parallel-apply`, `glyph-apply` (Glyph's short version).

## Taken, and from where

| Rule | From | Why |
|---|---|---|
| Coordinator reads ids and one-line states, writes only merges and ticks, ticks with `perl` | Mind, Sight, ALIX (Kartoteka/Clean shorter) | identical in substance |
| Typed agents only, brief files, never resume idle | Mind, Sight, ALIX | Kartoteka/Clean had it only for the Opus worker case |
| Wave plan by an author on Sonnet | global model rule; Mind/ALIX "wave plans run on Sonnet" | Mind's and ALIX's own step 2 still said Opus; the global rule (measured) settles it |
| Wave 0 / middle / last wave, stubs that fail loudly, a shared file splits waves | all | stack words (JSDoc, `todo!()`, `@spec`) generalised |
| Wave 0 and last wave as a chain of workers in the change worktree | Mind, Sight, ALIX | Kartoteka/Clean: one worker that also ran `ci`; the chain keeps workers on `check` |
| Registration files in wave 0 | Sight (`lib.rs`/`mod.rs`) | generic |
| Green base before workers | all | |
| **One worker per group, one long context** | Mind, ALIX, Glyph, global agents rule | Sight still had "one task, one worker"; the global rule (measured: 1,069 workers, 81% of a day's cost) is later and wins |
| At most 4 workers at once | Kartoteka, Clean, Mind, Sight, ALIX | stricter than the global 6 and Glyph's 6; four full builds already slow the machine (Sight) |
| No checks in the prompt; process rules live in the agent | Mind, Sight, ALIX | |
| BUDGET SPENT / BLOCKED handling, skipped tests with a `blocked:` note, a fixer un-skips | all | skip syntax is the stack's |
| Wave check: full `ci` per wave when local; scoped check when the gate is remote | Kartoteka/Clean/Mind/Sight vs ALIX/Glyph | now the binding `gate.final` |
| Long runs detached, waited in ≤240 s calls | Sight, ALIX | Mind ran `bin/ci` in the foreground because it takes 2 min; the rule covers both |
| Flake rule, max(20, ⌈3/p⌉), each run under 4 min | all; "under 4 min" from Mind | |
| Spec gap before the next wave; breaking a layer or principle is a gap | all; the layer/principle clause from Kartoteka/Clean | |
| Diagnostics missing become tasks; owed work too | all; `Owed:` from Glyph | |
| Sequential when ≤4 tasks or one module; feel settled first with the run skill | all; feel from Kartoteka/Clean/Mind | |

## Dropped or changed

- **Skill model Opus → Sonnet** (Glyph already Sonnet). The global rule names
  "applying" a Sonnet job, and the coordinator only dispatches. Weak point:
  in a leadless session that planned on Opus, the switch makes the next
  request re-write the whole context on Sonnet's cache. Starting apply in a
  fresh session (as `sdd:plan` suggests) avoids it; if parity runs show
  worse dispatch decisions, go back to Opus.
- **"Stop after two waves and suggest `/clear`"** (Kartoteka/Clean/Mind/Sight):
  dropped. The global context rule (2026-10-15 onward) says update the
  handover file and carry on, never ask for `/clear`.
- **Glyph's author writes one brief per group** with design text copied in:
  replaced by `kit packet <change> <group>`. Glyph has no `bin/packet` today;
  it gains one, but its `tasks.md` must carry the `Reads:` fields for it.
- **Kartoteka/Clean: wave-0 and last-wave worker runs `ci` itself**: dropped
  (the coordinator's wave check covers it; the global rule says workers loop
  on the quiet check).
- **Project specifics** (file names that edit together, deps commands,
  `--deps-from`, `ALIX_CHECK_TIMEOUT`, network/Bybit/Jev tasks from the lead,
  remote flake measuring, `bin/board` at handover, Glyph's 6-agent cap):
  additions.
- Prompt changed from "Implement task <id>" to "Implement group <group> ...
  Report: <path>". The `sdd:worker` agent must accept a group id (it is the
  `kit packet` unit) and the report path.

## Project additions

Drafted as `migration/<project>/kit/parallel-apply.md` for: alix, clean, glyph, kartoteka, mind, sight.
