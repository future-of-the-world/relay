#!/usr/bin/env bash
# Cases for hooks/inject-addition.sh over a temporary repository with a worktree.
#   plugins/core/tests/inject-addition.test.sh
set -uo pipefail

here="$(cd "$(dirname "$0")" && pwd -P)"
hook="$here/../hooks/inject-addition.sh"
golden="$here/inject-addition.golden"
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

out="$(agent openspec:worker "$R")"
ck "agent: the project's worker addition" "WORKER-RULE ПСК" "$(ctx "$out")"
ck "agent: whole file, second line too" "second line" "$(ctx "$out")"
ck "agent: event name echoed" "SubagentStart" "$(ev "$out")"
ck "agent: names who it is for" "openspec:worker" "$(ctx "$out")"
ck "agent: from a subfolder of the project" "WORKER-RULE" "$(ctx "$(agent openspec:worker "$R/sub/dir")")"
ck "agent: in a worktree, the worktree's own file" "WORKER-RULE" "$(ctx "$(agent openspec:worker "$R/.worktrees/wt1")")"
ck "agent: a worktree without the file gets nothing" - "$(agent openspec:worker "$R/.worktrees/wt2")"
ck "agent: no addition for that role" - "$(agent openspec:fixer "$R")"
ck "agent: a project's own agent (no plugin) gets nothing" - "$(agent worker "$R")"
ck "agent: a built-in agent gets nothing" - "$(agent general-purpose "$R")"
ck "agent: role cannot leave the folder" - "$(agent 'openspec:../../etc/passwd' "$R")"
ck "agent: a core: name is served too" "WORKER-RULE" "$(ctx "$(agent core:worker "$R")")"

ck "agent: another plugin's role gets nothing" - "$(agent pr-review-toolkit:worker "$R")"
ck "agent: an unlisted plugin's plan gets nothing" - "$(agent other:plan "$R")"
ck "agent: product is served" "PRODUCT-RULE" "$(ctx "$(agent product:ui-reviewer "$R")")"

out="$(prompt "/openspec:plan add a low-stock view" "$R")"
ck "prompt: a typed stage gets its addition" "PLAN-RULE" "$(ctx "$out")"
ck "prompt: UserPromptSubmit event name" "UserPromptSubmit" "$(ev "$out")"
ck "prompt: the stage alone, no arguments" "PLAN-RULE" "$(ctx "$(prompt "/openspec:plan" "$R")")"
ck "prompt: leading spaces" "PLAN-RULE" "$(ctx "$(prompt "  /openspec:plan x" "$R")")"
ck "prompt: a stage with no addition" - "$(prompt "/openspec:archive" "$R")"
ck "prompt: a stage of another plugin" - "$(prompt "/pr-review-toolkit:plan x" "$R")"
ck "prompt: a command without a plugin" - "$(prompt "/plan x" "$R")"
ck "prompt: an opsx command is not a stage skill" - "$(prompt "/opsx:propose x" "$R")"
ck "prompt: plain text" - "$(prompt "please /openspec:plan this" "$R")"
ck "prompt: a name that only starts like a stage" - "$(prompt "/openspec:planner x" "$R")"
ck "prompt: in a worktree, the worktree's own file" "PLAN-RULE" "$(ctx "$(prompt "/openspec:plan x" "$R/.worktrees/wt1")")"

out="$(skill openspec:plan "$R")"
ck "skill: the project's plan addition" "PLAN-RULE" "$(ctx "$out")"
ck "skill: PostToolUse event name" "PostToolUse" "$(ev "$out")"
ck "skill: no addition for that skill" - "$(skill openspec:archive "$R")"
ck "skill: an unqualified skill gets nothing" - "$(skill plan "$R")"
other="$(jq -n --arg c "$R" '{hook_event_name: "PostToolUse", tool_name: "Bash", tool_input: {command: "ls"}, cwd: $c}' | "$hook")"
ck "another tool gets nothing" - "$other"
ck "an outside directory gets nothing" - "$(agent openspec:worker "$tmp")"
ck "another event gets nothing" - "$(jq -n --arg c "$R" '{hook_event_name: "Stop", cwd: $c}' | "$hook")"

# I4: kartoteka's 12 per-agent files and no role file: the output is byte for byte what the hook gave before role files
# existed (inject-addition.golden, recorded from that hook; INJECT_RECORD=<file> re-records, only ever from a hook known good).
K="$tmp/kartoteka"
mkdir -p "$K/.claude/kit" && git -C "$K" init -q -b master
names="apply-review archive author fixer parallel-apply plan reviewer spec-conformance spec-review spec-reviewer ui-reviewer worker"
for n in $names; do printf '%s-MARK\nline two of %s\n' "$n" "$n" >"$K/.claude/kit/$n.md"; done
golden_out() {
  for n in $names; do
    echo "== agent openspec:$n"; agent "openspec:$n" "$K"
    echo "== agent product:$n"; agent "product:$n" "$K"
    echo "== skill openspec:$n"; skill "openspec:$n" "$K"
    echo "== prompt /openspec:$n"; prompt "/openspec:$n go" "$K"
  done
}
if [ -n "${INJECT_RECORD:-}" ]; then golden_out >"$INJECT_RECORD"; echo "recorded $INJECT_RECORD"; exit 0; fi
if [ "$(golden_out | shasum)" = "$(shasum <"$golden")" ]; then echo "ok    I4: 12 per-agent files, no role file: output equals the golden file"
else echo "FAIL  I4: output differs from inject-addition.golden"; fails=$((fails + 1)); fi

