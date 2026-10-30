"""bin/wt new: the "queue-" prefix is reserved for queue-landing branches."""
import os
import subprocess
import tempfile
import unittest

WT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin", "wt")


class BinWtNew(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = os.path.realpath(self.tmp.name)
        for args in (["init", "-q", "-b", "master"],
                     ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "i"]):
            subprocess.run(["git", "-C", self.repo, *args], check=True)

    def wt(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run([WT, *args], cwd=self.repo, capture_output=True, text=True)

    def test_queue_prefix_refused(self) -> None:
        done = self.wt("new", "queue-docs", "master")
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("queue-", done.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.repo, ".worktrees", "queue-docs")))
        branches = subprocess.run(["git", "-C", self.repo, "branch", "--list", "wt/*"],
                                  capture_output=True, text=True).stdout
        self.assertEqual(branches.strip(), "")

    def test_plain_name_unchanged(self) -> None:
        done = self.wt("new", "docs", "master")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertTrue(os.path.isdir(os.path.join(self.repo, ".worktrees", "docs")))
        branch = subprocess.run(["git", "-C", self.repo, "branch", "--list", "wt/docs"],
                                capture_output=True, text=True).stdout
        self.assertIn("wt/docs", branch)


if __name__ == "__main__":
    unittest.main()
