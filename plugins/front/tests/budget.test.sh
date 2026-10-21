#!/usr/bin/env bash
set -uo pipefail
here="$(cd "$(dirname "$0")" && pwd -P)"
export RELAY_HOME="$(mktemp -d)"
fails=0
check() { local name="$1" want="$2" out; out="$(printf '%s' "$3" | python3 "$here/../hooks/$4")"
  if [[ "$out" == *"$want"* ]]; then echo "ok   $name"; else echo "FAIL $name: got '$out'"; fails=1; fi; }
t="$RELAY_HOME/s.jsonl"
line() { printf '{"type":"assistant","timestamp":"2026-10-19T10:00:00Z","message":{"usage":{"input_tokens":100,"cache_read_input_tokens":%s,"cache_creation_input_tokens":0,"output_tokens":5}}}\n' "$1"; }
line 100000 > "$t"
check "under the line: silent" '' "{\"hook_event_name\":\"UserPromptSubmit\",\"session_id\":\"s\",\"transcript_path\":\"$t\",\"cwd\":\"/tmp\"}" budget.py
line 360000 > "$t"
check "over the line: handover note" 'handover' "{\"hook_event_name\":\"UserPromptSubmit\",\"session_id\":\"s\",\"transcript_path\":\"$t\",\"cwd\":\"/tmp\"}" budget.py
check "second prompt over the line: silent (marker)" '' "{\"hook_event_name\":\"UserPromptSubmit\",\"session_id\":\"s\",\"transcript_path\":\"$t\",\"cwd\":\"/tmp\"}" budget.py
mkdir -p "$RELAY_HOME/sess/subagents"; a="$RELAY_HOME/sess/subagents/agent-a1.jsonl"; line 250000 > "$a"
check "big agent: wrap note" 'hand back' "{\"hook_event_name\":\"PostToolUse\",\"session_id\":\"s\",\"agent_id\":\"a1\",\"transcript_path\":\"$RELAY_HOME/sess.jsonl\",\"agent_transcript_path\":\"$a\",\"tool_name\":\"Read\"}" budget.py
check "big agent: note once per step" '' "{\"hook_event_name\":\"PostToolUse\",\"session_id\":\"s\",\"agent_id\":\"a1\",\"agent_transcript_path\":\"$a\",\"tool_name\":\"Read\"}" budget.py
proj="$(mktemp -d)"; mkdir -p "$proj/docs"; echo state > "$proj/docs/handover.md"
check "compact names the handover file" 'handover.md' "{\"hook_event_name\":\"SessionStart\",\"source\":\"compact\",\"cwd\":\"$proj\"}" handover.py
check "no handover file: silent" '' '{"hook_event_name":"SessionStart","source":"compact","cwd":"/tmp"}' handover.py
check "resume warns about the cache" 'cheaper' "{\"hook_event_name\":\"SessionStart\",\"source\":\"resume\",\"cwd\":\"$proj\",\"prompt_cache_likely_expired\":true,\"estimated_cache_write_usd\":1.2,\"context_tokens\":180000}" handover.py
exit $fails
