#!/usr/bin/env bash
# The check-mark hook (hooks/check-mark.py) and the guard's .relay/checks rule (hooks/guard-main.sh): cases K1-K8,
# K10-K12 and G1-G7 of docs/plans/review-gate.md section 12.3, on throwaway repositories under a temp dir (temp HOME).
# K9 is the live run (a real checker, paid): tests/live_k9.sh, never part of the gate.
#   plugins/core/tests/check-mark.test.sh
set -uo pipefail
here="$(cd "$(dirname "$0")" && pwd -P)"
hook="$here/../hooks/check-mark.py"
guard="$here/../hooks/guard-main.sh"
unset CLAUDE_PROJECT_DIR
tmp="$(cd "$(mktemp -d)" && pwd -P)"
trap 'rm -rf "$tmp"' EXIT
export HOME="$tmp/home"; mkdir -p "$HOME"
export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_SYSTEM=/dev/null GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@t GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@t
export TZ=UTC   # touch -t stamps are read as UTC, like the transcript timestamps
fails=0; n=0
ok() { echo "ok    $1"; }
bad() { echo "FAIL  $1"; fails=$((fails + 1)); }
expect() { if [ "$2" -eq 0 ]; then ok "$1"; else bad "$1"; fi; }   # <desc> <exit code 0 = true>
has() { case "$2" in *"$1"*) return 0 ;; *) return 1 ;; esac; }
count() { git -C "$W" rev-list --count HEAD; }

START="2026-10-22T10:00:00.000Z"      # the agent's first timestamp; a report is new when its mtime is after it
NEW=202610221100; OLD=202610220900    # touch -t stamps after and before START

# mkrepo [norelay]: M = main on master (with .relay/ unless norelay); W = worktree on wt/t with one commit;
# INIT = master's commit (the "reviewed" sha), HEAD0 = W's head (the "checked" sha)
mkrepo() {
  n=$((n + 1)); M="$tmp/r$n"; S="$tmp/s$n"; mkdir -p "$M" "$S" && cd "$M" && git init -q -b master . || exit 1
  printf '.ci/\n' >.gitignore
  [ "${1:-}" = norelay ] || { mkdir -p .relay && echo x >.relay/README.md; }
  git add -A && git commit -q -m init
  git worktree add -q .worktrees/t -b wt/t
  W="$M/.worktrees/t"
  ( cd "$W" && echo a >a.txt && git add a.txt && git commit -q -m work )
  INIT="$(git -C "$M" rev-parse master)"; HEAD0="$(git -C "$W" rev-parse HEAD)"
  printf 'Reviewed: %s\nF1 note\n' "$INIT" >"$S/f.md"
  report 0
}
# report <open> [stamp]: the checker's report at $S/rep.md ending in the verdict
report() {
  printf '# Check\nall good\n## Verdict\nhead %s\nreviewed %s\nopen %s\nqueued 0\n' "$HEAD0" "$INIT" "$1" >"$S/rep.md"
  touch -t "${2:-$NEW}" "$S/rep.md"
}
# prompt [check files]: the delegate skill's check prompt, verbatim form (backticks, periods), as the transcript's first line
prompt() {
  local files="${1:-\`$S/f.md\`}"
  jq -nc --arg t "Check: $files. Fixes: \`none\`. Worktree: \`$W\`. Check command: \`bin/ci --quick\`. Gate: \`none\`. Report: \`$S/rep.md\`." --arg ts "$START" \
    '{type:"user", timestamp:$ts, message:{role:"user", content:$t}}' >"$S/agent.jsonl"
}
# stop <agent_type> -> $out, $rc
stop() {
  out="$(jq -n --arg ty "$1" --arg cwd "$M" --arg tp "$S/agent.jsonl" '{hook_event_name:"SubagentStop", agent_type:$ty, agent_id:"a1", cwd:$cwd, agent_transcript_path:$tp}' \
    | python3 -I "$hook" 2>&1)"; rc=$?
  msg="$(jq -r '.systemMessage // empty' <<<"$out" 2>/dev/null)"
}
checks() { git -C "$W" ls-tree --name-only HEAD .relay/checks/ | sed 's|.*/||' | sort | tr '\n' ' '; }

