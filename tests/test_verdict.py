"""Review and check data as JSON, the only stored form (lib/relay_verdict.py, `relay check record --input`): schema
refusals, the TOML input and its refusals, the readable text rendered from the JSON on demand. Every file lives in a
temp directory.
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

import relay_checkpage  # noqa: E402
import relay_verdict as rv  # noqa: E402

RELAY = os.path.join(ROOT, "bin", "relay")
SHA_A, SHA_B = "a" * 40, "b" * 40


def finding(fid="F1", **over):
    base = {"id": fid, "path": "lib/x.py", "line": 12, "severity": "HIGH", "rank": "high", "kind": "inside", "summary": "drops a row",
            "failing_case": ["input a=1 gives 0 rows", "should give 1"]}
    base.update(over)
    return base


class Schema(unittest.TestCase):
    def review(self, **over):
        data = {"schema": 1, "type": "review", "reviewed": SHA_A, "base": "master", "findings": [finding()]}
        data.update(over)
        return data

    def test_a_whole_review_has_no_errors_and_so_does_one_with_no_findings(self):
        self.assertEqual(rv.review_errors(self.review()), [])
        self.assertEqual(rv.review_errors(self.review(findings=[], reviewed="unknown")), [])

    def test_each_broken_finding_field_is_refused_by_name(self):
        # hand-listed: the field each bad value breaks, and the word the message must carry
        cases = [({"id": "1"}, "id must look like F1"), ({"line": 0}, "line must be a whole number of 1 or more"),
                 ({"line": "3"}, "line must be a whole number"), ({"line": True}, "line must be a whole number"),
                 ({"severity": "URGENT"}, "severity must be one of HIGH/MEDIUM/LOW, BLOCKER/FIX/NIT, CRITICAL/WARNING/SUGGESTION"), ({"rank": "low"}, "rank must be high for severity HIGH"), ({"kind": "other"}, "kind must be one of"),
                 ({"summary": "two\nlines"}, "summary must be a one-line text"), ({"failing_case": []}, "no finding without a failing case"),
                 ({"failing_case": ["", "  "]}, "failing_case must be a list of lines with at least one non-empty line"), ({"path": ""}, "path must be"),
                 ({"details": "text"}, "details must be a list of one-line texts"), ({"evidence": ["a\nb"]}, "evidence must be a list"),
                 ({"fix_hint": [1]}, "fix_hint must be a list"), ({"pass_cases": "x"}, "pass_cases must be a list")]
        for over, word in cases:
            errors = rv.review_errors(self.review(findings=[finding(**over)]))
            self.assertTrue(any(word in e for e in errors), (over, errors))

    def test_q_ids_and_every_prose_field_are_accepted(self):
        whole = finding("Q1", details=["why", ""], pass_cases=["p"], evidence=["$ cmd", "out"], fix_hint=["do x"])
        self.assertEqual(rv.review_errors(self.review(findings=[whole], scope=["s"], notes=["n"])), [])

    def test_review_level_refusals(self):
        self.assertTrue(any("reviewed must be a full 40-character sha" in e for e in rv.review_errors(self.review(reviewed="abc1234"))))
        self.assertTrue(any("schema must be 1" in e for e in rv.review_errors(self.review(schema="other"))))
        self.assertTrue(any("type must be review" in e for e in rv.review_errors(self.review(type="check"))))
        self.assertTrue(any("used twice" in e for e in rv.review_errors(self.review(findings=[finding(), finding()]))))
        self.assertTrue(any("unknown field" in e for e in rv.review_errors(self.review(extra=1))))
        self.assertTrue(any("scope" in e for e in rv.review_errors(self.review(scope="one text"))))
        self.assertEqual(rv.review_errors([]), ["the review data is not an object"])

    def check(self, **over):
        data = {"schema": 1, "type": "check", "head": SHA_B, "reviewed": SHA_A, "gate": None, "worktree": "/w", "review": ["/r.json"],
                "findings": [{"id": "F1", "verdict": "MET", "reason": ["t.py:5"]}], "new": [], "open": 0, "queued": 0}
        data.update(over)
        return data

    def test_a_whole_check_and_each_broken_field(self):
        self.assertEqual(rv.check_errors(self.check()), [])
        cases = [({"head": SHA_B[:7]}, "head must be a full 40-character sha"), ({"open": -1}, "open must be a whole number of 0 or more"),
                 ({"queued": "1"}, "queued must be"), ({"findings": [{"id": "F1", "verdict": "FINE"}]}, "verdict must be one of"),
                 ({"findings": [{"id": "F1", "verdict": "MET", "reason": "t"}]}, "reason must be a list"),
                 ({"review": []}, "review must be a list of at least one"), ({"new": [finding(severity="x")]}, "new[0]: severity"),
                 ({"gate": ""}, "gate must be a log path or null"), ({"worktree": None}, "worktree must be a path"),
                 ({"type": "review"}, "type must be check")]
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
        with self.assertRaises(rv.VerdictError) as caught:
            rv.load_any(json.dumps({"type": "report"}), "z")
        self.assertIn("is not a review, a check or a stored review", str(caught.exception))


def lit(lines):
    """A TOML multi-line literal string holding these lines (nothing in it is escaped)."""
    return "'''\n" + "\n".join(lines) + "\n'''"


def toml_finding(table, f):
    """The TOML text of one [[finding]]/[[new]] table from a dict whose list values are prose and the rest scalars."""
    out = ["[[%s]]" % table]
    for key, value in f.items():
        out.append("%s = %s" % (key, lit(value) if isinstance(value, list) else json.dumps(value)))
    return "\n".join(out) + "\n"


def toml_input(top, tables=()):
    """A TOML input: `top` is {key: scalar or list of lines}, `tables` is [(table name, dict)]."""
    # `review` is a list of paths (a TOML array), every other list is prose lines (a multi-line string)
    out = ["%s = %s" % (k, lit(v) if isinstance(v, list) and k != "review" else json.dumps(v)) for k, v in top.items()]
    return "\n".join(out) + "\n\n" + "\n".join(toml_finding(t, f) for t, f in tables)


# a finding as the agent writes it in the input (no rank: the script derives it)
IN_FINDING = {"id": "F1", "path": "lib/x.py", "line": 12, "severity": "HIGH", "kind": "inside", "summary": "drops a row",
              "failing_case": ["input a=1 gives 0 rows", "should give 1"]}


class RecordBase(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="relay-verdict-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.report = os.path.join(self.tmp, "rev.json")

    def relay(self, *args):
        return subprocess.run([sys.executable, RELAY, *args], capture_output=True, text=True, env={**os.environ, "RELAY_ROOT": ROOT})

    def write_input(self, text, name="in.toml"):
        path = os.path.join(self.tmp, name)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        return path

    def record_review(self, findings=(IN_FINDING,), **top):
        fields = {"report": self.report, "reviewed": SHA_A, "base": "master"}
        fields.update(top)
        return self.relay("check", "record", "review", "--input", self.write_input(toml_input(fields, [("finding", f) for f in findings])))

    def record_check(self, statuses=(), new=(), review=None, name="chk.json", **top):
        fields = {"report": os.path.join(self.tmp, name), "head": SHA_B, "reviewed": SHA_A, "worktree": self.tmp, "gate": "none",
                  "review": [review or self.report], "open": 1, "queued": 0}
        fields.update(top)
        tables = [("status", s) for s in statuses] + [("new", f) for f in new]
        return self.relay("check", "record", "check", "--input", self.write_input(toml_input(fields, tables), "chk.toml"))

    def load(self, name="rev.json"):
        with open(os.path.join(self.tmp, name), encoding="utf-8") as handle:
            return json.load(handle)


class Record(RecordBase):
    def test_a_review_is_stored_as_json_only_and_no_markdown_is_written(self):
        done = self.record_review([IN_FINDING, dict(IN_FINDING, id="F2", path="lib/y.py", line=3, severity="LOW", kind="outside", summary="elsewhere")])
        self.assertEqual(done.returncode, 0, done.stderr)
        data = self.load()
        # the severity word gives the rank; the schema and type are set by the script
        self.assertEqual((data["schema"], data["type"], data["reviewed"], data["base"]), (1, "review", SHA_A, "master"))
        self.assertEqual([(f["id"], f["severity"], f["rank"]) for f in data["findings"]], [("F1", "HIGH", "high"), ("F2", "LOW", "low")])
        # the only files in the folder are the input and the one JSON: no readable copy of the report is written
        self.assertEqual(sorted(os.listdir(self.tmp)), ["in.toml", "rev.json"])
        self.assertEqual(done.stdout.strip(), "recorded " + self.report)

    def test_every_prose_field_of_a_review_and_a_check_round_trips(self):
        f = dict(IN_FINDING, details=["why it happens", "", "second paragraph"], pass_cases=["a=2 gives 2"], evidence=["$ python t.py", "AssertionError"],
                 fix_hint=["sort before comparing"])
        done = self.record_review([f], scope=["reviewed lib/x.py against master", "ran the tests"], notes=["lib/y.py is fine", "design: ok"])
        self.assertEqual(done.returncode, 0, done.stderr)
        data = self.load()
        self.assertEqual(data["scope"], ["reviewed lib/x.py against master", "ran the tests"])
        self.assertEqual(data["notes"], ["lib/y.py is fine", "design: ok"])
        stored = data["findings"][0]
        for key in ("details", "pass_cases", "evidence", "fix_hint", "failing_case"):
            self.assertEqual(stored[key], f[key], key)          # lines as written, the empty line between paragraphs kept
        done = self.record_check(statuses=[{"id": "F1", "verdict": "NOT MET", "reason": ["no test", "see t.py"]}], new=[dict(IN_FINDING, id="F5", details=["d"])],
                                 scope=["rechecked F1"], notes=["gate was red"])
        self.assertEqual(done.returncode, 0, done.stderr)
        check = self.load("chk.json")
        self.assertEqual(check["findings"], [{"id": "F1", "verdict": "NOT MET", "reason": ["no test", "see t.py"]}])
        self.assertEqual((check["scope"], check["notes"], check["new"][0]["details"]), (["rechecked F1"], ["gate was red"], ["d"]))

    def test_text_with_shell_characters_is_stored_byte_identical(self):
        # a line a shell would change: a variable, backticks, a substitution, quotes of both kinds, a backslash, leading spaces
        text = ['costs $TMPDIR and `rm -rf x` and $(whoami)', '  "double" and \'single\' and \\n a backslash', 'tab\tinside', 'last line  ']
        done = self.record_review([dict(IN_FINDING, details=["x"])], notes=text)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.load()["notes"], text)           # the lines come back exactly, with their spaces

    def test_recording_again_replaces_the_data(self):
        self.assertEqual(self.record_review().returncode, 0)
        self.assertEqual(self.record_review(findings=()).returncode, 0)
        self.assertEqual(self.load()["findings"], [])

    def test_a_bad_input_is_refused_with_the_field_named_and_writes_nothing(self):
        cases = [
            ("bad syntax", "report = (\n", "not valid TOML"),
            ("unknown top key", toml_input({"report": self.report, "reviewed": SHA_A, "base": "m", "colour": "red"}), "unknown key `colour` at the top of the input"),
            ("missing base", toml_input({"report": self.report, "reviewed": SHA_A}), "missing required key `base` at the top of the input"),
            ("unknown finding key", toml_input({"report": self.report, "reviewed": SHA_A, "base": "m"}, [("finding", dict(IN_FINDING, rank="high"))]),
             "unknown key `rank` in [[finding]] 1"),
            ("missing finding key", toml_input({"report": self.report, "reviewed": SHA_A, "base": "m"}, [("finding", {k: v for k, v in IN_FINDING.items() if k != "summary"})]),
             "missing required key `summary` in [[finding]] 1"),
            ("bad line", toml_input({"report": self.report, "reviewed": SHA_A, "base": "m"}, [("finding", dict(IN_FINDING, line=0))]), "line must be a whole number of 1 or more"),
            ("bad sha", toml_input({"report": self.report, "reviewed": "abc", "base": "m"}), "reviewed must be a full 40-character sha"),
            ("report not json", toml_input({"report": "rev.md", "reviewed": SHA_A, "base": "m"}), "`report` must be the path of the report's JSON file, ending in .json"),
            ("prose of the wrong kind", toml_input({"report": self.report, "reviewed": SHA_A, "base": "m", "notes": 3}), "`notes` at the top of the input must be a text"),
        ]
        for name, text, expect in cases:
            done = self.relay("check", "record", "review", "--input", self.write_input(text))
            self.assertEqual(done.returncode, 1, name)
            self.assertIn("nothing recorded", done.stderr, name)
            self.assertIn(expect, done.stderr, name)
            self.assertFalse(os.path.exists(self.report), name)
        self.assertEqual(self.relay("check", "record", "review", "--input", os.path.join(self.tmp, "none.toml")).returncode, 1)
        for bad_args in (("review",), ("review", "--report", self.report), ("other", "--input", "x"), ("review", "--input", "a", "b")):
            self.assertEqual(self.relay("check", "record", *bad_args).returncode, 2, bad_args)     # the old option form is gone

    def test_check_data_is_stored_with_its_verdicts_and_new_problems(self):
        self.assertEqual(self.record_review().returncode, 0)
        done = self.record_check(statuses=[{"id": "F1", "verdict": "NOT MET", "reason": ["no test"]}], new=[dict(IN_FINDING, id="F5", path="lib/z.py", line=2, severity="MEDIUM", summary="a new problem")])
        self.assertEqual(done.returncode, 0, done.stderr)
        data = self.load("chk.json")
        self.assertEqual((data["schema"], data["type"], data["open"], data["queued"], data["gate"]), (1, "check", 1, 0, None))
        self.assertEqual(data["new"][0]["id"], "F5")
        self.assertEqual(data["new"][0]["rank"], "medium")
        self.assertEqual(data["review"], [self.report])
        self.assertEqual(sorted(os.listdir(self.tmp)), ["chk.json", "chk.toml", "in.toml", "rev.json"])

    def test_check_refuses_what_the_review_data_contradicts(self):
        # no review data yet
        done = self.record_check()
        self.assertIn("the review data", done.stderr)
        self.assertIn("record the review first", done.stderr)
        self.assertEqual(self.record_review().returncode, 0)
        # a different reviewed sha than the review's
        done = self.record_check(reviewed=SHA_B)
        self.assertIn("is of %s, not of the reviewed sha %s" % (SHA_A, SHA_B), done.stderr)
        # a status for a finding nobody made
        done = self.record_check(statuses=[{"id": "F9", "verdict": "MET"}])
        self.assertIn("F9 is not a finding of the reviews or a new one", done.stderr)
        # an abbreviated head
        done = self.record_check(head=SHA_B[:7])
        self.assertIn("head must be a full 40-character sha", done.stderr)
        # a missing key and an unknown one, named
        done = self.relay("check", "record", "check", "--input", self.write_input(toml_input({"report": os.path.join(self.tmp, "chk.json"), "head": SHA_B, "extra": 1})))
        self.assertIn("unknown key `extra`", done.stderr)
        self.assertIn("missing required key `worktree`", done.stderr)
        # a corrupt review data file
        broken = os.path.join(self.tmp, "broken.json")
        open(broken, "w").write("{")
        self.assertIn("is not JSON", self.record_check(review=broken).stderr)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "chk.json")))


class Views(RecordBase):
    """`relay check show` prints the readable text from the JSON; the same data gives the full text and the short one."""

    def recorded(self):
        f = dict(IN_FINDING, details=["because the loop stops early"], evidence=["$ pytest -k x", "1 failed"], pass_cases=["a=2 is fine"], fix_hint=["use <="])
        out = dict(IN_FINDING, id="F2", path="lib/y.py", line=3, severity="LOW", kind="outside", summary="elsewhere", failing_case=["z"])
        self.assertEqual(self.record_review([f, out], scope=["lib/x.py against master"], notes=["lib/w.py is fine"]).returncode, 0)

    def test_show_prints_the_full_report_from_the_json(self):
        self.recorded()
        done = self.relay("check", "show", self.report)
        self.assertEqual(done.returncode, 0, done.stderr)
        # worked by hand from the recorded data: header, scope, notes, the count, then each finding as a linter line with its
        # prose under it (a non-inside kind is named); sections in a fixed order, only the ones with lines
        self.assertEqual(done.stdout, "\n".join([
            "Review of %s against master" % SHA_A, "Scope:", "  lib/x.py against master", "Notes:", "  lib/w.py is fine", "Findings: 2", "",
            "lib/x.py:12: HIGH: F1 drops a row",
            "  Failing case:", "    input a=1 gives 0 rows", "    should give 1",
            "  Pass cases:", "    a=2 is fine",
            "  Details:", "    because the loop stops early",
            "  Evidence:", "    $ pytest -k x", "    1 failed",
            "  Fix hint:", "    use <=", "",
            "lib/y.py:3: LOW: F2 elsewhere", "  Kind: outside", "  Failing case:", "    z", ""]))

    def test_brief_is_a_short_summary_cut_at_ten_lines(self):
        self.recorded()
        done = self.relay("check", "show", "--brief", self.report)
        self.assertEqual(done.stdout.splitlines(), ["Review of %s against master: 2 findings (high 1, medium 0, low 1)" % SHA_A[:12],
                                                    "lib/x.py:12: HIGH: F1 drops a row", "lib/y.py:3: LOW: F2 elsewhere"])
        many = [dict(IN_FINDING, id="F%d" % n, line=n) for n in range(1, 13)]
        self.assertEqual(self.record_review(many).returncode, 0)
        lines = self.relay("check", "show", "--brief", self.report).stdout.splitlines()
        # 1 header + 12 findings = 13 lines; ten fit: the header, 8 findings, and the cut line counting the 4 left out
        self.assertEqual(len(lines), 10)
        self.assertEqual(lines[1], "lib/x.py:1: HIGH: F1 drops a row")
        self.assertEqual(lines[-1], "... 4 more lines: relay check show %s" % self.report)

    def test_show_of_a_check_lists_verdicts_with_their_reasons(self):
        self.recorded()
        self.assertEqual(self.record_check(statuses=[{"id": "F1", "verdict": "NOT MET", "reason": ["no test", "see t.py"]}, {"id": "F2", "verdict": "OUTSIDE"}],
                                           new=[dict(IN_FINDING, id="F5", summary="fresh")], notes=["gate red"]).returncode, 0)
        path = os.path.join(self.tmp, "chk.json")
        full = self.relay("check", "show", path).stdout
        for line in ("Check of %s" % SHA_B, "Reviewed: %s" % SHA_A, "Gate: none", "Open: 1  Queued: 0", "Notes:", "  gate red", "Findings checked: 2",
                     "F1 NOT MET", "  no test", "  see t.py", "F2 OUTSIDE", "New problems: 1", "lib/x.py:12: HIGH: F5 fresh"):
            self.assertIn(line + "\n", full)
        brief = self.relay("check", "show", "--brief", path).stdout.splitlines()
        self.assertEqual(brief, ["Check of %s (reviewed %s): open 1, queued 0, gate none" % (SHA_B[:12], SHA_A[:12]), "F1 NOT MET no test", "F2 OUTSIDE",
                                 "new: lib/x.py:12: HIGH: F5 fresh"])

    def test_show_refuses_what_is_not_a_report(self):
        path = os.path.join(self.tmp, "other.json")
        open(path, "w").write('{"type": "report"}')
        done = self.relay("check", "show", path)
        self.assertEqual(done.returncode, 1)
        self.assertIn("is not a review, a check or a stored review", done.stderr)


class FlowWords(RecordBase):
    """A flow's own severity words are accepted: the finding keeps the word and stores its rank beside it."""

    # the sets named in the flows: roles/judge.md (default), sdd spec-reviewer ("BLOCKER = HIGH, FIX = MEDIUM, NIT = LOW"),
    # sdd spec-conformance (CRITICAL / WARNING / SUGGESTION, worked as high / medium / low in that order)
    SETS = {"default": [("HIGH", "high"), ("MEDIUM", "medium"), ("LOW", "low")],
            "spec-reviewer": [("BLOCKER", "high"), ("FIX", "medium"), ("NIT", "low")],
            "spec-conformance": [("CRITICAL", "high"), ("WARNING", "medium"), ("SUGGESTION", "low")]}

    def record_set(self, words):
        found = [dict(IN_FINDING, id="F%d" % i, line=i, severity=word, summary="s%d" % i) for i, (word, _) in enumerate(words, 1)]
        done = self.record_review(found)
        self.assertEqual(done.returncode, 0, done.stderr)
        return self.load()

    def test_each_flows_words_are_kept_with_their_rank(self):
        for flow, words in self.SETS.items():
            data = self.record_set(words)
            self.assertEqual([(f["severity"], f["rank"]) for f in data["findings"]], words, flow)
            self.assertIn("lib/x.py:1: %s: F1 s1" % words[0][0], rv.render_review(data), flow)
            self.assertEqual(rv.counts_by_rank(data["findings"]), {"high": 1, "medium": 1, "low": 1}, flow)

    def test_a_word_of_no_flow_is_refused_naming_the_sets(self):
        done = self.record_review([dict(IN_FINDING, severity="URGENT")])
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("severity must be one of HIGH/MEDIUM/LOW, BLOCKER/FIX/NIT, CRITICAL/WARNING/SUGGESTION", done.stderr)
        self.assertFalse(os.path.exists(self.report))

    def test_counts_by_rank_mix_words_of_two_flows(self):
        # BLOCKER and CRITICAL are both high; FIX is medium: worked by hand 2 / 1 / 0
        found = [dict(finding(), severity="BLOCKER", rank="high"), dict(finding(), severity="CRITICAL", rank="high"),
                 dict(finding(), severity="FIX", rank="medium")]
        self.assertEqual(rv.counts_by_rank(found), {"high": 2, "medium": 1, "low": 0})


