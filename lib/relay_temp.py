"""Where relay's tests keep their temporary files: the roots of the temporary folders and the test folders on a path (used by the gate's sweep of leftovers, lib/relay_gate.py)."""
import os
import subprocess
import tempfile
from typing import Sequence

TEMP_PREFIXES = ("relay-run-", "relay-gate-", "relay-home-")      # folder names relay's tests make under the temporary folder


def temp_roots() -> list[str]:
    """The folders a test's temporary files live under, each in its given and its resolved form (`/var/folders/..` and `/private/var/folders/..`
    on macOS: `$TMPDIR` holds the first, `ps` shows the second): the process's temporary folder, the user's temporary folder, /tmp."""
    found = [tempfile.gettempdir(), "/tmp"]
    try:
        done = subprocess.run(["getconf", "DARWIN_USER_TEMP_DIR"], capture_output=True, text=True, timeout=10)
        if done.returncode == 0 and done.stdout.strip():
            found.append(done.stdout.strip())
    except (OSError, subprocess.SubprocessError):
        pass
    roots: list[str] = []
    for folder in found:
        for form in (folder, os.path.realpath(folder)):
            form = form.rstrip("/")
            if form and form not in roots:
                roots.append(form)
    return roots


def under(path: str, roots: Sequence[str]) -> bool:
    real = os.path.realpath(path)
    return any(real == root or real.startswith(root + os.sep) for root in roots)


def prefixed_folders(path: str, roots: Sequence[str]) -> list[str]:
    """The folders on `path` (under one of `roots`) whose name starts with a TEMP_PREFIXES entry, outermost first; [] when `path` is outside the roots."""
    for root in roots:
        if path.startswith(root + "/"):
            parts = path[len(root) + 1:].split("/")
            return [root + "/" + "/".join(parts[:i + 1]) for i, part in enumerate(parts) if part.startswith(TEMP_PREFIXES)]
    return []
