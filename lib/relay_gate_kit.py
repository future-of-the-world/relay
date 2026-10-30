"""The settings schema `relay gate` checks a branch's .claude/kit.toml with: the branch's own lib/relay_kit.py."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from types import ModuleType

# Runs in a child process with the branch's lib/ first on the path, so the branch's relay_kit meets the branch's own helper modules.
_CHILD = (
    "import json, sys\n"
    "sys.path.insert(0, sys.argv[1])\n"
    "import relay_kit\n"
    "print(json.dumps([p.line() for p in relay_kit.load(sys.argv[2]).problems]))\n"
)
CHILD_TIMEOUT = 60


def settings_problems(worktree: str, installed: ModuleType) -> list[str]:
    """The lines of the settings problems of the branch's .claude/kit.toml, found by the branch's own lib/relay_kit.py (the code
    under test, so a branch that renames or adds a key passes); by the installed module when the branch has none. A branch module
    that does not load, or lacks load(root).problems or Problem.line(), raises RuntimeError: the caller refuses the gate."""
    lib = os.path.join(worktree, "lib")
    if not os.path.isfile(os.path.join(lib, "relay_kit.py")):
        return [p.line() for p in installed.load(worktree).problems]
    try:
        done = subprocess.run([sys.executable, "-I", "-c", _CHILD, lib, worktree], capture_output=True, text=True,
                              timeout=CHILD_TIMEOUT)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError("the branch's lib/relay_kit.py cannot be run: %s" % exc)
    if done.returncode != 0:
        last = (done.stderr.strip().splitlines() or ["exit %d" % done.returncode])[-1]
        raise RuntimeError("the branch's lib/relay_kit.py cannot be loaded or does not give load(root).problems with line(): %s" % last)
    try:
        lines = json.loads(done.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        raise RuntimeError("the branch's lib/relay_kit.py printed no list of problems")
    return [str(x) for x in lines]
