"""A test's `relay gate` never outlives its test runner: when the runner's process group is stopped, the gate and the command
it started end too (findings F1, F2 of the review of a-test-leaves-a-real-gate-running-that-holds-a-s)."""
import os
import shutil
import signal
import subprocess
import sys
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))

RUNNER = '''
import signal
import sys
signal.signal(signal.SIGINT, signal.default_int_handler)      # a job started in the background has SIGINT ignored; a terminal's Ctrl-C does not
sys.path.insert(0, %r)
import test_gate
f = test_gate.Fixture("setUp")
f.setUp()
f.repo(gate='echo $$ > "%%s/pid"\\nexec sleep 600\\n' %% f.tmp)
print(f.tmp, flush=True)
f.gate(f.wt)
''' % HERE

WAIT = 30      # seconds a condition has to become true; it is polled, so a pass returns at once


def until(condition):
    deadline = time.monotonic() + WAIT
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.05)
    return condition()


def alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


class RunnerStopped(unittest.TestCase):
    def stop_runner_group_with(self, sig):
        """A runner (its own process group) runs Fixture.gate on a command that sleeps; its group gets `sig`. Returns the
        command's pid once it is running, and the runner."""
        runner = subprocess.Popen([sys.executable, "-c", RUNNER], stdout=subprocess.PIPE, text=True, start_new_session=True)
        self.addCleanup(runner.wait)
        tmp = runner.stdout.readline().strip()
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        pidfile = os.path.join(tmp, "pid")
        self.assertTrue(until(lambda: os.path.exists(pidfile) and open(pidfile).read().strip()), "the gate command never started")
        pid = int(open(pidfile).read())

        def cleanup():
            for target in (lambda: os.killpg(runner.pid, signal.SIGKILL), lambda: os.kill(pid, signal.SIGKILL)):
                try:
                    target()
                except OSError:      # already gone (macOS answers PermissionError for a finished group)
                    pass
        self.addCleanup(cleanup)
        os.killpg(runner.pid, sig)
        return pid

    def test_f1_a_stopped_runner_group_leaves_no_gate_command(self):
        """F1: SIGTERM to the runner's group. The gate shares the group, ends its command, and nothing is left. With the gate
        in a session of its own the sleep keeps running (alive after WAIT s)."""
        pid = self.stop_runner_group_with(signal.SIGTERM)
        self.assertTrue(until(lambda: not alive(pid)), "the gate command is still running after its runner was stopped")

    def test_f2_an_interrupted_runner_leaves_no_gate_command(self):
        """F2: SIGINT (Ctrl-C) to the runner's group. The gate is ended by a signal it handles, so its finally kills the
        command; a SIGKILL of the gate skips that and leaves the sleep running."""
        pid = self.stop_runner_group_with(signal.SIGINT)
        self.assertTrue(until(lambda: not alive(pid)), "the gate command is still running after its runner was interrupted")


if __name__ == "__main__":
    unittest.main()
