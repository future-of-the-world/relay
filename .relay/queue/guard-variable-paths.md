---
kind: fix
state: open
ip: 91
size: 15
found: 2026-10-22, relay review-gate design 10.6 seed 6
taken-by:
closed-by:
test:
---
# guard variable paths

Where: plugins/core/hooks/guard-main.sh:39
What is wrong: guard variable paths
Failing case: from the main checkout `git -C $G branch -d x` (a worktree in `$G`) is refused: the guard takes an unquoted `$NAME/...` word as a path under the current folder (`guard-main.sh:39-41`); the same mechanism refuses writes to `$TMPDIR/...` and `mkdir -p $S` (handover "guard-main reads -C $VAR as a literal path", "guard and $TMPDIR", earlier note at handover:144; the `$TMPDIR` case is the coordinator's shorthand, confirmed by the taker)
Why it matters: Safe commands are refused for no reason, and a worker is stopped in the middle of its job.
