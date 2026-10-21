---
name: create
description: Draft and create an issue (or several from a plan): .issues/<slug>/description.md committed on branch <slug> in a worktree, the tracker issue, the branch pushed; then a report. Use when the owner asks to create, draft or file an issue, or to break a plan into microtasks. Created without asking first; the report comes after (the owner's rule).
argument-hint: "<what the issue is about | a plan file>"
---

# Create an issue

Bindings (`kit get`): `project.default_branch`, `gate.wt`,
`issues.create` (a command with `{title}` and `{body_file}` printing the
tracker's issue number or url), `issues.commit_ref` (`#{n}`),
`issues.attribution`.

The owner's rule (Arsenal, D1): an issue is created without asking; it is
a record on its own branch and reaches the default branch only with the
merged pull request. A wrong issue is undone on the owner's word (close
the tracker issue, `wt rm <slug>`, delete the remote branch).

## Shape of an issue

`.issues/<slug>/description.md`: title; `**Dependencies:**` (slugs or
none); Summary (the PROBLEM first: what works today, what breaks, for
whom, why the existing mechanism cannot serve it; then the shape of the
solution and why that shape); Acceptance Criteria (testable; or one line
pointing at the change's delta spec when the flow is combined with
OpenSpec); Implementation Notes; Files to Create/Modify; References
(verified against the repository at draft time). No status field, ever.

`decisions.md` beside it, required when the owner shaped the issue in the
conversation or the agent chose a scope, a name or a policy: one entry per
decision with Choice, Rejected (and the evidence), Source (who, when); an
"Open questions" list with the "if X then Y" trigger of each.

## Who does what

1. **Draft**: one `delegate:thinker` with a brief holding the owner's words
   verbatim, the source document (a plan file) if any, and the slug rules
   (kebab-case, unique: no `.issues/<slug>` on the default branch, no
   branch `<slug>` local or remote). It writes the draft files into the
   scratchpad and replies with the slug, the summary, the decisions and
   the open questions. For a plan: one draft per unit of work that fits
   one focused session, dependencies declared, foundations first.
2. **Faithfulness check** (discussion-born issues): one `delegate:critic`
   compares the draft with the owner's words in the brief: coverage,
   every decision with its rejected alternative, nothing invented or
   attributed to the owner that they did not say, references real.
   Findings go back to a fresh thinker; the check runs again after any
   later correction.
3. **Secrets**: the critic also confirms no token, key, DSN or credential
   URL is in the draft (the tracker publishes it).
4. **Create**: one `delegate:runner` per issue: `wt new <slug>
   <default_branch>` (from `origin/<default_branch>` after a fetch),
   write the files into the worktree, `git add .issues/<slug>/ && git
   commit -m "chore: add <slug> issue description"`, run `issues.create`
   with the title and a body file (the summary, the dependency list, a
   one-paragraph decision digest), `git push -u origin <slug>`. Several
   issues: worktrees and commits first, then tracker calls in one
   message, then pushes. Attribution per `issues.attribution`.
5. **Report** to the owner, in plain words: slug and tracker number, the
   summary in a few lines, each decision with who made it, the open
   questions. A correction from the owner is applied on the branch and
   pushed (and the check in 2 runs again).

Creating an issue does not start it; that is `issues:implement`.
