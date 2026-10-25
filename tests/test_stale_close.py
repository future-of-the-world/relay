"""relay queue done --fixed-by: a fix that a change already on the default branch fixed is closed without a branch of its own
(finding Q1 of a-fix-already-merged-by-another-change-cannot-be). Scratch repositories in a temp dir; the clock is fixed."""
import os
import subprocess
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_queue as tq  # noqa: E402

rq = tq.rq
NOW = "2026-10-25T09:00:00Z"
TEST_FILE = "tests/test_flag.py"
TEST_TEXT = ("def test_flag_is_ok():\n    assert open('flag.txt').read().strip() == 'ok'\n\n\n"
             "def test_always():\n    assert True\n")
NAME = TEST_FILE + "::test_flag_is_ok"


class TestFixedBy(tq.Base):
    def setUp(self):
        super().setUp()
        # master: the item is open; the flag is bad (commit `broken`), then a change makes it ok (commit `fix`) and adds the test
        self.write_commit(self.main, {".relay/queue/item.json": tq.fix_item(), "flag.txt": "bad\n"}, "broken")
        self.write_commit(self.main, {"flag.txt": "ok\n", TEST_FILE: TEST_TEXT}, "fix")
        self.fix = tq.git(self.main, "rev-parse", "HEAD")
        self.write_commit(self.main, {"other.txt": "later\n"}, "later")

    def close(self, commit=None, test=NAME):
        with mock.patch.object(rq, "utcnow", return_value=NOW):
            return rq.close_fixed_by(self.main, "item", commit or self.fix, test, **tq.QUIET)

    def test_q1_an_item_fixed_on_master_closes_with_the_commit_and_test_and_leaves_the_list(self):
        self.close()
        # worked out: the test fails at the parent (flag bad), passes at the fix (flag ok), so the close is allowed and
        # the done file names the full sha and the test, dated by the fixed clock
        self.assertIsNone(self.item("item"))
        closed = self.item("item", sub="done/")
        self.assertEqual((closed["state"], closed["closed_at"], closed["test"], closed["fixed_by"], closed["problems"]),
                         ("done", NOW, NAME, self.fix, []))
        self.assertIn(f"fixed by {self.fix}", rq.show_text(closed))

    def test_q1_a_named_test_that_already_passes_at_the_parent_is_refused(self):
        # test_always passes before and after the fix: the commit did not fix what that test checks
        with self.assertRaises(rq.Refused) as ctx:
            self.close(test=TEST_FILE + "::test_always")
        self.assertIn("passes at", str(ctx.exception))
        self.assertIn("did not fix it", str(ctx.exception))
        self.assertIsNotNone(self.item("item"))
        self.assertIsNone(self.item("item", sub="done/"))

    def test_q1_a_commit_not_on_master_a_missing_test_and_a_test_that_still_fails_are_refused(self):
        tq.git(self.main, "checkout", "-q", "-b", "side")
        self.write_commit(self.main, {"side.txt": "x\n"}, "unmerged")
        side = tq.git(self.main, "rev-parse", "HEAD")
        tq.git(self.main, "checkout", "-q", "master")
        with self.assertRaises(rq.Refused) as ctx:
            self.close(commit=side)
        self.assertIn("is not on master", str(ctx.exception))
        with self.assertRaises(rq.Refused) as ctx:
            self.close(test=TEST_FILE + "::test_nothing_like_it")
        self.assertIn("does not hold a test named", str(ctx.exception))
        # the "later" commit leaves the flag ok, but its parent already passes: the test does not fail before it
        later = tq.git(self.main, "rev-parse", "HEAD")
        with self.assertRaises(rq.Refused):
            self.close(commit=later)
        # the commit before the fix has a bad flag: the test fails before it and at it, so it was not that commit that fixed it
        with self.assertRaises(rq.Refused) as ctx:
            self.close(commit=tq.git(self.main, "rev-parse", self.fix + "^"))
        self.assertIn("does not pass at", str(ctx.exception))

    def test_q1_a_fix_taken_by_a_live_branch_is_released_first(self):
        self.write_commit(self.main, {".relay/queue/job.json": tq.with_fields(tq.fix_item(), **tq.taken_fields("wt/live"))}, "take")
        tq.git(self.main, "checkout", "-q", "-b", "wt/live")
        tq.git(self.main, "commit", "-q", "--allow-empty", "-m", "work")
        tq.git(self.main, "checkout", "-q", "master")
        with self.assertRaises(rq.Refused) as ctx:
            with mock.patch.object(rq, "utcnow", return_value=NOW):
                rq.close_fixed_by(self.main, "job", self.fix, NAME, **tq.QUIET)
        self.assertIn("release", str(ctx.exception))
        self.assertIn("wt/live", str(ctx.exception))

    def test_q1_a_fix_taken_by_a_branch_without_code_closes_here_keeping_its_take(self):
        self.write_commit(self.main, {".relay/queue/job.json": tq.with_fields(tq.fix_item(), **tq.taken_fields("wt/idle"))}, "take")
        tq.git(self.main, "branch", "wt/idle")      # at master: no commit of its own, so it is not live
        with mock.patch.object(rq, "utcnow", return_value=NOW):
            rq.close_fixed_by(self.main, "job", self.fix, NAME, **tq.QUIET)
        closed = self.item("job", sub="done/")
        self.assertEqual((closed["state"], closed["taken_by"], closed["fixed_by"], closed["problems"]), ("done", "wt/idle", self.fix, []))

    def test_q1_the_command_line_form_closes_it_and_a_fixed_by_without_a_test_is_a_usage_error(self):
        run = lambda *a: subprocess.run([sys.executable, os.path.join(tq.ROOT, "bin", "relay"), "queue", *a], capture_output=True,  # noqa: E731
                                        text=True, env=dict(os.environ, RELAY_ROOT=tq.ROOT))
        bad = run("done", "item", "--fixed-by", self.fix, "-C", self.main)
        self.assertNotEqual(bad.returncode, 0)
        good = run("done", "item", "--fixed-by", self.fix, "--test", NAME, "-C", self.main)
        self.assertEqual(good.returncode, 0, good.stderr)
        self.assertEqual(self.item("item", sub="done/")["fixed_by"], self.fix)


if __name__ == "__main__":
    unittest.main()
