"""Asked for a review, the front starts a critic; it never reviews code itself.

Cause found 2026-10-30: bench review-offbyone, the Opus front started no critic in 4 of 6 active runs and read
the code itself. The failing runs made 0 Skill calls: the front decides at turn 1 from the always-loaded rules,
and rules/delegation.md said nothing about reviews. The skill texts help only once a skill is loaded.
"""
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(rel: str) -> str:
    with open(os.path.join(ROOT, rel), encoding="utf-8") as handle:
        return re.sub(r"\s+", " ", handle.read())


class ReviewGoesToACritic(unittest.TestCase):
    def test_delegate_row_covers_any_review_request(self) -> None:
        text = read("plugins/delegate/skills/delegate/SKILL.md")
        for key in ("any request to review code", "a function, a file, a diff", "never read it and judge it yourself"):
            self.assertIn(key, text)

    def test_front_skill_forbids_reviewing_itself(self) -> None:
        text = read("plugins/front/skills/front/SKILL.md")
        for key in ("Asked to review", "start a `delegate:critic`", "never read the code and judge it yourself"):
            self.assertIn(key, text)

    def test_rule_sends_a_review_request_to_a_critic(self) -> None:
        # The failing bench runs never loaded a skill: the front decides at turn 1 from the rules alone.
        text = read("rules/delegation.md")
        for key in ("A request to review code", "goes to a `critic` however small",
                    "never reads the code and judges it itself"):
            self.assertIn(key, text)

    def test_bench_rules_file_for_active_profile_carries_the_review_line(self) -> None:
        import relay_bench

        text = re.sub(r"\s+", " ", relay_bench.rules_text(relay_bench.load_profile("active")))
        self.assertIn("goes to a `critic` however small", text)


if __name__ == "__main__":
    unittest.main()
