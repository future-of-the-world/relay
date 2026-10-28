#!/usr/bin/env python3
"""front: fills free lanes (design: docs/plans or the queue item choose-which-unblocked-items-start-together).

One script, three events:
  UserPromptSubmit  one line "Lanes: 4 of 6 running; start: <slug> (fix, ip 92), design: <slug> (feature, ip 96); waits: <slug> (<file>, <branch>)"
                    when a lane is free and an item can start, or an item landed and is still open; silent otherwise.
  PostToolUse       the same line after a landing (`git merge ... wt/<x>` in Bash), after closing each landed feature with its merge sha.
  Stop              refuses the end of the turn once per observed lane state while lanes are free and an item can start, until the
                    front starts it or says why it holds. Nothing when `stop_hook_active` is true; the stamp is per session under
                    $RELAY_HOME/state/lanes-stop/, outside the repository.
Settings and bounds: lib/relay_lanes.py header. Silent outside a project with .relay/ and for subagents. Fails open.
Tests: tests/test_lanes_state.py
"""

from __future__ import annotations   # the hooks may run under Python 3.9: annotations are never evaluated

import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "lib"))
import relay_config  # noqa: E402
import relay_lanes  # noqa: E402

LANDING = re.compile(r"\bgit\b[^\n;&|]*\bmerge(?=\s)[^\n;&|]*\bwt/")


def context(event: str, text: str) -> None:
    json.dump({"hookSpecificOutput": {"hookEventName": event, "additionalContext": text}}, sys.stdout)


def main() -> None:
    data = json.load(sys.stdin)
    event = data.get("hook_event_name")
    if data.get("agent_id") or not data.get("cwd"):
        return
    root = relay_config.main_checkout(data["cwd"])
    cfg = relay_config.load_bindings(root)
    quiet = relay_lanes.setting(cfg, "lane_quiet_hours")
    cap = relay_lanes.setting(cfg, "lanes_line_items")
    if event == "UserPromptSubmit":
        shown = relay_lanes.line(relay_lanes.lanes_state(root, quiet), cap)
        if shown:
            context(event, shown)
    elif event == "PostToolUse":
        command = (data.get("tool_input") or {}).get("command")
        if data.get("tool_name") != "Bash" or not isinstance(command, str) or not LANDING.search(command):
            return
        closed = relay_lanes.close_landed(root)
        shown = relay_lanes.line(relay_lanes.lanes_state(root, quiet), cap)
        text = "\n".join(closed + ([shown] if shown else []))
        if text:
            context(event, text)
    elif event == "Stop":
        session = data.get("session_id")
        if data.get("stop_hook_active") or not isinstance(session, str):
            return
        stamp = os.path.join(relay_config.home_dir(), "state", "lanes-stop", session + ".json")
        reason = relay_lanes.stop_refusal(relay_lanes.lanes_state(root, quiet), stamp, relay_lanes.setting(cfg, "stop_nudge"), session)
        if reason:
            json.dump({"decision": "block", "reason": reason}, sys.stdout)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
