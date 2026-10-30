"""`relay precheck`: the steps that went red in the gate, run in seconds so a worker sees them before the gate does
(docs: speed approach A). It only checks, never writes: the worker's quiet check must not change the tree it checks.

Steps, in this order:
  types and lint   bin/types-lint, the whole tree (a changed signature breaks callers in other files)
  python 3.9       every plugin lib module imports, and every hook survives an empty event, under /usr/bin/python3
  plugin lib links every tracked entry under plugins/*/lib is a link to its one source in lib/ (or prices.toml), or a plugin-only
                   kit_* file or agent-roles.tsv, read from HEAD as the gate reads it; a copy or a stray file prints its path and the fix

  changed tests    the tests/test_*.py files changed since the default branch, and test_rules_gate.RuleTestsComplete, under plain
                   python3 with tests/run_unittest.py: the gate's runner (a pytest-only import or an unlisted rules reader fails here too)

A link not yet committed is not seen: the gate gates the commit.
"""

import glob
import os
import posixpath
import re
import shutil
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import relay_tokens

PLUGINS = ("observe", "delegate", "front", "relay", "openspec")
OLD_PYTHON = "/usr/bin/python3"
STEP_TIMEOUT = 60       # seconds one step may take in all (about 10 s for the whole precheck when healthy); a timeout is a RED line
CHANGED_TESTS_TIMEOUT = 600   # a hang bound, not a clock: 16 changed files took 199 s at load 8 and over 230 s at load 17-35; only a hung test reaches 600 s
_test_env: dict[str, str] = {}   # the environment of the changed tests: the token this precheck holds, passed down; run() sets it
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


def _find_uv() -> str | None:
    return shutil.which("uv") or next((p for p in [os.path.join(os.path.expanduser("~"), ".local", "bin", "uv")] if os.access(p, os.X_OK)), None)


def _pinned(worktree: str) -> dict[str, str]:
    """The tool specs bin/types_lint.py runs through uv, as uv takes them; the unpinned name when the file does not say."""
    try:
        with open(os.path.join(worktree, "bin", "types_lint.py"), encoding="utf-8") as f:
            text = f.read()
    except OSError:
        text = ""
    mypy = re.search(r'^MYPY = "([^"]+)"', text, re.M)
    ruff = re.search(r'^RUFF = "([^"]+)"', text, re.M)
    return {"mypy": "mypy==" + mypy.group(1) if mypy else "mypy", "ruff": "ruff@" + ruff.group(1) if ruff else "ruff"}


