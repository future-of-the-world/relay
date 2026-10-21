"""The ledger: one JSON line per event, written by the observe plugin's hook,
one file per day under ~/.relay/ledger/. This module reads it.

Events (field `event`): session_start, prompt, agent_start, agent_stop,
tool_pre, tool_post, stop, compact, session_end, session_usage (Claude Code's own
per-model figures for a finished session: the exact numbers `/cost` showed). Every event has `ts`
(ISO 8601, UTC), `session_id`, and, inside a subagent, `agent_id` and `agent_type`.
"""

import datetime as dt
import glob
import json
import os

from relay_config import claude_json, ledger_dir


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


# ---- exact per-session figures, written by Claude Code itself -------------------------------
# Claude Code keeps, per project folder, the last session's id and its per-model totals
# (`lastModelUsage`: the numbers /cost shows). The next session in that folder overwrites them, so
# relay copies them into the ledger as `session_usage` lines before that happens.

_MODEL_KEYS = {
    "inputTokens": "input_tokens", "outputTokens": "output_tokens", "thinkingTokens": "thinking_tokens",
    "cacheReadInputTokens": "cache_read_input_tokens", "cacheCreationInputTokens": "cache_creation_input_tokens",
    "webSearchRequests": "web_search_requests", "costUSD": "cost_usd",
}


def claude_json_sessions():
    """[(project folder, session id, {model: numbers})] for every folder whose last session has figures."""
    try:
        with open(claude_json(), encoding="utf-8") as handle:
            projects = (json.load(handle) or {}).get("projects") or {}
    except (OSError, ValueError, AttributeError):
        return []
    out = []
    for folder, entry in projects.items():
        if not isinstance(entry, dict) or not entry.get("lastSessionId") or not isinstance(entry.get("lastModelUsage"), dict):
            continue
        models = {}
        for model, raw in entry["lastModelUsage"].items():
            if isinstance(raw, dict):
                models[model] = {new: raw[old] for old, new in _MODEL_KEYS.items()
                                 if isinstance(raw.get(old), (int, float))}
        if models:
            out.append((folder, entry["lastSessionId"], models))
    return out


def usage_records(since=None):
    """{session_id: (when written, {model: numbers})} from `session_usage` ledger lines. The newest line of a
    session wins: a resumed session is written again when Claude Code's total for it has changed."""
    found = {}
    for event in read(since=since):
        if event.get("event") == "session_usage" and event.get("session_id") and isinstance(event.get("models"), dict):
            found[event["session_id"]] = (parse_ts(event.get("ts")), event["models"])
    return found


def usage_sessions(since=None):
    """{session_id: {model: numbers}} from `session_usage` ledger lines (the newest line of a session wins)."""
    return {sid: models for sid, (_when, models) in usage_records(since).items()}


def record_usage(session_id, folder, models, now, source="claude.json"):
    append({"ts": now, "event": "session_usage", "session_id": session_id, "cwd": folder,
            "source": source, "models": models})


def capture(now, folder=None, skip_session=None):
    """Write a `session_usage` line for each session in Claude Code's file whose total is not yet in the ledger
    (or has changed since: a resumed session). folder: only that project folder (the hook's own);
    skip_session: a session still running."""
    written = []
    recorded = None
    for project, sid, models in claude_json_sessions():
        if folder is not None and project != folder:
            continue
        if sid == skip_session:
            continue
        if recorded is None:
            recorded = usage_sessions()
        if recorded.get(sid) == models:
            continue
        record_usage(sid, project, models, now)
        recorded[sid] = models
        written.append(sid)
    return written


def exact_records():
    """{session_id: (when the figure was written, {model: numbers})}: the ledger's newest lines, then Claude
    Code's file where it holds a different (newer) total or one not yet copied; its time is the file's."""
    found = usage_records()
    try:
        file_time = dt.datetime.fromtimestamp(os.path.getmtime(claude_json()), dt.timezone.utc)
    except OSError:
        file_time = None
    for _folder, sid, models in claude_json_sessions():
        if sid not in found or found[sid][1] != models:
            found[sid] = (file_time, models)
    return found


def exact_sessions():
    """{session_id: {model: numbers}}: the ledger's lines, then Claude Code's file for sessions not yet copied."""
    return {sid: models for sid, (_when, models) in exact_records().items()}
