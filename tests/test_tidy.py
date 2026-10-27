"""relay doctor's lines about leftovers of finished work (docs/plans/review-gate.md 11.3, test T17).

Every repository is built in a temp directory with a bare `origin`; nothing touches the real repo.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "lib"))

import relay_queue  # noqa: E402
import relay_tidy  # noqa: E402

GIT_ENV = {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


def git(cwd, *args):
    done = subprocess.run(["git", "-C", cwd, *args], capture_output=True, text=True, env={**os.environ, **GIT_ENV})
    if done.returncode != 0:
        raise AssertionError("git %s: %s" % (" ".join(args), done.stderr))
    return done.stdout.strip()


def commit_file(cwd, name, text="x", message="work"):
    path = os.path.join(cwd, name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as handle:
        handle.write(text)
    git(cwd, "add", name)
    git(cwd, "commit", "-q", "-m", message)


def item_text(slug, state, taken_by):
    """A queue item file as relay_queue writes it (JSON), a fix item in the given state."""
    item = relay_queue.new_item("fix", 1, 10, "2026-10-22T08:00:00Z", "test", "%s loses a row" % slug, "it loses a row", "a row is lost", failing="one row in, none out")
    events = {"open": {}, "taken": {"taken_at": "2026-10-22T09:00:00Z", "taken_by": taken_by},
              "done": {"taken_at": "2026-10-22T09:00:00Z", "taken_by": taken_by, "closed_at": "2026-10-22T10:00:00Z", "test": "t.py::t"}}[state]
    return relay_queue.serialize(slug, relay_queue.changed(item, **events))


class Tidy(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="relay-tidy-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.claude = os.path.join(self.tmp, "claude")
        os.makedirs(self.claude)
        old = os.environ.get("CLAUDE_CONFIG_DIR")
        os.environ["CLAUDE_CONFIG_DIR"] = self.claude
        self.addCleanup(lambda: os.environ.__setitem__("CLAUDE_CONFIG_DIR", old) if old is not None else os.environ.pop("CLAUDE_CONFIG_DIR", None))
        origin = os.path.join(self.tmp, "origin.git")
        subprocess.run(["git", "init", "-q", "--bare", "-b", "master", origin], check=True, env={**os.environ, **GIT_ENV})
        seed = os.path.join(self.tmp, "seed")
        os.makedirs(seed)
        git(seed, "init", "-q", "-b", "master")
        commit_file(seed, ".relay/README.md", message="init")
        git(seed, "remote", "add", "origin", origin)
        git(seed, "push", "-q", "origin", "master")
        self.main = os.path.join(self.tmp, "main")
        subprocess.run(["git", "clone", "-q", origin, self.main], check=True, env={**os.environ, **GIT_ENV})
        self.origin = origin

    def task(self, name, commits=1):
        git(self.main, "worktree", "add", "-q", ".worktrees/" + name, "-b", "wt/" + name)
        wt = os.path.join(self.main, ".worktrees", name)
        for i in range(commits):
            commit_file(wt, name + str(i) + ".txt")
        return wt

    def build(self):
        """merged m; unmerged u; fresh f; merged and locked by s9 l; upstream gone g; queue branch; taken item; cache dir."""
        self.task("m")
        self.task("u")
        self.task("l")
        self.task("f", commits=0)
        git(self.main, "merge", "-q", "--ff-only", "wt/m")
        git(self.main, "merge", "-q", "--no-edit", "wt/l")
        git(self.main, "worktree", "lock", "--reason", "session s9", os.path.join(self.main, ".worktrees", "l"))
        git(self.main, "branch", "wt/g")
        git(self.main, "push", "-q", "-u", "origin", "wt/g")
        git(self.main, "push", "-q", "origin", "--delete", "wt/g")
        git(self.main, "fetch", "-q", "--prune")
        git(self.main, "branch", "wt/queue-x")
        commit_file(self.main, ".relay/queue/foo.json", item_text("foo", "taken", "wt/gone2"), "queue")
        commit_file(self.main, ".relay/queue/bar.json", item_text("bar", "done", "wt/gone3"), "queue done")
        os.makedirs(os.path.join(self.claude, "plugins", "cache", "relay"))

    def test_t17_exactly_those_lines(self):
        # Hand-worked: m is merged with its own commit -> listed; u is not merged; f has no commit of its own; l is merged
        # and locked "session s9" -> its own line; g's upstream is gone ("[gone]" after prune) -> information; wt/queue-x is
        # a leftover queue branch; foo.json is taken by wt/gone2, which does not exist; bar.json is a done item;
        # the cache folder exists -> one information line.
        self.build()
        got = sorted(relay_tidy.lines(self.main))
        want = sorted([
            (True, "merged worktree still present: .worktrees/m (wt/m)"),
            (True, "merged worktree .worktrees/l (wt/l) is locked by session s9; remove it once that session is closed"),
            (False, "wt/g: its upstream is gone (probably merged on the server, a squash); not removed"),
            (False, "unused plugin copy: %s/ (informational)" % os.path.join(self.claude, "plugins", "cache", "relay")),
            (True, "leftover queue branch: wt/queue-x"),
            (True, "queue item foo is taken by wt/gone2, which no longer exists"),
        ])
        self.assertEqual(got, want)

    def test_nothing_to_report_is_empty(self):
        self.task("u")                                   # unmerged only
        self.assertEqual(relay_tidy.lines(self.main), [])

    def test_a_worktree_asked_from_inside_gives_the_same_lines(self):
        wt = self.task("m")
        git(self.main, "merge", "-q", "--ff-only", "wt/m")
        self.assertEqual(relay_tidy.lines(wt), [(True, "merged worktree still present: .worktrees/m (wt/m)")])

    def test_taken_item_whose_branch_exists_is_not_listed(self):
        self.task("t")
        commit_file(self.main, ".relay/queue/foo.json", item_text("foo", "taken", "wt/t"), "queue")
        self.assertEqual(relay_tidy.lines(self.main), [])

    def test_taken_item_of_a_missing_branch_is_one_fix_line(self):
        # foo is taken by wt/gone, no such branch: one line, fix; an open item and a malformed file say nothing
        commit_file(self.main, ".relay/queue/foo.json", item_text("foo", "taken", "wt/gone"), "queue")
        commit_file(self.main, ".relay/queue/open-one.json", item_text("open-one", "open", ""), "queue")
        commit_file(self.main, ".relay/queue/broken.json", "{", "queue")
        self.assertEqual(relay_tidy.lines(self.main), [(True, "queue item foo is taken by wt/gone, which no longer exists")])

    def test_a_markdown_item_is_no_longer_read(self):
        # the queue is JSON now: an old front-matter file taken by a missing branch is not a queue item
        commit_file(self.main, ".relay/queue/old.md", "---\nkind: fix\nstate: taken\ntaken-by: wt/gone\n---\n", "queue")
        self.assertEqual(relay_tidy.lines(self.main), [])

    def test_a_leftover_queue_branch_is_one_fix_line_from_the_queue_library(self):
        git(self.main, "branch", "wt/queue-a")
        git(self.main, "branch", "wt/queue-b")
        self.assertEqual(relay_queue.leftover_branches(self.main), ["wt/queue-a", "wt/queue-b"])
        self.assertEqual(sorted(relay_tidy.lines(self.main)), [(True, "leftover queue branch: wt/queue-a"), (True, "leftover queue branch: wt/queue-b")])

    def test_relay_doctor_prints_the_lines(self):
        self.task("m")
        git(self.main, "merge", "-q", "--ff-only", "wt/m")
        env = {**os.environ, "CLAUDE_CONFIG_DIR": self.claude, "RELAY_HOME": os.path.join(self.tmp, "home"), "RELAY_ROOT": ROOT}
        done = subprocess.run([sys.executable, os.path.join(ROOT, "bin", "relay"), "doctor", self.main], capture_output=True, text=True, env=env)
        self.assertIn("FIX  merged worktree still present: .worktrees/m (wt/m)", done.stdout)
        self.assertEqual(done.returncode, 1)

    def test_relay_doctor_with_no_folder_checks_the_current_repository(self):
        self.task("m")
        git(self.main, "merge", "-q", "--ff-only", "wt/m")
        env = {**os.environ, "CLAUDE_CONFIG_DIR": self.claude, "RELAY_HOME": os.path.join(self.tmp, "home"), "RELAY_ROOT": ROOT}
        relay = os.path.join(ROOT, "bin", "relay")
        inside = subprocess.run([sys.executable, relay, "doctor"], capture_output=True, text=True, env=env, cwd=self.main)
        self.assertIn("FIX  merged worktree still present: .worktrees/m (wt/m)", inside.stdout)
        # outside any repository: no tidy lines and no traceback
        elsewhere = os.path.join(self.tmp, "not-a-repo")
        os.makedirs(elsewhere)
        outside = subprocess.run([sys.executable, relay, "doctor"], capture_output=True, text=True, env=env, cwd=elsewhere)
        self.assertNotIn("merged worktree", outside.stdout)
        self.assertNotIn("Traceback", outside.stderr)


if __name__ == "__main__":
    unittest.main()
