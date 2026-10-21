"""Synthetic transcripts and ledger events for the tests (no real sessions needed)."""
import json
import os
import datetime as dt


def _ts(base, minutes):
    return (base + dt.timedelta(minutes=minutes)).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def assistant(ts, model, cache_read, cache_write, out, request_id, tools=(), text="", sidechain=False):
    content = [{"type": "text", "text": text}] if text else []
    for name, inp in tools:
        content.append({"type": "tool_use", "id": "tu_" + request_id, "name": name, "input": inp})
    return {"type": "assistant", "timestamp": ts, "requestId": request_id, "isSidechain": sidechain,
            "message": {"role": "assistant", "model": model, "content": content,
                        "usage": {"input_tokens": 50, "cache_read_input_tokens": cache_read,
                                  "cache_creation_input_tokens": cache_write, "output_tokens": out}}}


def user(ts, text):
    return {"type": "user", "timestamp": ts, "message": {"role": "user", "content": text}}


def write_session(claude_dir, slug, session_id, base, agents):
    """A main session with 3 user turns and the given agents: [(agent_type, model, requests, gap_minutes)]."""
    folder = os.path.join(claude_dir, "projects", slug)
    os.makedirs(os.path.join(folder, session_id, "subagents"), exist_ok=True)
    lines = []
    minute = 0
    for turn in range(3):
        lines.append(user(_ts(base, minute), f"request {turn}"))
        lines.append(assistant(_ts(base, minute + 1), "claude-opus-5", 120_000 + turn * 20_000, 5_000, 400, f"r{turn}",
                               tools=[("Agent", {"subagent_type": a[0], "prompt": "x"}) for a in agents] if turn == 1 else [],
                               text="A reply " * 100))
        minute += 10
    with open(os.path.join(folder, session_id + ".jsonl"), "w") as handle:
        for line in lines:
            line["sessionId"] = session_id
            line["cwd"] = "/Users/me/" + slug
            handle.write(json.dumps(line) + "\n")
    for i, (agent_type, model, requests, gap) in enumerate(agents):
        aid = f"a{i}"
        path = os.path.join(folder, session_id, "subagents", f"agent-{aid}.jsonl")
        with open(path, "w") as handle:
            m = 12
            for r in range(requests):
                write = 15_000 if r == 0 else 2_000
                handle.write(json.dumps(assistant(_ts(base, m), model, 0 if r == 0 else 15_000 + r * 2_000, write, 300, f"{aid}-{r}",
                                                  tools=[("Read", {"file_path": "x"})], sidechain=True)) + "\n")
                m += gap if r == 0 else 1
        with open(path[:-len(".jsonl")] + ".meta.json", "w") as handle:
            json.dump({"agentType": agent_type}, handle)


def populate(claude_dir, day=None):
    base = (day or dt.datetime(2026, 10, 18, 9, 0, tzinfo=dt.timezone.utc))
    write_session(claude_dir, "-Users-me-alix", "s-alix-" + base.strftime("%m%d"), base, [
        ("alix-worker", "claude-opus-5", 12, 1),           # F1: a build agent on Opus
        ("general-purpose", "claude-sonnet-5", 6, 1),      # F2
        ("Explore", "claude-haiku-5", 2, 1),               # tiny
        ("alix-reviewer", "claude-opus-5", 8, 7),          # F5: a 7-minute gap
    ])
    write_session(claude_dir, "-Users-me-carry", "s-carry-" + base.strftime("%m%d"), base + dt.timedelta(hours=3), [
        ("delegate:scout", "claude-haiku-5", 3, 1),
        ("delegate:worker", "claude-sonnet-5", 10, 1),
    ])
    return base
