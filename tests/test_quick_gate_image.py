"""The clean-image fixes: the sync tests run the working tree's code, and the image sets no git identity."""
import os
import subprocess
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import test_paid_batch  # noqa: E402


class SyncTestRunsTheWorkingTree(unittest.TestCase):
    def test_run_sync_runs_this_checkouts_bin_relay_and_clones_nothing(self):
        # an uncommitted edit to bin/relay or bin/paid-cost must be what the test runs: no clone of HEAD
        calls: list[list[str]] = []
        real = subprocess.run

        def spy(cmd, *a, **kw):
            calls.append(list(cmd))
            return real(cmd, *a, **kw)

        case = test_paid_batch.SyncWaits("test_sync_dry_still_prints_its_plan")
        with mock.patch.object(test_paid_batch.subprocess, "run", spy):
            case.run_sync("--dry")
        self.assertFalse([c for c in calls if "clone" in c], calls)
        ran = [c for c in calls if len(c) > 1 and c[1].endswith(os.path.join("bin", "relay"))]
        self.assertEqual([c[1] for c in ran], [os.path.join(ROOT, "bin", "relay")])

    def test_run_sync_leaves_no_master_it_made(self):
        # a detached clone has no master: the test makes one for its run and removes it after
        case = test_paid_batch.SyncWaits("test_sync_dry_still_prints_its_plan")
        before = subprocess.run(["git", "-C", ROOT, "rev-parse", "--verify", "-q", "refs/heads/master"], capture_output=True).returncode
        case.run_sync("--dry")
        case.doCleanups()
        after = subprocess.run(["git", "-C", ROOT, "rev-parse", "--verify", "-q", "refs/heads/master"], capture_output=True).returncode
        self.assertEqual(before, after)


class ImageHasNoGitIdentity(unittest.TestCase):
    def test_containerfile_sets_no_author_variable(self):
        # each test gives its own git calls an identity; the image must not hide one that does not
        text = open(os.path.join(ROOT, "container", "Containerfile"), encoding="utf-8").read()
        self.assertNotIn("GIT_AUTHOR", text)
        self.assertNotIn("GIT_COMMITTER", text)


if __name__ == "__main__":
    unittest.main()
