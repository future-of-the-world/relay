#!/usr/bin/env python3
"""observe: the ledger hook. One JSON line per event into ~/.relay/ledger/<day>.jsonl.

Registered for SessionStart, UserPromptSubmit, SubagentStart, SubagentStop,
PreToolUse, PostToolUse, Stop, PreCompact, SessionEnd. It records sizes and
names, never prompt or reply text (unless [observe].log_prompts = true in the
project's kit.toml, which stores the first 200 characters of each prompt).

Fails open: any error prints nothing and exits 0. It must never slow a session:
the only file it reads besides stdin is the tail of a transcript on Stop and
SubagentStop, to record the context size.
"""

import datetime as dt
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
# The plugin ships a copy of the two library modules it needs (lib/), so it
# works from the installed plugin cache without the repository.
sys.path.insert(0, os.path.join(HERE, "..", "lib"))

import relay_ledger  # noqa: E402
import relay_transcripts  # noqa: E402


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def base(data, event):
    out = {
        "ts": now(),
        "event": event,
        "session_id": data.get("session_id"),
        "cwd": data.get("cwd"),
    }
    if data.get("agent_id"):
        out["agent_id"] = data["agent_id"]
        out["agent_type"] = data.get("agent_type") or ""
    if isinstance(data.get("effort"), dict) and data["effort"].get("level"):
        out["effort"] = data["effort"]["level"]
    return out


def log_prompts_enabled(cwd):
    try:
        import relay_toml
        root = cwd or os.getcwd()
        path = os.path.join(root, ".claude", "kit.toml")
        with open(path, "rb") as handle:
            return bool(relay_toml.load(handle).get("observe", {}).get("log_prompts"))
    except Exception:
        return False


def main():
    data = json.load(sys.stdin)
    event = data.get("hook_event_name")
    out = None
    if event == "SessionStart":
        out = base(data, "session_start")
        out["source"] = data.get("source")
        for key in ("model", "context_tokens", "seconds_since_last_response", "prompt_cache_likely_expired", "estimated_cache_write_usd"):
            if key in data:
                out[key] = data[key]
        # The last session of this folder finished: copy Claude Code's own totals for it into the
        # ledger before the next session overwrites them (this one, still running, is skipped).
        relay_ledger.capture(out["ts"], folder=data.get("cwd"), skip_session=data.get("session_id"))
    elif event == "UserPromptSubmit":
        out = base(data, "prompt")
        prompt = data.get("prompt") or ""
        out["chars"] = len(prompt)
        out["prompt_id"] = data.get("prompt_id")
        out["kind"] = "notification" if relay_transcripts.is_notification(prompt, data.get("origin")) else "owner"
        out["slash"] = prompt.strip().split()[0] if prompt.strip().startswith("/") else None
        if log_prompts_enabled(data.get("cwd")):
            out["text"] = prompt[:200]
    elif event == "SubagentStart":
        out = base(data, "agent_start")
        out["prompt_chars"] = len(data.get("agent_prompt") or data.get("prompt") or "")
        # key names only, never values: tells which fields this Claude Code version sends
        out["input_keys"] = sorted(str(k) for k in data)
    elif event == "SubagentStop":
        out = base(data, "agent_stop")
        handback = None
        path = data.get("agent_transcript_path")
        if not (path and os.path.isfile(path)):
            # older input: the agent's file sits beside the session's transcript
            session = data.get("transcript_path") or ""
            aid = "".join(ch for ch in str(data.get("agent_id") or "") if ch.isalnum() or ch in "-_")
            candidate = os.path.join(session[:-len(".jsonl")], "subagents", f"agent-{aid}.jsonl") if session.endswith(".jsonl") and aid else ""
            path = candidate if os.path.isfile(candidate) else None
        if path:
            trace = relay_transcripts.read_trace(path, kind="agent")
            out["requests"] = trace.total.requests
            out["context"] = trace.last_context
            out["model"] = trace.model
            out["cost_est"] = round(trace.total.cost, 4)
            handback = trace.handback_chars
        # What the caller receives: the SubagentHandback message when the agent used it (its
        # last_assistant_message is then the text before the hand-back, never delivered), else the
        # final text. None, not 0, when neither can be seen.
        reply = len(data.get("last_assistant_message") or "") or None
        out["reply_chars"] = handback if handback is not None else reply
    elif event == "PreToolUse":
        out = base(data, "tool_pre")
        out["tool"] = data.get("tool_name")
        out["tool_use_id"] = data.get("tool_use_id")
        if data.get("tool_name") in ("Agent", "Task"):
            ti = data.get("tool_input") or {}
            out["subagent_type"] = ti.get("subagent_type") or "general-purpose"
            out["model"] = ti.get("model")
            prompt = ti.get("prompt") or ""
            out["prompt_chars"] = len(prompt)
            out["escalated"] = relay_transcripts.is_escalated(prompt)
    elif event == "PostToolUse":
        out = base(data, "tool_post")
        out["tool"] = data.get("tool_name")
        out["tool_use_id"] = data.get("tool_use_id")
    elif event == "Stop":
        out = base(data, "stop")
        out["reply_chars"] = len(data.get("last_assistant_message") or "")
        path = data.get("transcript_path")
        if path and os.path.isfile(path):
            out["context"] = relay_transcripts.context_tokens_of(path)
    elif event == "PreCompact":
        out = base(data, "compact")
        out["trigger"] = data.get("trigger")
    elif event == "SessionEnd":
        out = base(data, "session_end")
        out["reason"] = data.get("reason")
    if out:
        relay_ledger.append(out)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
