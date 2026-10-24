#!/usr/bin/env bash
# The check-mark hook (hooks/check-mark.py) and the guard's .relay/checks rule (hooks/guard-main.sh): cases K1-K8,
# K10-K12 (K4b is new) and G1-G7 of docs/plans/review-gate.md section 12.3, on throwaway repositories under a temp dir (temp HOME).
# The reports are recorded by `relay check record review|check --input <file.toml>` (the agents' only way to write the JSON the hook reads;
# nothing but JSON is stored: no .md report is written or committed).
# K9 is the live run (a real checker, paid): tests/live_k9.sh, never part of the gate.
#   plugins/core/tests/check-mark.test.sh
set -uo pipefail
here="$(cd "$(dirname "$0")" && pwd -P)"
hook="$here/../hooks/check-mark.py"
guard="$here/../hooks/guard-main.sh"
relay="$here/../../../bin/relay"
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
  review "$S/f.json" F1 note
  report 0
}
# review <file.json> <id> <summary> [kind]: the review recorded at <file.json> from a TOML input (the shell passes no text but paths)
review() {
  cat >"$S/review.toml" <<EOF
report = "$1"
reviewed = "$INIT"
base = "master"
[[finding]]
id = "$2"
path = "a.txt"
line = 1
severity = "HIGH"
kind = "${4:-inside}"
summary = "$3"
failing_case = "x gives 1, should give 2"
EOF
  "$relay" check record review --input "$S/review.toml" >/dev/null || echo "setup: review record failed" >&2
  touch -t $NEW "$1"
}
# report <open> [stamp] [head]: the checker's data at $S/rep.json; REVIEWS = the review data files
REVIEWS="" ; HEADREC=""
report() {
  local revs=${REVIEWS:-$S/f.json} arr
  arr="$(printf '"%s", ' $revs)"; arr="[${arr%, }]"
  cat >"$S/check.toml" <<EOF
report = "$S/rep.json"
head = "${3:-$HEAD0}"
reviewed = "$INIT"
worktree = "$W"
gate = "none"
review = $arr
open = $1
queued = 0
[[status]]
id = "F1"
verdict = "MET"
EOF
  "$relay" check record check --input "$S/check.toml" >/dev/null || echo "setup: check record failed" >&2
  touch -t "${2:-$NEW}" "$S/rep.json"
}
# prompt [check files]: the delegate skill's check prompt, verbatim form (backticks, periods), as the transcript's first line
prompt() {
  local files="${1:-\`$S/f.json\`}"
  jq -nc --arg t "Check: $files. Fixes: \`none\`. Worktree: \`$W\`. Check command: \`bin/ci --quick\`. Gate: \`none\`. Report: \`$S/rep.json\`." --arg ts "$START" \
    '{type:"user", timestamp:$ts, message:{role:"user", content:$t}}' >"$S/agent.jsonl"
}
# stop <agent_type> -> $out, $rc
stop() {
  out="$(jq -n --arg ty "$1" --arg cwd "$M" --arg tp "$S/agent.jsonl" '{hook_event_name:"SubagentStop", agent_type:$ty, agent_id:"a1", cwd:$cwd, agent_transcript_path:$tp}' \
    | python3 -I "$hook" 2>&1)"; rc=$?
  msg="$(jq -r '.systemMessage // empty' <<<"$out" 2>/dev/null)"
}
checks() { git -C "$W" ls-tree --name-only HEAD .relay/checks/ | sed 's|.*/||' | sort | tr '\n' ' '; }

