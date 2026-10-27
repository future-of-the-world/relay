"""One check record per change, read by one function (design: the check records in one order, `relay_verdict.load_record`
is the one reader, `relay_queue.close_refusal` the one rule for what may change after the check).

Every test runs on scratch repositories in a temp dir (tests/test_queue.py's Base). The tests use the real pipeline: a review
JSON, the TOML input of `relay check record check`, the hook's `write_mark`, `relay queue done` and the merge guard's steps.
"""
import importlib.util
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "lib"))
sys.path.insert(0, HERE)

import relay_marks as rm  # noqa: E402
from relay_testbase import load_hook as _load_hook  # noqa: E402
import relay_queue as rq  # noqa: E402
import relay_verdict as rv  # noqa: E402
import test_queue as tq  # noqa: E402

git, QUIET = tq.git, tq.QUIET
TEST_FILE = "tests/test_job.py"
TEST_NAME = TEST_FILE + "::TestJob::test_job_works"
TEST_SOURCE = "class TestJob:\n    def test_job_works(self):\n        pass\n"
SPREAD = "one\n" + "pad\n" * 6 + "end\n"      # edits to the first and the last line merge without a conflict


def load_hook(name, file):
    return _load_hook(name, os.path.join(ROOT, "plugins", "core", "hooks", file))


check_mark = load_hook("check_mark_for_record_test", "check-mark.py")
merge_hook = load_hook("merge_for_record_test", "merge.py")


def review_finding(number, path="lib/y.py", kind="inside", severity="HIGH"):
    rank = rv.WORDS[severity]
    return {"id": "F%d" % number, "path": path, "line": 1, "severity": severity, "rank": rank, "kind": kind,
            "summary": "finding %d is wrong" % number, "failing_case": ["case %d fails" % number]}


def met(*ids):
    return {i: ("MET", "checked") for i in ids}


class Flow(tq.Base):
    """A main repository with the fix item `job`, a worktree wt/a that took it, and helpers for the steps after."""

    def setUp(self):
        super().setUp()
        self.write_commit(self.main, {".relay/queue/job.json": tq.fix_item("Job", ip=60, failing="line 1\nline 2"),
                                      "lib/y.py": SPREAD, "lib/z.py": SPREAD, "lib/w.py": SPREAD}, "seed")
        self.wa = self.worktree("a")
        rq.take(self.wa, "job", **QUIET)
        self.took = git(self.wa, "rev-parse", "HEAD")
        self.tomls = 0

    # ---- steps
    def head(self, wt=None):
        return git(wt or self.wa, "rev-parse", "HEAD")

    def commit(self, files, wt=None, message="change"):
        self.write_commit(wt or self.wa, files, message)
        return self.head(wt)

    def fix(self):
        return self.commit({TEST_FILE: TEST_SOURCE, "lib/y.py": SPREAD.replace("one", "ONE")}, message="the fix and its test")

    def master_changes(self, files):
        self.write_commit(self.main, files, "master moves")

    def take_master(self):
        git(self.wa, "merge", "-q", "--no-edit", "master")
        return self.head()

    def review(self, name, reviewed, findings, owner=None):
        path = os.path.join(self.tmp, name)
        data = rv.review_data(reviewed, "master", findings)
        if owner:
            data["owner"] = owner
        rv.write_review(path, data)
        return path

    def gate(self, exit_code=0, head=None):
        """A gate log for `head` (default HEAD), committed (it is an inert file); returns its file name."""
        sha = head or self.head()
        name = "%s.gate.log" % sha
        self.commit({".relay/checks/" + name: "head %s\nexit %d\n" % (sha, exit_code)}, message="gate")
        return name

    def toml(self, head, reviews, verdicts, gate="none", extra="", report=None):
        self.tomls += 1
        report = report or os.path.join(self.tmp, "record%d.json" % self.tomls)
        lines = ["report = '%s'" % report, "head = '%s'" % head, "worktree = '%s'" % self.wa, "gate = '%s'" % gate,
                 "review = [%s]" % ", ".join("'%s'" % r for r in reviews), extra]
        for fid, (verdict, reason) in verdicts.items():
            lines += ["[[status]]", "id = '%s'" % fid, "verdict = '%s'" % verdict, "reason = '%s'" % reason]
        path = os.path.join(self.tmp, "input%d.toml" % self.tomls)
        with open(path, "w") as handle:
            handle.write("\n".join(lines) + "\n")
        return path, report

    def record(self, reviews, verdicts, gate="auto", head=None, extra=""):
        """Record a check as `relay check record check` does (gate "auto": a green gate log for HEAD is made first); returns the record as a dict."""
        if gate == "auto":
            gate = self.gate()
        path, report = self.toml(head or self.head(), reviews, verdicts, gate, extra)
        rv.record_check(path)
        with open(report) as handle:
            return rv.load_record(handle.read())

    def mark(self, record):
        """Commit the mark and the stored record as the check hook does; returns the commit of the checked head."""
        check_mark.write_mark(self.wa, record)
        return record["head"]

    def checked(self, reviews, verdicts, gate="auto", extra=""):
        record = self.record(reviews, verdicts, gate, extra=extra)
        self.mark(record)
        return record

    def flow_to_check(self):
        """take (done in setUp), fix, one review, gate, one check with every verdict MET; returns (record, review path)."""
        self.fix()
        review = self.review("a.json", self.took, [review_finding(1), review_finding(2), review_finding(3)])
        gate = self.gate()
        record = self.checked([review], met("Q1", "F1", "F2", "F3"), gate)
        return record, review