class Owner(RecordBase):
    """`relay check owner`: the owner's word that a finding is not wrong is data in the review JSON, not a prompt line."""

    # shell characters, a quote, a backslash and a second line: none may change on the way into the JSON
    WORDS = ["it's \"fine\" as built: $HOME `date` $(touch x) & ; | > \\n", "second line, kept"]

    def owner(self, fid="F1", words=None, review=None):
        text = "words = " + lit(self.WORDS if words is None else words) + "\n"
        return self.relay("check", "owner", review or self.report, fid, "--input", self.write_input(text, "owner.toml"))

    def test_the_word_is_appended_verbatim_with_the_date_and_the_review_stays_valid(self):
        self.assertEqual(self.record_review([IN_FINDING, dict(IN_FINDING, id="F2", line=3)]).returncode, 0)
        done = self.owner("F2")
        self.assertEqual(done.returncode, 0, done.stderr)
        data = self.load()
        # one entry: the id asked for, the two lines exactly as written (no shell touched them), a date
        self.assertEqual([(e["id"], e["words"]) for e in data["owner"]], [("F2", self.WORDS)])
        self.assertRegex(data["owner"][0]["date"], r"^\d{4}-\d{2}-\d{2}$")
        self.assertEqual(rv.review_errors(data), [])
        self.assertEqual(sorted(os.listdir(self.tmp)), ["in.toml", "owner.toml", "rev.json"])    # no readable copy written
        self.assertEqual(self.owner("F1", ["second word"]).returncode, 0)
        self.assertEqual([e["id"] for e in self.load()["owner"]], ["F2", "F1"])                 # a second word is appended

    def test_the_library_stores_the_date_it_is_given(self):
        self.assertEqual(self.record_review().returncode, 0)
        rv.add_owner(self.report, "F1", self.write_input("words = '''no problem'''\n"), "2026-10-23")
        self.assertEqual(self.load()["owner"], [{"id": "F1", "words": ["no problem"], "date": "2026-10-23"}])

    def test_an_unknown_id_is_refused_and_the_review_is_unchanged(self):
        self.assertEqual(self.record_review().returncode, 0)
        before = open(self.report, encoding="utf-8").read()
        done = self.owner("F9")
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("F9 is not a finding of", done.stderr)
        self.assertEqual(open(self.report, encoding="utf-8").read(), before)

    def test_bad_input_is_refused_by_name(self):
        self.assertEqual(self.record_review().returncode, 0)
        for text, word in (("other = 'x'\n", "unknown key `other`"), ("", "missing required key `words`"), ("words = '''  '''\n", "must hold the owner's words")):
            done = self.relay("check", "owner", self.report, "F1", "--input", self.write_input(text, "o.toml"))
            self.assertNotEqual(done.returncode, 0, text)
            self.assertIn(word, done.stderr)
        self.assertNotIn("owner", self.load())

    def test_the_schema_refuses_an_owner_entry_for_a_finding_the_review_lacks(self):
        data = {"schema": 1, "type": "review", "reviewed": SHA_A, "base": "master", "findings": [finding()],
                "owner": [{"id": "F5", "words": ["x"], "date": "2026-10-23"}]}
        self.assertTrue(any("id 'F5' is not a finding of this review" in e for e in rv.review_errors(data)))
        data["owner"] = [{"id": "F1", "words": [], "date": "23 Oct"}]
        errors = rv.review_errors(data)
        self.assertTrue(any("words must be a list of lines" in e for e in errors) and any("date must look like" in e for e in errors), errors)

    def test_the_checker_count_leaves_out_a_finding_with_an_owner_entry(self):
        high, medium, low = finding("F1"), finding("F2", severity="FIX", rank="medium"), finding("F3", severity="NIT", rank="low")
        outside = finding("F4", kind="outside")
        review = {"schema": 1, "type": "review", "reviewed": SHA_A, "base": "master", "findings": [high, medium, low, outside]}
        statuses = [{"id": i, "verdict": "NOT MET"} for i in ("F1", "F2", "F3", "F4")]
        # high and medium inside the change and NOT MET: F1 and F2 (F3 is low, F4 is outside) -> 2
        self.assertEqual(rv.count_open(review, statuses), 2)
        review["owner"] = [{"id": "F1", "words": ["not wrong"], "date": "2026-10-23"}]
        self.assertEqual(rv.count_open(review, statuses), 1)           # the owner's word takes F1 out: only F2 is left
        self.assertEqual(rv.count_open(review, [dict(s, verdict="MET") for s in statuses]), 0)

    def test_show_and_the_page_print_the_words_under_the_finding(self):
        self.assertEqual(self.record_review().returncode, 0)
        self.assertEqual(self.owner("F1", ["not wrong, because it is by design"]).returncode, 0)
        data = self.load()
        date = data["owner"][0]["date"]
        shown = self.relay("check", "show", self.report).stdout
        self.assertIn("  Owner (%s) says not wrong:\n    not wrong, because it is by design\n" % date, shown)
        view = relay_checkpage.finding_view(data["findings"][0], rv.owner_of(data, "F1"))
        self.assertIn("Owner: not wrong: not wrong, because it is by design (%s)" % date, relay_checkpage.render_finding(view, "not checked", []))
        plain = relay_checkpage.render_finding(relay_checkpage.finding_view(data["findings"][0]), "not checked", [])
        self.assertNotIn("Owner", plain)