# K1: valid checker stop -> one commit holding only the three JSON files; the json as 4.1; every sha 40 characters
mkrepo; prompt; before="$(count)"; stop delegate:checker
expect "K1 exit 0" "$([ "$rc" -eq 0 ]; echo $?)"
expect "K1 one new commit" "$([ "$(count)" -eq $((before + 1)) ]; echo $?)"
want="$(printf '%s\n' ".relay/checks/$HEAD0.check.json" ".relay/checks/$HEAD0.json" ".relay/checks/$INIT.review.json" | sort | tr '\n' ' ')"
got="$(git -C "$W" show --name-only --format= HEAD | sort | tr '\n' ' ')"
expect "K1 the commit holds only the mark, the check data and the review data (no .md)" "$([ "$want" = "$got" ]; echo $?)"
j="$(git -C "$W" show "HEAD:.relay/checks/$HEAD0.json")"
expect "K1 json fields" "$(jq -e --arg h "$HEAD0" --arg r "$INIT" '.commit==$h and .schema==1 and .verdict=={open:0,queued:0,reviewed:$r} and .review==($r+".review.json") and .check==($h+".check.json") and (has("review_data")|not) and (.time|type=="string")' <<<"$j" >/dev/null; echo $?)"
expect "K1 every sha is 40 hex characters" "$(jq -e '[.commit, .verdict.reviewed] | all(test("^[0-9a-f]{40}$"))' <<<"$j" >/dev/null; echo $?)"
expect "K1 no readable report is stored: no .md under .relay/checks" "$(! git -C "$W" ls-tree --name-only -r HEAD .relay/checks/ | grep -q '\.md$'; echo $?)"
cj="$(git -C "$W" show "HEAD:.relay/checks/$HEAD0.check.json")"
expect "K1 the stored check data: head, reviewed, open, no worktree, review is the stored set" "$(jq -e --arg h "$HEAD0" --arg r "$INIT" '.head==$h and .reviewed==$r and .open==0 and .queued==0 and (has("worktree")|not) and .review==[($r+".review.json")] and .schema==1 and .type=="check" and .findings==[{id:"F1",verdict:"MET",reason:[]}]' <<<"$cj" >/dev/null; echo $?)"
rj="$(git -C "$W" show "HEAD:.relay/checks/$INIT.review.json")"
expect "K1 the stored review set holds the finding under its file name" "$(jq -e '.schema==1 and .type=="review-set" and (.reviews|length==1) and .reviews[0].file=="f.json" and .reviews[0].findings[0].id=="F1" and .reviews[0].findings[0].kind=="inside"' <<<"$rj" >/dev/null; echo $?)"
expect "K1 the commit message names the head" "$([ "$(git -C "$W" log -1 --format=%s)" = "relay: check of $HEAD0" ]; echo $?)"

# K2: delegate:critic -> nothing; then the checker's stop -> the mark
mkrepo; prompt; before="$(count)"; stop delegate:critic
expect "K2 critic: no commit, no output" "$([ "$(count)" -eq "$before" ] && [ -z "$out" ]; echo $?)"
stop delegate:checker
expect "K2 then checker: the mark commit" "$([ "$(count)" -eq $((before + 1)) ]; echo $?)"

# K3: empty agent_type
mkrepo; prompt; before="$(count)"; stop ""
expect "K3 empty agent_type: no commit" "$([ "$(count)" -eq "$before" ] && [ -z "$out" ]; echo $?)"

# K4: no check data (the old prose-only report, or the data gone), with an earlier clean mark on that head: no mark, the old one removed, reason named
mkrepo; prompt; stop delegate:checker
expect "K4 setup: the earlier mark exists" "$(git -C "$W" cat-file -e "HEAD:.relay/checks/$HEAD0.json"; echo $?)"
before="$(count)"; rm -f "$S/rep.json"
printf '# Check\nF1 MET\n## Verdict\nhead %s\nreviewed %s\nopen 0\nqueued 0\n' "$HEAD0" "$INIT" >"$S/rep.md"; touch -t $NEW "$S/rep.md"; stop delegate:checker
expect "K4 a commit removing the old mark" "$([ "$(count)" -eq $((before + 1)) ] && ! git -C "$W" cat-file -e "HEAD:.relay/checks/$HEAD0.json" 2>/dev/null; echo $?)"
expect "K4 the old prose verdict is not read: the message names the missing data" "$(has 'check mark not written for wt/t: the check data' "$msg" && has 'the checker must run relay check record check' "$msg"; echo $?)"
# K4b: the data is not JSON, or breaks the schema: no mark, the reason names it
mkrepo; prompt; report 0; printf 'not json' >"$S/rep.json"; touch -t $NEW "$S/rep.json"; before="$(count)"; stop delegate:checker
expect "K4b not JSON: no commit, reason named" "$([ "$(count)" -eq "$before" ] && has 'is not JSON' "$msg"; echo $?)"
report 0; jq '.open = "0"' "$S/rep.json" >"$S/rep2.json" && mv "$S/rep2.json" "$S/rep.json"; touch -t $NEW "$S/rep.json"; stop delegate:checker
expect "K4b open is a string: no commit, reason names open" "$([ "$(count)" -eq "$before" ] && has 'open must be a whole number' "$msg"; echo $?)"

