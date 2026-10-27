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
from typing import Any

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "lib"))
import relay_config  # noqa: E402
import relay_queue  # noqa: E402

DAYS = (7, 1, 30)     # default, lowest, highest
LINES = (5, 1, 20)


def setting(cfg: Any, key: str, bounds: tuple) -> int:
    """The setting `front.<key>` clamped to its bounds; the default when it is missing or not a whole number."""
    value = relay_config.get(cfg, "front." + key, bounds[0])
    if isinstance(value, bool) or not isinstance(value, int):
        return bounds[0]
    return max(bounds[1], min(bounds[2], value))


def main() -> None:
    data = json.load(sys.stdin)
    if data.get("hook_event_name") != "UserPromptSubmit" or data.get("agent_id") or not data.get("cwd"):
        return
    cfg = relay_config.load_bindings(relay_config.main_checkout(data["cwd"]))
    lines = relay_queue.waiting_lines(data["cwd"], setting(cfg, "ask_reminder_days", DAYS), setting(cfg, "ask_reminder_lines", LINES))
    if lines:
        json.dump({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": "\n".join(lines)}}, sys.stdout)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
