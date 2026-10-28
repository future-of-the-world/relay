#!/usr/bin/env bash
# Cleanup after the allowed merge (hooks/merge.sh -> merge.py), cases T1-T14, T16, T18-T20 of
# docs/plans/review-gate.md section 12.1 and the merge gate T15 (a)-(p) of 12.2, on throwaway repositories under a temp dir (temp HOME).
#   plugins/relay/tests/merge.test.sh
set -uo pipefail
here="$(cd "$(dirname "$0")" && pwd -P)"
hook="$here/../hooks/merge.sh"
unset CLAUDE_PROJECT_DIR
tmp="$(cd "$(mktemp -d)" && pwd -P)"
trap 'rm -rf "$tmp"' EXIT
export HOME="$tmp/home"; mkdir -p "$HOME"
export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_SYSTEM=/dev/null GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@t GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@t
fails=0; n=0

ok() { echo "ok    $1"; }
bad() { echo "FAIL  $1"; fails=$((fails + 1)); }
expect() { # <desc> <condition exit code 0 = true>
  if [ "$2" -eq 0 ]; then ok "$1"; else bad "$1"; fi
}
has() { case "$2" in *"$1"*) return 0 ;; *) return 1 ;; esac; }

# mkrepo <name> [norelay]: M = main checkout on master; a worktree .worktrees/t on wt/t with one commit
mkrepo() {
  n=$((n + 1)); M="$tmp/r$n"
  mkdir -p "$M" && cd "$M" && git init -q -b master . || exit 1
  printf '.ci/\n' >.gitignore
  [ "${1:-}" = norelay ] || { mkdir -p .relay && echo x >.relay/README.md; }
  git add -A && git commit -q -m init
  git worktree add -q .worktrees/t -b wt/t
  ( cd .worktrees/t && echo a >a.txt && git add a.txt && git commit -q -m work )
  W="$M/.worktrees/t"
}
# run_hook <command> [cwd] [session_id] -> $out (hook stdout), $rc
run_hook() {
  out="$(jq -n --arg c "$1" --arg cwd "${2:-$M}" --arg s "${3:-s0}" \
    '{hook_event_name:"PostToolUse", tool_name:"Bash", cwd:$cwd, session_id:$s, tool_input:{command:$c}}' | "$hook" 2>&1)"; rc=$?
  ctx="$(jq -r '.hookSpecificOutput.additionalContext // empty' <<<"$out" 2>/dev/null)"
}
merge_and_hook() { git -C "$M" merge -q --ff-only wt/t; run_hook "git merge --ff-only wt/t" "${1:-$M}" "${2:-s0}"; }
gone() { [ ! -e "$M/.worktrees/t" ] && ! git -C "$M" show-ref --verify --quiet refs/heads/wt/t; }

# T1 + T3 control: merge in main, clean
mkrepo; merge_and_hook
expect "T1 removed folder and branch" "$(gone; echo $?)"
expect "T1 message 'Removed .worktrees/t and branch wt/t (merged)'" "$(has 'Removed .worktrees/t and branch wt/t (merged)' "$ctx"; echo $?)"

# T2: git -C <main> merge from elsewhere
mkrepo; mkdir "$tmp/elsewhere"; git -C "$M" merge -q --ff-only wt/t
run_hook "git -C $M merge --ff-only wt/t" "$tmp/elsewhere"
expect "T2 -C from elsewhere: removed" "$(gone; echo $?)"
expect "T2 message" "$(has 'Removed .worktrees/t' "$ctx"; echo $?)"

# T3: no .relay/ -> kept, silent; then commit the folder and the same input -> removed
mkrepo norelay; merge_and_hook
expect "T3 no .relay/: kept" "$([ -d "$M/.worktrees/t" ] && git -C "$M" show-ref --verify --quiet refs/heads/wt/t; echo $?)"
expect "T3 no .relay/: silent, exit 0" "$([ -z "$out" ] && [ "$rc" -eq 0 ]; echo $?)"
( cd "$M" && mkdir .relay && echo x >.relay/README.md && git add .relay && git commit -q -m relay )
run_hook "git merge --ff-only wt/t"
expect "T3 with .relay/: removed" "$(gone; echo $?)"

# T4: the hook's cwd is the worktree: kept and locked with the session id
mkrepo; git -C "$M" merge -q --ff-only wt/t; run_hook "git -C $M merge --ff-only wt/t" "$W" s1
expect "T4 kept" "$([ -d "$W" ]; echo $?)"
expect "T4 message 'this session runs in it'" "$(has 'this session runs in it' "$ctx"; echo $?)"
lock="$(git -C "$M" worktree list --porcelain | grep -A0 '^locked' | head -1)"
expect "T4 locked with reason 'session s1'" "$([ "$lock" = "locked session s1" ]; echo $?)"
# the same through CLAUDE_PROJECT_DIR
mkrepo; git -C "$M" merge -q --ff-only wt/t
out="$(jq -n --arg cwd "$M" '{hook_event_name:"PostToolUse",tool_name:"Bash",cwd:$cwd,session_id:"s2",tool_input:{command:"git merge --ff-only wt/t"}}' | CLAUDE_PROJECT_DIR="$W" "$hook")"
expect "T4 CLAUDE_PROJECT_DIR in the worktree: locked" "$(git -C "$M" worktree list --porcelain | grep -qx 'locked session s2'; echo $?)"

