"""The merge guard and `relay queue done` judge a recorded test name the same way (one function, relay_queue.holds_test)."""
import importlib.util
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "lib"))
sys.path.insert(0, HERE)

import relay_queue as rq  # noqa: E402
import test_queue as tq  # noqa: E402

SOURCE = "class Suite:\n    def test_hangs_within_bound(self):\n        pass\n\n\ndef test_plain():\n    pass\n"
# (recorded test, accepted?): the file is tests/t.py; a name counts when `def <name>` is in it as a whole word
CASES = [
    ("tests/t.py::Suite::test_hangs_within_bound", True),    # file::Class::function
    ("tests/t.py::test_hangs_within_bound", True),           # file::function
    ("tests/t.py::test_plain", True),
    ("tests/t.py::test_hangs_within_bound", True),           # file::method of a class (class part optional)
    ("tests/t.py::Suite::test_missing", False),              # a name the file does not define
    ("tests/t.py::NoSuchClass::test_hangs_within_bound", False),  # a class the file does not define: pytest cannot collect it
    ("tests/t.py::test_hangs", False),                       # only a part of a name
    ("tests/gone.py::test_plain", False),                    # a file that does not exist
    ("tests/t.py::", False),
    ("tests/t.py", False),
]


def load_hook():
    spec = importlib.util.spec_from_file_location("merge_hook_for_test_name", os.path.join(ROOT, "plugins", "core", "hooks", "merge.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestHoldsTest(unittest.TestCase):
    def test_the_shared_function_judges_the_whole_recorded_name(self):
        for test, accepted in CASES:
            source = SOURCE if test.startswith("tests/t.py") else None     # a missing file has no source
            self.assertEqual(rq.holds_test(test, source), accepted, test)


class TestDoneJudges(tq.Base):
    def setUp(self):
        super().setUp()
        self.write_commit(self.main, {".relay/queue/job.json": tq.fix_item("Job", ip=60, failing="line 1\nline 2")}, "seed")
        self.wa = self.worktree("a")

    def test_done_accepts_and_refuses_the_same_names(self):
        findings = os.path.join(self.tmp, "f.json")
        rq.take(self.wa, "job", findings, **tq.QUIET)
        self.write_commit(self.wa, {"tests/t.py": SOURCE}, "test")
        check = os.path.join(self.tmp, "c.json")
        with open(check, "w") as handle:
            json.dump({"schema": 1, "type": "check", "head": tq.git(self.wa, "rev-parse", "HEAD"), "reviewed": "a" * 40, "gate": None,
                       "worktree": "/w", "review": [findings], "findings": [{"id": "Q1", "verdict": "MET", "reason": ["tests/t.py:1"]}],
                       "new": [], "open": 0, "queued": 0}, handle)
        for test, accepted in CASES:
            if "::" not in test or test.endswith("::"):
                continue                                                    # refused earlier, by the shape of --test
            if accepted:
                continue
            with self.assertRaises(rq.Refused, msg=test):
                rq.done(self.wa, "job", test, check)
        for test, accepted in CASES:
            if accepted:
                self.assertIn("closed job", rq.done(self.wa, "job", test, check), test)
                tq.git(self.wa, "reset", "-q", "--hard", "HEAD~1")        # back to the taken item, to try the next name


class TestMergeJudges(tq.Base):
    def merge_accepts(self, n, test):
        """Whether the merge guard lets through branch wt/m<n>, which closes a fix item with `test` and holds tests/t.py with SOURCE."""
        hook = load_hook()
        wt = self.worktree("m%d" % n)
        done = tq.new_shape(kind="fix", title="Job", failing_case=["it fails"], taken_at="2026-10-23T21:47:35Z", taken_by="wt/m%d" % n,
                            closed_at="2026-10-24T01:00:00Z", test=test)
        self.write_commit(wt, {"tests/t.py": SOURCE, ".relay/queue/done/job.json": done}, "close job")
        try:
            hook.step_queue(self.main, "master", "wt/m%d" % n)
        except hook.Refused as exc:
            self.assertIn("closed without a test", str(exc))
            return False
        return True

    def test_merge_accepts_and_refuses_the_same_names(self):
        for n, (test, accepted) in enumerate(CASES):
            self.assertEqual(self.merge_accepts(n, test), accepted, test)
