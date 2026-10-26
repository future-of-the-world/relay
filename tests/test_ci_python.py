"""lib/relay_ci.py (what bin/ci runs): the paid part, the record step, the rules gate's test names, and the inert probe that
runs beside the outer steps. Free; no model call. Programs are replaced by a recording runner or by stubs in a temporary
PATH; every tree is a temporary folder."""
import io
import os
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from typing import Any, Callable, List, Optional

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
import relay_ci  # noqa: E402

GIT_ENV = {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull, "GIT_AUTHOR_NAME": "t",
           "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
WAIT = 60.0   # seconds a test waits for a condition (a process, a file); it never sleeps a fixed time


def wait_for(condition: Callable[[], Any]) -> Any:
    deadline = time.monotonic() + WAIT
    while time.monotonic() < deadline:
        found = condition()
        if found:
            return found
        time.sleep(0.02)
    raise AssertionError("condition not met in %s seconds" % WAIT)


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


class Recorder:
    """A runner that records every program and answers from `answers`: a function (argv) -> (returncode, stdout)."""

    def __init__(self, answers: Optional[Callable[[List[str]], Any]] = None) -> None:
        self.calls: List[List[str]] = []
        self.envs: List[dict] = []
        self.answers = answers or (lambda argv: (0, ""))

    def __call__(self, argv: List[str], **kwargs: Any) -> subprocess.CompletedProcess:
        self.calls.append(list(argv))
        self.envs.append(kwargs.get("env") or {})
        code, out = self.answers(list(argv))
        return subprocess.CompletedProcess(argv, code, out if kwargs.get("text") else None)

    def find(self, word: str) -> List[List[str]]:
        return [c for c in self.calls if word in c or any(word in part for part in c)]


def stubs(folder: str, names: List[str]) -> str:
    """A folder of do-nothing programs, for a PATH."""
    os.makedirs(folder, exist_ok=True)
    for name in names:
        path = os.path.join(folder, name)
        with open(path, "w") as handle:
            handle.write("#!/bin/sh\nexit 0\n")
        os.chmod(path, stat.S_IRWXU)
    return folder


class PaidPart(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = os.path.realpath(self.tmp.name)

    def ci(self, runner: Recorder, quick: bool = False, **env: str) -> relay_ci.Ci:
        base = {"PATH": stubs(os.path.join(self.root, "stub"), ["git", "jq", "python3", "bun", "claude"])}
        ci = relay_ci.Ci(self.root, quick, env={**base, **env}, runner=runner)
        ci.prepare()
        return ci

    def paid_answers(self, ceiling: str = "1 15") -> Callable[[List[str]], Any]:
        def answer(argv: List[str]) -> Any:
            if "ceiling" in argv:
                return 0, ceiling + "\n"
            if "estimate" in argv:
                return 0, "about $4\n"
            if "symbolic-ref" in argv:
                return 0, "master\n"
            if "rev-parse" in argv:
                return 0, "abc\n"
            return 0, ""
        return answer

    def test_the_eval_command_names_the_judge_model(self) -> None:
        # default sonnet; EVALS_JUDGE_MODEL replaces it
        rec = Recorder(self.paid_answers())
        with redirect_stdout(io.StringIO()):
            self.assertIsNone(self.ci(rec).plugin_evals())
        argv = rec.find("plugin")[-1]
        self.assertEqual(argv[argv.index("--judge-model") + 1], "sonnet")
        rec = Recorder(self.paid_answers())
        with redirect_stdout(io.StringIO()):
            self.ci(rec, EVALS_JUDGE_MODEL="opus").plugin_evals()
        argv = rec.find("plugin")[-1]
        self.assertEqual(argv[argv.index("--judge-model") + 1], "opus")

    def test_the_old_results_file_is_removed_before_the_eval_step(self) -> None:
        evals_json = os.path.join(self.root, ".ci", "evals.json")
        seen = []

        def answer(argv: List[str]) -> Any:
            if argv[0] == "claude":
                seen.append(os.path.exists(evals_json))   # the file as the eval tool starts
            return self.paid_answers()(argv)
        ci = self.ci(Recorder(answer))
        with open(evals_json, "w") as handle:
            handle.write("{}")
        with redirect_stdout(io.StringIO()):
            ci.plugin_evals()
        self.assertEqual(seen, [False])

    def test_the_ceiling_and_jobs_come_from_paid_cost_and_reach_the_eval_tool(self) -> None:
        # paid-cost answers "2 9.5": two jobs, a $9.5 ceiling; unset EVALS_MAX_COST asks for the estimate with a $15 cap
        rec = Recorder(self.paid_answers("2 9.5"))
        with redirect_stdout(io.StringIO()):
            self.ci(rec, EVALS_JOBS="2").plugin_evals()
        ceiling = rec.find("ceiling")[0]
        self.assertEqual(ceiling[ceiling.index("--within-day"):], ["--within-day", "--from-estimate", "--cap", "15", "--jobs", "2"])
        argv = rec.find("plugin")[-1]
        self.assertEqual(argv[argv.index("-j") + 1], "2")
        self.assertEqual(argv[argv.index("--max-cost-usd") + 1], "9.5")

    def test_the_owners_fixed_number_replaces_the_estimate(self) -> None:
        rec = Recorder(self.paid_answers())
        with redirect_stdout(io.StringIO()):
            self.ci(rec, EVALS_MAX_COST="7").plugin_evals()
        ceiling = rec.find("ceiling")[0]
        self.assertEqual(ceiling[ceiling.index("--within-day"):], ["--within-day", "--cap", "7", "--jobs", "1"])

    def test_a_refused_guard_ends_the_gate_before_claude_is_called(self) -> None:
        rec = Recorder(lambda argv: (1, "") if "guard" in argv else (0, ""))
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(self.ci(rec).plugin_evals(), 1)
        self.assertIn("the day's paid-run cap", out.getvalue())
        self.assertEqual(rec.find("claude"), [])

    def test_no_ceiling_ends_the_gate(self) -> None:
        rec = Recorder(lambda argv: (1, "") if "ceiling" in argv else (0, ""))
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(self.ci(rec).plugin_evals(), 1)
        self.assertIn("no money ceiling", out.getvalue())
        self.assertEqual(rec.find("claude"), [])

    def record(self, code: int) -> "tuple[relay_ci.Ci, str]":
        rec = Recorder(lambda argv: (code, "") if "bin/eval-record" in argv else (0, "master\n"))
        ci = self.ci(rec)
        out = io.StringIO()
        with redirect_stdout(out):
            ci.record()
        return ci, out.getvalue()

    def test_the_record_step_decides_the_gate(self) -> None:
        # eval-record exit 0 keeps the gate green; 1 (copy failed) and 2 (not judged / meaning grader failed) turn it red
        ci, out = self.record(0)
        self.assertEqual((ci.status, out), (0, ""))
        ci, out = self.record(1)
        self.assertEqual(ci.status, 1)
        self.assertIn("could not be stored", out)
        ci, out = self.record(2)
        self.assertEqual(ci.status, 1)
        self.assertIn("not a pass", out)

    def test_the_record_step_runs_in_the_full_gate_only_and_after_the_evals(self) -> None:
        for quick in (True, False):
            rec = Recorder(self.paid_answers())
            with redirect_stdout(io.StringIO()):
                ci = self.ci(rec, quick=quick)
                ci.main()
            names = ["eval-record" if "bin/eval-record" in c else "evals" if "eval" in c and c[0] == "claude" else ""
                     for c in rec.calls]
            if quick:
                self.assertNotIn("eval-record", names)
                self.assertNotIn("evals", names)
            else:
                self.assertLess(names.index("evals"), names.index("eval-record"))

    def test_the_rules_gate_runs_exactly_the_named_tests(self) -> None:
        # F2: relay_textonly names two tests; the unittest runner gets those two names and nothing else
        def answer(argv: List[str]) -> Any:
            return (0, "tests.test_a tests.test_b.C\n") if argv[-1] == "tests" else (0, "")
        rec = Recorder(answer)
        ci = self.ci(rec)
        with open(os.path.join(self.root, "log"), "w") as log:
            self.assertEqual(ci.rules_tests(log), 0)
        runner = [c for c in rec.calls if "tests/run_unittest.py" in c][0]
        self.assertEqual(runner[runner.index("tests/run_unittest.py") + 1:], ["tests.test_a", "tests.test_b.C"])
        self.assertEqual(rec.calls[-1], ["python3", "bin/relay", "sync", "--dry"])


class ProbeBesideTheRun(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = os.path.realpath(self.tmp.name)
        self.env = {**os.environ, **GIT_ENV}
        subprocess.run(["git", "init", "-q", "-b", "master", self.root], check=True, env=self.env)
        with open(os.path.join(self.root, "docs.txt"), "w") as handle:
            handle.write("x\n")
        subprocess.run(["git", "-C", self.root, "add", "-A"], check=True, env=self.env)
        subprocess.run(["git", "-C", self.root, "commit", "-q", "-m", "init"], check=True, env=self.env)
        self.head = subprocess.run(["git", "-C", self.root, "rev-parse", "HEAD"], check=True, capture_output=True, text=True,
                                   env=self.env).stdout.strip()

    def worktrees(self) -> List[str]:
        out = subprocess.run(["git", "-C", self.root, "worktree", "list", "--porcelain"], check=True, capture_output=True,
                             text=True, env=self.env).stdout
        return [ln for ln in out.splitlines() if ln.startswith("worktree ")]

    def probe(self, script: str) -> relay_ci.Probe:
        log = os.path.join(self.root, ".ci", "steps", "inert-nested.log")
        return relay_ci.Probe(self.root, self.head, True, self.env, log, nested=("sh", "-c", script))

    def test_stop_ends_the_probe_and_everything_below_it_and_removes_the_worktree(self) -> None:
        # case 3: the outer run leaves early; the nested run's own child (sleep) must not outlive it, and no worktree stays
        probe = self.probe("sleep 600 & wait")
        probe.start()
        self.assertEqual(len(self.worktrees()), 2)
        assert probe.proc is not None
        child = wait_for(lambda: relay_ci._descendants(probe.proc.pid))[0]
        probe.stop()
        self.assertIsNotNone(probe.proc.poll())
        wait_for(lambda: not alive(child))
        self.assertEqual(len(self.worktrees()), 1)
        probe.stop()   # twice is safe

    def test_the_probe_is_running_before_the_first_step_and_a_step_that_stops_the_run_removes_it(self) -> None:
        # B: the nested run starts before "library tests", not after "plugin validate"; an interrupt in a step stops it
        flag = os.path.join(self.root, "flag")
        env = {"PATH": os.environ["PATH"], "RELAY_GATE": self.head, "FLAG": flag}
        ci = relay_ci.Ci(self.root, True, env=env)
        ci.nested = ("sh", "-c", 'until [ -e "$FLAG" ]; do sleep 0.02; done')
        started = []

        def library_tests(log: Any) -> int:
            try:
                assert ci.probe is not None and ci.probe.proc is not None
                started.append(ci.probe.proc.poll() is None)   # still running: it began before this step
                raise KeyboardInterrupt
            finally:
                open(flag, "w").close()   # lets a nested run end, so a failing test never hangs
        ci.lib_tests = library_tests   # type: ignore[assignment,method-assign]
        with redirect_stdout(io.StringIO()), self.assertRaises(KeyboardInterrupt):
            ci.main()
        self.assertEqual(started, [True])
        assert ci.probe is not None and ci.probe.proc is not None
        self.assertIsNotNone(ci.probe.proc.poll())
        self.assertEqual(len(self.worktrees()), 1)

    def test_a_probe_that_dies_makes_inert_failed(self) -> None:
        # case 2: the nested run is killed (signal 9) -> exit code -9 -> the step is FAILED, never ok
        ci = relay_ci.Ci(self.root, True, env={"PATH": os.environ["PATH"], "RELAY_GATE": self.head})
        ci.prepare()
        ci.probe = self.probe("kill -9 $$")
        out = io.StringIO()
        with redirect_stdout(out):
            ci.probe.start()
            ci.step("inert", ci.inert_step, show_all=True)
            ci.probe.stop()
        self.assertEqual(ci.status, 1)
        self.assertIn("ci: inert FAILED", out.getvalue())
        self.assertIn("stopped by signal 9", out.getvalue())
        self.assertEqual(len(self.worktrees()), 1)


if __name__ == "__main__":
    unittest.main()