# T5: fresh branch, no commit: kept; then master gains a commit and wt/n fast-forwards to it
mkrepo; git -C "$M" worktree add -q .worktrees/n -b wt/n
run_hook "git merge --ff-only wt/n"
expect "T5 fresh: kept with the reason" "$(has 'wt/n: it has no commits of its own' "$ctx"; echo $?)"
( cd "$M" && git commit -q --allow-empty -m queue ) ; git -C "$M/.worktrees/n" merge -q --ff-only master
run_hook "git merge --ff-only wt/n"
expect "T5 fast-forwarded to master: kept with the reason" "$(has 'wt/n: it has no commits of its own' "$ctx"; echo $?)"
expect "T5 folder and branch still there" "$([ -d "$M/.worktrees/n" ] && git -C "$M" show-ref --verify --quiet refs/heads/wt/n; echo $?)"

# T6: tracked file changed in the worktree
mkrepo; git -C "$M" merge -q --ff-only wt/t; echo changed >>"$W/a.txt"; run_hook "git merge --ff-only wt/t"
expect "T6 kept, file named" "$(has 'a.txt' "$ctx"; echo $?)"
expect "T6 worktree and branch kept" "$([ -d "$W" ] && git -C "$M" show-ref --verify --quiet refs/heads/wt/t; echo $?)"

# T7: untracked file
mkrepo; git -C "$M" merge -q --ff-only wt/t; echo u >"$W/new.txt"; run_hook "git merge --ff-only wt/t"
expect "T7 kept, file named" "$(has 'kept .worktrees/t' "$ctx" && has 'new.txt' "$ctx"; echo $?)"
expect "T7 folder kept" "$([ -d "$W" ]; echo $?)"

# T8: locked worktree
mkrepo; git -C "$M" worktree lock --reason "other" "$W"; merge_and_hook
expect "T8 kept, 'locked'" "$(has 'locked' "$ctx" && [ -d "$W" ]; echo $?)"

# T9: merge refused (not a fast-forward): nothing removed; the positive control is T1
mkrepo; ( cd "$M" && git commit -q --allow-empty -m diverge ); git -C "$M" merge -q --ff-only wt/t 2>/dev/null
run_hook "git merge --ff-only wt/t"
expect "T9 refused merge: nothing removed, silent" "$([ -d "$W" ] && git -C "$M" show-ref --verify --quiet refs/heads/wt/t && [ -z "$out" ]; echo $?)"
git -C "$M" merge -q --no-edit wt/t; git -C "$W" merge -q --no-edit master; git -C "$M" merge -q --ff-only wt/t
run_hook "git merge --ff-only wt/t"
expect "T9 control: once merged the same input removes" "$(gone; echo $?)"

# T9b: not the allowed merge (no --ff-only): the hook does not act
mkrepo; git -C "$M" merge -q --ff-only wt/t; run_hook "git merge wt/t"
expect "T9b plain merge: silent, nothing removed" "$([ -z "$out" ] && [ -d "$W" ]; echo $?)"

# T10: a read-only git command, and a merge run inside a worktree
mkrepo; git -C "$M" merge -q --ff-only wt/t
run_hook "git -C $W log"
expect "T10 git log: silent, nothing removed" "$([ -z "$out" ] && [ -d "$W" ]; echo $?)"
git -C "$M" worktree add -q .worktrees/w -b wt/w; ( cd "$M/.worktrees/w" && git commit -q --allow-empty -m c && git merge -q --ff-only wt/t 2>/dev/null )
run_hook "git -C $M/.worktrees/w merge --ff-only wt/t" "$M/.worktrees/w"
expect "T10 merge inside a worktree: silent, nothing removed" "$([ -z "$out" ] && [ -d "$W" ]; echo $?)"
run_hook "git merge --ff-only wt/t"
expect "T10 control: the merge in main removes" "$(gone; echo $?)"

# T11: branch with no worktree
mkrepo; git -C "$M" worktree remove --force "$W"; git -C "$M" merge -q --ff-only wt/t; run_hook "git merge --ff-only wt/t"
expect "T11 branch deleted" "$(! git -C "$M" show-ref --verify --quiet refs/heads/wt/t; echo $?)"
expect "T11 message names the branch only" "$(has 'Removed branch wt/t (merged)' "$ctx"; echo $?)"

# T12: two merges joined by &&; cd <main> && merge
mkrepo; git -C "$M" worktree add -q .worktrees/u -b wt/u; ( cd "$M/.worktrees/u" && echo b >b.txt && git add b.txt && git commit -q -m w2 )
git -C "$M" merge -q --ff-only wt/t; git -C "$M" merge -q --no-edit wt/u
run_hook "git merge --ff-only wt/t && git merge --ff-only wt/u"
expect "T12 both removed (two lines)" "$([ ! -e "$M/.worktrees/t" ] && [ ! -e "$M/.worktrees/u" ] && [ "$(wc -l <<<"$ctx" | tr -d ' ')" = 2 ]; echo $?)"
mkrepo; git -C "$M" merge -q --ff-only wt/t; run_hook "cd $M && git merge --ff-only wt/t" "$tmp"
expect "T12 cd <main> && merge handled" "$(gone; echo $?)"

# T14: an ignored file under .ci/
mkrepo; mkdir "$W/.ci"; echo log >"$W/.ci/ci.log"; merge_and_hook
expect "T14 removed, message names .ci/" "$(gone && has 'with 1 ignored path gone: .ci/' "$ctx"; echo $?)"

