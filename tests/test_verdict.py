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
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "lib"))

import relay_git  # noqa: E402
import relay_verdict as rv  # noqa: E402

RELAY = os.path.join(ROOT, "bin", "relay")
SHA_A, SHA_B = "a" * 40, "b" * 40


def finding(fid="F1", **over):
    base = {"id": fid, "path": "lib/x.py", "line": 12, "severity": "HIGH", "rank": "high", "kind": "inside", "summary": "drops a row",
            "failing_case": ["input a=1 gives 0 rows", "should give 1"]}
    base.update(over)
    return base


def record_finding(fid="F1", **over):
    """A finding of a check record: a review finding with its source, the commit it was stated at, and its verdict."""
    out = finding(fid, source="a.json", since=SHA_A, verdict="MET", reason=["t.py:5"])
    out.update(over)
    return out


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
        """A recorded check record (schema 2) with one finding."""
        data = {"schema": 2, "type": "check", "head": SHA_B, "branch": "wt/x", "item": None, "gate": None, "worktree": "/w",
                "findings": [record_finding("F1")]}
        data.update(over)
        return data

    def test_a_whole_check_and_each_broken_field(self):
        self.assertEqual(rv.record_errors(self.check()), [])
        cases = [({"head": SHA_B[:7]}, "head must be a full 40-character sha"), ({"item": "Bad Name"}, "item must be null or the name of a queue item"),
                 ({"findings": [record_finding("F1", verdict="FINE")]}, "verdict must be one of"),
                 ({"findings": [record_finding("F1", reason="t")]}, "reason must be a list"),
                 ({"findings": [record_finding("F1", since="abc")]}, "since must be a full 40-character sha"),
                 ({"findings": [record_finding("F1", source="")]}, "source must be a one-line text"),
                 ({"findings": [record_finding("F1", severity="x")]}, "findings[0]: severity"),
                 ({"findings": [record_finding("F1"), record_finding("F1")]}, "id F1 is used twice"),
                 ({"findings": [record_finding("F1", owner=[{"words": [], "date": "2026-10-24"}])]}, "words must hold at least one"),
                 ({"gate": "x.log"}, "gate must be null, a gate log file name"), ({"worktree": None}, "worktree must be a path"),
                 ({"open": 0}, "unknown field open"), ({"type": "review"}, "type must be check")]
        for over, word in cases:
            errors = rv.record_errors(self.check(**over))
            self.assertTrue(any(word in e for e in errors), (over, errors))

    def test_every_verdict_word_is_accepted(self):
        for word in ("MET", "NOT MET", "DISPUTED", "GAP", "OUTSIDE", "QUEUED"):
            self.assertEqual(rv.record_errors(self.check(findings=[record_finding("F1", verdict=word)])), [], word)

    def test_every_finding_source_has_its_id_letter(self):
        ids = [record_finding(i) for i in ("Q1", "F1", "M1", "N1")]
        self.assertEqual(rv.record_errors(self.check(findings=ids)), [])
        self.assertTrue(rv.record_errors(self.check(findings=[record_finding("X1")])))

    def test_stored_copy_has_no_worktree(self):
        stored = rv.stored_record(self.check())
        self.assertEqual(rv.record_errors(stored, stored=True), [])
        self.assertNotIn("worktree", stored)
        self.assertTrue(rv.record_errors(self.check(), stored=True))     # a worktree in a stored copy is refused

    def test_counts_are_derived_from_the_findings(self):
        high, med, low = record_finding("F1", verdict="NOT MET"), record_finding("F2", verdict="NOT MET", severity="FIX", rank="medium"), \
            record_finding("F3", verdict="NOT MET", severity="NIT", rank="low")
        outside = record_finding("F4", verdict="NOT MET", kind="outside")
        data = self.check(findings=[high, med, low, outside])
        # high and medium inside the change and not MET: F1 and F2 (F3 is low, F4 is outside) -> 2
        self.assertEqual(rv.open_of(data), 2)
        high["owner"] = [{"words": ["not wrong"], "date": "2026-10-23"}]      # the owner's word takes F1 out
        self.assertEqual(rv.open_of(data), 1)
        med["owner"] = [{"words": ["later"], "date": "2026-10-23", "queue": "redo-x"}]       # a move answers F2 and counts as queued
        self.assertEqual((rv.open_of(data), rv.queued_of(data)), (0, 1))
        self.assertEqual(rv.open_of(self.check(findings=[dict(f, verdict="MET") for f in (high, med)])), 0)

    def test_load_names_what_is_wrong(self):
        with self.assertRaises(rv.VerdictError) as caught:
            rv.load_review("not json", "the review data x")
        self.assertIn("the review data x is not JSON", str(caught.exception))
        with self.assertRaises(rv.VerdictError) as caught:
            rv.load_record(json.dumps(self.check(head="1")), "the check data y")
        self.assertIn("head must be a full 40-character sha", str(caught.exception))
        with self.assertRaises(rv.VerdictError) as caught:
            rv.load_any(json.dumps({"type": "report"}), "z")
        self.assertIn("is not a review or a check", str(caught.exception))

    def test_a_schema_1_check_is_refused_naming_the_migration(self):
        old = {"schema": 1, "type": "check", "head": SHA_B, "reviewed": SHA_A, "gate": None, "review": ["/r"], "findings": [], "new": [], "open": 0, "queued": 0}
        with self.assertRaises(rv.VerdictError) as caught:
            rv.load_any(json.dumps(old), "the old check")
        self.assertIn("relay check migrate", str(caught.exception))


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

    def relay(self, *args, cwd=None):
        return subprocess.run([sys.executable, RELAY, *args], capture_output=True, text=True, env={**os.environ, "RELAY_ROOT": ROOT}, cwd=cwd)

    def write_input(self, text, name="in.toml"):
        path = os.path.join(self.tmp, name)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        return path

    def record_review(self, findings=(IN_FINDING,), **top):
        fields = {"report": self.report, "reviewed": SHA_A, "base": "master"}
        fields.update(top)
        return self.relay("check", "record", "review", "--input", self.write_input(toml_input(fields, [("finding", f) for f in findings])))

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

    def test_every_prose_field_of_a_review_round_trips(self):
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

    def test_show_of_a_check_lists_findings_with_their_verdicts_and_sources(self):
        data = {"schema": 2, "type": "check", "head": SHA_B, "branch": "wt/x", "item": "redo-x", "gate": SHA_A + ".gate.log", "scope": [], "notes": ["gate red"],
                "findings": [record_finding("Q1", source="queue", verdict="MET", reason=["t.py:1"]),
                             record_finding("F1", verdict="NOT MET", reason=["no test", "see t.py"], source_id="F1"),
                             record_finding("N1", source="check", verdict="NOT MET", kind="inside", summary="fresh")]}
        path = os.path.join(self.tmp, "chk.json")
        with open(path, "w") as handle:
            json.dump(dict(data, worktree="/w"), handle)
        full = self.relay("check", "show", path).stdout
        # open: F1 (high, inside, not met) and N1 -> 2; Q1 is MET
        for line in ("Check of %s on wt/x" % SHA_B, "Item: redo-x", "Gate: %s.gate.log" % SHA_A, "Open: 2  Queued: 0", "Notes:", "  gate red", "Findings: 3",
                     "  Source: queue, since %s" % SHA_A[:12], "  Verdict: NOT MET", "    no test", "    see t.py", "lib/x.py:12: HIGH: N1 fresh"):
            self.assertIn(line + "\n", full)
        brief = self.relay("check", "show", "--brief", path).stdout.splitlines()
        self.assertEqual(brief, ["Check of %s: open 2, queued 0, gate %s" % (SHA_B[:12], SHA_A[:12]), "Q1 MET t.py:1", "F1 NOT MET no test", "N1 NOT MET t.py:5"])

    def test_show_refuses_what_is_not_a_report(self):
        path = os.path.join(self.tmp, "other.json")
        open(path, "w").write('{"type": "report"}')
        done = self.relay("check", "show", path)
        self.assertEqual(done.returncode, 1)
        self.assertIn("is not a review or a check", done.stderr)


