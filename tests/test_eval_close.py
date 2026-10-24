"""relay queue done --test takes an eval case as the proof of a fix: evals/plugin/<case>::<grader> (finding Q1).
Scratch repositories in a temp dir."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_queue as tq  # noqa: E402

rq = tq.rq
CASE = "evals/plugin/some-case"
# the grader file does not name itself: its text has no mention of "my-grader"
GRADER_TEXT = "The skill must not be loaded.\n"


class TestEvalCaseAsTest(tq.Base):
    def test_q1_an_eval_case_and_grader_at_head_is_accepted_and_a_missing_grader_is_refused_with_the_forms(self):
        self.write_commit(self.main, {f"{CASE}/graders/my-grader.md": GRADER_TEXT, f"{CASE}/case.yaml": "name: some-case\n"}, "case")
        # the grader file exists at HEAD: no refusal, though its text never names it
        self.assertIsNone(rq.test_refusal(self.main, "HEAD", f"{CASE}::my-grader"))
        self.assertIsNone(rq.test_refusal(self.main, "HEAD", f"{CASE}/::my-grader"))
        # a grader that is not there: refused, and the line lists both accepted forms
        reason = rq.test_refusal(self.main, "HEAD", f"{CASE}::no-such-grader")
        self.assertIn("graders/no-such-grader.md", reason)
        self.assertIn("<test file>::<test name>", reason)
        self.assertIn("evals/plugin/<case>::<grader>", reason)
        # a case that is not there is refused the same way
        self.assertIn("evals/plugin/<case>::<grader>", rq.test_refusal(self.main, "HEAD", "evals/plugin/gone::my-grader"))
        # the older forms keep their rule: a file form still needs its text to hold the name
        self.assertIsNone(rq.test_refusal(self.main, "HEAD", f"{CASE}/case.yaml::some-case"))
        self.assertIn("does not hold a test named", rq.test_refusal(self.main, "HEAD", f"{CASE}/case.yaml::my-grader"))

    def test_f1_every_refusal_names_the_forms(self):
        self.write_commit(self.main, {f"{CASE}/graders/g.md": "no name\n"}, "case")
        for t in (f"{CASE}/graders/g.md::g", "tests/missing.py::test_x"):
            reason = rq.test_refusal(self.main, "HEAD", t)
            self.assertIn("<test file>::<test name>", reason)
            self.assertIn("evals/plugin/<case>::<grader>", reason)
        self.assertIn("does not hold a test named g", rq.test_refusal(self.main, "HEAD", f"{CASE}/graders/g.md::g"))
        self.assertIn("is not in the last commit", rq.test_refusal(self.main, "HEAD", "tests/missing.py::test_x"))
        self.assertIsNone(rq.test_refusal(self.main, "HEAD", f"{CASE}::g"))

    def test_f3_a_judge_measure_case_is_accepted(self):
        self.write_commit(self.main, {"evals/judge-measure/c/graders/g.md": "x\n", "lib/x.py": "def other(): pass\n"}, "case")
        self.assertIsNone(rq.test_refusal(self.main, "HEAD", "evals/judge-measure/c::g"))
        self.assertIn("does not hold a test named", rq.test_refusal(self.main, "HEAD", "lib/x.py::g"))
        self.assertIn("graders/nope.md", rq.test_refusal(self.main, "HEAD", "evals/judge-measure/c::nope"))


if __name__ == "__main__":
    unittest.main()