class TestRecordOrder(Flow):
    def test_t1_the_item_and_the_reviews_findings_are_one_record_stated_at_their_own_commits(self):
        # Case 1: the item's problem (Q1, stated when it was taken) and the whole-change review (F1-F3, stated at a later
        # commit) were two reviews and the second was refused. Now they are the findings of one record, in this order.
        record, review = self.flow_to_check()
        self.assertEqual([f["id"] for f in record["findings"]], ["Q1", "F1", "F2", "F3"])
        self.assertEqual(record["item"], "job")
        q1, f1 = record["findings"][0], record["findings"][1]
        self.assertEqual((q1["source"], q1["since"], q1["summary"]), ("queue", self.took, "Job"))
        self.assertEqual((f1["source"], f1["source_id"], f1["since"]), ("a.json", "F1", self.took))
        # the take commit on master is where the item became taken; the review is of the commit the worktree was at
        self.assertEqual(q1["since"], git(self.main, "log", "-1", "--format=%H", "--", ".relay/queue/job.json"))
        self.assertEqual((rv.open_of(record), rv.queued_of(record)), (0, 0))

    def test_t1_a_review_of_a_later_commit_than_the_take_is_not_a_second_set(self):
        self.fix()
        later = self.head()
        self.commit({"lib/w.py": SPREAD.replace("one", "uno")})
        review = self.review("late.json", later, [review_finding(1)])
        record = self.record([review], met("Q1", "F1"))
        self.assertEqual([(f["id"], f["since"]) for f in record["findings"]], [("Q1", self.took), ("F1", later)])

    def test_t6_findings_of_many_review_files_are_numbered_in_order_and_keep_their_source(self):
        self.fix()
        a = self.review("a.json", self.took, [review_finding(1), review_finding(2), review_finding(3)])
        b = self.review("b.json", self.took, [review_finding(1, path="lib/w.py"), review_finding(2, path="lib/z.py")])
        record = self.record([a, b], met("Q1", "F1", "F2", "F3", "F4", "F5"))
        got = [(f["id"], f["source"], f["source_id"]) for f in record["findings"] if f["id"].startswith("F")]
        self.assertEqual(got, [("F1", "a.json", "F1"), ("F2", "a.json", "F2"), ("F3", "a.json", "F3"),
                               ("F4", "b.json", "F1"), ("F5", "b.json", "F2")])
        self.assertEqual(record["findings"][4]["path"], "lib/w.py")      # F4 is b.json's F1

    def test_t6_a_duplicate_id_inside_one_review_file_is_refused(self):
        path = os.path.join(self.tmp, "dup.json")
        data = rv.review_data(self.took, "master", [review_finding(1), review_finding(1)])
        with open(path, "w") as handle:
            json.dump(data, handle)
        self.fix()
        toml, _ = self.toml(self.head(), [path], met("Q1", "F1"))
        with self.assertRaises(rv.VerdictError) as ctx:
            rv.record_check(toml)
        self.assertIn("used twice", str(ctx.exception))

    def test_a_missing_verdict_and_a_verdict_for_an_unknown_id_are_refused_and_nothing_is_written(self):
        self.fix()
        review = self.review("a.json", self.took, [review_finding(1)])
        for verdicts, expect in ((met("Q1"), "no verdict for F1"), (met("Q1", "F1", "F9"), "F9 is not a finding of this check")):
            toml, report = self.toml(self.head(), [review], verdicts)
            with self.assertRaises(rv.VerdictError) as ctx:
                rv.record_check(toml)
            self.assertIn(expect, str(ctx.exception))
            self.assertFalse(os.path.exists(report))

    def test_the_input_does_not_take_the_counts_open_and_queued(self):
        # the counts are derived from the findings: an `open = 0` typed by the checker is an unknown key
        self.fix()
        review = self.review("a.json", self.took, [review_finding(1)])
        toml, _ = self.toml(self.head(), [review], met("Q1", "F1"), extra="open = 0")
        with self.assertRaises(rv.VerdictError) as ctx:
            rv.record_check(toml)
        self.assertIn("unknown key `open`", str(ctx.exception))

    def test_check_findings_lists_the_ids_the_record_will_use(self):
        self.fix()
        a = self.review("a.json", self.took, [review_finding(1)])
        b = self.review("b.json", self.took, [review_finding(1, path="lib/w.py")])
        lines = rv.finding_list(self.wa, [a, b])
        self.assertEqual([l.split(" ")[0] for l in lines[2:]], ["Q1", "F1", "F2"])
        self.assertIn("Item: job", lines)


