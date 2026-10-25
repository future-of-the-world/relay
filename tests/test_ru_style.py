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

    def test_f1_rule_examples_keep_the_english_term(self):
        rule = " ".join(read("rules", "working-with-me.md").split())
        self.assertNotIn("несколько изменений", rule)
        self.assertIn("в нескольких commit", rule)
        self.assertIn("после merge", rule)
        self.assertIn("not \"commit'ов\"", rule)

    def test_f3_the_apostrophe_class_covers_u2018_and_backtick(self):
        grader = re.compile(pattern())
        self.assertIsNone(grader.search("Это несколько commit\u2018ов."))
        self.assertIsNone(grader.search("Это несколько commit`ов."))
        self.assertIsNone(grader.search("Это несколько commit'ов."))
        self.assertIsNotNone(grader.search("Это merge, а don't значит не надо."))
        self.assertIsNotNone(grader.search(read("evals", "plugin", "it-terms-ru", "recorded", "good", "merge-reply.txt")))

    def test_f4_no_calques_example_is_masculine(self):
        text = read("evals", "plugin", "it-terms-ru", "graders", "no-calques.md")
        self.assertNotIn("основная branch", text)
        self.assertIn("основной branch может сделать fast-forward", text)

    def test_f5_every_copy_of_the_opener_rule_has_the_exception(self):
        for parts in (("rules", "front.md"), ("plugins", "front", "skills", "front", "SKILL.md")):
            text = " ".join(read(*parts).split())
            self.assertIn("when no project is named", text, parts)
            self.assertIn("was not named", text, parts)


if __name__ == "__main__":
    unittest.main()
