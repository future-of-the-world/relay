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


if __name__ == "__main__":
    unittest.main()
