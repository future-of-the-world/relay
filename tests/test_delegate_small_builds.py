"""The delegation rule and skill say that a small build still goes to a worker.

Cause found 2026-10-24: the rule said the main session "does not write code" but never said that size
is no exception, and the skill's table had a row only for "nobody: answer". In the bench, add-function
under the active setup was built by the session itself (0 agents started, 10 turns), so the session
read "a small function" as below the rule. The bench grader `delegated-to-a-worker` measures the result.
"""
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as handle:
        return re.sub(r"\s+", " ", handle.read())


class SmallBuildsGoToAWorker(unittest.TestCase):
    def test_rule_says_size_is_no_reason(self):
        text = read("rules/delegation.md")
        self.assertIn("Size is no reason to do it yourself", text)
        for key in ("one function", "one test", "one edited line", "one small script", "still go to a `worker`"):
            self.assertIn(key, text)

    def test_rule_keeps_the_fronts_own_duties(self):
        # The front skill gives the front the handover, the merge and the background paid run.
        text = read("rules/delegation.md")
        self.assertNotIn("own work is answering from the conversation", text)
        for key in ("writing briefs", "handover", "merge"):
            self.assertIn(key, text)

    def test_skill_gives_no_false_cost_reason(self):
        # The bench measured a delegated small build as dearer ($0.88 vs $0.31), so no "cheaper" claim.
        text = read("plugins/delegate/skills/delegate/SKILL.md")
        self.assertNotIn("is cheaper than the front's", text)
        self.assertIn("long session", text)

    def test_skill_has_no_small_exception(self):
        text = read("plugins/delegate/skills/delegate/SKILL.md")
        self.assertIn('The table has no row for "small"', text)
        self.assertIn("The front never writes the change itself, whatever its size.", text)


if __name__ == "__main__":
    unittest.main()
