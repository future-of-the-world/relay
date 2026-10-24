#!/usr/bin/env bash
# The fixture plus the change worktree a coordinator would have made, and the packet of group 1 in it.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd -P)"
"$here/../setup-fixture.sh"
bin/wt new add-low-stock master >/dev/null
# The brief a coordinator hands a plain delegate:worker: `kit packet` (core's tool; the sandbox PATH has no plugin bin/).
mkdir -p .worktrees/add-low-stock/.ci
(cd .worktrees/add-low-stock && "$here/../../../plugins/core/bin/kit" packet add-low-stock 1 > .ci/brief.md)
# The unchanged base commit (the stub), for the case's step 3: `git worktree add`
# cannot be run inside the eval sandbox (it cannot create .claude/commands there).
git worktree add -q --detach .worktrees/base master
