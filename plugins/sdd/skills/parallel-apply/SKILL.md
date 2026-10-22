---
name: parallel-apply
description: Apply stage of an OpenSpec change, and the coordinator's playbook. Use together with openspec-apply-change whenever /opsx:apply runs, or the user says to implement, apply or continue a change. Covers planning waves, one fresh sdd:worker per group of tasks in a ready worktree from a kit packet brief, merging a wave and its check, when to apply in sequence instead, and ending every apply with the sdd:apply-review gate.
argument-hint: "<change>"
---

# Parallel apply

The project's rules for this stage arrive with this skill; they add to it and
win where they differ.

Below, `wt`, `check` and `ci` are the commands `kit get gate.wt`,
`kit get gate.check` and `kit get gate.ci` name; `<base>` is
`kit get project.default_branch`; `<worktrees>` is `kit get project.worktrees`;
`<final>` is `kit get --default local gate.final` (`local`: the full gate runs on this
machine; `remote`: it runs once, on the project's pipeline, at the end).

The **coordinator** (the main session, or the lead) owns the change, the
merges into the change branch, and the final gate. It works in the change
worktree `<worktrees>/<change>` on `wt/<change>` (`wt new <change> <base>` if
missing). Workers work in worktrees branched from `wt/<change>`. The main
checkout is never touched, and the coordinator never merges into `<base>`
unless the project's rules grant it.

OpenSpec is the shared knowledge, but a worker never reads it whole:
`kit packet <change> <task|group>` cuts its brief (the tasks, their
scenarios, and only what `Reads:` names).

## The coordinator's context

Load `openspec-apply-orchestrator` first. The coordinator lives longest, so it
only dispatches, merges and ticks:

- It **reads** ids and one-line states: `grep -n 'Wave ' <tasks.md>`,
  `openspec instructions apply --change <change> --json | jq -c '{state, progress}'`,
  `git log --oneline`, `git status --short`, and hand-backs. Never
  `design.md`, spec deltas, code, or `openspec show`; a question goes to an
  `Explore` agent that answers in at most 5 lines.
- It **writes** only merges and ticks. It ticks without opening the file:
  `perl -pi -e 's/^(\s*)- \[ \] 2\.1 /$1- [x] 2.1 /' <tasks.md>`.
- It **runs** the wave's check (section 3) and the final gate's start, each
  cut to `2>&1 | tail -15`; the full log stays in `kit get gate.ci_log` for
  whoever fixes it. A run that may pass 4 minutes starts detached with a log
  and is waited on in calls of at most 240 seconds.
- Every hand-back is at most 10 lines (the `sdd:worker` reply); detail goes
  to `<scratchpad>/reports/<task>.md`, opened (`head -40`) only when the
  hand-back is not `DONE`.
- **Typed agents only**: `sdd:worker` for a group of tasks, `sdd:fixer` for a
  group of findings or a red check, `sdd:author` for artifacts and the wave
  plan, `Explore` for a question (with `model: "haiku"` to read a pipeline or
  an API result and answer in one line). No fork, no `general-purpose` agent. What an
  agent needs beyond the artifacts goes in a brief file
  (`<scratchpad>/briefs/<name>.md`); the prompt passes its path.
- **Models.** This skill never switches the session's own model. Workers,
  fixers, the wave plan and any build continuation run on Sonnet. A worker or fixer gets `model: "opus"` only after a Sonnet agent
  failed the same task or group, or where the project's rules name the
  case. A task that needs judgment the artifacts lack is a gap in the
  artifacts, not a reason for a larger model.
- **Never resume an agent idle over 5 minutes**: start a fresh one from a
  brief file and the old report.

## 1. Plan the waves (before any code)

1. If the groups already have `Wave N · depends on:` lines, use them and go
   to step 5.
2. Otherwise one `sdd:author` (`model: "sonnet"`) derives them. Its brief
   (`<scratchpad>/briefs/<change>-waves.md`) names the change, the worktree,
   this section as the job, and any owner decision of this session:
   - **Wave 0** (a chain of workers): dependency manifests and lockfiles,
     config, shared types, registration files every module adds itself to,
     and **stubs of everything later waves call**, with full signatures, doc
     comments, and bodies that fail loudly ("not implemented"). The stubs are
     the contract that lets later waves run in parallel; they pass the type
     check and the lint.
   - **Middle waves**: groups on disjoint files. Pure modules and a component
     with its own test nearly always parallelise. A file two groups edit (a
     stylesheet, an engine module) puts them in different waves or one task.
     At most 4 groups per wave.
   - **Last wave** (a chain of workers): wiring, the end-to-end tests, docs,
     CLAUDE.md.
3. No two groups in a wave edit the same file (tasks of one group may).
4. `kit spec-check <change>` passes before code is written (it runs
   `kit packet --check`: fields, refs, size, end-to-end entries,
   `Interfaces`). A plan written before this format gets the fields now, from
   the same author.
5. Show the owner the wave plan in 5–10 lines, then start.

Wave 0 and the last wave run as a chain of `sdd:worker` agents in the change
worktree itself, one after another, each fresh from the previous commit:
their tasks edit shared files.

## 2. Run a wave

**Start from a green base.** Every merged wave ends with its check passing
(section 3); wave 0 and the last wave, which run in the change worktree, end
with the same check run there once their chain is done (section 3, step 2).
Never start workers from a commit with a known type error, warning, lint
finding or failing test: each would rediscover it and be unable to fix it.

**One worker, one group brief, one long context.** The group is the unit:
one brief (`kit packet <change> <group>`), one worker, its tasks in order,
working continuously. A fresh worker re-pays its first read, so fewer,
longer workers are the cheap shape; a worker with nothing to do hands back at
once. At most 4 workers run at once. An agent hands back when done or after
about 60 tool calls with "remaining" in its report; a fresh agent of the same
type continues in the same worktree (`... Remaining: <report path>`).

```sh
wt new <change>-<group> wt/<change>     # a ready worktree from the change branch
```

Pass the base explicitly. Spawn every ready worker in one message. The prompt
is one line; the agent knows its loop, process rules and reply:

> Implement group <group> of change <change> in `<abs worktree path>`. Report: `<scratchpad>/reports/<group>.md`.

Add no checks to the prompt (the full suite, `ci`): the worker stops at
`check`, the coordinator runs the wave's check, and four full builds at once
slow the machine until timing tests flake. A decision a worker needs goes
into the artifacts, not the prompt. While workers run, the coordinator merges
the finished ones; it doesn't review code, write stubs or docs.

## 3. Merge a wave

1. For each finished worker: `git -C <change worktree> merge --no-ff
   wt/<change>-<group>`, then `wt rm <change>-<group>`. **BUDGET SPENT** or an
   incomplete `Reads:` is not merged: fix the stub, spec or fields, then a
   fresh worker. **BLOCKED** has committed what passes, the blocked
   scenarios' tests skipped with a `blocked:` note: merge it, don't tick the
   task, and start an `sdd:fixer` on the blocker with the worker's report as
   evidence and the skipped tests as its check (un-skipping them is the fix).
2. Record the wave base before the first merge. After the whole wave is
   merged (for wave 0 and the last wave: after the chain of workers), run
   the wave's check once in the change worktree:
   - `<final>` is `local`: `ci 2>&1 | tail -15`, the wave's only full run;
   - `<final>` is `remote`: the scoped check the project's rules name (a
     compile and the test files the wave changed since the wave base); no
     full gate runs on this machine during apply.

   A failure outside every worker's files shows here first; that is
   expected. It goes to one `sdd:fixer` in the change worktree with the log
   path; it fixes, commits, and the coordinator reruns the check. The next
   wave starts only on green.
