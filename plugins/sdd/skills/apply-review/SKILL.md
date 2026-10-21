---
name: apply-review
description: Quality gate and fix loop for an implemented OpenSpec change - correctness review, spec conformance, code review and, for a person-facing change, the look review in parallel, then one triage, fixes by sdd:fixer agents, one check of the fixes, the final gate, and the report. Use after the last apply wave (sdd:parallel-apply calls it), after a sequential apply, whenever /opsx:verify runs, or when the user asks to review an implemented change before merge.
argument-hint: "<change>"
---

# Apply review and fix

The project's rules for this stage arrive with this skill; they add to it and
win where they differ.

Below, `wt`, `check` and `ci` are the commands `kit get gate.wt`,
`kit get gate.check` and `kit get gate.ci` name; `<base>` is
`kit get project.default_branch`; `<worktrees>` is `kit get project.worktrees`;
`<final>` is `kit get --default local gate.final` (`local` or `remote`). The coordinator works in `<worktrees>/<change>` on
`wt/<change>`, starting from the last wave's check green there, and keeps the
context rules of `sdd:parallel-apply`: reviews, triage and fixes live in
report files under `<scratchpad>/review/` and in typed agents; it reads only
their 10-line hand-backs. Record the gate base first
(`git -C <path> rev-parse HEAD`). One review, then a check of the fixes; the method is the judge base, `roles/judge.md`.

## 1. Gate: the reviews in one message

Each is read-only and gets the change name, the worktree path, the branch
`wt/<change>`, and its report path `<scratchpad>/review/<name>.md`:

| Review | Model | Looks at |
|---|---|---|
| `sdd:reviewer` | Opus | correctness against the project's rules: what could go wrong for the person or the system |
| `sdd:spec-conformance` | Sonnet | OpenSpec verify, each `#### Scenario:` mapped to a test that asserts it, each end-to-end entry backed by a test from outside, data shapes as specified |
| `sdd:code-reviewer` | Opus | `/code-review high` on `<base>...wt/<change>`; findings to its report, counts in its reply |
| `product:ui-reviewer`, when the look review runs (below) | Opus | the look, by looking: every touched screen shot and measured, against the locked sketch |

A change that touches no code (docs, prompts, skills) may skip the
correctness review; the report says so.

**The look review** applies when `kit get --default false product.look_review` is `true`. Go by
the file list (`git -C <path> diff --stat <base>...HEAD | tail -40`) against
`kit get product.surface` (regexes; a changed path matching one can reach a screen), not by reading
code:

- **No surface file touched**: no look review; the report says "not run" and
  why.
- **Meant to alter a screen** (the proposal says so, or a screen's markup or
  styles change on purpose): it runs.
- **Surface touched, said to change nothing on screen**: the claim never
  skips it; a check does. When `kit get --default "" product.look_diff` names a command, run it
  against `<base>` before the reviews; when its first line ends in
  `0 different`, skip with `Look review: skipped, <N> shots identical to
  <base>`. Anything else, or no such binding, and it runs, its prompt naming
  where the differing shots are.

In doubt, run it. Its prompt:

> Look review of change <change> in `<abs change worktree path>`, branch `wt/<change>`. Scratchpad: `<scratchpad>/review/look/`. Report: `<scratchpad>/review/look.md`.

No other review stands in for it: a screen that passed them has not been seen.

## 2. Triage (one author)

Write `<scratchpad>/briefs/<change>-triage.md`: the report paths, the
worktree, the range `<base>...wt/<change>`, this section as the job, and any
owner decision of this session. One `sdd:author` (`model: "sonnet"`: triage
is not an Opus job) gets one line:

> Triage the review reports of change <change> in `<abs change worktree path>`. Brief: `<brief path>`.

It writes `<scratchpad>/review/triage.md`:

1. One defect reported twice is one finding; ids F1, F2, ...
2. Each finding is checked against the code: CONFIRMED kept; PLAUSIBLE traced,
   or the test that would show it described (the author never edits code). A
   look finding is checked against its screenshot and measure, and keeps its
   screenshot path.
3. A spec gap (the spec silent or wrong) is fixed in the artifacts first,
   through `sdd:spec-review` step 3, before code.
4. Confirmed findings are grouped by the files they touch, one
   `## Group <x>` with its file list; dependency manifests, lockfiles,
   `tasks.md` and the artifacts form their own group.
5. Look `DEFECT`s are grouped like any finding; each `TASTE` goes under
   `## For the owner` with its question and its A-beside-B picture.

It replies in at most 10 lines: counts (confirmed, dropped, spec gaps), one
line per high finding, the groups and files, the judgment calls. A judgment
call on what a person sees or feels (a wording, a pace, a scope cut) goes to
the owner, never decided silently. **Matters of taste** are the owner's,
every one: show the picture of the real screen, A as built beside B the
other way (an `sdd:fixer` makes it with `kit get product.run_skill` when the
look review has none), then ask A or B with what the person sees in each. A
change they want becomes a finding; one they keep is written into
`design.md` as theirs with the date. Never fix or drop one silently.

## 3. Fix