# K1: valid checker stop -> one commit holding only the three files; the json as 4.1; every sha 40 characters
mkrepo; prompt; before="$(count)"; stop delegate:checker
expect "K1 exit 0" "$([ "$rc" -eq 0 ]; echo $?)"
expect "K1 one new commit" "$([ "$(count)" -eq $((before + 1)) ]; echo $?)"
want="$(printf '%s\n' ".relay/checks/$HEAD0.check.md" ".relay/checks/$HEAD0.json" ".relay/checks/$INIT.review.md" | sort | tr '\n' ' ')"
got="$(git -C "$W" show --name-only --format= HEAD | sort | tr '\n' ' ')"
expect "K1 the commit holds only <head>.json, <head>.check.md, <reviewed>.review.md" "$([ "$want" = "$got" ]; echo $?)"
j="$(git -C "$W" show "HEAD:.relay/checks/$HEAD0.json")"
expect "K1 json fields" "$(jq -e --arg h "$HEAD0" --arg r "$INIT" '.commit==$h and .verdict=={open:0,queued:0,reviewed:$r} and .review==($r+".review.md") and .check==($h+".check.md") and (.time|type=="string")' <<<"$j" >/dev/null; echo $?)"
expect "K1 every sha is 40 hex characters" "$(jq -e '[.commit, .verdict.reviewed] | all(test("^[0-9a-f]{40}$"))' <<<"$j" >/dev/null; echo $?)"
expect "K1 the review holds the findings under their file name" "$(git -C "$W" show "HEAD:.relay/checks/$INIT.review.md" | grep -q '^# f.md$'; echo $?)"
expect "K1 the commit message names the head" "$([ "$(git -C "$W" log -1 --format=%s)" = "relay: check of $HEAD0" ]; echo $?)"

# K2: delegate:critic -> nothing; then the checker's stop -> the mark
mkrepo; prompt; before="$(count)"; stop delegate:critic
expect "K2 critic: no commit, no output" "$([ "$(count)" -eq "$before" ] && [ -z "$out" ]; echo $?)"
stop delegate:checker
expect "K2 then checker: the mark commit" "$([ "$(count)" -eq $((before + 1)) ]; echo $?)"

# K3: empty agent_type
mkrepo; prompt; before="$(count)"; stop ""
expect "K3 empty agent_type: no commit" "$([ "$(count)" -eq "$before" ] && [ -z "$out" ]; echo $?)"

# K4: a report without ## Verdict, with an earlier clean mark on that head: no mark, the old one removed, reason named
mkrepo; prompt; stop delegate:checker
expect "K4 setup: the earlier mark exists" "$(git -C "$W" cat-file -e "HEAD:.relay/checks/$HEAD0.json"; echo $?)"
before="$(count)"; printf '# Check\nno verdict here\n' >"$S/rep.md"; touch -t $NEW "$S/rep.md"; stop delegate:checker
expect "K4 a commit removing the old mark" "$([ "$(count)" -eq $((before + 1)) ] && ! git -C "$W" cat-file -e "HEAD:.relay/checks/$HEAD0.json" 2>/dev/null; echo $?)"
expect "K4 systemMessage names the reason" "$(has 'check mark not written for wt/t: the report has no ## Verdict block' "$msg"; echo $?)"

# K5: a report older than the transcript's first timestamp
mkrepo; prompt; report 0 $OLD; before="$(count)"; stop delegate:checker
expect "K5 old report: no commit" "$([ "$(count)" -eq "$before" ]; echo $?)"
expect "K5 reason named" "$(has 'older than the checker' "$msg"; echo $?)"

# K6: head not in the history, or abbreviated
mkrepo; prompt; before="$(count)"
printf '## Verdict\nhead %s\nreviewed %s\nopen 0\nqueued 0\n' "$(printf 'ab%.0s' $(seq 20))" "$INIT" >"$S/rep.md"; touch -t $NEW "$S/rep.md"; stop delegate:checker
expect "K6 unknown head: no commit, reason named" "$([ "$(count)" -eq "$before" ] && has 'is not a commit of this worktree' "$msg"; echo $?)"
printf '## Verdict\nhead %s\nreviewed %s\nopen 0\nqueued 0\n' "${HEAD0:0:7}" "$INIT" >"$S/rep.md"; touch -t $NEW "$S/rep.md"; stop delegate:checker
expect "K6 abbreviated head: no commit, reason named" "$([ "$(count)" -eq "$before" ] && has 'is not a full sha' "$msg"; echo $?)"

