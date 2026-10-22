#!/usr/bin/env bash
# Cleanup after the allowed merge (hooks/merge.sh -> merge.py), cases T1-T14, T16, T18-T20 of
# docs/plans/review-gate.md section 12.1, on throwaway repositories under a temp dir (temp HOME).
#   plugins/core/tests/merge.test.sh
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
expect "N1 agent-text and sync notices" "$(has 'open sessions keep the old texts' "$ctx" && has 'Run relay sync once from the main checkout.' "$ctx"; echo $?)"

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

echo; [ "$fails" -eq 0 ] && echo "merge.test: all passed" || { echo "merge.test: $fails failed"; exit 1; }
