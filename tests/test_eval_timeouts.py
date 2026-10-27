"""The eval tool's time-limit error is recognised whatever its capitalisation, and the record's docstring states the rule."""
import os, sys, unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_eval_record import load_record
from test_eval_majority import batch, case, P


class TimeoutWording(unittest.TestCase):
    def setUp(self):
        self.rec = load_record()

    def test_a_capitalised_timeout_message_is_a_failed_run_not_an_unjudged_one(self):
        # "Timed out after 600s" in PASS, PASS, <that> = 2 of 3 passed -> green, named as a timeout
        c = case([P, P, P]); c["arms"]["with"][2] = {"error": "Timed out after 600s", "graders": []}
        b = batch(c)
        self.assertTrue(self.rec.timed_out(c["arms"]["with"][2]))
        self.assertTrue(self.rec.is_green(b))
        text = "\n".join(self.rec.report(b, ""))
        self.assertIn("2 of 3 runs passed, 1 timed out", text)
        self.assertNotIn("not judged", text)

    def test_max_turns_is_still_not_a_timeout(self):
        self.assertFalse(self.rec.timed_out({"error": "exit 1: Reached maximum number of turns (3)"}))

    def test_the_docstring_states_the_timeout_rule(self):
        self.assertIn("time limit is a failed run of the majority", self.rec.__doc__)


if __name__ == "__main__":
    unittest.main()
