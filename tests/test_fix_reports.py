"""Q1 of fix-reports-are-moved-by-hand-author-gives-messa: the spec-review skill hands the
author a report path and the checker reads that same path; `kit packet --check` asks for no Wave line."""
import os
import subprocess
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KIT = os.path.join(ROOT, "plugins", "relay", "bin", "kit")
SKILL = os.path.join(ROOT, "plugins", "openspec", "skills", "spec-review", "SKILL.md")
AUTHOR = os.path.join(ROOT, "plugins", "openspec", "agents", "author.md")

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

    def test_plans_without_wave_lines_pass(self):
        # Groups are built one after another in tasks.md order (the change cycle's step 2): no Wave line is asked for.
        code, out = self.check("## 1. A\n\n" + TASK % "1.1" + "\n## 2. B\n\n" + TASK % "2.1")
        self.assertEqual(code, 0, out)
        self.assertNotIn("Wave", out)

    def test_old_wave_lines_are_plain_text(self):
        # An old tasks.md that still carries Wave lines (even a gap in them) passes.
        tasks = ("## 1. A\n\nWave 0 · depends on: none\n\n" + TASK % "1.1"
                 + "\n## 2. B\n\nWave 2 · depends on: 1\n\n" + TASK % "2.1")
        self.assertEqual(self.check(tasks)[0], 0)

    def test_author_names_the_fix_report_path(self):
        text = read(AUTHOR)
        self.assertIn("for a fix, `Report: <path>`", text)
        self.assertIn("or the prompt's `Report:` names", text)


if __name__ == "__main__":
    unittest.main()
