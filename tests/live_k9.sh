#!/usr/bin/env bash
# K9 (docs/plans/review-gate.md 12.3, 13.2 P-1): ONE real delegate:checker on a fixture repository, through `claude -p`
# with this worktree's plugins. PAID (about $0.50, ceiling --max-budget-usd 1.5). Not part of bin/ci; run by hand:
#   tests/live_k9.sh <output folder>
# Records in <output folder>: stop-input.json (the SubagentStop input, to see whether agent_transcript_path is there),
# stop-input.json.t (when the hook input arrived), claude.json (cost), mark.txt (what the front saw right after the
# hand-back, and the mark commit's time).
set -uo pipefail
root="$(cd "$(dirname "$0")/.." && pwd -P)"
out="$1"; mkdir -p "$out"; out="$(cd "$out" && pwd -P)"
fx="$out/fx"; rm -rf "$fx"; mkdir -p "$fx"
export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_SYSTEM=/dev/null GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@t GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@t
cd "$fx" && git init -q -b master . && printf '.ci/\n' >.gitignore && mkdir .relay && echo x >.relay/README.md && git add -A && git commit -q -m init
git worktree add -q .worktrees/t -b wt/t; wt="$fx/.worktrees/t"
printf 'def add(a, b):\n    return a + b\n' >"$wt/calc.py"; git -C "$wt" add calc.py; git -C "$wt" commit -q -m "calc"
base="$(git -C "$fx" rev-parse master)"
printf 'Reviewed: %s\n\ncalc.py:1: LOW: F1 add has no docstring\nFailing case: help(add) shows nothing.\nPass-cases: a docstring exists.\n' "$(git -C "$wt" rev-parse HEAD)" >"$out/f.md"
printf '{"hooks":{"SubagentStop":[{"hooks":[{"type":"command","command":"python3 -c \\"import sys,time;p=sys.argv[1];open(p,chr(119)).write(sys.stdin.read());open(p+chr(46)+chr(116),chr(119)).write(repr(time.time()))\\" %s"}]}]}}' "$out/stop-input.json" >"$out/settings.json"
line="Check: \`$out/f.md\`. Fixes: \`none\`. Worktree: \`$wt\`. Check command: \`python3 -c 'print(1)'\`. Gate: \`none\`. Report: \`$wt/.ci/report.md\`."
ask="Start the agent delegate:checker with exactly this prompt (one line, nothing added): $line  When it hands back, run: git -C $wt log --format='%H %ct %s' -3 ; date +%s ; and print its output unchanged."
mkdir -p "$wt/.ci"; mkdir -p "$wt/.ci"   # the checker's report goes inside the session folder, where a headless run may write
cd "$wt" && claude -p "$ask" --plugin-dir "$root/plugins/relay" --plugin-dir "$root/plugins/delegate" --settings "$out/settings.json" \
  --permission-mode acceptEdits --allowedTools Agent Bash Read Write Grep Glob --max-budget-usd 1.5 --output-format json >"$out/claude.json" 2>"$out/claude.err"
echo "claude exit $?" >"$out/mark.txt"
git -C "$wt" log --format='%H %ct %s' -4 >>"$out/mark.txt"
ls "$wt/.relay/checks" >>"$out/mark.txt" 2>&1
echo done
