"""`relay_inert.resolved` and `own_since_mark` (design relay-land 4.2) and the merge hook's mark step after a take of the default
branch. Every test runs on a scratch repository in a temp dir."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from relay_testbase import load_hook as _load_hook  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "lib"))
import relay_inert  # noqa: E402

HOOK = os.path.join(ROOT, "plugins", "relay", "hooks", "merge.py")
ENV = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull, "GIT_AUTHOR_NAME": "t",
       "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


class Repo(unittest.TestCase):
    """master with .relay/ and a file x.py of ten lines; branch wt/x forked from it, checked out in the repo."""

    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(lambda: subprocess.run(["rm", "-rf", self.tmp]))
        self.repo = os.path.join(self.tmp, "r")
        os.makedirs(self.repo)
        self.git("init", "-q", "-b", "master")
        self.write(".relay/README.md", "x\n")
        self.write("x.py", "".join("line %d\n" % i for i in range(10)))
        self.commit("init")
        self.git("checkout", "-q", "-b", "wt/x")

    def git(self, *args, ok=True):
        done = subprocess.run(["git", "-C", self.repo, *args], capture_output=True, text=True, env=ENV)
        if ok:
            self.assertEqual(done.returncode, 0, done.stderr)
        return done.stdout.strip()

    def write(self, rel, text):
        path = os.path.join(self.repo, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as handle:
            handle.write(text)

    def commit(self, message):
        self.git("add", "-A")
        self.git("commit", "-q", "-m", message)

    def edit_line(self, rel, number, text):
        path = os.path.join(self.repo, rel)
        with open(path) as handle:
            lines = handle.read().splitlines(True)
        lines[number] = text + "\n"
        self.write(rel, "".join(lines))

    def mark(self, openn=0):
        head = self.git("rev-parse", "HEAD")
        data = {"schema": 2, "commit": head, "check": head + ".check.json", "verdict": {"open": openn, "queued": 0}}
        self.write(".relay/checks/%s.json" % head, json.dumps(data))
        self.write(".relay/checks/%s.gate.log" % head, "head %s\nexit 0\n" % head)
        self.commit("relay: check of %s" % head)
        return head

    def on_master(self, fn, message):
        self.git("checkout", "-q", "master")
        fn()
        self.commit(message)
        self.git("checkout", "-q", "wt/x")

    def clean_overlap_take(self):
        """The branch changed line 1 of x.py and was checked; master changed line 8 of the same file; git merges it by itself."""
        self.edit_line("x.py", 1, "branch one")
        self.commit("branch change")
        mark = self.mark()
        self.on_master(lambda: self.edit_line("x.py", 8, "master eight"), "master change")
        self.git("merge", "-q", "--no-edit", "master")
        return mark

    def conflict_take(self, keep=None):
        """Both sides changed line 1: git stops; the author resolves it by hand (editing the file)."""
        self.edit_line("x.py", 1, "branch one")
        self.commit("branch change")
        mark = self.mark()
        self.on_master(lambda: self.edit_line("x.py", 1, "master one"), "master change")
        self.git("merge", "-q", "--no-edit", "master", ok=False)
        self.write("x.py", "".join("line %d\n" % i if i else "both one\n" for i in range(10)))
        self.git("add", "-A")
        self.git("commit", "-q", "--no-edit")
        return mark


class Resolved(Repo):
    def test_resolved_content(self):
        # both sides changed line 1: git cannot merge it, so x.py is a hand decision
        self.conflict_take()
        self.assertEqual(relay_inert.resolved(self.repo, "HEAD"), ["x.py"])

    def test_resolved_clean_overlap(self):
        # both sides changed x.py on different lines: git merged it by itself, nothing was decided by hand
        self.clean_overlap_take()
        self.assertEqual(relay_inert.resolved(self.repo, "HEAD"), [])

    def test_resolved_modify_delete_kept(self):
        # master deletes x.py, the branch modified it: a conflict; the fixer keeps the branch's file. The tree of the merge
        # equals the branch's, so a tree comparison alone would be empty; the conflict list names x.py.
        self.edit_line("x.py", 1, "branch one")
        self.commit("branch change")
        self.on_master(lambda: os.remove(os.path.join(self.repo, "x.py")), "master deletes")
        self.git("merge", "-q", "--no-edit", "master", ok=False)
        self.git("checkout", "-q", "--ours", "x.py")
        self.git("add", "x.py")
        self.git("commit", "-q", "--no-edit")
        self.assertEqual(relay_inert.resolved(self.repo, "HEAD"), ["x.py"])

    def test_resolved_extra_hand_edit(self):
        # a clean take plus an edit of an unrelated file inside the merge commit
        self.edit_line("x.py", 1, "branch one")
        self.write("y.py", "y\n")
        self.commit("branch change")
        self.on_master(lambda: self.write("z.py", "z\n"), "master change")
        self.git("merge", "-q", "--no-edit", "--no-commit", "master")
        self.write("y.py", "y edited by hand\n")
        self.git("add", "-A")
        self.git("commit", "-q", "--no-edit")
        self.assertEqual(relay_inert.resolved(self.repo, "HEAD"), ["y.py"])


class OwnSinceMark(Repo):
    def test_clean_overlap_take_leaves_nothing(self):
        mark = self.clean_overlap_take()
        # changed() alone lists x.py (both sides touched it); the rule leaves it out: a clean take
        self.assertEqual(relay_inert.changed(self.repo, mark, "HEAD", own=True, archive=True), ["x.py"])
        self.assertEqual(relay_inert.own_since_mark(self.repo, mark, "HEAD"), [])

    def test_commit_after_the_mark_stays(self):
        mark = self.clean_overlap_take()
        self.edit_line("x.py", 2, "later")
        self.commit("branch commit after the check")
        self.assertEqual(relay_inert.own_since_mark(self.repo, mark, "HEAD"), ["x.py"])

    def test_hand_resolved_take_stays(self):
        mark = self.conflict_take()
        self.assertEqual(relay_inert.own_since_mark(self.repo, mark, "HEAD"), ["x.py"])


class MergeHookAfterTake(Repo):
    def setUp(self):
        super().setUp()
        self.hook = _load_hook("merge_hook_inert_test", HOOK)

    def judge(self):
        return self.hook.step_mark(self.repo, "master", "wt/x")

    def test_clean_overlap_take_lands(self):
        # red today: the branch's own file x.py changed since the mark (master's line), so the hook asked for a new check
        mark = self.clean_overlap_take()
        self.assertEqual(self.judge(), mark)

    def test_hand_resolved_take_needs_check(self):
        self.conflict_take()
        with self.assertRaises(self.hook.Refused) as caught:
            self.judge()
        self.assertIn("x.py", str(caught.exception))
        self.assertIn("by hand", str(caught.exception))

    def test_hand_resolved_take_after_check_lands(self):
        self.conflict_take()
        newest = self.mark()
        self.assertEqual(self.judge(), newest)

    def test_commit_after_check_refused(self):
        self.clean_overlap_take()
        self.edit_line("x.py", 2, "later")
        self.commit("branch commit after the check")
        with self.assertRaises(self.hook.Refused) as caught:
            self.judge()
        self.assertIn("x.py", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
