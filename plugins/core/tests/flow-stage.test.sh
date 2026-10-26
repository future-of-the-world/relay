#!/usr/bin/env bash
set -uo pipefail
here="$(cd "$(dirname "$0")" && pwd -P)"
hook="$here/../hooks/flow-stage.py"
export RELAY_ROOT="$(cd "$here/../../.." && pwd -P)"
fails=0
check() { local name="$1" want="$2" out; out="$(printf '%s' "$3" | python3 "$hook")"
  if [[ -z "$want" && -z "$out" ]] || [[ -n "$want" && "$out" == *"$want"* ]]; then echo "ok   $name"; else echo "FAIL $name: got '$out'"; fails=1; fi; }
p="$(mktemp -d)"; mkdir -p "$p/.claude"
check "no binding: silent" '' "{\"hook_event_name\":\"UserPromptSubmit\",\"cwd\":\"$p\",\"prompt\":\"/opsx:apply x\"}"
printf '[specs]\nmethod = "openspec"\n' > "$p/.claude/kit.toml"
# the spec method's line is the openspec plugin's hook now (tests/test_openspec_hook.py); core cannot know the plugin is loaded
check "openspec: core stays silent on /opsx:apply" '' "{\"hook_event_name\":\"UserPromptSubmit\",\"cwd\":\"$p\",\"prompt\":\"/opsx:apply add-x\"}"
printf '[flow]\nkind = "none"\n' > "$p/.claude/kit.toml"
check "kind none: silent" '' "{\"hook_event_name\":\"UserPromptSubmit\",\"cwd\":\"$p\",\"prompt\":\"/opsx:apply x\"}"
exit $fails
