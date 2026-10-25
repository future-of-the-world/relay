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
from test_queue import committed_text  # noqa: E402


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
    def test_the_moved_done_items_name_a_test_in_a_file_that_exists_and_the_file_is_the_queue_writer_s_text(self) -> None:
        # a test moved by the split is recorded through the queue's own parser and serializer: the file text equals serialize(parse(text))
        problems = []
        moved = ("runner-turns-while-waiting", "a-new-openspec-project-silently-has-no-openspec")   # the two items whose test the split moved
        for slug in moved:
            # the queue is inert (bin/ci's inert probe appends a line to every item): in a probe commit this reads the commit before it
            text = committed_text(ROOT, ".relay/queue/done/" + slug + ".json")
            item = relay_queue.parse(slug, text, "done")
            if item["problems"]:
                problems.append(f"{slug}: {item['problems']}")
                continue
            if relay_queue.serialize(slug, item, "done") != text:
                problems.append(f"{slug}: not the serializer's text")
            test = item.get("test") or ""
            file, _, rest = test.partition("::")
            if not file or file.startswith("evals/") or not rest:
                continue
            full = os.path.join(ROOT, file)
            if not os.path.isfile(full):
                problems.append(f"{slug}: {file} is gone")
            else:
                with open(full, encoding="utf-8") as handle:
                    if not relay_queue.holds_test(test, handle.read()):
                        problems.append(f"{slug}: {test} is not defined")
        self.assertEqual(problems, [])


if __name__ == "__main__":
    unittest.main()
