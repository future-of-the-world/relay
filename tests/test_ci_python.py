"""lib/relay_ci.py (what bin/ci runs): the paid part, the record step, the rules gate's test names, and the inert probe that
runs beside the outer steps. Free; no model call. Programs are replaced by a recording runner or by stubs in a temporary
PATH; every tree is a temporary folder."""
import contextlib
import io
import json
import os
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock
from contextlib import redirect_stdout
from typing import Any, Callable, List, Optional

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
import relay_ci  # noqa: E402
import relay_ci_probe  # noqa: E402
from pidfile import wait_pid  # noqa: E402

GIT_ENV = {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull, "GIT_AUTHOR_NAME": "t",
           "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
WAIT = 600.0  # seconds a test waits for a condition (a process, a file); it never sleeps a fixed time


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


class PythonPin(unittest.TestCase):
    def root(self, text: str) -> str:
        tmp = tempfile.mkdtemp(prefix="relay-ci-pin-")
        self.addCleanup(__import__("shutil").rmtree, tmp, True)
        with open(os.path.join(tmp, "deps.toml"), "w") as handle:
            handle.write(text)
        return tmp

    PIN = '[[dep]]\nname = "python3"\nmin = "3.14.6"\nexact = true\n'

    def test_another_python_is_refused_with_the_version_it_wants(self) -> None:
        got = relay_ci.python_problem(self.root(self.PIN), (3, 11, 9))
        assert got is not None
        self.assertIn("python3 is 3.11.9", got)
        self.assertIn("pins 3.14.6", got)

    def test_the_pinned_python_passes(self) -> None:
        self.assertIsNone(relay_ci.python_problem(self.root(self.PIN), (3, 14, 6)))

    def test_no_pin_means_no_refusal(self) -> None:
        self.assertIsNone(relay_ci.python_problem(self.root('[[dep]]\nname = "python3"\nmin = "3.11"\n'), (3, 9, 1)))

    def test_main_refuses_before_any_step(self) -> None:
        root = self.root(self.PIN.replace("3.14.6", "2.7.1"))   # a pin this python can never be
        self.assertEqual(relay_ci.main([], root), 1)


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
        ci.lib_links = lambda log: 0   # type: ignore[method-assign]  # the root here is no git repository: the step reads HEAD
        ci.prepare()
        return ci

    def test_a_step_summary_names_a_test_that_raised(self) -> None:
        # unittest's controller prints "ERROR: <test id>" for a test that raised; "ERROR" in capitals matched no finding
        def failing(log: Any) -> int:
            log.write("ERROR: test_x (m.C.test_x)\nTraceback (most recent call last):\nValueError: boom\n")
            return 1
        ci = self.ci(Recorder())
        out = io.StringIO()
        with redirect_stdout(out):
            ci.step("lib", failing)
        self.assertIn("    ERROR: test_x (m.C.test_x)", out.getvalue().splitlines())

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

    def test_the_eval_tool_keeps_its_run_folders_for_the_record_step(self) -> None:
        # without --keep-temp the failing runs' traces are deleted before bin/eval-record can copy them (26 Oct)
        rec = Recorder(self.paid_answers())
        with redirect_stdout(io.StringIO()):
            self.ci(rec).plugin_evals()
        self.assertIn("--keep-temp", rec.find("plugin")[-1])

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

    def fast_first(self, red: str) -> "tuple[list[str], str, int]":
        """Run the quick gate with every step replaced by a recorder; `red` is the step name that fails ('' for none)."""
        ci = self.ci(Recorder(self.paid_answers()), quick=True)
        order: List[str] = []
        for attr, name in (("lib_tests", "library tests"), ("types_lint", "types and lint"), ("hook_tests", "hook tests"),
                           ("lib_links", "plugin lib links"), ("grader_tests", "eval grader tests"),
                           ("validate_all", "plugin validate")):
            def fn(log: Any, name: str = name) -> int:
                order.append(name)
                return 1 if name == red else 0
            setattr(ci, attr, fn)
        out = io.StringIO()
        with redirect_stdout(out):
            code = ci.main()
        return order, out.getvalue(), code

    def test_a_lib_copy_is_reported_before_the_library_tests_start(self) -> None:
        # design A.3: the seconds-long steps run first; a red one ends the gate before the 4-10 minute steps
        order, out, code = self.fast_first("plugin lib links")
        self.assertEqual(order, ["types and lint", "plugin lib links"])   # library tests never started
        self.assertIn("plugin lib links FAILED", out)
        self.assertEqual(code, 1)
        self.assertIn("ci: RED", out)

    def test_a_lint_error_is_reported_first_and_ends_the_gate_red(self) -> None:
        order, out, code = self.fast_first("types and lint")
        self.assertNotIn("library tests", order)
        self.assertNotIn("hook tests", order)
        self.assertEqual(order[0], "types and lint")
        self.assertIn("types and lint FAILED", out)
        self.assertEqual(code, 1)

    def test_a_green_tree_runs_every_step_with_the_fast_ones_first(self) -> None:
        order, out, code = self.fast_first("")
        self.assertEqual(order, ["types and lint", "plugin lib links", "library tests", "hook tests",
                                 "eval grader tests", "plugin validate"])
        self.assertEqual(code, 0)

    def test_a_run_that_timed_out_keeps_the_gate_green_when_the_other_two_passed(self) -> None:
        # the gate's own verdict (plugin_evals + record, bin/eval-record run for real): PASS, PASS, timed out is 2 of 3
        self.assertEqual(self.gate_verdict_for([True, True, None]), 0)
        self.assertEqual(self.gate_verdict_for([True, None, None]), 1)

    def gate_verdict_for(self, runs: "List[Optional[bool]]") -> int:
        """Runs the gate's eval and record steps over a case whose runs passed (True) or timed out (None); returns ci.status."""
        def run(passed: Optional[bool]) -> dict:
            if passed is None:
                return {"error": "timed out after 600s", "graders": []}
            return {"graders": [{"name": "g", "type": "llm", "passed": True, "judgeVotes": [True] * 3}]}
        data = {"startedAt": "2026-10-27T10:00:00.000Z", "costUsd": 1.0,
                "cases": [{"name": "c", "runsPerCase": 3, "graders": [{"name": "g", "type": "llm"}],
                           "arms": {"with": [run(r) for r in runs]}}]}
        real = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin", "eval-record")
        home = os.path.join(self.root, "home")

        def answer(argv: List[str]) -> Any:
            if argv[0] == "claude":
                os.makedirs(os.path.join(self.root, ".ci"), exist_ok=True)
                with open(os.path.join(self.root, ".ci", "evals.json"), "w") as handle:
                    json.dump(data, handle)
                return 1, ""   # the eval tool exits 1 when a run failed
            if "bin/eval-record" in argv:
                done = subprocess.run([sys.executable, real, *argv[2:], "--repo", "t"], cwd=self.root, text=True, capture_output=True,
                                      env=dict(os.environ, RELAY_HOME=home))
                return done.returncode, done.stdout
            return self.paid_answers()(argv)
        ci = self.ci(Recorder(answer))
        with redirect_stdout(io.StringIO()):
            self.assertIsNone(ci.plugin_evals())
            ci.record()
        return ci.status

    def test_the_eval_tools_exit_code_does_not_decide_the_gate_the_records_majority_does(self) -> None:
        # Q1 of the majority item: the eval tool exits 1 when any run failed, yet the case with runs PASS PASS FAIL
        # passes by majority (2 of 3). The gate takes the verdict from bin/eval-record, so it stays green.
        def run(passed: bool) -> dict:
            votes = [passed] * 3
            return {"graders": [{"name": "g", "type": "llm", "passed": passed, "judgeVotes": votes}]}
        data = {"startedAt": "2026-10-27T10:00:00.000Z", "costUsd": 1.0,
                "cases": [{"name": "c", "runsPerCase": 3, "graders": [{"name": "g", "type": "llm"}],
                           "arms": {"with": [run(True), run(True), run(False)]}}]}
        real = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin", "eval-record")
        home = os.path.join(self.root, "home")

        def answer(argv: List[str]) -> Any:
            if argv[0] == "claude":
                os.makedirs(os.path.join(self.root, ".ci"), exist_ok=True)
                with open(os.path.join(self.root, ".ci", "evals.json"), "w") as handle:
                    json.dump(data, handle)
                return 1, ""   # the eval tool's exit code for one failed run
            if "bin/eval-record" in argv:
                done = subprocess.run([sys.executable, real, *argv[2:], "--repo", "t"], cwd=self.root, text=True, capture_output=True,
                                      env=dict(os.environ, RELAY_HOME=home))
                return done.returncode, done.stdout
            return self.paid_answers()(argv)
        ci = self.ci(Recorder(answer))
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertIsNone(ci.plugin_evals())
            ci.record()
        self.assertEqual((ci.status, out.getvalue()), (0, out.getvalue()))
        self.assertNotIn("FAILED", out.getvalue())

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


class QuickGateLimit(unittest.TestCase):
    """The quick gate stops itself at its time limit (RELAY_CI_QUICK_LIMIT seconds, from the start of Ci.main): exit 124 and a
    named step, the whole process tree ended. Steps are replaced by stubs; the long ones are real child processes."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = os.path.realpath(self.tmp.name)

    def ci(self, limit: str, quick: bool = True, **env: str) -> relay_ci.Ci:
        ci = relay_ci.Ci(self.root, quick, env={"PATH": os.environ["PATH"], "RELAY_CI_QUICK_LIMIT": limit, **env})
        for name in ("types_lint", "lib_links", "lib_tests", "hook_tests", "grader_tests", "validate_all"):
            setattr(ci, name, lambda log: 0)
        return ci

    def sleeper(self, ci: relay_ci.Ci, seconds: str = "600") -> Callable[[Any], int]:
        return lambda log: ci.run([sys.executable, "-c", "import time; time.sleep(%s)" % seconds], log).returncode

    def run_main(self, ci: relay_ci.Ci) -> tuple:
        out = io.StringIO()
        with redirect_stdout(out):
            code = ci.main()
        with open(os.path.join(self.root, ".ci", "results.txt")) as handle:
            results = handle.read().splitlines()
        return code, out.getvalue().splitlines(), results

    def test_t1_a_stop_ends_the_child_and_the_grandchild_and_names_the_step(self) -> None:
        # limit 2 s; the step is a shell with a background sleep (a grandchild of the gate) and a foreground sleep
        pid_file = os.path.join(self.root, "grandchild.pid")
        ci = self.ci("2")
        ci.lib_tests = lambda log: ci.run(["sh", "-c", "sleep 600 & echo $! > '%s'; sleep 600" % pid_file], log).returncode   # type: ignore[method-assign]
        code, lines, results = self.run_main(ci)
        self.assertEqual(code, 124)
        # worked out from the design: the 2 s limit is not a whole number of minutes, so "the 2-second limit"
        self.assertIn("gate: stopped at the 2-second limit, step library tests was running", lines)
        self.assertIn("ci: RED (stopped at the time limit, not a test failure: run the gate again; the step's log is "
                      ".ci/steps/library-tests.log)", lines)
        self.assertIn("library tests STOPPED", results)
        self.assertEqual([ln for ln in lines if "FAILED" in ln], [])
        grandchild = wait_pid(pid_file)
        wait_for(lambda: not alive(grandchild))

    def test_t2_a_normal_run_is_green_and_the_watchdog_has_ended(self) -> None:
        code, lines, results = self.run_main(self.ci("3"))
        self.assertEqual(code, 0)
        self.assertEqual(lines[-1], "ci: green (QUICK MODE: paid steps skipped, not a release gate)")
        self.assertNotIn("library tests STOPPED", results)
        self.assertEqual([t for t in threading.enumerate() if isinstance(t, threading.Timer) and t.is_alive()], [])

    def test_t3_the_full_gate_has_no_limit(self) -> None:
        ci = self.ci("1", quick=False)    # the step runs 2 s, past the 1 s limit; no claude on PATH ends the full gate red by its own rule
        ci.lib_tests = self.sleeper(ci, "2")    # type: ignore[method-assign]
        code, lines, results = self.run_main(ci)
        self.assertNotEqual(code, 124)
        self.assertEqual([ln for ln in lines if ln.startswith("gate: stopped")], [])
        self.assertIn("library tests ok", results)

    def test_t4_the_inert_probe_run_has_no_limit_of_its_own(self) -> None:
        ci = self.ci("1", RELAY_INERT_PROBE="1")
        ci.lib_tests = self.sleeper(ci, "2")    # type: ignore[method-assign]
        code, lines, results = self.run_main(ci)
        self.assertEqual(code, 0)
        self.assertIn("library tests ok", results)

    def test_t5_a_real_failure_before_the_stop_wins(self) -> None:
        # library tests FAILED at once; hook tests then run past the 2 s limit: exit 1 (not 124), FAILED line first, stopped line after
        ci = self.ci("2")
        ci.lib_tests = lambda log: 1    # type: ignore[method-assign]
        ci.hook_tests = self.sleeper(ci)    # type: ignore[method-assign]
        code, lines, results = self.run_main(ci)
        self.assertEqual(code, 1)
        failed = next(i for i, ln in enumerate(lines) if "FAILED" in ln)
        stopped = lines.index("gate: stopped at the 2-second limit, step hook tests was running")
        self.assertIn("library tests FAILED", lines[failed])
        self.assertLess(failed, stopped)
        self.assertIn("hook tests STOPPED", results)
        self.assertEqual(lines[-1], "ci: RED")

    def test_f1_a_step_that_starts_programs_in_a_loop_ends_at_the_stop(self) -> None:
        # limit 2 s; the step runs three 600 s programs in a row (plugin validate's loop): after the kill the later ones are not started
        ci = self.ci("2")
        started = time.monotonic()

        def loop(log: Any) -> int:
            return max(self.sleeper(ci)(log) for _ in range(3))
        ci.validate_all = loop    # type: ignore[method-assign]
        code, lines, results = self.run_main(ci)
        self.assertEqual(code, 124)
        self.assertLess(time.monotonic() - started, 15)    # a bound, not a window: 3 x 600 s without the fix
        self.assertIn("gate: stopped at the 2-second limit, step plugin validate was running", lines)
        self.assertIn("plugin validate STOPPED", results)

    def test_f1_nothing_starts_after_the_stop(self) -> None:
        ci = self.ci("5")
        ci.stopped = True
        got = ci.run(["definitely-not-run"], None, capture=True)
        self.assertEqual(got.returncode, 124)

    def test_t7_a_bad_limit_setting_refuses_to_run(self) -> None:
        for bad in ("0", "abc", "-5", "1.5", ""):
            ci = self.ci(bad)
            err = io.StringIO()
            with redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
                code = ci.main()
            self.assertEqual(code, 2, bad)
            self.assertEqual(err.getvalue().strip(), "bin/ci: RELAY_CI_QUICK_LIMIT must be a whole number of seconds, 1 or more "
                                                     "(default 1800), not %r" % bad)
        self.assertEqual(relay_ci.quick_limit({}), 1800)    # the owner's 30 minutes (29 Oct)


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

    def test_a_probe_whose_lane_worktree_was_removed_is_removed_by_the_next_gate_of_any_worktree(self) -> None:
        # live case 29 Oct: a lane worktree removed (or killed) while its probe existed; the probe stays registered in the main
        # repository because the record sat in the lane's own .ci. Two lanes: lane_a dies with its probe, lane_b runs a gate.
        lanes = []
        for name in ("lane_a", "lane_b"):
            path = os.path.join(self.root, ".worktrees", name)
            subprocess.run(["git", "-C", self.root, "worktree", "add", "-q", "--detach", path, self.head], check=True, env=self.env)
            lanes.append(path)
        log = os.path.join(lanes[0], ".ci", "steps", "inert-nested.log")
        probe = relay_ci.Probe(lanes[0], self.head, True, self.env, log, nested=("true",))
        probe.start()
        probe.wait()
        # 1 main + 2 lanes + 1 probe; the gate of lane_a is gone without stop() (killed) and so is its worktree
        self.assertEqual(len(self.worktrees()), 4)
        subprocess.run(["git", "-C", self.root, "worktree", "remove", "--force", lanes[0]], check=True, env=self.env)
        self.assertEqual(len(self.worktrees()), 3)   # the probe is still registered: the leak
        relay_ci.remove_leftover_probe(lanes[1])
        self.assertEqual(len(self.worktrees()), 2)   # main + lane_b
        assert probe.tmpd is not None
        self.assertFalse(os.path.exists(probe.tmpd))

    def test_two_gates_that_read_one_dead_owner_record_at_once_both_return(self) -> None:
        # a probe worktree whose shared record names an owner folder that does not exist; two gates start together and both
        # read the record before either removes it: the probe is removed once and neither raises
        tmpd = tempfile.mkdtemp(dir=self.root)
        subprocess.run(["git", "-C", self.root, "worktree", "add", "-q", "--detach", os.path.join(tmpd, "wt"), self.head],
                       check=True, env=self.env)
        folder = relay_ci_probe.shared_dir(self.root)
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, os.path.basename(tmpd)), "w") as handle:
            handle.write(os.path.join(self.root, "missing-lane") + "\n" + tmpd + "\n")
        barrier = threading.Barrier(2)
        real = relay_ci_probe._read_lines

        def reading(path: str) -> List[str]:
            lines = real(path)
            if os.path.dirname(path) == folder:
                barrier.wait(timeout=WAIT)   # both threads hold the record's lines before either goes on
            return lines

        errors: List[BaseException] = []

        def gate() -> None:
            try:
                relay_ci_probe.remove_leftover_probe(self.root)
            except BaseException as err:  # noqa: BLE001 - the test reports whatever escaped
                errors.append(err)

        with mock.patch.object(relay_ci_probe, "_read_lines", reading):
            threads = [threading.Thread(target=gate) for _ in range(2)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
        self.assertEqual(errors, [])
        self.assertEqual(len(self.worktrees()), 1)   # main only
        self.assertEqual(os.listdir(folder), [])

    def test_a_probe_of_a_live_lane_is_not_touched_by_the_gate_of_another_lane(self) -> None:
        lanes = []
        for name in ("lane_a", "lane_b"):
            path = os.path.join(self.root, ".worktrees", name)
            subprocess.run(["git", "-C", self.root, "worktree", "add", "-q", "--detach", path, self.head], check=True, env=self.env)
            lanes.append(path)
        probe = relay_ci.Probe(lanes[0], self.head, True, self.env, os.path.join(lanes[0], ".ci", "n.log"), nested=("true",))
        probe.start()
        probe.wait()
        self.addCleanup(probe.stop)
        relay_ci.remove_leftover_probe(lanes[1])
        self.assertEqual(len(self.worktrees()), 4)   # main + 2 lanes + the live probe

    def test_the_probe_run_is_marked_so_its_test_runner_only_reads_the_class_times(self) -> None:
        # the nested run gets RELAY_INERT_PROBE=1 (the outer run's environment does not have it)
        mark = os.path.join(self.root, "mark.txt")
        probe = self.probe('printf "%%s" "$RELAY_INERT_PROBE" > "%s"' % mark)
        probe.start()
        probe.wait()
        with open(mark) as handle:
            self.assertEqual(handle.read(), "1")
        probe.stop()

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
        ci.types_lint = lambda log: 0   # type: ignore[assignment,method-assign]  # the fast steps run before library tests
        ci.lib_links = lambda log: 0   # type: ignore[assignment,method-assign]
        with redirect_stdout(io.StringIO()), self.assertRaises(KeyboardInterrupt):
            ci.main()
        self.assertEqual(started, [True])
        assert ci.probe is not None and ci.probe.proc is not None
        self.assertIsNotNone(ci.probe.proc.poll())
        self.assertEqual(len(self.worktrees()), 1)

    def test_t6_a_stop_at_the_limit_removes_the_probe_and_its_record(self) -> None:
        env = {"PATH": os.environ["PATH"], "RELAY_GATE": self.head, "RELAY_CI_QUICK_LIMIT": "2"}
        ci = relay_ci.Ci(self.root, True, env=env)
        ci.nested = ("sh", "-c", "sleep 600 & wait")
        for name in ("types_lint", "lib_links", "hook_tests", "grader_tests", "validate_all"):
            setattr(ci, name, lambda log: 0)
        ci.lib_tests = lambda log: ci.run([sys.executable, "-c", "import time; time.sleep(600)"], log).returncode   # type: ignore[method-assign]
        with redirect_stdout(io.StringIO()):
            code = ci.main()
        self.assertEqual(code, 124)
        assert ci.probe is not None and ci.probe.proc is not None
        self.assertIsNotNone(ci.probe.proc.poll())
        self.assertEqual(len(self.worktrees()), 1)
        self.assertFalse(os.path.exists(os.path.join(self.root, ".ci", "inert-probe")))

    def test_f3_the_probe_cleanup_starts_after_the_watchdog_has_finished_its_kills(self) -> None:
        # the watchdog's kills are replaced by 0.5 s of work (the probe's own stop_tree calls are not); the step returns at once,
        # so without the fix Probe.stop (git worktree remove) starts while the watchdog may still kill every descendant
        env = {"PATH": os.environ["PATH"], "RELAY_GATE": self.head, "RELAY_CI_QUICK_LIMIT": "1"}
        ci = relay_ci.Ci(self.root, True, env=env)
        ci.nested = ("sh", "-c", "sleep 600 & wait")
        for name in ("types_lint", "lib_links", "hook_tests", "grader_tests", "validate_all"):
            setattr(ci, name, lambda log: 0)
        order: list[str] = []
        entered = threading.Event()
        ci.lib_tests = lambda log: (entered.wait(30), 0)[1]    # type: ignore[method-assign]
        real_stop_tree, real_probe_stop = relay_ci.stop_tree, relay_ci.Probe.stop

        def slow_stop(pids: Any, root: Any) -> None:
            if not isinstance(threading.current_thread(), threading.Timer):
                return real_stop_tree(pids, root)
            entered.set()
            time.sleep(0.5)
            order.append("kills end")

        def probe_stop(probe: Any) -> None:
            order.append("cleanup")
            real_probe_stop(probe)
        relay_ci.stop_tree, relay_ci.Probe.stop = slow_stop, probe_stop    # type: ignore[assignment,method-assign]
        self.addCleanup(lambda: (setattr(relay_ci, "stop_tree", real_stop_tree), setattr(relay_ci.Probe, "stop", real_probe_stop)))
        with redirect_stdout(io.StringIO()):
            self.assertEqual(ci.main(), 124)
        self.assertEqual(order, ["kills end", "cleanup"])
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

    def test_a_gate_killed_without_cleanup_leaves_a_probe_that_the_next_run_of_that_worktree_removes(self) -> None:
        # F1: relay gate SIGKILLs the group, so stop() never runs; the record in .ci/inert-probe lets the next prepare() clean up
        probe = self.probe("sleep 600 & wait")
        probe.start()
        assert probe.proc is not None and probe.tmpd is not None
        left = probe.tmpd
        child = wait_for(lambda: relay_ci._descendants(probe.proc.pid))[0]
        for pid in (child, probe.proc.pid):   # the kill: no finally, no stop()
            os.kill(pid, 9)
        probe.proc.wait()
        self.assertEqual(len(self.worktrees()), 2)   # the leak, as reproduced
        ci = relay_ci.Ci(self.root, True, env={"PATH": os.environ["PATH"]})
        ci.prepare()
        self.assertEqual(len(self.worktrees()), 1)
        self.assertFalse(os.path.exists(left))
        self.assertFalse(os.path.exists(os.path.join(self.root, ".ci", "inert-probe")))

    def test_cleanup_removes_only_the_probe_recorded_for_this_worktree(self) -> None:
        # pass case 2: a second worktree of the repo has a live probe; the first one's prepare() leaves it alone
        other = os.path.join(self.root, "other")
        subprocess.run(["git", "-C", self.root, "worktree", "add", "-q", "--detach", other, self.head], check=True, env=self.env)
        live = probe_for(other, self.head, self.env)
        live.start()
        try:
            relay_ci.Ci(self.root, True, env={"PATH": os.environ["PATH"]}).prepare()
            self.assertTrue(os.path.isdir(live.work))
            self.assertEqual(len(self.worktrees()), 3)   # root, other, the live probe
        finally:
            live.stop()

    def test_a_probe_that_ends_normally_leaves_no_record(self) -> None:
        probe = self.probe("true")
        probe.start()
        probe.wait()
        probe.stop()
        self.assertFalse(os.path.exists(os.path.join(self.root, ".ci", "inert-probe")))
        self.assertEqual(len(self.worktrees()), 1)


def probe_for(root: str, head: str, env: Any) -> relay_ci.Probe:
    return relay_ci.Probe(root, head, True, env, os.path.join(root, ".ci", "steps", "inert-nested.log"),
                          nested=("sh", "-c", "sleep 600"))


class LockFdReachesChildren(unittest.TestCase):
    def test_a_fd_inherited_by_the_gate_is_open_in_step_children_and_in_the_probe(self) -> None:
        # F2: relay gate passes a lock fd; every child of bin/ci must keep it (close_fds=False), or killing bin/ci frees the lock
        genv = {**os.environ, **GIT_ENV}
        with tempfile.TemporaryDirectory() as tmp:
            fd = os.open(os.path.join(tmp, "lock"), os.O_CREAT | os.O_RDWR)
            try:
                os.set_inheritable(fd, True)
                ci = relay_ci.Ci(tmp, True, env={"PATH": os.environ["PATH"]})
                self.assertEqual(ci.run(["sh", "-c", "test -e /dev/fd/%d" % fd]).returncode, 0)
                root = os.path.join(tmp, "repo")
                os.makedirs(root)
                subprocess.run(["git", "init", "-q", root], check=True, env=genv)
                subprocess.run(["git", "-C", root, "commit", "-q", "--allow-empty", "-m", "i"], check=True, env=genv)
                head = subprocess.run(["git", "-C", root, "rev-parse", "HEAD"], check=True, capture_output=True, text=True,
                                      env=genv).stdout.strip()
                probe = relay_ci.Probe(root, head, True, genv, os.path.join(root, ".ci", "n.log"),
                                       nested=("sh", "-c", "test -e /dev/fd/%d" % fd))
                try:
                    probe.start()
                    self.assertEqual(probe.wait(), 0)
                finally:
                    probe.stop()   # also when an assertion fails: the worktree and its temporary folder never stay
            finally:
                os.close(fd)


if __name__ == "__main__":
    unittest.main()
