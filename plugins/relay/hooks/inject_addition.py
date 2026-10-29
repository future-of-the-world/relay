#!/usr/bin/env python3
"""SubagentStart, PostToolUse(Skill) and UserPromptSubmit hook inject-addition (inject-addition.sh execs this file).

SubagentStart, PostToolUse(Skill) and UserPromptSubmit hook: put a project's
addition in front of the shared role that needs it.

A project keeps its rules for an agent in `.claude/kit/<name>.md`. When
an agent `<plugin>:<name>` starts, the skill `<plugin>:<role>` has just been
loaded with the Skill tool, or the owner has typed the stage as a slash
command (`/openspec:archive ...`: then no Skill call happens, the skill comes in
with the prompt), this hook hands that file to the agent or session as
additional context, so the project's rules are always there and no
instruction has to be obeyed first. No file, nothing is injected.

A project may also keep rules for a whole role in `.claude/kit/<role>.md`,
role one of lookup, run, build, fix, think, judge. An agent's role is read
from `../lib/agent-roles.tsv` (`<plugin>:<name><TAB><role>`, written by
`relay sync agents` from the agents' relay:base markers); an agent not in
the map, or no map, gets its own file only. At SubagentStart the role file
comes first, then the agent's file, whose rules win where they differ
(project per agent > project per role > flow > base). Skills and typed
stages have no role. With no role file the output is what it was before
role files existed (test I4).

Only the framework's own plugins are served (core, openspec, delegate,
front): another plugin's `code-reviewer` must not receive a
project's `code-reviewer.md`.

Project root = the git top-level of the hook's cwd (inside a worktree, that
worktree's own root), else the cwd.

Hook input (verified on Claude Code 2.1.302): SubagentStart has `agent_type`
(`<plugin>:<role>` for a plugin agent); PostToolUse with matcher Skill has
`tool_input.skill`; UserPromptSubmit has `prompt`. Output is
`hookSpecificOutput.additionalContext`.

Tests: tests/test_hook_inject_addition.py
"""
import json
import os
import re
import subprocess
import sys
from typing import Any, Optional

HERE = os.path.dirname(os.path.realpath(__file__))
SPACE = r"[ \t\n\r\f\v]"
ROLES = ("lookup", "run", "build", "fix", "think", "judge")


def text_of(value: Any) -> str:
    return value if isinstance(value, str) else ""


def read(path: str) -> str:
    with open(path, encoding="utf-8", errors="replace") as handle:
        return handle.read()


def emit(event: str, context: str) -> None:
    sys.stdout.write(json.dumps({"hookSpecificOutput": {"hookEventName": event, "additionalContext": context}}, indent=2, ensure_ascii=False) + "\n")


def name_of(event: dict[str, Any], kind: str) -> Optional[str]:
    if kind == "SubagentStart":
        return text_of(event.get("agent_type"))
    if kind == "PostToolUse":
        tool_input = event.get("tool_input")
        return text_of(tool_input.get("skill")) if event.get("tool_name") == "Skill" and isinstance(tool_input, dict) else ""
    if kind == "UserPromptSubmit":
        # a typed stage: the prompt starts with /<plugin>:<role>, then a space or its end
        found = re.match(r"%s*/([a-z0-9][a-z0-9_-]*:[a-z][a-z0-9-]*)(%s|\Z)" % (SPACE, SPACE), text_of(event.get("prompt")))
        return found.group(1) if found else None
    return None


def main() -> None:
    try:
        event = json.loads(sys.stdin.buffer.read().decode("utf-8", errors="replace"))
    except ValueError:
        return
    if not isinstance(event, dict):
        return
    kind = text_of(event.get("hook_event_name"))
    name = name_of(event, kind)
    if name is None:
        return
    cwd = text_of(event.get("cwd")) or os.getcwd()
    # <plugin>:<role> of a framework plugin, nothing else (no path can leave .claude/kit/)
    named = re.fullmatch(r"(relay|openspec|delegate|front):([a-z][a-z0-9-]*)", name)
    if not named:
        return
    role = named.group(2)
    done = subprocess.run(["git", "-C", cwd, "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    root = done.stdout.strip() if done.returncode == 0 else cwd
    file = os.path.join(root, ".claude", "kit", role + ".md")
    # the role's own file (agents only): the role named in the map, never an agent's or skill's name
    role_name = ""
    if kind == "SubagentStart":
        table = os.path.join(HERE, "..", "lib", "agent-roles.tsv")
        if os.path.isfile(table):
            mapped = ""
            for line in read(table).split("\n"):
                fields = line.split("\t")
                if fields[0] == name:
                    mapped = fields[1] if len(fields) > 1 else ""
                    break
            if mapped in ROLES and mapped != role and os.path.isfile(os.path.join(root, ".claude", "kit", mapped + ".md")):
                role_name = mapped
    if role_name:
        role_text = read(os.path.join(root, ".claude", "kit", role_name + ".md"))
        head = "Project rules for the %s role (.claude/kit/%s.md of this project)\n\n" % (role_name, role_name) + role_text
        if os.path.isfile(file):
            emit(kind, head + "\nProject rules for %s (.claude/kit/%s.md); where they differ from the role's rules, these win\n\n" % (name, role) + read(file))
        else:
            emit(kind, head)
        return
    if not os.path.isfile(file):
        return
    emit(kind, "Project addition for %s (.claude/kit/%s.md of this project). It belongs to the shared role; where it differs from the shared text, it wins.\n\n"
         % (name, role) + read(file))


if __name__ == "__main__":
    main()
