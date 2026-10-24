#!/usr/bin/env python3
"""front: the context budget. Keeps the main session and every agent small.

- UserPromptSubmit: the first prompt after the session crosses HANDOVER_AT adds
  a note: bring the handover file up to date and carry on; compaction follows by
  itself. One note per crossing (a marker under ~/.relay/state/).
- PostToolUse inside a subagent: once the agent's own context passes WRAP_AT, a
  note beside the tool result tells it to finish the step in hand and hand back
  with what remains; repeated every STEP tokens. Never a refusal, so the agent
  can always write its report.

Forks are the routing guard's business (delegate plugin). Limits per shell:
RELAY_CTX_HANDOVER_AT (350000), RELAY_CTX_WRAP_AT (200000), RELAY_CTX_STEP (30000).
Fails open. Tests: plugins/front/tests/budget.test.sh
"""

from __future__ import annotations   # the hooks may run under Python 3.9: annotations are never evaluated

import json
import os
import sys
from typing import Any

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "lib"))
import handover_path  # noqa: E402
import relay_transcripts  # noqa: E402

HANDOVER_AT = int(os.environ.get("RELAY_CTX_HANDOVER_AT", "350000"))
WRAP_AT = int(os.environ.get("RELAY_CTX_WRAP_AT", "200000"))
STEP = int(os.environ.get("RELAY_CTX_STEP", "30000"))
STATE_DIR = os.path.join(os.path.expanduser(os.environ.get("RELAY_HOME") or "~/.relay"), "state")


def k(n: int) -> str:
    return f"{n // 1000}k"


def marker(name: object) -> str | None:
    safe = "".join(ch for ch in str(name) if ch.isalnum() or ch in "-_")
    return os.path.join(STATE_DIR, f"budget-{safe}") if safe else None


def agent_transcript(data: dict[str, Any]) -> str | None:
    path = data.get("agent_transcript_path")
    if path and os.path.isfile(path):
        return path
    agent_id = "".join(ch for ch in str(data.get("agent_id") or "") if ch.isalnum() or ch in "-_")
    transcript = data.get("transcript_path") or ""
    if not agent_id or not transcript.endswith(".jsonl"):
        return None
    candidate = os.path.join(transcript[:-len(".jsonl")], "subagents", f"agent-{agent_id}.jsonl")
    return candidate if os.path.isfile(candidate) else None


def agent_note(data: dict[str, Any]) -> dict[str, Any] | None:
    path = agent_transcript(data)
    if not path:
        return None
    tokens = relay_transcripts.context_tokens_of(path)
    if not tokens or tokens <= WRAP_AT:
        return None
    level = (tokens - WRAP_AT) // max(STEP, 1)
    m = marker(f"agent-{data.get('agent_id')}-{level}")
    if m:
        if os.path.exists(m):
            return None
        os.makedirs(STATE_DIR, exist_ok=True)
        open(m, "w").close()
    text = (f"Context budget: you hold about {k(tokens)} tokens (the line is {k(WRAP_AT)}) and every further request "
            "re-reads all of it. Finish the step in hand, start no new one, write your report, and hand back now, "
            "listing the unfinished work as remaining so a fresh agent can continue.")
    return {"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": text}}


def prompt_note(data: dict[str, Any]) -> dict[str, Any] | None:
    path = data.get("transcript_path")
    if not path or not os.path.isfile(path):
        return None
    tokens = relay_transcripts.context_tokens_of(path)
    if tokens is None:
        return None
    m = marker(f"session-{data.get('session_id')}")
    if tokens <= HANDOVER_AT:
        if m and os.path.exists(m):
            os.remove(m)
        return None
    if m:
        if os.path.exists(m):
            return None
        os.makedirs(STATE_DIR, exist_ok=True)
        open(m, "w").close()
    target = handover_path.resolve(data.get("cwd"))
    where = f"Update the handover file {target} now with" if target else \
        "The project has no docs/handover.md, so write into your final message of this turn"
    text = (f"Context budget: this session is at about {k(tokens)} tokens (handover line {k(HANDOVER_AT)}). {where} "
            "the state, the decisions since it was last written (who made each), the owner's latest instructions in "
            "their words, and the exact next step; commit it if the project commits docs. Then continue without asking "
            "the owner to /clear: compaction happens by itself and the handover file is named to you afterwards.")
    return {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": text}}


def main() -> None:
    data = json.load(sys.stdin)
    event = data.get("hook_event_name")
    out = None
    if event == "PostToolUse" and data.get("agent_id"):
        out = agent_note(data)
    elif event == "UserPromptSubmit" and not data.get("agent_id"):
        out = prompt_note(data)
    if out:
        json.dump(out, sys.stdout)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
