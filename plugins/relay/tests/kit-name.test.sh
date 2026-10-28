#!/usr/bin/env bash
# The helper is called `kit`, a common command name (KitOps ships a `kit` CLI).
# Claude Code puts a plugin's bin/ on the Bash tool's PATH AFTER the user's own
# entries (verified 2026-10-19 on 2.1.303: with a fake `kit` first on PATH, the
# agent's `kit get ...` ran the fake). So another `kit` on this machine's PATH
# would silently take over every agent's `kit` call. This test fails when one
# exists, and says what to do. (A rename to a distinctive name was weighed and
# deferred: it touches every agent and skill text, every project's
# `Bash(kit:*)` permission and the migration script; this test is the
# cheap guard until a clash is real.)
#   plugins/relay/tests/kit-name.test.sh
set -uo pipefail
# Only a `kit` that is NOT this plugin's own helper counts (any checkout or install of it on PATH is fine), so the
# result does not depend on which copy of the plugin happens to be on this machine's PATH.
here="$(cd "$(dirname "$0")" && pwd -P)"
ours() { # <file>: is it a copy of this plugin's bin/kit (this checkout, another checkout or worktree of it, an install)?
  local real; real="$(cd "$(dirname "$1")" && pwd -P)/$(basename "$1")"
  # plugins/core/bin/kit is this plugin under its pre-rename folder name (a checkout from before the rename may still be on PATH).
  case "$real" in */plugins/relay/bin/kit|*/plugins/core/bin/kit) return 0 ;; esac
  cmp -s "$1" "$here/../bin/kit"
}
found=""
IFS=: read -r -a dirs <<<"$PATH"
for d in "${dirs[@]}"; do
  [ -n "$d" ] && [ -f "$d/kit" ] && [ -x "$d/kit" ] || continue
  if ! ours "$d/kit"; then found="$d/kit"; break; fi
done
if [ -z "$found" ]; then
  echo "ok    no other 'kit' on PATH, so the plugin's helper is the one agents call"
  echo "kit-name.test: all passed"
  exit 0
fi
echo "FAIL  '$found' is on PATH and would shadow the plugin's kit helper inside Claude's Bash tool."
echo "      Rename this plugin's helper (bin/kit and every 'kit ' call in agents, skills, docs, Bash(kit:*) permissions) or remove that program."
echo "kit-name.test: 1 failed"
exit 1
