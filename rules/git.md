# Git
> One worktree and branch per task; the primary checkout stays on its default branch and clean; no bare stash; where the project has `.relay/` a ready change is merged without asking, elsewhere I say when to merge.

- Work in a git worktree per task, on its own branch, and keep the primary
  checkout on its default branch and clean. Use the project's worktree tooling
  when it has one (ALIX: `bin/wt`; arsenal and linter: `.worktrees/` via their
  issue skills); otherwise `git worktree add .worktrees/<task> -b <branch>`.
- Never use bare `git stash` / `git stash pop`: the stash is shared by all
  worktrees. Set work aside with a WIP commit instead.
- Where the project has `.relay/` (relay's merge hook guards the merge), a
  ready change is merged into the default branch without asking me; the
  front reports it in one line. Elsewhere, and for merge requests on Glonass
  repositories, merge into the default branch only when I ask for that merge.
  It is ready when the check says `open 0`, the
  gate is green on the head and the branch has taken the default branch. Agent,
  skill, role and rule texts get one paid run on the default branch after a wave
  of merges (the train of checked-path changes landed after a green run), not one per change; `relay sync` waits for it, and a red run is one
  fix item at the top of the queue. While a paid run goes, lanes keep building; a change for which
  `bin/paid-cost touches <branch>` prints files waits at the landing until the run ends, then lands in
  one train after the run's `relay sync`.
  Ask me before the merge only when a fixer could not resolve a conflict from
  taking the default branch (it stopped on it); a finding is open as Design, question, Disputed or
  Gap, or I have not answered a question about the change; the change is
  person-facing; or I said to hold it. A resolved conflict still needs a green
  gate and a new check of the resolved files on the head (on a train, of every
  rider's item). When I say "hold", wait for my word on that change.
  After a merge into the default branch its worktree and branch are removed
  (the core plugin does it where the project has `.relay/`; `relay doctor`
  lists any left over). Nothing lives only in a task worktree: commit it, or
  keep it in the session scratchpad; ignored files there go with it. Before
  its merge a task branch takes the default branch by a merge commit, never a
  rebase (a rebase loses the check). Ready changes that wait together land as
  one train: a throwaway branch `wt/train-<n>` that merges them, is gated once
  and lands with one fast-forward; only one landing at a time while a train is
  open, and a red train falls back to one change at a time. `relay queue` lands a queue item on the
  default branch at once, and its code refuses when anything but that one file
  under `.relay/queue/` would change.

