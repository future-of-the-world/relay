#!/usr/bin/env python3
"""delegate: the turn-limit note. PreToolUse inside a typed delegate agent.

An agent that runs out of turns (maxTurns in its agent file) dies without a hand-back. The count of its tool
calls is a fact, so code counts it: the agent's own transcript holds one tool_use per call made so far. From
RESERVE calls before the limit (8; 2 for an agent with fewer than 40 turns, the runner) each call gets a note
beside it: write the report and hand back now, BLOCKED with `still running: <log>` if a job is still running.
Never a refusal. The main session and agents of other plugins get nothing. Fails open.
Tests: tests/test_turn_limit.py
"""

from __future__ import annotations   # the hooks may run under Python 3.9: annotations are never evaluated

import json
import os
import re
import sys
from dataclasses import dataclass
from typing import Any, Optional

HERE = os.path.dirname(os.path.abspath(__file__))
AGENTS = os.path.join(HERE, "..", "agents")
PLUGIN = "delegate"
BIG_AGENT_TURNS = 40


@dataclass
class HookInput:
    """The fields of the PreToolUse input this hook reads, checked once here."""
    agent_id: str
    agent_type: str
    transcript: str


def parse(raw: Any) -> Optional[HookInput]:
    """None unless the input comes from a typed delegate agent whose transcript can be found."""
    if not isinstance(raw, dict) or raw.get("hook_event_name") != "PreToolUse":
        return None
    agent_id, agent_type = raw.get("agent_id"), raw.get("agent_type")
    if not isinstance(agent_id, str) or not agent_id or not isinstance(agent_type, str):
        return None
    if not agent_type.startswith(PLUGIN + ":"):
        return None
    path = raw.get("agent_transcript_path")
    if not (isinstance(path, str) and os.path.isfile(path)):
        safe = "".join(ch for ch in agent_id if ch.isalnum() or ch in "-_")
        session = raw.get("transcript_path")
        if not safe or not isinstance(session, str) or not session.endswith(".jsonl"):
            return None
        path = os.path.join(session[:-len(".jsonl")], "subagents", "agent-%s.jsonl" % safe)
        if not os.path.isfile(path):
            return None
    return HookInput(agent_id, agent_type, path)


def max_turns(agent_type: str) -> Optional[int]:
    role = "".join(ch for ch in agent_type.split(":", 1)[1] if ch.isalnum() or ch in "-_")
    try:
        with open(os.path.join(AGENTS, role + ".md"), encoding="utf-8") as handle:
            head = handle.read(4000).split("---")[1]
    except (OSError, IndexError):
        return None
    found = re.search(r"^maxTurns:\s*(\d+)\s*$", head, re.MULTILINE)
    return int(found.group(1)) if found else None


def calls_made(transcript: str) -> int:
    count = 0
    with open(transcript, encoding="utf-8") as handle:
        for line in handle:
            try:
                node = json.loads(line)
            except ValueError:
                continue
            content = (node.get("message") or {}).get("content") if isinstance(node, dict) else None
            if node.get("type") == "assistant" and isinstance(content, list):
                count += sum(1 for part in content if isinstance(part, dict) and part.get("type") == "tool_use")
    return count


def note(raw: Any) -> Optional[dict]:
    hook = parse(raw)
    limit = max_turns(hook.agent_type) if hook else None
    if not hook or not limit:
        return None
    this_call = calls_made(hook.transcript) + 1   # PreToolUse: the current call is not in the transcript yet
    reserve = 8 if limit >= BIG_AGENT_TURNS else 2
    if this_call < limit - reserve:
        return None
    left = max(limit - this_call, 0)
    text = ("Turn limit: this is your tool call %d of %d (%d left). Write your report now and hand back; if a job is "
            "still running, hand back BLOCKED with `still running: <log>` (a runner replies RUNNING with the log path). "
            "Start no new step." % (this_call, limit, left))
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": text}}


if __name__ == "__main__":
    try:
        out = note(json.load(sys.stdin))
        if out:
            json.dump(out, sys.stdout)
    except Exception:
        pass
    sys.exit(0)
