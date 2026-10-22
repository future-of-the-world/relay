# Git
> One worktree and branch per task; the primary checkout stays on its default branch and clean; no bare stash; merge only when asked.

- Work in a git worktree per task, on its own branch, and keep the primary
  checkout on its default branch and clean. Use the project's worktree tooling
  when it has one (ALIX: `bin/wt`; arsenal and linter: `.worktrees/` via their
  issue skills); otherwise `git worktree add .worktrees/<task> -b <branch>`.
- Never use bare `git stash` / `git stash pop`: the stash is shared by all
  worktrees. Set work aside with a WIP commit instead.
- Merge into the default branch only when I ask for that specific merge.
  After a merge into the default branch its worktree and branch are removed
  (the core plugin does it where the project has `.relay/`; `relay doctor`
  lists any left over). Nothing lives only in a task worktree: commit it, or
  keep it in the session scratchpad; ignored files there go with it. Before
  its merge a task branch takes the default branch by a merge commit, never a
  rebase (a rebase loses the check). One merge needs no word from me: `relay
  queue` lands a queue item on the default branch at once, and its code
  refuses when anything but that one file under `.relay/queue/` would
  change.

