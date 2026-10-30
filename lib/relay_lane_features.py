"""Reads `front.feature_lanes` for the lanes (split out of relay_lanes.py to keep it under the size limit).

Tests: tests/test_lanes_state.py
"""

from __future__ import annotations

from typing import Optional

import relay_config
import relay_git


def feature_lanes_read(main: str, capacity: int) -> tuple[int, Optional[str]]:
    """`front.feature_lanes` of the project's kit.toml: lanes kept for features (the owner's 3 and 3 split, 29 Oct). Default 0 (no split),
    bound 0..capacity; out of bounds or not a whole number: the default, and the note that says so (clamping would turn a 3 and 3 into all features)."""
    try:
        value = relay_config.get(relay_config.load_bindings(main), "front.feature_lanes", None)
    except (OSError, ValueError):
        return 0, None
    if value is None:
        return 0, None
    if isinstance(value, bool) or not isinstance(value, int):
        return 0, f"feature_lanes {value} is not a whole number: 0 is used"
    if 0 <= value <= capacity:
        return value, None
    return 0, f"feature_lanes {value} is out of bounds 0-{capacity}: 0 is used"


def feature_lanes_setting(main: str, capacity: int) -> int:
    """The value of `feature_lanes_read`, without its note."""
    return feature_lanes_read(main, capacity)[0]


def own_commits(main: str, branch: str) -> bool:
    """The branch's reflog holds an entry other than its creation, a fast-forward (git appends "(no commit created; -m option ignored)"
    when a message was given) or a reset: a branch that only took the default branch has no commit of its own."""
    rc, out = relay_git.git(main, "reflog", "show", "--format=%gs", "refs/heads/" + branch)
    if rc != 0:
        return False
    return any(not (s.startswith("branch: Created from") or s.startswith("reset: moving to") or "Fast-forward" in s) for s in out.splitlines())
