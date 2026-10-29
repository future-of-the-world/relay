"""Reading the gate's step logs back as lines (split from relay_ci)."""
from __future__ import annotations

import os
import re


def outcome(directory: str) -> list[str]:
    """What a run did, as lines that must not change when an inert file does: each step's result, the library test count
    ("Ran N tests"); hooks-live's lines are not in it: only a full run runs it, with a live model."""
    lines: list[str] = []
    lines += _read_lines(os.path.join(directory, ".ci", "results.txt"))
    lines += [re.sub(r" in [0-9.]+s", "", ln, count=1)
              for ln in _read_lines(os.path.join(directory, ".ci", "steps", "library-tests.log")) if ln.startswith("Ran ")]
    return lines


def _read_lines(path: str) -> list[str]:
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            return handle.read().splitlines()
    except FileNotFoundError:
        return []


def _read_lines_keep(path: str) -> list[str]:
    with open(path, encoding="utf-8", errors="replace") as handle:
        return handle.readlines()