# Notices: a range touching an agent text; and rules/ in a repo with bin/relay
mkrepo; mkdir -p "$W/plugins/p/agents" "$W/rules" && echo x >"$W/plugins/p/agents/a.md" && echo y >"$W/rules/r.md"
git -C "$W" add -A && git -C "$W" commit -q -m texts; mkdir -p "$M/bin"; : >"$M/bin/relay"; git -C "$M" add bin; git -C "$M" commit -q -m relay
git -C "$W" merge -q --no-edit master; merge_and_hook
expect "N1 agent-text and sync notices" "$(has 'open sessions keep the old texts' "$ctx" && has 'once the wave'"'"'s paid run is green' "$ctx"; echo $?)"

# T18: default branch (relay_git.default_branch) through the hook: unknown default branch = silent
mkdefault() { # <dir> <branch>: a repo whose only branch is <branch>, with .relay/ and a worktree on wt/t
  D="$tmp/$1"; mkdir -p "$D" && cd "$D" && git init -q -b "$2" . && mkdir .relay && echo x >.relay/README.md && git add -A && git commit -q -m init
  git worktree add -q .worktrees/t -b wt/t; ( cd .worktrees/t && echo a >a.txt && git add a.txt && git commit -q -m work ); git merge -q --ff-only wt/t
}
dhook() { out="$(jq -n --arg cwd "$D" '{hook_event_name:"PostToolUse",tool_name:"Bash",cwd:$cwd,session_id:"s0",tool_input:{command:"git merge --ff-only wt/t"}}' | "$hook" 2>&1)"; rc=$?; }
mkdefault dev develop; dhook
expect "T18 only develop, no kit.toml: hook silent, nothing removed" "$([ -z "$out" ] && [ "$rc" -eq 0 ] && [ -d "$D/.worktrees/t" ]; echo $?)"
mkdir "$D/.claude"; printf '[project]\ndefault_branch = "develop"\n' >"$D/.claude/kit.toml"; dhook
expect "T18 kit.toml default_branch develop: hook cleans up" "$(has 'Removed .worktrees/t' "$out" && [ ! -e "$D/.worktrees/t" ]; echo $?)"
mkdefault wtb develop; mkdir "$D/.claude"; printf '[project]\ndefault_branch = "wt/x"\n' >"$D/.claude/kit.toml"; dhook
expect "T18 kit.toml naming wt/x ignored: silent" "$([ -z "$out" ] && [ -d "$D/.worktrees/t" ]; echo $?)"

# ---- B2: guard fallback (T13), session-start sweep (T3 control, T16, T20), SessionEnd (T19) ----
guard="$here/../hooks/guard-main.sh"
guard_run() { # <cwd> <command> <CLAUDE_PROJECT_DIR> -> $out, $rc
  out="$(jq -n --arg cwd "$1" --arg c "$2" '{tool_name:"Bash",cwd:$cwd,tool_input:{command:$c}}' | CLAUDE_PROJECT_DIR="${3-}" "$guard" 2>&1)"; rc=$?
}
sweep_hook() { # <cwd> <session_id> -> $out, $ctx, $rc
  out="$(jq -n --arg cwd "$1" --arg s "$2" '{hook_event_name:"SessionStart",cwd:$cwd,session_id:$s}' | python3 -I "$here/../hooks/merge.py" sweep 2>&1)"; rc=$?
  ctx="$(jq -r '.hookSpecificOutput.additionalContext // empty' <<<"$out" 2>/dev/null)"
}
end_hook() { # <session_id> [cwd]
  out="$(jq -n --arg cwd "${2:-$M}" --arg s "$1" '{hook_event_name:"SessionEnd",cwd:$cwd,session_id:$s}' | python3 -I "$here/../hooks/merge.py" end 2>&1)"; rc=$?
}
wait_for() { # <timeout s> <command...>: poll for the detached child's effect; at most <timeout> seconds
  local limit=$(( $1 * 10 )) i=0; shift
  while [ "$i" -lt "$limit" ]; do "$@" && return 0; i=$((i + 1)); python3 -c 'import time; time.sleep(0.1)'; done; return 1
}
absent() { [ ! -e "$1" ]; }
nobranch() { ! git -C "$M" show-ref --verify --quiet "refs/heads/$1"; }

# T13: a deleted CLAUDE_PROJECT_DIR falls back to cwd (main): `touch a` is refused; before, it was allowed
mkrepo; guard_run "$M" "touch a" "$tmp/deleted-folder"
expect "T13 deleted CLAUDE_PROJECT_DIR, cwd = main: touch refused" "$([ "$rc" -eq 2 ]; echo $?)"
guard_run "$W" "touch a" "$tmp/deleted-folder"
expect "T13 control: cwd a worktree: the same fallback allows the write" "$([ "$rc" -eq 0 ]; echo $?)"
guard_run "$tmp/none-1" "touch a" "$tmp/none-2"
expect "T13 neither folder exists: refused, names the folder" "$([ "$rc" -eq 2 ] && has "$tmp/none-2 no longer exists" "$out"; echo $?)"
mkdir "$tmp/norepo"; guard_run "$tmp/norepo" "touch a" ""
expect "T13 outside any repository: allowed" "$([ "$rc" -eq 0 ]; echo $?)"

