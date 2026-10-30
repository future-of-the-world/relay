#!/usr/bin/env python3
"""front: refuses the end of the front's turn once while a digest or a spend alert is due.

Stop (every turn of the front, notification turns included): runs the due check of `relay digest --due` (lib/relay_digest.py). When it
names a reason, the end of the turn is refused once for that exact state, with the next step in the message: run `relay digest`, send
the page to the owner in plain words, then `relay digest --sent` (for a spend alert: send the one line, then `relay digest --alert-sent`).
Nothing when `stop_hook_active` is true, for subagents, outside a project with .relay/, or when nothing is due (the stamp is then
cleared, so the next due state is refused again). The stamp is per session under $RELAY_HOME/state/digest-stop/, outside the repository.
Fails open: a git call that does not answer, or a run over BUDGET_S, ends the turn as it was, with a one-line note.
Tests: tests/test_digest.py (class StopHook)
"""

from __future__ import annotations   # the hooks may run under Python 3.9: annotations are never evaluated

import json
import os
import re
import signal
import sys
from typing import Any, Optional

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "lib"))
import relay_config  # noqa: E402
import relay_digest  # noqa: E402
import relay_git  # noqa: E402

BUDGET_S = 4.0       # well under the 10 s limit in hooks.json


class Overrun(Exception):
    """The run passed its deadline."""


def deadline(signum: int, frame: Any) -> None:
    raise Overrun()


def refusal(lines: "list[str]", stamp: str) -> Optional[str]:
    """The reason to refuse the end of the turn, or None. One refusal per due state: `stamp` keeps the last state refused."""
    key = "\n".join(lines)
    if not lines:
        try:
            os.remove(stamp)
        except OSError:
            pass
        return None
    try:
        with open(stamp, encoding="utf-8") as handle:
            if json.load(handle).get("state") == key:
                return None
    except (OSError, ValueError, AttributeError):
        pass
    os.makedirs(os.path.dirname(stamp), exist_ok=True)
    with open(stamp, "w", encoding="utf-8") as handle:
        json.dump({"state": key}, handle)
    steps = []
    if any(x.startswith("digest due") for x in lines):
        steps.append("run `relay digest`, send the page to the owner in plain words (his language, every decision listed), then run `relay digest --sent`")
    if any(x.startswith("alert due") for x in lines):
        steps.append("send the owner the one spend line in plain words, then run `relay digest --alert-sent`")
    return "; ".join(lines) + ". Next: " + "; and ".join(steps) + "."


def main() -> None:
    data = json.load(sys.stdin)
    session = data.get("session_id")
    if (data.get("hook_event_name") != "Stop" or data.get("agent_id") or data.get("stop_hook_active") or not data.get("cwd")
            or not isinstance(session, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", session)):
        return
    if not relay_git.has_relay(data["cwd"]):
        return
    stamp = os.path.join(relay_config.home_dir(), "state", "digest-stop", session + ".json")
    if hasattr(signal, "setitimer"):
        signal.signal(signal.SIGALRM, deadline)
        signal.setitimer(signal.ITIMER_REAL, float(os.environ.get("RELAY_DIGEST_HOOK_BUDGET_S") or BUDGET_S))
    out: Optional[dict] = None
    try:
        root = relay_config.main_checkout(data["cwd"])
        default = relay_git.default_branch(root)
        if default is None:
            return
        reason = refusal(relay_digest.due(root, default, relay_config.load_bindings(root)), stamp)
        if reason:
            out = {"decision": "block", "reason": reason}
    except (Overrun, relay_digest.DigestError, OSError) as exc:
        out = {"systemMessage": "digest hook: could not tell whether a digest is due (%s)" % (str(exc) or type(exc).__name__)}
    finally:
        if hasattr(signal, "setitimer"):
            signal.setitimer(signal.ITIMER_REAL, 0)     # before anything is printed, so stdout never holds half an object
    if out:
        json.dump(out, sys.stdout)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
