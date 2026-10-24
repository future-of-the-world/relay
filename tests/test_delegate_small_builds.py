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
        self.assertIn("one function, one test, one edited line, one small script still go to a `worker`", text)

    def test_skill_has_no_small_exception(self):
        text = read("plugins/delegate/skills/delegate/SKILL.md")
        self.assertIn('The table has no row for "small"', text)
        self.assertIn("The front never writes the change itself, whatever its size.", text)


if __name__ == "__main__":
    unittest.main()