class FlowWords(RecordBase):
    """A flow's own severity words are accepted: the finding keeps the word and stores its rank beside it."""

    # the sets named in the flows: roles/judge.md (default), openspec spec-reviewer ("BLOCKER = HIGH, FIX = MEDIUM, NIT = LOW"),
    # openspec spec-conformance (CRITICAL / WARNING / SUGGESTION, worked as high / medium / low in that order)
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

    def test_show_prints_the_words_under_the_finding(self):
        self.assertEqual(self.record_review().returncode, 0)
        self.assertEqual(self.owner("F1", ["not wrong, because it is by design"]).returncode, 0)
        data = self.load()
        date = data["owner"][0]["date"]
        shown = self.relay("check", "show", self.report).stdout
        self.assertIn("  Owner (%s) says not wrong:\n    not wrong, because it is by design\n" % date, shown)


class OwnerMoved(RecordBase):
    """Review F8: "the owner moved this finding to queue item <slug>" is data in the review JSON (an owner entry with `queue`),
    counted by the script, not a prompt line."""

    DESIGN = dict(IN_FINDING, id="F3", kind="design", severity="MEDIUM", summary="the design is wrong here")

    def setUp(self):
        super().setUp()
        self.repo = os.path.join(self.tmp, "proj")
        os.makedirs(os.path.join(self.repo, ".relay", "queue"))
        item = {"kind": "fix", "ip": 91, "time": 10, "found_at": "2026-10-23T08:00:00Z", "found_in": "test", "title": "Redo the part",
                "what": ["the part"], "why": ["it matters"], "failing_case": ["it fails"], "taken_at": None, "taken_by": None, "closed_at": None,
                "test": None, "dropped_at": None, "dropped_why": None}
        with open(os.path.join(self.repo, ".relay", "queue", "redo-x.json"), "w") as handle:
            json.dump(item, handle)
        env = {**os.environ, "GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@e.x", "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@e.x"}
        for args in (("init", "-q", "-b", "master"), ("add", "-A"), ("commit", "-q", "-m", "queue")):
            subprocess.run(["git", "-C", self.repo, *args], check=True, capture_output=True, env=env)
        self.assertEqual(self.record_review([IN_FINDING, self.DESIGN]).returncode, 0)

    def read_report(self):
        with open(self.report, encoding="utf-8") as handle:
            return handle.read()

    def move(self, slug="redo-x", fid="F3"):
        text = "words = '''the owner: put it in the queue, $HOME'''\nqueue = \"%s\"\n" % slug
        return self.relay("check", "owner", self.report, fid, "--input", self.write_input(text, "move.toml"), cwd=self.repo)

    def test_a_move_is_an_owner_entry_with_the_item_and_show_prints_it(self):
        done = self.move()
        self.assertEqual(done.returncode, 0, done.stderr)
        data = self.load()
        entry = data["owner"][0]
        self.assertEqual((entry["id"], entry["queue"], entry["words"]), ("F3", "redo-x", ["the owner: put it in the queue, $HOME"]))
        self.assertEqual(rv.review_errors(data), [])
        shown = self.relay("check", "show", self.report).stdout
        self.assertIn("  Owner (%s) moved to queue item redo-x:\n    the owner: put it in the queue, $HOME\n" % entry["date"], shown)

    def test_a_slug_that_is_not_on_the_default_branch_is_refused_and_the_review_is_unchanged(self):
        before = self.read_report()
        done = self.move("redo-y")
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("queue item redo-y not found", done.stderr)
        self.assertEqual(self.read_report(), before)
        self.assertNotEqual(self.move("Bad Name").returncode, 0)       # a name that cannot be an item is refused the same way
        self.assertEqual(self.read_report(), before)

    def test_without_queue_the_entry_still_means_not_wrong(self):
        text = "words = '''by design'''\n"
        self.assertEqual(self.relay("check", "owner", self.report, "F1", "--input", self.write_input(text, "o.toml"), cwd=self.repo).returncode, 0)
        data = self.load()
        self.assertNotIn("queue", data["owner"][0])


