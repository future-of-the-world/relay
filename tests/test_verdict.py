"""Review and check data as JSON (lib/relay_verdict.py, `relay check record`): schema refusals, the readable report
rendered from the same data, and the command's refusals. Every file lives in a temp directory.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "lib"))

import relay_verdict as rv  # noqa: E402

RELAY = os.path.join(ROOT, "bin", "relay")
SHA_A, SHA_B = "a" * 40, "b" * 40


def finding(fid="F1", **over):
    base = {"id": fid, "path": "lib/x.py", "line": 12, "severity": "HIGH", "kind": "inside", "summary": "drops a row",
            "failing_case": ["input a=1 gives 0 rows", "should give 1"]}
    base.update(over)
    return base


class Schema(unittest.TestCase):
    def review(self, **over):
        data = {"schema": rv.REVIEW_SCHEMA, "reviewed": SHA_A, "base": "master", "findings": [finding()]}
        data.update(over)
        return data

    def test_a_whole_review_has_no_errors_and_so_does_one_with_no_findings(self):
        self.assertEqual(rv.review_errors(self.review()), [])
        self.assertEqual(rv.review_errors(self.review(findings=[], reviewed="unknown")), [])

    def test_each_broken_finding_field_is_refused_by_name(self):
        # hand-listed: the field each bad value breaks, and the word the message must carry
        cases = [({"id": "1"}, "id must look like F1"), ({"line": 0}, "line must be a whole number of 1 or more"),
                 ({"line": "3"}, "line must be a whole number"), ({"line": True}, "line must be a whole number"),
                 ({"severity": "CRITICAL"}, "severity must be one of HIGH/MEDIUM/LOW"), ({"kind": "other"}, "kind must be one of"),
                 ({"summary": "two\nlines"}, "summary must be a one-line text"), ({"failing_case": []}, "no finding without a failing case"),
                 ({"failing_case": [""]}, "failing_case must be a list"), ({"path": ""}, "path must be")]
        for over, word in cases:
            errors = rv.review_errors(self.review(findings=[finding(**over)]))
            self.assertTrue(any(word in e for e in errors), (over, errors))

    def test_review_level_refusals(self):
        self.assertTrue(any("reviewed must be a full 40-character sha" in e for e in rv.review_errors(self.review(reviewed="abc1234"))))
        self.assertTrue(any("schema must be" in e for e in rv.review_errors(self.review(schema="other"))))
        self.assertTrue(any("used twice" in e for e in rv.review_errors(self.review(findings=[finding(), finding()]))))
        self.assertTrue(any("unknown field" in e for e in rv.review_errors(self.review(extra=1))))
        self.assertEqual(rv.review_errors([]), ["the review data is not an object"])

    def check(self, **over):
        data = {"schema": rv.CHECK_SCHEMA, "head": SHA_B, "reviewed": SHA_A, "gate": None, "worktree": "/w", "review": ["/r.json"],
                "findings": [{"id": "F1", "verdict": "MET", "note": "t.py:5"}], "new": [], "open": 0, "queued": 0}
        data.update(over)
        return data

    def test_a_whole_check_and_each_broken_field(self):
        self.assertEqual(rv.check_errors(self.check()), [])
        cases = [({"head": SHA_B[:7]}, "head must be a full 40-character sha"), ({"open": -1}, "open must be a whole number of 0 or more"),
                 ({"queued": "1"}, "queued must be"), ({"findings": [{"id": "F1", "verdict": "FINE"}]}, "verdict must be one of"),
                 ({"review": []}, "review must be a list of at least one"), ({"new": [finding(severity="x")]}, "new[0]: severity"),
                 ({"gate": ""}, "gate must be a log path or null"), ({"worktree": None}, "worktree must be a path")]
        for over, word in cases:
            errors = rv.check_errors(self.check(**over))
            self.assertTrue(any(word in e for e in errors), (over, errors))

    def test_every_verdict_word_is_accepted(self):
        for word in ("MET", "NOT MET", "DISPUTED", "GAP", "OUTSIDE", "QUEUED"):
            self.assertEqual(rv.check_errors(self.check(findings=[{"id": "F1", "verdict": word}])), [], word)

    def test_stored_copy_has_no_worktree(self):
        stored = rv.stored_check(self.check(), "A.review.json")
        self.assertEqual(rv.check_errors(stored, stored=True), [])
        self.assertNotIn("worktree", stored)
        self.assertEqual(stored["review"], ["A.review.json"])
        self.assertTrue(rv.check_errors(self.check(), stored=True))     # a worktree in a stored copy is refused

    def test_load_names_what_is_wrong(self):
        with self.assertRaises(rv.VerdictError) as caught:
            rv.load_review("not json", "the review data x")
        self.assertIn("the review data x is not JSON", str(caught.exception))
        with self.assertRaises(rv.VerdictError) as caught:
            rv.load_check(json.dumps(self.check(open="0")), "the check data y")
        self.assertIn("open must be a whole number", str(caught.exception))

    def test_parse_status_and_findings(self):
        self.assertEqual(rv.parse_status("F2=NOT MET: no test"), {"id": "F2", "verdict": "NOT MET", "note": "no test"})
        self.assertEqual(rv.parse_status("F1=MET"), {"id": "F1", "verdict": "MET"})
        with self.assertRaises(rv.VerdictError):
            rv.parse_status("F1=METAL")
        with self.assertRaises(rv.VerdictError):
            rv.parse_status("F1")
        got = rv.parse_findings(["id=F1", "path=a", "failing=x", "failing=y", "id=F2", "path=b"])
        self.assertEqual([f["id"] for f in got], ["F1", "F2"])
        self.assertEqual(got[0]["failing"], ["x", "y"])
        for bad in (["path=a"], ["id=F1", "colour=red"], ["id=F1", "path=a", "path=b"], ["nonsense"]):
            with self.assertRaises(rv.VerdictError):
                rv.parse_findings(bad)


class Record(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="relay-verdict-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.report = os.path.join(self.tmp, "rev.md")

    def relay(self, *args):
        return subprocess.run([sys.executable, RELAY, "check", "record", *args], capture_output=True, text=True,
                              env={**os.environ, "RELAY_ROOT": ROOT})

    def record_review(self, *extra):
        return self.relay("review", "--report", self.report, "--reviewed", SHA_A, "--base", "master", *extra)

    FINDING = ["--finding", "id=F1", "path=lib/x.py", "line=12", "severity=HIGH", "kind=inside", "summary=drops a row",
               "failing=input a=1 gives 0 rows", "failing=should give 1"]

    def test_markdown_is_rendered_from_the_json_and_keeps_the_prose(self):
        with open(self.report, "w") as handle:
            handle.write("# Review\nmy prose\n")
        done = self.record_review(*self.FINDING, "--finding", "id=F2", "path=lib/y.py", "line=3", "severity=LOW", "kind=outside",
                                  "summary=elsewhere", "failing=z")
        self.assertEqual(done.returncode, 0, done.stderr)
        data = json.load(open(os.path.join(self.tmp, "rev.json")))
        text = open(self.report).read()
        self.assertTrue(text.startswith("# Review\nmy prose\n\n" + rv.RECORD_MARK))
        # worked by hand: the linter line is path:line: SEVERITY: id summary, the failing case follows it, and the outside
        # finding sits under its own heading, after the inside one
        self.assertIn("Reviewed: %s\n" % SHA_A, text)
        self.assertIn("lib/x.py:12: HIGH: F1 drops a row\nFailing case: input a=1 gives 0 rows\nshould give 1\n", text)
        self.assertLess(text.index("F1 drops"), text.index("## Outside this change"))
        self.assertIn("## Outside this change\n\nlib/y.py:3: LOW: F2 elsewhere\nFailing case: z\n", text)
        self.assertEqual([f["id"] for f in data["findings"]], ["F1", "F2"])
        self.assertEqual(text.split(rv.RECORD_MARK)[1], rv.render_review(data).split(rv.RECORD_MARK)[1])

    def test_recording_again_replaces_the_block_not_the_prose(self):
        with open(self.report, "w") as handle:
            handle.write("# Review\nprose\n")
        self.assertEqual(self.record_review(*self.FINDING).returncode, 0)
        self.assertEqual(self.record_review().returncode, 0)          # no findings now
        text = open(self.report).read()
        self.assertEqual(text.count(rv.RECORD_MARK), 1)
        self.assertIn("prose", text)
        self.assertNotIn("F1", text)
        self.assertIn("No findings.", text)
        self.assertEqual(json.load(open(os.path.join(self.tmp, "rev.json")))["findings"], [])

    def test_a_bad_record_is_refused_with_a_message_and_writes_nothing(self):
        bad = ["--finding", "id=F1", "path=lib/x.py", "line=0", "severity=HIGH", "kind=inside", "summary=s", "failing=f"]
        done = self.record_review(*bad)
        self.assertEqual(done.returncode, 1)
        self.assertIn("nothing recorded", done.stderr)
        self.assertIn("line must be a whole number of 1 or more", done.stderr)
        self.assertEqual(os.listdir(self.tmp), [])
        done = self.relay("review", "--report", self.report, "--reviewed", "abc", "--base", "master")
        self.assertIn("reviewed must be a full 40-character sha", done.stderr)
        done = self.record_review("--finding", "id=F1", "path=a", "line=x")
        self.assertIn("line must be a whole number", done.stderr)
        self.assertEqual(os.listdir(self.tmp), [])
        self.assertEqual(self.relay("review", "--report", self.report).returncode, 1)     # missing options named

    def record_check(self, *extra, head=SHA_B, reviewed=SHA_A, review=None):
        review = review or os.path.join(self.tmp, "rev.json")
        report = os.path.join(self.tmp, "chk.md")
        return self.relay("check", "--report", report, "--head", head, "--reviewed", reviewed, "--worktree", self.tmp, "--gate", "none",
                          "--review", review, "--open", "1", "--queued", "0", *extra)

    def test_check_report_ends_with_the_verdict_block_built_from_the_json(self):
        self.assertEqual(self.record_review(*self.FINDING).returncode, 0)
        done = self.record_check("--status", "F1=NOT MET: no test", "--new", "id=F5", "path=lib/z.py", "line=2", "severity=MEDIUM",
                                 "kind=inside", "summary=a new problem", "failing=w")
        self.assertEqual(done.returncode, 0, done.stderr)
        text = open(os.path.join(self.tmp, "chk.md")).read()
        data = json.load(open(os.path.join(self.tmp, "chk.json")))
        self.assertTrue(text.endswith("## Verdict\nhead %s\nreviewed %s\nopen 1\nqueued 0\n" % (SHA_B, SHA_A)))
        self.assertIn("F1 NOT MET no test\n", text)
        self.assertIn("lib/z.py:2: MEDIUM: F5 a new problem", text)
        self.assertEqual((data["open"], data["queued"], data["gate"]), (1, 0, None))
        self.assertEqual(data["findings"], [{"id": "F1", "verdict": "NOT MET", "note": "no test"}])
        self.assertEqual(data["new"][0]["id"], "F5")

    def test_check_refuses_what_the_review_data_contradicts(self):
        # no review data yet
        done = self.record_check()
        self.assertIn("the review data", done.stderr)
        self.assertIn("record the review first", done.stderr)
        self.assertEqual(self.record_review(*self.FINDING).returncode, 0)
        # a different reviewed sha than the review's
        done = self.record_check(reviewed=SHA_B)
        self.assertIn("is of %s, not of the reviewed sha %s" % (SHA_A, SHA_B), done.stderr)
        # a status for a finding nobody made
        done = self.record_check("--status", "F9=MET")
        self.assertIn("F9 is not a finding of the reviews or a new one", done.stderr)
        # an abbreviated head
        done = self.record_check(head=SHA_B[:7])
        self.assertIn("head must be a full 40-character sha", done.stderr)
        # a corrupt review data file
        broken = os.path.join(self.tmp, "broken.json")
        open(broken, "w").write("{")
        self.assertIn("is not JSON", self.record_check(review=broken).stderr)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "chk.json")))
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "chk.md")))


if __name__ == "__main__":
    unittest.main()
