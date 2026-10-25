#!/usr/bin/env python3
"""delegate: read-only agents do not run relay commands that write. PreToolUse on Bash inside a typed agent.

A critic, checker or scout reads; it never changes the project. Their Bash is still open, and `relay migrate --all`
run from a worktree wrote CLAUDE.md, bin/ and .claude/ into the main checkout (queue item
a-reviewer-ran-relay-migrate-all-and-wrote-into). Which relay subcommands write is a fact, so a fixed list holds it
(WRITERS) and the hook refuses them for the read-only agent types (READ_ONLY). `relay sync --dry` is a read.
Catches a slip, not a determined bypass. The main session and other agents get nothing. Fails open on input of
another shape. Tests: tests/test_read_only_guard.py
"""

from __future__ import annotations   # the hooks may run under Python 3.9: annotations are never evaluated

import json
import os
import re
import shlex
import sys
from typing import Any, Optional

READ_ONLY = {"critic", "checker", "scout", "ui-reviewer", "spec-reviewer", "spec-conformance"}
# relay subcommand -> the words after it that write; None means every use writes
WRITERS = {
    "setup": None, "migrate": None, "install": None,
    "queue": {"add", "take", "release", "done", "drop", "land", "ip", "migrate"},
    "check": {"migrate"},
}
SPLIT = re.compile(r"&&|\|\||[;|&\n()`]|\$\(")


def words(part: str) -> list[str]:
    """The words of one simple command; a quoted string with spaces (`bash -c "relay setup"`) is split again."""
    try:
        found = shlex.split(part)
    except ValueError:
        found = part.split()
    out: list[str] = []
    for word in found:
        out.extend(words(word) if " " in word.strip() and word != part else [word])
    return out


def writer(command: str) -> Optional[str]:
    """The relay command in `command` that writes, as text; None when there is none."""
    for part in SPLIT.split(command):
        tokens = words(part)
        for i, token in enumerate(tokens):
            if os.path.basename(token) != "relay":
                continue
            rest = [t for t in tokens[i + 1:] if not t.startswith("-")]
            if not rest:
                continue
            sub = rest[0]
            if sub == "sync" and "--dry" not in tokens[i + 1:]:
                return "relay sync"
            if sub in WRITERS:
                words_after = WRITERS[sub]
                if words_after is None:
                    return "relay " + sub
                if len(rest) > 1 and rest[1] in words_after:
                    return "relay %s %s" % (sub, rest[1])
    return None


def decide(raw: Any) -> Optional[dict]:
    if not isinstance(raw, dict) or raw.get("hook_event_name") != "PreToolUse" or raw.get("tool_name") != "Bash":
        return None
    agent_type = raw.get("agent_type")
    if not isinstance(agent_type, str) or agent_type.split(":")[-1] not in READ_ONLY:
        return None
    tool_input = raw.get("tool_input")
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    found = writer(command) if isinstance(command, str) else None
    if not found:
        return None
    reason = ("%s writes into the project, and you are read-only. Probe it with a plan that writes nothing (`relay sync --dry`), "
              "or describe the command in the finding and leave it to the front." % found)
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                   "permissionDecisionReason": reason}}


if __name__ == "__main__":
    try:
        out = decide(json.load(sys.stdin))
        if out:
            json.dump(out, sys.stdout)
    except Exception:
        pass
    sys.exit(0)
