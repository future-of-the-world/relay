"""Review findings F1, F3, F4, F5, F6 of the claudemd change (rules reach eval cases through append_system_prompt)."""
import glob
import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
PLUGIN = os.path.join(ROOT, "evals", "plugin")
sys.path.insert(0, PLUGIN)
sys.path.insert(0, os.path.dirname(__file__))
import system_rules  # noqa: E402
from test_wave_red import CASES, input_match, js_match  # noqa: E402


class NoCalquesJudge(unittest.TestCase):
    def read(self) -> str:
        with open(os.path.join(PLUGIN, "it-terms-ru", "graders", "no-calques.md"), encoding="utf-8") as handle:
            return handle.read()

    def test_a_russian_gloss_beside_the_term_fails(self) -> None:  # F1
        text = self.read()
        self.assertNotIn("Only a Russian phrase used in place of the term counts", text)
        self.assertIn("is a calque: FAIL", text)
        self.assertIn("hook (крючок)", text)

    def test_plain_explanation_passes_and_old_calques_stay_fail(self) -> None:  # F1 pass cases 3, 4
        text = self.read()
        self.assertIn("hook — скрипт, который Claude Code запускает перед командой", text)
        self.assertIn("is not a calque: PASS", text)
        self.assertIn("fast-forward, то есть просто сдвинуться вперёд на эти изменения", text)
        self.assertIn('"слияние"', text)
        self.assertIn('"перемотка"', text)


class GlossaryGivesNoInstruction(unittest.TestCase):
    def test_glossary_only_says_what_the_gate_is(self) -> None:  # F3
        text = system_rules.GLOSSARY.lower()
        for word in ("define", "one line", "first"):
            self.assertNotIn(word, text)
        self.assertIn("full local check before a merge (tests, lint, types)", text)
        self.assertNotIn("define it", system_rules.current("it-terms-ru").replace(system_rules.rule("working-with-me"), "").lower())


class EveryScaffold(unittest.TestCase):
    def test_no_scaffold_writes_an_instruction_file_the_runner_ignores(self) -> None:  # F4
        scaffolds = sorted(glob.glob(os.path.join(PLUGIN, "*", "scaffold.sh")))
        self.assertGreaterEqual(len(scaffolds), 18)
        with open(os.path.join(PLUGIN, "fixture", "CLAUDE.md"), encoding="utf-8") as handle:
            fixture = handle.read()
        for scaffold in scaffolds:
            with tempfile.TemporaryDirectory() as work:
                done = subprocess.run(["bash", scaffold], cwd=work, capture_output=True, text=True)
                self.assertEqual(done.returncode, 0, scaffold + done.stderr)
                mine = os.path.join(work, "CLAUDE.md")
                if os.path.exists(mine):
                    with open(mine, encoding="utf-8") as handle:
                        self.assertEqual(handle.read(), fixture, scaffold)
                self.assertFalse(os.path.exists(os.path.join(work, "CLAUDE.local.md")), scaffold)
                self.assertFalse(os.path.exists(os.path.join(work, ".claude", "CLAUDE.md")), scaffold)

    def test_the_eval_docs_say_so(self) -> None:  # F4
        with open(os.path.join(ROOT, "docs", "benchmark.md"), encoding="utf-8") as handle:
            text = handle.read()
        self.assertIn("CLAUDE_CODE_DISABLE_CLAUDE_MDS=1", text)
        self.assertIn("append_system_prompt", text)


class HyphenEscape(unittest.TestCase):
    def escaped(self, text: str) -> str:
        old = system_rules.CASES.copy()
        system_rules.CASES["x"] = lambda: text
        try:
            return system_rules.line("x")
        finally:
            system_rules.CASES.clear()
            system_rules.CASES.update(old)

    def test_runs_of_five_and_six_hyphens_hold_no_triple(self) -> None:  # F5
        for text in ("-----", "------", "|---|---|", "--------"):
            line = self.escaped(text)
            self.assertNotIn("---", line, text)
            self.assertEqual(json.loads(line.split(system_rules.KEY, 1)[1]), text)


class OpenspecPattern(unittest.TestCase):
    def test_key_order_spacing_and_bare_flag(self) -> None:  # F6
        for case in CASES:
            pattern = input_match(case)
            for raw in ('{"description":"x","command":"openspec list"}', '{"command": "openspec list"}',
                        json.dumps({"command": "openspec --help"}, separators=(",", ":")),
                        json.dumps({"command": "openspec --version"})):
                self.assertTrue(js_match(pattern, raw), (case, raw))
            for command in ("find .claude openspec docs -type f", "ls openspec/changes", "ls openspec"):
                self.assertFalse(js_match(pattern, json.dumps({"description": "x", "command": command})), (case, command))


if __name__ == "__main__":
    unittest.main()
