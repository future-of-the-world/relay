---
name: spec-review
description: Review and fix an OpenSpec change's planning artifacts before apply. Use after /opsx:propose (openspec:plan calls it), when the user asks to review a spec, proposal or plan, and together with openspec-update-change whenever /opsx:update revises a change. Runs openspec:spec-reviewer, fixes findings through one openspec:author with the full sweep, one check of the fixes, and asks the owner only for real decisions.
argument-hint: "<change>"
---

# Spec review and fix

The project's rules for this stage arrive with this skill; they add to it and
win where they differ.

The coordinator (the main session) only dispatches. The review
runs in **`openspec:spec-reviewer`** (Opus, read-only), which starts fresh and
reads only the artifacts, as a worker will: what it can't understand from
them, a worker won't either. Fixes are written by an **`openspec:author`**. Each
pass and each fix is a fresh typed agent; never resume one idle over 5
minutes. Work in `<worktrees>/<change>` (`kit get project.worktrees`) on
`wt/<change>`.

## 1. Review

Record the review base (`git -C <path> rev-parse HEAD`). Spawn the reviewer
with one line:

> Review change <change> in `<abs change worktree path>`. Report: `<scratchpad>/review/spec-1.json`.

Don't edit the artifacts while it runs. It replies with the counts, one line
per blocker, the questions for the owner, and the report path.

## 2. Questions first

The reviewer's **Questions for the owner** are the owner's. Sort them first:
a plan that contradicts itself is a fix for the author, not a question. Ask
the rest as numbered questions with lettered options, your recommendation
first, the difference made visible. A question about what a person sees is
shown, not described: a picture of the screen as specified beside the other
way (`openspec:plan` section 3). Don't pick a scope cut, a change of feel, a busier
screen, or a departure from a principle or the approved look yourself. Work
that does not depend on an answer carries on.

## 3. Triage and fix, in one author

The coordinator doesn't read the report or the artifacts. Write
`<scratchpad>/briefs/<change>-spec-fix.md`: the report path, the owner's
answers word for word, and this section as the job. One `openspec:author`
(`subagent_type: "openspec:author"`) gets one line:

> Fix the spec review findings of change <change> in `<abs change worktree path>`. Brief: `<brief path>`. Report: `<scratchpad>/review/spec-fix.md`.

It takes this one report, writes its own reply to the `Report:` path (the checker's `Fixes:` reads that file), hands back when done or after about 60 tool calls
(a fresh author continues from the brief and its "remaining" line), and:

- reads each finding against the artifacts and keeps the ones that hold;
- fixes **BLOCKER** and **FIX**; fixes a one-line **NIT**, else lists it;
- writes each answer into `design.md` (or where it belongs), marked as the
  owner's with the date;
- sweeps every place an old wording lives: proposal, design, tasks, all spec
  deltas, and docs the change wrote outside `openspec/changes/`;
  `git grep -n '<old term>'` returns nothing for every renamed term;
- passes `openspec validate <change> --strict` and `kit spec-check <change>`;
- commits `Spec review fixes: <what changed>` and replies in at most 10
  lines: fixed / dropped / listed, one line per blocker and its fix, where
  each answer was written, check results, sha.

It is an `openspec-update-change` pass: it never edits code.

## 4. Check of the fixes

The method is the judge base that every reviewer carries (relay's copy: `~/relay/roles/judge.md`).

Whenever fix commits exist (any BLOCKER or FIX was fixed), `delegate:checker`
runs once over `<review base>..HEAD`; it reads the artifacts (artifact cases
are checked by reading):

> Check: `<scratchpad>/review/spec-1.json`. Fixes: `<scratchpad>/review/spec-fix.md`. Worktree: `<abs change worktree path>`. Gate: none (artifacts only). Report: `<scratchpad>/review/spec-check.md`.

No author fixes what it finds and there is no new open review, even when the
fixes changed a core rule. The spec check writes no verdict (it is not a
merge). Every finding it leaves open goes to the owner with a recommendation
(the reviewer's smallest fix now, a queue item, or a drop, and why); read
`<scratchpad>/review/spec-check.md` (a plain text report: an artifacts-only check records no JSON, so
`relay check show` does not read it) for that list. A further fix runs only on the owner's word
and is checked the same way.

## 5. Report

```
Spec review: <N> findings (<B> blockers), <fixed / open>.
- <each blocker: what apply would have built wrong, and the fix>
Questions answered: <decision -> where it was written>.
Open after the check: <each finding and the recommendation; "none">.
openspec validate --strict: passed. spec-check: passed.
Branch: wt/<change>, ready for /opsx:apply.
```
