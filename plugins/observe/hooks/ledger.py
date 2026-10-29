#!/usr/bin/env python3
"""observe: the ledger hook. One JSON line per event into ~/.relay/ledger/<day>.jsonl.

Registered for SessionStart, UserPromptSubmit, SubagentStart, SubagentStop,
PreToolUse, PostToolUse, Stop, PreCompact, SessionEnd. It records sizes and
names, never prompt or reply text (unless [observe].log_prompts = true in the
project's kit.toml, which stores the first 200 characters of each prompt).

Fails open: any error prints nothing and exits 0. It must never slow a session:
the only files it reads besides stdin are the tail of a transcript on Stop and
SubagentStop (the context size) and, for an agent that a workflow script started,
the first 4 KB of the agent's .meta.json beside its transcript (run, stage label,
phase: names only, and the label only when it fits the stage grammar below).
"""

import datetime as dt
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
# The plugin ships a copy of the two library modules it needs (lib/), so it
# works from the installed plugin cache without the repository.
sys.path.insert(0, os.path.join(HERE, "..", "lib"))

import relay_labels  # noqa: E402
import relay_ledger  # noqa: E402
import relay_transcripts  # noqa: E402


# The label an agent is started with (relay_labels): an agent started by hand has a free-text description, which the ledger must not
# store, so only the label form is kept, and never the free words after " - ".
STAGE_LABEL = relay_labels.STAGE_LABEL
PHASE_NAME = re.compile(r"^[A-Za-z][A-Za-z ]{0,29}$")
META_HEAD_BYTES = 4096


def meta_string(head: str, key: str) -> str:
    """The string value of `key` in the head of a .meta.json, or "" (a truncated tail does not matter: the keys we want are early)."""
    found = re.search(r'"%s"\s*:\s*("(?:[^"\\]|\\.)*")' % re.escape(key), head)
    if not found:
        return ""
    try:
        value = json.loads(found.group(1))
    except ValueError:
        return ""
    return value if isinstance(value, str) else ""


def workflow_fields(transcript: str) -> dict:
    """run, label and phase of an agent a workflow script started: its transcript sits in .../workflows/wf_<id>/.
    Empty for any other agent, and for a missing or unreadable meta file."""
    folder = os.path.basename(os.path.dirname(transcript))
    if not (re.fullmatch(r"wf_[A-Za-z0-9-]{1,40}", folder) and os.path.basename(os.path.dirname(os.path.dirname(transcript))) == "workflows"):
        return {}
    out = {"run": folder}
    meta = transcript[:-len(".jsonl")] + ".meta.json" if transcript.endswith(".jsonl") else ""
    try:
        with open(meta, "r", encoding="utf-8", errors="replace") as handle:
            head = handle.read(META_HEAD_BYTES)
    except OSError:
        return out
    label = relay_labels.label_of(meta_string(head, "description"))
    if label:
        out["label"] = label
        phase = meta_string(head, "workflowPhase")
        if PHASE_NAME.match(phase):
            out["phase"] = phase
    return out


def hand_fields(transcript: str) -> dict:
    """label of an agent started by hand (not by a workflow script), from its .meta.json; {} when it has none or none can be read."""
    meta = transcript[:-len(".jsonl")] + ".meta.json" if transcript.endswith(".jsonl") else ""
    try:
        with open(meta, "r", encoding="utf-8", errors="replace") as handle:
            head = handle.read(META_HEAD_BYTES)
    except OSError:
        return {}
    label = relay_labels.label_of(meta_string(head, "description"))
    return {"label": label} if label else {}


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


def has_start(agent_id: str, *stamps: str) -> bool:
    """True when the ledger already holds an agent_start line for this agent in the day file(s) of the given timestamps."""
    needle = json.dumps(agent_id)
    for stamp in stamps:
        try:
            with open(relay_ledger.day_file(relay_ledger.parse_ts(stamp)), "r", encoding="utf-8", errors="replace") as handle:
                for line in handle:
                    if '"agent_start"' in line and needle in line:
                        return True
        except OSError:
            continue
    return False


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
        # ledger before the next session overwrites them. A new session skips itself; a resumed one is
        # copied too (its old total, stamped now, so the work that follows makes it an estimate).
        resumed = data.get("source") in ("resume", "compact")
        relay_ledger.capture(out["ts"], folder=data.get("cwd"), skip_session=None if resumed else data.get("session_id"))
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
            out.update(workflow_fields(path) or hand_fields(path))
            trace = relay_transcripts.read_trace(path, kind="agent")
            # Claude Code sends no SubagentStart for many agents (workflow agents included): when none was
            # recorded, write the start now, stamped with the agent's first transcript line.
            aid = data.get("agent_id")
            if aid and trace.started and not has_start(str(aid), trace.started, out["ts"]):
                begun = base(data, "agent_start")
                begun["ts"] = trace.started
                begun["synthetic"] = True
                begun.update(workflow_fields(path) or hand_fields(path))
                relay_ledger.append(begun)
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
        # The event line first (the hook has 1 s), then, if Claude Code has already written the session's final
        # total, copy it: it covers everything. If Claude Code writes it only after this hook, the next session
        # start in the folder copies it.
        relay_ledger.append(out)
        relay_ledger.capture(out["ts"], folder=data.get("cwd"), only_session=data.get("session_id"))
        out = None
    if out:
        relay_ledger.append(out)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
