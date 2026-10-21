"""The ledger: one JSON line per event, written by the observe plugin's hook,
one file per day under ~/.relay/ledger/. This module reads it.

Events (field `event`): session_start, prompt, agent_start, agent_stop,
tool_pre, tool_post, stop, compact, session_end. Every event has `ts`
(ISO 8601, UTC), `session_id`, and, inside a subagent, `agent_id` and `agent_type`.
"""

import datetime as dt
import glob
import json
import os

from relay_config import ledger_dir


def day_file(when=None):
    when = when or dt.datetime.now(dt.timezone.utc)
    return os.path.join(ledger_dir(), when.strftime("%Y-%m-%d") + ".jsonl")


def append(event):
    os.makedirs(ledger_dir(), exist_ok=True)
    with open(day_file(), "a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False) + "\n")


def parse_ts(value):
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def read(since=None, until=None):
    """Events from the day files, oldest first. since/until are aware datetimes."""
    events = []
    for path in sorted(glob.glob(os.path.join(ledger_dir(), "*.jsonl"))):
        day = os.path.basename(path)[:-len(".jsonl")]
        try:
            day_dt = dt.datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=dt.timezone.utc)
        except ValueError:
            continue
        if since and day_dt + dt.timedelta(days=1) < since:
            continue
        if until and day_dt > until:
            continue
        with open(path, encoding="utf-8") as handle:
            for raw in handle:
                try:
                    event = json.loads(raw)
                except ValueError:
                    continue
                ts = parse_ts(event.get("ts", ""))
                if since and ts and ts < since:
                    continue
                if until and ts and ts > until:
                    continue
                events.append(event)
    return events


def running_agents(events):
    """Agents started and not yet stopped, per session: {session_id: [event, ...]}."""
    open_by_session = {}
    for event in events:
        kind = event.get("event")
        sid = event.get("session_id")
        if kind == "agent_start":
            open_by_session.setdefault(sid, {})[event.get("agent_id")] = event
        elif kind == "agent_stop":
            open_by_session.get(sid, {}).pop(event.get("agent_id"), None)
        elif kind == "session_end":
            open_by_session.pop(sid, None)
    return {sid: list(agents.values()) for sid, agents in open_by_session.items() if agents}


def tool_durations(events):
    """Seconds per tool call, paired by tool_use_id: [(tool, agent_type, seconds)]."""
    pending = {}
    out = []
    for event in events:
        kind = event.get("event")
        if kind == "tool_pre":
            pending[event.get("tool_use_id")] = event
        elif kind == "tool_post":
            start = pending.pop(event.get("tool_use_id"), None)
            if not start:
                continue
            a, b = parse_ts(start.get("ts")), parse_ts(event.get("ts"))
            if a and b:
                out.append((event.get("tool"), event.get("agent_type") or "main", (b - a).total_seconds()))
    return out


def agent_spans(events):
    """Each agent as (session_id, agent_type, agent_id, start_dt, end_dt|None)."""
    starts = {}
    spans = []
    for event in events:
        kind = event.get("event")
        key = (event.get("session_id"), event.get("agent_id"))
        if kind == "agent_start":
            starts[key] = event
        elif kind == "agent_stop" and key in starts:
            start = starts.pop(key)
            spans.append((key[0], start.get("agent_type") or "", key[1], parse_ts(start.get("ts")), parse_ts(event.get("ts"))))
    for key, start in starts.items():
        spans.append((key[0], start.get("agent_type") or "", key[1], parse_ts(start.get("ts")), None))
    return spans


def owner_prompts(events):
    """Prompt events typed by the owner (not background-agent notifications; old events have no kind)."""
    return [e for e in events if e.get("event") == "prompt" and e.get("kind") != "notification"]


def agent_briefs(events):
    """What each agent was asked: {(session_id, agent_id): {subagent_type, prompt_chars, escalated}}.

    SubagentStart does not carry the prompt, so it comes from the `Agent` tool call that
    started the agent: each agent_start takes the oldest unclaimed Agent tool_pre of its
    session with the same subagent type."""
    waiting = {}
    out = {}
    for event in events:
        kind = event.get("event")
        sid = event.get("session_id")
        if kind == "tool_pre" and event.get("tool") in ("Agent", "Task"):
            waiting.setdefault(sid, []).append(event)
        elif kind == "agent_start":
            want = event.get("agent_type") or "general-purpose"
            queue = waiting.get(sid, [])
            for i, pre in enumerate(queue):
                if (pre.get("subagent_type") or "general-purpose") == want:
                    queue.pop(i)
                    out[(sid, event.get("agent_id"))] = {
                        "subagent_type": want,
                        "prompt_chars": int(pre.get("prompt_chars") or 0),
                        "escalated": bool(pre.get("escalated")),
                    }
                    break
    return out


def agent_results(events):
    """One record per agent from its agent_stop events. The harness fires agent_stop twice:
    with the reply, then again after the hand-back message (reply_chars 0, requests + 1).
    reply_chars is the largest seen; requests, context, model and cost_est are the last stop's
    (they are cumulative). {(session_id, agent_id): {...}}"""
    out = {}
    for event in events:
        if event.get("event") != "agent_stop":
            continue
        key = (event.get("session_id"), event.get("agent_id"))
        cur = out.setdefault(key, {"agent_type": event.get("agent_type") or "", "reply_chars": 0, "stops": 0})
        cur["stops"] += 1
        cur["reply_chars"] = max(cur["reply_chars"], int(event.get("reply_chars") or 0))
        for field in ("requests", "context", "model", "cost_est"):
            if field in event:
                cur[field] = event[field]
    return out
