"""The gate's python pin: refuse to run on a python other than the one deps.toml pins (split from relay_ci)."""
from __future__ import annotations

import os
import sys


def python_problem(root: str, running: tuple[int, int, int] | None = None) -> str | None:
    """A refusal line when the python running the gate is not the one deps.toml pins (exact python3 entry), else None."""
    import tomllib
    with open(os.path.join(root, "deps.toml"), "rb") as handle:
        entries = tomllib.load(handle).get("dep", [])
    pins = [d for d in entries if d.get("name") == "python3" and d.get("exact") is True and isinstance(d.get("min"), str)]
    if not pins:
        return None
    want = pins[0]["min"]
    have = running or (sys.version_info[0], sys.version_info[1], sys.version_info[2])
    if ".".join(map(str, have)) == want:
        return None
    return ("ci: python3 is %s but relay pins %s (deps.toml): make python3 %s (uv python install --default %s, with ~/.local/bin first on PATH), then run bin/ci again"
            % (".".join(map(str, have)), want, want, want))