3. **Flaky tests are unacceptable.** A worker's `FLAKY` line, or a failure
   that passes on a rerun, is not green: start a fix at once in its own
   worktree (`wt new fix-flake-<test> <base>`, an `sdd:fixer`: reproduce under
   load, measure the failure rate p, wait on a condition instead of a longer
   timeout, prove max(20, ⌈3/p⌉) clean runs under the same load, each call under
   4 minutes; its reply carries p and the clean-run count, and a fix without
   them is not merged). Fix it in the change worktree instead when the next
   wave would hit it. List it in every report until merged.
4. Tick the wave's tasks and commit on `wt/<change>`.
5. **Spec gaps first.** A gap a worker reported is fixed by an `sdd:author`
   (through `/opsx:update` and its sweep, from a brief with the gap line and
   the decision) before the next wave. A value that crosses tasks and that
   `Interfaces` didn't pin is such a gap; so is a task that could be done
   only by breaking a layer or a principle (a principle changes only with the
   owner's decision).
6. **Diagnostics missing and owed work.** Each question a worker answered
   with prints, and anything it reports as owed, becomes a task when it
   concerns code the change adds or touches (a state field, an event, a
   sharper error); otherwise a queue item. The author adding
   the tasks gets the list in its brief.

## Handing over

State lives in `tasks.md` and on `wt/<change>`. At the budget the global rules
name (or after about 150 tool calls), bring `docs/handover.md` up to date and
carry on; a lead at its budget writes its handover and replies `BUDGET`.
Stop only for the owner's decisions.

## 4. Quality gate (once, after the last wave)

Run `sdd:apply-review` on the change. Don't report the apply as done before
its report.

## Apply in sequence when

- The change has 4 tasks or fewer, or every task edits one module: one chain
  of workers in the change worktree, not in this session.
- The interface isn't settled: settle the stubs first.
- It is about feel (motion, sound, the look of a screen) the owner must see:
  one worker builds it, show it with `kit get product.run_skill`, settle it.

A sequential apply still ends with section 4.
