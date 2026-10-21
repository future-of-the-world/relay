"""Shared by the context hooks: where a project's handover file lives.

docs/handover.md under the session's working directory, else under the git top
level of that directory. Returns the path as a string, or None.
"""

import os
import subprocess

RELATIVE = os.path.join("docs", "handover.md")


def resolve(cwd):
    if not cwd or not os.path.isdir(cwd):
        return None
    candidate = os.path.join(cwd, RELATIVE)
    if os.path.isfile(candidate):
        return candidate
    try:
        top = subprocess.run(
            ["git", "-C", cwd, "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=3,
        ).stdout.strip()
    except Exception:
        return None
    if top:
        candidate = os.path.join(top, RELATIVE)
        if os.path.isfile(candidate):
            return candidate
    return None