class ApplyReviewHandoff(RecordBase):
    """sdd:apply-review hands the triage to the checker as a review record: the author writes the TOML input and records it,
    the checker's `Check:` names that JSON. The fixture runs both record steps with no live agent."""

    SKILL = os.path.join(ROOT, "plugins", "sdd", "skills", "apply-review", "SKILL.md")

    def test_a_triage_recorded_as_a_review_is_what_a_check_records_against(self):
        triage = os.path.join(self.tmp, "triage.json")
        finding_in = dict(IN_FINDING, evidence=["screenshot: shots/home.png"], pass_cases=["a=2 gives 1 row"])
        fields = {"report": triage, "reviewed": SHA_A, "base": "master", "notes": ["Group A: lib/x.py (F1)", "For the owner: none"]}
        recorded = self.relay("check", "record", "review", "--input", self.write_input(toml_input(fields, [("finding", finding_in)]), "triage.toml"))
        self.assertEqual(recorded.returncode, 0, recorded.stderr)
        data = self.load("triage.json")
        self.assertEqual(data["type"], "review")
        self.assertEqual(data["notes"][0], "Group A: lib/x.py (F1)")
        checked = self.record_check(statuses=[{"id": "F1", "verdict": "MET", "reason": ["tests/test_x.py:4"]}], review=triage, open=0)
        self.assertEqual(checked.returncode, 0, checked.stderr)
        self.assertEqual(self.load("chk.json")["review"], [triage])
        self.assertIn("F1 MET", self.relay("check", "show", os.path.join(self.tmp, "chk.json")).stdout)

    def test_the_checker_refuses_a_markdown_triage(self):
        old = os.path.join(self.tmp, "triage.md")
        with open(old, "w") as handle:
            handle.write("## Group A\nF1\n")
        done = self.record_check(statuses=[{"id": "F1", "verdict": "MET"}], review=old)
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("is not JSON", done.stderr)

    def test_the_skill_hands_the_json_over_and_names_no_triage_markdown(self):
        with open(self.SKILL, encoding="utf-8") as handle:
            text = handle.read()
        self.assertNotIn("review/triage.md", text)
        self.assertIn("relay check record review --input", text)
        checks = [l for l in text.splitlines() if l.startswith("> Check:")]
        self.assertEqual(len(checks), 1)
        self.assertIn("Check: `<scratchpad>/review/triage.json`", checks[0])


if __name__ == "__main__":
    unittest.main()