class ReviewHandoff(RecordBase):
    """A review is recorded as a review record with the TOML input and the checker's `Check:` names that JSON (the delegate
    skill, step 7; the apply-review skill and its triage author are gone). The fixture runs the record step with no live agent."""

    SKILL = os.path.join(ROOT, "plugins", "delegate", "skills", "delegate", "SKILL.md")

    def test_a_triage_recorded_as_a_review_is_the_review_the_checker_names(self):
        triage = os.path.join(self.tmp, "triage.json")
        finding_in = dict(IN_FINDING, evidence=["screenshot: shots/home.png"], pass_cases=["a=2 gives 1 row"])
        fields = {"report": triage, "reviewed": SHA_A, "base": "master", "notes": ["Group A: lib/x.py (F1)", "For the owner: none"]}
        recorded = self.relay("check", "record", "review", "--input", self.write_input(toml_input(fields, [("finding", finding_in)]), "triage.toml"))
        self.assertEqual(recorded.returncode, 0, recorded.stderr)
        data = self.load("triage.json")
        self.assertEqual(data["type"], "review")
        self.assertEqual(data["notes"][0], "Group A: lib/x.py (F1)")

    def test_the_skill_hands_the_json_over_and_names_no_triage_markdown(self):
        with open(self.SKILL, encoding="utf-8") as handle:
            text = handle.read()
        self.assertNotIn("review/triage.md", text)
        self.assertIn("relay check record check", text)
        checks = [l for l in text.splitlines() if l.startswith("> Check:")]
        self.assertEqual(len(checks), 1)
        self.assertIn("Report: `<path>.json`", checks[0])