# K4c: hand-made check data (the record command would refuse it) with F1 HIGH inside NOT MET and open 0: no mark, the reason names F1
mkrepo; prompt; report 0; jq '.findings[0].verdict = "NOT MET"' "$S/rep.json" >"$S/rep2.json" && mv "$S/rep2.json" "$S/rep.json"; touch -t $NEW "$S/rep.json"; before="$(count)"; stop delegate:checker
expect "K4c open below the verdicts: no commit, reason names F1" "$([ "$(count)" -eq "$before" ] && has 'open is 0 but 1 findings inside the change are not met: F1' "$msg"; echo $?)"

# K5: a report older than the transcript's first timestamp
mkrepo; prompt; report 0 $OLD; before="$(count)"; stop delegate:checker   # the data file is older than the start
expect "K5 old report: no commit" "$([ "$(count)" -eq "$before" ]; echo $?)"
expect "K5 reason named" "$(has 'older than the checker' "$msg"; echo $?)"

# K6: head not in the history; an abbreviated head is refused by the record script, and by the hook when the data was changed behind it
mkrepo; prompt; before="$(count)"
report 0 $NEW "$(printf 'ab%.0s' $(seq 20))"; stop delegate:checker
expect "K6 unknown head: no commit, reason named" "$([ "$(count)" -eq "$before" ] && has 'is not a commit of this worktree' "$msg"; echo $?)"
rec="$(report 0 $NEW "${HEAD0:0:7}" 2>&1)"
expect "K6 the record script refuses an abbreviated head and names it" "$(has 'head must be a full 40-character sha' "$rec"; echo $?)"
report 0; jq --arg h "${HEAD0:0:7}" '.head = $h' "$S/rep.json" >"$S/rep2.json" && mv "$S/rep2.json" "$S/rep.json"; touch -t $NEW "$S/rep.json"; stop delegate:checker
expect "K6 abbreviated head in the data: no commit, reason named" "$([ "$(count)" -eq "$before" ] && has 'head must be a full 40-character sha' "$msg"; echo $?)"

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

# K10: Check: a.json, b.json -> one review set holding both under their file names, a before b
mkrepo; review "$S/a.json" F1 "from a"; review "$S/b.json" F2 "question from b" question; prompt "\`$S/a.json\`, \`$S/b.json\`"
REVIEWS="$S/a.json $S/b.json" report 0; stop delegate:checker
expect "K10 the review set lists a.json then b.json" "$(git -C "$W" show "HEAD:.relay/checks/$INIT.review.json" | jq -e '[.reviews[].file]==["a.json","b.json"]' >/dev/null; echo $?)"
expect "K10 both findings are in the set, F1 inside and F2 a question" "$(git -C "$W" show "HEAD:.relay/checks/$INIT.review.json" | jq -e '[.reviews[].findings[]|[.id,.kind,.summary]]==[["F1","inside","from a"],["F2","question","question from b"]]' >/dev/null; echo $?)"
REVIEWS=""

# K11: a re-check of the same head after the review was recorded again: the stored review is replaced, the mark's open changes
mkrepo; prompt; report 1; stop delegate:checker
expect "K11 first mark: open 1" "$([ "$(git -C "$W" show "HEAD:.relay/checks/$HEAD0.json" | jq .verdict.open)" = 1 ]; echo $?)"
review "$S/f.json" F1 "changed after the owner's word"; report 0; stop delegate:checker
expect "K11 the stored review carries the new summary" "$(git -C "$W" show "HEAD:.relay/checks/$INIT.review.json" | jq -e '.reviews[0].findings[0].summary=="changed after the owner'"'"'s word"' >/dev/null; echo $?)"
expect "K11 the mark's open is 0" "$([ "$(git -C "$W" show "HEAD:.relay/checks/$HEAD0.json" | jq .verdict.open)" = 0 ]; echo $?)"

# K12: a prompt that is a brief file, not the check line: the report it names has no data; with no Report: label at all, the prompt is refused by name
mkrepo; before="$(count)"; rm -f "$S/rep.json"
jq -nc --arg t "Check the fix per the brief. Brief: $S/brief.md. Report: $S/rep.json." --arg ts "$START" '{type:"user",timestamp:$ts,message:{role:"user",content:$t}}' >"$S/agent.jsonl"
stop delegate:checker
expect "K12 no commit" "$([ "$(count)" -eq "$before" ]; echo $?)"
expect "K12 systemMessage names the missing check data" "$(has 'the check data' "$msg" && has 'cannot be read' "$msg"; echo $?)"
jq -nc --arg t "Check the fix per the brief. Brief: $S/brief.md." --arg ts "$START" '{type:"user",timestamp:$ts,message:{role:"user",content:$t}}' >"$S/agent.jsonl"
stop delegate:checker
expect "K12 no Report: label: names 'no Report: line'" "$(has 'no Report: line' "$msg"; echo $?)"

