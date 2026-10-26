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

    def test_the_rule_keeps_agreement_with_the_term_after_a_gloss(self):
        # 26 Oct run 3: "Gate, то есть полная ... проверка, тоже зелёная" agreed with the gloss; a pronoun after the gloss is fine
        rule = " ".join(read("rules", "working-with-me.md").split())
        self.assertIn('never "gate тоже зелёная"', rule)
        self.assertIn("a pronoun that points at the Russian gloss", rule)
        judge = read("evals", "plugin", "it-terms-ru", "graders", "gender-and-opener.md")
        self.assertIn("gate, ... any English IT noun", judge)
        self.assertIn("is not a breach", judge)

    def test_q1_the_case_judges_gender_and_opener(self):
        judge = read("evals", "plugin", "it-terms-ru", "graders", "gender-and-opener.md")
        self.assertIn("type: llm", judge)
        self.assertIn("masculine", judge)
        self.assertIn("not named", judge)

    def test_f2_the_judge_is_measured_on_the_live_bad_replies_and_the_good_one(self):
        # F2: the grader text alone proves nothing; the judge is measured (evals/judge-measure/measure-ru-style,
        # paid, re-run by hand with its README) on the live bad replies of 25 Oct and the owner-approved good one.
        items = [l.split() for l in read("evals", "judge-measure", "measure-ru-style", "items.txt").split("\n")
                 if l.strip() and not l.startswith("#")]
        bad = sorted(os.listdir(os.path.join(CASE, "recorded", "bad")))
        bad = ["plugin/it-terms-ru/recorded/bad/" + n for n in bad if n.startswith("gender-and-opener__")]
        self.assertEqual(7, len(bad))
        self.assertEqual(sorted(("no", b) for b in bad), sorted(tuple(i) for i in items if i[0] == "no"))
        self.assertEqual([["yes", "plugin/it-terms-ru/recorded/good/gloss-pronoun.txt"], ["yes", "plugin/it-terms-ru/recorded/good/merge-reply.txt"]],
                         sorted(i for i in items if i[0] == "yes"))
        # each recorded bad reply really shows a fault the judge is asked to refuse; the good one shows neither
        feminine = re.compile(r"(?:отдельной|эта|Основная|основная) branch|Gate, то есть[^.]*тоже зелёная")
        opener = re.compile(r"\A[^.]*(?:не прозвучал|не назван|не назвали|назначение проекта я не знаю)")
        for rel in bad:
            text = read("evals", rel)
            self.assertTrue(feminine.search(text) or opener.search(text), rel)
        self.assertIsNotNone(opener.search(read("evals", "plugin/it-terms-ru/recorded/bad/gender-and-opener__opener-only-masculine.txt")))
        self.assertIsNotNone(feminine.search(read("evals", "plugin/it-terms-ru/recorded/bad/gender-and-opener__feminine-only.txt")))
        for rel in (i[1] for i in items if i[0] == "yes"):
            good = read("evals", rel)
            self.assertIsNone(feminine.search(good), rel)
            self.assertIsNone(opener.search(good), rel)

    def test_f1_the_pronoun_example_uses_a_descriptive_gloss_not_a_one_word_one(self):
        rule = " ".join(read("rules", "working-with-me.md").split())
        self.assertNotIn("hook, то есть проверка,", rule)
        self.assertIn("hook, то есть автоматическая проверка перед merge, и она прошла", rule)

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
