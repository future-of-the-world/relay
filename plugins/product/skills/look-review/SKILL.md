---
name: look-review
description: When the look review (product:ui-reviewer) runs on a change, and how it is started. Load at step 4 of the change cycle in a project with a person-facing surface.
---

# Look review

Step 4 of the change cycle names this skill when the project has a person-facing
surface. The look review is one more judge beside `delegate:critic`: it looks at
the screens, it does not read code. No other review stands in for it: a screen
that passed them has not been seen.

It applies when `kit get --default false product.look_review` is `true`. Go by the
file list (`git -C <path> diff --stat <base>...HEAD | tail -40`) against
`kit get product.surface` (regexes; a changed path matching one can reach a
screen), not by reading code:

- **No surface file touched**: no look review; the report says "not run" and why.
- **Meant to alter a screen** (the proposal or brief says so, or a screen's markup
  or styles change on purpose): it runs.
- **Surface touched, said to change nothing on screen**: the claim never skips it;
  a check does. When `kit get --default "" product.look_diff` names a command, run
  it against `<base>` before the reviews; when its first line ends in `0 different`,
  skip with `Look review: skipped, <N> shots identical to <base>`. Anything else,
  or no such binding, and it runs, its prompt naming where the differing shots are.

In doubt, run it. Start `product:ui-reviewer` in the same message as the other
judges of step 4, with this prompt:

> Look review of change <change> in `<abs change worktree path>`, branch `wt/<change>`. Scratchpad: `<scratchpad>/review/look/`. Report: `<scratchpad>/review/look.json`.
