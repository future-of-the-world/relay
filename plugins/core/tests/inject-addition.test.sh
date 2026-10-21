#!/usr/bin/env bash
# Cases for hooks/inject-addition.sh over a temporary repository with a worktree.
#   plugins/core/tests/inject-addition.test.sh
set -uo pipefail

hook="$(cd "$(dirname "$0")" && pwd -P)/../hooks/inject-addition.sh"
tmp="$(cd "$(mktemp -d)" && pwd -P)"
trap 'rm -rf "$tmp"' EXIT
R="$tmp/repo"
mkdir -p "$R/.claude/kit" "$R/sub/dir" && cd "$R" && git init -q -b master . \
  && printf 'WORKER-RULE ПСК\nsecond line\n' >.claude/kit/worker.md \
  && printf 'PLAN-RULE\n' >.claude/kit/plan.md \
  && printf 'PRODUCT-RULE\n' >.claude/kit/ui-reviewer.md \
  && git add -A && git -c user.name=t -c user.email=t@t commit -q -m init \
  && git worktree add -q .worktrees/wt1 -b wt/wt1 \
  && git worktree add -q .worktrees/wt2 -b wt/wt2 || { echo "inject-addition.test: cannot build the repo" >&2; exit 1; }
rm -f .worktrees/wt2/.claude/kit/worker.md   # a worktree whose branch lacks the file
fails=0

agent() { jq -n --arg a "$1" --arg c "$2" '{hook_event_name: "SubagentStart", agent_type: $a, cwd: $c}' | "$hook"; }
skill() { jq -n --arg s "$1" --arg c "$2" '{hook_event_name: "PostToolUse", tool_name: "Skill", tool_input: {skill: $s}, cwd: $c}' | "$hook"; }
prompt() { jq -n --arg p "$1" --arg c "$2" '{hook_event_name: "UserPromptSubmit", prompt: $p, cwd: $c}' | "$hook"; }
ck() { # <description> <expected substring or -> <actual output>
  if [ "$2" = - ]; then
    [ -z "$3" ] && echo "ok    $1" || { echo "FAIL  $1: expected no output, got: $3"; fails=$((fails + 1)); }
  else
    grep -qF -- "$2" <<<"$3" && echo "ok    $1" || { echo "FAIL  $1: expected [$2], got: $3"; fails=$((fails + 1)); }
  fi
}
ctx() { jq -r '.hookSpecificOutput.additionalContext // empty' <<<"$1"; }
ev() { jq -r '.hookSpecificOutput.hookEventName // empty' <<<"$1"; }

out="$(agent sdd:worker "$R")"
ck "agent: the project's worker addition" "WORKER-RULE ПСК" "$(ctx "$out")"
ck "agent: whole file, second line too" "second line" "$(ctx "$out")"
ck "agent: event name echoed" "SubagentStart" "$(ev "$out")"
ck "agent: names who it is for" "sdd:worker" "$(ctx "$out")"
ck "agent: from a subfolder of the project" "WORKER-RULE" "$(ctx "$(agent sdd:worker "$R/sub/dir")")"
ck "agent: in a worktree, the worktree's own file" "WORKER-RULE" "$(ctx "$(agent sdd:worker "$R/.worktrees/wt1")")"
ck "agent: a worktree without the file gets nothing" - "$(agent sdd:worker "$R/.worktrees/wt2")"
ck "agent: no addition for that role" - "$(agent sdd:fixer "$R")"
ck "agent: a project's own agent (no plugin) gets nothing" - "$(agent worker "$R")"
ck "agent: a built-in agent gets nothing" - "$(agent general-purpose "$R")"
ck "agent: role cannot leave the folder" - "$(agent 'sdd:../../etc/passwd' "$R")"
ck "agent: a core: name is served too" "WORKER-RULE" "$(ctx "$(agent core:worker "$R")")"

ck "agent: another plugin's role gets nothing" - "$(agent pr-review-toolkit:worker "$R")"
ck "agent: an unlisted plugin's plan gets nothing" - "$(agent other:plan "$R")"
ck "agent: product is served" "PRODUCT-RULE" "$(ctx "$(agent product:ui-reviewer "$R")")"

out="$(prompt "/sdd:plan add a low-stock view" "$R")"
ck "prompt: a typed stage gets its addition" "PLAN-RULE" "$(ctx "$out")"
ck "prompt: UserPromptSubmit event name" "UserPromptSubmit" "$(ev "$out")"
ck "prompt: the stage alone, no arguments" "PLAN-RULE" "$(ctx "$(prompt "/sdd:plan" "$R")")"
ck "prompt: leading spaces" "PLAN-RULE" "$(ctx "$(prompt "  /sdd:plan x" "$R")")"
ck "prompt: a stage with no addition" - "$(prompt "/sdd:archive" "$R")"
ck "prompt: a stage of another plugin" - "$(prompt "/pr-review-toolkit:plan x" "$R")"
ck "prompt: a command without a plugin" - "$(prompt "/plan x" "$R")"
ck "prompt: an opsx command is not a stage skill" - "$(prompt "/opsx:propose x" "$R")"
ck "prompt: plain text" - "$(prompt "please /sdd:plan this" "$R")"
ck "prompt: a name that only starts like a stage" - "$(prompt "/sdd:planner x" "$R")"
ck "prompt: in a worktree, the worktree's own file" "PLAN-RULE" "$(ctx "$(prompt "/sdd:plan x" "$R/.worktrees/wt1")")"

out="$(skill sdd:plan "$R")"
ck "skill: the project's plan addition" "PLAN-RULE" "$(ctx "$out")"
ck "skill: PostToolUse event name" "PostToolUse" "$(ev "$out")"
ck "skill: no addition for that skill" - "$(skill sdd:archive "$R")"
ck "skill: an unqualified skill gets nothing" - "$(skill plan "$R")"
other="$(jq -n --arg c "$R" '{hook_event_name: "PostToolUse", tool_name: "Bash", tool_input: {command: "ls"}, cwd: $c}' | "$hook")"
ck "another tool gets nothing" - "$other"
ck "an outside directory gets nothing" - "$(agent sdd:worker "$tmp")"
ck "another event gets nothing" - "$(jq -n --arg c "$R" '{hook_event_name: "Stop", cwd: $c}' | "$hook")"

[ "$fails" -eq 0 ] && echo "inject-addition.test: all passed" || { echo "inject-addition.test: $fails failed"; exit 1; }