class TestCounts(Flow):
    def test_t8_an_owner_word_answers_a_finding_and_a_move_to_a_queue_item_is_counted_queued(self):
        self.fix()
        owner = [{"id": "F1", "words": ["not wrong"], "date": "2026-10-24"},
                 {"id": "F2", "words": ["later"], "date": "2026-10-24", "queue": "job"}]
        review = self.review("a.json", self.took, [review_finding(1), review_finding(2), review_finding(3)], owner)
        wrong = {"Q1": ("MET", "x"), "F1": ("NOT MET", "x"), "F2": ("QUEUED", "x"), "F3": ("NOT MET", "x")}
        record = self.record([review], wrong)
        by_id = {f["id"]: f for f in record["findings"]}
        self.assertEqual(by_id["F1"]["owner"][0]["words"], ["not wrong"])
        # F1 owner word and F2 moved: only F3 is wrong and unanswered; one finding is queued
        self.assertEqual((rv.open_of(record), rv.queued_of(record)), (1, 1))

    def test_t8_an_owner_word_given_on_the_second_review_file_attaches_to_its_renumbered_finding(self):
        self.fix()
        a = self.review("a.json", self.took, [review_finding(1)])
        b = self.review("b.json", self.took, [review_finding(1, path="lib/w.py")], [{"id": "F1", "words": ["fine"], "date": "2026-10-24"}])
        record = self.record([a, b], {"Q1": ("MET", "x"), "F1": ("NOT MET", "x"), "F2": ("NOT MET", "x")})
        self.assertEqual([(f["id"], bool(f.get("owner"))) for f in record["findings"]][1:], [("F1", False), ("F2", True)])
        self.assertEqual(rv.open_of(record), 1)

    def test_only_high_and_medium_findings_inside_the_change_are_open(self):
        self.fix()
        findings = [review_finding(1, severity="LOW"), review_finding(2, kind="outside"), review_finding(3, severity="MEDIUM"), review_finding(4)]
        review = self.review("a.json", self.took, findings)
        wrong = {i: ("NOT MET", "x") for i in ("F1", "F2", "F3", "F4")}
        wrong["Q1"] = ("MET", "x")
        record = self.record([review], wrong)
        self.assertEqual(rv.open_of(record), 2)                      # F3 (medium) and F4 (high); F1 is low, F2 is outside
        self.assertEqual(rv.outside_of(record), 1)

    def test_a_red_gate_counts_as_open_through_a_finding_of_the_check(self):
        self.fix()
        review = self.review("a.json", self.took, [review_finding(1)])
        gate = self.gate(exit_code=1)
        record = self.record([review], met("Q1", "F1"), gate)
        n1 = record["findings"][-1]
        self.assertEqual((n1["id"], n1["source"], n1["verdict"], n1["rank"]), ("N1", "check", "NOT MET", "high"))
        self.assertIn("red", n1["summary"])
        self.assertEqual(rv.open_of(record), 1)

    def test_a_gate_log_for_other_code_a_missing_log_and_no_gate_are_findings_of_the_check(self):
        self.fix()
        review = self.review("a.json", self.took, [review_finding(1)])
        old = self.gate()
        self.commit({"lib/w.py": SPREAD.replace("one", "two")}, message="code after the gate")
        stale = self.record([review], met("Q1", "F1"), old)
        self.assertIn("other code", stale["findings"][-1]["summary"])
        missing = self.record([review], met("Q1", "F1"), "%s.gate.log" % ("a" * 40))
        self.assertIn("missing", missing["findings"][-1]["summary"])
        self.assertIsNone(missing["gate"])
        none = self.record([review], met("Q1", "F1"), "none")
        self.assertIn("no gate result", none["findings"][-1]["summary"])
        for record in (stale, missing, none):
            self.assertEqual(rv.open_of(record), 1)

    def test_a_new_problem_of_the_checker_gets_the_next_n_id(self):
        self.fix()
        review = self.review("a.json", self.took, [review_finding(1)])
        extra = ("[[new]]\npath = 'lib/w.py'\nline = 3\nseverity = 'MEDIUM'\nkind = 'inside'\nsummary = 'w is wrong'\n"
                 "failing_case = '''\nw fails\n'''\n")
        record = self.record([review], met("Q1", "F1"), extra=extra)
        n1 = record["findings"][-1]
        self.assertEqual((n1["id"], n1["since"], n1["verdict"], n1["source"]), ("N1", self.head(), "NOT MET", "check"))
        self.assertEqual(rv.open_of(record), 1)


