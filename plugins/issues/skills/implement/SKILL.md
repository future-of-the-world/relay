---
name: implement
description: Carry an accepted issue to a merged change - read the issue, check it against reality, implement in its worktree from a brief, self-review, gate, commit with the tracker reference, open the PR, merge on the owner's word, rebase the other worktrees. Use when the owner names an issue to work on (#123, a slug), says to implement, continue or finish one.
argument-hint: "<slug | #number>"
---

# Implement an issue

Bindings: `project.default_branch`, `project.worktrees`, `gate.wt`,
`gate.check`, `gate.ci`, `gate.ci_log`, `issues.view` (`{n}`),
`issues.commit_ref` (`#{n}`), `issues.attribution`.

## 1. Read, then check against reality

A `delegate:scout` reads `.issues/<slug>/description.md` and
`decisions.md` (on the branch: `git show origin/<slug>:...`), the
dependencies' state, and the tracker issue, and replies with: the problem
in two lines, the acceptance criteria as a list (or the spec file they
point at), the files named, the decisions (settled: never re-litigated,
a deviation is raised to the owner), the open questions.

Then the **reality review** (Arsenal's first-class gate): a second scout
question, or the same scout, checks every claim in the issue against the
repository as it is now: the files exist, the lines say what the issue
says, the dependencies are merged, nothing the issue assumes has changed
since it was written. A claim that no longer holds stops here and goes to
the owner with the two options (amend the issue on its branch; or drop it).

## 2. Worktree

`.worktrees/<slug>` on branch `<slug>` normally exists (created with the
issue). If it does: the preflight: uncommitted changes or a stash entry of
that branch are a finding for the owner before anything else, never
silently bundled. If it does not: `wt new <slug> <default_branch>`. If the
default branch moved since the branch was cut: `git fetch` and `git rebase
origin/<default_branch>` in the worktree first (a runner).

## 3. Build

One brief (`delegate` skill template): the problem, the acceptance
criteria as `Done when`, the files, `gate.check` as the check, the
decisions verbatim as settled, the open questions as "not decided: ask".
One `delegate:worker`:

> Implement the brief. Brief: `<path>`. Report: `<scratchpad>/reports/<slug>.md`.

`BLOCKED` means the brief or the issue is wrong, not the model: fix the
brief, or amend the issue on its branch with the owner, then a fresh
worker. The same brief failing twice on Sonnet may go once to Opus with
`Escalated: <what failed>`.

## 4. Self-review and gate

`delegate:critic` over `origin/<default_branch>...<slug>` against the
acceptance criteria and the project's rules; `delegate:fixer` on blockers
and majors; the critic again over the fix range. Then a `delegate:runner`
runs `gate.ci` in the worktree (detached when it may pass 4 minutes); a
red gate goes to a fixer with the log path; the second red comes to the
owner. Minors left: listed in the PR body, not fixed now.

## 5. Commit and push

Conventional message (`feat:`, `fix:`, `chore:` ...) with the body saying
what changed and why; the footer `Closes: <commit_ref>` on the **final**
commit only (an early `Closes:` closes the issue while work is in flight).
Attribution per `issues.attribution`. `git push`.

Then `issues:merge`.

## What the owner hears

Two or three sentences per step that matters: the issue in their terms,
what the reality check found, that the build is running, what the review
found that matters, that the gate is green and the PR is open. Questions
only for a decision that is theirs: an issue that no longer holds, a
deviation from a recorded decision, the merge.
