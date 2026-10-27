"""Eval case files must load, and the relay stand-in used by queue cases must behave like `relay queue show|note`."""
import glob
import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLUGIN = os.path.join(ROOT, "evals", "plugin")
STUB = os.path.join(PLUGIN, "relay-stub.py")


def description_line(path: str) -> str:
    for line in open(path, encoding="utf-8").read().split("\n"):
        if line.startswith("description:"):
            return line.partition(":")[2].strip()
    raise AssertionError("%s has no description" % path)


class CaseFiles(unittest.TestCase):
    def test_every_description_is_one_valid_double_quoted_string(self):
        # a quote inside a description broke recall-decision's case.yaml ("YAML parse failed"): `claude plugin eval` then
        # skipped the case and the gate stayed green without it. A JSON string is valid YAML, so json.loads is the check.
        for path in sorted(glob.glob(os.path.join(PLUGIN, "*", "case.yaml"))):
            text = description_line(path)
            if text.startswith('"'):
                json.loads(text)


class Stub(unittest.TestCase):
    def run_stub(self, work: str, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, "-I", STUB, *args], cwd=work, capture_output=True, text=True)

    def project(self, tmp: str) -> str:
        os.makedirs(os.path.join(tmp, ".relay", "queue"))
        with open(os.path.join(tmp, ".relay", "queue", "an-item.json"), "w", encoding="utf-8") as fh:
            fh.write('{"title": "An item"}')
        return tmp

    def test_note_prints_the_text_back_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = self.project(tmp)
            toml = os.path.join(tmp, "n.toml")
            with open(toml, "w", encoding="utf-8") as fh:
                fh.write("said = '''минуты ожидания проверки'''\n")
            done = self.run_stub(work, "queue", "note", "an-item", "--input", toml)
            self.assertEqual(done.returncode, 0, done.stderr)
            # the judge reads the reply, so the stored words must come back verbatim
            self.assertEqual(done.stdout, 'noted an-item: said: "минуты ожидания проверки"\n')
            self.assertEqual(open(os.path.join(work, ".relay", "queue", "an-item.json"), encoding="utf-8").read(), '{"title": "An item"}')

    def test_note_refuses_two_kinds_and_an_unknown_item(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = self.project(tmp)
            toml = os.path.join(tmp, "n.toml")
            with open(toml, "w", encoding="utf-8") as fh:
                fh.write("said = 'a'\nfact = 'b'\n")
            self.assertEqual(self.run_stub(work, "queue", "note", "an-item", "--input", toml).returncode, 1)
            self.assertEqual(self.run_stub(work, "queue", "note", "nope", "--input", toml).returncode, 1)

    def test_show_prints_the_item_found_by_words(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = self.project(tmp)
            done = self.run_stub(work, "queue", "show", "AN-item")
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertEqual(done.stdout, 'an-item\n{"title": "An item"}\n')


if __name__ == "__main__":
    unittest.main()
