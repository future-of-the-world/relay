#!/usr/bin/env bash
set -uo pipefail
here="$(cd "$(dirname "$0")" && pwd -P)"; hook="$here/../hooks/ledger.py"
export RELAY_HOME="$(mktemp -d)"; fails=0
send() { printf '%s' "$1" | python3 "$hook"; }
has() { local name="$1" want="$2"; if grep -q "$want" "$RELAY_HOME"/ledger/*.jsonl; then echo "ok   $name"; else echo "FAIL $name: no '$want'"; fails=1; fi; }
t="$RELAY_HOME/s.jsonl"; mkdir -p "$RELAY_HOME/s/subagents"
printf '{"type":"assistant","timestamp":"2026-10-19T10:00:00Z","requestId":"r1","message":{"model":"claude-sonnet-5","usage":{"input_tokens":100,"cache_read_input_tokens":50000,"cache_creation_input_tokens":0,"output_tokens":5}}}\n' > "$t"
cp "$t" "$RELAY_HOME/s/subagents/agent-a1.jsonl"
send '{"hook_event_name":"SessionStart","session_id":"s","cwd":"/p","source":"startup","model":"claude-opus-5"}'; has "session_start with model" '"event": "session_start".*"model": "claude-opus-5"'
send '{"hook_event_name":"UserPromptSubmit","session_id":"s","cwd":"/p","prompt":"/opsx:apply x","prompt_id":"p1"}'; has "prompt with slash, no text" '"slash": "/opsx:apply"'
grep -q '"text"' "$RELAY_HOME"/ledger/*.jsonl && { echo "FAIL prompt text stored"; fails=1; } || echo "ok   prompt text not stored"
send '{"hook_event_name":"SubagentStart","session_id":"s","cwd":"/p","agent_id":"a1","agent_type":"delegate:scout","effort":{"level":"low"},"agent_prompt":"abc"}'; has "agent_start" '"agent_type": "delegate:scout".*"effort": "low"'
send "{\"hook_event_name\":\"SubagentStop\",\"session_id\":\"s\",\"cwd\":\"/p\",\"agent_id\":\"a1\",\"agent_type\":\"delegate:scout\",\"transcript_path\":\"$t\",\"last_assistant_message\":\"done\"}"; has "agent_stop reads the agent transcript by fallback" '"event": "agent_stop".*"requests": 1'
send "{\"hook_event_name\":\"Stop\",\"session_id\":\"s\",\"cwd\":\"/p\",\"transcript_path\":\"$t\",\"last_assistant_message\":\"hello\"}"; has "stop with context" '"event": "stop".*"context": 50100'
send '{"hook_event_name":"PreToolUse","session_id":"s","cwd":"/p","tool_name":"Agent","tool_use_id":"t1","tool_input":{"subagent_type":"delegate:worker","model":"sonnet"}}'; has "tool_pre with subagent" '"subagent_type": "delegate:worker"'
send 'garbage'; echo "ok   malformed input fails open"
exit $fails
