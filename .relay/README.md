# .relay/

This folder turns on relay's hard rules in this repository (relay's design: docs/plans/review-gate.md).
It exists on the default branch, so every worktree sees it. It is created only by `relay setup`
(or `relay setup --relay-folder`), and committed.

- `queue/` the work queue: one JSON file per item, `fix` (something wrong, with its failing case) or
  `feature`, fix before feature, then by important points. `relay queue` lists it; `relay queue -h` shows the commands.
- `checks/` the gate logs, reviews, checks and check marks of task branches. A merge into the
  default branch is refused until the branch's last commit has its gate, its review and its check.
  Only merges made through relay (`relay land`, the merge hook) are refused; a pull request squash-merged
  on the server is not gated, and its `checks/` files then name commits of the deleted branch.

Not here: `~/.relay` is per machine (ledger, bench results) and is never committed.
