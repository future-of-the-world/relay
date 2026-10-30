"""A decision made without the owner (design work-goes-on-while-the-owner-is-away, part A): the `decided` field of a finding,
the bound on what a checker may decide, the count it changes, the line that tells the owner, and the feature a scope cut's rest becomes.

Every test runs on scratch repositories in a temp dir; none touches the live queue, checks or handover."""
import json
import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "lib"))
sys.path.insert(0, HERE)

import relay_queue as rq  # noqa: E402
import relay_verdict as rv  # noqa: E402
import test_check_record as tcr  # noqa: E402
import test_queue as tq  # noqa: E402
import test_verdict as tv  # noqa: E402

RELAY = os.path.join(ROOT, "bin", "relay")
CUT = "principle 1, scope cut: name who sends the signal (owner can reverse)"


class Schema(unittest.TestCase):
    def check(self, **finding):
        fields = dict(verdict="OUTSIDE", severity="MEDIUM", rank="medium")
        fields.update(finding)
        return {"schema": 2, "type": "check", "head": tv.SHA_B, "branch": "wt/x", "item": None, "gate": None, "worktree": "/w",
                "findings": [tv.record_finding("F1", **fields)]}

    def test_a_decided_medium_outside_is_not_open_and_is_counted_outside(self):
        # F1 is MEDIUM inside and not MET, so it is open (1) and outside (0) -- until the checker decides it as a scope cut.
        plain = self.check()
        self.assertEqual((rv.open_of(plain), rv.outside_of(plain)), (1, 0))
        cut = self.check(decided=CUT)
        self.assertEqual(rv.record_errors(cut), [])
        self.assertEqual((rv.open_of(cut), rv.outside_of(cut)), (0, 1))

    def test_the_guard_refuses_a_high_a_question_and_a_design_finding(self):
        high = rv.record_errors(self.check(decided=CUT, severity="HIGH", rank="high"))
        self.assertTrue(any("decided is refused on rank high" in e for e in high), high)
        for kind in ("question", "design"):
            errors = rv.record_errors(self.check(decided=CUT, kind=kind))
            self.assertTrue(any("decided is refused on kind " + kind in e for e in errors), errors)

    def test_a_decided_that_is_empty_is_refused_by_name(self):
        errors = rv.record_errors(self.check(decided="  "))
        self.assertTrue(any("decided must be a one-line text" in e for e in errors), errors)

    def test_f3_a_merge_finding_cannot_be_decided_as_a_scope_cut(self):
        errors = rv.record_errors(self.check(decided=CUT, source="merge"))
        self.assertTrue(any("decided is refused on a merge finding" in e for e in errors), errors)
        self.assertEqual(rv.record_errors(self.check(verdict="MET", source="merge")), [])        # MET without decided: recorded
        self.assertEqual(rv.record_errors(self.check(decided=CUT, source="a.json")), [])         # a review finding: kept

    def test_decided_lines_print_one_line_for_each_decided_finding(self):
        data = self.check(decided=CUT)
        data["findings"].append(tv.record_finding("F2", verdict="NOT MET"))
        self.assertEqual(rv.decided_lines(data), ["decided: F1 " + CUT])
        self.assertEqual(rv.decided_lines(self.check()), [])
        self.assertIn("  decided: " + CUT, rv.render_check(self.check(decided=CUT)))


class ReviewInput(tv.RecordBase):
    def test_a_review_finding_keeps_decided_and_a_blank_one_is_refused(self):
        done = self.record_review([dict(tv.IN_FINDING, decided="principle 3: derived, not stored (owner can reverse)")])
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.load()["findings"][0]["decided"], "principle 3: derived, not stored (owner can reverse)")
        bad = self.record_review([dict(tv.IN_FINDING, decided=" ")])
        self.assertNotEqual(bad.returncode, 0)
        self.assertIn("decided", bad.stderr)


