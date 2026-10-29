"""The library tests on several processes, split by test class (standard library only).

A controller (the process that runs `run`) discovers the tests, groups them by class, and feeds the classes, longest
first, to k long-lived worker processes (`python3 tests/parallel_unittest.py --worker`). A worker asks for nothing: the
controller writes one class name on its stdin, the worker runs that class with unittest and answers with one JSON line
on a pipe (its stdout is moved to its stderr, so a test's own prints cannot corrupt the pipe). No worker writes to the
step log: the controller prints exactly one summed "Ran N tests" line and every failing test by name.

Each worker keeps the guards of tests/run_unittest.py: a TMPDIR of its own, the per-test temporary HOME and RELAY_HOME
(tests/tmp_default.py), and the leaked-process scan (tests/leaked_gates.py) over its own folder when it ends.

The class times live in ONE file per machine, $RELAY_HOME/test-times/<repo>.json (<repo> is the name of the main
checkout's folder, so every worktree of the repo shares it). Only an outer run writes it (RELAY_INERT_PROBE=1 marks the
inert probe, which only reads), and only after a complete run: every class ran. It is replaced in one step (a temporary
file, then a rename). With no file, classes go out by test count, the biggest first: a weak guess, so the first run on a
machine can be slower than later ones; its log says so.

RELAY_TEST_JOBS: the number of workers, default 4, from 1 to the core count; 1 is the single process of run_unittest.

Tokens (lib/relay_tokens.py): a worker runs only while it holds a token of the machine-wide pool. The first workers (the run's
base) run on the base its holder passed down in RELAY_TEST_TOKENS (a gate's share, halved between the outer run and the inert
probe), or on one shared token this run took itself; the rest are extras, each taken for one class and given back after it.
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
from typing import Any, Callable, Dict, List, Optional, TextIO, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "lib"))
import relay_tokens
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
                          capture_output=True, text=True, timeout=600)
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


class _Loader(unittest.TestLoader):
    """Remembers which module discovery found each test in: a class imported into a second test module is found (and, in a
    single process, run) once per module, so the unit of work is "<discovering module>.<class>", not the defining module."""

    def __init__(self) -> None:
        super().__init__()
        self.found_in: Dict[int, str] = {}

    def loadTestsFromModule(self, module: Any, *args: Any, **kwargs: Any) -> unittest.TestSuite:
        suite = super().loadTestsFromModule(module, *args, **kwargs)
        for test in _flatten(suite):
            self.found_in[id(test)] = module.__name__
        return suite


# ---- the worker -----------------------------------------------------------------------------------------------------
def worker_main(tests_dir: str) -> int:
    sys.path.insert(0, tests_dir)
    import leaked_gates
    import tmp_default
    out = os.fdopen(os.dup(1), "w", encoding="utf-8")
    os.dup2(2, 1)                       # a test's prints go to the worker's log, not to the pipe
    commands = os.fdopen(os.dup(0), encoding="utf-8")   # the class names; os.dup's fd is not inherited by a test's children
    os.dup2(os.open(os.devnull, os.O_RDONLY), 0)        # a child that reads stdin sees EOF, as under a detached gate
    run_dir = os.path.realpath(tempfile.mkdtemp(prefix="relay-run-"))
    os.environ["TMPDIR"] = run_dir
    tempfile.tempdir = None
    tmp_default.patch_unittest()
    try:
        for line in commands:
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
        notes: List[str] = []
        leaked = leaked_gates.stop(run_dir, notes)
        out.write(json.dumps({"leaked": leaked, "notes": notes}) + "\n")
        out.flush()
        return 0
    finally:
        shutil.rmtree(run_dir, ignore_errors=True)


# ---- the controller -------------------------------------------------------------------------------------------------
class Pool:
    def __init__(self, jobs: int, classes: List[str], log_dir: Optional[str], tests_dir: str,
                 env: Optional[Dict[str, str]] = None, base: Optional[int] = None,
                 extras: Optional[Callable[[], Optional[relay_tokens.Held]]] = None, retry: float = 1.0) -> None:
        """`base` workers run freely (their tokens are held above); the other `jobs - base` run a class only while `extras()`
        hands them a token, which goes back after the class. With no `extras`, only the base workers start."""
        self.todo: "queue.Queue[str]" = queue.Queue()
        for name in classes:
            self.todo.put(name)
        self.jobs, self.log_dir, self.tests_dir, self.env = jobs, log_dir, tests_dir, env
        self.base = jobs if base is None else min(base, jobs)
        self.extras, self.retry = extras, retry
        self.lock = threading.Lock()
        self.replies: List[Dict[str, Any]] = []
        self.deaths: List[str] = []
        self.leaks: List[Tuple[int, str]] = []
        self.notes: List[str] = []

    def _loop(self, index: int) -> None:
        extra = index >= self.base
        log: TextIO
        if self.log_dir:
            log = open(os.path.join(self.log_dir, "library-tests.w%d.log" % (index + 1)), "w", encoding="utf-8")
        else:
            log = open(os.devnull, "w")
        proc: Optional["subprocess.Popen[str]"] = None
        try:
            while True:
                token: Optional[relay_tokens.Held] = None
                if extra:
                    if self.todo.empty():
                        break
                    token = self.extras() if self.extras is not None else None
                    if token is None:
                        time.sleep(self.retry)      # no token free: this worker idles (no process, no CPU) and looks again
                        continue
                try:
                    try:
                        current = self.todo.get_nowait()
                    except queue.Empty:
                        break
                    if proc is None:
                        proc = subprocess.Popen([sys.executable, "-W", "ignore::ResourceWarning", os.path.abspath(__file__), "--worker", self.tests_dir],
                                                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log, text=True, cwd=ROOT, env=self.env,
                                                close_fds=False)    # keeps a gate's lock fd, as every child of the gate does
                    assert proc.stdin is not None and proc.stdout is not None
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
                finally:
                    if token is not None:
                        token.release()
            if proc is None:
                return
            assert proc.stdin is not None and proc.stdout is not None
            try:
                proc.stdin.close()
                line = proc.stdout.readline()
            except (BrokenPipeError, OSError):
                line = ""
            if not line:
                with self.lock:
                    self.deaths.append("worker %d died before it reported its leaked-process scan" % (index + 1))
                return
            with self.lock:
                reply = json.loads(line)
                self.leaks += [(int(p), str(c)) for p, c in reply.get("leaked", [])]
                self.notes += [str(n) for n in reply.get("notes", []) if str(n) not in self.notes]
        finally:
            if proc is not None:
                try:
                    assert proc.stdout is not None
                    proc.stdout.close()
                    proc.wait(timeout=600)
                except (subprocess.TimeoutExpired, OSError):
                    proc.kill()
            log.close()

    def run(self) -> None:
        count = self.jobs if self.extras is not None else self.base
        threads = [threading.Thread(target=self._loop, args=(i,)) for i in range(count)]
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
    base = relay_tokens.acquire_run_base(env, lambda line: print("tests: " + line, flush=True))
    try:
        return _run(root, env, tests_dir, jobs, note, base)
    finally:
        base.held.release()


def probe_share(given: int, probe: bool) -> int:
    """The workers of one of the gate's two test runs out of the gate's `given` base: the inert probe gets half, the outer run the rest."""
    return max(1, given // 2 if probe else given - given // 2)


def _run(root: str, env: Dict[str, str], tests_dir: str, jobs: int, note: str, run_base: relay_tokens.RunBase) -> int:
    if note:
        print(note)
    base = min(jobs, probe_share(run_base.workers, env.get("RELAY_INERT_PROBE") == "1") if run_base.passed else run_base.workers)
    st = run_base.settings
    for text in st.notes:
        print("NOTE test tokens: " + text)
    start = time.monotonic()
    sys.path.insert(0, tests_dir)
    sys.path.insert(0, root)
    loader = _Loader()
    suite = loader.discover(tests_dir, pattern="test_*.py")
    tests = _flatten(suite)
    # tests that failed to import (or a module that skipped itself) are not classes a worker can load: run them here
    local = [t for t in tests if type(t).__module__.startswith("unittest")]
    counts: Dict[str, int] = {}
    for t in tests:
        if t not in local:
            unit = "%s.%s" % (loader.found_in.get(id(t), type(t).__module__), type(t).__qualname__)
            counts[unit] = counts.get(unit, 0) + 1
    path = times_path(root, env)
    times, why = load_times(path)
    print("test jobs: %d (%d on the base tokens, the rest on free tokens of the pool); class times from $RELAY_HOME/test-times (searched %s)%s" %
          (jobs, base, path, "" if not why else ": " + why + "; classes go out by test count, the biggest first"))
    steps = os.path.join(root, ".ci", "steps")
    prefer = relay_tokens.GATE if run_base.passed else relay_tokens.SHARED
    pool = Pool(jobs, order_classes(counts, times), steps if os.path.isdir(steps) else None, tests_dir, env, base,
                lambda: relay_tokens.try_extra(run_base.home, st, prefer), st.retry)
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
    for note in pool.notes:
        print("NOTE leak scan: " + note)
    for pid, command in pool.leaks:
        problems.append(("leaked process", "FAIL", "leaked process: pid %d was still running after the tests, in a temporary "
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
