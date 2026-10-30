"""Gate reuse after a take of the default branch (design relay-land 4.2): `relay_gate.reusable` walks the branch's own line."""
import os
import subprocess
import sys
import unittest

from test_gate import GIT_ENV, HERE, ROOT, Fixture, git, read, write

sys.path.insert(0, HERE)


class ReuseAfterTake(Fixture):
    """A take of the default branch (merge, branch as first parent) must not defeat gate reuse when master moved only by
    inert files, even if master's commit is dated after the branch's gate commit (the walk follows the branch's own line)."""

    def setUp(self):
        super().setUp()
        self.counter = os.path.join(self.tmp, "runs")

    def runs(self):
        return len(read(self.counter).splitlines()) if os.path.exists(self.counter) else 0

    def _commit_on_master(self, rel, text, stamp):
        write(os.path.join(self.main, rel), text)
        git(self.main, "add", "-A")
        env = {**os.environ, **GIT_ENV, "GIT_COMMITTER_DATE": stamp, "GIT_AUTHOR_DATE": stamp}
        subprocess.run(["git", "-C", self.main, "commit", "-q", "-m", "master " + rel], check=True, env=env)

    def _gate_then_take(self, rel, text):
        self.repo(gate='echo run >> "%s"\nexit 0\n' % self.counter)
        self.assertEqual(self.gate(self.wt).returncode, 0)
        self.assertEqual(self.runs(), 1)
        # master's commit is dated a day after the gate commit: a date-ordered walk would list it before the gate log
        self._commit_on_master(rel, "m\n", "2099-01-01T00:00:00")
        git(self.wt, "merge", "-q", "--no-edit", "master")
        return git(self.wt, "rev-parse", "HEAD")

    def test_reuse_after_inert_take(self):
        """The branch is gated green; master then gets a queue record; the take is gated: the log of the branch's commit is
        reused, so the fake gate has run once in all (today the date-ordered walk stops at master's commit: 2 runs)."""
        self._gate_then_take(".relay/queue/a.toml", "x")
        self.assertEqual(self.gate(self.wt).returncode, 0)
        self.assertEqual(self.runs(), 1)

    def test_reuse_after_handover_take(self):
        self._gate_then_take("docs/handover.md", "x")
        self.assertEqual(self.gate(self.wt).returncode, 0)
        self.assertEqual(self.runs(), 1)

    def test_no_reuse_after_code_take(self):
        """Master's new commit changes lib/b.py: that is code, the take needs its own run (2 in all)."""
        self._gate_then_take("lib/b.py", "x")
        self.assertEqual(self.gate(self.wt).returncode, 0)
        self.assertEqual(self.runs(), 2)

    def test_reuse_after_check_commit(self):
        """Linear branch, then only a record commit on it: reused, today's behaviour."""
        self.repo(gate='echo run >> "%s"\nexit 0\n' % self.counter)
        self.assertEqual(self.gate(self.wt).returncode, 0)
        write(os.path.join(self.wt, ".relay", "checks", "z.json"), "{}\n")
        git(self.wt, "add", "-A")
        git(self.wt, "commit", "-q", "-m", "relay: check of z")
        self.assertEqual(self.gate(self.wt).returncode, 0)
        self.assertEqual(self.runs(), 1)


class StepGateAcrossInertCommits(Fixture):
    """The merge hook's step_gate and `reusable` accept a green gate across commits that touch only inert files (the gate ran on a
    copy without them) and refuse after a code commit. The speed-up of the quick gate leaves both unchanged."""

    def commit(self, rel, text):
        write(os.path.join(self.wt, rel), text)
        git(self.wt, "add", "-A")
        git(self.wt, "commit", "-q", "-m", "edit " + rel)
        return git(self.wt, "rev-parse", "HEAD")

    def test_a_green_log_stands_across_a_queue_commit_and_not_across_a_code_commit(self):
        import relay_gate
        from relay_testbase import load_hook
        hook = load_hook("merge_hook_for_reuse_test", os.path.join(ROOT, "plugins", "relay", "hooks", "merge.py"))
        self.repo(gate="exit 0\n")
        self.assertEqual(self.gate(self.wt).returncode, 0)
        hook.step_gate(self.wt, "wt/x", "its worktree")            # the gate's own log covers the head
        queue = self.commit(".relay/queue/x.json", "{}\n")
        self.assertIsNotNone(relay_gate.reusable(self.wt, queue, [self.script]))
        hook.step_gate(self.wt, "wt/x", "its worktree")            # returns: only an inert file changed since the green log
        code = self.commit("lib/b.py", "b\n")
        self.assertIsNone(relay_gate.reusable(self.wt, code, [self.script]))
        with self.assertRaises(hook.Refused) as caught:
            hook.step_gate(self.wt, "wt/x", "its worktree")
        self.assertIn("code changed since", str(caught.exception))


class StoppedGate(Fixture):
    def test_t8_a_gate_stopped_at_its_time_limit_is_run_again_not_reported(self):
        """The command exits 124 the first time (stopped at the limit), 0 afterwards. A plain second `relay gate` on the same
        code runs it (2 runs) and is green; a red 3 would be reported without a run (test_gate), 124 is not."""
        counter = os.path.join(self.tmp, "runs")
        self.repo(gate='echo run >> "%s"\n[ "$(wc -l < "%s")" -eq 1 ] && exit 124\nexit 0\n' % (counter, counter))
        self.assertEqual(self.gate(self.wt).returncode, 124)
        again = self.gate(self.wt)
        self.assertEqual(again.returncode, 0, again.stderr)
        self.assertEqual(len(read(counter).splitlines()), 2)


if __name__ == "__main__":
    unittest.main()
