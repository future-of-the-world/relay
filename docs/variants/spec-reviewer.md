# Variants: sdd:spec-reviewer

Built from six copies (2026-10-19): `kartoteka-`, `clean-`, `carry-` (Mind),
`sight-`, `alix-` and `glyph-spec-reviewer`. Kartoteka, Clean and Mind are
one text with project checks swapped in; Sight and ALIX share its frame with
weaker scenario rules; Glyph is a short rewrite.

## What came from where

| Rule in the shared agent | From | Why this one |
|---|---|---|
| Frame: inputs, second pass is the last, `Remaining:` hand-back, reply format | Clean = Kartoteka = Mind | all six agree; Glyph's is a shortened form |
| 1 Coherence, incl. "no contradiction with `CLAUDE.md`" | Clean | Sight and ALIX omit `CLAUDE.md` |
| 2 Requirements: worked values, redo two or three scenarios | Clean, Mind | stricter than Sight, ALIX, Glyph ("a THEN no test could fail on" only) |
| 2 "No scenario looser than the design section it cites" | ALIX "First time right" | measured: half of ~380 kept findings were scenario clauses no test asserted |
| 3 Failure scenarios (missing, corrupt, older, slow, unavailable) | Clean 3, Kartoteka 3, Sight 3, ALIX 3, Glyph 3 | merged to the generic cases; each project's named cases stay in its addition |
| 4 Failure-state table, never/only/first sentences, parity list, caller sweep | ALIX 13, Glyph 8 | later measurement (outbox-sqlite: 7 of 12 high findings came from the design's silence); `sdd:plan` now asks for the table |
| 5 Principles: departure needs the owner's written decision | Clean 4, Kartoteka 4 | |
| 5 Bounds, checked reads, visible causes, deferred work with id/owner/deadline | ALIX 12 | the strictest; Glyph 4 has the same bound rule |
| 6 Settings, not constants; how the default was chosen | Mind 5, ALIX 4, Sight 5, Glyph 4 | four of six had it; Mind's "what a person would notice" is the strongest form |
| 7 What a person sees, BLOCKER for a busier screen | Clean 5, Kartoteka 5 | |
| 7 Quotes the locked words exactly; no internal terms | Glyph 6 | matches the product-work rule ("quoted exactly by the specs") |
| 7 Locked sketch saved in `sketch/` | Mind 4 | later improvement; `sdd:plan` now saves it |
| 8 Time, chance, order; deterministic written output | Clean 6, Mind 6, Kartoteka 6, Sight 6 | merged |
| 9 Layers, and modules that exist (BLOCKER) | Clean 7, Kartoteka 7 | |
| 10 Terms | all | |
| 11 Design observable without a debug print; unverified platform fact is a FIX | Clean 9, Kartoteka 9, Sight 8, ALIX 8 | generalised: "where the project keeps such facts" |
| 12 Waves: new settings and failure fakes in wave 0; outside-service tasks marked for the coordinator | Mind 10, ALIX 9, ALIX 13 | |
| 13 Briefs; `Tests:` gives the level; smoke entry for code run outside the test process | Clean 11, ALIX 10, ALIX 13, Sight 10 | merged the e2e, CLI and mix-task forms |
| 14 Interfaces incl. sort keys | Clean 12, ALIX 11, Sight 11 | |

## Dropped, and why

- "Questions for the user" became "Questions for the owner": the owner
  decides; ALIX's and Glyph's "user/operator" wording is kept by Glyph's
  addition only.
- "The last wave holds the full `bin/ci`": ALIX runs the gate remotely and
  forbids it on a worker; the shared text names no gate in the last wave, and
  each addition says where its gate runs.
- ALIX's `skills: [alix-jev]` preload: a shared agent cannot name a project
  skill; ALIX's addition tells it to load the skill (the addition is injected at its start).
- ALIX's opening sentence about add-strategy-engine (history).

## Weak points

- Stricter for Kartoteka, Clean and Sight than today: the failure-state
  table, bounds and settings rules will add findings to plans that passed
  before. That is the intent, but the first migrated plans will cost an
  extra fix round. The parity cases should show it.
- Item 7 (sketch saved in the change) relies on `sdd:plan` saving it; a
  project that shapes in another medium (Glyph: a Telegram Mini App) needs
  its own picture convention or the check is a recurring FIX.
- At 14 checks the agent is longer than any copy but ALIX's; nothing was cut
  that a project measured.

## Project additions (drafts in `migration/<project>/kit/spec-reviewer.md`)

- **Kartoteka**: the two prototypes, the law (ПСК, bank texts), offline,
  promotion clock, `src/data`/`src/ui`, card/offer, `docs/sources.md`.
- **Clean**: `docs/tauri.md`, clean-probe, media that misbehaves, the
  owner-chooses principle, design rules, viewer state machine, layers,
  viewer/reader terms, wiring files.
- **Mind**: rules.ts arithmetic, prototype notes, `Rules`, `Rng`, the skill
  contract, `RunView`/`RunEffect`, wiring files, "the player".
- **Sight**: no `cargo`, parse failure cases, real names not metaphors,
  `schema_version`, refs at a sha, crate layout, `tracing`, cost on a large
  repo, `todo!()`, CLI smoke tests.
- **ALIX**: the Jev skill, docs, order/funds failure names, setting naming,
  Jev, safety, OTP and `Alix.Diag`, backtest timing (rule 15), decider for
  empty cells, remote gate, coordinator tasks, primer, 4 lib files, smoke.
- **Glyph**: operator, funds failure names, fees, rights, wording, message
  layouts.
