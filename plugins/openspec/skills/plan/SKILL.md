---
name: plan
description: Research and planning stage of an OpenSpec change. Use together with openspec-explore or openspec-propose whenever /opsx:explore or /opsx:propose runs, or the user asks to research, plan, design, or propose a change. Covers the change worktree, research (repo first, cheap subagents, the network last), shaping what a person will see, the artifact rules the author follows, and handing the plan to spec review.
argument-hint: "<change>"
---

# Research and planning

The project's rules for this stage arrive with this skill; they add to it and
win where they differ.

This skill adds to `openspec-explore` and `openspec-propose`; where it says
more, it wins. Per-artifact rules come from `openspec instructions` (fed from
`openspec/config.yaml`): read what it returns, never recall it.

Below, `wt`, `check` and `ci` are the commands `kit get gate.wt`,
`kit get gate.check` and `kit get gate.ci` name; `<base>` is
`kit get project.default_branch`; `<worktrees>` is `kit get project.worktrees`.

**Who runs it.** The front plans, as step "before 1" of the change cycle: it
keeps the decisions and the conversation, not the documents. Research goes to
`delegate:scout` (the delegate skill's table says when a scout is worth it);
an `openspec:author` writes the artifacts. Every role goes to a typed agent,
never a fork or a `general-purpose` agent. The build needs nothing from this
conversation, so it may start in a fresh session (`/opsx:apply <change>`).

## 1. Worktree first

Before the first artifact: `wt new <change> <base>` makes
`<worktrees>/<change>` on `wt/<change>`. Run `openspec new change`, write and
commit there only. Explore mode writes nothing and needs no worktree until the
owner asks to capture the result as a change.

## 2. Research: repo first, subagents, the network last

1. **The repo knows most of it.** A scout reads what bears on the change in
   `openspec/specs/` (current behaviour), `docs/handover.md`, and the docs the
   project's rules list, and answers with `file:line`. Ask what exists; never
   assume a module.
2. **Broad sweeps go to a scout**: "where is X / what reads Y / which specs
   mention Z". Independent sweeps go in one message. Ask for conclusions, not
   file dumps.
3. **The network last.** A library, platform or domain fact is checked
   against the installed version and the real source before a design relies
   on it; what can only be measured (what a runtime really does) is measured
   first. A fact that settles a question goes into `docs/` with its source
   and date, so nobody looks it up twice.

Load the skills `kit get project.stack_skills` names for the stack, and those
the project's rules list for the area the change touches.

## 3. Shape what a person will see

Only when the project has a `[product]` binding and the change alters what a
person sees or does (screens, words, flows, defaults). Engineering parts are
decided under the principles, with no live example.

- **Leading apps first.** Before shaping a screen or flow, look at how two or
  three leading apps of the kind do it (CLAUDE.md, "Product surface") and
  start from the best; each sample names its reference and where ours differs
  and why.
- **Settle it in the person's terms**: which screen and which moment change,
  the exact words, and a short timeline of what happens in order, with the
  numbers worked from the code so the example is true. Never ask the owner to
  choose between module names.
- **Show, don't describe.** Each question is a sketch in the real medium
  (`kit get product.medium`), made with `kit get product.run_skill`: a small
  page in the app's own styles, or the running app changed by a script, which
  leaves everything else as built. It shows what a demo would not: the
  longest and shortest values a screen can hold, every theme, the narrowest
  width beside the usual one, and every state that differs side by side, so a
  layout that jumps shows in the sketch. An option is a picture beside today's
  screen; two options are A beside B. Wait for "lock it".
- **The locked sample is saved with the change**, by default as
  `openspec/changes/<change>/sketch/` (the project's rules may name another
  place or form, e.g. a locked page): what made the pictures and the pictures
  shown, each named by screen, size and theme, today's beside the locked one
  for an existing screen. `design.md` names each one beside its decision. The
  look review compares the build against it, so a change that alters a screen
  and has no locked sample is not ready for an author.
- The owner decides: a departure from a principle, a design rule or the
  approved prototype, a busier screen, a new control, a change of feel, a
  scope cut. Ask; don't pick.

## 4. Writing the artifacts

Write the brief first: `<scratchpad>/briefs/<change>-plan.md` holds the
settled approach, every owner decision word for word, the artifacts to write,
the locked sample files, and the exact files and sections to read (the
scout's answers, not whole documents). Then one `openspec:author`
(`subagent_type: "openspec:author"`) gets one line:

> Write the artifacts of change <change> in `<abs change worktree path>`. Brief: `<brief path>`.

It commits and replies in at most 10 lines: artifacts, group and task count,
check results, open questions, sha, what remains. It hands back when done or
after about 60 tool calls at the end of an artifact; a fresh author continues
from the same brief and the "remaining" line. Later decisions go to a new
author with a brief holding the decision and the sections it changes. Never
resume an author idle over 5 minutes. This session neither edits nor
re-reads the artifacts (once is fine when the owner wants to discuss one).

The author applies, beyond `openspec instructions`:

- **Purpose and size.** The plan states its purpose in one line and a budget
  in tasks. A plan that outgrows it is cut back (the rest becomes a named
  later change), not reviewed harder.
- **Concrete scenarios.** A THEN states values: the exact words, a number, a
  count. A worked value has its working in `design.md`, where a test comment
  can cite it. No scenario is looser than the design section it cites: it
  names the same limit ("only", "never", "re-raises").
- **Failure states, before the tasks.** `design.md` has a table: a row per
  failure state the change adds (a read that fails, data missing or expired,
  input that misbehaves, a write refused, a process that restarts), a column
  per caller or screen that can meet it, each cell the outcome with its bound
  and what the person sees and how they get out, or "cannot happen: <why>".
  An empty cell is a question for the owner now, not for a worker. A change
  that adds no failure state says so in one line.
- **Absolutes are tested.** For every "X never happens", "only X" or "X comes
  first", `design.md` names the task and the test that fails when it is false.
- **Tasks** in groups numbered in build order (the groups are built one after
  another, in `tasks.md` order), each task sized for one fresh worker (about one module and its tests, at most 4
  source files; more only as `Size: mechanical (<reason>)`). Every task ends
  with four fields that `kit packet` turns into the worker's brief (its
  header has the ref syntax):
  - `Reads:` the design sections, requirements, module contracts and doc
    sections the task needs, nothing else. A `module` ref names a file that
    exists when the plan is checked (existing code); a module an earlier
    task creates is described in `design.md`. A frozen
    record with no headings (a prototype) is named by line range, never
    whole;
  - `Tests:` the scenarios it must test, or `none (<reason>)`, with the level
    a scenario is seen at when that is not the task's own module, on the task
    that owns that test file. A task that creates or edits an entry point a
    person or another process reaches (a screen, a command) names its
    end-to-end test, run from outside as the real thing, or waives it with a
    reason;
  - `Files:` the paths it creates or edits, tests included;
  - `Check:` a focused command that runs in under about 30 s.
- **Fakes first.** The first group makes the test fakes able to script every
  failure the deltas use, named by scenario.
- **Second paths.** A task that adds a path beside an existing one carries a
  parity list: the old path's guards, locks, checks, alerts and retries by
  `file:line`, each on the new path or refused with a reason.
- **Callers.** A task that changes what a function does on failure (a return
  becomes a raise, a write may now be refused) lists its callers in `Files:`,
  or gets a caller-sweep task: one line per caller, what it does and why.
- **Decisions** the owner makes go into `design.md` as they are made, marked
  as theirs with the date. A worker sees only its packet.
- Build one brief (`kit packet <change> <task>`) for the largest task and read
  it as a worker would: if the task can't be done from it, `Reads:` is
  incomplete.
- `openspec validate <change> --strict` and `kit spec-check <change>` pass
  (it runs `kit packet --check`); commit on `wt/<change>`.

## 5. Hand over to spec review

When `openspec-propose` would stop, run `openspec:spec-review` on the change before
presenting it. The owner sees the plan with the review's result and its
questions. Reviewing and fixing the plan is still planning; code is written
only after the owner says apply.
