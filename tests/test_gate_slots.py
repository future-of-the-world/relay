"""Gate slots: `relay gate` takes one of N slots shared by the machine before it runs the gate command.

Every slot folder is under a temp RELAY_HOME (the Fixture sets it), never the live ~/.relay.
"""
import fcntl
import os
import queue
import signal
import subprocess
import sys
import threading
import time
import unittest
from unittest import mock

from test_gate import RELAY, Fixture, git, read, write

import relay_gate

BOUND = 30      # seconds any wait in these tests may last: with the feature broken a test fails inside it instead of hanging the gate

# a gate that says it started, then waits for the test to let it go (polling a file, no fixed sleep in the test);
# it also ends when the test's temp folder is gone, so a failed test leaves no polling process
HOLD = 'echo $$ > .ci/pid\necho run >> "%s"\ntouch .ci/started\nwhile [ ! -f "%s" ] && [ -d "%s" ]; do sleep 0.05; done\nexit 0\n'


class Slots(Fixture):
    def setUp(self):
        super().setUp()
        self.env["RELAY_GATE_SLOTS"] = "1"
        self.release = os.path.join(self.tmp, "release")
        self.counter = os.path.join(self.tmp, "runs")
        self.repo(gate=HOLD % (self.counter, self.release, self.tmp))
        self.wt2 = os.path.join(self.main, ".worktrees", "y")
        git(self.main, "worktree", "add", "-q", self.wt2, "-b", "wt/y")
        write(os.path.join(self.wt2, "lib", "b.py"), "b\n")
        git(self.wt2, "add", "-A")
        git(self.wt2, "commit", "-q", "-m", "work")

    def start(self, cwd):
        proc = subprocess.Popen([sys.executable, RELAY, "gate"], cwd=cwd, env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                preexec_fn=lambda: signal.signal(signal.SIGINT, signal.SIG_DFL))      # a detached run ignores SIGINT and the child would inherit that
        self.addCleanup(self.reap, proc)
        return proc

    def reap(self, proc):
        write(self.release, "go\n")        # a gate command left polling ends, even when the test failed before it released it
        proc.kill()
        proc.wait()
        proc.stdout.close()
        proc.stderr.close()

    def wait_until(self, condition):
        deadline = time.monotonic() + BOUND
        while not condition():
            if time.monotonic() > deadline:
                self.fail("condition not reached within %d s" % BOUND)
            time.sleep(0.01)

    def wait_for(self, path):
        self.wait_until(lambda: os.path.exists(path))

    def line(self, proc):
        """The next stderr line of `proc`, failing the test when none comes within BOUND."""
        box = queue.Queue()
        threading.Thread(target=lambda: box.put(proc.stderr.readline()), daemon=True).start()
        try:
            return box.get(timeout=BOUND).strip()
        except queue.Empty:
            self.fail("no line on stderr within %d s" % BOUND)

    def runs(self):
        return len(read(self.counter).splitlines())

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
        self.wait_for(os.path.join(self.wt, ".ci", "started"))
        second = self.start(self.wt2)
        # B's waiting line is the first thing it prints; reading it blocks until B has looked at the slot
        self.assertEqual(self.line(second), "gate: waiting for a free gate slot (1 busy)")
        self.assertFalse(os.path.exists(os.path.join(self.wt2, ".ci", "started")))     # B holds back while A holds the slot
        write(self.release, "go\n")
        self.assertEqual(first.wait(timeout=BOUND), 0)
        self.assertEqual(second.wait(timeout=BOUND), 0)
        head = git(self.wt2, "rev-parse", "HEAD~1")        # the log commit is on top of the gated commit
        lines = read(os.path.join(self.wt2, ".relay", "checks", head + ".gate.log")).splitlines()
        self.assertRegex(lines[2], r"^wait \d+\.\d$")

    def test_a_gate_killed_with_sigkill_frees_its_slot(self):
        """N=1: while A runs the slot is locked; after SIGKILL of A the lock is free (the OS drops it), and B does not wait."""
        first = self.start(self.wt)
        self.wait_for(os.path.join(self.wt, ".ci", "started"))
        self.assertFalse(self.slot_is_free())
        first.kill()
        first.wait(timeout=BOUND)
        self.assertTrue(self.slot_is_free())
        write(self.release, "go\n")        # lets A's orphaned command end, and B's command go straight through
        second = subprocess.run([sys.executable, RELAY, "gate"], cwd=self.wt2, env=self.env, capture_output=True, text=True, timeout=BOUND)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertNotIn("waiting", second.stderr)

    def test_the_reused_path_takes_no_slot(self):
        """A green gate for the same code is reported while another process holds the only slot: no wait, no hang."""
        write(self.release, "go\n")
        done = subprocess.run([sys.executable, RELAY, "gate"], cwd=self.wt, env=self.env, capture_output=True, text=True, timeout=BOUND)
        self.assertEqual(done.returncode, 0, done.stderr)
        busy = open(os.path.join(self.env["RELAY_HOME"], "gate-slots", "slot-0"), "a")
        self.addCleanup(busy.close)
        fcntl.flock(busy, fcntl.LOCK_EX | fcntl.LOCK_NB)      # fails (and so fails the test) if the first gate left the slot held
        again = subprocess.run([sys.executable, RELAY, "gate"], cwd=self.wt, env=self.env, capture_output=True, text=True, timeout=BOUND)
        self.assertEqual(again.returncode, 0, again.stderr)
        self.assertNotIn("waiting", again.stderr)

    def test_a_bad_slot_count_is_refused(self):
        self.env["RELAY_GATE_SLOTS"] = "none"
        done = subprocess.run([sys.executable, RELAY, "gate"], cwd=self.wt, env=self.env, capture_output=True, text=True, timeout=BOUND)
        self.assertEqual(done.returncode, 1)
        self.assertIn("RELAY_GATE_SLOTS", done.stderr)

    def test_a_gate_stopped_with_sigterm_ends_its_command_before_the_slot_is_free(self):
        """N=1: SIGTERM to A's relay process ends A's command (its process group) too; only then can B take the slot."""
        first = self.start(self.wt)
        pid_file = os.path.join(self.wt, ".ci", "pid")
        self.wait_for(os.path.join(self.wt, ".ci", "started"))
        command_pid = int(read(pid_file))
        first.terminate()
        first.wait(timeout=BOUND)

        def gone():
            try:
                os.kill(command_pid, 0)
            except ProcessLookupError:
                return True
            return False
        # worked out: A's command is `sh` started in its own session; the gate kills that group before it exits, so by now the pid is gone
        self.assertTrue(gone())
        self.assertTrue(self.slot_is_free())

    def test_sigint_on_a_waiting_gate_exits_without_running_its_command(self):
        first = self.start(self.wt)
        self.wait_for(os.path.join(self.wt, ".ci", "started"))
        second = self.start(self.wt2)
        self.assertEqual(self.line(second), "gate: waiting for a free gate slot (1 busy)")
        second.send_signal(signal.SIGINT)
        self.assertNotEqual(second.wait(timeout=BOUND), 0)
        self.assertFalse(os.path.exists(os.path.join(self.wt2, ".ci", "started")))
        self.assertEqual(self.runs(), 1)        # only A ran
        self.assertIsNone(first.poll())

    def test_a_gate_whose_head_moved_during_the_wait_refuses(self):
        first = self.start(self.wt)
        self.wait_for(os.path.join(self.wt, ".ci", "started"))
        second = self.start(self.wt2)
        self.assertEqual(self.line(second), "gate: waiting for a free gate slot (1 busy)")
        write(os.path.join(self.wt2, "lib", "c.py"), "c\n")
        git(self.wt2, "add", "-A")
        git(self.wt2, "commit", "-q", "-m", "more")
        write(self.release, "go\n")
        first.wait(timeout=BOUND)
        self.assertEqual(second.wait(timeout=BOUND), 1)
        self.assertIn("moved", second.stderr.read())
        self.assertEqual(self.runs(), 1)        # B never ran its command

    def test_a_green_log_that_appears_during_the_wait_is_reported_without_a_run(self):
        """A holds the slot; B1 and B2 gate the same code and both wait. After A, one of them runs (2 runs in all); the other finds that log and runs nothing."""
        first = self.start(self.wt)
        self.wait_for(os.path.join(self.wt, ".ci", "started"))
        b1, b2 = self.start(self.wt2), self.start(self.wt2)
        self.assertEqual(self.line(b1), "gate: waiting for a free gate slot (1 busy)")
        self.assertEqual(self.line(b2), "gate: waiting for a free gate slot (1 busy)")
        write(self.release, "go\n")
        for proc in (first, b1, b2):
            self.assertEqual(proc.wait(timeout=BOUND), 0)
        self.assertEqual(self.runs(), 2)        # A and one B; three would mean the second B ran the gate again

    def test_the_slot_folder_comes_from_the_given_environ(self):
        """run() with environ naming RELAY_HOME puts the slot files there, not under the process's own RELAY_HOME."""
        other = os.path.join(self.tmp, "other-home")
        write(self.release, "go\n")
        with mock.patch.dict(os.environ, {"RELAY_HOME": other}):
            code, _, _ = relay_gate.run(self.wt, environ=self.env)
        self.assertEqual(code, 0)
        self.assertTrue(os.path.isdir(os.path.join(self.env["RELAY_HOME"], "gate-slots")))
        self.assertFalse(os.path.exists(os.path.join(other, "gate-slots")))


if __name__ == "__main__":
    unittest.main()
