"""Reads `front.feature_lanes` for the lanes (split out of relay_lanes.py to keep it under the size limit).

Tests: tests/test_lanes_state.py
"""

from __future__ import annotations

from typing import Optional

import relay_kit


def feature_lanes_read(main: str, capacity: int) -> tuple[int, Optional[str]]:
    """`front.feature_lanes` of the project's kit.toml: lanes kept for features (the owner's 3 and 3 split, 29 Oct). Default 0 (no split).
    relay_kit checks the value (not a whole number or outside 0..8: 0, and the problem it names); here it must also fit `capacity`:
    above it, 0 and the note that says so (clamping would turn a 3 and 3 into all features)."""
    value = relay_kit.load(main).get("front", "feature_lanes")
    if 0 <= value <= capacity:
        return value, None
    return 0, f"feature_lanes {value} is out of bounds 0-{capacity}: 0 is used"


def feature_lanes_setting(main: str, capacity: int) -> int:
    """The value of `feature_lanes_read`, without its note."""
    return feature_lanes_read(main, capacity)[0]
