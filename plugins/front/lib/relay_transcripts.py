"""Read Claude Code transcripts into numbers: requests, tokens, cost, agents, tools.

A session is ~/.claude/projects/<slug>/<session>.jsonl. Its subagents sit beside
it: <slug>/<session>/subagents/agent-<id>.jsonl, with agent-<id>.meta.json
({"agentType": ...}) when the harness wrote one. Every assistant line carries
`message.model` and `message.usage` (input, cache creation, cache read, output
tokens); the lines of one API request share a `requestId`, so a request is
counted once. Tool calls are `tool_use` blocks in assistant content.

Nothing here reads prompt or reply text beyond its length.
"""

import glob
import json
import os
from dataclasses import dataclass, field

import relay_prices

USAGE_KEYS = ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens", "output_tokens")


def _zero():
    return {k: 0 for k in USAGE_KEYS}


def _add(into, usage):
    for k in USAGE_KEYS:
        into[k] += int(usage.get(k) or 0)


@dataclass
class Agg:
    """Token and request totals for one model, one agent, or one session."""
    requests: int = 0
    usage: dict = field(default_factory=_zero)
    cost: float = 0.0

    def add(self, model, usage):
        self.requests += 1
        _add(self.usage, usage)
        self.cost += relay_prices.cost(model, usage)

    @property
    def context(self):
        """Tokens re-read per request: the sum of all input kinds."""
        return self.usage["input_tokens"] + self.usage["cache_creation_input_tokens"] + self.usage["cache_read_input_tokens"]


@dataclass
class Trace:
    """One transcript file: the main thread of a session, or one subagent."""
    path: str
    kind: str                      # "session" | "agent"
    session_id: str = ""
    agent_id: str = ""
    agent_type: str = ""
    cwd: str = ""
    started: str = ""
    ended: str = ""
    total: Agg = field(default_factory=Agg)
    by_model: dict = field(default_factory=dict)      # model -> Agg
    tools: dict = field(default_factory=dict)         # tool name -> count
    agents_started: dict = field(default_factory=dict)  # subagent_type -> count (Agent tool calls)
    user_turns: int = 0
    prompt_chars: int = 0          # what the owner typed, in characters (a long prompt is a setup gap)
    long_prompts: int = 0          # prompts over 600 characters
    reply_chars: int = 0           # assistant text, in characters (noise measure)
    last_context: int = 0          # context size of the last request
    max_context: int = 0
    compactions: int = 0
    models: set = field(default_factory=set)
    gaps_over_5m: int = 0          # pauses between requests longer than the 5-minute agent cache
    max_gap_s: float = 0.0
    _last_request_ts: str = ""
    first_read: int = 0            # cache_creation tokens of the first request: what a fresh agent pays

    @property
    def model(self):
        if not self.by_model:
            return ""
        return max(self.by_model, key=lambda m: self.by_model[m].requests)


def read_trace(path, kind="session"):
    trace = Trace(path=path, kind=kind)
    seen_requests = set()
    try:
        handle = open(path, "r", encoding="utf-8", errors="replace")
    except OSError:
        return trace
    with handle:
        for raw in handle:
            raw = raw.strip()
            if not raw:
                continue
            try:
                entry = json.loads(raw)
            except ValueError:
                continue
            _absorb(trace, entry, seen_requests)
    return trace


