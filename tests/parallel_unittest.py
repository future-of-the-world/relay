"""The library tests on several processes, split by test class (standard library only).

A controller (the process that runs `run`) discovers the tests, groups them by class, and feeds the classes, longest
first, to k long-lived worker processes (`python3 tests/parallel_unittest.py --worker`). A worker asks for nothing: the
controller writes one class name on its stdin, the worker runs that class with unittest and answers with one JSON line
on a pipe (its stdout is moved to its stderr, so a test's own prints cannot corrupt the pipe). No worker writes to the
step log: the controller prints exactly one summed "Ran N tests" line and every failing test by name.

Each worker keeps the guards of tests/run_unittest.py: a TMPDIR of its own, the per-test temporary HOME and RELAY_HOME
(tests/tmp_default.py), and the leaked-gate scan (tests/leaked_gates.py) over its own folder when it ends.

The class times live in ONE file per machine, $RELAY_HOME/test-times/<repo>.json (<repo> is the name of the main
checkout's folder, so every worktree of the repo shares it). Only an outer run writes it (RELAY_INERT_PROBE=1 marks the
inert probe, which only reads), and only after a complete run: every class ran. It is replaced in one step (a temporary
file, then a rename). With no file, classes go out by test count, the biggest first: a weak guess, so the first run on a
machine can be slower than later ones; its log says so.

RELAY_TEST_JOBS: the number of workers, default 4, from 1 to the core count; 1 is the single process of run_unittest.
"""
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from typing import Any, Dict, List, Optional, TextIO, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DEFAULT_JOBS = 4


def jobs_setting(env: Dict[str, str], cores: Optional[int] = None) -> Tuple[int, str]:
    """(workers, note). A value that is not a whole number gives 0 and the reason in the note; a value outside 1..cores
    is brought into it and the note says so."""
    cores = cores or os.cpu_count() or 1
    raw = env.get("RELAY_TEST_JOBS", "").strip()
    if not raw:
        return min(DEFAULT_JOBS, cores), ""
    if not re.fullmatch(r"[0-9]+", raw):
        return 0, "FAIL RELAY_TEST_JOBS=%s is not a whole number (use 1 to %d)" % (raw, cores)
    wanted = int(raw)
    jobs = max(1, min(wanted, cores))
    return jobs, ("RELAY_TEST_JOBS=%d is outside 1..%d: using %d" % (wanted, cores, jobs)) if jobs != wanted else ""


def repo_name(root: str) -> str:
    """The name of the repo from its main checkout (the folder that holds the common .git), not a machine path."""
    done = subprocess.run(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"], cwd=root,
                          capture_output=True, text=True, timeout=60)
    top = root
    if done.returncode == 0 and done.stdout.strip():
        top = os.path.dirname(os.path.realpath(done.stdout.strip()))
    return re.sub(r"[^A-Za-z0-9._-]", "_", os.path.basename(top)) or "repo"


def home_dir(env: Dict[str, str]) -> str:
    """$RELAY_HOME of the given environment, else where relay_config says (the default home)."""
    if env.get("RELAY_HOME"):
        return os.path.expanduser(env["RELAY_HOME"])
    sys.path.insert(0, os.path.join(ROOT, "lib"))
    import relay_config
    return str(relay_config.home_dir())


def times_path(root: str, env: Dict[str, str]) -> str:
    return os.path.join(home_dir(env), "test-times", repo_name(root) + ".json")


def load_times(path: str) -> Tuple[Dict[str, float], str]:
    """(class -> seconds, note). A missing file is an empty dict with a note; a file of an unexpected shape is ignored with
    the reason in the note (the run still works, ordered by test count)."""
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError:
        return {}, "no times file (first run on this machine)"
    except (OSError, ValueError) as err:
        return {}, "times file unreadable (%s)" % err
    classes = data.get("classes") if isinstance(data, dict) else None
    if not isinstance(classes, dict) or not all(isinstance(k, str) and isinstance(v, (int, float)) and not isinstance(v, bool)
                                                 for k, v in classes.items()):
        return {}, "times file has an unexpected shape"
    return {k: float(v) for k, v in classes.items()}, ""