# K13: a workflow's checker: the first line is the harness's relayed request (no Report: label), the second the check prompt
mkrepo; prompt; before="$(count)"
harness() { jq -nc --arg t "[Workflow harness — user request] run the change for me" --arg ts "$START" '{type:"user",timestamp:$ts,message:{role:"user",content:$t}}'; }
harness >"$S/wf.jsonl"
cat "$S/wf.jsonl" "$S/agent.jsonl" >"$S/agent2.jsonl" && mv "$S/agent2.jsonl" "$S/agent.jsonl"
stop delegate:checker
expect "K13 workflow transcript: the mark commit" "$([ "$(count)" -eq $((before + 1)) ] && git -C "$W" cat-file -e "HEAD:.relay/checks/$HEAD0.json"; echo $?)"
# K13b: the harness line and no Report: label in any leading user entry: no mark, named
mkrepo; before="$(count)"
{ harness; jq -nc --arg t "Check the fix per the brief." --arg ts "$START" '{type:"user",timestamp:$ts,message:{role:"user",content:$t}}'; } >"$S/agent.jsonl"
stop delegate:checker
expect "K13b no label in the leading user entries: no commit, names 'no Report: line'" "$([ "$(count)" -eq "$before" ] && has 'no Report: line' "$msg"; echo $?)"
# K13c: a Report: label after the first assistant entry is not the prompt
{ harness; jq -nc '{type:"assistant",message:{role:"assistant",content:"ok"}}'; jq -nc --arg t "Report: $S/rep.json." --arg ts "$START" '{type:"user",timestamp:$ts,message:{role:"user",content:$t}}'; } >"$S/agent.jsonl"
stop delegate:checker
expect "K13c a label after an assistant entry is not read" "$([ "$(count)" -eq "$before" ] && has 'no Report: line' "$msg"; echo $?)"
# K13d: the start time is the prompt entry's, not the harness line's: harness 09:00, prompt 10:00 (START), report 09:30 -> older
mkrepo; prompt; before="$(count)"; report 0; touch -t 202610220930 "$S/rep.json"
{ jq -nc --arg t "[Workflow harness — user request] run the change for me" --arg ts "2026-10-22T09:00:00.000Z" '{type:"user",timestamp:$ts,message:{role:"user",content:$t}}'; cat "$S/agent.jsonl"; } >"$S/agent2.jsonl" && mv "$S/agent2.jsonl" "$S/agent.jsonl"
stop delegate:checker
expect "K13d report between harness line and prompt: no commit, 'older'" "$([ "$(count)" -eq "$before" ] && has 'older' "$msg"; echo $?)"
# K13e: the harness line repeats the owner's words with a Report: label; the checker's prompt (the last label) wins
mkrepo; prompt; before="$(count)"
{ jq -nc --arg t "[Workflow harness — user request] look at Report: $S/old-check.json" --arg ts "$START" '{type:"user",timestamp:$ts,message:{role:"user",content:$t}}'; cat "$S/agent.jsonl"; } >"$S/agent2.jsonl" && mv "$S/agent2.jsonl" "$S/agent.jsonl"
stop delegate:checker
expect "K13e the last Report: label among leading entries: the mark commit" "$([ "$(count)" -eq $((before + 1)) ] && git -C "$W" cat-file -e "HEAD:.relay/checks/$HEAD0.json"; echo $?)"

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
g allow "G6 cat a stored review" Bash "$GW" command "cat .relay/checks/x.review.json"
g allow "G6 jq .verdict" Bash "$GW" command "jq .verdict .relay/checks/X.json"
g allow "G6 inline python that only reads" Bash "$GW" command "python3 -c \"import json;print(json.load(open('.relay/checks/X.json'))['verdict'])\""
g allow "G6 F8 inline python that reads and compares with >" Bash "$GW" command "python3 -c \"import json; print(json.load(open('.relay/checks/a.json'))['verdict']['open'] > 0)\""
g allow "G6 F8 inline python that reads and prints with sys.stdout.write" Bash "$GW" command "python3 -c \"import sys; sys.stdout.write(open('.relay/checks/a.json').read())\""
g block "G3 F8 shutil.rmtree of .relay/checks" Bash "$GW" command "python3 -c \"import shutil; shutil.rmtree('.relay/checks')\""
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
