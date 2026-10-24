"""Read Claude Code transcripts into numbers: requests, tokens, cost, agents, tools.

A session is ~/.claude/projects/<slug>/<session>.jsonl. Its subagents sit beside
it: <slug>/<session>/subagents/agent-<id>.jsonl, with agent-<id>.meta.json
({"agentType": ...}) when the harness wrote one. Every assistant line carries
`message.model` and `message.usage` (input, cache creation, cache read, output
tokens); the lines of one API request share a `requestId`, so a request is
counted once. Tool calls are `tool_use` blocks in assistant content.

Nothing here reads prompt or reply text beyond its length.
"""
from __future__ import annotations   # the hooks may run under Python 3.9: annotations are never evaluated

import glob
import json
import os
import re
from dataclasses import dataclass, field

import relay_prices

USAGE_KEYS = ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens", "output_tokens")


NOTIFICATION_MARKERS = ("[SYSTEM NOTIFICATION", "<task-notification>", "<agent-message from=")
NOTIFICATION_KINDS = ("task-notification", "peer")
# Lines that are user lines in a transcript but not something the owner typed.
_NOT_TYPED_STARTS = ("[Request interrupted", "<local-command-stdout>", "<local-command-stderr>", "<local-command-caveat>",
                     "<bash-input>", "<bash-stdout>", "<bash-stderr>")
# A slash command is a turn only when it runs a prompt. The harness answers its own commands (/clear, /cost,
# /rate-limit-options, ...) with a `<local-command-stdout>` line instead of a model reply, so the structure
# tells them apart, not a list of names: see _absorb.
_ENDS_COMMAND = ("[Request interrupted", "<local-command-stdout>", "<local-command-stderr>")   # a local command ended, or was cut off
_COMMAND_WRAPPER = ("<command-name>", "<command-message>")
# promptSource of a user line the owner wrote; any other value ("sdk": a program, "system") is not the owner.
OWNER_PROMPT_SOURCES = ("typed", "suggestion_accepted", "queued")
_ESCALATED = re.compile(r"(?mi)^\s*Escalated:\s*\S")


def is_notification(text, origin=None):
    """True when a "user prompt" is really a background-agent notification, not the owner typing.

    The structured field wins when the harness sent one (`origin.kind`: "task-notification" or
    "peer" are notifications, any other kind is not). Without it, the text must start with a
    marker: an owner who quotes a marker in the middle of a sentence is still the owner."""
    kind = origin.get("kind") if isinstance(origin, dict) else None
    if kind:
        return kind in NOTIFICATION_KINDS
    text = (text or "").lstrip()
    return any(text.startswith(m) for m in NOTIFICATION_MARKERS)


def is_owner_turn(text, origin=None, prompt_source=None):
    """True when a user line is something the owner typed (or a slash command; _absorb takes back one the
    harness answered itself).

    With the structured `origin`, only kind "human" counts; with `promptSource`, only what the owner wrote
    (typed, an accepted suggestion, a queued line), so a prompt a program sent ("sdk") is not a turn. Whatever the origin says, the text must not be an
    interruption marker, a local command's wrapper or output, or a notification (older transcripts have no origin)."""
    if is_notification(text, origin):
        return False
    kind = origin.get("kind") if isinstance(origin, dict) else None
    if kind and kind != "human":
        return False
    if prompt_source and prompt_source not in OWNER_PROMPT_SOURCES:
        return False
    return not (text or "").lstrip().startswith(_NOT_TYPED_STARTS)


def is_escalated(prompt):
    """True when an agent prompt carries a line `Escalated: <reason>` (any case, a reason is required).
    The routing guard and the ledger both use this, so they cannot disagree."""
    return bool(_ESCALATED.search(prompt or ""))


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
    estimated: bool = False     # output tokens were estimated (agent transcripts hold a mid-answer snapshot)
    one_hour: int = 0           # cache-write tokens the transcript says were written for 1 hour
    early_reads: int = 0        # cache-read tokens requested before the model's earlier-price date (prices.toml)

    def add(self, model, usage, estimated=False, when=""):
        self.requests += 1
        early = relay_prices.is_before(model, when)
        if early:
            self.early_reads += int(usage.get("cache_read_input_tokens") or 0)
        split = usage.get("cache_creation")
        if isinstance(split, dict):
            self.one_hour += int(split.get("ephemeral_1h_input_tokens") or 0)
        _add(self.usage, usage)
        self.cost += relay_prices.cost(model, usage, 1.0 if early else 0.0)
        self.estimated = self.estimated or estimated

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
    scripted_turns: int = 0        # prompts a program sent (headless `claude -p`, bench, evals): not the owner's turns
    scripted: bool = False         # session only: started by a program (entrypoint "sdk-*")
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
    escalated: bool = False        # agent only: its prompt had an `Escalated:` line (set from the parent's transcript)
    agent_briefs: dict = field(default_factory=dict)   # session only: agent_id -> {prompt_chars, escalated}, paired by id
    handback_chars: object = None  # agent only: length of its SubagentHandback message (None: it never handed back)
    _agent_calls: dict = field(default_factory=dict)   # Agent tool_use id -> {prompt_chars, escalated}
    first_read: int = 0            # cache_creation tokens of the first request: what a fresh agent pays
    chars_by_model: dict = field(default_factory=dict)  # agent only: model -> visible characters of its answers
    _command_open: bool = False    # a slash command line was seen and no other user line or model reply has followed it yet
    _pending: dict = field(default_factory=dict)       # agent only: requestId -> the request's lines folded together

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
    _settle_agent_requests(trace)
    if trace.scripted:          # every prompt of a program-started session is the program's, not the owner's
        trace.scripted_turns += trace.user_turns
        trace.user_turns = trace.prompt_chars = trace.long_prompts = 0
    return trace


