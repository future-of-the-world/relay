"""A test's `relay gate` never outlives its test runner: when the runner's process group is stopped, the gate and the command
it started end too (findings F1, F2 of the review of a-test-leaves-a-real-gate-running-that-holds-a-s)."""
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
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


def patch_signal_log(case, path):
    """Point the signal log at `path` for one test (the environment is restored after)."""
    patcher = mock.patch.dict(os.environ, {"RELAY_SIGNAL_LOG": path}); patcher.start(); case.addCleanup(patcher.stop)
    return path


NO_LOGGED_SENDER = "no relay sender that logs its signals sent it"


class RunnerStopped(unittest.TestCase):
    def test_a_gate_command_ended_by_a_signal_leaves_a_line_in_the_gate_log(self):
        """Live case 29 Oct: a fixture gate script was killed by SIGTERM and the log only said 143. The script stops itself with
        SIGTERM (killed by a signal, returncode -15): the log must name SIGTERM and say relay did not send it (nothing in the signal log)."""
        import test_gate
        import relay_gate
        f = test_gate.Fixture("setUp")
        f.setUp()
        self.addCleanup(f.doCleanups)
        patcher = mock.patch.dict(os.environ, test_gate.GIT_ENV); patcher.start(); self.addCleanup(patcher.stop)      # relay_gate commits its log with this process's environment
        logdir = tempfile.mkdtemp(); self.addCleanup(shutil.rmtree, logdir, ignore_errors=True)
        patch_signal_log(self, os.path.join(logdir, "signals.log"))
        f.repo(gate="kill -TERM $$\n")
        code, log, _ = relay_gate.run(f.wt, environ=f.env)
        self.assertEqual(code, 143)      # 128 + 15
        text = test_gate.read(log)
        self.assertIn("gate command ended by SIGTERM, no relay sender that logs its signals sent it", text)      # F4: the claim is only what the log can show
        self.assertNotIn("not sent by relay", text)
        self.assertNotIn("sent by relay:", text)

    def test_a_stop_relay_sends_to_the_command_is_named_in_the_gate_log(self):
        """Each sender of relay is named: here relay's own stop (relay_procs.stop, as the reclaim and the sweep call it) ends the
        gate's command; the gate log must carry the signal log's line: relay, the sender's pid, SIGTERM, the command's group and the reason."""
        import test_gate
        import relay_gate
        import relay_procs
        f = test_gate.Fixture("setUp")
        f.setUp()
        self.addCleanup(f.doCleanups)
        patcher = mock.patch.dict(os.environ, test_gate.GIT_ENV); patcher.start(); self.addCleanup(patcher.stop)
        logdir = tempfile.mkdtemp(); self.addCleanup(shutil.rmtree, logdir, ignore_errors=True)
        patch_signal_log(self, os.path.join(logdir, "signals.log"))
        f.repo(gate='echo $$ > "%s/pid"\nexec sleep 600\n' % f.tmp)

        def stopper():
            pid = wait_pid(os.path.join(f.tmp, "pid"), WAIT)
            relay_procs.stop([(pid, True)], "test: a hang bound")      # the command is its own group leader (start_new_session)

        thread = threading.Thread(target=stopper); thread.start(); self.addCleanup(thread.join)
        code, log, _ = relay_gate.run(f.wt, environ=f.env)
        self.assertEqual(code, 143)
        text = test_gate.read(log)
        self.assertIn("gate command ended by SIGTERM, sent by relay: relay pid %d sent SIGTERM to group" % os.getpid(), text)
        self.assertIn(": test: a hang bound", text)

    def test_every_sender_writes_a_line_to_the_signal_log(self):
        """relay_procs.send, the gate's time-limit stop (relay_ci.stop_tree) each leave a line naming relay, the target and the reason."""
        import relay_ci
        import relay_procs
        logdir = tempfile.mkdtemp(); self.addCleanup(shutil.rmtree, logdir, ignore_errors=True)
        path = os.path.join(logdir, "signals.log")
        patch_signal_log(self, path)
        sleeper = subprocess.Popen(["sleep", "600"]); self.addCleanup(sleeper.wait)
        relay_procs.send(sleeper.pid, False, signal.SIGTERM, "test: send")
        sleeper.wait()
        other = subprocess.Popen(["sleep", "600"]); self.addCleanup(other.wait)
        relay_ci.stop_tree([other.pid], other.pid)
        other.wait()
        text = open(path, encoding="utf-8").read()
        self.assertIn("relay pid %d sent SIGTERM to pid %d: test: send" % (os.getpid(), sleeper.pid), text)
        self.assertIn("relay pid %d sent SIGTERM to pid %d: bin/ci: the time limit" % (os.getpid(), other.pid), text)

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

    def test_a_stop_landing_in_the_cleanup_log_write_still_kills_the_command_group(self):
        """The flaky hang of F2: the runner's SIGTERM can land while the gate's cleanup writes its signal-log line, and the
        exception then skipped the kill, leaving the command's group alive. The command starts a background sleep and exits; the
        log write is made to raise (as a stop would); the sleep must still be killed. Cleanup that logs before it kills leaves it alive."""
        import test_gate
        import relay_gate
        import relay_procs
        f = test_gate.Fixture("setUp")
        f.setUp()
        self.addCleanup(f.doCleanups)
        f.repo(gate='sleep 600 &\necho $! > "%s/pid"\nexit 0\n' % f.tmp)

        def stop_in_log_write(*args: Any, **kwargs: Any) -> None:
            raise SystemExit(143)
        with mock.patch.object(relay_procs, "record_sent", stop_in_log_write):
            with self.assertRaises(SystemExit):
                relay_gate.run(f.wt, environ=f.env)
        pid = wait_pid(os.path.join(f.tmp, "pid"), WAIT)
        try:
            self.assertTrue(until(lambda: not alive(pid)), "the command's background process survived a stop in the cleanup")
        finally:
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass

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


