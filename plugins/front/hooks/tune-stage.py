#!/usr/bin/env python3
"""front: name the `front:tune` skill when the owner's prompt is about the setup
itself (models, effort, cost, comparing setups, how agents work). One line of
additional context; nothing when the prompt is about the project's work. Fails open."""

import json
import re
import sys

PATTERNS = [
    r"\b(haiku|sonnet|opus)\b",
    r"\b(effort|cheaper|cost(s|ing)?|expensive|usage|tokens?|spend|budget)\b.*\b(setup|agents?|workers?|sessions?|week|today|yesterday|this|that|it)\b",
    r"\b(what|how much) (did|does|do|is)\b.*\b(cost|spend|usage)\b",
    r"\b(compare|comparison|side by side|which (one|setup|is better)|a/b|bench(mark)?)\b",
    r"\b(try|use|switch to|instead of)\b.*\b(model|effort|setup|profile|configuration)\b",
    r"\b(workers?|scouts?|runners?|thinkers?|critics?|reviewers?|agents?)\b.*\b(should|flow|plan more|smaller tasks|more planning|differently|instead)\b",
    r"\b(adopt|keep|revert) (it|that|the (candidate|change|new setup))\b",
    r"\brelay (status|report|bench|improve|profile)\b",
]


def main():
    data = json.load(sys.stdin)
    if data.get("hook_event_name") != "UserPromptSubmit" or data.get("agent_id"):
        return
    prompt = data.get("prompt") or ""
    if prompt.lstrip().startswith("/"):
        return
    if not any(re.search(p, prompt, re.I) for p in PATTERNS):
        return
    json.dump({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext":
        "This looks like a request about the setup itself (models, effort, cost, how agents work, comparing two ways). "
        "Load the `front:tune` skill with the Skill tool before the first step; it turns the request into a candidate, "
        "a bench and a plain-words verdict. The `relay` command is on PATH."}}, sys.stdout)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