class TestMergeFindings(Flow):
    """M findings: a file the branch changed that a merge of the default branch changed after the last review or check."""

    def start(self):
        """The fix changes lib/y.py; a review is of the take commit."""
        self.fix()
        self.commit({"lib/w.py": SPREAD.replace("one", "uno")}, message="a file only the fixer changes")
        return self.review("a.json", self.took, [review_finding(1)])

    def m_of(self, review):
        _, _, found = rv.build_findings(self.wa, self.head(), [review])
        return [(f["id"], f["path"], f["since"]) for f in found if f["id"].startswith("M")]

    def test_t7_a_file_the_branch_and_a_later_merge_both_changed_is_an_m_finding_at_the_merge(self):
        review = self.start()
        self.master_changes({"lib/y.py": SPREAD.replace("end", "END"), "lib/z.py": SPREAD.replace("end", "END")})
        merge = self.take_master()
        # y.py: the branch changed it and the merge brought master's change. z.py: only master changed it. w.py: only the fixer did.
        self.assertEqual(self.m_of(review), [("M1", "lib/y.py", merge)])

    def test_t7_a_merge_before_the_review_is_not_m(self):
        self.start()
        self.master_changes({"lib/y.py": SPREAD.replace("end", "END")})
        merged = self.take_master()
        review = self.review("late.json", merged, [review_finding(1)])
        self.assertEqual(self.m_of(review), [])

    def test_t7_a_merge_before_the_last_mark_is_not_m_and_a_merge_after_it_is(self):
        review = self.start()
        self.master_changes({"lib/y.py": SPREAD.replace("end", "END")})
        first = self.take_master()
        gate = self.gate()
        record = self.checked([review], met("Q1", "F1", "M1"), gate)
        self.assertEqual([f["id"] for f in record["findings"] if f["id"] == "M1"], ["M1"])          # judged in this check
        self.assertEqual(self.m_of(review), [])                       # the mark came after that merge
        self.master_changes({"lib/y.py": SPREAD.replace("end", "END").replace("pad\npad\nEND", "padded\npad\nEND")})
        second = self.take_master()
        self.assertEqual(self.m_of(review), [("M1", "lib/y.py", second)])
        self.assertNotEqual(first, second)

    def test_t7_a_file_only_the_fixer_changed_after_the_review_is_not_m(self):
        review = self.start()
        self.commit({"lib/y.py": SPREAD.replace("one", "ONE").replace("pad", "pod", 1)}, message="the fixer changes y.py again")
        self.assertEqual(self.m_of(review), [])


