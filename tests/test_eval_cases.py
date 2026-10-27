"""Eval case files must load, and the relay stand-in used by queue cases must behave like `relay queue show|note`."""
import glob
import json
import os
import subprocess
import sys
import tempfile
import unittest
import datetime as dt

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
import relay_queue as rq  # noqa: E402
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
        env = {"PATH": os.environ.get("PATH", ""), "TZ": "UTC"}  # the real code is called with UTC below
        return subprocess.run([sys.executable, "-I", STUB, *args], cwd=work, capture_output=True, text=True, env=env)

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
            self.assertEqual(done.stdout, "an-item: An item\n")

    def test_show_finds_a_word_inside_the_item_and_lists_several_matches(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = self.project(tmp)
            with open(os.path.join(work, ".relay", "queue", "other-thing.json"), "w", encoding="utf-8") as fh:
                fh.write('{"title": "Other", "notes": [{"at": "2026-10-27T03:00:00Z", "said": ["Is the done/ folder needed?"]}]}')
            # "done" is only in the notes of other-thing, not in any file name: found by content, one match is shown
            one = self.run_stub(work, "queue", "show", "done")
            self.assertEqual(one.returncode, 0, one.stderr)
            self.assertTrue(one.stdout.startswith("other-thing: Other\n"), one.stdout)
            # "item" is in an-item (name) only; "t" is in both names: two matches are listed by name, sorted
            many = self.run_stub(work, "queue", "show", "t")
            self.assertEqual(many.stdout, "an-item\nother-thing\n")
            self.assertEqual(self.run_stub(work, "queue", "list").stdout, "an-item\nother-thing\n")

    def test_note_takes_the_exact_slug_only(self):
        # F4: the real command refuses 'nothing noted: no queue item' for anything but the slug; a word found inside the item is not one
        with tempfile.TemporaryDirectory() as tmp:
            work = self.project(tmp)
            toml = os.path.join(tmp, "n.toml")
            with open(toml, "w", encoding="utf-8") as fh:
                fh.write("said = 'a'\n")
            self.assertEqual(self.run_stub(work, "queue", "note", "an-item", "--input", toml).returncode, 0)
            for word in ("item", "An", "an"):  # in the name or the title, but not the slug
                self.assertEqual(self.run_stub(work, "queue", "note", word, "--input", toml).returncode, 1, word)
            # show still finds by words
            self.assertEqual(self.run_stub(work, "queue", "show", "item").returncode, 0)


class StubShowMatchesTheRealNotes(unittest.TestCase):
    """F2: the stub's show prints the Notes lines the real `relay queue show` prints (notes_text), not the raw JSON."""

    def stub_show(self, slug_dir: str, slug: str) -> str:
        env = {"PATH": os.environ.get("PATH", ""), "TZ": "UTC"}
        return subprocess.run([sys.executable, "-I", STUB, "queue", "show", slug], cwd=slug_dir, capture_output=True, text=True, env=env).stdout

    def check_item(self, text: str) -> str:
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, ".relay", "queue"))
            with open(os.path.join(tmp, ".relay", "queue", "x.json"), "w", encoding="utf-8") as fh:
                fh.write(text)
            out = self.stub_show(tmp, "x")
        item = rq.parse("x", text)
        self.assertEqual(item["problems"], [])
        want = rq.notes_text(item, dt.timezone.utc)
        got = out.split("\n")
        if want:
            self.assertIn("\n".join(want), out)
            self.assertEqual(got[got.index("Notes:"):][: len(want)], want)
        else:
            self.assertNotIn("Notes:", out)  # an item with no notes prints no Notes section
        return out

    def test_recall_decision_fixture_items_print_the_real_notes(self):
        for path in sorted(glob.glob(os.path.join(PLUGIN, "recall-decision", "queue", "*.json"))):
            with open(path, encoding="utf-8") as fh:
                out = self.check_item(fh.read())
            self.assertNotIn('"answer"', out)  # not the raw JSON
            self.assertIn("the owner answered question 1 (whole reply):", out)

    def test_a_said_note_a_fact_and_an_open_question(self):
        base = json.load(open(os.path.join(PLUGIN, "recall-decision", "queue", "the-owner-says-what-the-queue-keeps.json"), encoding="utf-8"))
        base["notes"] = [
            {"at": "2026-10-27T03:00:00Z", "said": ["first line", "second line"]},
            {"at": "2026-10-27T03:01:00Z", "fact": ["measured 31.9%"]},
            {"asked_at": "2026-10-27T03:02:00Z", "number": 2, "question": ["**2. Q?**"], "options": ["a. yes", "b. no"]},
        ]
        out = self.check_item(json.dumps(base))
        self.assertIn("the owner said:\n    \u201cfirst line\n    second line\u201d", out)

    def test_an_item_with_no_notes_prints_no_notes_section(self):
        base = json.load(open(os.path.join(PLUGIN, "recall-decision", "queue", "the-owner-says-what-the-queue-keeps.json"), encoding="utf-8"))
        del base["notes"]
        self.check_item(json.dumps(base))


if __name__ == "__main__":
    unittest.main()