def save_times(path: str, updates: Dict[str, float]) -> None:
    """Merge the classes that ran into the file and replace it in one step."""
    merged, _ = load_times(path)
    merged.update(updates)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".times-", suffix=".tmp", dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump({"classes": {k: round(v, 3) for k, v in sorted(merged.items())}}, handle, indent=1)
            handle.write("\n")
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def order_classes(counts: Dict[str, int], times: Dict[str, float]) -> List[str]:
    """Longest first. A class with a recorded time goes by it; one without (new, or no file at all) goes by test count and
    ahead of the timed ones, since nothing says it is short."""
    unknown = sorted((c for c in counts if c not in times), key=lambda c: (-counts[c], c))
    known = sorted((c for c in counts if c in times), key=lambda c: (-times[c], c))
    return unknown + known


def _flatten(suite: unittest.TestSuite) -> List[unittest.TestCase]:
    found: List[unittest.TestCase] = []
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            found += _flatten(item)
        else:
            found.append(item)
    return found


def _class_of(test: unittest.TestCase) -> str:
    return "%s.%s" % (type(test).__module__, type(test).__qualname__)


# ---- the worker -----------------------------------------------------------------------------------------------------
def worker_main(tests_dir: str) -> int:
    sys.path.insert(0, tests_dir)
    import leaked_gates
    import tmp_default
    out = os.fdopen(os.dup(1), "w", encoding="utf-8")
    os.dup2(2, 1)                       # a test's prints go to the worker's log, not to the pipe
    run_dir = os.path.realpath(tempfile.mkdtemp(prefix="relay-run-"))
    os.environ["TMPDIR"] = run_dir
    tempfile.tempdir = None
    tmp_default.patch_unittest()
    try:
        for line in sys.stdin:
            name = line.strip()
            if not name:
                continue
            suite = unittest.defaultTestLoader.loadTestsFromName(name)
            runner = unittest.TextTestRunner(stream=sys.stderr, verbosity=1)
            start = time.monotonic()
            result = runner.run(suite)
            problems = [(str(t), "FAIL" if kind == "failures" else "ERROR", tb)
                        for kind in ("failures", "errors") for t, tb in getattr(result, kind)]
            problems += [(str(t), "FAIL", "unexpected success\n") for t in result.unexpectedSuccesses]
            reply = {"class": name, "ran": result.testsRun, "seconds": time.monotonic() - start, "problems": problems}
            out.write(json.dumps(reply) + "\n")
            out.flush()
        leaked = leaked_gates.stop(run_dir)
        out.write(json.dumps({"leaked": leaked}) + "\n")
        out.flush()
        return 0
    finally:
        shutil.rmtree(run_dir, ignore_errors=True)