class TestOneFunction(Flow):
    """What may change after the check is one function, tested from both callers (`done` and the merge guard)."""

    def after_check(self):
        self.flow_to_check()
        return self.head()

    def test_t3_a_handover_commit_after_the_check_is_accepted_by_done_the_guard_and_the_stale_rule(self):
        # Case 3: `done` refused a commit of docs/handover.md after the check while the gate treated it as inert.
        self.after_check()
        self.commit({"docs/handover.md": "state\n"}, message="handover")
        self.assertIn("closed job", rq.done(self.wa, "job", TEST_NAME))
        self.assertIsNone(rq.close_refusal(self.wa, "HEAD", "job", TEST_NAME))
        self.assertEqual(merge_hook.step_mark(self.main, "master", "wt/a"), self.mark_commit())

    def mark_commit(self):
        return next(c for c, _ in rm.marks(self.wa, "HEAD"))

    def test_t3_a_code_commit_after_the_check_is_refused_by_done_the_guard_and_the_stale_rule(self):
        self.after_check()
        self.commit({"bin/ci": "echo changed\n"}, message="code after the check")
        reason = rq.close_refusal(self.wa, "HEAD", "job", TEST_NAME)
        self.assertIn("bin/ci changed", reason)
        with self.assertRaises(rq.Refused):
            rq.done(self.wa, "job", TEST_NAME)
        with self.assertRaises(merge_hook.Refused) as ctx:
            merge_hook.step_mark(self.main, "master", "wt/a")
        self.assertIn("bin/ci", str(ctx.exception))

    def test_t2_done_and_the_guard_judge_a_test_name_by_the_same_function(self):
        self.after_check()
        wrong = TEST_FILE + "::TestJob::test_job"                       # only a part of the name
        self.assertIn("does not hold a test named test_job", rq.close_refusal(self.wa, "HEAD", "job", wrong))
        with self.assertRaises(rq.Refused):
            rq.done(self.wa, "job", wrong)
        # the name written as file::Class::function is the same test to both (the last part is looked up)
        rq.done(self.wa, "job", TEST_FILE + "::TestJob::test_job_works")
        self.assertIsNone(merge_hook.step_queue(self.main, "master", "wt/a"))
        self.assertIsNone(rq.close_refusal(self.wa, "HEAD", "job", TEST_FILE + "::TestJob::test_job_works"))

    def test_the_merge_guard_refuses_a_closed_item_whose_check_is_of_another_item_or_says_q1_is_not_met(self):
        self.fix()
        review = self.review("a.json", self.took, [review_finding(1)])
        self.checked([review], {"Q1": ("NOT MET", "the test passes without the fix"), "F1": ("MET", "x")}, self.gate())
        self.assertIn("says Q1 NOT MET", rq.close_refusal(self.wa, "HEAD", "job", TEST_NAME))
        with self.assertRaises(rq.Refused):
            rq.done(self.wa, "job", TEST_NAME)

    def test_no_mark_means_no_close(self):
        self.fix()
        self.assertIn("no check of this fix", rq.close_refusal(self.wa, "HEAD", "job", TEST_NAME))

    def test_a_feature_item_needs_only_its_test(self):
        self.write_commit(self.main, {".relay/queue/feat.json": tq.feature_item("Feat")}, "a feature")
        git(self.wa, "merge", "-q", "--no-edit", "master")
        self.commit({TEST_FILE: TEST_SOURCE})
        self.assertIsNone(rq.close_refusal(self.wa, "HEAD", "feat", TEST_NAME))

    def test_a_check_of_another_item_does_not_close_this_one(self):
        self.after_check()
        self.master_changes({".relay/queue/other.json": tq.fix_item("Other", ip=50)})
        self.take_master()
        reason = rq.close_refusal(self.wa, "HEAD", "other", TEST_NAME)
        self.assertIn("is of job, not of 'other'", reason)


