#!/usr/bin/env bash
# Smoke test of the hooks inside a real Claude Code session (claude -p, Haiku,
# a few cents): the plugins load from this checkout with --plugin-dir, in a
# throwaway repo.
#   - a stage typed as a slash command (/openspec:archive) gets the project's
#     addition (UserPromptSubmit);
#   - an agent (openspec:author) gets its addition at start (SubagentStart);
#   - the guard refuses a shell write in the main checkout, and the same write
#     in a worktree goes through (so the refusal is the guard's, not a failed run).
# The unit tests feed the hooks JSON by hand; this one proves that Claude Code
# sends what they expect. Skipped, loudly, when `claude` is missing or
# HOOKS_LIVE=0 is set (offline runs).
# Each session runs with --output-format stream-json (with the hook events): the
# checks read only its final "result" line, so a hook's own text cannot pass a case.
# On a failure the four raw outputs are kept in a folder whose path is printed.
#   plugins/core/tests/hooks-live.test.sh
set -uo pipefail

here="$(cd "$(dirname "$0")" && pwd -P)"
core="$here/.."
openspec="$here/../../openspec"
if [ "${HOOKS_LIVE:-1}" = 0 ] || ! command -v claude >/dev/null 2>&1; then
  echo "hooks-live.test: SKIPPED (claude not on PATH, or HOOKS_LIVE=0): the hooks were not run in a real session"
  exit 0
fi

tmp="$(cd "$(mktemp -d)" && pwd -P)"
trap 'rm -rf "$tmp"' EXIT
R="$tmp/repo"
mkdir -p "$R/.claude/kit" && cd "$R" && git init -q -b master . \
  && printf '[project]\ndefault_branch = "master"\nworktrees = ".worktrees"\n' >.claude/kit.toml \
  && printf 'The project codeword for the archive stage is OTTER-77.\n' >.claude/kit/archive.md \
  && printf 'The project codeword for the author is BADGER-31.\n' >.claude/kit/author.md \
  && git add -A && git -c user.name=t -c user.email=t@t commit -q -m init \
  && git worktree add -q .worktrees/w -b wt/w || { echo "hooks-live.test: cannot build the repo" >&2; exit 1; }

run() { # <cwd> <outfile> <prompt> [claude options...]
  local cwd="$1" out="$2" prompt="$3"; shift 3
  (cd "$cwd" && claude -p --model haiku --max-budget-usd 0.5 --plugin-dir "$core" --plugin-dir "$openspec" --output-format stream-json --verbose --include-hook-events "$@" "$prompt" >"$out" 2>&1)
}

run "$R" "$tmp/stage.out" "/openspec:archive Do not archive anything. Reply with only the project codeword for the archive stage, or NONE if you were given none." &
run "$R" "$tmp/agent.out" "Start the agent openspec:author with the Agent tool (subagent_type openspec:author) and this prompt: 'Do not start any work. Reply with only the project codeword for the author, or NONE if you were given none.' Then reply with only what the agent replied." &
run "$R" "$tmp/guard.out" "Run exactly this command with the Bash tool, nothing else: echo probe > guard-probe.txt   Then reply with the tool's result text." --allowedTools=Bash &
run "$R/.worktrees/w" "$tmp/control.out" "Run exactly this command with the Bash tool, nothing else: echo probe > guard-probe.txt   Then reply DONE." --allowedTools=Bash &
wait

fails=0
ck() { # <description> <ok: 0 or 1> <output file>
  if [ "$2" = 0 ]; then echo "ok    $1"; else echo "FAIL  $1: $(result "$3" | head -c 400 | tr '\n' ' ')"; fails=$((fails + 1)); fi
}
result() { grep -F '"type":"result"' "$1"; } # the session's final answer: not the hook events, which may hold the codeword
result "$tmp/stage.out" | grep -q 'OTTER-77'; ck "a typed /openspec:archive gets the project's archive addition" $? "$tmp/stage.out"
result "$tmp/agent.out" | grep -q 'BADGER-31'; ck "openspec:author gets the project's author addition at its start" $? "$tmp/agent.out"
[ ! -e "$R/guard-probe.txt" ] && result "$tmp/guard.out" | grep -q 'guard-main'; ck "the guard refuses a shell write in the main checkout" $? "$tmp/guard.out"
[ -e "$R/.worktrees/w/guard-probe.txt" ]; ck "the same write in a worktree goes through" $? "$tmp/control.out"

if [ "$fails" -eq 0 ]; then echo "hooks-live.test: all passed"; exit 0; fi
kept="$(mktemp -d "${TMPDIR:-/tmp}/hooks-live-XXXXXX")" && cp "$tmp"/*.out "$kept"/
echo "hooks-live.test: $fails failed; the sessions' stream-json output (hook events included) is kept in $kept"
exit 1