# T3 control (sweep): no .relay/ -> silent and kept; once the folder is committed the same sweep removes
mkrepo norelay; git -C "$M" merge -q --ff-only wt/t; sweep_hook "$M" s0
expect "T3 sweep, no .relay/: silent, kept" "$([ -z "$out" ] && [ "$rc" -eq 0 ] && [ -d "$W" ]; echo $?)"
( cd "$M" && mkdir .relay && echo x >.relay/README.md && git add .relay && git commit -q -m relay )
sweep_hook "$M" s0
expect "T3 sweep with .relay/: line 'Removing 1 merged worktree: .worktrees/t (wt/t)'" "$(has 'Removing 1 merged worktree: .worktrees/t (wt/t)' "$ctx"; echo $?)"
expect "T3 sweep with .relay/: removed (detached child)" "$(wait_for 10 absent "$W"; echo $?)"

# T16: one merged, one unmerged, the session's own merged, one merged and locked by another session
mkrepo
for x in u own locked; do
  git -C "$M" worktree add -q .worktrees/$x -b wt/$x; ( cd "$M/.worktrees/$x" && echo $x >$x.txt && git add $x.txt && git commit -q -m $x )
done
git -C "$M" merge -q --ff-only wt/t; git -C "$M" merge -q --no-edit wt/own; git -C "$M" merge -q --no-edit wt/locked
git -C "$M" worktree lock --reason "session s9" "$M/.worktrees/locked"
sweep_hook "$M/.worktrees/own" s1
expect "T16 line names only .worktrees/t" "$([ "$ctx" = "Removing 1 merged worktree: .worktrees/t (wt/t)" ]; echo $?)"
expect "T16 the merged one is removed" "$(wait_for 10 absent "$W"; echo $?)"
expect "T16 its branch is gone" "$(wait_for 10 nobranch wt/t; echo $?)"
expect "T16 unmerged, own and locked-by-s9 kept" "$([ -d "$M/.worktrees/u" ] && [ -d "$M/.worktrees/own" ] && [ -d "$M/.worktrees/locked" ]; echo $?)"
expect "T16 s9's lock still there" "$(git -C "$M" worktree list --porcelain | grep -qx 'locked session s9'; echo $?)"

# T16b: locked with this very session's id: started inside it, kept and still locked; started elsewhere, removed
mkrepo; git -C "$M" merge -q --ff-only wt/t; git -C "$M" worktree lock --reason "session s1" "$W"
sweep_hook "$W" s1
expect "T16b started inside its own locked worktree: kept, still locked" "$([ -d "$W" ] && git -C "$M" worktree list --porcelain | grep -qx 'locked session s1'; echo $?)"
sweep_hook "$M" s1
expect "T16b same session started elsewhere: unlocked and removed" "$(wait_for 10 absent "$W"; echo $?)"

# T16c (F4): session s1 starts inside .worktrees/t (not merged yet) and locks it; s2's merge and sweep from main keep it; s1's end removes it
mkrepo; sweep_hook "$W" s1
expect "T16c a session started inside a worktree locks it" "$(git -C "$M" worktree list --porcelain | grep -qx 'locked session s1'; echo $?)"
git -C "$M" merge -q --ff-only wt/t; run_hook "git -C $M merge --ff-only wt/t" "$M" s2
expect "T16c another session's merge keeps it, message names the lock" "$([ -d "$W" ] && has 'kept .worktrees/t: locked (session s1)' "$ctx"; echo $?)"
sweep_hook "$M" s2
expect "T16c another session's sweep keeps it" "$([ -d "$W" ]; echo $?)"
end_hook s1 "$W"
expect "T16c s1's end removes it" "$(wait_for 10 absent "$W"; echo $?)"
# no session inside: the merge removes it as before (T1); a session started in main does not lock it (T16 covers the sweep)

# T19: SessionEnd for s1 after T4: unlocked and removed; a worktree locked by s9 kept
mkrepo; git -C "$M" worktree add -q .worktrees/o -b wt/o; ( cd "$M/.worktrees/o" && echo o >o.txt && git add o.txt && git commit -q -m o )
git -C "$M" merge -q --ff-only wt/t; git -C "$M" merge -q --no-edit wt/o
run_hook "git -C $M merge --ff-only wt/t" "$W" s1; git -C "$M" worktree lock --reason "session s9" "$M/.worktrees/o"
expect "T19 before: locked by s1" "$(git -C "$M" worktree list --porcelain | grep -qx 'locked session s1'; echo $?)"
end_hook s1 "$W"
expect "T19 s1's worktree removed" "$(wait_for 10 absent "$W"; echo $?)"
expect "T19 s9's worktree kept and locked" "$([ -d "$M/.worktrees/o" ] && git -C "$M" worktree list --porcelain | grep -qx 'locked session s9'; echo $?)"

