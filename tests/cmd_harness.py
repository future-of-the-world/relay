"""Run bin/relay as a user would, in temporary folders, for the per-command test files.

Convention for every command's own test file (tests/test_cmd_<cmd>.py, or tests/test_cmd_<cmd>_<action>.py for an
action of a package command), written when the command moves to lib/relay_cmd/:
  1. `relay <cmd> --help` prints the usage lines it printed before the move (a literal, copied from before the move);
  2. one smoke case with harmless arguments asserting the exit code and one output line (for a command that cannot run
     in a temporary tree, its usage refusal, e.g. `relay land` with no branch: exit 2 and its usage line).
Together they catch an off-by-one in how the dispatcher hands args to a module's run().

`run_relay(args)` uses a temporary HOME, RELAY_HOME, RELAY_ROOT and working folder (a plain folder, not a repository,
unless `git=True`), and returns the exit code, stdout, stderr and the files that appeared in any of them.
"""
import os
import subprocess
import sys
import tempfile
from typing import NamedTuple

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
RELAY = os.path.join(ROOT, "bin", "relay")


class Ran(NamedTuple):
    code: int
    stdout: str
    stderr: str
    written: list[str]


def snapshot(top: str) -> list[str]:
    found = []
    for base, dirs, files in os.walk(top):
        found += [os.path.relpath(os.path.join(base, n), top) for n in dirs + files]
    return sorted(found)


def run_relay(args: list[str], git: bool = False) -> Ran:
    """Run `bin/relay <args>`; `written` lists what appeared under home, cwd and root, prefixed `home:`, `cwd:`, `root:`."""
    with tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as cwd, tempfile.TemporaryDirectory() as root:
        if git:
            subprocess.run(["git", "init", "-q", cwd], check=True, capture_output=True, timeout=60)
        before = snapshot(cwd)
        env = {**os.environ, "HOME": home, "RELAY_HOME": os.path.join(home, ".relay"), "RELAY_ROOT": root}
        done = subprocess.run([sys.executable, RELAY, *args], cwd=cwd, env=env, capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)
        written = (["home:" + n for n in snapshot(home)] + ["cwd:" + n for n in snapshot(cwd) if n not in before]
                   + ["root:" + n for n in snapshot(root)])
        return Ran(done.returncode, done.stdout, done.stderr, written)
