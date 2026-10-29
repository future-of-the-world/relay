"""The finds-the-contradiction grader of evals/plugin/spec-reviewer-flaw passes the
reply of the failing 24 Oct run (the spec named in prose, design.md/D2 elsewhere)
and still fails a reply that never names the design side."""
import json
import shutil
import subprocess
import unittest
from pathlib import Path

CASE = Path(__file__).resolve().parent.parent / "evals/plugin/spec-reviewer-flaw"


def grader(path):
    # front matter: `pattern: "<json string>"` and `flags: i`
    meta = {}
    for line in path.read_text(encoding="utf-8").split("\n")[1:]:
        if line == "---":
            break
        k, _, v = line.partition(":")
        v = v.strip()
        meta[k.strip()] = json.loads(v) if v.startswith('"') else v
    return meta


def matches(meta, reply):
    # node's RegExp is the grader's own dialect (same as evals/plugin/graders.py)
    js = ("const [p,f,t]=JSON.parse(require('fs').readFileSync(0,'utf8'));"
          "process.stdout.write(String(new RegExp(p,f).test(t)))")
    out = subprocess.run(["node", "-e", js], input=json.dumps([meta["pattern"], meta.get("flags", ""), reply]),
                         capture_output=True, text=True, check=True).stdout
    return out == "true"


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class FindsTheContradiction(unittest.TestCase):
    def setUp(self):
        self.meta = grader(CASE / "graders/finds-the-contradiction.md")

    def test_failing_run_reply_passes(self):
        # run-spec-in-prose.txt names "the spec" in prose and design.md:13 / D2 on another line
        reply = (CASE / "recorded/good/run-spec-in-prose.txt").read_text(encoding="utf-8")
        self.assertTrue(matches(self.meta, reply))

    def test_reply_without_the_design_side_still_fails(self):
        reply = (CASE / "recorded/bad/finds-the-contradiction__contradiction-elsewhere.txt").read_text(encoding="utf-8")
        self.assertFalse(matches(self.meta, reply))


if __name__ == "__main__":
    unittest.main()