def _absorb(trace, entry, seen_requests):
    kind = entry.get("type")
    ts = entry.get("timestamp") or ""
    if ts:
        if not trace.started or ts < trace.started:
            trace.started = ts
        if ts > trace.ended:
            trace.ended = ts
    if not trace.session_id and entry.get("sessionId"):
        trace.session_id = entry["sessionId"]
    if not trace.cwd and entry.get("cwd"):
        trace.cwd = entry["cwd"]
    if entry.get("isCompactSummary") or kind == "summary":
        trace.compactions += 1
    message = entry.get("message") or {}
    if kind == "user":
        content = message.get("content")
        # A real user turn is a string or text blocks; tool results are user lines too.
        if isinstance(content, str) or (isinstance(content, list) and any(
            isinstance(b, dict) and b.get("type") == "text" for b in content
        )):
            if not entry.get("isMeta"):
                trace.user_turns += 1
                text = content if isinstance(content, str) else " ".join(b.get("text") or "" for b in content if isinstance(b, dict))
                if not text.lstrip().startswith("<"):   # tool results and system reminders are not the owner
                    trace.prompt_chars += len(text)
                    if len(text) > 600:
                        trace.long_prompts += 1
        return
    if kind != "assistant":
        return
    content = message.get("content") or []
    if isinstance(content, list):
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "text":
                trace.reply_chars += len(block.get("text") or "")
            elif block.get("type") == "tool_use":
                name = block.get("name") or "?"
                trace.tools[name] = trace.tools.get(name, 0) + 1
                if name in ("Agent", "Task"):
                    sub = (block.get("input") or {}).get("subagent_type") or "general-purpose"
                    trace.agents_started[sub] = trace.agents_started.get(sub, 0) + 1
    usage = message.get("usage") or {}
    if not any(usage.get(k) for k in USAGE_KEYS):
        return
    request_id = entry.get("requestId") or entry.get("uuid")
    if request_id in seen_requests:
        return
    seen_requests.add(request_id)
    if ts:
        if trace._last_request_ts:
            gap = _seconds_between(trace._last_request_ts, ts)
            if gap is not None:
                trace.max_gap_s = max(trace.max_gap_s, gap)
                if gap > 300:
                    trace.gaps_over_5m += 1
        trace._last_request_ts = ts
    if trace.total.requests == 0:
        trace.first_read = int(usage.get("cache_creation_input_tokens") or 0) + int(usage.get("input_tokens") or 0)
    model = message.get("model") or "unknown"
    trace.models.add(model)
    trace.total.add(model, usage)
    trace.by_model.setdefault(model, Agg()).add(model, usage)
    context = sum(int(usage.get(k) or 0) for k in USAGE_KEYS[:3])
    trace.last_context = context
    trace.max_context = max(trace.max_context, context)


def _seconds_between(a, b):
    import datetime as dt
    try:
        da = dt.datetime.fromisoformat(a.replace("Z", "+00:00"))
        db = dt.datetime.fromisoformat(b.replace("Z", "+00:00"))
    except ValueError:
        return None
    return (db - da).total_seconds()


def duration_s(trace):
    if not trace.started or not trace.ended:
        return 0.0
    return _seconds_between(trace.started, trace.ended) or 0.0


def agent_meta(agent_path):
    meta = agent_path[: -len(".jsonl")] + ".meta.json"
    try:
        with open(meta, encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def session_agents(session_path):
    """The subagent traces of a session, in start order."""
    folder = session_path[: -len(".jsonl")]
    out = []
    for path in sorted(glob.glob(os.path.join(folder, "subagents", "agent-*.jsonl"))):
        trace = read_trace(path, kind="agent")
        trace.agent_id = os.path.basename(path)[len("agent-"):-len(".jsonl")]
        meta = agent_meta(path)
        trace.agent_type = meta.get("agentType") or meta.get("agent_type") or ""
        trace.session_id = trace.session_id or os.path.basename(session_path)[:-len(".jsonl")]
        out.append(trace)
    out.sort(key=lambda t: t.started)
    return out


def find_sessions(claude_dir, since_mtime=0.0, project_slug=None):
    """Session transcript paths under <claude_dir>/projects, newest first."""
    pattern = os.path.join(claude_dir, "projects", project_slug or "*", "*.jsonl")
    paths = [p for p in glob.glob(pattern) if os.path.getmtime(p) >= since_mtime]
    paths.sort(key=os.path.getmtime, reverse=True)
    return paths


def session_path_for(claude_dir, session_id):
    hits = glob.glob(os.path.join(claude_dir, "projects", "*", f"{session_id}.jsonl"))
    return hits[0] if hits else None


def context_tokens_of(session_path):
    """Context size of the last main-thread request of a session, read from the file's tail."""
    size = os.path.getsize(session_path)
    tail = 8_000_000
    with open(session_path, "rb") as handle:
        if size > tail:
            handle.seek(size - tail)
            handle.readline()
        lines = handle.read().splitlines()
    for raw in reversed(lines):
        if b'"usage"' not in raw:
            continue
        try:
            entry = json.loads(raw)
        except ValueError:
            continue
        if entry.get("type") != "assistant" or entry.get("isSidechain"):
            continue
        usage = (entry.get("message") or {}).get("usage") or {}
        total = sum(int(usage.get(k) or 0) for k in USAGE_KEYS[:3])
        if total:
            return total
    return None
