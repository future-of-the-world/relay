#!/usr/bin/env bash
# Scaffold of every case: copies evals/fixture into the run's working
# directory as a git repo on master with one commit. Inside `claude plugin eval`
# the loaded plugin's bin/ is NOT on the agents' PATH and /usr/bin/git cannot run
# (sandbox), so bin/ci puts core's bin/ and a git shim (.ci/evalbin) first on PATH.
#
# A case that needs a worktree makes it after this, the way a coordinator does:
# `bin/wt new <change> master` (its scaffold.sh), because the shared agents work
# only in a worktree and the guard hook blocks writes in the main checkout.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd -P)"
cp -R "$here/fixture/." .
git init -q -b master .
git add -A
git -c user.name=fixture -c user.email=fixture@example.invalid commit -qm "fixture"