class Record(tcr.Flow):
    def toml_with(self, statuses, reviews):
        """The check input with a [[status]] for each (id, verdict, decided or None); returns (input path, report path)."""
        self.tomls += 1
        report = os.path.join(self.tmp, "rec%d.json" % self.tomls)
        lines = ["report = '%s'" % report, "head = '%s'" % self.head(), "worktree = '%s'" % self.wa, "gate = '%s'" % self.gate(),
                 "review = [%s]" % ", ".join("'%s'" % r for r in reviews)]
        for fid, verdict, decided in statuses:
            lines += ["[[status]]", "id = '%s'" % fid, "verdict = '%s'" % verdict, "reason = 'checked'"]
            if decided:
                lines.append("decided = '%s'" % decided)
        path = os.path.join(self.tmp, "input%d.toml" % self.tomls)
        with open(path, "w") as handle:
            handle.write("\n".join(lines) + "\n")
        return path, report

    def setup_review(self, **over):
        self.fix()
        return self.review("a.json", self.took, [dict(tcr.review_finding(1, severity="MEDIUM"), **over)])

    def run_record(self, statuses, reviews):
        path, report = self.toml_with(statuses, reviews)
        out = subprocess.run([sys.executable, RELAY, "check", "record", "check", "--input", path], capture_output=True, text=True,
                             env={**os.environ, "RELAY_ROOT": ROOT})
        return out, report

    def test_a_medium_scope_cut_decided_by_the_checker_is_recorded_and_the_owner_is_told(self):
        review = self.setup_review()
        out, report = self.run_record([("Q1", "MET", None), ("F1", "OUTSIDE", CUT)], [review])
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("(open 0, queued 0)", out.stdout)
        self.assertIn("decided: F1 " + CUT, out.stdout.splitlines())
        with open(report) as handle:
            record = rv.load_record(handle.read())
        self.assertEqual((rv.open_of(record), rv.outside_of(record)), (0, 1))

    def test_no_decision_means_no_decided_line(self):
        review = self.setup_review()
        out, _ = self.run_record([("Q1", "MET", None), ("F1", "MET", None)], [review])
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertNotIn("decided:", out.stdout)

    def test_an_outside_without_decided_stays_open(self):
        # today's behaviour kept: a MEDIUM inside finding the checker calls OUTSIDE with no `decided` and no owner entry is still open
        review = self.setup_review()
        out, report = self.run_record([("Q1", "MET", None), ("F1", "OUTSIDE", None)], [review])
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("(open 1, queued 0)", out.stdout)

    def test_f1_a_review_time_decided_is_not_the_checkers_scope_cut(self):
        # the reviewer's decided (a principle's answer) rides on the review finding; the checker's plain OUTSIDE must stay open
        review = self.setup_review(decided="principle 3: derived, not stored (owner can reverse)")
        out, report = self.run_record([("Q1", "MET", None), ("F1", "OUTSIDE", None)], [review])
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("(open 1, queued 0)", out.stdout)
        self.assertNotIn("decided:", out.stdout)

    def test_f1_a_review_time_decided_on_a_high_finding_does_not_block_a_plain_outside(self):
        review = self.setup_review(severity="HIGH", rank="high", decided="principle 1: check again (owner can reverse)")
        out, _ = self.run_record([("Q1", "MET", None), ("F1", "OUTSIDE", None)], [review])
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("(open 1, queued 0)", out.stdout)

    def test_f1_a_review_time_decided_still_prints_when_the_finding_is_met(self):
        review = self.setup_review(decided="principle 3: derived, not stored (owner can reverse)")
        out, _ = self.run_record([("Q1", "MET", None), ("F1", "MET", None)], [review])
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("(open 0, queued 0)", out.stdout)
        self.assertIn("decided: F1 principle 3: derived, not stored (owner can reverse)", out.stdout.splitlines())

    def test_a_high_finding_cannot_be_decided(self):
        review = self.setup_review(severity="HIGH", rank="high")
        out, report = self.run_record([("Q1", "MET", None), ("F1", "OUTSIDE", CUT)], [review])
        self.assertNotEqual(out.returncode, 0)
        self.assertIn("decided is refused on rank high", out.stderr)
        self.assertFalse(os.path.exists(report))

    def test_a_question_finding_cannot_be_decided(self):
        review = self.setup_review(kind="question")
        out, report = self.run_record([("Q1", "MET", None), ("F1", "OUTSIDE", CUT)], [review])
        self.assertNotEqual(out.returncode, 0)
        self.assertIn("decided is refused on kind question", out.stderr)
        self.assertFalse(os.path.exists(report))

    def test_decided_goes_only_with_the_verdict_outside(self):
        review = self.setup_review()
        for verdict in ("MET", "GAP", "NOT MET"):
            out, report = self.run_record([("Q1", "MET", None), ("F1", verdict, CUT)], [review])
            self.assertNotEqual(out.returncode, 0, verdict)
            self.assertIn("decided", out.stderr)
            self.assertIn("only for the verdict OUTSIDE", out.stderr)
            self.assertFalse(os.path.exists(report))