# T20: a removal slowed past 5 s (a git wrapper) still completes; the next sweep is quiet. A failing one is named next time.
realgit="$(command -v git)"; wrap="$tmp/wrap"; mkdir -p "$wrap"
cat >"$wrap/git" <<WRAPEOF
#!/usr/bin/env bash
case " \$* " in *" worktree remove "*) case "\${WRAP_MODE:-}" in slow) sleep 7 ;; fail) echo "fatal: simulated refusal" >&2; exit 1 ;; esac ;; esac
exec "$realgit" "\$@"
WRAPEOF
chmod +x "$wrap/git"
mkrepo; git -C "$M" merge -q --ff-only wt/t
# the hook runs in its own process group, which is killed (as the 5 s timeout would) once the hook has returned
cat >"$tmp/cut.py" <<'CUTEOF'
import json, os, signal, subprocess, sys
p = subprocess.Popen([sys.executable, "-I", sys.argv[1], "sweep"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, start_new_session=True)
out, _ = p.communicate(json.dumps({"hook_event_name": "SessionStart", "cwd": sys.argv[2], "session_id": "s0"}))
try:
    os.killpg(p.pid, signal.SIGKILL)
except OSError:
    pass
print(out)
CUTEOF
( export PATH="$wrap:$PATH" WRAP_MODE=slow; python3 -I "$tmp/cut.py" "$here/../hooks/merge.py" "$M" | jq -r '.hookSpecificOutput.additionalContext // empty' >"$tmp/t20.ctx" )
expect "T20 slow: the sweep returns while the folder is still there" "$([ -d "$W" ] && has 'Removing 1 merged worktree' "$(cat "$tmp/t20.ctx")"; echo $?)"
expect "T20 slow: the removal still completes (folder and branch)" "$(wait_for 20 absent "$W" && wait_for 20 nobranch wt/t; echo $?)"
sweep_hook "$M" s0
expect "T20 slow: the next sweep prints no failure" "$([ -z "$out" ]; echo $?)"
mkrepo; git -C "$M" merge -q --ff-only wt/t
( export PATH="$wrap:$PATH" WRAP_MODE=fail; sweep_hook "$M" s0 )
cleanlog="$(git -C "$M" rev-parse --path-format=absolute --git-common-dir)/relay-cleanup.log"
wait_for 10 test -s "$cleanlog"
sweep_hook "$M" s0
expect "T20 failing: the next sweep names the failure from the log" "$(has 'could not remove .worktrees/t: simulated refusal' "$ctx"; echo $?)"
sweep_hook "$M" s0
expect "T20 failing: the failure is named once (log cleared)" "$(has 'simulated refusal' "$ctx"; [ $? -ne 0 ]; echo $?)"

# ---- B5: the merge gate (PreToolUse), T15 (a)-(p) of docs/plans/review-gate.md section 12.2 ----
LIB="$here/../lib"; RELAY="$here/../../../bin/relay"; CHECKMARK="$here/../hooks/check-mark.py"
printf '#!/bin/sh\necho "ci: fixture ok"\nexit "${FIXGATE_EXIT:-0}"\n' >"$tmp/fixgate"; chmod +x "$tmp/fixgate"

# qjson <state> <test>: a queue item file as lib/relay_queue.py writes it, with dated events (a fix item named x; the hook reads it through relay_queue).
# taken: taken_at and taken_by; done: also closed_at and the test; dropped: dropped_at and why, never taken
qjson() {
  local ev='"taken_at": "2026-10-22T10:00:00Z", "taken_by": "wt/t", "closed_at": null, "test": null, "dropped_at": null, "dropped_why": null'
  [ "$1" = done ] && ev='"taken_at": "2026-10-22T10:00:00Z", "taken_by": "wt/t", "closed_at": "2026-10-22T12:00:00Z", "test": "'"$2"'", "dropped_at": null, "dropped_why": null'
  [ "$1" = dropped ] && ev='"taken_at": null, "taken_by": null, "closed_at": null, "test": null, "dropped_at": "2026-10-22T12:00:00Z", "dropped_why": ["not wanted"]'
  printf '{\n  "kind": "fix",\n  "ip": 5,\n  "time": 10,\n  "found_at": "2026-10-22T08:00:00Z",\n  "found_in": "fixture",\n  "title": "Item x loses a row",\n  "what": ["x loses a row"],\n  "why": ["a row is lost"],\n  "failing_case": ["y"],\n  %s\n}' "$ev"
}
# m15 [norelay]: master holds lib/a.py (v1), bin/x (six lines), .relay/queue/x.json (a taken fix item, JSON as relay_queue writes it), a kit.toml whose
# gate is the fixture gate; M = main checkout, W = .worktrees/t on wt/t (no commit yet); BASE = master's head
m15() {
  n=$((n + 1)); M="$tmp/g$n"; S="$tmp/gs$n"; mkdir -p "$M/lib" "$M/bin" "$M/.claude" "$S"; cd "$M" && git init -q -b master . || exit 1
  printf '.ci/\n.worktrees/\n' >.gitignore; printf 'v1\n' >lib/a.py; printf '1\n2\n3\n4\n5\n6\n' >bin/x
  printf '[gate]\nci = "%s"\n' "$tmp/fixgate" >.claude/kit.toml
  [ "${1:-}" = norelay ] || { mkdir -p .relay/queue && echo x >.relay/README.md
    qjson taken "" >.relay/queue/x.json; }
  git add -A && git commit -q -m init; BASE="$(git rev-parse HEAD)"
  git worktree add -q .worktrees/t -b wt/t; W="$M/.worktrees/t"
}
commit() { # <message> <file>=<content>...: write and commit in W
  local msg="$1" kv; shift
  for kv in "$@"; do mkdir -p "$W/$(dirname "${kv%%=*}")"; printf '%b' "${kv#*=}" >"$W/${kv%%=*}"; done
  git -C "$W" add -A && git -C "$W" commit -q -m "$msg"
}
head_of() { git -C "$W" rev-parse HEAD; }
# mark [open] / gate [exit]: the mark of the checked commit $X and the gate log of W's head, written and committed the way the hook and relay gate do
mark() { python3 -I - "$LIB" "$W" "$X" "${1:-0}" <<'PY'
import sys
sys.path.insert(0, sys.argv[1]); import relay_marks as m
w, c, o = sys.argv[2], sys.argv[3], int(sys.argv[4])
import json
q1 = {"id": "Q1", "path": "lib/a.py", "line": 1, "severity": "HIGH", "rank": "high", "kind": "inside", "summary": "Item x loses a row", "failing_case": ["y"], "details": ["a row is lost"], "pass_cases": [],
      "source": "queue", "since": c, "verdict": "MET", "reason": ["tests/t.sh:1"]}
f1 = dict(q1, id="F1", source="a.json", verdict="NOT MET", summary="a finding")
record = {"schema": 2, "type": "check", "head": c, "branch": "wt/t", "item": "x", "gate": None, "scope": [], "notes": [], "findings": [q1] + ([f1] * o)[:1]}
m.put(w, c, {"schema": 2, "commit": c, "verdict": {"open": o, "queued": 0}, "check": c + ".check.json", "gate": None, "time": "2026-10-22T10:00:00Z"},
      {c + ".check.json": json.dumps(record) + "\n"})
PY
}
gate() { python3 -I - "$LIB" "$W" "$(head_of)" "${1:-0}" <<'PY'
import os, sys
sys.path.insert(0, sys.argv[1]); import relay_marks as m
w, c, e = sys.argv[2], sys.argv[3], sys.argv[4]
path = os.path.join(w, ".relay", "checks", c + ".gate.log")
os.makedirs(os.path.dirname(path), exist_ok=True)
open(path, "w").write("head %s\ncmd fixture\nci: fixture\nexit %s\n" % (c, e))
m.commit_file(w, path, "relay: gate of " + c)
PY
}
# green: the case's start: a commit touching lib/a.py, a green gate log and a clean mark for it
green() { commit "fix a" "lib/a.py=v2\n"; X="$(head_of)"; gate 0; mark 0; }
# pre <command> [cwd] -> $out (stderr and stdout of the hook), $rc
pre() {
  out="$(jq -n --arg c "$1" --arg cwd "${2:-$M}" '{hook_event_name:"PreToolUse", tool_name:"Bash", cwd:$cwd, session_id:"s0", tool_input:{command:$c}}' | "$hook" 2>&1)"; rc=$?
}
MERGE="git merge --ff-only wt/t"
refused() { [ "$rc" -eq 2 ] && has "$1" "$out"; }
allowed() { [ "$rc" -eq 0 ] && [ -z "$out" ]; }

# (a) no mark
m15; commit "fix a" "lib/a.py=v2\n"; gate 0; pre "$MERGE"
expect "T15a no mark: refused" "$(refused 'no check mark for wt/t'; echo $?)"
# (b) mark open 2
m15; commit "fix a" "lib/a.py=v2\n"; X="$(head_of)"; gate 0; mark 2; pre "$MERGE"
expect "T15b open 2: refused" "$(refused 'left 2 things open'; echo $?)"
expect "T15b names the report" "$(has ".relay/checks/$X.check.json" "$out"; echo $?)"
# (c) clean mark and green gate; the merge itself then succeeds
m15; green; pre "$MERGE"
expect "T15c clean mark and green gate: allowed, silent" "$(allowed; echo $?)"
expect "T15c the real fast-forward succeeds" "$(git -C "$M" merge -q --ff-only wt/t; echo $?)"
# (d) a handover commit after
m15; green; commit "handover" "docs/handover.md=state\n"; pre "$MERGE"
expect "T15d handover commit after: allowed" "$(allowed; echo $?)"
# (e) a lib/a.py commit after
m15; green; commit "more" "lib/a.py=v3\n"; pre "$MERGE"
expect "T15e code after the check: refused" "$(refused "after the check of $X, wt/t changed lib/a.py"; echo $?)"
# (f) only inert files, no mark, no gate
m15; commit "handover" "docs/handover.md=state\n"; pre "$MERGE"
expect "T15f only inert: allowed" "$(allowed; echo $?)"
# (g) no .relay/: silent; positive control (a)
m15 norelay; commit "fix a" "lib/a.py=v2\n"; pre "$MERGE"
expect "T15g no .relay/: allowed, silent" "$(allowed; echo $?)"
m15; commit "fix a" "lib/a.py=v2\n"; pre "$MERGE"
expect "T15g control with .relay/: refused" "$(refused 'no check mark'; echo $?)"
# (h) M-A: a queue commit lands on master; behind, then taken, then allowed
m15; green; echo q >"$M/.relay/queue/y.md"; git -C "$M" add -A; git -C "$M" commit -q -m "queue y"
pre "$MERGE"
expect "T15h behind master by 1 commit: refused" "$(refused 'wt/t is behind master by 1 commit; take master first: git -C .worktrees/t merge --no-edit master'; echo $?)"
git -C "$W" merge -q --no-edit master; pre "$MERGE"
expect "T15h after taking master: allowed" "$(allowed; echo $?)"
expect "T15h and the real fast-forward succeeds" "$(git -C "$M" merge -q --ff-only wt/t; echo $?)"
# (i) M-A: master gains lib/b.py; the branch takes it; refused until relay gate is green
m15; green; echo b >"$M/lib/b.py"; git -C "$M" add -A; git -C "$M" commit -q -m "b"; git -C "$W" merge -q --no-edit master
pre "$MERGE"
expect "T15i code came in: refused, names lib/b.py" "$(refused 'code changed since: lib/b.py; run relay gate in .worktrees/t'; echo $?)"
"$RELAY" gate -C "$W" >"$tmp/gate.out" 2>&1; grc=$?
expect "T15i relay gate (fixture gate) is green" "$([ "$grc" -eq 0 ]; echo $?)"
pre "$MERGE"
expect "T15i after the gate: allowed with the same mark" "$(allowed; echo $?)"
# (j) the checked fix reverted to master's content: still the branch's own file. The fix also adds lib/c.py, so the
# branch still differs from master after the revert (a net-empty branch would be all inert, step 3, and rightly allowed)
m15; commit "fix a and c" "lib/a.py=v2\n" "lib/c.py=c\n"; X="$(head_of)"; gate 0; mark 0; commit "revert" "lib/a.py=v1\n"; pre "$MERGE"
expect "T15j reverted checked fix: refused, changed lib/a.py" "$(refused 'changed lib/a.py'; echo $?)"
# (k) both sides changed bin/x, git combined them: refused; the check (the script writes M1 for bin/x itself) and a green gate allow it
m15; commit "fix a and x" "lib/a.py=v2\n" "bin/x=1a\n2\n3\n4\n5\n6\n"; BEFORE="$(head_of)"; X="$BEFORE"; gate 0; mark 0
printf '1\n2\n3\n4\n5\n6a\n' >"$M/bin/x"; git -C "$M" commit -q -am "x end"; git -C "$W" merge -q --no-edit master
pre "$MERGE"
expect "T15k combined file: refused, changed bin/x" "$(refused 'changed bin/x'; echo $?)"
cat >"$S/review.toml" <<EOF
report = "$S/f.json"
reviewed = "$BEFORE"
base = "master"
[[finding]]
id = "F1"
path = "bin/x"
line = 1
severity = "MEDIUM"
kind = "inside"
summary = "combined with master's change by the merge"
failing_case = "the gate fails or the merge does not apply"
EOF
"$RELAY" check record review --input "$S/review.toml" >/dev/null
HEADG="$(head_of)"; "$RELAY" gate -C "$W" >"$tmp/gate.out" 2>&1
HEADK="$(head_of)"
cat >"$S/check.toml" <<EOF
report = "$S/rep.json"
head = "$HEADK"
worktree = "$W"
gate = "$HEADG.gate.log"
review = ["$S/f.json"]
[[status]]
id = "Q1"
verdict = "MET"
[[status]]
id = "F1"
verdict = "MET"
[[status]]
id = "M1"
verdict = "MET"
EOF
"$RELAY" check record check --input "$S/check.toml" >/dev/null
jq -nc --arg t "Check: \`$S/f.json\`. Fixes: \`none\`. Worktree: \`$W\`. Check command: \`bin/ci --quick\`. Gate: \`none\`. Report: \`$S/rep.json\`." \
  '{type:"user", timestamp:"2026-10-22T10:00:00.000Z", message:{role:"user", content:$t}}' >"$S/agent.jsonl"
jq -n --arg cwd "$M" --arg tp "$S/agent.jsonl" '{hook_event_name:"SubagentStop", agent_type:"delegate:checker", agent_id:"a1", cwd:$cwd, agent_transcript_path:$tp}' | python3 -I "$CHECKMARK" >/dev/null 2>&1
pre "$MERGE"
expect "T15k check with the script-made merge finding by the real hook + green gate: allowed" "$(allowed; echo $?)"
# (l) M-B: gate log for F, mark for F, then the mark commit and a handover commit
m15; commit "fix a" "lib/a.py=v2\n"; X="$(head_of)"; gate 0; mark 0; commit "handover" "docs/handover.md=state\n"; pre "$MERGE"
expect "T15l gate log of F, HEAD = F + gate + mark + handover: allowed" "$(allowed; echo $?)"
# (m) only a red gate log
m15; commit "fix a" "lib/a.py=v2\n"; G="$(head_of)"; X="$G"; gate 1; mark 0; pre "$MERGE"
expect "T15m red gate log: refused, last gate exit 1" "$(refused "last gate $G: exit 1"; echo $?)"
# (m2) F2: green on G, then red on the same code (a flaky failure): the newest gate on unchanged code decides; green again allows
m15; commit "fix a" "lib/a.py=v2\n"; X="$(head_of)"; gate 0; mark 0; G2="$(head_of)"; gate 1; pre "$MERGE"
expect "T15m2 green then red on the same code: refused, names the red log" "$(refused "last gate $G2: exit 1"; echo $?)"
gate 0; pre "$MERGE"
expect "T15m2 green again after the red, same code: allowed" "$(allowed; echo $?)"
# (n) m-1: a fix item closed in place (closed_at set) without a test; then with the test
m15; commit "fix a, close x" "lib/a.py=v2\n" ".relay/queue/x.json=$(qjson done tests/t.sh::case_x)\n"; X="$(head_of)"; gate 0; mark 0; pre "$MERGE"
expect "T15n item closed in place, its test file not in the tree: refused" "$(refused 'closed without a test or a check'; echo $?)"
commit "test" "tests/t.sh=case_x() { :; }\n"; X="$(head_of)"; gate 0; mark 0; pre "$MERGE"
expect "T15n with the test and a clean check: allowed" "$(allowed; echo $?)"
commit "name gone" "tests/t.sh=other() { :; }\n"; X="$(head_of)"; gate 0; mark 0; pre "$MERGE"
expect "T15n test file lacks the name: refused" "$(refused 'closed without a test'; echo $?)"
# (n2) done/ is gone: a file under it is refused, whatever else the branch holds; a dropped item that came through master is not judged
m15; mkdir -p "$W/.relay/queue/done"; git -C "$W" mv .relay/queue/x.json .relay/queue/done/x.json; git -C "$W" commit -q -m "move x"; pre "$MERGE"
expect "T15n2 a file moved to done/: refused, names the migration command" "$(refused 'done/, which is gone; run relay queue migrate'; echo $?)"
m15; mkdir -p "$W/.relay/queue/done"; git -C "$W" mv .relay/queue/x.json .relay/queue/done/x.json; git -C "$W" commit -q -m "move x"; green; pre "$MERGE"
expect "T15n2 the move plus a fix with clean mark and gate: refused" "$(refused 'done/, which is gone; run relay queue migrate'; echo $?)"
m15; green; qjson dropped "" >"$M/.relay/queue/y.json"; git -C "$M" add -A; git -C "$M" commit -q -m "drop y"
git -C "$W" merge -q --no-edit master; pre "$MERGE"
expect "T15n2 a dropped item that came through master: not judged, allowed" "$(allowed; echo $?)"
# (n3) the dated events: an item closed in place is judged by the same rule; a malformed one is refused; one already closed on master is not this branch's
newq() { # newq <extra json fields>: a new-shape fix item named x
  printf '{"kind": "fix", "ip": 5, "time": 10, "found_at": "2026-10-22T08:00:00Z", "found_in": "fixture", "title": "Item x loses a row", "what": ["x loses a row"], "why": ["a row is lost"], "failing_case": ["y"], "taken_at": "2026-10-22T10:00:00Z", "taken_by": "wt/t", %s, "dropped_at": null, "dropped_why": null}' "$1"
}
m15
commit "fix a, close x" "lib/a.py=v2\n" "tests/t.sh=case_x() { :; }\n" ".relay/queue/x.json=$(newq '"closed_at": "2026-10-24T01:00:00Z", "test": "tests/t.sh::case_x"')\n"; X="$(head_of)"; gate 0; mark 0; pre "$MERGE"
expect "T15n3 a well-formed new-shape item closed in place: allowed" "$(allowed; echo $?)"
commit "closed_at before taken_at" ".relay/queue/x.json=$(newq '"closed_at": "2026-10-21T20:00:00Z", "test": "tests/t.sh::case_x"')\n"; X="$(head_of)"; gate 0; mark 0; pre "$MERGE"
expect "T15n3 a malformed new-shape item: refused as malformed" "$(refused 'queue item x is malformed'; echo $?)"
commit "old shape" ".relay/queue/x.json={\"kind\": \"fix\", \"state\": \"done\", \"found\": \"2026-10-22\", \"closed_by\": \"wt/t\"}\n"; X="$(head_of)"; gate 0; mark 0; pre "$MERGE"
expect "T15n3 an item in the old shape (a branch started before the migration): refused, names the migration command" "$(refused 'relay queue migrate'; echo $?)"
m15; green; newq '"closed_at": "2026-10-24T01:00:00Z", "test": "tests/t.sh::case_x"' >"$M/.relay/queue/x.json"; git -C "$M" add -A; git -C "$M" commit -q -m "an older branch closed x"
git -C "$W" merge -q --no-edit master; pre "$MERGE"
expect "T15n3 x already closed on master, not closed by this branch: not judged, allowed" "$(allowed; echo $?)"
m15; commit "old shape in the open folder" ".relay/queue/z.json={\"kind\": \"feature\", \"state\": \"open\", \"found\": \"2026-10-22\"}\n"; X="$(head_of)"; gate 0; mark 0; pre "$MERGE"
expect "T15n3 an old-shape item added in the open folder: refused, names the migration command" "$(refused 'relay queue migrate'; echo $?)"
# (n4) F1: an old-shape item that reached the branch by taking the default branch (not in the range) is still refused
m15; green; printf '{"kind": "feature", "state": "open", "found": "2026-10-22"}\n' >"$M/.relay/queue/late.json"; git -C "$M" add -A; git -C "$M" commit -q -m "late old-shape item"
git -C "$W" merge -q --no-edit master; pre "$MERGE"
expect "T15n4 an old-shape item that came in through master: refused, names the migration command" "$(refused 'relay queue migrate'; echo $?)"
# (o) a code file moved into an inert folder is not "all inert"; control (f)
m15; mkdir -p "$W/.relay/queue"; git -C "$W" mv lib/a.py .relay/queue/a.py; git -C "$W" commit -q -m "move a"; pre "$MERGE"
expect "T15o code moved into an inert folder, no mark: refused, no check mark" "$(refused 'no check mark'; echo $?)"
m15; commit "handover" "docs/handover.md=state\n"; pre "$MERGE"
expect "T15o control (f): only inert files allowed" "$(allowed; echo $?)"
# (p) a merge inside a task worktree is not judged; control (a)
m15; commit "fix a" "lib/a.py=v2\n"; git -C "$M" worktree add -q .worktrees/w -b wt/w
pre "git -C $M/.worktrees/w merge --ff-only wt/t" "$M/.worktrees/w"
expect "T15p merge inside a worktree: silent, exit 0" "$(allowed; echo $?)"
pre "$MERGE"
expect "T15p control (a): the same branch merged in main is refused" "$(refused 'no check mark'; echo $?)"

echo; [ "$fails" -eq 0 ] && echo "merge.test: all passed" || { echo "merge.test: $fails failed"; exit 1; }