Artifact fixes go first to an `sdd:author`, manifest, lockfile and `tasks.md`
fixes to one `sdd:fixer` in the change worktree; each commits so the others
branch from it. Then one **`sdd:fixer`** (Sonnet) per group, fresh:

- **4 groups or fewer, or one module**: a chain in the change worktree, each
  committing its group.
- **More**: one per group in `wt new <change>-fix-<x> wt/<change>`, at most 4
  at once, merged back as a wave (`sdd:parallel-apply` section 3).

> Fix findings in group <x> of `<scratchpad>/review/triage.md` (change <change>) in `<abs worktree path>`. Range: `<base>...wt/<change>`. Report: `<scratchpad>/reports/fix-<x>.md`.

The fixer stops at `check` on its test files. `model: "opus"` only after a
Sonnet fixer failed the same group, or where the project's rules name the
case; a "remaining" hand-back is followed by a fresh fixer on the same group.
After the merges the coordinator runs the wave's check (`sdd:parallel-apply`
section 3, step 2).

Every fix comes with a test that fails without it, shown by disabling the fix
and watching it fail. A look defect the page can be asked about (cut text, an
overlap, a box that moves between states, sideways scroll) gets an end-to-end
test at the size and with the value that showed it; one only the eye can
judge (a colour) is proven by the check's screenshot, and the report
says so.

## 4. Close: the final gate (before the check)

`openspec validate <change> --strict` and `kit spec-check <change>`, each cut
to its tail; commit `Review fixes: <summary>`.

- **`<final>` is `local`**: in the change worktree, on the fixed head, `{ echo "head $(git -C <wt> rev-parse HEAD)"; ci; echo "exit $?"; } > <gate log> 2>&1`
  (detached and waited on in calls of at most 240 s if it may pass 4
  minutes); the check reads that log as `Gate:`. A failure goes to an
  `sdd:fixer` with the log, then the gate runs again.
- **`<final>` is `remote`**: merge `<base>` into `wt/<change>` if it moved,
  push the branch (a push is not a merge), and start the pipeline by hand as
  the project's rules say. An `Explore` agent with `model: "haiku"`, started
  when the pipeline is due (no agent waits on it), reads the result as one
  line (`pipeline #<n> on <full sha> passed`, which the check takes as `Gate:`) and, on a failure, writes the failing lines to
  `<scratchpad>/review/gate-<n>.md` for an `sdd:fixer`; then push and run again. If the pipeline cannot run, say so
  and ask the owner; a local full run is a fallback only on their word.
  The gate holds for its commit: a later commit that changes only
  `openspec/` or docs needs none (run the tests that read docs), anything
  else does.

A failure that passes on a rerun is a flaky test: the gate has not passed
until it is fixed or its fix runs in its own worktree, and the report names
it under **Flaky**.

## 5. Check of the fixes (after the final gate)

`delegate:checker` runs once on `<scratchpad>/review/triage.md` and the
fixers' reports, over `<gate base>..HEAD` (the gate base is the `Reviewed:`
sha), with the log of section 4's final gate (or its pipeline result) named as `Gate:`. The look review runs in
check mode when the fix commits touch the surface (the test of section 1 on
that range):

> Check: `<scratchpad>/review/triage.md`. Fixes: `<fixer reports>`. Worktree: `<abs change worktree path>`. Check command: `<cmd>`. Gate: `<log>`. Report: `<scratchpad>/review/check.md`.

There is no fixer after it and no new open review. The triage author keeps
each finding's failing case and pass-cases when it merges duplicates. Every
finding left open goes to the owner with a recommendation. An open HIGH or
MEDIUM inside the change is fixed before the merge: it is one more round on
the owner's word (a fix, the gate again, then the check again), never a
follow-up; only items outside the change are listed as follow-ups. A look defect still
on screen is listed with its screenshot; the look is never reported clean.

If the change alters what a person sees, the owner checks it before merge:
give the last look review's contact sheets and offer to launch the change
with `kit get product.run_skill`.

## 6. Report

It opens with the gate, since that says whether the change is safe to merge.
Build it from the hand-backs; open `triage.md` only for a line they lack.

```
Quality gate: <N> findings (<X> high), <fixed / open>. Check: <met>/<all> cases met, open <n>.
- <each high finding: what the person would have seen or lost, and the fix>
Open after the check: <each finding and the recommendation; "none">.
What changes for the person: <the new screen, moment, words or output, in one line>.
Look: <D> defects (<fixed / open>), <T> matters of taste (<kept / changed / waiting for you>); or: skipped, <N> shots identical to <base>; or: not run (<why>).
Contact sheets: <path; or none>.
Scenarios: <covered>/<total> asserted by tests. Verify: <critical> critical.
Tests: <counts>. Gate: <ci passed | pipeline #<n> on <sha> passed>. openspec validate --strict: passed.
Flaky: <each test that failed then passed, and its fix branch; "none">.
Spec gaps: <each, and where it was folded in>.
Diagnostics missing: <each, and the task or follow-up that covers it>.
Branch: wt/<change>, ready for /opsx:archive (archive first, then the merge).
```
