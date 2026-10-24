# Variants: `openspec:author`

Built 2026-10-19 from the six copies of the author agent:
`kartoteka-author` (6.4 KB), `clean-author` (6.5 KB), `carry-author` (Mind,
6.5 KB), `sight-author` (6.4 KB), `alix-author` (7.0 KB), `glyph-author`
(3.2 KB). Shared file: `plugins/openspec/agents/author.md`.

## What came from where

| Part | Source | Note |
|---|---|---|
| Skeleton (brief, write, check and commit, budget, rules, reply) | Kartoteka = Clean | the common version |
| Description: never builds or continues a build; wave plans and triage on Sonnet | Mind, ALIX | later; matches the global model rule and how `openspec:plan`, `openspec:spec-review`, `openspec:parallel-apply` and `openspec:apply-review` spawn it |
| Read one skill *section*, not the whole skill | Mind, Sight, ALIX, Glyph | section numbers dropped: the brief names the heading, so the agent survives renumbering |
| Every interval, timeout, limit and tunable number is configuration with a bound and an outcome at the bound | Sight, ALIX, Glyph, Mind (`rules.ts`) | stricter, general |
| Failure-state table, absolutes tested, test level in `Tests:`, fakes first, parity list, caller sweep | ALIX ("First time right" in `alix-plan` section 4) | measured 12–13 Oct: the design's silence on a failure state gave 7 of 12 high findings of one change; the rules live in `openspec:plan` "Writing the artifacts", the author points to them (one source) |
| Person-facing wording only from quoted locked decisions | Glyph | matches the global product-work rule |
| Options given as what a person sees or what it costs | Mind ("what the player will see or feel") | general form |
| Reply note that the coordinator keeps every reply | Mind, Sight, ALIX | |
| No secret in an artifact | ALIX, Glyph | general |

## Conflicts and how they were settled

- **"owner" vs "user" vs "operator".** Shared text says "the owner"; the
  addition may name its own word.
- **Glyph's group briefs.** Glyph's author writes one brief per task group
  because Glyph has no `bin/packet`. With `kit packet` in core, the packet
  is the shared way; Glyph keeps the group-brief job in its addition until
  its tasks carry the packet fields. Writing briefs by hand costs Opus or
  Sonnet output tokens per group and drifts from the artifacts; the packet
  does not.
- **Skill paths.** Plugin skills are not under the worktree's
  `.claude/skills/`, so the agent asks `kit path <plugin:skill>` for the
  `SKILL.md` to grep. This command does not exist in core yet (proposed).

## Dropped

- Project directories in "never touch" lists (into additions); the general
  rule is "code, tests, dependency manifests or lockfiles, build config".
- Section numbers in the jobs table.

## What each project keeps as `.claude/kit/author.md`

Drafts: `migration/<project>/kit/author.md`.

- **Kartoteka**: `kartoteka-product`; failure scenarios for data the page
  reads and expired promotions; legal text never dropped, nothing to press
  added; the code folders.
- **Clean**: `clean-product`, `tauri`; failure scenarios for stored data,
  the native shell, misbehaving media; content the owner did not choose;
  nothing to press; code folders.
- **Mind**: `carry-game`, `carry-method`, `tauri`; worked numbers; tunable
  numbers in `Rules`; prototype departures, feel, numbers and scope are the
  owner's; code folders and `docs/prototype/`.
- **Sight**: `tree-sitter`; its failure scenarios (unparsable file, missing
  grammar, huge file, path outside the repo); `schema_version`; no `cargo`.
- **ALIX**: `alix-jev`, `typesafe-ai`; order/funds/API-key failure
  scenarios; `docs/principles.md`; the caller classes of its failure-state
  table and the decider for empty cells; capital safety and demo/mainnet
  words; no `mix`.
- **Glyph**: funds failure scenarios; prices, fees and limits in contract
  storage or config; operator-owned wording; the group-brief job; testnet.

## Weak points

- The failure-state table and its companions (from `openspec:plan`) now apply
  to every project's new change, including Kartoteka's static site, where
  most cells will be "cannot happen": extra Opus output per plan, with the
  saving measured only on ALIX.
- `kit path` is a new dependency on core.