class SenderReasons(unittest.TestCase):
    """Review F3, F5, F6, F7 of a-sigterm-in-a-gate-does-not-name-its-sender."""

    def log(self):
        logdir = tempfile.mkdtemp(); self.addCleanup(shutil.rmtree, logdir, ignore_errors=True)
        return patch_signal_log(self, os.path.join(logdir, "signals.log"))

    def test_f3_the_leak_scan_names_itself_and_the_folder(self):
        """F3: leaked_gates.stop on a sleeper under the folder writes one line naming the leak scan and the folder, not 'no reason given'."""
        import leaked_gates
        path = self.log()
        folder = os.path.realpath(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree, folder, ignore_errors=True)
        sleeper = subprocess.Popen(["sleep", "600"], cwd=folder); self.addCleanup(sleeper.wait)
        with mock.patch.object(leaked_gates, "find", lambda f, notes=None: [(sleeper.pid, "sleep 600")]):
            leaked_gates.stop(folder)
        text = open(path, encoding="utf-8").read()
        self.assertIn("test run leak scan: still running under the run's temporary folder %s" % folder, text)
        self.assertNotIn("no reason given", text)

    def test_f5_the_sweep_stops_with_a_reason_holding_the_leftovers_why(self):
        """F5: a leftover in a deleted folder is stopped with a reason starting 'leftover sweep: ' and holding 'folder deleted'."""
        import relay_gate
        import relay_procs
        root = os.path.realpath(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        os.makedirs(os.path.join(root, "relay-run-X"))
        seen = []
        me = [relay_procs.Proc(999, 50, 50, time.time() - 5, "python3 relay gate"), relay_procs.Proc(50, 40, 50, time.time() - 5, "zsh")]
        gone = relay_procs.Proc(1469, 1, 1469, time.time() - 5, "/bin/sh %s/relay-run-X/relay-gate-Y/gate.sh" % root)
        with mock.patch.object(relay_procs, "stop", lambda targets, reason="": (seen.append(reason), [])[1]):
            relay_gate.sweep([root], lambda: me + [gone], lambda pids: {}, [999])
        self.assertEqual(len(seen), 1)
        self.assertTrue(seen[0].startswith("leftover sweep: "), seen)
        self.assertIn("folder deleted", seen[0])

    def test_f5_the_reclaim_stops_the_group_with_its_reason(self):
        """F5: reclaim of a held lock of an ended gate stops the holder's group with the reclaim reason (the signal log line)."""
        import relay_gate
        import relay_procs
        path = self.log()
        tmp = tempfile.mkdtemp(); self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        lock = os.path.join(tmp, "lockfile")
        holder = subprocess.Popen([sys.executable, "-c", "import fcntl,sys,time; f=open(sys.argv[1], 'w'); fcntl.flock(f, fcntl.LOCK_EX); print('locked', flush=True); time.sleep(600)", lock],
                                  stdout=subprocess.PIPE, text=True, start_new_session=True)
        self.addCleanup(holder.wait); self.addCleanup(holder.stdout.close)
        self.assertEqual(holder.stdout.readline().strip(), "locked")
        done = subprocess.Popen([sys.executable, "-c", "pass"]); done.wait()
        with open(lock, "w") as handle:
            handle.write("%d %d\n" % (done.pid, holder.pid))
        with mock.patch.object(relay_procs, "STOP_GRACE", 0.3):
            text_in_lock = "%d %d\n" % (done.pid, holder.pid)
            self.assertTrue(relay_gate.reclaim(lock, text_in_lock, lambda line: None))
        text = open(path, encoding="utf-8").read()
        self.assertIn("sent SIGTERM to group %d: reclaim: the gate that held the worktree lock ended" % holder.pid, text)

    def test_f5_f6_a_gate_whose_command_ended_logs_that_cleanup(self):
        """F5 pass 3 and F6 pass 2: the gate's cleanup line names the command's group and says 'its command ended'."""
        path = self.log()
        import test_gate
        import relay_gate
        f = test_gate.Fixture("setUp"); f.setUp(); self.addCleanup(f.doCleanups)
        patcher = mock.patch.dict(os.environ, test_gate.GIT_ENV); patcher.start(); self.addCleanup(patcher.stop)
        f.repo(gate='echo $$ > "%s/pid"\nexit 0\n' % f.tmp)
        relay_gate.run(f.wt, environ=f.env)
        pid = wait_pid(os.path.join(f.tmp, "pid"), WAIT)
        self.assertIn("sent SIGKILL to group %d: gate: its command ended" % pid, open(path, encoding="utf-8").read())

    def test_f6_a_gate_stopped_while_its_command_runs_names_the_stop(self):
        """F6: SIGTERM to the gate while its command sleeps: the group's SIGKILL line says the gate was stopped, not that the command ended."""
        import test_gate
        import relay_gate
        path = self.log()
        f = test_gate.Fixture("setUp"); f.setUp(); self.addCleanup(f.doCleanups)
        patcher = mock.patch.dict(os.environ, test_gate.GIT_ENV); patcher.start(); self.addCleanup(patcher.stop)
        f.repo(gate='echo $$ > "%s/pid"\nexec sleep 600\n' % f.tmp)
        old = signal.getsignal(signal.SIGTERM); self.addCleanup(signal.signal, signal.SIGTERM, old)

        def stopper():
            wait_pid(os.path.join(f.tmp, "pid"), WAIT)
            os.kill(os.getpid(), signal.SIGTERM)
        thread = threading.Thread(target=stopper); thread.start(); self.addCleanup(thread.join)
        with self.assertRaises(SystemExit):
            relay_gate.run(f.wt, environ=f.env)
        pid = wait_pid(os.path.join(f.tmp, "pid"), WAIT)
        text = open(path, encoding="utf-8").read()
        self.assertIn("sent SIGKILL to group %d: gate: the gate was stopped while its command ran" % pid, text)
        self.assertNotIn("its command ended", text)

    def test_f7_an_unnamed_signal_is_found_by_the_reader(self):
        """F7 pass 2: a line 'sent signal 99 to pid N' is found by sent_by_relay."""
        import relay_procs
        self.log()
        relay_procs.record_sent(4242, False, 99, "x")
        self.assertIn("sent signal 99 to pid 4242: x", relay_procs.sent_by_relay(4242, 0))

    def test_f7_an_unreadable_log_is_not_reported_as_not_sent_by_relay(self):
        """F7 pass 1: a log that exists but cannot be read (a directory here) says so; a missing log and a log with no line say 'not sent by relay'."""
        import relay_gate
        path = self.log()
        self.assertIn(NO_LOGGED_SENDER, relay_gate.signal_line(15, 4242, 0))      # pass 3 (nothing was ever sent: no file yet)
        os.mkdir(path)
        text = relay_gate.signal_line(15, 4242, 0)
        self.assertIn("could not be read", text)
        self.assertNotIn("not sent by relay", text)
        os.rmdir(path)
        open(path, "w").write("t=1.000 relay pid 1 sent SIGTERM to pid 7: other\n")
        self.assertIn(NO_LOGGED_SENDER, relay_gate.signal_line(15, 4242, 0))


if __name__ == "__main__":
    unittest.main()