class GitCouldNotAnswer(unittest.TestCase):
    """A git that times out is reported as its own error, not as a detached HEAD."""

    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="relay-verdict-git-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        subprocess.run(["git", "init", "-q", "-b", "wt/x", self.tmp], check=True)
        # a fake git that sleeps far past the lowered limit; the sleep is killed by the timeout
        fake = os.path.join(self.tmp, "fakebin")
        os.mkdir(fake)
        with open(os.path.join(fake, "git"), "w", encoding="utf-8") as handle:
            handle.write("#!/bin/sh\nexec sleep 30\n")
        os.chmod(os.path.join(fake, "git"), 0o755)
        patcher = mock.patch.dict(os.environ, {"PATH": fake + os.pathsep + os.environ["PATH"]})
        patcher.start()
        self.addCleanup(patcher.stop)
        limit = mock.patch.object(relay_git, "TIMEOUT", 0.2)
        limit.start()
        self.addCleanup(limit.stop)

    def test_current_branch_strict_raises_when_git_times_out(self):
        with self.assertRaises(relay_git.GitError) as caught:
            relay_git.current_branch(self.tmp, strict=True)
        self.assertIn("git could not answer: git -C", str(caught.exception))

    def test_current_branch_default_still_answers_none(self):
        # the hooks that read it as a plain question keep their old answer
        self.assertIsNone(relay_git.current_branch(self.tmp))

    def test_the_verdict_says_git_could_not_answer_not_that_it_is_not_on_a_branch(self):
        with self.assertRaises(rv.VerdictError) as caught:
            rv.build_findings(self.tmp, "a" * 40, [])
        self.assertIn("git could not answer", str(caught.exception))
        self.assertNotIn("not on a branch", str(caught.exception))


