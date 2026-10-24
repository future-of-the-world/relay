"""relay queue done --evidence: a finished feature leaves the queue with a merge sha or a report path (finding Q1);
a fix still needs its test. Scratch repositories in a temp dir."""
import os
import subprocess
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_queue as tq  # noqa: E402

rq = tq.rq


class TestCloseWithEvidence(tq.Base):
    def run_relay(self, *args):
        return subprocess.run([sys.executable, os.path.join(tq.ROOT, "bin", "relay"), "queue", *args], capture_output=True, text=True,
                              env=dict(os.environ, RELAY_ROOT=tq.ROOT))

    def test_q1_a_feature_closes_with_a_merge_sha_and_leaves_the_list(self):
        self.write_commit(self.main, {".relay/queue/feat.json": tq.feature_item("Feat", ip=99)}, "seed")
        done = self.run_relay("done", "feat", "--evidence", "19c02df", "-C", self.main)
        self.assertEqual(done.returncode, 0, done.stderr)
        # the open file is gone, the done file holds the dated close and the evidence, and it is a well formed done item
        self.assertIsNone(self.item("feat"))
        closed = self.item("feat", sub="done/")
        self.assertEqual((closed["state"], closed["evidence"], closed["test"], closed["problems"]), ("done", "19c02df", None, []))
        self.assertNotIn("feat", self.run_relay("-C", self.main).stdout)
        self.assertIn("evidence 19c02df", rq.show_text(closed))

    def test_q1_a_report_path_is_evidence_too_and_a_taken_feature_is_closed_the_same_way_by_its_taker_not_here(self):
        self.write_commit(self.main, {".relay/queue/feat.json": tq.feature_item("Feat"),
                                      ".relay/queue/job.json": tq.with_fields(tq.feature_item("Job"), **tq.taken_fields("wt/x"))}, "seed")
        with mock.patch.object(rq, "utcnow", return_value="2026-10-24T08:00:00Z"):
            rq.close_with_evidence(self.main, "feat", "docs/reports/trial.md", **tq.QUIET)
        self.assertEqual(self.item("feat", sub="done/")["evidence"], "docs/reports/trial.md")
        self.assertEqual(self.item("feat", sub="done/")["closed_at"], "2026-10-24T08:00:00Z")
        tq.git(self.main, "checkout", "-q", "-b", "wt/x")      # its branch is live and not merged
        tq.git(self.main, "commit", "-q", "--allow-empty", "-m", "work")
        tq.git(self.main, "checkout", "-q", "master")
        with self.assertRaises(rq.Refused) as ctx:          # a taken item is its branch's while it lives
            rq.close_with_evidence(self.main, "job", "abc1234", **tq.QUIET)
        self.assertIn("taken by wt/x", str(ctx.exception))

    def test_f1_a_feature_taken_by_a_merged_or_gone_branch_closes_keeping_its_take(self):
        self.write_commit(self.main, {".relay/queue/job.json": tq.with_fields(tq.feature_item("Job"), **tq.taken_fields("wt/x")),
                                      ".relay/queue/live.json": tq.with_fields(tq.feature_item("Live"), **tq.taken_fields("wt/y"))}, "seed")
        # wt/x is merged into master (a branch at an ancestor commit); wt/y has a commit master lacks
        tq.git(self.main, "branch", "wt/x")
        tq.git(self.main, "branch", "wt/y")
        tq.git(self.main, "checkout", "-q", "wt/y")
        tq.git(self.main, "commit", "-q", "--allow-empty", "-m", "unmerged")
        tq.git(self.main, "checkout", "-q", "master")
        with self.assertRaises(rq.Refused) as ctx:          # live and not merged: its taker closes it
            rq.close_with_evidence(self.main, "live", "abc1234", **tq.QUIET)
        self.assertIn("taken by wt/y", str(ctx.exception))
        rq.close_with_evidence(self.main, "job", "abc1234", **tq.QUIET)
        closed = self.item("job", sub="done/")
        self.assertEqual((closed["state"], closed["evidence"], closed["taken_by"], closed["problems"]), ("done", "abc1234", "wt/x", []))
        self.assertIsNotNone(closed["taken_at"])
        # a branch that is gone altogether is the same
        tq.git(self.main, "branch", "-D", "wt/y")
        rq.close_with_evidence(self.main, "live", "def5678", **tq.QUIET)
        self.assertEqual(self.item("live", sub="done/")["taken_by"], "wt/y")

    def test_q1_a_fix_without_a_test_is_still_refused(self):
        self.write_commit(self.main, {".relay/queue/job.json": tq.fix_item("Job")}, "seed")
        head = tq.git(self.main, "rev-parse", "master")
        with self.assertRaises(rq.Refused) as ctx:
            rq.close_with_evidence(self.main, "job", "abc1234", **tq.QUIET)
        self.assertIn("is a fix", str(ctx.exception))
        self.assertEqual(self.run_relay("done", "job", "--evidence", "abc1234", "-C", self.main).returncode, 2)
        self.assertEqual(tq.git(self.main, "rev-parse", "master"), head)      # nothing landed
        # by hand: a fix file closed with evidence does not pass the item check either
        data = rq.changed(rq.parse("job", tq.fix_item("Job")), closed_at="2026-10-03T00:00:00Z", evidence="abc1234")
        with self.assertRaises(rq.Refused) as ctx:
            rq.serialize("job", data, "done")
        self.assertIn("a fix is closed with a test", str(ctx.exception))

    def test_q1_empty_evidence_and_both_flags_are_refused(self):
        self.write_commit(self.main, {".relay/queue/feat.json": tq.feature_item("Feat")}, "seed")
        head = tq.git(self.main, "rev-parse", "master")
        with self.assertRaises(rq.Refused):
            rq.close_with_evidence(self.main, "feat", "  ", **tq.QUIET)
        both = self.run_relay("done", "feat", "--evidence", "abc1234", "--test", "t.py::t", "-C", self.main)
        self.assertEqual(both.returncode, 2)
        self.assertEqual(tq.git(self.main, "rev-parse", "master"), head)


if __name__ == "__main__":
    unittest.main()
