"""Q1 of fix-reports-are-moved-by-hand-author-gives-messa: the spec-review skill hands the
author a report path and the checker reads that same path; `kit packet --check` reports a
tasks.md whose waves are missing a Wave line."""
import os
import subprocess
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KIT = os.path.join(ROOT, "plugins", "core", "bin", "kit")
SKILL = os.path.join(ROOT, "plugins", "sdd", "skills", "spec-review", "SKILL.md")
AUTHOR = os.path.join(ROOT, "plugins", "sdd", "agents", "author.md")

TASK = ("- [ ] %s Do it. Reads: file docs/guide.md. Tests: none (docs). Files: docs/guide.md. "
        "Check: `true`\n")


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


class SpecReviewReportPath(unittest.TestCase):
    def test_author_gets_the_path_the_checker_reads(self):
        # The skill's author prompt line names `Report: <path>`; the checker line's `Fixes:` is the same path.
        text = read(SKILL)
        self.assertIn("Report: `<scratchpad>/review/spec-fix.md`", text)
        self.assertIn("Fixes: `<scratchpad>/review/spec-fix.md`", text)
        self.assertNotIn("<author report>", text)

    def test_author_writes_a_fix_report_to_the_given_path(self):
        self.assertIn("a fix job too", read(AUTHOR))


class WaveLineCheck(unittest.TestCase):
    def check(self, tasks):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        d = tmp.name
        os.makedirs(os.path.join(d, ".claude"))
        os.makedirs(os.path.join(d, "docs"))
        os.makedirs(os.path.join(d, "openspec", "changes", "c"))
        open(os.path.join(d, ".claude", "kit.toml"), "w").close()
        open(os.path.join(d, "docs", "guide.md"), "w").write("# Guide\n")
        open(os.path.join(d, "openspec", "changes", "c", "design.md"), "w").write("# D\n\n## Interfaces\n\nNone.\n")
        open(os.path.join(d, "openspec", "changes", "c", "tasks.md"), "w").write(tasks)
        r = subprocess.run([KIT, "packet", "--check", "c"], cwd=d, capture_output=True, text=True)
        return r.returncode, r.stdout + r.stderr

    def test_group_without_wave_line_is_reported(self):
        # Group 2 has no Wave line while group 1 and 3 do: the failing run (no Wave 1 line).
        tasks = ("## 1. A\n\nWave 0 · depends on: none\n\n" + TASK % "1.1"
                 + "\n## 2. B\n\n" + TASK % "2.1"
                 + "\n## 3. C\n\nWave 2 · depends on: 1\n\n" + TASK % "3.1")
        code, out = self.check(tasks)
        self.assertEqual(code, 1, out)
        self.assertIn("group 2: no Wave line", out)
        self.assertNotIn("group 1: no Wave line", out)
        self.assertNotIn("group 3: no Wave line", out)

    def test_no_wave_1_is_reported(self):
        tasks = ("## 1. A\n\nWave 0 · depends on: none\n\n" + TASK % "1.1"
                 + "\n## 2. B\n\nWave 2 · depends on: 1\n\n" + TASK % "2.1")
        code, out = self.check(tasks)
        self.assertEqual(code, 1, out)
        self.assertIn("no Wave 1 line", out)

    def test_complete_waves_and_sequential_plans_pass(self):
        waves = ("## 1. A\n\nWave 0 · depends on: none\n\n" + TASK % "1.1"
                 + "\n## 2. B\n\nWave 1 · depends on: 1\n\n" + TASK % "2.1")
        self.assertEqual(self.check(waves)[0], 0)
        self.assertEqual(self.check("## 1. A\n\nWave 1 · depends on: none\n\n" + TASK % "1.1")[0], 0)

    def test_no_wave_line_anywhere_is_reported(self):
        # The trial's shape: one group, one open task, no Wave line (rule 12 wants one per group).
        code, out = self.check("## 1. A\n\n" + TASK % "1.1")
        self.assertEqual(code, 1, out)
        self.assertIn("group 1: no Wave line", out)

    def test_done_groups_and_empty_plans_need_no_wave_line(self):
        done = TASK.replace("[ ]", "[x]")
        tasks = ("## 1. A\n\n" + done % "1.1" + "\n## 2. B\n\n" + done % "2.1"
                 + "\n## 3. C\n\nWave 1 · depends on: none\n\n" + TASK % "3.1")
        self.assertEqual(self.check(tasks)[0], 0)
        self.assertEqual(self.check("## 1. A\n\n" + done % "1.1")[0], 0)

    def test_single_wave_0_plan_does_not_ask_for_wave_1(self):
        code, out = self.check("## 1. A\n\nWave 0 · depends on: none\n\n" + TASK % "1.1")
        self.assertEqual(code, 0, out)
        self.assertNotIn("no Wave 1", out)

    def test_docs_name_the_wave_line_check(self):
        self.assertIn("Wave line", read(os.path.join(ROOT, "plugins", "core", "lib", "kit_spec_check.py")))
        self.assertIn("Wave lines", read(os.path.join(ROOT, "plugins", "sdd", "skills", "parallel-apply", "SKILL.md")))
        text = read(AUTHOR)
        self.assertIn("for a fix, `Report: <path>`", text)
        self.assertIn("or the prompt's `Report:` names", text)


if __name__ == "__main__":
    unittest.main()