class GitDiedOrFailed(unittest.TestCase):
    """A git killed by a signal or failing fatally is no answer; only `symbolic-ref -q` exit 1 is a detached HEAD."""

    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="relay-verdict-git-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.repo = os.path.join(self.tmp, "repo")
        self.git("init", "-q", "-b", "master", self.repo)
        self.git("-C", self.repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "one")
        self.git("-C", self.repo, "checkout", "-q", "-b", "wt/x")
        self.real = shutil.which("git")

    def git(self, *args):
        subprocess.run(["git", *args], check=True)

    def fake(self, body):
        fake = os.path.join(self.tmp, "fakebin")
        os.makedirs(fake, exist_ok=True)
        with open(os.path.join(fake, "git"), "w", encoding="utf-8") as handle:
            handle.write("#!/bin/sh\n" + body)
        os.chmod(os.path.join(fake, "git"), 0o755)
        patcher = mock.patch.dict(os.environ, {"PATH": fake + os.pathsep + os.environ["PATH"]})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_git_killed_by_a_signal_is_no_answer_not_a_detached_head(self):
        self.fake("kill -TERM $$\n")
        with self.assertRaises(relay_git.GitError) as caught:
            relay_git.current_branch(self.repo, strict=True)
        self.assertIn("killed by signal 15", str(caught.exception))
        with self.assertRaises(rv.VerdictError) as caught:
            rv.build_findings(self.repo, "a" * 40, [])
        self.assertIn("git could not answer", str(caught.exception))
        self.assertNotIn("not on a branch", str(caught.exception))

    def test_a_git_failing_fatally_is_no_answer(self):
        self.fake("exit 128\n")
        with self.assertRaises(relay_git.GitError) as caught:
            relay_git.current_branch(self.repo, strict=True)
        self.assertIn("exit 128", str(caught.exception))
        self.assertIn("git -C", str(caught.exception))

    def test_a_detached_head_is_none_and_a_branch_is_its_name(self):
        self.assertEqual(relay_git.current_branch(self.repo, strict=True), "wt/x")     # symbolic-ref gives the name
        self.git("-C", self.repo, "checkout", "-q", "--detach")
        self.assertIsNone(relay_git.current_branch(self.repo, strict=True))            # symbolic-ref -q exits 1: detached
        with self.assertRaises(rv.VerdictError) as caught:
            rv.build_findings(self.repo, "a" * 40, [])
        self.assertIn("not on a branch", str(caught.exception))

    def test_a_merge_base_that_fails_says_git_could_not_answer(self):
        # symbolic-ref and the rest answer through the real git; merge-base sleeps past the lowered limit
        self.fake('for a in "$@"; do [ "$a" = merge-base ] && exec sleep 30; done\nexec %s "$@"\n' % self.real)
        head = subprocess.run(["git", "-C", self.repo, "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
        import relay_inert
        # a branch inside this one is what lets build_findings go on to the merge-base without a review
        with mock.patch.object(relay_git, "TIMEOUT", 0.5), mock.patch.object(relay_inert, "absorbed", return_value={"b": head}):
            with self.assertRaises(rv.VerdictError) as caught:
                rv.build_findings(self.repo, head, [])
        self.assertIn("git could not answer", str(caught.exception))
        self.assertIn("merge-base", str(caught.exception))
        self.assertNotIn("no common commit", str(caught.exception))


class RebasedRecords(unittest.TestCase):
    """A rebase that leaves the branch's patch unchanged keeps the review and the check mark (queue item
    a-rebase-that-changes-nothing-voids-the-review); a rebase that changes the patch voids them."""

    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="relay-rebased-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.wt = os.path.join(self.tmp, "r")
        os.makedirs(self.wt)
        self.env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull, "GIT_AUTHOR_NAME": "t",
                    "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
        self.git("init", "-q", "-b", "master")
        self.commit("base.txt", "base\n")
        self.git("checkout", "-q", "-b", "wt/x")
        self.commit("lib_x.py", "x = 1\n")
        self.old = self.git("rev-parse", "HEAD")
        sys.path.insert(0, os.path.join(ROOT, "lib"))
        import relay_marks
        self.marks = relay_marks
        mark = {"schema": relay_marks.MARK_SCHEMA, "commit": self.old, "verdict": {"open": 0, "queued": 0},
                "check": self.old + ".check.json", "gate": None, "time": "2026-10-29T00:00:00Z"}
        relay_marks.put(self.wt, self.old, mark, {self.old + ".check.json": "{}\n"})
        self.review = os.path.join(self.tmp, "rev.json")
        rv.write_review(self.review, rv.review_data(self.old, "master", [finding()]))

    def git(self, *args):
        done = subprocess.run(["git", "-C", self.wt, *args], capture_output=True, text=True, env=self.env, check=True)
        return done.stdout.strip()

    def commit(self, name, text, branch=None):
        with open(os.path.join(self.wt, name), "w", encoding="utf-8") as handle:
            handle.write(text)
        self.git("add", name)
        self.git("commit", "-q", "-m", "add " + name)

    def main_moves(self):
        self.git("checkout", "-q", "master")
        self.commit("unrelated.txt", "u\n")
        self.git("checkout", "-q", "wt/x")

    def head(self):
        return self.git("rev-parse", "HEAD")

    def test_a_review_of_a_commit_a_clean_rebase_replaced_still_counts(self):
        # the rebase moves lib_x.py's commit onto the new master tip; its patch (add lib_x.py) is the same, so the
        # review of the old commit is a review of the new one: `since` is the new twin, not a refusal
        self.main_moves()
        self.git("rebase", "-q", "master")
        found = rv._review_findings(self.wt, self.head(), [self.review])
        self.assertEqual([f["source_id"] for f in found], ["F1"])
        self.assertNotEqual(found[0]["since"], self.old)
        self.assertEqual(self.git("show", found[0]["since"] + ":lib_x.py"), "x = 1")

    def rebase_changing_the_patch(self):
        """A rebase whose code commit also changed lib_x.py (x = 2); the mark commit is carried over as the rebase does."""
        self.main_moves()
        self.git("rebase", "-q", "master")
        self.git("reset", "-q", "--hard", "HEAD~1")        # the mark commit goes; the rebased code commit is the tip
        with open(os.path.join(self.wt, "lib_x.py"), "w", encoding="utf-8") as handle:
            handle.write("x = 2\n")
        self.git("commit", "-q", "-a", "--amend", "--no-edit")
        mark = {"schema": self.marks.MARK_SCHEMA, "commit": self.old, "verdict": {"open": 0, "queued": 0},
                "check": self.old + ".check.json", "gate": None, "time": "2026-10-29T00:00:00Z"}
        self.marks.put(self.wt, self.old, mark, {self.old + ".check.json": "{}\n"})

    def test_a_review_of_a_commit_a_rebase_with_a_changed_patch_replaced_is_refused(self):
        self.rebase_changing_the_patch()
        with self.assertRaises(rv.VerdictError) as caught:
            rv._review_findings(self.wt, self.head(), [self.review])
        self.assertIn("not in the history", str(caught.exception))

    def test_the_mark_of_a_commit_a_clean_rebase_replaced_is_read_at_the_new_commit(self):
        self.main_moves()
        self.git("rebase", "-q", "master")
        stored = dict(self.marks.marks(self.wt, "refs/heads/wt/x"))
        twin = self.head()      # the newest commit with the same patch (check files left out) is the rebased mark commit
        self.assertIn(twin, stored)
        self.assertEqual(stored[twin]["commit"], self.old)

    def test_the_mark_of_a_commit_a_rebase_with_a_changed_patch_replaced_is_not_carried(self):
        self.rebase_changing_the_patch()
        # only the old name: the rebased code commit's patch (x = 2) is not the one the mark checked (x = 1), so no twin
        self.assertEqual([c for c, _ in self.marks.marks(self.wt, "refs/heads/wt/x")], [self.old])


    def merge_step(self):
        sys.path.insert(0, HERE)
        from relay_testbase import load_hook
        hook = load_hook("merge_hook_for_rebased_test", os.path.join(ROOT, "plugins", "relay", "hooks", "merge.py"))
        self.git("checkout", "-q", "master")
        return hook, hook.step_mark(self.wt, "master", "wt/x")

    def test_the_merge_hook_takes_the_mark_after_a_clean_rebase_and_refuses_after_a_changed_patch(self):
        self.main_moves()
        self.git("rebase", "-q", "master")
        hook, mark = self.merge_step()
        self.assertEqual(self.git("rev-parse", "wt/x"), mark)          # the mark is read at the rebased commit
        self.git("checkout", "-q", "wt/x")
        self.git("reset", "-q", "--hard", "HEAD~1")
        self.rebase_changing_the_patch_from_here()
        with self.assertRaises(hook.Refused):
            hook.step_mark(self.wt, "master", "wt/x")

    def rebase_changing_the_patch_from_here(self):
        with open(os.path.join(self.wt, "lib_x.py"), "w", encoding="utf-8") as handle:
            handle.write("x = 2\n")
        self.git("commit", "-q", "-a", "--amend", "--no-edit")
        mark = {"schema": self.marks.MARK_SCHEMA, "commit": self.old, "verdict": {"open": 0, "queued": 0},
                "check": self.old + ".check.json", "gate": None, "time": "2026-10-29T00:00:00Z"}
        self.marks.put(self.wt, self.old, mark, {self.old + ".check.json": "{}\n"})


if __name__ == "__main__":
    unittest.main()