class TestSchema(Flow):
    def test_a_schema_1_check_is_refused_with_a_line_that_names_the_migration(self):
        old = json.dumps({"schema": 1, "type": "check", "head": "a" * 40, "reviewed": "b" * 40, "gate": None, "review": ["r"],
                          "findings": [], "new": [], "open": 0, "queued": 0})
        with self.assertRaises(rv.VerdictError) as ctx:
            rv.load_record(old, "the old check", stored=True)
        self.assertIn("relay check migrate", str(ctx.exception))

    def test_the_mark_holds_the_counts_and_the_record_name_only(self):
        record, _ = self.flow_to_check()
        mark = json.loads(git(self.wa, "show", "HEAD:.relay/checks/%s.json" % record["head"]))
        self.assertEqual(sorted(mark), ["check", "commit", "gate", "schema", "time", "verdict"])
        self.assertEqual(mark["verdict"], {"open": 0, "queued": 0})
        self.assertEqual(mark["check"], record["head"] + ".check.json")
        stored = rv.load_record(git(self.wa, "show", "HEAD:.relay/checks/" + mark["check"]), stored=True)
        self.assertNotIn("worktree", stored)

    def test_check_show_renders_the_record(self):
        record, _ = self.flow_to_check()
        text = rv.render_any(json.dumps(record), what="record")
        self.assertIn("Q1", text)
        self.assertIn("Open: 0  Queued: 0", text)
        self.assertIn("F3 MET", rv.brief_check(record))

    def test_t10_a_finding_of_the_checks_own_can_be_queued_from_the_record(self):
        self.fix()
        review = self.review("a.json", self.took, [review_finding(1)])
        gate = self.gate(exit_code=1)
        record = self.record([review], met("Q1", "F1"), gate)
        report = os.path.join(self.tmp, "record1.json")
        found = rq.find_finding(report, "N1")
        self.assertEqual(found["id"], "N1")
        self.assertEqual(rq.find_finding(report, "Q1")["summary"], record["findings"][0]["summary"])


class TestOnePerBranch(Flow):
    def test_t11_a_second_fix_item_on_a_branch_that_holds_one_is_refused_open_or_closed(self):
        self.write_commit(self.main, {".relay/queue/second.json": tq.fix_item("Second", ip=50)}, "another fix")
        with self.assertRaises(rq.Refused) as ctx:
            rq.take(self.wa, "second", **QUIET)
        self.assertIn("already holds the fix item 'job' (open on it)", str(ctx.exception))
        self.assertEqual(self.item("second")["state"], "open")
        self.flow_to_check()
        rq.done(self.wa, "job", TEST_NAME)
        with self.assertRaises(rq.Refused) as ctx:
            rq.take(self.wa, "second", **QUIET)
        self.assertIn("(closed on it)", str(ctx.exception))

    def test_t11_an_item_an_older_branch_of_the_same_name_closed_is_not_held_by_this_branch(self):
        # Case F3: `old` is closed on master (closed by an earlier wt/a); a new wt/a that took another item holds only that one.
        self.write_commit(self.main, {".relay/queue/old.json": tq.with_fields(tq.fix_item("Old"), taken_at=tq.TAKEN_AT, taken_by="wt/a",
                                                                                      closed_at=tq.CLOSED_AT, test="tests/x.py::test_x")},
                          "an older branch closed this")
        git(self.wa, "merge", "-q", "--no-edit", "master")
        self.assertEqual(sorted(rq.held_fix_items(self.wa)), ["job"])


