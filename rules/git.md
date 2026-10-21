# Git
> One worktree and branch per task; the primary checkout stays on its default branch and clean; no bare stash; merge only when asked.

- Work in a git worktree per task, on its own branch, and keep the primary
  checkout on its default branch and clean. Use the project's worktree tooling
  when it has one (ALIX: `bin/wt`; arsenal and linter: `.worktrees/` via their
  issue skills); otherwise `git worktree add .worktrees/<task> -b <branch>`.
- Never use bare `git stash` / `git stash pop`: the stash is shared by all
  worktrees. Set work aside with a WIP commit instead.
- Merge into the default branch only when I ask for that specific merge.

