# Variants: `sdd:worker`

Built 2026-10-19 from the six copies of the worker agent:
`kartoteka-worker` (10.8 KB), `clean-worker` (11.3 KB), `carry-worker`
(Mind, 10.7 KB), `sight-worker` (9.9 KB), `alix-worker` (16.3 KB),
`glyph-worker` (3.0 KB). Shared file: `plugins/sdd/agents/worker.md`
(8.8 KB). Kartoteka and Clean are the same text with project names and
paths changed; Mind and Sight share their skeleton; ALIX adds the proof
steps; Glyph is a short rewrite of the ALIX version for a lead-run project.

## What came from where

| Part | Source | Note |
|---|---|---|
| Skeleton (brief, tests then code, check budget, long commands, diagnosing, blocker, commit gate, rules, reply) | Kartoteka = Clean | the common version |
| Brief to a file, read with Read in parts | Kartoteka, Clean | later than Mind/Sight/ALIX, which print the packet to stdout; a 60 KB brief reaches the agent cut short |
| `Brief: <file>` in the prompt as an alternative to the packet | Glyph | Glyph's author writes group briefs; kept so Glyph can migrate before its tasks carry packet fields |
| Test rules: wait on a condition, no wall-clock window, the test owns its state, deterministic output, missing signal | Sight, ALIX (general form), Kartoteka (expected values by hand) | Sight's and ALIX's rules are stated generally; Kartoteka's are tied to its helpers |
| e2e / smoke line as one black-box rule | Kartoteka (e2e), Sight and ALIX (smoke) | merged: "through the real outside", in-process does not count |
| Wait on own pid, never a machine-wide name | Sight, ALIX | ALIX records such loops outliving their worker by hours |
| Prove each test by disabling its behaviour | ALIX, Glyph | stricter, later (ALIX, measured 12–13 Oct: half of ~380 review findings were scenario clauses no test asserted) |
| Clause ledger, `Owed:` | ALIX, Glyph | as above |
| Diff scan for defect classes | ALIX (grep), Glyph (list) | shared text lists the classes; ALIX's Elixir grep moves to its addition |
| Second path gets the first path's guards; callers of a changed function | ALIX | moved out of the worker: the plan carries it as the parity list and the caller sweep (`sdd:plan`), so the shared worker has no such line |
| Code rules: bounds from config, caps, broken invariant raises, outside data checked | ALIX (`docs/principles.md` 2–5, 8), Sight, Glyph | the stricter rule; Kartoteka/Clean/Mind had it only in parts |
| No content/no button the brief does not list | Kartoteka, Clean | generalised to "person-facing task" (the global product-work rule) |
| Never read secret files (`.env*`, keys, mnemonics) | Glyph | stricter, general |
| Don't push, don't start a pipeline | ALIX fixer, Glyph | now also for workers |
| Reply with `Proof:`, `clauses n of m`, `Callers not updated:`, `Tests that name it:` | ALIX | kept |

## Conflicts and how they were settled

- **When a worker runs the full gate.** Kartoteka/Clean: when the prompt
  says so (wave 0, last wave), detached. Mind: same, in the foreground (it
  takes 2 min). Sight: same, detached. ALIX: never on this machine. Shared:
  only when the prompt says so; foreground or detached follows the general
  4-minute rule. ALIX's ban and Mind's timing are in their additions.
- **Group or task.** Sight's copy is one task per worker (older); the rest
  run a group in one context (later, cheaper per the cost rules). Shared:
  group.
- **Proof steps for every project.** ALIX measured their value; no other
  project did. Kept for all because the cost (one disabled-and-rerun per
  new test, one grep) is small next to a review round. See "Weak points".

## Dropped

- Every project path, env var, helper name, skill name, and test framework
  marker (moved to additions below).
- "Measured on" notes in the agent text (kept here).
- The coverage/lint rule is kept in a general form ("don't lower a coverage
  threshold or silence a lint without a comment"); TypeScript's `!`/`any`
  specifics moved to additions.

## What each project keeps as `.claude/kit/worker.md`

Drafts: `migration/<project>/kit/worker.md`, injected when `sdd:worker` starts.
A fixer gets only `kit/fixer.md`, so a project repeats there the code and test
rules a fix needs.

- **Kartoteka**: `kartoteka-product`; test helpers (`createTestServices`,
  `TEST_CARDS`), no clock in `src/data`; Playwright e2e in two engines;
  long commands and `KARTOTEKA_CHECK_TIMEOUT`; dev port 1420; `console.log`
  grep and `it.skip` marker; layers; the "content the owner did not choose"
  rule (it reads like Clean's principle copied in; the owner may drop it);
  `!`/`any`/`eslint-disable`; `bun run test`; files never touched;
  `docs/prototype/`.
- **Clean**: as Kartoteka with `clean-product`, `tauri`, layers
  `src/core`/`src/kinds`, Tauri files, and the `probe/` (Kotlin, Swift)
  rule.
- **Mind**: `carry-method`/`carry-game`/`tauri`; `fakeSkill`, seeded
  `createRng`, worked examples per method; e2e that plays the game;
  `bin/ci` in the foreground; `rules.ts`; no special-casing one skill.
- **Sight**: `tree-sitter`; `docs/testing.md`; Rust test layout and insta;
  `assert_cmd` smoke; `dbg!`/`tracing`; `#[ignore]`; no `unwrap` on
  fallible input; `cargo metadata`.
- **ALIX**: no Bybit Demo or Jev calls; Fake and emulator; ExUnit waits and
  10 s `assert_receive`; `System.cmd` smoke; credo, `erl -eval` halt; no
  full runs on this machine; the Elixir diff-scan grep; parity and caller
  greps; `Alix.Diag`/`Alix.Trace`; capital safety and demo/mainnet words.
- **Glyph**: the stack line and `docs/dev.md`; Acton and `bun test`; its
  `bin/check` flags until it meets the check contract; funds-specific diff
  classes.

## Bindings and contracts relied on

- `kit get gate.check`, `gate.ci`, `gate.ci_log` (its folder holds the
  brief and long logs), `project.stack_skills`, `product.run_skill` (fixer).
- `kit packet <change> <task|group>`.
- The **check contract**, which five of six projects' `bin/check` meet and
  Glyph's does not: `check <change> <task> [--failed]`,
  `check --tests <files> [--failed]`, prints only failures, counts failed
  rounds and prints `BUDGET SPENT` on the third, kills a hung `Check:`
  (`HUNG`), prints `TIME BUDGET SPENT` at 40 minutes.

## Weak points

- The proof steps add work to every task in every project (about 2–4 tool
  calls per new test, plus a grep); their saving is measured only on ALIX's
  Elixir code. If Kartoteka's parity cases show workers hitting the
  60-call wrap line more often, move steps 3–5 to an addition for the
  projects that measured them.
- After the fix round the shared file is 8.8 KB (Kartoteka's copy was 10.8 KB,
  Glyph's 3.0 KB): only what every project needs; the rest moved to additions
  (1.5–3.5 KB, injected once at the agent's start).
- Glyph cannot use this agent until its `bin/check` meets the contract; its
  addition works around it by self-counted rounds, which is weaker.
