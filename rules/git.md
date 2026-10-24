# Git
> One worktree and branch per task; the primary checkout stays on its default branch and clean; no bare stash; merge when ready, ask only when it needs my judgement.

- Work in a git worktree per task, on its own branch, and keep the primary
  checkout on its default branch and clean. Use the project's worktree tooling
  when it has one (ALIX: `bin/wt`; arsenal and linter: `.worktrees/` via their
  issue skills); otherwise `git worktree add .worktrees/<task> -b <branch>`.
- Never use bare `git stash` / `git stash pop`: the stash is shared by all
  worktrees. Set work aside with a WIP commit instead.
- A ready change is merged into the default branch without asking me; the
  front reports it in one line. It is ready when the check says `open 0`, the
  gate is green on the head, the branch has taken the default branch, and the
  paid run is green when the change edited agent, skill, role or rule texts.
  Ask me before the merge only when taking the default branch hit a conflict a
  fixer resolved by hand; a finding is open as Design, question, Disputed or
  Gap, or I have not answered a question about the change; the change is
  person-facing; the paid run is red or was not run for the day's cap; or I
  said to hold it. When I say "hold", wait for my word on that change.
  After a merge into the default branch its worktree and branch are removed
  (the core plugin does it where the project has `.relay/`; `relay doctor`
  lists any left over). Nothing lives only in a task worktree: commit it, or
  keep it in the session scratchpad; ignored files there go with it. Before
  its merge a task branch takes the default branch by a merge commit, never a
  rebase (a rebase loses the check). `relay queue` lands a queue item on the
  default branch at once, and its code refuses when anything but that one file
  under `.relay/queue/` would change.

