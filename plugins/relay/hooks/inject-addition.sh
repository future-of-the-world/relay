#!/usr/bin/env bash
# SubagentStart, PostToolUse(Skill) and UserPromptSubmit hook: put a project's
# addition in front of the shared role that needs it.
#
# A project keeps its rules for an agent in `.claude/kit/<name>.md`. When
# an agent `<plugin>:<name>` starts, the skill `<plugin>:<role>` has just been
# loaded with the Skill tool, or the owner has typed the stage as a slash
# command (`/openspec:archive ...`: then no Skill call happens, the skill comes in
# with the prompt), this hook hands that file to the agent or session as
# additional context, so the project's rules are always there and no
# instruction has to be obeyed first. No file, nothing is injected.
#
# A project may also keep rules for a whole role in `.claude/kit/<role>.md`,
# role one of lookup, run, build, fix, think, judge. An agent's role is read
# from `../lib/agent-roles.tsv` (`<plugin>:<name><TAB><role>`, written by
# `relay sync agents` from the agents' relay:base markers); an agent not in
# the map, or no map, gets its own file only. At SubagentStart the role file
# comes first, then the agent's file, whose rules win where they differ
# (project per agent > project per role > flow > base). Skills and typed
# stages have no role. With no role file the output is what it was before
# role files existed (test I4).
#
# Only the framework's own plugins are served (core, openspec, delegate,
# front): another plugin's `code-reviewer` must not receive a
# project's `code-reviewer.md`.
#
# Project root = the git top-level of the hook's cwd (inside a worktree, that
# worktree's own root), else the cwd.
#
# Hook input (verified on Claude Code 2.1.302): SubagentStart has `agent_type`
# (`<plugin>:<role>` for a plugin agent); PostToolUse with matcher Skill has
# `tool_input.skill`; UserPromptSubmit has `prompt`. Output is
# `hookSpecificOutput.additionalContext`.
#
# Tests: plugins/relay/tests/inject-addition.test.sh
set -uo pipefail

command -v jq >/dev/null 2>&1 || { echo "inject-addition: jq is not installed (brew install jq)." >&2; exit 2; }
input="$(cat)"
event="$(jq -r '.hook_event_name // empty' <<<"$input")"
case "$event" in
  SubagentStart) name="$(jq -r '.agent_type // empty' <<<"$input")" ;;
  PostToolUse) name="$(jq -r 'select(.tool_name == "Skill") | .tool_input.skill // empty' <<<"$input")" ;;
  UserPromptSubmit)
    # a typed stage: the prompt starts with /<plugin>:<role>, then a space or its end
    prompt="$(jq -r '.prompt // empty' <<<"$input")"
    [[ "$prompt" =~ ^[[:space:]]*/([a-z0-9][a-z0-9_-]*:[a-z][a-z0-9-]*)([[:space:]]|$) ]] || exit 0
    name="${BASH_REMATCH[1]}"
    ;;
  *) exit 0 ;;
esac
cwd="$(jq -r '.cwd // empty' <<<"$input")"
[ -n "$cwd" ] || cwd="$PWD"

# <plugin>:<role> of a framework plugin, nothing else (no path can leave .claude/kit/).
[[ "$name" =~ ^(relay|openspec|delegate|front):([a-z][a-z0-9-]*)$ ]] || exit 0
role="${BASH_REMATCH[2]}"

root="$(git -C "$cwd" rev-parse --show-toplevel 2>/dev/null)" || root="$cwd"
file="$root/.claude/kit/$role.md"

# the role's own file (agents only): the role named in the map, never an agent's or skill's name
rolefile=""
if [ "$event" = SubagentStart ]; then
  map="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)/../lib/agent-roles.tsv"
  if [ -f "$map" ]; then
    r="$(awk -F'\t' -v n="$name" '$1 == n { print $2; exit }' "$map")"
    if [[ "$r" =~ ^(lookup|run|build|fix|think|judge)$ ]] && [ "$r" != "$role" ] && [ -f "$root/.claude/kit/$r.md" ]; then
      rolefile="$root/.claude/kit/$r.md"; rolename="$r"
    fi
  fi
fi

if [ -n "$rolefile" ]; then
  if [ -f "$file" ]; then
    jq -n --arg ev "$event" --arg name "$name" --arg role "$role" --arg rn "$rolename" --rawfile rbody "$rolefile" --rawfile body "$file" '{
      hookSpecificOutput: {
        hookEventName: $ev,
        additionalContext: ("Project rules for the \($rn) role (.claude/kit/\($rn).md of this project)\n\n" + $rbody + "\nProject rules for \($name) (.claude/kit/\($role).md); where they differ from the role'"'"'s rules, these win\n\n" + $body)
      }
    }'
  else
    jq -n --arg ev "$event" --arg rn "$rolename" --rawfile rbody "$rolefile" '{
      hookSpecificOutput: {
        hookEventName: $ev,
        additionalContext: ("Project rules for the \($rn) role (.claude/kit/\($rn).md of this project)\n\n" + $rbody)
      }
    }'
  fi
  exit 0
fi
[ -f "$file" ] || exit 0

jq -n --arg ev "$event" --arg name "$name" --arg role "$role" --rawfile body "$file" '{
  hookSpecificOutput: {
    hookEventName: $ev,
    additionalContext: ("Project addition for \($name) (.claude/kit/\($role).md of this project). It belongs to the shared role; where it differs from the shared text, it wins.\n\n" + $body)
  }
}'
