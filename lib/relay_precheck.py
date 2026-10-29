"""`relay precheck`: the steps that went red in the gate, run in seconds so a worker sees them before the gate does
(docs: speed approach A). It only checks, never writes: the worker's quiet check must not change the tree it checks.

Steps, in this order:
  types and lint   bin/types-lint, the whole tree (a changed signature breaks callers in other files)
  python 3.9       every plugin lib module imports, and every hook survives an empty event, under /usr/bin/python3
  lib copies       each lib/relay_*.py and prices.toml against its copies under plugins/*/lib, read from HEAD, as the gate
                   reads them; a difference prints the copy's path and the sync command, then fails

  changed tests    the tests/test_*.py files changed since the default branch, and test_rules_gate.RuleTestsComplete, under plain
                   python3 with tests/run_unittest.py: the gate's runner (a pytest-only import or an unlisted rules reader fails here too)

A copy refreshed by bin/sync-lib-copies but not committed still fails: the gate gates the commit.
"""

import glob
import os
import subprocess
import sys
import time

PLUGINS = ("observe", "delegate", "front", "relay", "openspec")
OLD_PYTHON = "/usr/bin/python3"
STEP_TIMEOUT = 60       # seconds one step may take in all (about 10 s for the whole precheck when healthy); a timeout is a RED line
CHANGED_TESTS_TIMEOUT = 600   # a hang bound, not a clock: 16 changed files took 199 s at load 8 and over 230 s at load 17-35; only a hung test reaches 600 s
_deadline = 0.0         # time.monotonic() by which the running step must end; run() sets it per step
TAIL = 20               # lines of a failing step's output shown


def _left() -> float:
    """Seconds the running step may still take: one deadline for all of the step's subprocesses, not one per call."""
    if _deadline == 0.0:
        return float(STEP_TIMEOUT)
    return max(0.1, _deadline - time.monotonic())


