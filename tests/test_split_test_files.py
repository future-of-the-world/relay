"""Q1 of one-shared-test-file-makes-parallel-changes-conf: no test file is so large that every parallel change must append to it."""
import os
import subprocess
import sys
import unittest

TESTS = os.path.dirname(os.path.abspath(__file__))
# tests/test_relay.py was 2008 lines with 17 classes and was the file all three conflicting merges of 24 Oct appended to.
# The largest file now is test_queue.py (1342 lines), so the cap leaves it room and refuses a return of one shared file.
MAX_LINES = 1500

ROOT = os.path.dirname(TESTS)
sys.path.insert(0, os.path.join(ROOT, "lib"))

import relay_queue  # noqa: E402
import relay_textonly  # noqa: E402
sys.path.insert(0, TESTS)
from test_queue import QUEUE_COMMIT, show_raw  # noqa: E402


class TestFilesStaySplit(unittest.TestCase):
    def test_no_test_file_is_longer_than_the_cap(self) -> None:
        too_long = []
        for name in sorted(os.listdir(TESTS)):
            if not name.endswith(".py"):
                continue
            with open(os.path.join(TESTS, name)) as handle:
                lines = len(handle.read().splitlines())
            if lines > MAX_LINES:
                too_long.append(f"{name}: {lines} lines")
        self.assertEqual(too_long, [])

    def test_the_old_shared_file_is_gone(self) -> None:
        self.assertFalse(os.path.exists(os.path.join(TESTS, "test_relay.py")))

    def test_the_rule_tests_import_the_way_the_short_gate_loads_them(self) -> None:
        # bin/ci runs `python3 -m unittest <RULE_TESTS names>` from the repository root, with nothing on sys.path but the root,
        # so each test file must find relay_testbase itself. On master the 117 tests loaded; the moved files failed to import.
        code = ("import sys, unittest\n"
                "def walk(s):\n"
                "    for t in s:\n"
                "        yield from walk(t) if isinstance(t, unittest.TestSuite) else [t]\n"
                "suite = unittest.defaultTestLoader.loadTestsFromNames(sys.argv[1:])\n"
                "print([t.id() for t in walk(suite) if t.__class__.__name__ == '_FailedTest'])\n")
        env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
        done = subprocess.run([sys.executable, "-c", code, *relay_textonly.RULE_TESTS], cwd=ROOT, env=env, capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stdout.strip(), "[]", done.stderr)


class TestDoneItemsKeepTheirTests(unittest.TestCase):
    def test_a_done_item_keeps_the_test_id_it_closed_with_and_the_test_is_found_by_name_under_tests(self) -> None:
        # a done item's test id is the dated fact of how it closed: the split does not rewrite it (no reader re-runs it).
        # The test it names moved out of tests/test_relay.py, so it is found by its name in any file under tests/.
        expected = {"runner-turns-while-waiting": "tests/test_relay.py::test_a_job_longer_than_a_runner_s_turns_runs_in_the_front_s_background",
                    "a-new-openspec-project-silently-has-no-openspec": "tests/test_relay.py::test_setup_install_failure_todo_names_the_command"}
        sources = []
        for name in sorted(os.listdir(TESTS)):
            if name.endswith(".py"):
                with open(os.path.join(TESTS, name), encoding="utf-8") as handle:
                    sources.append(handle.read())
        problems = []
        for slug, recorded in expected.items():
            # a pinned commit, never the live queue: a queue event must not turn this red
            item = relay_queue.parse(slug, show_raw(ROOT, QUEUE_COMMIT, ".relay/queue/done/" + slug + ".json"))
            if item["problems"]:
                problems.append(f"{slug}: {item['problems']}")
            elif item["test"] != recorded:
                problems.append(f"{slug}: the recorded test was rewritten to {item['test']}")
            if not any("def " + recorded.rpartition("::")[2] + "(" in text for text in sources):
                problems.append(f"{slug}: {recorded.rpartition('::')[2]} is defined in no file under tests/")
        self.assertEqual(problems, [])


if __name__ == "__main__":
    unittest.main()
