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

READ_ONLY = {"critic", "checker", "scout", "spec-reviewer", "spec-conformance"}
# every top-level relay subcommand is in WRITERS (it writes) or READS (it does not); a test fails when bin/relay gains one
# that is in neither. WRITERS: subcommand -> the words after it that write; None means every use writes.
WRITERS: dict[str, Optional[set[str]]] = {
    "setup": None, "migrate": None, "install": None, "sync": None, "candidate": None, "calibrate": None, "gate": None,
    "bench": None, "land": None,
    "queue": {"add", "take", "start", "release", "done", "drop", "land", "ip", "migrate", "note", "edit"},
    "check": {"migrate", "owner"},
    "improve": {"adopt"},
    "license": {"add"},
}
READS = {"status", "report", "profile", "doctor", "flows", "rules", "changed", "precheck", "metrics"}
# the words after a writing-or-mixed subcommand that only read (the other words of WRITERS[sub] is None are writes)
READ_WORDS = {
    "bench": {"list"},
    "queue": {"count", "show", "history", "check"},
    "check": {"show", "findings", "record"},   # record is the judge's own way to write its verdict
    "improve": {"suggest", "log"},
    "license": {"check"},
}
PASS_THROUGH = {"env", "exec", "command", "nohup", "time", "sudo"}
SHELLS = {"sh", "bash", "zsh", "dash"}
SHELL_C = re.compile(r"^-[a-z]*c$")
PYTHON = re.compile(r"^python[0-9.]*$")


def simple_commands(command: str) -> list[str]:
    """Split on ; && || | & newline ( ) backtick and $( that are outside quotes, so a quoted word stays whole."""
    parts: list[str] = []
    current: list[str] = []
    quote = ""
    i = 0
    while i < len(command):
        char = command[i]
        if quote:
            if char == "\\" and quote == '"' and i + 1 < len(command):
                current.append(command[i:i + 2])
                i += 2
                continue
            if char == quote:
                quote = ""
        elif char in "'\"":
            quote = char
        elif char == "\\" and i + 1 < len(command):
            current.append(command[i:i + 2])
            i += 2
            continue
        elif char in ";&|\n()`" or command.startswith("$(", i):
            parts.append("".join(current))
            current = []
            i += 2 if command.startswith("$(", i) else 1
            continue
        current.append(char)
        i += 1
    parts.append("".join(current))
    return parts


def words(part: str) -> list[str]:
    try:
        return shlex.split(part)
    except ValueError:
        return part.split()


def relay_call(tokens: list[str]) -> Optional[str]:
    """The program of one simple command, looked through VAR=x, env, python3, sh -c and eval; a writing relay call as text."""
    i = 0
    while i < len(tokens):
        token = tokens[i]
        base = os.path.basename(token)
        if "=" in token and not token.startswith("-") and "/" not in token.split("=")[0]:
            i += 1   # VAR=x
        elif base in PASS_THROUGH or PYTHON.match(base):
            i += 1
            while i < len(tokens) and (tokens[i].startswith("-") or (base in PASS_THROUGH and "=" in tokens[i])):
                i += 1
        elif base in SHELLS:
            for j in range(i + 1, len(tokens) - 1):
                if SHELL_C.match(tokens[j]):
                    return writer(tokens[j + 1])
            i += 1
            while i < len(tokens) and tokens[i].startswith("-"):
                i += 1
        elif base == "eval":
            return writer(" ".join(tokens[i + 1:]))
        elif base == "relay":
            return relay_writes(tokens[i + 1:])
        else:
            return None
    return None


def relay_writes(args: list[str]) -> Optional[str]:
    rest = [t for t in args if not t.startswith("-")]
    if not rest or rest[0] not in WRITERS:
        return None
    sub = rest[0]
    second = rest[1] if len(rest) > 1 else ""
    if sub == "sync":
        return None if "--dry" in args else "relay sync"
    after = WRITERS[sub]
    if after is None:
        return None if second in READ_WORDS.get(sub, ()) else "relay " + sub
    return "relay %s %s" % (sub, second) if second in after else None


def writer(command: str) -> Optional[str]:
    """The relay command in `command` that writes, as text; None when there is none."""
    for part in simple_commands(command):
        found = relay_call(words(part))
        if found:
            return found
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