# K7: no .relay/ on the default branch -> nothing; positive control K1 (same input, with it)
mkrepo norelay; prompt; before="$(count)"; stop delegate:checker
expect "K7 no .relay/: no commit, no output" "$([ "$(count)" -eq "$before" ] && [ -z "$out" ]; echo $?)"
mkrepo; prompt; before="$(count)"; stop delegate:checker
expect "K7 control with .relay/: the mark commit" "$([ "$(count)" -eq $((before + 1)) ]; echo $?)"

# K8: another file staged, the index locked for 2 s: the commit holds only the hook's files, the other stays staged,
# and the locked case lands on a retry (the lock is taken away by the background job; the hook waits 1 s between tries)
mkrepo; prompt; echo o >"$W/other.txt"; git -C "$W" add other.txt; before="$(count)"
lock="$(git -C "$W" rev-parse --path-format=absolute --git-path index.lock)"
: >"$lock"; ( sleep 2; rm -f "$lock" ) & job=$!
stop delegate:checker; wait "$job"
expect "K8 locked 2 s: the mark landed on a retry" "$([ "$(count)" -eq $((before + 1)) ] && git -C "$W" cat-file -e "HEAD:.relay/checks/$HEAD0.json"; echo $?)"
expect "K8 the commit holds only the hook's files" "$(! git -C "$W" show --name-only --format= HEAD | grep -q other.txt; echo $?)"
expect "K8 the other file stays staged" "$([ "$(git -C "$W" diff --cached --name-only)" = other.txt ]; echo $?)"

# K10: Check: a.md, b.md -> one review file holding both under their headings
mkrepo; printf 'Reviewed: %s\nF1 from a\n' "$INIT" >"$S/a.md"; printf 'Q1 question from b\n' >"$S/b.md"; prompt "\`$S/a.md\`, \`$S/b.md\`"; stop delegate:checker
rev="$(git -C "$W" show "HEAD:.relay/checks/$INIT.review.md")"
expect "K10 both headings, both bodies" "$(has '# a.md' "$rev" && has 'F1 from a' "$rev" && has '# b.md' "$rev" && has 'Q1 question from b' "$rev"; echo $?)"
expect "K10 a before b" "$([ "$(grep -n '^# a.md' <<<"$rev" | cut -d: -f1)" -lt "$(grep -n '^# b.md' <<<"$rev" | cut -d: -f1)" ]; echo $?)"

# K11: a re-check of the same head after 'Owner: F3 is not wrong': the review file is replaced, the mark's open changes
mkrepo; prompt; report 1; stop delegate:checker
expect "K11 first mark: open 1" "$([ "$(git -C "$W" show "HEAD:.relay/checks/$HEAD0.json" | jq .verdict.open)" = 1 ]; echo $?)"
printf 'Owner: F3 is not wrong ("fine")\n' >>"$S/f.md"; report 0; stop delegate:checker
expect "K11 the review carries the Owner line" "$(git -C "$W" show "HEAD:.relay/checks/$INIT.review.md" | grep -q '^Owner: F3 is not wrong'; echo $?)"
expect "K11 the mark's open is 0" "$([ "$(git -C "$W" show "HEAD:.relay/checks/$HEAD0.json" | jq .verdict.open)" = 0 ]; echo $?)"

# K12: a prompt that is a brief file, not the check line
mkrepo; before="$(count)"
jq -nc --arg t "Check the fix per the brief. Brief: $S/brief.md. Report: $S/rep.md." --arg ts "$START" '{type:"user",timestamp:$ts,message:{role:"user",content:$t}}' >"$S/agent.jsonl"
stop delegate:checker
expect "K12 no commit" "$([ "$(count)" -eq "$before" ]; echo $?)"
expect "K12 systemMessage names 'no Check:/Worktree: line'" "$(has 'no Check:/Worktree: line' "$msg"; echo $?)"

