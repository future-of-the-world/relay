"""Eval cases get their rules through `append_system_prompt`: the runner turns CLAUDE.md loading off (evals/plugin/system_rules.py)."""
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLUGIN = os.path.join(ROOT, "evals", "plugin")
sys.path.insert(0, PLUGIN)
import system_rules  # noqa: E402


class SystemRules(unittest.TestCase):
    def test_every_case_carries_the_text_built_from_the_rule_files(self):
        # the expected text is built from rules/*.md now, so a hand edit of a case's copy, or a rule changed without
        # rewriting the cases (python3 evals/plugin/system_rules.py), differs
        for case in system_rules.CASES:
            self.assertEqual(system_rules.current(case), system_rules.CASES[case](), case)

    def test_the_line_has_no_run_of_three_hyphens(self):
        # the runner closes the frontmatter at the first `---`, even inside a quoted string: the spec cases' table separators
        for case in system_rules.CASES:
            self.assertNotIn("---", system_rules.line(case).split(system_rules.KEY, 1)[1], case)

    def test_the_text_holds_the_rule_the_case_proves(self):
        # what each case needs in front of the session: the IT-terms sentence, the delegation rule, the spec steps table
        self.assertIn("Standard IT terms stay in their English form", system_rules.CASES["it-terms-ru"]())
        self.assertIn("My native language: Spanish.", system_rules.CASES["it-terms-es"]())
        self.assertIn("Project glossary:", system_rules.CASES["it-terms-ru"]())
        self.assertIn("Spec steps in the change cycle", system_rules.CASES["spec-step-on"]())
        self.assertIn("typed agents only", system_rules.CASES["design-track"]())

    def test_the_it_terms_prompts_do_not_tell_the_session_to_read_claude_md(self):
        for case in ("it-terms-ru", "it-terms-es"):
            with open(os.path.join(PLUGIN, case, "prompt.md"), encoding="utf-8") as handle:
                self.assertNotIn("CLAUDE.md", handle.read(), case)

    def test_scaffolds_write_no_instruction_file_the_runner_would_ignore(self):
        for case in system_rules.CASES:
            with tempfile.TemporaryDirectory() as work:
                done = subprocess.run(["bash", os.path.join(PLUGIN, case, "scaffold.sh")], cwd=work,
                                      capture_output=True, text=True)
                self.assertEqual(done.returncode, 0, case + done.stderr)
                with open(os.path.join(work, "CLAUDE.md"), encoding="utf-8") as mine, \
                        open(os.path.join(PLUGIN, "fixture", "CLAUDE.md"), encoding="utf-8") as fixture:
                    self.assertEqual(mine.read(), fixture.read(), case)  # the fixture's own file, no rule text added
                self.assertFalse(os.path.exists(os.path.join(work, "CLAUDE.local.md")), case)


if __name__ == "__main__":
    unittest.main()