# Per-role files (I1-I3, I5-I9): the same 12 files plus .claude/kit/judge.md, JUDGE-MARK inside.
J="$tmp/withrole"
cp -R "$K" "$J" && printf 'JUDGE-MARK\n' >"$J/.claude/kit/judge.md"
before() { # <first marker> <second marker> <text>: the first occurs, then the second after it
  local a b
  a="$(grep -bo -m1 -- "$1" <<<"$3" | head -1 | cut -d: -f1)"; b="$(grep -bo -m1 -- "$2" <<<"$3" | head -1 | cut -d: -f1)"
  [ -n "$a" ] && [ -n "$b" ] && [ "$a" -lt "$b" ]
}
out="$(ctx "$(agent openspec:spec-reviewer "$J")")"
before "JUDGE-MARK" "spec-reviewer-MARK" "$out" && echo "ok    I1: openspec:spec-reviewer gets the judge file, then its own" || { echo "FAIL  I1: $out"; fails=$((fails + 1)); }
ck "I1: role heading" "Project rules for the judge role (.claude/kit/judge.md of this project)" "$out"
ck "I1: agent heading says its rules win" "Project rules for openspec:spec-reviewer (.claude/kit/spec-reviewer.md); where they differ from the role's rules, these win" "$out"
ck "I1: event name" "SubagentStart" "$(ev "$(agent openspec:spec-reviewer "$J")")"
out="$(ctx "$(agent delegate:critic "$J")")"
ck "I2: delegate:critic gets the judge file" "JUDGE-MARK" "$out"
ck "I2: and its role heading" "Project rules for the judge role" "$out"
case "$out" in *"Project rules for delegate:critic"*) echo "FAIL  I2: critic has no file of its own, no second heading"; fails=$((fails + 1)) ;; *) echo "ok    I2: no agent heading without an agent file" ;; esac
ck "I3: delegate:checker gets the judge file" "JUDGE-MARK" "$(ctx "$(agent delegate:checker "$J")")"
out="$(ctx "$(agent delegate:worker "$J")")"
ck "I5: delegate:worker gets worker.md as before" "worker-MARK" "$out"
case "$out" in *JUDGE-MARK*) echo "FAIL  I5: a build agent got the judge file"; fails=$((fails + 1)) ;; *) echo "ok    I5: and not the judge file" ;; esac
ck "I6: the skill openspec:plan gets plan.md" "plan-MARK" "$(ctx "$(skill openspec:plan "$J")")"
ck "I6: the typed /openspec:plan gets plan.md" "plan-MARK" "$(ctx "$(prompt "/openspec:plan go" "$J")")"
case "$(skill openspec:plan "$J")$(prompt "/openspec:plan go" "$J")" in *JUDGE-MARK*) echo "FAIL  I6: a role file reached a skill"; fails=$((fails + 1)) ;; *) echo "ok    I6: no role file for a skill or a typed stage" ;; esac
JO="$tmp/judgeonly"; mkdir -p "$JO/.claude/kit" && git -C "$JO" init -q -b master && printf 'JUDGE-MARK\n' >"$JO/.claude/kit/judge.md"
out="$(ctx "$(agent product:ui-reviewer "$JO")")"
ck "I8: judge.md alone reaches product:ui-reviewer" "JUDGE-MARK" "$out"
ck "I8: judge.md alone gives a build agent nothing" - "$(agent delegate:worker "$JO")"
# a map of our own, beside a copy of the hook
mkdir -p "$tmp/h/hooks" "$tmp/h/lib" && cp "$hook" "$tmp/h/hooks/inject-addition.sh"
hook_saved="$hook"; hook="$tmp/h/hooks/inject-addition.sh"
printf 'openspec:author\tthink\n' >"$tmp/h/lib/agent-roles.tsv"
ck "I7: an agent missing from the map gets its own file only" "reviewer-MARK" "$(ctx "$(agent openspec:reviewer "$J")")"
case "$(agent openspec:reviewer "$J")" in *JUDGE-MARK*) echo "FAIL  I7: a role file reached an agent not in the map"; fails=$((fails + 1)) ;; *) echo "ok    I7: and no role file" ;; esac
rm -f "$tmp/h/lib/agent-roles.tsv"
out="$(agent openspec:reviewer "$J")"; rc=$?
[ "$rc" -eq 0 ] && echo "ok    I9: no map file: exit 0" || { echo "FAIL  I9: exit $rc"; fails=$((fails + 1)); }
ck "I9: no map file: per-agent file only" "reviewer-MARK" "$(ctx "$out")"
case "$out" in *JUDGE-MARK*) echo "FAIL  I9: role file with no map"; fails=$((fails + 1)) ;; *) echo "ok    I9: and no role file" ;; esac
hook="$hook_saved"

[ "$fails" -eq 0 ] && echo "inject-addition.test: all passed" || { echo "inject-addition.test: $fails failed"; exit 1; }
