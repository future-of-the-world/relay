"""E: the shared gate Fixture's cleanup stops what its worktree locks name after the folder is removed, then fails the test.
Each case runs an inner Fixture test under a runner of its own and looks at its outcome."""
import io
import os
import signal
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from typing import Callable
from unittest import mock

from test_gate import RELAY, Fixture, relay_procs, write
from pidfile import wait_pid

import leaked_gates
import relay_gate

BOUND = 30
FOREVER = "echo $$ > .ci/pid\ntouch .ci/started\nwhile true; do sleep 0.05; done\n"      # no folder check: it never ends by itself
CHECKED = 'echo $$ > .ci/pid\ntouch .ci/started\nwhile [ -d "%s" ]; do sleep 0.05; done\n'      # ends when the fixture's folder is gone


def run_inner(body: Callable[[Fixture], None]) -> tuple[unittest.TestResult, Fixture]:
    """Run `body(self)` as a Fixture test under its own runner; returns (result, the inner test instance)."""
    class Inner(Fixture):
        def runTest(self):
            body(self)
    test = Inner()
    result = unittest.TextTestRunner(stream=io.StringIO()).run(unittest.TestSuite([test]))
    result.problems = result.failures + result.errors      # a cleanup's AssertionError is a failure
    return result, test


def start_gate_then_kill_it(test: Fixture, script: str, folder: str) -> None:
    """The gate runs `script` (kept in `folder`, outside the fixture's folders); once it runs, the gate (not its command) is SIGKILLed, so
    the command is left holding the lock. The script's path names no folder that the fixture's cleanup deletes, so no other lane's real
    gate (which sweeps the real temporary folders) takes the command for a dead test's leftover while E waits for it."""
    path = os.path.join(folder, "loop.sh")
    write(path, "#!/bin/sh\n" + script, 0o700)
    test.repo(gate="exec /bin/sh %s\n" % path)
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
    def setUp(self) -> None:
        self.folder = tempfile.mkdtemp(prefix="script-")      # lives until this test ends, longer than the inner fixture's folders
        self.addCleanup(shutil.rmtree, self.folder, True)

    def test_a_command_that_outlives_its_folder_is_stopped_and_the_test_fails_naming_it(self):
        """A loop with no folder check, its gate killed: after rmtree it is still running. E stops it and the inner test fails with its pid."""
        result, inner = run_inner(lambda t: start_gate_then_kill_it(t, FOREVER, self.folder))
        self.addCleanup(relay_procs.send, inner.pid, False, signal.SIGKILL)
        self.assertEqual(len(result.problems), 1, result.problems)
        message = result.problems[0][1]
        self.assertIn("left gate processes running", message)
        self.assertIn(str(inner.pid), message)
        deadline = time.monotonic() + BOUND
        while relay_procs.is_alive(inner.pid) and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertFalse(relay_procs.is_alive(inner.pid))

    def test_a_sweep_of_the_real_roots_during_E_s_wait_does_not_take_the_command(self):
        """Another lane's gate sweeps the real temporary folders at the moment E waits for the lock: it finds nothing to stop (the
        command's script is outside the deleted folders), so the inner test still fails naming the pid and this test passes."""
        seen = []
        original = Fixture.lock_freed      # E calls it right after the folder is removed

        def sweeping(handle, grace):
            seen.extend(relay_gate.sweep(relay_gate.temp_roots(), lambda: [p for p in relay_procs.read_procs() if p.pid == box["pid"]],
                                         relay_procs.working_folders, [os.getpid()]))
            return original(handle, grace)
        box = {}

        def body(t):
            start_gate_then_kill_it(t, FOREVER, self.folder)
            box["pid"] = t.pid
        with mock.patch.object(Fixture, "lock_freed", staticmethod(sweeping)):
            result, inner = run_inner(body)
        self.addCleanup(relay_procs.send, inner.pid, False, signal.SIGKILL)
        self.assertEqual(seen, [])
        self.assertEqual(len(result.problems), 1, result.problems)
        self.assertIn(str(inner.pid), result.problems[0][1])

    def test_a_loop_that_checks_its_folder_ends_by_itself_and_the_test_passes(self):
        """The correct shape (test_gate_slots' HOLD): the loop ends within the grace once the folder is removed; nothing is stopped, nothing fails."""
        def body(t):
            start_gate_then_kill_it(t, CHECKED % t.tmp, self.folder)
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
