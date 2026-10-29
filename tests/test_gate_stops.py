"""A test's `relay gate` never outlives its test runner: when the runner's process group is stopped, the gate and the command
it started end too (findings F1, F2 of the review of a-test-leaves-a-real-gate-running-that-holds-a-s)."""
import os
import shutil
import signal
import subprocess
import sys
import time
import unittest
from typing import Any
from unittest import mock

from pidfile import wait_pid

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

WAIT = 600     # seconds a condition has to become true; it is polled, so a pass returns at once


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
    def test_a_gate_command_ended_by_a_signal_leaves_a_line_in_the_gate_log(self):
        """Live case 29 Oct: a fixture gate script was killed by SIGTERM and the log only said 143. The script stops itself with
        SIGTERM (killed by a signal, returncode -15): the log must name SIGTERM and say the sender is unknown."""
        import test_gate
        import relay_gate
        f = test_gate.Fixture("setUp")
        f.setUp()
        self.addCleanup(f.doCleanups)
        f.repo(gate="kill -TERM $$\n")
        code, log, _ = relay_gate.run(f.wt, environ=f.env)
        self.assertEqual(code, 143)      # 128 + 15
        text = test_gate.read(log)
        self.assertIn("gate command ended by SIGTERM (sender unknown", text)

    def stop_runner_group_with(self, sig):
        """A runner (its own process group) runs Fixture.gate on a command that sleeps; its group gets `sig`. Returns the
        command's pid once it is running, and the runner."""
        runner = subprocess.Popen([sys.executable, "-c", RUNNER], stdout=subprocess.PIPE, text=True, start_new_session=True)
        self.addCleanup(runner.wait)
        tmp = runner.stdout.readline().strip()
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        pidfile = os.path.join(tmp, "pid")
        pid = wait_pid(pidfile, WAIT)

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


class StopWhilePopenReturns(unittest.TestCase):
    def test_f3_a_stop_between_the_command_starting_and_popen_returning_leaves_no_command(self):
        """F3 (the cause of the flaky F2): the runner's SIGINT can land after the command runs but before Popen returns, when
        the gate has no process to kill. The signal is sent from inside a wrapped Popen, right after the real one started the
        command and the command wrote its pid. Without the hold the gate exits with the sleep alive."""
        import test_gate
        import relay_gate
        f = test_gate.Fixture("setUp")
        f.setUp()
        self.addCleanup(f.doCleanups)
        f.repo(gate='echo $$ > "%s/pid"\nexec sleep 600\n' % f.tmp)
        real = subprocess.Popen
        started = []

        def popen_then_stop(*args: Any, **kwargs: Any) -> "subprocess.Popen[bytes]":
            proc = real(*args, **kwargs)
            if not kwargs.get("start_new_session"):      # only the gate command's own start (git and others use Popen too)
                return proc
            started.append(proc)
            wait_pid(os.path.join(f.tmp, "pid"), WAIT)      # the command is running
            os.kill(os.getpid(), signal.SIGINT)      # the stop lands before Popen returns
            return proc

        def cleanup() -> None:
            for proc in started:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except OSError:
                    pass
        self.addCleanup(cleanup)
        old = signal.signal(signal.SIGINT, signal.default_int_handler)
        self.addCleanup(signal.signal, signal.SIGINT, old)
        with mock.patch.object(relay_gate.subprocess, "Popen", popen_then_stop):
            with self.assertRaises(KeyboardInterrupt):
                relay_gate.run(f.wt, environ=f.env)
        pid = wait_pid(os.path.join(f.tmp, "pid"), WAIT)
        self.assertTrue(until(lambda: not alive(pid)), "the gate command is still running after the stop landed during Popen")

    def test_f2_review_a_stop_held_while_popen_raises_still_stops_the_gate(self):
        """Review F2: SIGTERM lands while Popen runs and Popen raises OSError. The gate exits 143 and commits no log (it used to
        write 'could not start', exit 127 and commit a log)."""
        import test_gate
        import relay_gate
        f = test_gate.Fixture("setUp")
        f.setUp()
        self.addCleanup(f.doCleanups)
        f.repo(gate="exit 0\n")
        real = subprocess.Popen

        def popen_stop_then_fail(*args: Any, **kwargs: Any) -> "subprocess.Popen[bytes]":
            if not kwargs.get("start_new_session"):
                return real(*args, **kwargs)
            os.kill(os.getpid(), signal.SIGTERM)
            raise OSError("cannot start")
        old = signal.getsignal(signal.SIGTERM)
        self.addCleanup(signal.signal, signal.SIGTERM, old)
        before = subprocess.run(["git", "-C", f.wt, "rev-parse", "HEAD"], capture_output=True, text=True).stdout
        with mock.patch.object(relay_gate.subprocess, "Popen", popen_stop_then_fail):
            with self.assertRaises(SystemExit) as caught:
                relay_gate.run(f.wt, environ=f.env)
        self.assertEqual(caught.exception.code, 143)      # 128 + SIGTERM(15)
        after = subprocess.run(["git", "-C", f.wt, "rev-parse", "HEAD"], capture_output=True, text=True).stdout
        self.assertEqual(before, after)      # no log committed

    def test_f3_review_an_ignored_sigint_stays_ignored_through_the_hold(self):
        """Review F3: SIGINT = SIG_IGN before the hold stays SIG_IGN during it and after release; SIGTERM is still held."""
        import relay_gate
        old_int = signal.signal(signal.SIGINT, signal.SIG_IGN)
        old_term = signal.getsignal(signal.SIGTERM)
        self.addCleanup(signal.signal, signal.SIGINT, old_int)
        self.addCleanup(signal.signal, signal.SIGTERM, old_term)
        held, release = relay_gate.hold_stops()
        self.assertEqual(signal.getsignal(signal.SIGINT), signal.SIG_IGN)
        self.assertNotEqual(signal.getsignal(signal.SIGTERM), old_term)
        release()
        self.assertEqual(signal.getsignal(signal.SIGINT), signal.SIG_IGN)
        self.assertEqual(signal.getsignal(signal.SIGTERM), old_term)
        self.assertEqual(held, [])


if __name__ == "__main__":
    unittest.main()
