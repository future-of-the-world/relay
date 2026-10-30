"""Asked for a review, the front starts a critic; it never reviews code itself.

Cause found 2026-10-30: bench review-offbyone, the Opus front started no critic in 5 of 12 runs and read the
code itself. The delegate skill's row said only "a review before merge, a design critique", which a request
"review this function" did not match, and the front skill never named reviews as the front's no-go.
"""
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(rel: str) -> str:
    with open(os.path.join(ROOT, rel), encoding="utf-8") as handle:
        return re.sub(r"\s+", " ", handle.read())


class ReviewGoesToACritic(unittest.TestCase):
    def test_delegate_row_covers_any_review_request(self):
        text = read("plugins/delegate/skills/delegate/SKILL.md")
        for key in ("any request to review code", "a function, a file, a diff", "never read it and judge it yourself"):
            self.assertIn(key, text)

    def test_front_skill_forbids_reviewing_itself(self):
        text = read("plugins/front/skills/front/SKILL.md")
        for key in ("Asked to review", "start a `delegate:critic`", "never read the code and judge it yourself"):
            self.assertIn(key, text)


if __name__ == "__main__":
    unittest.main()
