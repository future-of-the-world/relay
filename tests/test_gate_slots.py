"""Gate slots: `relay gate` takes one of N slots shared by the machine before it runs the gate command.

Every slot folder is under a temp RELAY_HOME (the Fixture sets it), never the live ~/.relay.
"""
import fcntl
import os
import subprocess
import sys
import time
import unittest

from test_gate import RELAY, Fixture, git, read, write

# a gate that says it started, then waits for the test to let it go (polling a file, no fixed sleep in the test)
HOLD = 'touch .ci/started\nwhile [ ! -f "%s" ]; do sleep 0.05; done\nexit 0\n'


class Slots(Fixture):
    def setUp(self):
        super().setUp()
        self.env["RELAY_GATE_SLOTS"] = "1"
        self.release = os.path.join(self.tmp, "release")
        self.repo(gate=HOLD % self.release)
        self.wt2 = os.path.join(self.main, ".worktrees", "y")
        git(self.main, "worktree", "add", "-q", self.wt2, "-b", "wt/y")
        write(os.path.join(self.wt2, "lib", "b.py"), "b\n")
        git(self.wt2, "add", "-A")
        git(self.wt2, "commit", "-q", "-m", "work")

    def start(self, cwd):
        return subprocess.Popen([sys.executable, RELAY, "gate"], cwd=cwd, env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    def wait_for(self, path):
        while not os.path.exists(path):       # the gate command makes the file; the test's own timeout ends a hang
            time.sleep(0.01)

    def slot_is_free(self):
        handle = open(os.path.join(self.env["RELAY_HOME"], "gate-slots", "slot-0"), "a")
        self.addCleanup(handle.close)
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return False
        fcntl.flock(handle, fcntl.LOCK_UN)
        return True

    def test_with_one_slot_a_second_gate_waits_until_the_first_exits(self):
        """N=1: gate B in another worktree prints the waiting line and does not start its command until gate A exits;
        B's log records the seconds it waited as its third line."""
        first = self.start(self.wt)
        self.addCleanup(first.kill)
        self.wait_for(os.path.join(self.wt, ".ci", "started"))
        second = self.start(self.wt2)
        self.addCleanup(second.kill)
        # B's waiting line is the first thing it prints; reading it blocks until B has looked at the slot
        self.assertEqual(second.stderr.readline().strip(), "gate: waiting for a free gate slot (1 busy)")
        self.assertFalse(os.path.exists(os.path.join(self.wt2, ".ci", "started")))     # B holds back while A holds the slot
        write(self.release, "go\n")
        self.assertEqual(first.wait(timeout=60), 0)
        self.assertEqual(second.wait(timeout=60), 0)
        head = git(self.wt2, "rev-parse", "HEAD~1")        # the log commit is on top of the gated commit
        lines = read(os.path.join(self.wt2, ".relay", "checks", head + ".gate.log")).splitlines()
        self.assertRegex(lines[2], r"^wait \d+\.\d$")

    def test_a_gate_killed_with_sigkill_frees_its_slot(self):
        """N=1: while A runs the slot is locked; after SIGKILL of A the lock is free (the OS drops it), and B does not wait."""
        first = self.start(self.wt)
        self.addCleanup(first.kill)
        self.wait_for(os.path.join(self.wt, ".ci", "started"))
        self.assertFalse(self.slot_is_free())
        first.kill()
        first.wait(timeout=60)
        self.assertTrue(self.slot_is_free())
        write(self.release, "go\n")        # lets A's orphaned command end, and B's command go straight through
        second = subprocess.run([sys.executable, RELAY, "gate"], cwd=self.wt2, env=self.env, capture_output=True, text=True, timeout=60)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertNotIn("waiting", second.stderr)

    def test_the_reused_path_takes_no_slot(self):
        """A green gate for the same code is reported while another process holds the only slot: no wait, no hang."""
        write(self.release, "go\n")
        done = subprocess.run([sys.executable, RELAY, "gate"], cwd=self.wt, env=self.env, capture_output=True, text=True, timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr)
        busy = open(os.path.join(self.env["RELAY_HOME"], "gate-slots", "slot-0"), "a")
        self.addCleanup(busy.close)
        fcntl.flock(busy, fcntl.LOCK_EX | fcntl.LOCK_NB)      # fails (and so fails the test) if the first gate left the slot held
        again = subprocess.run([sys.executable, RELAY, "gate"], cwd=self.wt, env=self.env, capture_output=True, text=True, timeout=60)
        self.assertEqual(again.returncode, 0, again.stderr)
        self.assertNotIn("waiting", again.stderr)

    def test_a_bad_slot_count_is_refused(self):
        self.env["RELAY_GATE_SLOTS"] = "none"
        done = subprocess.run([sys.executable, RELAY, "gate"], cwd=self.wt, env=self.env, capture_output=True, text=True, timeout=60)
        self.assertEqual(done.returncode, 1)
        self.assertIn("RELAY_GATE_SLOTS", done.stderr)


if __name__ == "__main__":
    unittest.main()