class TestEndToEnd(Flow):
    def test_t5_t4_take_review_fix_gate_one_check_done_take_master_recheck_merge_and_master_holds_the_record(self):
        # Pass case: no refusal; after the merge master holds the item's problem, every finding's verdict and the gate log.
        record, review = self.flow_to_check()
        self.assertIn("closed job", rq.done(self.wa, "job", TEST_NAME))
        self.master_changes({"lib/z.py": SPREAD.replace("end", "END")})                   # master moves on, in a file the branch never touched
        self.take_master()
        gate = self.gate()
        second = self.checked([review], met("Q1", "F1", "F2", "F3"), gate)
        self.assertEqual([f["id"] for f in second["findings"]], ["Q1", "F1", "F2", "F3"])    # z.py is not the branch's own: no M
        self.assertIsNone(merge_hook.judge(self.main, "master", "wt/a"))
        git(self.main, "merge", "-q", "--ff-only", "wt/a")
        stored = rv.load_record(git(self.main, "show", "master:.relay/checks/%s.check.json" % second["head"]), stored=True)
        q1 = stored["findings"][0]
        self.assertEqual((q1["id"], q1["verdict"], q1["source"], stored["item"]), ("Q1", "MET", "queue", "job"))
        self.assertEqual(stored["gate"], gate)
        self.assertEqual(git(self.main, "show", "master:.relay/checks/" + gate).splitlines()[-1], "exit 0")
        self.assertIsNotNone(self.item("job"))

    def test_t4_the_guard_refuses_the_merge_when_code_changed_after_the_check_even_if_the_item_was_closed(self):
        self.flow_to_check()
        rq.done(self.wa, "job", TEST_NAME)
        self.commit({"lib/w.py": SPREAD.replace("one", "late")}, message="code after the check")
        with self.assertRaises(merge_hook.Refused) as ctx:
            merge_hook.judge(self.main, "master", "wt/a")
        self.assertIn("lib/w.py", str(ctx.exception))