# ---- the controller -------------------------------------------------------------------------------------------------
class Pool:
    def __init__(self, jobs: int, classes: List[str], log_dir: Optional[str], tests_dir: str) -> None:
        self.todo: "queue.Queue[str]" = queue.Queue()
        for name in classes:
            self.todo.put(name)
        self.jobs, self.log_dir, self.tests_dir = jobs, log_dir, tests_dir
        self.lock = threading.Lock()
        self.replies: List[Dict[str, Any]] = []
        self.deaths: List[str] = []
        self.leaks: List[Tuple[int, str]] = []

    def _loop(self, index: int) -> None:
        log: TextIO
        if self.log_dir:
            log = open(os.path.join(self.log_dir, "library-tests.w%d.log" % (index + 1)), "w", encoding="utf-8")
        else:
            log = open(os.devnull, "w")
        proc = subprocess.Popen([sys.executable, "-W", "ignore::ResourceWarning", os.path.abspath(__file__), "--worker", self.tests_dir],
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log, text=True, cwd=ROOT,
                                close_fds=False)    # keeps a gate's lock fd, as every child of the gate does
        assert proc.stdin is not None and proc.stdout is not None
        current = ""
        try:
            while True:
                try:
                    current = self.todo.get_nowait()
                except queue.Empty:
                    break
                try:
                    proc.stdin.write(current + "\n")
                    proc.stdin.flush()
                    line = proc.stdout.readline()
                except (BrokenPipeError, OSError):
                    line = ""
                if not line:
                    with self.lock:
                        self.deaths.append("worker %d died while running %s" % (index + 1, current))
                    return
                with self.lock:
                    self.replies.append(json.loads(line))
                current = ""
            try:
                proc.stdin.close()
                line = proc.stdout.readline()
            except (BrokenPipeError, OSError):
                line = ""
            if not line:
                with self.lock:
                    self.deaths.append("worker %d died before it reported its leaked-gate scan" % (index + 1))
                return
            with self.lock:
                self.leaks += [(int(p), str(c)) for p, c in json.loads(line).get("leaked", [])]
        finally:
            try:
                proc.stdout.close()
                proc.wait(timeout=60)
            except (subprocess.TimeoutExpired, OSError):
                proc.kill()
            log.close()

    def run(self) -> None:
        threads = [threading.Thread(target=self._loop, args=(i,)) for i in range(self.jobs)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()


def run(root: str = ROOT, env: Optional[Dict[str, str]] = None, tests_dir: str = HERE) -> int:
    env = dict(os.environ if env is None else env)
    jobs, note = jobs_setting(env)
    if jobs == 0:
        print(note)
        return 1
    if note:
        print(note)
    start = time.monotonic()
    sys.path.insert(0, tests_dir)
    sys.path.insert(0, root)
    suite = unittest.defaultTestLoader.discover(tests_dir, pattern="test_*.py")
    tests = _flatten(suite)
    # tests that failed to import (or a module that skipped itself) are not classes a worker can load: run them here
    local = [t for t in tests if type(t).__module__.startswith("unittest")]
    counts: Dict[str, int] = {}
    for t in tests:
        if t not in local:
            counts[_class_of(t)] = counts.get(_class_of(t), 0) + 1
    path = times_path(root, env)
    times, why = load_times(path)
    print("test jobs: %d; class times from $RELAY_HOME/test-times (searched %s)%s" %
          (jobs, path, "" if not why else ": " + why + "; classes go out by test count, the biggest first"))
    steps = os.path.join(root, ".ci", "steps")
    pool = Pool(jobs, order_classes(counts, times), steps if os.path.isdir(steps) else None, tests_dir)
    pool.run()

    ran = sum(r["ran"] for r in pool.replies)
    problems: List[Tuple[str, str, str]] = [tuple(p) for r in pool.replies for p in r["problems"]]   # type: ignore[misc]
    problems += [("worker", "ERROR", d + "\n") for d in pool.deaths]
    done = {r["class"] for r in pool.replies}
    for name in sorted(set(counts) - done):
        if not pool.deaths:
            problems.append((name, "ERROR", "class never ran\n"))
    if local:
        result = unittest.TextTestRunner(stream=open(os.devnull, "w"), verbosity=0).run(unittest.TestSuite(local))
        ran += result.testsRun
        problems += [(str(t), "FAIL" if k == "failures" else "ERROR", tb)
                     for k in ("failures", "errors") for t, tb in getattr(result, k)]
    expected = len(tests)
    if not pool.deaths and ran != expected:
        problems.append(("count", "ERROR", "ran %d tests but discovery found %d\n" % (ran, expected)))
    for pid, command in pool.leaks:
        problems.append(("leaked gate", "FAIL", "leaked gate: pid %d was still running after the tests, in a temporary "
                         "folder of a worker (stopped): %s\n" % (pid, command)))
    for name, kind, text in sorted(problems):
        print("=" * 70)
        print("%s: %s" % (kind, name))
        print("-" * 70)
        print(text)
    print("-" * 70)
    print("Ran %d tests in %.3fs" % (ran, time.monotonic() - start))
    print()
    fails = sum(1 for p in problems if p[1] == "FAIL")
    errors = len(problems) - fails
    print("OK" if not problems else "FAILED (%s)" % ", ".join(
        "%s=%d" % (k, n) for k, n in (("failures", fails), ("errors", errors)) if n))
    if not pool.deaths and env.get("RELAY_INERT_PROBE") != "1":
        try:
            save_times(path, {r["class"]: r["seconds"] for r in pool.replies})
        except OSError as err:
            print("test times not saved: %s" % err)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.path.insert(0, HERE)
    sys.path.insert(0, ROOT)
    sys.exit(worker_main(sys.argv[2]) if sys.argv[1:2] == ["--worker"] else run())
