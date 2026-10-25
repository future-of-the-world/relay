"""The front measures before it recommends, and a question about a new mechanism goes to the design track (queue item
the-front-recommends-from-unmeasured-claims-unre, finding Q1). Free: reads the rule and skill texts and the eval case."""
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def text(*parts: str) -> str:
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as handle:
        return " ".join(handle.read().split())  # one line: a phrase wrapped across lines still matches


class FrontMeasures(unittest.TestCase):
    def test_q1_a_recommendation_names_what_it_rests_on_and_a_view_moves_on_evidence(self):
        """Pass case 3: a recommendation says "measured: <number>" or "not measured"; a cheap measurement runs before the reply."""
        for where in (("rules", "verify.md"), ("plugins", "front", "skills", "front", "SKILL.md")):
            body = text(*where)
            for phrase in ("not measured", "measured:", "before the reply", "on new evidence, not on the owner's push"):
                self.assertIn(phrase, body, where)
        # "Verify against the real system" covers replies to the owner, not only docs and code.
        self.assertIn("before a recommendation to the owner", text("rules", "verify.md"))

    def test_q1_a_question_about_a_new_mechanism_goes_to_the_design_track(self):
        """Pass case 1: thinker with the owner's words verbatim and a measurement, two approaches plus do nothing, a critic, the revision."""
        for where in (("rules", "delegation.md"), ("rules", "working-with-me.md"), ("plugins", "front", "skills", "front", "SKILL.md")):
            body = text(*where).replace("NEW mechanism", "new mechanism")
            for phrase in ("new mechanism", "design track", "verbatim", "plus \"do nothing\""):
                self.assertIn(phrase, body, where)
        routing = text("plugins", "delegate", "skills", "delegate", "SKILL.md")
        self.assertIn("the owner asks about a NEW mechanism", routing)
        self.assertIn("`delegate:thinker`, then `delegate:critic`", routing)

    def test_q1_explaining_what_exists_stays_with_the_front(self):
        """Pass case 2: no design track for "what does relay queue take do?"."""
        self.assertIn("Explaining what already exists stays with the front", text("rules", "delegation.md"))
        self.assertIn("explaining a mechanism that already exists", text("plugins", "delegate", "skills", "delegate", "SKILL.md"))

    def test_q1_the_eval_cases_exist_and_the_short_rules_gate_runs_this_file(self):
        for case, grader in (("design-track", "thinker-started"), ("explain-existing", "no-thinker")):
            base = os.path.join(ROOT, "evals", "plugin", case)
            for name in ("case.yaml", "prompt.md", "scaffold.sh", os.path.join("graders", grader + ".md")):
                self.assertTrue(os.path.isfile(os.path.join(base, name)), (case, name))
        import sys
        sys.path.insert(0, os.path.join(ROOT, "lib"))
        import relay_textonly
        self.assertIn("tests.test_front_measures", relay_textonly.RULE_TESTS)


if __name__ == "__main__":
    unittest.main()