# ---- the guard (G1-G7), the real guard-main.sh with CLAUDE_PROJECT_DIR = the worktree (as in a worktree session) ----
mkrepo; GM="$M"; GW="$W"; mkdir -p "$tmp/scratch" "$tmp/fx"
# g <expect: block|allow> <desc> <tool> <cwd> <key> <value> [anchor]
g() {
  local expect="$1" desc="$2" tool="$3" cwd="$4" key="$5" val="$6" anchor="${7:-$GW}" got err
  err="$(jq -n --arg tool "$tool" --arg cwd "$cwd" --arg key "$key" --arg val "$val" '{tool_name:$tool, cwd:$cwd, tool_input:{($key):$val}}' \
    | CLAUDE_PROJECT_DIR="$anchor" "$guard" 2>&1 >/dev/null)"
  [ $? -eq 2 ] && got=block || got=allow
  if [ "$got" = "$expect" ]; then ok "$desc"; else bad "$desc (got $got: $err)"; fi
  LAST_ERR="$err"
}
g block "G1 Write on the worktree's .relay/checks/x.json" Write "$GW" file_path "$GW/.relay/checks/x.json"
expect "G1 the guard's message" "$(has 'files in .relay/checks are written only by relay' "$LAST_ERR"; echo $?)"
g block "G1 Edit on the main checkout's .relay/checks/x.json" Edit "$GM" file_path "$GM/.relay/checks/x.json"
g block "G1 MultiEdit, relative path" MultiEdit "$GW" file_path ".relay/checks/x.json"
g block "G2 printf > .relay/checks/a.json" Bash "$GW" command "printf x > .relay/checks/a.json"
g block "G2 cp a .relay/checks/" Bash "$GW" command "cp a.txt .relay/checks/"
g block "G2 git add .relay/checks" Bash "$GW" command "git add .relay/checks"
g block "G2 git checkout other -- .relay/checks" Bash "$GW" command "git checkout other -- .relay/checks"
g block "G2 git -C <worktree> rm from elsewhere" Bash "$tmp/scratch" command "git -C $GW rm -r .relay/checks"
g block "G3 python3 -c open(...,'w')" Bash "$GW" command "python3 -c \"open('.relay/checks/a.json','w').write('x')\""
g block "G3 node -e writeFile" Bash "$GW" command "node -e \"require('fs').writeFileSync('.relay/checks/a.json','x')\""
g allow "G4 Write on the scratchpad's check.md" Write "$GW" file_path "$tmp/scratch/check.md"
g allow "G4 Write on <worktree>/.ci/check.md" Write "$GW" file_path "$GW/.ci/check.md"
g allow "G5 relay check show wt/x" Bash "$GW" command "relay check show wt/x"
g allow "G5 relay gate" Bash "$GW" command "relay gate"
g allow "G5 git log" Bash "$GW" command "git log --oneline .relay/checks"
g allow "G6 grep -rn" Bash "$GW" command "grep -rn \".relay/checks\" plugins/core"
g allow "G6 cat a stored review" Bash "$GW" command "cat .relay/checks/x.review.md"
g allow "G6 jq .verdict" Bash "$GW" command "jq .verdict .relay/checks/X.json"
g allow "G6 inline python that only reads" Bash "$GW" command "python3 -c \"import json;print(json.load(open('.relay/checks/X.json'))['verdict'])\""
g allow "G6 a heredoc into the scratchpad whose body names .relay/checks" Bash "$GW" command "cat >> $tmp/scratch/r.md <<'EOF'
the findings live in .relay/checks/x.review.md
EOF"
# G7: outside any repository with .relay/, Write and Bash are allowed; inside one, refused
g allow "G7 mkdir + printf under a fixture outside any repository" Bash "$GW" command "mkdir -p $tmp/fx/.relay/checks && printf '{}' > $tmp/fx/.relay/checks/a.json"
g allow "G7 Write on the same path" Write "$GW" file_path "$tmp/fx/.relay/checks/a.json"
g block "G7 the same printf into the worktree's .relay/checks/a.json" Bash "$GW" command "printf '{}' > .worktrees/t/.relay/checks/a.json" "$GM"
mkrepo norelay
g allow "G7 a repository without .relay/: printf into its worktree's .relay/checks" Bash "$W" command "printf '{}' > .relay/checks/a.json" "$W"
g allow "G7 a repository without .relay/: Write there" Write "$W" file_path "$W/.relay/checks/a.json" "$W"

[ "$fails" -eq 0 ] && echo "check-mark.test: all passed" || echo "check-mark.test: $fails FAILED"
exit $((fails > 0))