def _running_tool(root_pid: int) -> str | None:
    """The tool (mypy or ruff) named in the command line of the step's process or one of its descendants, or None."""
    try:
        listing = subprocess.run(["ps", "-A", "-o", "pid=,ppid=,command="], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    rows: dict[int, tuple[int, str]] = {}
    for line in listing.splitlines():
        parts = line.split(None, 2)
        if len(parts) == 3 and parts[0].isdigit() and parts[1].isdigit():
            rows[int(parts[0])] = (int(parts[1]), parts[2])
    family = {root_pid}
    grew = True
    while grew:
        grew = False
        for pid, (ppid, _) in rows.items():
            if ppid in family and pid not in family:
                family.add(pid)
                grew = True
    for pid in sorted(family):
        command = rows.get(pid, (0, ""))[1]
        for tool in ("mypy", "ruff"):
            if re.search(r"(^|[\s/=@])" + tool + r"([\s=@]|$)", command):
                return tool
    return None


def _timeout_lines(worktree: str, running: str | None) -> list[str]:
    """What follows the timeout line: a tool uv cannot find offline (cold cache, so the step is downloading it) with its install
    step, else the tool that was still running."""
    specs = _pinned(worktree)
    uv = _find_uv()
    if uv is None:
        return ["    uv is not installed: install uv (https://docs.astral.sh/uv/), then run relay doctor"]
    out: list[str] = []
    for tool, spec in specs.items():
        try:
            probe = subprocess.run([uv, "tool", "run", "--offline", spec, "--version"], capture_output=True, timeout=20)
            absent = probe.returncode != 0
        except subprocess.TimeoutExpired:
            absent = False
        if absent:
            out.append("    %s is not installed (not in the uv cache): run uv tool install %s, or relay doctor" % (tool, spec))
    if not out and running:
        out.append("    still running: %s (%s); a slow machine or a cold cache: run relay doctor" % (running, specs[running]))
    return out


def check_types(worktree: str) -> list[str]:
    script = os.path.join(worktree, "bin", "types-lint")
    if not os.path.exists(script):
        return ["skipped: no bin/types-lint here"]
    try:
        proc = subprocess.Popen(["bash", script], cwd=worktree, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    except OSError as err:
        what = err.filename or "bash"
        return ["FAIL types and lint could not start: %s is not installed or not on PATH (run: relay doctor)" % what]
    try:
        output, _ = proc.communicate(timeout=_left())
    except subprocess.TimeoutExpired:
        running = _running_tool(proc.pid)
        proc.kill()
        proc.communicate()
        return ["FAIL types and lint took longer than %d s" % STEP_TIMEOUT] + _timeout_lines(worktree, running)
    if proc.returncode == 0:
        return []
    return ["FAIL types and lint (bin/types-lint):"] + _tail(output)


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


def _link_problem(worktree: str, rel: str, mode: str, sha: str, files: set[str]) -> str | None:
    """Why one tracked entry under plugins/<p>/lib/ breaks the allow-list; None when it is allowed."""
    name = rel.rsplit("/", 1)[-1]
    in_lib = ("lib/" + name in files) or name == "prices.toml"
    source = "prices.toml" if name == "prices.toml" else "lib/" + name
    if mode == "120000":
        blob = _git(worktree, "cat-file", "blob", sha)
        target = blob.stdout.decode("utf-8", "replace") if blob.returncode == 0 else ""
        resolved = posixpath.normpath(posixpath.join(posixpath.dirname(rel), target))
        if resolved == source and source in files:
            return None
        return "FAIL %s is a link to %r: it must point to the one source, %s (ln -sf %s %s)" % (
            rel, target, source, "../../../" + source, rel)
    # kit_* are the plugin-only modules and agent-roles.tsv the role table: they exist once already. A name with "~" is never one
    # (git leaves `<name>~HEAD` when a merge meets a file on one side and a link on the other).
    if "~" not in name and (name.startswith("kit_") or name == "agent-roles.tsv") and rel.count("/") == 3:
        return None
    if in_lib and rel.count("/") == 3:
        return "FAIL %s is a copy of %s: replace it with a link, ln -sf ../../../%s %s" % (rel, source, source, rel)
    return ("FAIL %s is a stray file under plugins/*/lib: git rm it if a merge left it (<name>~HEAD); "
            "a new plugin-only file is named kit_* or added to the allow-list in relay_precheck._link_problem" % rel)


def check_lib_links(worktree: str) -> list[str]:
    """The gate's `plugin lib links` step, on the committed tree: each lib module exists once, in lib/ (and prices.toml at the root);
    every tracked entry under plugins/*/lib/ is a link to it or a plugin-only file. Read-only."""
    listing = _git(worktree, "ls-tree", "-r", "-z", "HEAD")
    if listing.returncode != 0:
        return ["FAIL plugin lib links: cannot read HEAD: " + listing.stderr.decode("utf-8", "replace").strip()]
    entries: dict[str, tuple[str, str]] = {}
    for record in listing.stdout.decode("utf-8", "replace").split("\0"):
        info, _, rel = record.partition("\t")
        parts = info.split()
        if rel and len(parts) == 3:
            entries[rel] = (parts[0], parts[2])
    files = set(entries)
    out: list[str] = []
    checked = 0
    for rel in sorted(entries):
        parts = rel.split("/")
        if len(parts) >= 4 and parts[0] == "plugins" and parts[2] == "lib":
            checked += 1
            problem = _link_problem(worktree, rel, entries[rel][0], entries[rel][1], files)
            if problem:
                out.append(problem)
    if not out and checked == 0:
        return ["skipped: no plugin lib files here"]
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
                                  text=True, timeout=limit, env=_test_env or None)
        except subprocess.TimeoutExpired:
            if group == [RULES_REGISTRY_TEST]:
                failed.append("FAIL rules registry test took longer than %d s" % STEP_TIMEOUT)   # the allowance it was given
            else:
                failed.append("FAIL changed tests took longer than %d s" % CHANGED_TESTS_TIMEOUT)
            break
        if done.returncode != 0:
            failed += ["FAIL changed tests (python3 tests/run_unittest.py %s):" % " ".join(group)] + _tail(done.stdout + done.stderr)
    return failed


STEPS = (("types and lint", check_types), ("python 3.9", check_python39), ("plugin lib links", check_lib_links),
         ("changed tests", check_changed_tests))


def take_test_token(lines: list[str]) -> relay_tokens.Held:
    """Wait for the precheck's one test token (printing the waiting line once) and fill `_test_env` for its test runs."""
    base = relay_tokens.acquire_run_base(os.environ, lambda line: print("precheck: " + line, file=sys.stderr, flush=True))
    _test_env.clear()
    _test_env.update(os.environ)
    _test_env[relay_tokens.ENV_HOLD] = relay_tokens.hold_value(1 if not base.passed else base.workers, base.home)
    return base.held


def run(worktree: str) -> tuple[int, list[str]]:
    """Every step, in order (a red one does not hide the next); the output lines and 0 when all are clean."""
    global _deadline
    worktree = os.path.realpath(worktree)
    top = subprocess.run(["git", "-C", worktree, "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    if top.returncode == 0 and top.stdout.strip():
        worktree = os.path.realpath(top.stdout.strip())   # from a subfolder, the repository's root is what is checked
    lines: list[str] = []
    code = 0
    held = relay_tokens.Held()
    for name, step in STEPS:
        budget = CHANGED_TESTS_TIMEOUT if name == "changed tests" else STEP_TIMEOUT
        if name == "changed tests":
            # one test token for the changed tests, taken BEFORE their budget starts (a wait never counts against it) and passed
            # down, so the test runs below take no base of their own; with a holder above (a gate), nothing is taken here
            held = take_test_token(lines)
        _deadline = time.monotonic() + budget
        try:
            found = step(worktree)
        except subprocess.TimeoutExpired:
            found = ["FAIL %s took longer than %d s" % (name, budget)]
        finally:
            _deadline = 0.0
            held.release()
            _test_env.clear()
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
