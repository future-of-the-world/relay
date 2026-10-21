"""The ledger: one JSON line per event, written by the observe plugin's hook,
one file per day under ~/.relay/ledger/. This module reads it.

Events (field `event`): session_start, prompt, agent_start, agent_stop,
tool_pre, tool_post, stop, compact, session_end, session_usage (Claude Code's own
per-model figures for a finished session: the exact numbers `/cost` showed), usage_restart (that session's
counter went down: it stays an estimate). Every event has `ts`
(ISO 8601, UTC), `session_id`, and, inside a subagent, `agent_id` and `agent_type`.
"""

import datetime as dt
import glob
import json
import os

try:
    import fcntl
except ImportError:      # not on Windows
    fcntl = None

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


def restarted_sessions(since=None):
    """Session ids whose Claude Code counter was seen to restart (see _shrank): their totals cover only part of
    the session, so they are never labelled exact, even when the new count later grows past the old one."""
    return {e["session_id"] for e in read(since=since) if e.get("event") == "usage_restart" and e.get("session_id")}


def usage_sessions(since=None):
    """{session_id: {model: numbers}} from `session_usage` ledger lines (the newest line of a session wins)."""
    return {sid: models for sid, (_when, models) in usage_records(since).items()}


_INDEX_KEEP = 300      # newest sessions the index remembers: it must stay small, the hook reads it every time


def _index_path():
    return os.path.join(ledger_dir(), "usage-index.json")


def _read_index():
    """{"sessions": {session_id: models}, "restarted": [session_id, ...]}; empty when missing or unreadable."""
    try:
        with open(_index_path(), encoding="utf-8") as handle:
            found = json.load(handle)
    except (OSError, ValueError):
        found = None
    if not isinstance(found, dict) or not isinstance(found.get("sessions"), dict):
        return {"sessions": {}, "restarted": []}
    restarted = found.get("restarted")
    return {"sessions": found["sessions"], "restarted": restarted if isinstance(restarted, list) else []}


def _write_index(index):
    """Atomic: a temp file of its own (one per writer), then a rename, so a reader never sees half a file."""
    sessions = index["sessions"]
    while len(sessions) > _INDEX_KEEP:
        sessions.pop(next(iter(sessions)))
    del index["restarted"][:-_INDEX_KEEP]
    os.makedirs(ledger_dir(), exist_ok=True)
    tmp = "%s.tmp.%d" % (_index_path(), os.getpid())
    try:
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(index, handle)
        os.replace(tmp, _index_path())
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def _update_index(change):
    """Read-modify-write of the index under a lock, so concurrent SessionEnd hooks merge instead of overwriting
    each other (30 hooks at once lost up to 18 of 30 entries without it)."""
    try:
        os.makedirs(ledger_dir(), exist_ok=True)
        with open(os.path.join(ledger_dir(), "usage-index.lock"), "a") as lock:
            if fcntl is not None:
                fcntl.flock(lock, fcntl.LOCK_EX)
            index = _read_index()
            change(index)
            _write_index(index)
    except OSError:
        pass


def record_usage(session_id, folder, models, now, source="claude.json"):
    append({"ts": now, "event": "session_usage", "session_id": session_id, "cwd": folder,
            "source": source, "models": models})

    def change(index):
        index["sessions"].pop(session_id, None)
        index["sessions"][session_id] = models
    _update_index(change)


def record_restart(session_id, folder, now):
    """Remember that a session's counter restarted: it stays an estimate for the rest of its life."""
    append({"ts": now, "event": "usage_restart", "session_id": session_id, "cwd": folder})

    def change(index):
        if session_id not in index["restarted"]:
            index["restarted"].append(session_id)
    _update_index(change)


def _recorded(session_id, index):
    """The total the ledger holds for a session, without reading the ledger: the small index file, else the
    last few days' lines (the index is only a shortcut and may be missing)."""
    if session_id in index["sessions"]:
        return index["sessions"][session_id]
    since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=3)
    return usage_sessions(since=since).get(session_id)


def _is_restarted(session_id, index):
    if session_id in index["restarted"]:
        return True
    since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=3)
    return session_id in restarted_sessions(since=since)


def _shrank(old, new):
    """True when a total is smaller than the one already recorded for the same session: a counter that
    restarted from 0 on resume would look like this, and its figure covers only the resumed part."""
    for model, row in old.items():
        now_row = new.get(model) or {}
        for key in ("output_tokens", "cost_usd"):
            if isinstance(row.get(key), (int, float)) and now_row.get(key, 0) < row[key]:
                return True
    return False


def capture(now, folder=None, skip_session=None, only_session=None):
    """Write a `session_usage` line for each session in Claude Code's file whose total is not yet in the ledger
    (or has grown since: a resumed session). The line's time is `now`: the moment the total was seen.
    folder: only that project folder (the hook's own); skip_session: a session still running;
    only_session: just that session (the hook of a session that is ending).
    Cost does not grow with the age of the ledger: the check against what is recorded reads one small index.
    A total smaller than the recorded one is not written, and the session is marked restarted: Claude Code
    has not been seen to say whether its counter restarts on resume, so once a total went down the counter is
    taken to have restarted, and every later total of that session (even one that grows past the old figure,
    which would then look like a plain growth) covers only a part. Such a session stays an estimate."""
    written = []
    index = None
    for project, sid, models in claude_json_sessions():
        if folder is not None and project != folder:
            continue
        if sid == skip_session or (only_session is not None and sid != only_session):
            continue
        if index is None:
            index = _read_index()
        if _is_restarted(sid, index):
            continue
        have = _recorded(sid, index)
        if have == models:
            continue
        if have is not None and _shrank(have, models):
            record_restart(sid, project, now)
            index["restarted"].append(sid)
            continue
        record_usage(sid, project, models, now)
        index["sessions"][sid] = models
        written.append(sid)
    return written


# The write time of a total found only in ~/.claude.json: unknown. Claude Code rewrites that file every few
# seconds, so its modification time says nothing about when this session's total was last updated. A total
# counts as covering the whole session only when a ledger line proves it was seen after the last activity.
UNKNOWN = dt.datetime.min.replace(tzinfo=dt.timezone.utc)


def exact_records():
    """{session_id: (when the figure was seen, {model: numbers})}: the ledger's newest lines, then Claude
    Code's file where it holds a different (newer) total or one not yet copied; those get UNKNOWN as their
    time, so a report estimates them while the session has any transcript activity."""
    found = usage_records()
    restarted = restarted_sessions()
    for sid in restarted:
        found.pop(sid, None)
    for _folder, sid, models in claude_json_sessions():
        if sid in restarted:
            continue
        if sid not in found or found[sid][1] != models:
            found[sid] = (UNKNOWN, models)
    return found


def exact_sessions():
    """{session_id: {model: numbers}}: the ledger's lines, then Claude Code's file for sessions not yet copied."""
    return {sid: models for sid, (_when, models) in exact_records().items()}
