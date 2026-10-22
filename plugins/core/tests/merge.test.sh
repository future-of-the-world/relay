#!/usr/bin/env bash
# Cleanup after the allowed merge (hooks/merge.sh -> merge.py), cases T1-T12, T14 and T18 of
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

echo; [ "$fails" -eq 0 ] && echo "merge.test: all passed" || { echo "merge.test: $fails failed"; exit 1; }
