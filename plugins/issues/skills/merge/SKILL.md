---
name: merge
description: Open the pull request for an issue branch, wait for the pipeline, squash-merge on the owner's word, then prune the worktree and rebase every remaining worktree onto the moved default branch. Use when a reviewed issue branch is pushed, or when the owner says to open the PR, merge, or rebase.
argument-hint: "<slug>"
---

# Pull request and merge

Bindings: `issues.pr_create` (`{branch}` `{title}` `{body_file}`, prints
the PR number or url), `issues.pr_status` (`{pr}`, one line), `issues.pr_merge`
(`{pr}`; squash, delete the remote branch), `project.default_branch`,
`project.worktrees`, `gate.wt`, `issues.attribution`.

Every call goes through a `delegate:runner`; the main session sees one line
per step.

1. **Preflight** the worktree (uncommitted changes or a stash of this
   branch: a finding for the owner, never bundled into a push or rebase).
   Rebase onto `origin/<default_branch>` if it moved; `git push
   --force-with-lease`.
2. **Open the PR**, unless one is already open for `<slug>` →
   `<default_branch>` that still matches (head, base, `Closes:`
   reference, description): then update its body instead. Body: what
   changed in the owner's terms, the acceptance criteria met, minors
   left, the gate result, `Closes: <commit_ref>`; the `openspec validate`
   output when the change carries spec artifacts. Attribution per
   `issues.attribution`.
3. **Pipeline**: poll `issues.pr_status` in calls of at most 240 s; one
   reply with the final state. Red: a `delegate:fixer` with the log, then
   step 1 again.
4. **Merge only when the owner asks for this merge**: one line with the
   url and the gate state, then `issues.pr_merge` (squash; title
   `<type>: <description> (#<pr>)`; remote branch deleted). The issue
   file reaches the default branch with the squash; no status commit.
5. **After the merge**, one runner, in order: `git -C <main checkout>
   pull --ff-only`; `wt rm <slug>`; for **every** remaining worktree the
   preflight, then `git rebase origin/<default_branch>` (a conflict or a
   dirty worktree stops the loop and comes to the owner by name);
   `git worktree prune`; confirm the main checkout is clean on the
   default branch.

Tell the owner: merged (or waiting on them), the url once, which
worktrees were rebased, and what is next if `issues.list` is bound.
