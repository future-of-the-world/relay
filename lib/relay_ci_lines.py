"""Reading the gate's step logs back as lines (split from relay_ci)."""
from __future__ import annotations



def _read_lines(path: str) -> list[str]:
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            return handle.read().splitlines()
    except FileNotFoundError:
        return []


def _read_lines_keep(path: str) -> list[str]:
    with open(path, encoding="utf-8", errors="replace") as handle:
        return handle.readlines()
