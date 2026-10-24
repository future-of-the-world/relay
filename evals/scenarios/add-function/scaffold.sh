#!/usr/bin/env bash
# The fixture as a linked worktree on wt/bench, its primary checkout beside it ($PWD.main): the
# front's guard keeps agents out of a primary checkout, so a workspace that is one would send the
# worker's files to a worktree the graders never read.
set -euo pipefail
main="$PWD.main"
mkdir "$main" && cp -a . "$main"/
git -C "$main" init -q -b master && git -C "$main" add -A && git -C "$main" -c user.name=f -c user.email=f@x commit -qm fixture
find . -mindepth 1 -delete
git -C "$main" worktree add -q -b wt/bench "$PWD"
