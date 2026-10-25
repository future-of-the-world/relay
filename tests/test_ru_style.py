"""Q1: a Russian reply takes one gender for an English IT noun, no apostrophe before a Russian ending, no empty opener."""
import json
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CASE = os.path.join(ROOT, "evals", "plugin", "it-terms-ru")


def read(*parts: str) -> str:
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as handle:
        return handle.read()


def pattern() -> str:
    # the grader's front matter line is `pattern: "<json string>"`
    line = [l for l in read("evals", "plugin", "it-terms-ru", "graders", "no-apostrophe.md").split("\n")
            if l.startswith("pattern:")][0]
    return json.loads(line.split(":", 1)[1].strip())


class RuStyle(unittest.TestCase):
    def test_q1_the_apostrophe_grader_fails_commitov_and_passes_a_reply_without_it(self):
        # the live reply of 25 Oct had "commit'ов"; a reply with no apostrophe form must pass
        grader = re.compile(pattern())
        self.assertIsNone(grader.search("Изменения лежат в отдельном branch, это несколько commit'ов."))
        self.assertIsNone(grader.search("Это несколько commit’ов."))
        self.assertIsNotNone(grader.search("Изменения лежат в отдельном branch, это несколько изменений."))
        # an apostrophe in English text is not a Russian ending
        self.assertIsNotNone(grader.search("Это merge, а don't значит не надо."))

    def test_q1_the_rule_holds_the_three_lines(self):
        rule = " ".join(read("rules", "working-with-me.md").split())
        self.assertIn("an English IT noun is masculine", rule)
        self.assertIn("never \"в отдельной branch\"", rule)
        self.assertIn("takes no apostrophe before a Russian ending", rule)
        self.assertIn("never open with a remark that the project was not named", rule)

    def test_q1_the_case_judges_gender_and_opener(self):
        judge = read("evals", "plugin", "it-terms-ru", "graders", "gender-and-opener.md")
        self.assertIn("type: llm", judge)
        self.assertIn("masculine", judge)
        self.assertIn("not named", judge)


if __name__ == "__main__":
    unittest.main()
