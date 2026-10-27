#!/usr/bin/env bash
# Bash hook for the allowed merge (`git merge --ff-only wt/<name>`): the merge gate before it
# (PreToolUse) and the cleanup of the merged task's worktree and branch after it (PostToolUse).
# Reads the hook JSON on stdin and exits 0 at once unless it mentions `merge`: no python runs
# on other Bash calls. The work is in merge.py.
input="$(cat)"
case "$input" in
  *merge*) ;;
  *) exit 0 ;;
esac
here="$(cd "$(dirname "$0")" && pwd -P)"
command -v python3 >/dev/null 2>&1 || exit 0
printf '%s' "$input" | python3 -I "$here/merge.py"
