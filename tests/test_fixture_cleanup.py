"""E: the shared gate Fixture's cleanup stops what its worktree locks name after the folder is removed, then fails the test.
Each case runs an inner Fixture test under a runner of its own and looks at its outcome."""
import io
import os
import signal
import subprocess
import sys
import time
import unittest

from test_gate import RELAY, Fixture, relay_procs, write
from pidfile import wait_pid

import leaked_gates

BOUND = 30
FOREVER = "echo $$ > .ci/pid\ntouch .ci/started\nwhile true; do sleep 0.05; done\n"      # no folder check: it never ends by itself
CHECKED = 'echo $$ > .ci/pid\ntouch .ci/started\nwhile [ -d "%s" ]; do sleep 0.05; done\n'      # ends when the fixture's folder is gone


def run_inner(body):
    """Run `body(self)` as a Fixture test under its own runner; returns (result, the inner test instance)."""
    class Inner(Fixture):
        def runTest(self):
            body(self)
    test = Inner()
    result = unittest.TextTestRunner(stream=io.StringIO()).run(unittest.TestSuite([test]))
    result.problems = result.failures + result.errors      # a cleanup's AssertionError is a failure
    return result, test


def start_gate_then_kill_it(test, script):
    """The gate runs `script`; once it runs, the gate (not its command) is SIGKILLed, so the command is left holding the lock."""
    test.repo(gate=script)
    gate = subprocess.Popen([sys.executable, RELAY, "gate"], cwd=test.wt, env=test.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    deadline = time.monotonic() + BOUND
    while not os.path.exists(os.path.join(test.wt, ".ci", "started")):
        assert time.monotonic() < deadline, "the gate command never started"
        time.sleep(0.01)
    test.pid = wait_pid(os.path.join(test.wt, ".ci", "pid"))
    gate.kill()
    gate.wait()
    gate.stdout.close()
    gate.stderr.close()


class Cleanup(unittest.TestCase):
    def test_a_command_that_outlives_its_folder_is_stopped_and_the_test_fails_naming_it(self):
        """A loop with no folder check, its gate killed: after rmtree it is still running. E stops it and the inner test fails with its pid."""
        result, inner = run_inner(lambda t: start_gate_then_kill_it(t, FOREVER))
        self.addCleanup(relay_procs.send, inner.pid, False, signal.SIGKILL)
        self.assertEqual(len(result.problems), 1, result.problems)
        message = result.problems[0][1]
        self.assertIn("left gate processes running", message)
        self.assertIn(str(inner.pid), message)
        deadline = time.monotonic() + BOUND
        while relay_procs.is_alive(inner.pid) and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertFalse(relay_procs.is_alive(inner.pid))

    def test_a_loop_that_checks_its_folder_ends_by_itself_and_the_test_passes(self):
        """The correct shape (test_gate_slots' HOLD): the loop ends within the grace once the folder is removed; nothing is stopped, nothing fails."""
        def body(t):
            start_gate_then_kill_it(t, CHECKED % t.tmp)
        result, inner = run_inner(body)
        self.addCleanup(relay_procs.send, inner.pid, False, signal.SIGKILL)
        self.assertTrue(result.wasSuccessful(), result.problems)
        self.assertFalse(relay_procs.is_alive(inner.pid))

    def test_a_group_that_does_not_hold_the_lock_is_left_alone(self):
        """The lock text names a live foreign group, but a foreign process holds the file: E fails the test (lock still held, holder not identified) and kills neither."""
        sleeper = subprocess.Popen(["sleep", "600"], start_new_session=True)
        self.addCleanup(sleeper.wait)
        self.addCleanup(sleeper.kill)
        box = {}

        def body(t):
            t.repo(gate="exit 0\n")
            lock = os.path.join(t.main, ".git", "relay-gate.lock")
            write(lock, "%d %d\n" % (2 ** 22 - 2, sleeper.pid))
            holder = subprocess.Popen([sys.executable, "-c", "import fcntl,sys,time; f=open(sys.argv[1]); fcntl.flock(f, fcntl.LOCK_EX); print('locked', flush=True); time.sleep(600)", lock],
                                      stdout=subprocess.PIPE, text=True, start_new_session=True)
            box["holder"] = holder
            holder.stdout.readline()
        def finish():
            box["holder"].kill()
            box["holder"].wait()
            box["holder"].stdout.close()
        self.addCleanup(finish)
        old = relay_procs.STOP_GRACE
        relay_procs.STOP_GRACE = 0.5      # E waits this long for a lock nobody will free
        try:
            import test_gate
            saved = test_gate.LEAK_GRACE
            test_gate.LEAK_GRACE = 0.5
            try:
                result, _ = run_inner(body)
            finally:
                test_gate.LEAK_GRACE = saved
        finally:
            relay_procs.STOP_GRACE = old
        self.assertEqual(len(result.problems), 1)
        self.assertIn("not identified", result.problems[0][1])
        self.assertIsNone(sleeper.poll())
        self.assertIsNone(box["holder"].poll())

    def test_a_child_that_closed_the_lock_file_is_beyond_E_and_the_end_of_run_scan_finds_it(self):
        """The stated limit: a Python child started in a new session closes inherited files, so E passes the test; leaked_gates.find (the scan under bin/ci) names it."""
        found = {}

        def body(t):
            script = ("python3 -c \"import subprocess,sys; p=subprocess.Popen(['sleep','300'], cwd=sys.argv[1], start_new_session=True); "
                      "open('.ci/pid','w').write('%d\\n' % p.pid)\" \"$PWD\"\ntouch .ci/started\nexit 0\n")
            t.repo(gate=script)
            done = t.gate(t.wt)
            assert done.returncode == 0, done.stderr
            t.pid = wait_pid(os.path.join(t.wt, ".ci", "pid"))
            found["scan"] = [pid for pid, _ in leaked_gates.find(t.tmp)]
        result, inner = run_inner(body)
        self.addCleanup(relay_procs.send, inner.pid, False, signal.SIGKILL)
        self.assertTrue(result.wasSuccessful(), result.problems)      # E does not see it
        self.assertIn(inner.pid, found["scan"])                     # the scan does


if __name__ == "__main__":
    unittest.main()
