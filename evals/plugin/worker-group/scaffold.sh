#!/usr/bin/env bash
# The fixture plus the change worktree a coordinator would have made.
set -euo pipefail
"$(dirname "$0")/../setup-fixture.sh"
bin/wt new add-low-stock master >/dev/null
# The unchanged base commit (the stub), for the case's step 3: `git worktree add`
# cannot be run inside the eval sandbox (it cannot create .claude/commands there).
git worktree add -q --detach .worktrees/base master