def _git(worktree: str, *args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(["git", "-C", worktree, *args], capture_output=True, timeout=_left())


def _tail(text: str) -> list[str]:
    return ["    " + ln for ln in text.strip().splitlines()[-TAIL:]]


def check_types(worktree: str) -> list[str]:
    script = os.path.join(worktree, "bin", "types-lint")
    if not os.path.exists(script):
        return ["skipped: no bin/types-lint here"]
    try:
        done = subprocess.run(["bash", script], cwd=worktree, capture_output=True, text=True, timeout=_left())
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
    libs = sorted(glob.glob(os.path.join(worktree, "plugins", "*", "lib", "*.py")))
    hooks = sorted(glob.glob(os.path.join(worktree, "plugins", "*", "hooks", "*.py")))
    if not libs and not hooks:
        return ["skipped: no plugin modules here"]
    for path in libs:
        rel = os.path.relpath(path, worktree)
        code = "import sys, importlib; sys.path.insert(0, %r); importlib.import_module(%r)" % (
            os.path.dirname(path), os.path.basename(path)[:-3])
        done = subprocess.run([OLD_PYTHON, "-c", code], capture_output=True, text=True, timeout=_left())
        if done.returncode != 0:
            out.append("FAIL %s does not import under python 3.9:" % rel)
            out += _tail(done.stderr)
    for path in hooks:
        rel = os.path.relpath(path, worktree)
        done = subprocess.run([OLD_PYTHON, path], input="{}", capture_output=True, text=True, timeout=_left())
        # The rule (the gate's test uses this function): a hook that cannot be imported or parsed under 3.9 fails; a hook that
        # exits non-zero later, after its imports, is the hook's own business and passes.
        if any(word in done.stderr for word in ("TypeError", "SyntaxError", "ImportError", "ModuleNotFoundError")):
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
    checked = 0
    for plugin in PLUGINS:
        for rel in sorted(files):
            parts = rel.split("/")
            if len(parts) == 4 and parts[:2] == ["plugins", plugin] and parts[2] == "lib" and parts[3].startswith("relay_") \
                    and parts[3].endswith(".py"):
                lib = "lib/" + parts[3]
                checked += 1
                if lib not in files or _head_file(worktree, rel) != _head_file(worktree, lib):
                    out.append("FAIL %s differs from %s in the last commit: run bin/sync-lib-copies and commit" % (rel, lib))
        prices = "plugins/%s/lib/prices.toml" % plugin
        checked += prices in files
        if prices in files and (("prices.toml" not in files) or _head_file(worktree, prices) != _head_file(worktree, "prices.toml")):
            out.append("FAIL %s differs from prices.toml in the last commit: run bin/sync-lib-copies and commit" % prices)
    if not out and checked == 0:
        return ["skipped: no plugin lib copies here"]
    return out


DEFAULT_BRANCHES = ("master", "main")
RULES_REGISTRY_TEST = "tests.test_rules_gate.RuleTestsComplete"


def changed_test_modules(worktree: str) -> list[str] | None:
    """Dotted names of the tests/test_*.py files changed since the default branch (committed, edited or new), sorted; None when
    there is no default branch to compare with."""
    base = ""
    for branch in DEFAULT_BRANCHES:
        done = _git(worktree, "merge-base", "HEAD", branch)
        if done.returncode == 0 and done.stdout.strip():
            base = done.stdout.decode("utf-8").strip()
            break
    if not base:
        return None
    changed = _git(worktree, "diff", "--name-only", base, "--", "tests")
    new = _git(worktree, "ls-files", "--others", "--exclude-standard", "--", "tests")
    names: set[str] = set()
    for rel in (changed.stdout + b"\n" + new.stdout).decode("utf-8").splitlines():
        parts = rel.split("/")
        if len(parts) == 2 and parts[1].startswith("test_") and parts[1].endswith(".py") \
                and os.path.exists(os.path.join(worktree, rel)):   # a deleted test has nothing to run
            names.add("tests." + parts[1][:-3])
    return sorted(names)


def check_changed_tests(worktree: str) -> list[str]:
    """The gate's library tests, narrowed to what the branch changed, run the gate's way (python3, tests/run_unittest.py)."""
    runner = os.path.join(worktree, "tests", "run_unittest.py")
    if not os.path.exists(runner):
        return ["skipped: no tests/run_unittest.py here"]
    modules = changed_test_modules(worktree)
    if modules is None:
        return ["skipped: no master or main branch to compare with"]
    names = sorted(set(modules) | {RULES_REGISTRY_TEST}) if os.path.exists(os.path.join(worktree, "tests", "test_rules_gate.py")) else modules
    if not names:
        return ["skipped: no test changed"]   # a tree without the registry test and without a changed test
    failed: list[str] = []
    ran: list[list[str]] = []
    # the registry test alone first (0.6 s): a slow changed test that times out must not hide its verdict
    groups = [[RULES_REGISTRY_TEST]] if RULES_REGISTRY_TEST in names else []
    rest = [n for n in names if n != RULES_REGISTRY_TEST]
    if rest:
        groups.append(rest)
    for group in groups:
        ran.append(group)
        # the registry test (0.6 s healthy) gets the step allowance, not what is left of the changed-tests budget: on a loaded machine
        # a tight budget must not cut off its verdict
        limit = float(STEP_TIMEOUT) if group == [RULES_REGISTRY_TEST] else _left()
        try:
            done = subprocess.run(["python3", "-W", "ignore::ResourceWarning", runner, *group], cwd=worktree, capture_output=True,
                                  text=True, timeout=limit)
        except subprocess.TimeoutExpired:
            if group == [RULES_REGISTRY_TEST]:
                failed.append("FAIL rules registry test took longer than %d s" % STEP_TIMEOUT)   # the allowance it was given
            else:
                failed.append("FAIL changed tests took longer than %d s" % CHANGED_TESTS_TIMEOUT)
            break
        if done.returncode != 0:
            failed += ["FAIL changed tests (python3 tests/run_unittest.py %s):" % " ".join(group)] + _tail(done.stdout + done.stderr)
    return failed


STEPS = (("types and lint", check_types), ("python 3.9", check_python39), ("lib copies identical", check_lib_copies),
         ("changed tests", check_changed_tests))


def run(worktree: str) -> tuple[int, list[str]]:
    """Every step, in order (a red one does not hide the next); the output lines and 0 when all are clean."""
    global _deadline
    worktree = os.path.realpath(worktree)
    top = subprocess.run(["git", "-C", worktree, "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    if top.returncode == 0 and top.stdout.strip():
        worktree = os.path.realpath(top.stdout.strip())   # from a subfolder, the repository's root is what is checked
    lines: list[str] = []
    code = 0
    for name, step in STEPS:
        budget = CHANGED_TESTS_TIMEOUT if name == "changed tests" else STEP_TIMEOUT
        _deadline = time.monotonic() + budget
        try:
            found = step(worktree)
        except subprocess.TimeoutExpired:
            found = ["FAIL %s took longer than %d s" % (name, budget)]
        finally:
            _deadline = 0.0
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
