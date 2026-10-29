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
Never blocks the owner: every git call has a timeout (GIT_TIMEOUT_S) and the whole run a deadline (BUDGET_S, well under the 10 s
limit in hooks.json). On an overrun the prompt hook and a landing print one line that the lanes are not known this time; Stop
stays silent. A step that took over SLOW_S seconds is logged in $RELAY_HOME/state/lanes-slow.log with the step's name.
Tests: tests/test_lanes_state.py
"""

from __future__ import annotations   # the hooks may run under Python 3.9: annotations are never evaluated

import json
import os
import re
import signal
import sys
import time
from typing import Any, Callable, Optional

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "lib"))
import relay_config  # noqa: E402
import relay_land  # noqa: E402
import relay_lanes  # noqa: E402
import relay_git  # noqa: E402

GIT_TIMEOUT_S = 2.5     # one git call; the run's deadline is BUDGET_S, the limit in hooks.json is 10 s
BUDGET_S = 4.0
SLOW_S = 2.0            # a step slower than this is logged
UNKNOWN = "Lanes: not known this time (the repository answered too slowly)."
CLOCK: Callable[[], float] = time.monotonic
_step = ["start"]       # the step in progress, named in the log when the deadline hits


class Overrun(Exception):
    """The run passed its deadline."""


def slow_log(step: str, seconds: float) -> None:
    """One line in the slow-step log when `seconds` is over SLOW_S; a log that cannot be written is ignored."""
    if seconds <= SLOW_S:
        return
    try:
        folder = os.path.join(relay_config.home_dir(), "state")
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, "lanes-slow.log"), "a", encoding="utf-8") as handle:
            handle.write("%s lanes hook: %s took %.1f s\n" % (time.strftime("%Y-%m-%dT%H:%M:%S"), step, seconds))
    except OSError:
        pass


def timed(step: str, call: Callable[[], Any]) -> Any:
    outer = _step[0]
    _step[0] = step
    began = CLOCK()
    try:
        return call()
    finally:
        _step[0] = outer      # the deadline names the step still running, not a nested call that returned
        slow_log(step, CLOCK() - began)


_plain_git = relay_git.git


def bound_git() -> None:
    """Every git call of the shared library gets a timeout and a timing; a timeout raises Overrun (never an empty answer)."""
    def bounded(repo: str, *args: str, timeout: Optional[float] = None, raw: bool = False) -> "tuple[int, str]":
        try:
            return timed("git " + " ".join(args[:3]), lambda: relay_git.git_strict(repo, *args, timeout=GIT_TIMEOUT_S, raw=raw))
        except relay_git.GitError:
            raise Overrun("git " + " ".join(args[:3]))

    relay_git.git = bounded     # relay_lanes and relay_git.worktrees look it up at call time


def unbound_git() -> None:
    relay_git.git = _plain_git


def arm(seconds: float) -> None:
    if hasattr(signal, "setitimer"):
        signal.signal(signal.SIGALRM, deadline)
        signal.setitimer(signal.ITIMER_REAL, seconds)


def disarm() -> None:
    if hasattr(signal, "setitimer"):
        signal.setitimer(signal.ITIMER_REAL, 0)


def deadline(signum: int, frame: Any) -> None:
    raise Overrun(_step[0])

LANDING = re.compile(r"\bgit\b[^\n;&|]*\bmerge(?=\s)[^\n;&|]*\bwt/|\brelay\s+land\s")


def context(event: str, text: str) -> None:
    json.dump({"hookSpecificOutput": {"hookEventName": event, "additionalContext": text}}, sys.stdout)


def main() -> None:
    data = json.load(sys.stdin)
    event = data.get("hook_event_name")
    if data.get("agent_id") or not data.get("cwd"):
        return
    command = (data.get("tool_input") or {}).get("command")
    landing = data.get("tool_name") == "Bash" and isinstance(command, str) and bool(LANDING.search(command))
    bound_git()
    budget = float(os.environ.get("RELAY_LANES_HOOK_BUDGET_S") or BUDGET_S)     # a test shortens it
    arm(budget)
    text: Optional[str] = None
    block: Optional[dict] = None
    try:
        text, block = work(data, event, budget)
    except Overrun as exc:
        slow_log("overrun in " + str(exc), max(budget, SLOW_S + 0.1))
        if event == "UserPromptSubmit" or (event == "PostToolUse" and landing):
            text = UNKNOWN
    finally:
        disarm()        # before anything is printed, so stdout never holds half an object
    if block is not None:
        json.dump(block, sys.stdout)
    elif text:
        context(event or "", text)


def work(data: "dict[str, Any]", event: Optional[str], budget: float) -> "tuple[Optional[str], Optional[dict]]":
    """The text to show (or the Stop refusal) for the event; nothing is printed here, so the deadline can never cut a write to stdout."""
    root = timed("config", lambda: relay_config.main_checkout(data["cwd"]))
    cfg = relay_config.load_bindings(root)
    quiet = relay_lanes.setting(cfg, "lane_quiet_hours")
    cap = relay_lanes.setting(cfg, "lanes_line_items")
    if event == "UserPromptSubmit":
        state = timed("lanes", lambda: relay_lanes.lanes_state(root, quiet))
        try:
            relay_land.note_held(root, state.waits)      # the start counter: the first time an item is held at start, once
        except Exception:
            pass                                         # a counter must never hide the lanes line
        return relay_lanes.line(state, cap) or None, None
    if event == "PostToolUse":
        command = (data.get("tool_input") or {}).get("command")
        if data.get("tool_name") != "Bash" or not isinstance(command, str) or not LANDING.search(command):
            return None, None
        timed("lanes", lambda: relay_lanes.lanes_state(root, quiet))      # the read under the deadline: nothing is written when git is blocked
        disarm()
        unbound_git()       # the writes of a close finish whole: no deadline and no timeout kills a git that holds index.lock
        closed = relay_lanes.close_landed(root)
        bound_git()
        arm(budget)         # a fresh deadline for the final read; on an overrun the closes already made are still shown
        try:
            shown = relay_lanes.line(relay_lanes.lanes_state(root, quiet), cap)
        except Overrun:
            shown = UNKNOWN
        return "\n".join(closed + ([shown] if shown else [])) or None, None
    if event == "Stop":
        session = data.get("session_id")
        if data.get("stop_hook_active") or not isinstance(session, str):
            return None, None
        stamp = os.path.join(relay_config.home_dir(), "state", "lanes-stop", session + ".json")
        reason = relay_lanes.stop_refusal(timed("lanes", lambda: relay_lanes.lanes_state(root, quiet)), stamp, relay_lanes.setting(cfg, "stop_nudge"), session)
        if reason:
            return None, {"decision": "block", "reason": reason}
    return None, None


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