class TestGateForms(Flow):
    """F1 and F2 of the review of the check record: any gate the judge text names, and Gate: none with no fix after the review."""

    def _review(self, severity="LOW"):
        self.fix()
        return self.review("a.json", self.head(), [review_finding(1, severity=severity)])

    def _noted(self, record):
        return [(f["id"], f["summary"]) for f in record["findings"] if f["id"].startswith("N")]

    def test_f1_a_green_log_at_any_path_is_a_gate(self):
        # Pass 1: head <HEAD> / exit 0 in a scratch file, code unchanged since: no N finding, open 0.
        review = self._review()
        log = os.path.join(self.tmp, "gate.log")
        with open(log, "w") as handle:
            handle.write("head %s\nexit 0\n" % self.head())
        record = self.record([review], met("Q1", "F1"), log)
        self.assertEqual(self._noted(record), [])
        self.assertEqual(rv.open_of(record), 0)

    def test_f1_a_passed_pipeline_line_is_a_gate(self):
        review = self._review()
        record = self.record([review], met("Q1", "F1"), "pipeline #12 on %s passed" % self.head())
        self.assertEqual(self._noted(record), [])
        self.assertEqual(rv.open_of(record), 0)
        # a pipeline of older code, with code changed since, is the same problem as a log of older code
        old = self.head()
        self.commit({"lib/w.py": SPREAD.replace("one", "new")}, message="code after the pipeline")
        later = self.record([review], met("Q1", "F1"), "pipeline #12 on %s passed" % old)
        self.assertEqual(self._noted(later), [("N1", "the gate log is for other code than head")])

    def test_f1_relays_own_log_is_kept_by_name(self):
        review = self._review()
        reviewed = self.head()                                              # the gate is made for this commit, then committed on top
        record = self.record([review], met("Q1", "F1"))
        self.assertEqual(record["gate"], "%s.gate.log" % reviewed)
        self.assertEqual(self._noted(record), [])

    def test_f1_a_red_scratch_log_and_a_log_of_other_code_are_n_findings(self):
        review = self._review()
        red = os.path.join(self.tmp, "red.log")
        with open(red, "w") as handle:
            handle.write("head %s\nexit 1\n" % self.head())
        self.assertEqual(self._noted(self.record([review], met("Q1", "F1"), red)), [("N1", "the gate is red")])
        old = os.path.join(self.tmp, "old.log")
        with open(old, "w") as handle:
            handle.write("head %s\nexit 0\n" % self.head())
        self.commit({"lib/w.py": SPREAD.replace("one", "new")}, message="code after the gate")
        self.assertEqual(self._noted(self.record([review], met("Q1", "F1"), old)), [("N1", "the gate log is for other code than head")])

    def test_f2_gate_none_with_no_fix_after_the_review_is_open_0(self):
        # Pass 1: the review is of HEAD, nothing after it: no code ran unchecked, so no N finding.
        review = self._review()
        record = self.record([review], met("Q1", "F1"), "none")
        self.assertEqual(self._noted(record), [])
        self.assertEqual(rv.open_of(record), 0)

    def test_f2_gate_none_after_a_fix_commit_is_still_open(self):
        # Pass 2: reviewed at the take commit, the fix (lib/y.py) came after it.
        self.fix()
        review = self.review("a.json", self.took, [review_finding(1, severity="LOW")])
        record = self.record([review], met("Q1", "F1"), "none")
        self.assertEqual(self._noted(record), [("N1", "no gate result for the code of this change")])
        self.assertEqual(rv.open_of(record), 1)

    def test_f2_inert_files_docs_specs_and_master_files_after_the_review_do_not_count(self):
        review = self._review()
        self.commit({"docs/handover.md": "state\n", ".relay/queue/x.txt": "q\n"}, message="state")     # passes 3
        self.commit({"openspec/changes/x/proposal.md": "spec\n", "docs/x.md": "doc\n"}, message="spec")  # pass 5
        self.master_changes({"lib/z.py": SPREAD.replace("one", "master")})
        self.take_master()                                                                               # pass 4
        record = self.record([review], met("Q1", "F1"), "none")
        self.assertEqual(self._noted(record), [])


class TestMergeKeptUntilMet(Flow):
    def test_f3_a_merge_finding_not_met_is_listed_again_by_the_next_check(self):
        # Check 1: master changed lib/y.py which the branch changed too: M1 NOT MET, open 1. A fix that only touches
        # lib/w.py does not answer it: check 2 must list M1 again, and with it MET the record is open 0 (pass 1).
        self.fix()
        review = self.review("a.json", self.took, [review_finding(1)])
        self.master_changes({"lib/y.py": SPREAD.replace("end", "END")})
        self.take_master()
        first = self.checked([review], {"Q1": ("MET", "x"), "F1": ("MET", "x"), "M1": ("NOT MET", "merge broke y")})
        self.assertEqual(rv.open_of(first), 1)
        self.commit({"lib/w.py": SPREAD.replace("one", "fixed")}, message="a fix that does not touch y.py")
        second = self.record([review], met("Q1", "F1", "M1"))
        self.assertEqual([f["id"] for f in second["findings"]], ["Q1", "F1", "M1"])
        self.assertEqual(rv.open_of(second), 0)
        # without a verdict for M1 the record is refused: the finding is back in the list
        with self.assertRaises(rv.VerdictError):
            self.record([review], met("Q1", "F1"))

    def test_f3_a_merge_finding_met_is_not_listed_again(self):
        # Pass 2: check 1 has M1 MET; after more fixes and no new merge, no M finding.
        self.fix()
        review = self.review("a.json", self.took, [review_finding(1)])
        self.master_changes({"lib/y.py": SPREAD.replace("end", "END")})
        self.take_master()
        self.checked([review], met("Q1", "F1", "M1"))
        self.commit({"lib/w.py": SPREAD.replace("one", "fixed")}, message="more")
        second = self.record([review], met("Q1", "F1"))
        self.assertEqual([f["id"] for f in second["findings"]], ["Q1", "F1"])


if __name__ == "__main__":
    unittest.main()
