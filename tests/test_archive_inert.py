"""An archive-only commit after the check mark is inert for the merge guard (plugins/core/hooks/merge.py, lib/relay_inert.py).
Every test runs on a scratch repository in a temp dir."""
import json
import os
import subprocess
import tempfile
import unittest
from relay_testbase import load_hook as _load_hook  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
HOOK = os.path.join(os.path.dirname(HERE), "plugins", "core", "hooks", "merge.py")
ENV = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull, "GIT_AUTHOR_NAME": "t",
       "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


def load_hook():
    return _load_hook("merge_hook_archive_test", HOOK)


class ArchiveAfterTheMark(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(lambda: subprocess.run(["rm", "-rf", self.tmp]))
        self.repo = os.path.join(self.tmp, "r")
        os.makedirs(self.repo)
        self.git("init", "-q", "-b", "master")
        self.write(".relay/README.md", "x\n")
        self.commit("init")
        self.hook = load_hook()
        self.git("checkout", "-q", "-b", "wt/x")
        # the change: code plus its OpenSpec folder, then a mark and a green gate log for that head
        self.write("code.py", "a = 1\n")
        self.write("openspec/changes/x/tasks.md", "- [ ] one\n")
        self.write("openspec/changes/x/proposal.md", "why\n")
        self.commit("change")
        head = self.git("rev-parse", "HEAD")
        mark = {"schema": 2, "commit": head, "check": head + ".check.json", "verdict": {"open": 0, "queued": 0}}
        self.write(".relay/checks/%s.json" % head, json.dumps(mark))
        self.write(".relay/checks/%s.gate.log" % head, "head %s\nexit 0\n" % head)
        self.commit("relay: check")

    def git(self, *args):
        done = subprocess.run(["git", "-C", self.repo, *args], capture_output=True, text=True, env=ENV)
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

    def archive(self):
        """What openspec:archive does: sync the main spec, move the change folder into the archive."""
        self.write("openspec/specs/word/spec.md", "spec\n")
        self.write("openspec/changes/archive/2026-x/tasks.md", "- [x] one\n")
        self.write("openspec/changes/archive/2026-x/proposal.md", "why\n")
        self.git("rm", "-q", "-r", "openspec/changes/x")

    def judge(self):
        return self.hook.judge(self.repo, "master", "wt/x")

    def test_an_archive_only_commit_after_the_mark_is_allowed(self):
        # every path is under archive/ or specs/, or a deletion in changes/x/: nothing the check or gate judged changed
        self.archive()
        self.commit("Archive x")
        self.judge()                       # raises Refused when the merge is refused

    def test_the_same_commit_plus_a_code_line_is_refused(self):
        self.archive()
        self.write("code.py", "a = 1\nb = 2\n")      # code changed after the mark: check again
        self.commit("Archive x")
        with self.assertRaises(self.hook.Refused):
            self.judge()

    def test_an_edit_of_the_change_tasks_after_the_mark_is_refused(self):
        # an edit (not a deletion) of the change's folder is not archiving
        self.write("openspec/changes/x/tasks.md", "- [x] one\n")
        self.write("openspec/specs/word/spec.md", "spec\n")
        self.commit("Edit tasks")
        with self.assertRaises(self.hook.Refused):
            self.judge()

    def test_a_main_spec_edit_with_no_archive_is_refused(self):
        self.write("openspec/specs/word/spec.md", "spec\n")
        self.commit("Edit spec")
        with self.assertRaises(self.hook.Refused):
            self.judge()

    def test_deleting_another_change_folder_with_no_archive_is_refused(self):
        self.git("rm", "-q", "-r", "openspec/changes/x")
        self.commit("Drop change")
        with self.assertRaises(self.hook.Refused):
            self.judge()

    def test_a_failing_git_is_an_error_not_an_allowed_merge(self):
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(HERE), "lib"))
        import relay_inert
        self.archive()
        self.commit("Archive x")
        mark = self.git("rev-parse", "HEAD~1")
        real = subprocess.run

        def broken(cmd, *a, **k):
            if "ls-tree" in cmd:
                return subprocess.CompletedProcess(cmd, 128, "", "boom")
            return real(cmd, *a, **k)
        relay_inert.subprocess.run = broken
        try:
            with self.assertRaises(ValueError):
                relay_inert.changed(self.repo, mark, "HEAD", archive=True)
        finally:
            relay_inert.subprocess.run = real


if __name__ == "__main__":
    unittest.main()
