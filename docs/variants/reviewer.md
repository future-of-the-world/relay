# Variants: sdd:reviewer

Built from four copies of the correctness reviewer (Kartoteka, Clean, Mind,
Sight, 2026-10-19), and the generic rules of two project-only reviewers
(`alix-safety-reviewer`, `glyph-funds-reviewer`), which stay with their
projects. This role is the most project-bound of all: in every copy most
checks guard that product's own promise. The shared agent keeps the frame
and the checks that hold in any product; the promise and its checks are the
addition, which is injected into the agent when it starts.

## What came from where

| Rule | From |
|---|---|
| Frame, second pass last, CONFIRMED/PLAUSIBLE, HIGH/MEDIUM/LOW | Clean, Mind (Mind adds "the second pass is the last") |
| 1 The promise is HIGH unless the spec records the owner's decision | Clean 1 |
| 2 Layers and time: no clock, storage, random or screen in logic | Clean 4, Mind 2, Kartoteka 4 |
| 3 Input is untrusted: garbage, hand-edited, older data, storage failing | Clean 5, Mind 6, Kartoteka 5 |
| 3 Paths stay in their root; escaping; no code from input | Sight 4 |
| 4 Failures have a way out; no panic on fallible input; errors name input and cause | Clean 3, Sight 3 |
| 5 Bounds, checked reads, swallowed errors, constants, debt without id | ALIX safety 11, Glyph funds 3 |
| 6 Deterministic output and replay | Sight 2, Mind 2 |
| 7 Only what the design grants (network, permissions, writes) | Clean 6, Mind 7, Kartoteka 6, Sight 8 |
| 8 What a person sees: plain words, no internal terms, a number that disagrees with the logic, 340 px, safe areas, keyboard and touch, roles, tokens | Clean 7, Mind 8, Kartoteka 7 |
| 9 Tests honest; each guard has a test that fails without it | Clean 8, Mind 9, ALIX safety 10 |
| 10 Secrets | Sight 8, ALIX safety 8, Glyph funds 7 |

## Dropped, and why

- Hard-coded `master` in the diff command: `kit get project.default_branch`.
- "The narrowest width is 340 px": the shared text says "the narrowest width
  the project supports"; additions state it.

## Weak points

- Item 5 (from ALIX) is new for Clean, Kartoteka, Mind and Sight: in a
  browser app "a time left to a library's default" will catch Playwright or
  fetch defaults that were fine before. Expect noise in the first reviews;
  triage can mark such findings LOW.
- The shared checks are generic enough that a project without an addition
  gets a weak review: its promise is only what `CLAUDE.md` "Principles"
  says. Every migrating project with a reviewer today has an addition
  drafted; a new project must write one.
- ALIX and Glyph use their own safety/funds reviewers instead of this role.
  Whether they should also run `sdd:reviewer` is open (it would add the
  generic checks 2–9 at the cost of one more Opus review per gate).

## Project additions (`migration/<project>/kit/reviewer.md`)

Kartoteka (honesty and the law: ПСК, bank texts, nothing invented, ad
marks, static build), Clean (owner chooses, one writer, media faults,
Tauri, design rules), Mind (method, reproducible, time, `rules.ts`, the
contract, `restoreProfile`, Tauri), Sight (refs, determinism, failures,
boundaries, tree-sitter, data shapes).
