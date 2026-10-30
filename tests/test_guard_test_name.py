"""The merge guard and `relay queue done` judge a recorded test name the same way (one function, relay_queue.holds_test)."""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "lib"))
sys.path.insert(0, HERE)

import relay_queue as rq  # noqa: E402
import test_check_record as cr  # noqa: E402
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


class TestHoldsTest(unittest.TestCase):
    def test_the_shared_function_judges_the_whole_recorded_name(self):
        for test, accepted in CASES:
            source = SOURCE if test.startswith("tests/t.py") else None     # a missing file has no source
            self.assertEqual(rq.holds_test(test, source), accepted, test)


class TestDoneJudges(cr.Flow):
    def test_done_accepts_and_refuses_the_same_names(self):
        self.write_commit(self.wa, {"tests/t.py": SOURCE}, "test")
        review = self.review("r.json", self.took, [cr.review_finding(1)])
        self.checked([review], cr.met("Q1", "F1"))
        for test, accepted in CASES:
            if "::" not in test or test.endswith("::"):
                continue                                                    # refused earlier, by the shape of --test
            if accepted:
                continue
            with self.assertRaises(rq.Refused, msg=test):
                rq.done(self.wa, "job", test)
        for test, accepted in CASES:
            if accepted:
                self.assertIn("closed job", rq.done(self.wa, "job", test), test)
                tq.git(self.wa, "reset", "-q", "--hard", "HEAD~1")        # back to the checked state, to try the next name


class TestMergeJudges(cr.Flow):
    def checked_state(self):
        """Branch wt/a (it took the fix item `job`) holding tests/t.py with SOURCE and checked with Q1 MET: built once, by one take,
        one test commit and one check record; returns the item's text as `take` left it."""
        self.write_commit(self.wa, {"tests/t.py": SOURCE}, "test")
        review = self.review("r.json", self.head(), [cr.review_finding(1)])
        self.checked([review], cr.met("Q1", "F1"))
        return open(os.path.join(self.wa, ".relay/queue/job.json"), encoding="utf-8").read()

    def merge_accepts(self, taken, test):
        """Whether the merge guard lets through branch wt/a closing the item with `test`. The item is closed as `relay queue done` would
        (the merge hook refuses any other change of its text); the branch is put back to its checked state afterwards."""
        checked = self.head()
        done = tq.raw_item(taken, closed_at=rq.utcnow(), test=test)
        self.write_commit(self.wa, {".relay/queue/job.json": done}, "close job")
        hook = cr.merge_hook
        try:
            hook.step_queue(self.main, "master", "wt/a")
        except hook.Refused as exc:
            self.assertIn("closed without a test", str(exc))
            return False
        finally:
            tq.git(self.wa, "reset", "-q", "--hard", checked)
        return True

    def test_merge_accepts_and_refuses_the_same_names(self):
        taken = self.checked_state()
        for test, accepted in CASES:
            self.assertEqual(self.merge_accepts(taken, test), accepted, test)
