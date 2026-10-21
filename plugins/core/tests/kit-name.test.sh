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
#   plugins/core/tests/kit-name.test.sh
set -uo pipefail
found="$(command -v kit 2>/dev/null || true)"
if [ -z "$found" ]; then
  echo "ok    no other 'kit' on PATH, so the plugin's helper is the one agents call"
  echo "kit-name.test: all passed"
  exit 0
fi
echo "FAIL  '$found' is on PATH and would shadow the plugin's kit helper inside Claude's Bash tool."
echo "      Rename this plugin's helper (bin/kit and every 'kit ' call in agents, skills, docs, Bash(kit:*) permissions) or remove that program."
echo "kit-name.test: 1 failed"
exit 1
