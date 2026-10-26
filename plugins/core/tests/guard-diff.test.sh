#!/usr/bin/env bash
# Differential test of hooks/guard-main.sh: every command in guard-diff.golden.jsonl must get the verdict the guard
# at master 6a4b713 gave it (the "was" field: block or allow), except for the commands whose variable has a known
# value (guard-variable-paths): "was" holds the verdict of the guard that follows a variable set once by a plain
# assignment. An unquoted variable of unknown value is read literally, as at master; cd and git -C with one stay in
# the current directory. This test fails if a variable is followed in any other case.
# One more exception: `git merge --ff-only origin/master` in the main checkout on master is allowed since the sync fix (a
# main checkout catching up with its remote), so its "was" is allow.
# One more: the main session (cwd the main checkout) that cd's or pushd's into a linked worktree is blocked since the
# front-cd fix, so its "was" is block.
# The commands: the 28-command list of review 1, review 2's R1/R2 cases, review 3's M1/M2/S3 cases, and every
# Bash input of the guard-main suite (before the variable tests were dropped). Placeholders in cwd and cmd:
# @M@ the main checkout, @W@ its worktree .worktrees/any-change, @A@ its worktree .worktrees/a, @T@ a temp dir.
#   plugins/core/tests/guard-diff.test.sh
#   plugins/core/tests/guard-diff.test.sh --record <a plugins/core directory of the old guard>   (rewrites "was")
set -uo pipefail
here="$(cd "$(dirname "$0")" && pwd -P)"
hook="$here/../hooks/guard-main.sh"; golden="$here/guard-diff.golden.jsonl"
record=""; [ "${1:-}" = --record ] && record="${2:?--record needs the old plugins/core directory}"
[ -n "$record" ] && hook="$(cd "$record" && pwd -P)/hooks/guard-main.sh"
unset CLAUDE_PROJECT_DIR
tmp="$(cd "$(mktemp -d)" && pwd -P)"; trap 'rm -rf "$tmp"' EXIT
M="$tmp/repo"; mkdir -p "$M" && cd "$M" && git init -q -b master . \
  && git -c user.name=t -c user.email=t@t commit -q --allow-empty -m init \
  && git worktree add -q .worktrees/any-change -b wt/any-change \
  && git worktree add -q .worktrees/a -b wt/a \
  && git worktree add -q .worktree/any-change -b wt/any-change2 || { echo "guard-diff.test: cannot build the repo" >&2; exit 1; }
printf '.ci/\n' >"$M/.gitignore"; printf 'a\n' >"$M/README.md"
mkdir -p "$M/.claude" && cp "$here/profiles/kartoteka.toml" "$M/.claude/kit.toml"
W="$M/.worktrees/any-change"; A="$M/.worktrees/a"

n=$(( $(wc -l <"$golden") )); jobs=8
verdict() { # <line index> : the hook's verdict for that line of the golden file
  local line cwd cmd
  line="$(sed -n "${1}p" "$golden")"
  cwd="$(jq -r .cwd <<<"$line")"; cmd="$(jq -r .cmd <<<"$line")"
  for v in cwd cmd; do
    local x="${!v}"; x="${x//@W@/$W}"; x="${x//@A@/$A}"; x="${x//@M@/$M}"; x="${x//@T@/$tmp}"; printf -v "$v" %s "$x"
  done
  jq -n --arg cwd "$cwd" --arg val "$cmd" '{tool_name:"Bash",cwd:$cwd,tool_input:{command:$val}}' | "$hook" >/dev/null 2>&1
  [ $? -eq 2 ] && echo block || echo allow
}
for ((j = 0; j < jobs; j++)); do
  ( for ((i = j + 1; i <= n; i += jobs)); do echo "$i $(verdict "$i")"; done >"$tmp/v.$j" ) &
done
wait
cat "$tmp"/v.* | sort -n >"$tmp/verdicts"

if [ -n "$record" ]; then
  while read -r i v; do sed -n "${i}p" "$golden" | jq -c --arg v "$v" '.was = $v'; done <"$tmp/verdicts" >"$tmp/new" \
    && cp "$tmp/new" "$golden" && echo "recorded $n verdicts from $hook"; exit 0
fi

fails=0
while read -r i v; do
  was="$(sed -n "${i}p" "$golden" | jq -r .was)"
  if [ "$v" != "$was" ]; then echo "FAIL  $v (old guard: $was)  $(sed -n "${i}p" "$golden" | jq -r '.cwd + "  " + .cmd')"; fails=$((fails + 1)); fi
done <"$tmp/verdicts"
[ $(( $(wc -l <"$tmp/verdicts") )) -eq "$n" ] || { echo "FAIL  only $(wc -l <"$tmp/verdicts") of $n commands judged"; fails=$((fails + 1)); }
if [ "$fails" -eq 0 ]; then echo "all passed: $n commands, 0 differences from the guard at 6a4b713"; else echo "$fails differences from the guard at 6a4b713"; exit 1; fi
