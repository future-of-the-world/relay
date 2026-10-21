#!/usr/bin/env bash
# The routing guard's decisions on the Agent tool.
set -uo pipefail
here="$(cd "$(dirname "$0")" && pwd -P)"
guard="$here/../hooks/route-guard.py"
export RELAY_HOME="$(mktemp -d)"
fails=0
check() { # name expected-substring json
  local name="$1" want="$2" input="$3" out
  out="$(printf '%s' "$input" | python3 "$guard")"
  if [[ "$out" == *"$want"* ]]; then echo "ok   $name"; else echo "FAIL $name: got '$out'"; fails=1; fi
}
cd "$(mktemp -d)"
check "general-purpose denied" '"deny"' '{"tool_name":"Agent","cwd":".","tool_input":{"subagent_type":"general-purpose","prompt":"x"}}'
check "typed scout allowed" '' '{"tool_name":"Agent","cwd":".","tool_input":{"subagent_type":"delegate:scout","prompt":"x"}}'
check "worker on opus denied" 'Escalated' '{"tool_name":"Agent","cwd":".","tool_input":{"subagent_type":"delegate:worker","model":"opus","prompt":"x"}}'
check "worker on opus with escalation allowed" '' '{"tool_name":"Agent","cwd":".","tool_input":{"subagent_type":"delegate:worker","model":"opus","prompt":"Brief: /b.md\nEscalated: sonnet failed twice"}}'
check "thinker on opus allowed" '' '{"tool_name":"Agent","cwd":".","tool_input":{"subagent_type":"delegate:thinker","model":"opus","prompt":"x"}}'
long="$(python3 -c 'print("a"*3500)')"
check "long prompt without brief gets a note" 'Brief' "{\"tool_name\":\"Agent\",\"cwd\":\".\",\"tool_input\":{\"subagent_type\":\"delegate:worker\",\"prompt\":\"$long\"}}"
check "non-agent tool ignored" '' '{"tool_name":"Bash","cwd":".","tool_input":{"command":"ls"}}'
# project override: typed_only=false
mkdir -p .claude && printf '[delegate]\ntyped_only = false\n' > .claude/kit.toml
check "typed_only=false allows general-purpose" '' '{"tool_name":"Agent","cwd":".","tool_input":{"subagent_type":"general-purpose","prompt":"x"}}'
# fork over the limit: build a transcript with 150k context
t="$RELAY_HOME/t.jsonl"
printf '{"type":"assistant","message":{"usage":{"input_tokens":1000,"cache_read_input_tokens":150000,"cache_creation_input_tokens":0,"output_tokens":5}}}\n' > "$t"
check "fork over limit denied" '"deny"' "{\"tool_name\":\"Agent\",\"cwd\":\".\",\"transcript_path\":\"$t\",\"tool_input\":{\"subagent_type\":\"fork\",\"prompt\":\"x\"}}"
check "malformed input fails open" '' 'not json'
exit $fails
