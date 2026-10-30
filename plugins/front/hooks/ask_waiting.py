#!/usr/bin/env python3
"""front: names the questions that wait for the owner's answer.

On every owner message (UserPromptSubmit), one line per question that was recorded on a queue item with `relay queue note` and has no
answer yet, so the answer is recorded in the item and not lost (rules/queue.md). A question older than `ask_reminder_days` is no
longer named. Settings, in the project's .claude/kit.toml under [front]:
  ask_reminder_days   default 7, bound 1-30   (at 30 a question never answered is named on every message for a month)
  ask_reminder_lines  default 5, bound 1-20   (at 20 a front with many open questions carries 20 lines per message)
Silent outside a project with .relay/ and when nothing waits. Fails open. Tests: tests/test_queue_notes.py (class AskHook)
"""

from __future__ import annotations   # the hooks may run under Python 3.9: annotations are never evaluated

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "lib"))
import relay_config  # noqa: E402
import relay_kit  # noqa: E402
import relay_queue  # noqa: E402


def main() -> None:
    data = json.load(sys.stdin)
    if data.get("hook_event_name") != "UserPromptSubmit" or data.get("agent_id") or not data.get("cwd"):
        return
    kit = relay_kit.load(relay_config.main_checkout(data["cwd"]))
    lines = relay_queue.waiting_lines(data["cwd"], kit.get("front", "ask_reminder_days"), kit.get("front", "ask_reminder_lines"))
    # a wrong value of this hook's own keys (or a broken file) is said in the context, not on stderr
    note = relay_kit.say([p for p in kit.problems_of("front") if p is kit.broken or "ask_reminder" in p.where])
    if note:
        lines = lines + [note]
    if lines:
        json.dump({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": "\n".join(lines)}}, sys.stdout)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
