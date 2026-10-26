"""tests/parallel_unittest.py: the library tests on several processes split by class, and the per-machine class times file.
Free. Every tree is a temporary folder with a few tiny test files; RELAY_HOME is a temporary folder too."""
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from typing import Dict, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import parallel_unittest  # noqa: E402

GIT_ENV = {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull, "GIT_AUTHOR_NAME": "t",
           "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}

TEST_FILE = '''import unittest

class %(cls)s(unittest.TestCase):
%(body)s
'''


def methods(count: int, extra: str = "") -> str:
    return "".join("    def test_m%d(self):\n        pass\n" % i for i in range(count)) + extra


class Tree(unittest.TestCase):
    """A folder with tests/ of its own and a RELAY_HOME of its own."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = os.path.join(os.path.realpath(self.tmp.name), "myrepo")
        self.tests = os.path.join(self.root, "tests")
        os.makedirs(self.tests)
        self.home = os.path.join(os.path.realpath(self.tmp.name), "home")
        # run() discovers in this process: the modules it imports and the paths it adds are taken back after each test
        modules, paths = set(sys.modules), list(sys.path)
        self.addCleanup(self.restore, modules, paths)

    @staticmethod
    def restore(modules: set, paths: list) -> None:
        for name in set(sys.modules) - modules:
            del sys.modules[name]
        sys.path[:] = paths

    def add(self, module: str, cls: str, body: str) -> None:
        with open(os.path.join(self.tests, module + ".py"), "w") as handle:
            handle.write(TEST_FILE % {"cls": cls, "body": body})

    def env(self, **more: str) -> Dict[str, str]:
        env = {k: v for k, v in os.environ.items() if k not in ("RELAY_TEST_JOBS", "RELAY_INERT_PROBE")}
        env.update(RELAY_HOME=self.home, **more)
        return env

    def go(self, jobs: str = "4", **more: str) -> Tuple[int, str]:
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = parallel_unittest.run(self.root, self.env(RELAY_TEST_JOBS=jobs, **more), self.tests)
        return code, buffer.getvalue()

    def times_file(self) -> str:
        return os.path.join(self.home, "test-times", "myrepo.json")

    def three_classes(self) -> None:
        self.add("test_a", "Small", methods(2))
        self.add("test_b", "Medium", methods(3))
        self.add("test_c", "Big", methods(4))


class Runs(Tree):
    def test_one_summed_ran_line_and_the_same_result_at_one_and_four_jobs(self) -> None:
        # case 6: 2 + 3 + 4 = 9 tests in three classes; however the classes are split, the log has ONE "Ran 9 tests" line
        self.three_classes()
        results = []
        for jobs in ("1", "4"):
            code, out = self.go(jobs)
            ran = [ln for ln in out.splitlines() if ln.startswith("Ran ")]
            self.assertEqual(code, 0, out)
            self.assertEqual(len(ran), 1, out)
            results.append(re.sub(r" in [0-9.]+s", "", ran[0]))
        self.assertEqual(results, ["Ran 9 tests", "Ran 9 tests"])

    def test_a_failing_test_in_any_class_fails_the_run_and_is_named(self) -> None:
        # case 7: a deliberately failing test in one class; the others pass; the failing one is named, the count still adds up
        self.three_classes()
        self.add("test_bad", "Bad", methods(1, "    def test_boom(self):\n        self.assertEqual(1, 2)\n"))
        code, out = self.go()
        self.assertEqual(code, 1, out)
        self.assertIn("FAIL: test_boom (test_bad.Bad.test_boom)", out)
        self.assertIn("FAILED (failures=1)", out)
        self.assertEqual(len([ln for ln in out.splitlines() if ln.startswith("Ran ")]), 1)
        self.assertIn("Ran 11 tests", out)

    def test_a_module_that_does_not_import_fails_the_run(self) -> None:
        self.three_classes()
        with open(os.path.join(self.tests, "test_broken.py"), "w") as handle:
            handle.write("import no_such_module_anywhere\n")
        code, out = self.go()
        self.assertEqual(code, 1, out)
        self.assertIn("test_broken", out)

    def test_a_worker_killed_mid_run_fails_the_step_and_writes_no_times(self) -> None:
        # case 7: a test that kills its own worker; the run is FAILED, names the class, and the times file is not written
        self.three_classes()
        self.add("test_kill", "Killer", "    def test_dies(self):\n        import os, signal\n"
                 "        os.kill(os.getpid(), signal.SIGKILL)\n")
        code, out = self.go()
        self.assertEqual(code, 1, out)
        self.assertIn("died while running test_kill.Killer", out)
        self.assertFalse(os.path.exists(self.times_file()))

    def test_a_worker_keeps_the_temporary_home_guard(self) -> None:
        # the worker runs every test with a temporary RELAY_HOME (tests/tmp_default.py), never the one the run was given
        self.add("test_home", "Home", "    def test_home_is_temporary(self):\n        import os\n"
                 "        assert os.environ['RELAY_HOME'] != %r, os.environ['RELAY_HOME']\n" % self.home)
        code, out = self.go()
        self.assertEqual(code, 0, out)

    def test_a_bad_jobs_value_fails_with_the_reason(self) -> None:
        self.three_classes()
        code, out = self.go("many")
        self.assertEqual(code, 1)
        self.assertIn("RELAY_TEST_JOBS=many is not a whole number", out)


class Times(Tree):
    def test_the_outer_run_writes_the_times_file_with_every_class(self) -> None:
        self.three_classes()
        self.assertEqual(self.go()[0], 0)
        with open(self.times_file()) as handle:
            classes = json.load(handle)["classes"]
        self.assertEqual(sorted(classes), ["test_a.Small", "test_b.Medium", "test_c.Big"])
        self.assertEqual(os.listdir(os.path.dirname(self.times_file())), ["myrepo.json"])   # no temporary file left

    def test_the_probe_only_reads_the_times_file(self) -> None:
        # case 7: the probe run (RELAY_INERT_PROBE=1) writes nothing; its outcome equals the outer run's
        self.three_classes()
        code, out = self.go(RELAY_INERT_PROBE="1")
        self.assertEqual(code, 0, out)
        self.assertFalse(os.path.exists(self.times_file()))
        outer = self.go()[1]
        probe = self.go(RELAY_INERT_PROBE="1")[1]
        pick = lambda text: [re.sub(r" in [0-9.]+s", "", ln) for ln in text.splitlines() if ln.startswith(("Ran ", "OK"))]
        self.assertEqual(pick(outer), pick(probe))

    def test_a_run_updates_only_the_classes_that_ran(self) -> None:
        os.makedirs(os.path.dirname(self.times_file()))
        with open(self.times_file(), "w") as handle:
            json.dump({"classes": {"test_gone.Old": 5.0}}, handle)
        self.three_classes()
        self.go()
        with open(self.times_file()) as handle:
            self.assertIn("test_gone.Old", json.load(handle)["classes"])

    def test_the_first_run_says_it_has_no_times_and_orders_by_count(self) -> None:
        self.three_classes()
        out = self.go()[1]
        self.assertIn("no times file (first run on this machine)", out)
        self.assertIn(os.path.join(self.home, "test-times", "myrepo.json"), out)   # the real searched path is printed at run time

    def test_order_by_count_without_times_and_by_time_with_them(self) -> None:
        counts = {"a.A": 2, "b.B": 3, "c.C": 4}
        # no file: the biggest count first
        self.assertEqual(parallel_unittest.order_classes(counts, {}), ["c.C", "b.B", "a.A"])
        # times beat counts (the slow class has the fewest tests); a class without a time goes first
        self.assertEqual(parallel_unittest.order_classes(counts, {"a.A": 50.0, "b.B": 1.0}), ["c.C", "a.A", "b.B"])

    def test_an_unreadable_or_misshapen_times_file_is_ignored_with_the_reason(self) -> None:
        for text, reason in (("not json", "unreadable"), ('{"classes": {"a.A": "slow"}}', "unexpected shape"), ("[]", "unexpected shape")):
            path = os.path.join(self.tmp.name, "t.json")
            with open(path, "w") as handle:
                handle.write(text)
            times, note = parallel_unittest.load_times(path)
            self.assertEqual(times, {})
            self.assertIn(reason, note)

    def test_the_repo_name_is_the_main_checkouts_folder_for_every_worktree(self) -> None:
        main = os.path.join(os.path.realpath(self.tmp.name), "mainrepo")
        os.makedirs(main)
        env = {**os.environ, **GIT_ENV}
        for argv in (["init", "-q", "-b", "master"], ["commit", "-q", "--allow-empty", "-m", "i"],
                     ["worktree", "add", "-q", os.path.join(main, ".worktrees", "w"), "-b", "wt/w"]):
            subprocess.run(["git", "-C", main, *argv], check=True, env=env)
        self.assertEqual(parallel_unittest.repo_name(os.path.join(main, ".worktrees", "w")), "mainrepo")
        self.assertEqual(parallel_unittest.repo_name(main), "mainrepo")


class Jobs(unittest.TestCase):
    def test_default_four_and_bounded_by_the_cores(self) -> None:
        self.assertEqual(parallel_unittest.jobs_setting({}, 12), (4, ""))
        self.assertEqual(parallel_unittest.jobs_setting({}, 2), (2, ""))
        self.assertEqual(parallel_unittest.jobs_setting({"RELAY_TEST_JOBS": "1"}, 12), (1, ""))
        jobs, note = parallel_unittest.jobs_setting({"RELAY_TEST_JOBS": "99"}, 12)
        self.assertEqual(jobs, 12)
        self.assertIn("outside 1..12", note)
        jobs, note = parallel_unittest.jobs_setting({"RELAY_TEST_JOBS": "0"}, 12)
        self.assertEqual(jobs, 1)
        self.assertEqual(parallel_unittest.jobs_setting({"RELAY_TEST_JOBS": "-3"}, 12)[0], 0)


if __name__ == "__main__":
    unittest.main()
