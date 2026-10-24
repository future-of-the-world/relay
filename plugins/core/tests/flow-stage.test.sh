#!/usr/bin/env bash
set -uo pipefail
here="$(cd "$(dirname "$0")" && pwd -P)"
hook="$here/../hooks/flow-stage.py"
export RELAY_ROOT="$(cd "$here/../../.." && pwd -P)"
fails=0
check() { local name="$1" want="$2" out; out="$(printf '%s' "$3" | python3 "$hook")"
  if [[ "$out" == *"$want"* ]]; then echo "ok   $name"; else echo "FAIL $name: got '$out'"; fails=1; fi; }
p="$(mktemp -d)"; mkdir -p "$p/.claude"
check "no binding: silent" '' "{\"hook_event_name\":\"UserPromptSubmit\",\"cwd\":\"$p\",\"prompt\":\"/opsx:apply x\"}"
printf '[specs]\nmethod = "openspec"\n' > "$p/.claude/kit.toml"
check "openspec: /opsx:apply gives the step-2 note" 'step 2 of the change cycle' "{\"hook_event_name\":\"UserPromptSubmit\",\"cwd\":\"$p\",\"prompt\":\"/opsx:apply add-x\"}"
check "openspec: /opsx:propose names openspec:plan" 'openspec:plan' "{\"hook_event_name\":\"UserPromptSubmit\",\"cwd\":\"$p\",\"prompt\":\"/opsx:propose add-x: do it\"}"
check "openspec: plain prompt silent" '' "{\"hook_event_name\":\"UserPromptSubmit\",\"cwd\":\"$p\",\"prompt\":\"hello\"}"
check "inside an agent: silent" '' "{\"hook_event_name\":\"UserPromptSubmit\",\"cwd\":\"$p\",\"agent_id\":\"a\",\"prompt\":\"/opsx:apply x\"}"
printf '[flow]\nkind = "issues"\n' > "$p/.claude/kit.toml"
check "issues: /issue 42 names issues:implement" 'issues:implement' "{\"hook_event_name\":\"UserPromptSubmit\",\"cwd\":\"$p\",\"prompt\":\"/issue 42\"}"
check "issues: roles listed" 'delegate:worker' "{\"hook_event_name\":\"UserPromptSubmit\",\"cwd\":\"$p\",\"prompt\":\"/issues:merge 42\"}"
check "issues: keyword #123 -> implement" 'issues:implement' "{\"hook_event_name\":\"UserPromptSubmit\",\"cwd\":\"$p\",\"prompt\":\"do #123 please\"}"
check "issues: keyword create issue -> create" 'issues:create' "{\"hook_event_name\":\"UserPromptSubmit\",\"cwd\":\"$p\",\"prompt\":\"create an issue for the flaky kill test\"}"
check "issues: keyword list issues -> read" 'issues:read' "{\"hook_event_name\":\"UserPromptSubmit\",\"cwd\":\"$p\",\"prompt\":\"which issues are open?\"}"
check "issues: keyword PR -> merge" 'issues:merge' "{\"hook_event_name\":\"UserPromptSubmit\",\"cwd\":\"$p\",\"prompt\":\"open the PR\"}"
check "issues: unrelated prompt silent" '' "{\"hook_event_name\":\"UserPromptSubmit\",\"cwd\":\"$p\",\"prompt\":\"what time is it\"}"
printf '[flow]\nkind = "none"\n' > "$p/.claude/kit.toml"
check "kind none: silent" '' "{\"hook_event_name\":\"UserPromptSubmit\",\"cwd\":\"$p\",\"prompt\":\"/opsx:apply x\"}"
exit $fails