class AddFrom(tq.Base):
    def report(self, findings, name="rev"):
        path = os.path.join(self.tmp, name + ".json")
        with open(path, "w") as handle:
            json.dump({"schema": 1, "type": "review", "reviewed": "a" * 40, "base": "master", "findings": findings}, handle)
        return path

    def outside(self, **over):
        base = {"id": "F1", "path": "lib/sender.py", "line": 7, "severity": "MEDIUM", "rank": "medium", "kind": "outside",
                "summary": "the sender of the signal is not named", "failing_case": ["kill -USR1 shows no sender"]}
        base.update(over)
        return base

    def test_a_decided_scope_cut_is_queued_as_a_feature_of_the_rest_at_the_given_ip_marked_agent_chosen(self):
        report = self.report([self.outside(decided="principle 9, scope cut: the Linux variant (owner can reverse)")])
        message = rq.add_from(self.main, report, "F1", why="from the check", minutes=20, ip=90, **tq.QUIET)
        self.assertIn("(feature, ip 90)", message)
        item = self.item("the-linux-variant")
        self.assertEqual((item["kind"], item["ip"]), ("feature", 90))
        self.assertEqual(item["what"], ["the Linux variant"])           # the rest, without the closing "(owner can reverse)"
        self.assertTrue(any("agent-chosen" in line for line in item["why"]), item["why"])
        self.assertTrue(any("principle 9, scope cut" in line for line in item["why"]), item["why"])

    def test_a_checkers_outside_verdict_with_decided_is_the_same_scope_cut(self):
        finding = dict(self.outside(kind="inside"), source="a.json", since="a" * 40, verdict="OUTSIDE", reason=["x"],
                       decided="principle 1, scope cut: name the sender")
        record = {"schema": 2, "type": "check", "head": "b" * 40, "branch": "wt/x", "item": None, "gate": None, "findings": [finding]}
        path = os.path.join(self.tmp, "chk.json")
        with open(path, "w") as handle:
            json.dump(record, handle)
        rq.add_from(self.main, path, "F1", why="w", minutes=5, ip=70, **tq.QUIET)
        self.assertEqual(self.item("name-the-sender")["kind"], "feature")

    def test_any_other_finding_is_still_a_fix(self):
        # no `decided`; and a `decided` that is a principle's answer, not a scope cut, also stays a fix
        plain = self.outside(id="F1")
        principled = self.outside(id="F2", summary="the other signal is not named", decided="principle 3: derived, not stored")
        report = self.report([plain, principled])
        rq.add_from(self.main, report, "F1", why="w", minutes=5, **tq.QUIET)
        rq.add_from(self.main, report, "F2", why="w", minutes=5, **tq.QUIET)
        self.assertEqual(self.item("the-sender-of-the-signal-is-not-named")["kind"], "fix")
        self.assertEqual(self.item("the-other-signal-is-not-named")["kind"], "fix")

    def test_a_filed_rest_at_ip_70_ranks_below_a_feature_at_ip_96(self):
        self.write_commit(self.main, {".relay/queue/big.json": tq.feature_item("Big", ip=96)}, "a feature")
        report = self.report([self.outside(decided="principle 9, scope cut: the Linux variant")])
        rq.add_from(self.main, report, "F1", why="w", minutes=5, ip=70, **tq.QUIET)
        items = rq.ordered([i for i in (self.item("big"), self.item("the-linux-variant")) if i])
        self.assertEqual([i["slug"] for i in items], ["big", "the-linux-variant"])


if __name__ == "__main__":
    unittest.main()
