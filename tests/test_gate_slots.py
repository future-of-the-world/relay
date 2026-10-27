"""Gate slots: `relay gate` takes one of N slots shared by the machine before it runs the gate command.

Every slot folder is under a temp RELAY_HOME (the Fixture sets it), never the live ~/.relay.
"""
import fcntl
import os
import queue
import re
import shlex
import signal
import subprocess
import sys
import threading
import time
import unittest
from unittest import mock

from test_gate import RELAY, Fixture, git, read, write
from pidfile import wait_pid

import relay_gate

WAITING = "gate: waiting for a free gate slot (all 1 busy; the limit stops gates slowing each other, the file $RELAY_HOME/gate-slots/count sets it)"
BOUND = 30      # seconds any wait in these tests may last: with the feature broken a test fails inside it instead of hanging the gate

# a gate that says it started, then waits for the test to let it go (polling a file, no fixed sleep in the test);
# it also ends when the test's temp folder is gone, so a failed test leaves no polling process
HOLD = 'echo $$ > .ci/pid\necho run >> "%s"\ntouch .ci/started\nwhile [ ! -f "%s" ] && [ -d "%s" ]; do sleep 0.05; done\nexit 0\n'


class Slots(Fixture):
    def setUp(self):
        super().setUp()
        self.set_slots("1")
        self.release = os.path.join(self.tmp, "release")
        self.counter = os.path.join(self.tmp, "runs")
        self.repo(gate=HOLD % (self.counter, self.release, self.tmp))
        self.wt2 = os.path.join(self.main, ".worktrees", "y")
        git(self.main, "worktree", "add", "-q", self.wt2, "-b", "wt/y")
        write(os.path.join(self.wt2, "lib", "b.py"), "b\n")
        git(self.wt2, "add", "-A")
        git(self.wt2, "commit", "-q", "-m", "work")

    def set_slots(self, value):
        folder = os.path.join(self.env["RELAY_HOME"], "gate-slots")
        os.makedirs(folder, exist_ok=True)
        write(os.path.join(folder, "count"), value + "\n")

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
        self.assertEqual(self.line(second), WAITING)
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

    def test_the_default_slot_count_comes_from_the_cores(self):
        """cores // 6, at least 1: 12 cores give 2 (the measured knee: 2 gates at once 698 s each, 3 at once 1058 s each); 4 cores give 1, 24 give 4."""
        self.assertEqual([relay_gate.default_slots(n) for n in (1, 4, 12, 24)], [1, 1, 2, 4])
        home = os.path.join(self.tmp, "nohome")
        self.assertEqual(relay_gate.slot_count(home, cores=12), 2)
        for cores, want in ((12, 2), (4, 1), (None, 1)):      # no setting: cores // 6, at least 1; os.cpu_count() None counts as 1
            with mock.patch("os.cpu_count", return_value=cores):
                self.assertEqual(relay_gate.slot_count(home), want)
        os.makedirs(os.path.join(home, "gate-slots"))
        write(os.path.join(home, "gate-slots", "count"), "5\n")
        self.assertEqual(relay_gate.slot_count(home, cores=12), 5)       # the machine's setting wins

    def test_gates_read_one_machine_setting_not_their_own_environment(self):
        """A gate started with RELAY_GATE_SLOTS=3 in its environment still obeys the file: with the file saying 1 the second gate waits."""
        self.env["RELAY_GATE_SLOTS"] = "3"
        first = self.start(self.wt)
        self.wait_for(os.path.join(self.wt, ".ci", "started"))
        second = self.start(self.wt2)
        self.assertEqual(self.line(second), WAITING)
        write(self.release, "go\n")
        for proc in (first, second):
            self.assertEqual(proc.wait(timeout=BOUND), 0)

    def test_with_two_slots_the_third_concurrent_gate_waits(self):
        """N=2 (the default on 12 cores): gates A and B run together, gate C prints the waiting line with its reason and does not
        start its command until A or B exits."""
        self.set_slots("2")
        wt3 = os.path.join(self.main, ".worktrees", "z")
        git(self.main, "worktree", "add", "-q", wt3, "-b", "wt/z")
        write(os.path.join(wt3, "lib", "c.py"), "c\n")
        git(wt3, "add", "-A")
        git(wt3, "commit", "-q", "-m", "work")
        first = self.start(self.wt)
        second = self.start(self.wt2)
        self.wait_for(os.path.join(self.wt, ".ci", "started"))
        self.wait_for(os.path.join(self.wt2, ".ci", "started"))
        third = self.start(wt3)
        self.assertEqual(self.line(third), WAITING.replace("all 1 busy", "all 2 busy"))
        self.assertFalse(os.path.exists(os.path.join(wt3, ".ci", "started")))
        write(self.release, "go\n")
        for proc in (first, second, third):
            self.assertEqual(proc.wait(timeout=BOUND), 0)
        self.assertEqual(self.runs(), 3)

    def test_a_bad_slot_count_is_refused(self):
        self.set_slots("none")
        done = subprocess.run([sys.executable, RELAY, "gate"], cwd=self.wt, env=self.env, capture_output=True, text=True, timeout=BOUND)
        self.assertEqual(done.returncode, 1)
        self.assertIn("gate-slots", done.stderr)

    def test_a_gate_stopped_with_sigterm_ends_its_command_before_the_slot_is_free(self):
        """N=1: SIGTERM to A's relay process ends A's command (its process group) too; only then can B take the slot."""
        first = self.start(self.wt)
        pid_file = os.path.join(self.wt, ".ci", "pid")
        self.wait_for(os.path.join(self.wt, ".ci", "started"))
        command_pid = wait_pid(pid_file)
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
        self.assertEqual(self.line(second), WAITING)
        second.send_signal(signal.SIGINT)
        self.assertNotEqual(second.wait(timeout=BOUND), 0)
        self.assertFalse(os.path.exists(os.path.join(self.wt2, ".ci", "started")))
        self.assertEqual(self.runs(), 1)        # only A ran
        self.assertIsNone(first.poll())

    def test_a_gate_whose_head_moved_during_the_wait_refuses(self):
        first = self.start(self.wt)
        self.wait_for(os.path.join(self.wt, ".ci", "started"))
        second = self.start(self.wt2)
        self.assertEqual(self.line(second), WAITING)
        write(os.path.join(self.wt2, "lib", "c.py"), "c\n")
        git(self.wt2, "add", "-A")
        git(self.wt2, "commit", "-q", "-m", "more")
        write(self.release, "go\n")
        first.wait(timeout=BOUND)
        self.assertEqual(second.wait(timeout=BOUND), 1)
        self.assertIn("moved", second.stderr.read())
        self.assertEqual(self.runs(), 1)        # B never ran its command

    def test_a_green_log_that_appears_during_the_wait_is_reported_without_a_run(self):
        """A holds the slot; B1 and B2 gate the same code in one worktree. One of them waits for the slot, the other for the
        worktree lock (which of the two is up to the race, so the two lines are compared sorted). After A, one of them runs
        (2 runs in all); the other finds that log and runs nothing."""
        first = self.start(self.wt)
        self.wait_for(os.path.join(self.wt, ".ci", "started"))
        b1, b2 = self.start(self.wt2), self.start(self.wt2)
        lines = sorted([self.line(b1), self.line(b2)])
        self.assertEqual(lines[0], WAITING)
        # the holder may have locked the file but not yet written its pid when B reads it: the line then says "unknown"
        self.assertRegex(lines[1], r"^gate: waiting for the gate already running in this worktree \(pid (\d+|unknown)\)$")
        write(self.release, "go\n")
        for proc in (first, b1, b2):
            self.assertEqual(proc.wait(timeout=BOUND), 0)
        self.assertEqual(self.runs(), 2)        # A and one B; three would mean the second B ran the gate again

    def test_t1_a_second_gate_in_one_worktree_waits_then_reuses_the_first_log(self):
        """T1: B starts in the worktree where A runs (a slot is free: N=2). B prints the worktree waiting line, its command
        never starts, and after A commits its log B reports it: 1 run, both exit 0, no zero byte in the log."""
        self.set_slots("2")
        first = self.start(self.wt)
        self.wait_for(os.path.join(self.wt, ".ci", "started"))
        second = self.start(self.wt)
        self.assertRegex(self.line(second), r"^gate: waiting for the gate already running in this worktree \(pid %d\)$" % first.pid)
        self.assertEqual(self.runs(), 1)        # B holds back although a slot is free
        write(self.release, "go\n")
        self.assertEqual(first.wait(timeout=BOUND), 0)
        self.assertEqual(second.wait(timeout=BOUND), 0)
        self.assertEqual(self.runs(), 1)
        head = git(self.wt, "rev-parse", "HEAD~1")
        self.assertNotIn("\0", read(os.path.join(self.wt, ".relay", "checks", head + ".gate.log")))

    def test_t2_a_second_gate_after_code_moved_refuses_and_never_runs(self):
        """T2: code is committed in the worktree while A runs and B waits. B ends with 'moved' and never runs; A, whose tree
        is no longer its commit, is refused too, with no log."""
        self.set_slots("2")
        head = git(self.wt, "rev-parse", "HEAD")
        first = self.start(self.wt)
        self.wait_for(os.path.join(self.wt, ".ci", "started"))
        second = self.start(self.wt)
        self.line(second)
        write(os.path.join(self.wt, "lib", "c.py"), "c\n")
        git(self.wt, "add", "-A")
        git(self.wt, "commit", "-q", "-m", "more")
        write(self.release, "go\n")
        self.assertEqual(first.wait(timeout=BOUND), 1)
        self.assertEqual(second.wait(timeout=BOUND), 1)
        self.assertIn("moved", second.stderr.read())
        self.assertEqual(self.runs(), 1)
        self.assertFalse(os.path.exists(os.path.join(self.wt, ".relay", "checks", head + ".gate.log")))

    def orphan_gone(self, pid_file):
        pid = wait_pid(pid_file)

        def gone():
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return True
            return False
        return gone

    def test_t3_a_killed_gate_leaves_the_worktree_locked_until_its_command_ends(self):
        """T3: SIGKILL of A's relay process while its command runs. B in the same worktree prints the waiting line and does
        not start its command (1 run) until A's orphan ends; then it runs (2 runs)."""
        self.set_slots("2")
        first = self.start(self.wt)
        self.wait_for(os.path.join(self.wt, ".ci", "started"))
        first.kill()
        first.wait(timeout=BOUND)
        second = self.start(self.wt)
        self.assertRegex(self.line(second), r"^gate: waiting for the gate already running in this worktree")
        self.assertEqual(self.runs(), 1)
        write(self.release, "go\n")        # A's orphaned command ends; the OS frees the lock
        self.assertEqual(second.wait(timeout=BOUND), 0)
        self.assertEqual(self.runs(), 2)

    def test_f1_waiting_line_after_sigkill_names_a_live_process(self):
        """F1: A's relay is SIGKILLed while its command runs; the line B prints names the command's group, which is alive
        (so a person can kill it), not the dead relay pid. A's relay pid is first.pid, the command's group is read from .ci/pid
        ($$ of the gate command, its own session leader)."""
        self.set_slots("2")
        first = self.start(self.wt)
        self.wait_for(os.path.join(self.wt, ".ci", "started"))
        command_pid = wait_pid(os.path.join(self.wt, ".ci", "pid"))
        first.kill()
        first.wait(timeout=BOUND)
        second = self.start(self.wt)
        match = re.match(r"^gate: waiting for the gate already running in this worktree \(pid (\d+)", self.line(second))
        self.assertIsNotNone(match)
        named = int(match.group(1))
        self.assertNotEqual(named, first.pid)
        self.assertEqual(named, command_pid)
        os.kill(named, 0)      # alive while B waits

    def test_f2_a_stray_holder_outside_the_group_is_named_as_such(self):
        """F2: the lock file names a dead relay and a dead group, yet the lock is held (a detached daemon): the line says a
        process outside the gate's group holds the lock file."""
        path = os.path.join(self.tmp, "lockfile")
        holder = open(path, "a+")
        self.addCleanup(holder.close)
        fcntl.flock(holder, fcntl.LOCK_EX)
        dead = subprocess.Popen([sys.executable, "-c", "pass"])
        dead.wait()
        write(path, "%d %d\n" % (dead.pid, dead.pid))
        lines = []
        waiter = threading.Thread(target=lambda: relay_gate.take_worktree_lock(path, lines.append), daemon=True)
        waiter.start()
        self.wait_until(lambda: lines)
        self.assertIn("outside the gate's process group still holds " + path, lines[0])
        fcntl.flock(holder, fcntl.LOCK_UN)
        waiter.join(BOUND)

    def test_t3_a_killed_gate_whose_command_has_ended_does_not_block_the_next(self):
        self.set_slots("2")
        first = self.start(self.wt)
        self.wait_for(os.path.join(self.wt, ".ci", "started"))
        first.kill()
        first.wait(timeout=BOUND)
        write(self.release, "go\n")
        self.wait_until(self.orphan_gone(os.path.join(self.wt, ".ci", "pid")))
        second = subprocess.run([sys.executable, RELAY, "gate"], cwd=self.wt, env=self.env, capture_output=True, text=True, timeout=BOUND)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertNotIn("waiting", second.stderr)
        self.assertEqual(self.runs(), 2)

    def license_wt2(self):
        """wt2 gets a [license] table and the license files; LICENSE itself is git-ignored, so deleting or restoring it
        on disk leaves the worktree clean (a tracked file changed would be refused as dirty before the license re-check),
        and so is .relay/checks/, so a green log can be put there without a commit that moves HEAD. Returns (head, log path)."""
        import relay_license
        kit = os.path.join(self.wt2, ".claude", "kit.toml")
        write(kit, read(kit) + '[license]\nid = "MIT"\nholder = "me"\n')
        write(os.path.join(self.wt2, ".gitignore"), read(os.path.join(self.wt2, ".gitignore")) + "LICENSE\n.relay/checks/\n")
        relay_license.add(self.wt2, "MIT", "me", 2026)
        git(self.wt2, "add", "-A")
        git(self.wt2, "commit", "-q", "-m", "license")
        head = git(self.wt2, "rev-parse", "HEAD")
        return head, os.path.join(self.wt2, ".relay", "checks", head + ".gate.log")

    def put_green_log(self, head, log):
        write(log, "head %s\ncmd %s\nwait 0.0\nexit 0\n" % (head, shlex.quote(self.script)))

    def test_a_license_deleted_during_the_wait_fails_the_gate_and_the_green_log_is_not_reused(self):
        """A holds the only slot; B (license good when it starts) waits. While B waits LICENSE is deleted and a green log
        for B's very head appears. By worked reasoning: the check in the slot sees LICENSE missing, so it must not take the
        log; B runs its command (2 runs: A and B) and, the license being broken, exits 1 with the failure in its log.
        Without the re-check B would reuse the log, exit 0 and run nothing."""
        head, log = self.license_wt2()
        first = self.start(self.wt)
        self.wait_for(os.path.join(self.wt, ".ci", "started"))
        second = self.start(self.wt2)
        self.assertEqual(self.line(second), WAITING)
        os.remove(os.path.join(self.wt2, "LICENSE"))
        self.put_green_log(head, log)
        write(self.release, "go\n")
        self.assertEqual(first.wait(timeout=BOUND), 0)
        self.assertEqual(second.wait(timeout=BOUND), 1)
        self.assertEqual(self.runs(), 2)
        text = read(os.path.join(self.wt2, ".relay", "checks", head + ".gate.log"))
        self.assertIn("license check FAILED", text)
        self.assertIn("LICENSE is missing", text)

    def test_a_license_fixed_during_the_wait_clears_the_failure(self):
        """B starts with LICENSE missing (the check outside the slot fails) and waits for A. While it waits LICENSE is
        restored and a green log for B's head appears. The check in the slot passes, so B reports that log: exit 0 and
        only A's run. Without the re-check B would keep the early failure, run its command and exit 1."""
        import relay_license
        head, log = self.license_wt2()
        os.remove(os.path.join(self.wt2, "LICENSE"))
        first = self.start(self.wt)
        self.wait_for(os.path.join(self.wt, ".ci", "started"))
        second = self.start(self.wt2)
        self.assertEqual(self.line(second), WAITING)
        write(os.path.join(self.wt2, "LICENSE"), relay_license.license_text("MIT", "me", 2026))
        self.put_green_log(head, log)
        write(self.release, "go\n")
        self.assertEqual(first.wait(timeout=BOUND), 0)
        self.assertEqual(second.wait(timeout=BOUND), 0)
        self.assertEqual(self.runs(), 1)        # only A ran

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
