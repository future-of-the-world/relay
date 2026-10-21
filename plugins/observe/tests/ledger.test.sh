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
send '{"hook_event_name":"PreToolUse","session_id":"s","cwd":"/p","tool_name":"Agent","tool_use_id":"t2","tool_input":{"subagent_type":"delegate:worker","model":"opus","prompt":"line one\nEscalated: needs depth"}}'; has "tool_pre records prompt length and the escalated flag" '"prompt_chars": 31, "escalated": true'
send '{"hook_event_name":"PreToolUse","session_id":"s","cwd":"/p","tool_name":"Agent","tool_use_id":"t3","tool_input":{"subagent_type":"delegate:scout","prompt":"Not Escalated: here"}}'; has "no flag when the line does not start with it" '"prompt_chars": 19, "escalated": false'
grep -q 'needs depth' "$RELAY_HOME"/ledger/*.jsonl && { echo "FAIL agent prompt text stored"; fails=1; } || echo "ok   agent prompt text not stored"
send '{"hook_event_name":"UserPromptSubmit","session_id":"s","cwd":"/p","prompt":"<task-notification>done</task-notification>","prompt_id":"p2"}'; has "notification prompt is marked" '"kind": "notification"'
has "owner prompt is marked" '"kind": "owner"'
send '{"hook_event_name":"PreToolUse","session_id":"s","cwd":"/p","tool_name":"Agent","tool_use_id":"t4","tool_input":{"subagent_type":"delegate:worker","model":"opus","prompt":"x\n  escalated: lower case counts"}}'; has "escalation is read as the route guard reads it (any case)" '"tool_use_id": "t4".*"escalated": true'
send '{"hook_event_name":"PreToolUse","session_id":"s","cwd":"/p","tool_name":"Agent","tool_use_id":"t5","tool_input":{"subagent_type":"delegate:worker","model":"opus","prompt":"x\nEscalated:"}}'; has "an empty reason is not an escalation" '"tool_use_id": "t5".*"escalated": false'
send '{"hook_event_name":"UserPromptSubmit","session_id":"s","cwd":"/p","prompt":"tune-stage still fires on <task-notification> prompts, fix it","prompt_id":"p3"}'; has "an owner quoting a marker is still the owner" '"prompt_id": "p3".*"kind": "owner"'
send '{"hook_event_name":"UserPromptSubmit","session_id":"s","cwd":"/p","prompt":"anything","origin":{"kind":"task-notification"},"prompt_id":"p4"}'; has "the structured origin marks a notification" '"prompt_id": "p4".*"kind": "notification"'
printf '{"type":"assistant","timestamp":"2026-10-19T10:00:00Z","requestId":"r9","message":{"model":"claude-haiku-5","content":[{"type":"tool_use","id":"h1","name":"SubagentHandback","input":{"message":"DONE ok"}}],"usage":{"input_tokens":10,"cache_read_input_tokens":0,"cache_creation_input_tokens":0,"output_tokens":5}}}\n' > "$RELAY_HOME/s/subagents/agent-a2.jsonl"
send "{\"hook_event_name\":\"SubagentStop\",\"session_id\":\"s\",\"cwd\":\"/p\",\"agent_id\":\"a2\",\"agent_type\":\"delegate:scout\",\"transcript_path\":\"$t\",\"last_assistant_message\":\"text before the hand-back that the caller never sees\"}"; has "reply length is the hand-back message, not the text before it" '"agent_id": "a2".*"reply_chars": 7'
send "{\"hook_event_name\":\"SubagentStop\",\"session_id\":\"s\",\"cwd\":\"/p\",\"agent_id\":\"a3\",\"agent_type\":\"delegate:scout\",\"transcript_path\":\"$t\"}"; has "reply length unknown is null, not 0" '"agent_id": "a3".*"reply_chars": null'
printf '{"projects":{"/p":{"lastSessionId":"old1","lastModelUsage":{"claude-opus-5-5":{"inputTokens":34,"outputTokens":5683,"cacheReadInputTokens":1053863,"cacheCreationInputTokens":46711,"costUSD":0.698}}}}}' > "$RELAY_HOME/claude.json"
export RELAY_CLAUDE_JSON="$RELAY_HOME/claude.json"
send '{"hook_event_name":"SessionStart","session_id":"s","cwd":"/p","source":"startup"}'; has "session start copies the last finished session's totals" '"event": "session_usage".*"session_id": "old1".*"output_tokens": 5683'
send '{"hook_event_name":"SessionStart","session_id":"s2","cwd":"/p","source":"startup"}'
[ "$(grep -c '"session_usage"' "$RELAY_HOME"/ledger/*.jsonl)" = 1 ] && echo "ok   totals copied once" || { echo "FAIL totals copied twice"; fails=1; }
unset RELAY_CLAUDE_JSON
send 'garbage'; echo "ok   malformed input fails open"
exit $fails