def _visible_chars(content):
    """Characters of the answer that can be seen on disk: text, thinking, and tool-call input."""
    total = 0
    if isinstance(content, list):
        for block in content:
            if not isinstance(block, dict):
                continue
            kind = block.get("type")
            if kind == "text":
                total += len(block.get("text") or "")
            elif kind == "thinking":
                total += len(block.get("thinking") or "")
            elif kind == "tool_use":
                total += len(json.dumps(block.get("input"), ensure_ascii=False))
    return total


def _settle_agent_requests(trace):
    """Agent transcripts are written while the answer streams: each line keeps the output count so far
    (stop_reason empty), and the final count is on disk nowhere. A request's output is therefore
    max(largest recorded count, visible characters x tokens-per-character of its model), marked
    estimated. The main thread's lines carry the final usage and are counted as they come."""
    for item in trace._pending.values():
        usage = dict(item["usage"])
        guess = round(item["chars"] * relay_prices.output_per_char(item["model"]))
        usage["output_tokens"] = max(item["out"], guess)
        trace.chars_by_model[item["model"]] = trace.chars_by_model.get(item["model"], 0) + item["chars"]
        trace.total.add(item["model"], usage, estimated=True, when=item["when"])
        trace.by_model.setdefault(item["model"], Agg()).add(item["model"], usage, estimated=True, when=item["when"])
    trace._pending = {}


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
    if str(entry.get("entrypoint") or "").startswith("sdk"):
        trace.scripted = True
    if kind == "assistant":
        if trace._command_open:
            trace.user_turns += 1         # a model reply answered the command: it ran a prompt, it is a turn
            trace._command_open = False
    if kind == "user":
        content = message.get("content")
        result = entry.get("toolUseResult")
        if isinstance(result, dict) and result.get("agentId") and isinstance(content, list):
            # the Agent call that started this agent: the result names the agent, its block names the call
            for block in content:
                call = trace._agent_calls.get(block.get("tool_use_id")) if isinstance(block, dict) else None
                if call is not None:
                    trace.agent_briefs[str(result["agentId"])] = call
        # A real user turn is a string or text blocks; tool results are user lines too.
        if isinstance(content, str) or (isinstance(content, list) and any(
            isinstance(b, dict) and b.get("type") == "text" for b in content
        )):
            text = content if isinstance(content, str) else " ".join(b.get("text") or "" for b in content if isinstance(b, dict))
            stripped = text.lstrip()
            if stripped.startswith(_ENDS_COMMAND) or not (
                    stripped.startswith("<local-command-caveat>") or entry.get("isMeta")
                    or is_notification(text, entry.get("origin")) or not is_owner_turn(text, entry.get("origin"), entry.get("promptSource"))):
                # the owner's next line (or the command's own output) with no model reply between: the command ran locally.
                # A caveat, a skill expansion, a background-task notice or any other line the owner did not write
                # (origin or promptSource says so) leaves the command open: the reply can still come after it.
                trace._command_open = False
            if not (entry.get("isMeta") or entry.get("isCompactSummary") or is_notification(text, entry.get("origin"))
                    or not is_owner_turn(text, entry.get("origin"), entry.get("promptSource"))):
                if stripped.startswith(_COMMAND_WRAPPER):
                    trace._command_open = True    # counted only if the model answers it (a real /clear has no output line at all)
                else:
                    trace.user_turns += 1
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
                    given = block.get("input") or {}
                    sub = given.get("subagent_type") or "general-purpose"
                    trace.agents_started[sub] = trace.agents_started.get(sub, 0) + 1
                    prompt = given.get("prompt") or ""
                    trace._agent_calls[block.get("id")] = {"prompt_chars": len(prompt), "escalated": is_escalated(prompt)}
                elif name == "SubagentHandback":
                    trace.handback_chars = len((block.get("input") or {}).get("message") or "")
    usage = message.get("usage") or {}
    if not any(usage.get(k) for k in USAGE_KEYS):
        return
    request_id = entry.get("requestId") or entry.get("uuid")
    if trace.kind == "agent" and request_id in trace._pending:
        item = trace._pending[request_id]
        item["chars"] += _visible_chars(content)
        item["out"] = max(item["out"], int(usage.get("output_tokens") or 0))
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
    if len(seen_requests) == 1:
        trace.first_read = int(usage.get("cache_creation_input_tokens") or 0) + int(usage.get("input_tokens") or 0)
    model = message.get("model") or "unknown"
    trace.models.add(model)
    if trace.kind == "agent":
        trace._pending[request_id] = {"model": model, "usage": usage, "chars": _visible_chars(content),
                                      "out": int(usage.get("output_tokens") or 0), "when": ts}
    else:
        trace.total.add(model, usage, when=ts)
        trace.by_model.setdefault(model, Agg()).add(model, usage, when=ts)
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


def context_tokens_of(session_path: str) -> int | None:
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
