"""`relay precheck`: the steps that went red in the gate, run in seconds so a worker sees them before the gate does
(docs: speed approach A). It only checks, never writes: the worker's quiet check must not change the tree it checks.

Steps, in this order:
  types and lint   bin/types-lint, the whole tree (a changed signature breaks callers in other files)
  python 3.9       every plugin lib module imports, and every hook survives an empty event, under /usr/bin/python3
  lib copies       each lib/relay_*.py and prices.toml against its copies under plugins/*/lib, read from HEAD, as the gate
                   reads them; a difference prints the copy's path and the sync command, then fails

A copy refreshed by bin/sync-lib-copies but not committed still fails: the gate gates the commit.
"""

import glob
import os
import subprocess
import sys

PLUGINS = ("observe", "delegate", "front", "core", "openspec")
OLD_PYTHON = "/usr/bin/python3"
STEP_TIMEOUT = 60       # seconds a step may take (the design's bound for the whole precheck: about 10 s cold when healthy)
TAIL = 20               # lines of a failing step's output shown


def _git(worktree: str, *args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(["git", "-C", worktree, *args], capture_output=True, timeout=STEP_TIMEOUT)


def _tail(text: str) -> list[str]:
    return ["    " + ln for ln in text.strip().splitlines()[-TAIL:]]


def check_types(worktree: str) -> list[str]:
    script = os.path.join(worktree, "bin", "types-lint")
    if not os.path.exists(script):
        return ["skipped: no bin/types-lint here"]
    try:
        done = subprocess.run(["bash", script], cwd=worktree, capture_output=True, text=True, timeout=STEP_TIMEOUT)
    except subprocess.TimeoutExpired:
        return ["FAIL types and lint took longer than %d s" % STEP_TIMEOUT]
    if done.returncode == 0:
        return []
    return ["FAIL types and lint (bin/types-lint):"] + _tail(done.stdout + done.stderr)


def old_python() -> bool:
    if not os.path.exists(OLD_PYTHON):
        return False
    done = subprocess.run([OLD_PYTHON, "-c", "import sys; print(sys.version_info[1])"], capture_output=True, text=True)
    return done.stdout.strip().isdigit() and int(done.stdout.strip()) < 11


def check_python39(worktree: str) -> list[str]:
    if not old_python():
        return ["skipped: no /usr/bin/python3 older than 3.11 on this machine"]
    out: list[str] = []
    for path in sorted(glob.glob(os.path.join(worktree, "plugins", "*", "lib", "*.py"))):
        rel = os.path.relpath(path, worktree)
        code = "import sys, importlib; sys.path.insert(0, %r); importlib.import_module(%r)" % (
            os.path.dirname(path), os.path.basename(path)[:-3])
        done = subprocess.run([OLD_PYTHON, "-c", code], capture_output=True, text=True, timeout=STEP_TIMEOUT)
        if done.returncode != 0:
            out.append("FAIL %s does not import under python 3.9:" % rel)
            out += _tail(done.stderr)
    for path in sorted(glob.glob(os.path.join(worktree, "plugins", "*", "hooks", "*.py"))):
        rel = os.path.relpath(path, worktree)
        done = subprocess.run([OLD_PYTHON, path], input="{}", capture_output=True, text=True, timeout=STEP_TIMEOUT)
        if "TypeError" in done.stderr or "SyntaxError" in done.stderr:
            out.append("FAIL hook %s breaks under python 3.9:" % rel)
            out += _tail(done.stderr)
    return out


def _head_file(worktree: str, rel: str) -> bytes | None:
    done = _git(worktree, "show", "HEAD:" + rel)
    return done.stdout if done.returncode == 0 else None


def check_lib_copies(worktree: str) -> list[str]:
    """The gate's `lib copies identical` step, on the committed tree. Read-only."""
    listing = _git(worktree, "ls-tree", "-r", "--name-only", "HEAD")
    if listing.returncode != 0:
        return ["FAIL lib copies: cannot read HEAD: " + listing.stderr.decode("utf-8", "replace").strip()]
    files = set(listing.stdout.decode("utf-8").splitlines())
    out: list[str] = []
    for plugin in PLUGINS:
        for rel in sorted(files):
            parts = rel.split("/")
            if len(parts) == 4 and parts[:2] == ["plugins", plugin] and parts[2] == "lib" and parts[3].startswith("relay_") \
                    and parts[3].endswith(".py"):
                lib = "lib/" + parts[3]
                if lib not in files or _head_file(worktree, rel) != _head_file(worktree, lib):
                    out.append("FAIL %s differs from %s in the last commit: run bin/sync-lib-copies and commit" % (rel, lib))
        prices = "plugins/%s/lib/prices.toml" % plugin
        if prices in files and (("prices.toml" not in files) or _head_file(worktree, prices) != _head_file(worktree, "prices.toml")):
            out.append("FAIL %s differs from prices.toml in the last commit: run bin/sync-lib-copies and commit" % prices)
    return out


STEPS = (("types and lint", check_types), ("python 3.9", check_python39), ("lib copies identical", check_lib_copies))


def run(worktree: str) -> tuple[int, list[str]]:
    """Every step, in order (a red one does not hide the next); the output lines and 0 when all are clean."""
    worktree = os.path.realpath(worktree)
    lines: list[str] = []
    code = 0
    for name, step in STEPS:
        found = step(worktree)
        if not found:
            lines.append("ok   " + name)
        elif all(ln.startswith("skipped") for ln in found):
            lines.append("skip " + name + " (" + found[0][len("skipped: "):] + ")")
        else:
            lines.append("RED  " + name)
            lines += ["  " + ln for ln in found]
            code = 1
    lines.append("precheck: green" if code == 0 else "precheck: RED (the gate would be red; fix these first)")
    return code, lines


if __name__ == "__main__":
    status, text = run(sys.argv[1] if len(sys.argv) > 1 else ".")
    print("\n".join(text))
    sys.exit(status)
